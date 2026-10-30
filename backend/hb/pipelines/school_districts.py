"""school-districts pipeline — district polygons from NCES (docs/05 §12).

Pulls every school-district boundary polygon in the geography's state from the NCES TIGER
"School Districts - Current" ArcGIS layer (same org as the schools layer) and
bulk-upserts them into `school_districts`. Listing detail then assigns each
property its governing elementary/secondary/unified district by
point-in-polygon (hb.schools_match) instead of raw nearest-distance — the fix
for houses showing schools from the wrong district.

Composite semantics: unified areas carry a single polygon; elsewhere an
elementary district overlaps a secondary (high-school) district — `kind`
records which, derived from ELSDLEA/SCSDLEA/UNSDLEA. Daily-safe: content hash
over rows (geometry included) drives status=noop when unchanged (~annual TIGER
vintage bumps).
"""

import hashlib
import json
import logging

import httpx
from shapely.geometry import shape

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import SchoolDistrict
from hb.db.upsert import bulk_upsert
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

# NCES TIGER "School Districts - Current", layer 0 (polygon features).
DISTRICTS_URL = (
    "https://services1.arcgis.com/Ua5sjt3LWTPigjyD/arcgis/rest/services/"
    "School_Districts_Current/FeatureServer/0/query"
)
_FIELDS = ("GEOID,NAME,ELSDLEA,SCSDLEA,UNSDLEA,LOGRADE,HIGRADE,"
           "SDTYP,FUNCSTAT,SCHOOLYEAR")
_PAGE = 500  # polygon payloads are heavy; ~940 districts for California


def fetch_districts() -> list[dict]:
    """Page through the districts layer as GeoJSON for the geography's state;
    returns Feature dicts (properties + geometry). Seam: tests monkeypatch this."""
    where = f"STATEFP='{settings.geo.state_fips}'"
    out: list[dict] = []
    offset = 0
    while True:
        resp = httpx.get(DISTRICTS_URL, params={
            "where": where, "outFields": _FIELDS, "returnGeometry": "true",
            "outSR": 4326, "resultOffset": offset, "resultRecordCount": _PAGE,
            "orderByFields": "GEOID", "f": "geojson",
        }, timeout=120)
        resp.raise_for_status()
        j = resp.json()
        if "error" in j:
            raise RuntimeError(f"NCES ArcGIS error: {j['error']}")
        feats = j.get("features", [])
        out.extend(feats)
        # GeoJSON responses flag continuation inconsistently across ArcGIS
        # versions (top-level or properties.exceededTransferLimit) — a full
        # page means "maybe more" regardless of the flag.
        if len(feats) < _PAGE:
            break
        offset += len(feats)
    return out


def _to_row(feature: dict) -> dict | None:
    """One GeoJSON Feature -> a `school_districts` row, or None to skip
    (non-operational, pseudo-district, or missing id/name/geometry). NB: the
    layer pads empty attributes with a single space, so strip before testing."""
    p = feature.get("properties") or {}
    geom = feature.get("geometry")
    geoid = (str(p.get("GEOID") or "").strip())
    name = (p.get("NAME") or "").strip()
    if not (geoid and name and geom):
        return None
    if (str(p.get("FUNCSTAT") or "E").strip() or "E") != "E":  # not operational
        return None
    # A = grade-range pseudo-splits, B = DoD, C = interstate, D = BIE.
    # 'E' (duplicate-name flag) and blank are REAL districts — keep them.
    if (str(p.get("SDTYP") or "").strip()) in {"A", "B", "C", "D"}:
        return None
    if (p.get("ELSDLEA") or "").strip():
        kind = "elementary"
    elif (p.get("SCSDLEA") or "").strip():
        kind = "secondary"
    elif (p.get("UNSDLEA") or "").strip():
        kind = "unified"
    else:
        return None
    lon_min, lat_min, lon_max, lat_max = shape(geom).bounds
    return {
        "geoid": geoid,
        "name": name,
        "kind": kind,
        "lo_grade": (str(p.get("LOGRADE") or "").strip()) or None,
        "hi_grade": (str(p.get("HIGRADE") or "").strip()) or None,
        "geometry_json": json.dumps(geom, sort_keys=True),
        "bbox_lat_min": lat_min,
        "bbox_lat_max": lat_max,
        "bbox_lon_min": lon_min,
        "bbox_lon_max": lon_max,
        "school_year": (str(p.get("SCHOOLYEAR") or "").strip()) or None,
    }


def run(engine=None) -> str:
    with JobRunner("school-districts", engine) as runner:
        rows = [r for r in (_to_row(f) for f in fetch_districts()) if r]
        payload = json.dumps(sorted(rows, key=lambda r: r["geoid"]), sort_keys=True)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        runner.content_hash = digest
        if digest == runner.last_content_hash():
            runner.mark_noop()
        else:
            session = make_session(runner.engine)
            try:
                with runner.item(f"nces-{settings.geo.state.lower()}-districts"):
                    runner.items_upserted += bulk_upsert(
                        session, SchoolDistrict, rows, ["geoid"])
                    session.commit()
                    log.info("school-districts: upserted %d %s district polygons",
                             len(rows), settings.geo.state)
            finally:
                session.close()
    return runner.status
