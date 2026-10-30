"""Pipeline job registry. Jobs are plain callables taking an optional engine;
`hb pipeline <name>` dispatches through JOBS (docs/05-pipelines.md §2)."""

from collections.abc import Callable

from sqlalchemy.engine import Engine

from hb.pipelines.base import JobRunner

DAILY_SEQUENCE = ["redfin-market", "zillow-research", "fred", "build-index",
                  "market-supply", "hazards", "schools",
                  "school-districts", "schooldigger-ratings", "deal-deadlines"]


def _stub(job_name: str) -> Callable[[Engine | None], str]:
    """Placeholder for a registered job with no implementation — records a failed run."""

    def run(engine: Engine | None = None) -> str:
        with JobRunner(job_name, engine) as runner:
            raise NotImplementedError(f"pipeline '{job_name}' has no implementation")
        return runner.status

    return run


from hb.pipelines import (  # noqa: E402
    build_index, fred, market_supply, redfin_market, zillow_research,
)

JOBS: dict[str, Callable[[Engine | None], str]] = {
    name: _stub(name) for name in DAILY_SEQUENCE
}
from hb.pipelines import (  # noqa: E402
    backfill_sales, deal_deadlines, enrich, hazards, hazards_fetch, listing_scan, open_houses,
    price_history, sale_history, school_districts, school_ratings, schooldigger,
    schools,
)

JOBS["redfin-market"] = redfin_market.run
JOBS["zillow-research"] = zillow_research.run
JOBS["fred"] = fred.run
JOBS["build-index"] = build_index.run
# Live months-of-supply now-cast from our own listings/sales. Daily-safe: it
# rewrites only today's rows, one series per trailing window.
JOBS["market-supply"] = market_supply.run
JOBS["listing-scan"] = listing_scan.run
# Realtor open-house slots — listing-scan runs it in its own tail (slots attach
# to the listings the scan just stored); this entry is the standalone rerun.
JOBS["open-houses"] = open_houses.run


def _enrich_all_tracked(engine: Engine | None = None) -> str:
    """Registry entry: bare enrich.run() defaults to a silent no-op — the
    registry/scheduler path must mean 'enrich all tracked'."""
    return enrich.run(engine, all_tracked=True)


JOBS["enrich"] = _enrich_all_tracked
JOBS["backfill-sales"] = backfill_sales.run
JOBS["hazards"] = hazards.run  # daily-safe: hash-noop on unchanged polygon files
# Downloads the pack's hazard polygon layers — standalone, run once (and after a
# state re-releases zones); NOT in DAILY_SEQUENCE
JOBS["hazards-fetch"] = hazards_fetch.run
JOBS["schools"] = schools.run  # NCES directory; daily-safe via hash-noop
JOBS["school-districts"] = school_districts.run  # NCES polygons; daily-safe via hash-noop
# CAASPP test-score ratings — standalone (annual data, ~157MB), not in DAILY_SEQUENCE
JOBS["school-ratings"] = school_ratings.run
# SchoolDigger CA rankings — daily-safe by design: day-capped budget guard,
# per-district progress, noop when every assigned district is freshly rated
JOBS["schooldigger-ratings"] = schooldigger.run
# Contingency/closing deadline alerts over open deals. Daily-safe: pure DB read,
# no network, dedup_key carries the due date and bucket (docs/05 §15).
JOBS["deal-deadlines"] = deal_deadlines.run
# Realtor price-history backfill — standalone; the daily scan refreshes touched props
JOBS["price-history"] = price_history.run
# Replay cached Realtor timelines onto sales (price cuts, true original list,
# DOM/CDOM the scan was too young to observe). Pure derivation, no network;
# `price-history` runs it in its own tail, this entry is the standalone rerun.
JOBS["derive-sales-history"] = sale_history.run


def run_job(name: str, engine: Engine | None = None) -> str:
    if name not in JOBS:
        raise KeyError(f"unknown pipeline job: {name} (known: {', '.join(sorted(JOBS))})")
    return JOBS[name](engine)


def run_daily(engine: Engine | None = None) -> dict[str, str]:
    """The `DAILY_TIMES` meta-job (default 04:00): the bulk pipelines in order
    (docs/05-pipelines.md §2)."""
    return {name: run_job(name, engine) for name in DAILY_SEQUENCE}
