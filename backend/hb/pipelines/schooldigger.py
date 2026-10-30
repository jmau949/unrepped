"""schooldigger-ratings pipeline — SchoolDigger statewide rankings (docs/05 §13).

An independent rating source (next to the CAASPP decile in California): the
SchoolDigger statewide ranking for the geography's state, fetched from their sanctioned API
(v2.4, appID+appKey — free developer plan at developer.schooldigger.com) and
upserted into `school_rating_snapshots` with source='schooldigger'.
`rankStatewidePercentage` is "ranks above X% of the state's schools" (higher = better,
verified against live data + rankStars), normalized onto the same 1-10 badge
scale the UI uses (top decile => 10).

The free plan allows only **20 calls/day** (x-dayrate-limit headers), so the
job is built to converge across runs rather than finish in one: it targets
only the districts actually assigned to properties in the DB (point-in-polygon
via hb.schools_match, ~20 districts, 1-3 calls each — /v2.4/schools has no
county filter; unknown params are silently ignored), keeps per-district
progress in `settings` key "schooldigger_progress", and stops cleanly when the
day's budget (settings.schooldigger_daily_limit) runs out or the API 429s —
rerun on following days until every district is rated. In DAILY_SEQUENCE:
daily-safe because rated districts noop for _REFRESH_DAYS, so a converged
state spends zero calls. Missing credentials => clean noop, never a failure.
Matching is by NCES school id (SchoolDigger school ids are NCES ids) with
(zip, normalized name) fallback.
"""

import logging
from datetime import date

import httpx
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.orm import Session

from hb import schools_match
from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import AppSetting, Property, School, SchoolRatingSnapshot, utcnow_iso
from hb.db.upsert import upsert
from hb.pipelines.base import JobRunner
from hb.pipelines.school_ratings import _norm

log = logging.getLogger(__name__)

API_URL = "https://api.schooldigger.com/v2.4/schools"
_PER_PAGE = 50
_REFRESH_DAYS = 180  # rankings are annual; re-fetch a done district after this


# --- call budget guard (RentCast pattern, but DAY-scoped: 20 calls/day) ------

def _budget_state(session: Session) -> tuple[AppSetting | None, dict]:
    row = session.get(AppSetting, "schooldigger_budget")
    today = date.today().isoformat()
    val = dict(row.value) if row and row.value else {}
    if val.get("day") != today:  # roll over at day boundary
        val = {"day": today, "calls": 0}
    return row, val


def remaining(session: Session) -> int:
    _, val = _budget_state(session)
    return max(0, settings.schooldigger_daily_limit - val.get("calls", 0))


def _spend(session: Session) -> None:
    row, val = _budget_state(session)
    val["calls"] = val.get("calls", 0) + 1
    if row is None:
        session.add(AppSetting(key="schooldigger_budget", value=val))
    else:
        row.value = val
        row.updated_at = utcnow_iso()


# --- per-district progress ---------------------------------------------------

def _progress(session: Session) -> tuple[AppSetting | None, dict]:
    """geoid -> ISO date of last successful full fetch of that district."""
    row = session.get(AppSetting, "schooldigger_progress")
    return row, dict(row.value) if row and row.value else {}


def _mark_done(session: Session, geoid: str) -> None:
    row, val = _progress(session)
    val[geoid] = date.today().isoformat()
    if row is None:
        session.add(AppSetting(key="schooldigger_progress", value=val))
    else:
        row.value = val
        row.updated_at = utcnow_iso()


def target_districts(session: Session) -> list[str]:
    """Geoids of every district assigned to a property in the DB (the only
    districts whose schools the matcher can surface), stalest-fetched first.
    One vectorized STRtree pass — 13k properties x 938 TIGER polygons is far
    too slow point-by-point."""
    props = session.execute(
        select(Property.lat, Property.lon).where(
            Property.lat.is_not(None), Property.lon.is_not(None))
    ).all()
    geoids: set[str] = set()
    if props:
        tree, metas = schools_match._district_index(session)
        points = [Point(lon, lat) for lat, lon in props]
        hits = tree.query(points, predicate="covered_by")  # (2, n): point, poly
        geoids = {metas[int(t)]["geoid"] for t in hits[1]}
    _, prog = _progress(session)
    return sorted(geoids, key=lambda g: (prog.get(g, ""), g))


# --- fetch -------------------------------------------------------------------

def fetch_district_page(district_id: str, page: int) -> dict:
    """One page of a district's schools. Seam: tests monkeypatch this.
    Raises httpx.HTTPStatusError on 429 (daily API cap) — caller stops."""
    resp = httpx.get(API_URL, params={
        "st": settings.geo.state, "districtID": district_id,
        "page": page, "perPage": _PER_PAGE,
        "appID": settings.schooldigger_app_id,
        "appKey": settings.schooldigger_app_key,
    }, timeout=60)
    resp.raise_for_status()
    return resp.json()


# --- normalize + apply -------------------------------------------------------

def _to_snap(rec: dict) -> dict | None:
    """One SchoolDigger record -> snapshot values (+ match keys), or None when
    the school carries no ranking (new/alt/unranked)."""
    ranks = rec.get("rankHistory") or []
    if not ranks:
        return None
    r = ranks[0]  # newest first per API docs
    rank, rank_of = r.get("rank"), r.get("rankOf")
    pctile = r.get("rankStatewidePercentage")  # ranks above X% statewide (high=good)
    if pctile is None and rank and rank_of:
        pctile = 100.0 * (1.0 - float(rank) / float(rank_of))
    if pctile is None:
        return None
    rating = max(1, min(10, round(float(pctile) / 10.0)))
    addr = rec.get("address") or {}
    return {
        "nces_id": str(rec.get("schoolid") or "").strip(),
        "zip": (str(addr.get("zip") or "").strip())[:5],
        "name": rec.get("schoolName") or "",
        "rating_10": float(rating),
        "label": (f"#{rank} of {rank_of} in {settings.geo.state}" if rank and rank_of else
                  f"top {100 - float(pctile):.0f}% in {settings.geo.state}"),
        "detail": {"rank": rank, "rank_of": rank_of,
                   "pct_ranked_above": pctile, "stars": r.get("rankStars")},
        "as_of": str(r.get("year") or ""),
    }


def _apply(session: Session, records: list[dict]) -> int:
    """Upsert source='schooldigger' snapshots onto matching `schools` rows."""
    schools = session.execute(select(School)).scalars().all()
    by_nces = {s.nces_id: s for s in schools}
    by_zip_name = {(s.zip, _norm(s.name)): s for s in schools}
    matched = 0
    for rec in records:
        snap = _to_snap(rec)
        if snap is None:
            continue
        sc = by_nces.get(snap["nces_id"]) or by_zip_name.get(
            (snap["zip"], _norm(snap["name"])))
        if sc is None:
            continue
        upsert(session, SchoolRatingSnapshot, {
            "school_id": sc.id, "source": "schooldigger",
            "rating_10": snap["rating_10"], "label": snap["label"],
            "detail": snap["detail"], "as_of": snap["as_of"],
        }, ["school_id", "source"])
        matched += 1
    return matched


def run(engine=None) -> str:
    with JobRunner("schooldigger-ratings", engine) as runner:
        if not (settings.schooldigger_app_id and settings.schooldigger_app_key):
            log.info("schooldigger-ratings: no API credentials — skipping "
                     "(set SCHOOLDIGGER_APP_ID / SCHOOLDIGGER_APP_KEY)")
            runner.mark_noop()  # status finalized by __exit__; return AFTER the with-block
        else:
            # a mis-set state burns the 20-calls/day quota on empty results — say which
            log.info("schooldigger-ratings: state=%s", settings.geo.state)
            _run_with_credentials(runner)
    return runner.status


def _run_with_credentials(runner: JobRunner) -> None:
    session = make_session(runner.engine)
    try:
        _, prog = _progress(session)
        cutoff = date.today().toordinal() - _REFRESH_DAYS
        todo = [g for g in target_districts(session)
                if (d := prog.get(g)) is None
                or date.fromisoformat(d).toordinal() < cutoff]
        if not todo:
            runner.mark_noop()  # every assigned district freshly rated
        else:
            done = 0
            capped = False
            for geoid in todo:
                if remaining(session) <= 0:
                    capped = True
                    break
                with runner.item(geoid):
                    records: list[dict] = []
                    page = 1
                    try:
                        while True:
                            if remaining(session) <= 0:
                                capped = True
                                break
                            _spend(session)
                            j = fetch_district_page(geoid, page)
                            records.extend(j.get("schoolList") or [])
                            if page >= int(j.get("numberOfPages") or 1):
                                break
                            page += 1
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 429:
                            raise
                        capped = True  # API day-cap hit before our guard did
                    if records and not capped:
                        runner.items_upserted += _apply(session, records)
                        _mark_done(session, geoid)
                        done += 1
                    session.commit()
                if capped:
                    break
            session.commit()
            if capped:
                log.info(
                    "schooldigger-ratings: daily call budget reached — %d/%d "
                    "districts rated this run; rerun tomorrow for the rest",
                    done, len(todo))
                if done == 0:
                    runner.mark_noop()  # nothing fetched today; not a failure
    finally:
        session.close()
