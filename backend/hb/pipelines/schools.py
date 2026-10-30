"""schools pipeline — public schools from NCES (docs/05-pipelines.md §9).

Pulls every public school in the geography's state (name, level, lat/lon,
district) from the
NCES Common Core of Data "School Characteristics" ArcGIS layer and bulk-upserts
the elementary/middle/high schools into `schools`. Listing detail then surfaces
the nearest school per level by lat/lon — real, free, no-key data covering every
listing, with no per-listing fetch.

The NCES ArcGIS REST API is built for programmatic access (unlike the CDE web
export, which is behind bot management), so it's reliable from a server. Daily-
safe: a content hash of the fetched rows drives status=noop when unchanged.
`rating` is left NULL here (a future CAASPP-derived pass fills it); on-conflict
updates never clobber an existing rating.
"""

import hashlib
import json
import logging

import httpx

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import School
from hb.db.upsert import bulk_upsert
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

# NCES CCD "School Characteristics - Current", layer 1 (point features).
ARCGIS_URL = (
    "https://services1.arcgis.com/Ua5sjt3LWTPigjyD/arcgis/rest/services/"
    "School_Characteristics_Current/FeatureServer/1/query"
)
_FIELDS = ("NCESSCH,SCH_NAME,SCHOOL_LEVEL,LEA_NAME,LEAID,CHARTER_TEXT,"
           "NMCNTY,LZIP,LATCOD,LONCOD,SY_STATUS_TEXT")
_PAGE = 2000
_LEVEL = {"Elementary": "elementary", "Middle": "middle", "High": "high"}


def fetch_schools() -> list[dict]:
    """Page through the NCES ArcGIS layer for every school in the geography's
    state; returns raw attribute dicts. Seam: tests monkeypatch this."""
    where = f"LSTATE='{settings.geo.state}'"
    out: list[dict] = []
    offset = 0
    while True:
        resp = httpx.get(ARCGIS_URL, params={
            "where": where, "outFields": _FIELDS, "returnGeometry": "false",
            "resultOffset": offset, "resultRecordCount": _PAGE,
            "orderByFields": "NCESSCH", "f": "json",
        }, timeout=60)
        resp.raise_for_status()
        j = resp.json()
        if "error" in j:
            raise RuntimeError(f"NCES ArcGIS error: {j['error']}")
        feats = j.get("features", [])
        out.extend(f["attributes"] for f in feats)
        if not feats or not j.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return out


def _to_row(a: dict) -> dict | None:
    """One NCES attribute dict -> a `schools` row, or None to skip (non-mapped
    level, closed, or missing name/id/coordinates)."""
    level = _LEVEL.get(a.get("SCHOOL_LEVEL"))
    if not level:
        return None
    status = a.get("SY_STATUS_TEXT") or ""
    if "Closed" in status or "Inactive" in status:
        return None
    lat, lon = a.get("LATCOD"), a.get("LONCOD")
    name = (a.get("SCH_NAME") or "").strip()
    nces = (a.get("NCESSCH") or "").strip()
    if not (name and nces and isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and lat and lon):
        return None
    return {
        "nces_id": nces,
        "name": name,
        "level": level,
        "lat": float(lat),
        "lon": float(lon),
        "district": (a.get("LEA_NAME") or "").strip() or None,
        "leaid": (str(a.get("LEAID") or "").strip()) or None,
        "is_charter": (a.get("CHARTER_TEXT") or "").strip() == "Yes",
        "county": (a.get("NMCNTY") or "").strip() or None,
        "zip": (str(a.get("LZIP") or "").strip())[:5] or None,
    }


def run(engine=None) -> str:
    with JobRunner("schools", engine) as runner:
        rows = [r for r in (_to_row(a) for a in fetch_schools()) if r]
        payload = json.dumps(sorted(rows, key=lambda r: r["nces_id"]), sort_keys=True)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        runner.content_hash = digest
        if digest == runner.last_content_hash():
            runner.mark_noop()  # status finalized by __exit__; return AFTER the with-block
        else:
            session = make_session(runner.engine)
            try:
                with runner.item(f"nces-{settings.geo.state.lower()}"):
                    runner.items_upserted += bulk_upsert(session, School, rows, ["nces_id"])
                    session.commit()
                    log.info("schools: upserted %d %s public schools", len(rows), settings.geo.state)
            finally:
                session.close()
    return runner.status
