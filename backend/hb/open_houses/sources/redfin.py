"""Redfin open houses via its map-search (GIS) endpoint.

Redfin carries open houses Realtor's feed often lacks, so it runs alongside
the Realtor source. Its listing ids are its own, so each slot carries the MLS
number + ZIP and the pipeline matches it to the listing the scan stored.

The search is by polygon (the city's bbox from stored active homes), so no
Redfin region ids are needed. A response that hits the `num_homes` cap is
split into quadrants until every home is covered. Redfin answers plain HTTP
clients with 403, so requests go through curl_cffi's browser impersonation.
Redfin reports only each home's NEXT slot (epoch ms, UTC) and no event link.
"""

import json
import random
import time
from datetime import datetime, timezone

from hb.open_houses.sources.base import BBox, OpenHouseRecord

GIS_URL = "https://www.redfin.com/stingray/api/gis"
NUM_HOMES = 350  # Redfin's per-request cap
MAX_DEPTH = 4    # quadrant splits before giving up on a dense box
# active (status=1) single-family houses (uipt=1), matching listing-scan's scope.
# The paging/sort/sale-type params are what Redfin's own map sends: without
# them it ignores `poly` and answers with whatever region it snaps the box to.
BASE_PARAMS = {
    "al": 1, "status": 1, "uipt": 1, "num_homes": NUM_HOMES, "v": 8,
    "ord": "redfin-recommended-asc", "page_number": 1, "start": 0,
    "sf": "1,2,3,5,6,7", "mpt": 99,
}


def fetch_gis(params: dict) -> dict:
    """Seam for tests: one GIS search -> the decoded payload (`{}&&` stripped)."""
    from curl_cffi import requests

    time.sleep(random.uniform(2, 5))  # one request per city/quadrant; stay polite
    resp = requests.get(GIS_URL, params=params, impersonate="chrome", timeout=30)
    resp.raise_for_status()
    text = resp.text
    body = json.loads(text[text.index("&&") + 2:] if text.startswith("{}&&") else text)
    if body.get("resultCode") not in (0, None):
        raise RuntimeError(f"redfin gis error: {body.get('errorMessage')}")
    return body.get("payload") or {}


def _poly(bbox: BBox) -> str:
    w, s, e, n = bbox
    return ",".join(f"{lon} {lat}" for lon, lat in ((w, s), (e, s), (e, n), (w, n), (w, s)))


def _quadrants(bbox: BBox) -> list[BBox]:
    w, s, e, n = bbox
    mx, my = (w + e) / 2, (s + n) / 2
    return [(w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)]


def _homes(bbox: BBox, depth: int = 0) -> list[dict]:
    homes = fetch_gis({**BASE_PARAMS, "poly": _poly(bbox)}).get("homes") or []
    if len(homes) < NUM_HOMES or depth >= MAX_DEPTH:
        return homes
    out: list[dict] = []
    for quad in _quadrants(bbox):
        out.extend(_homes(quad, depth + 1))
    return out


def _value(v):
    """Redfin wraps most fields as {"value": ..., "level": ...}."""
    return v.get("value") if isinstance(v, dict) else v


def _utc(ms) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


class RedfinOpenHouses:
    name = "redfin"

    def fetch(self, city: str, bbox: BBox | None) -> list[OpenHouseRecord]:
        if bbox is None:
            return []
        records, seen = [], set()
        for home in _homes(bbox):
            start, end = home.get("openHouseStart"), home.get("openHouseEnd")
            mls_id = str(_value(home.get("mlsId")) or "").strip()
            if not start or not end or not mls_id:
                continue
            zip5 = str(_value(home.get("zip")) or _value(home.get("postalCode")) or "")[:5]
            key = (mls_id, zip5, start)
            if key in seen:  # quadrant edges can return a home twice
                continue
            seen.add(key)
            records.append(OpenHouseRecord(
                mls_id=mls_id,
                zip=zip5 or None,
                start_at=_utc(start),
                end_at=_utc(end),
                description=(home.get("openHouseEventName") or "").strip() or None,
                methods=["in_person"],
            ))
        return records
