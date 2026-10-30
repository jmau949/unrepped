"""fred pipeline — docs/05-pipelines.md §3.3. Mortgage rates + the metro Case-Shiller index."""

import logging

import httpx
from sqlalchemy import func, select

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import RateSnapshot
from hb.db.upsert import upsert
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

BASE = "https://api.stlouisfed.org/fred/series/observations"


# FRED series id -> stored series name (docs/04 rate_snapshots). The metro's
# Case-Shiller index is optional and named in the geography file.
def series() -> dict[str, str]:
    out = {"MORTGAGE30US": "MORTGAGE30US", "MORTGAGE15US": "MORTGAGE15US"}
    case_shiller = settings.geo.market.case_shiller_fred_id
    if case_shiller:
        out[case_shiller] = "CASESHILLER"
    return out


def fetch_observations(series_id: str, since: str | None) -> list[dict]:
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
    }
    if since:
        params["observation_start"] = since
    resp = httpx.get(BASE, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()["observations"]


def run(engine=None) -> str:
    with JobRunner("fred", engine) as runner:
        if not settings.fred_api_key:
            # optional key: affordability and offer math fall back to a 6.5% rate
            log.info("fred: no API key — skipping (free key at "
                     "https://fred.stlouisfed.org/docs/api/api_key.html; set FRED_API_KEY)")
            runner.mark_noop()  # status finalized by __exit__; return AFTER the with-block
        else:
            _fetch(runner)
    return runner.status


def _fetch(runner: JobRunner) -> None:
    session = make_session(runner.engine)
    try:
        for fred_id, stored_name in series().items():
            with runner.item(fred_id):
                last = session.execute(
                    select(func.max(RateSnapshot.date)).where(
                        RateSnapshot.series == stored_name
                    )
                ).scalar_one_or_none()
                # re-fetch a 90-day tail: FRED revises recent observations
                since = None
                if last:
                    import datetime as dt

                    since = (
                        dt.date.fromisoformat(last) - dt.timedelta(days=90)
                    ).isoformat()

                for obs in fetch_observations(fred_id, since):
                    if obs["value"] == ".":  # FRED's missing-value placeholder
                        continue
                    _, changed = upsert(
                        session,
                        RateSnapshot,
                        {
                            "date": obs["date"],
                            "series": stored_name,
                            "value": float(obs["value"]),
                        },
                        ["date", "series"],
                    )
                    if changed:
                        runner.items_upserted += 1
                session.commit()
    finally:
        session.close()
