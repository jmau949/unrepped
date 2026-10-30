"""Boundary-aware school assignment for listing detail (docs/05 §12).

Assigns one school per level (elementary/middle/high) to a property. The
governing district comes first: point-in-polygon against the NCES district
boundaries in `school_districts` (STRtree over parsed GeoJSON, cached at
process level and rebuilt only when the pipeline changes rows). Within that
district the nearest non-charter school of the level wins — elementary
districts can overlap secondary (high-school) districts, so each level resolves
its own district (unified covers all levels).

Fallback ladder, flagged per school via `assignment`:
  district -> polygon match + in-district school (the correct answer)
  nearest  -> no polygon match, or the district has no school of that level
              in the directory (charter-only, data gap): plain nearest within
              15 miles — the pre-boundary behavior
  zip      -> no usable coordinates: top-rated school in the property's ZIP
"""

import json
import logging

from shapely import STRtree
from shapely.geometry import Point, shape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hb import packs
from hb.db.models import School, SchoolDistrict, SchoolRatingSnapshot
from hb.geo import bbox, haversine_miles

log = logging.getLogger(__name__)

_LEVELS = ("elementary", "middle", "high")
_SEARCH_MILES = 15.0

# (cache_key, STRtree, district metas) — rebuilt when school_districts changes
_cache: tuple[tuple, STRtree, list[dict]] | None = None


def _district_index(session: Session) -> tuple[STRtree, list[dict]]:
    """Process-cached STRtree over all district polygons. Cache key is one
    cheap aggregate query; the ~1-2s GeoJSON parse only happens after the
    school-districts pipeline actually changed rows."""
    global _cache
    key = tuple(session.execute(
        select(func.count(SchoolDistrict.id), func.max(SchoolDistrict.updated_at))
    ).one())
    if _cache is not None and _cache[0] == key:
        return _cache[1], _cache[2]
    rows = session.execute(
        select(SchoolDistrict).order_by(SchoolDistrict.geoid)
    ).scalars().all()
    geoms, metas = [], []
    for d in rows:
        try:
            geoms.append(shape(json.loads(d.geometry_json)))
        except Exception:  # one bad polygon must not break every listing page
            log.warning("school_districts: unparseable geometry for %s (%s)",
                        d.geoid, d.name)
            continue
        metas.append({"geoid": d.geoid, "name": d.name, "kind": d.kind})
    tree = STRtree(geoms)
    _cache = (key, tree, metas)
    return tree, metas


def assigned_districts(session: Session, lat: float, lon: float) -> dict[str, dict]:
    """kind -> {geoid, name, kind} for every district polygon covering the
    point: one unified, or an overlapping elementary + secondary pair. First
    hit per kind wins (metas are geoid-ordered, so ties are deterministic)."""
    tree, metas = _district_index(session)
    hits: dict[str, dict] = {}
    for idx in tree.query(Point(lon, lat), predicate="covered_by"):
        meta = metas[int(idx)]
        hits.setdefault(meta["kind"], meta)
    return hits


def _governing(districts: dict[str, dict], level: str) -> dict | None:
    """The district that actually enrolls this level: elementary districts
    cover elementary+middle, secondary districts cover high, unified covers
    everything."""
    if level == "high":
        return districts.get("secondary") or districts.get("unified")
    return districts.get("elementary") or districts.get("unified")


def _row(school: School, level: str, distance_mi: float | None,
         assignment: str, district: str | None) -> dict:
    return {
        "name": school.name,
        "level": level,
        "rating": school.rating,
        "pct_met": school.pct_met,
        "distance_mi": distance_mi,
        "district": district,
        "assignment": assignment,
        "_school_id": school.id,  # stripped by _attach_ratings
    }


def _attach_ratings(session: Session, rows: list[dict]) -> list[dict]:
    """Replace each row's _school_id with its per-source ratings list in one
    query — the pack's rating sources first, in its order (primary source
    leads), then any other source alphabetically."""
    ids = [r["_school_id"] for r in rows]
    snaps = session.execute(
        select(SchoolRatingSnapshot).where(SchoolRatingSnapshot.school_id.in_(ids))
    ).scalars().all() if ids else []
    by_school: dict[str, list] = {}
    for s in snaps:
        by_school.setdefault(s.school_id, []).append(s)
    order = {src.key: i for i, src in enumerate(packs.current().rating_sources)}
    for r in rows:
        mine = sorted(by_school.get(r.pop("_school_id"), []),
                      key=lambda s: (order.get(s.source, len(order)), s.source))
        r["ratings"] = [{"source": s.source, "rating_10": s.rating_10,
                         "label": s.label} for s in mine]
    return rows


def schools_for_property(session: Session, lat: float | None, lon: float | None,
                         zip_code: str | None = None) -> list[dict]:
    """One school per level for a property, boundary-aware (see module doc).
    Empty only when neither coords nor ZIP yield a match."""
    if lat is not None and lon is not None:
        districts = assigned_districts(session, lat, lon)
        lat_min, lat_max, lon_min, lon_max = bbox(lat, lon, _SEARCH_MILES)
        near = session.execute(
            select(School).where(
                School.lat >= lat_min, School.lat <= lat_max,
                School.lon >= lon_min, School.lon <= lon_max,
            )
        ).scalars().all()
        out: list[dict] = []
        for level in _LEVELS:
            dist_mi = lambda s: haversine_miles(lat, lon, s.lat, s.lon)  # noqa: E731
            governing = _governing(districts, level)
            if governing:
                pool = session.execute(
                    select(School).where(
                        School.leaid == governing["geoid"],
                        School.level == level,
                        School.is_charter.is_(False),
                    )
                ).scalars().all()
                if pool:
                    pick = min(pool, key=dist_mi)
                    out.append(_row(pick, level, round(dist_mi(pick), 1),
                                    "district", governing["name"]))
                    continue
            pool = [s for s in near if s.level == level]
            if pool:
                pick = min(pool, key=dist_mi)
                out.append(_row(pick, level, round(dist_mi(pick), 1),
                                "nearest", pick.district))
        if out:
            return _attach_ratings(session, out)
    if zip_code:
        return _attach_ratings(session, _schools_by_zip(session, zip_code))
    return []


def _schools_by_zip(session: Session, zip_code: str) -> list[dict]:
    """Fallback for coordinate-less properties: top-rated school per level
    within the property's ZIP (distance unknown). Ranks by the best rating from
    any source's snapshot, then the CAASPP fast-path column, so it works in
    states where CAASPP never runs."""
    rows = session.execute(
        select(School, func.max(SchoolRatingSnapshot.rating_10))
        .outerjoin(SchoolRatingSnapshot, SchoolRatingSnapshot.school_id == School.id)
        .where(School.zip == zip_code)
        .group_by(School.id)
    ).all()

    def score(pair) -> float:
        school, snap_best = pair
        if snap_best is not None:
            return float(snap_best)
        return float(school.rating) if school.rating is not None else -1.0

    out: list[dict] = []
    for level in _LEVELS:
        pool = [p for p in rows if p[0].level == level]
        if not pool:
            continue
        best = max(pool, key=score)[0]
        out.append(_row(best, level, None, "zip", best.district))
    return out
