"""backfill-sales — one-time (or occasional) historical comp backfill.

The daily `listing-scan` only pulls `sold` records from the last 30 days, so a
fresh install has no deep sales history — and the golden backtest (docs/10 §4)
needs comps that closed *before* each list date. This job pulls a wide date
range of closed single-family sales via HomeHarvest (`date_from`/`date_to`) and
upserts them straight into `sales`.

It is comp-only by design: it resolves properties and writes `sales` rows but
creates **no** `listings`, `listing_events`, or alerts — a backfill of
years-old solds must not spam the timeline or the alert inbox.

Backfill is a GAP-FILLER, never an updater: rows that already exist on the
`(property_id, sale_date)` key are skipped untouched. The daily scan's
event-derived truth (`had_price_cut`, pre-cut `original_list_price`, sp_lp vs
the original) is strictly richer than what a historical sold record exposes —
overwriting it corrupted the overbid fresh/stale split.

Not on the daily schedule. Run once after install:
    hb pipeline backfill-sales --months 24
"""

import logging
import random
import time
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import Sale
from hb.db.upsert import upsert
from hb.pipelines.base import JobRunner
from hb.pipelines.listing_scan import _date_part, _resolve_record, _source_listing_id, _val
from hb.pipelines.resolve import resolve

log = logging.getLogger(__name__)


def fetch_sold(city: str, date_from: str, date_to: str) -> pd.DataFrame:
    """Seam for tests. Closed single-family sales in a date window."""
    from homeharvest import scrape_property

    return scrape_property(
        location=f"{city}, {settings.geo.state}", listing_type="sold",
        property_type=["single_family"],
        date_from=date_from, date_to=date_to,
    )


def _months_ago(today: date, n: int) -> date:
    total = today.year * 12 + (today.month - 1) - n
    y, m = divmod(total, 12)
    return date(y, m + 1, 1)


def process_sold(session: Session, row: dict) -> bool:
    """Upsert one closed sale as a comp. Returns True if a row was written/changed."""
    zip5 = str(_val(row, "zip_code") or "")
    sold_price = _val(row, "sold_price") or _val(row, "last_sold_price")
    sale_date = _date_part(_val(row, "last_sold_date")) or _date_part(_val(row, "sold_date"))
    if not zip5 or not sold_price or not sale_date:
        return False

    record = _resolve_record(row)
    property_id, _ = resolve(session, record, "realtor",
                             str(_val(row, "property_id") or _source_listing_id(row) or ""))

    # gap-filler contract: never touch a sale the scan already recorded
    existing = session.execute(
        select(Sale.id).where(Sale.property_id == property_id, Sale.sale_date == sale_date)
    ).scalar_one_or_none()
    if existing is not None:
        return False

    sold_price = int(sold_price)
    list_price = _val(row, "list_price")
    list_price = int(list_price) if list_price is not None else None
    # historical solds expose only the final list price — use it as the
    # original-list proxy (we never saw the pre-cut price for old episodes).
    original = list_price
    _, changed = upsert(
        session, Sale,
        {
            "property_id": property_id,
            "sale_date": sale_date,
            "sale_price": sold_price,
            "list_price_at_sale": list_price,
            "original_list_price": original,
            "sp_lp": round(sold_price / original, 4) if original else None,
            "dom": int(_val(row, "days_on_mls")) if _val(row, "days_on_mls") is not None else None,
            "had_price_cut": False,  # unknown for backfilled history -> treated as fresh
            "source": "realtor_sold_scan",
        },
        ["property_id", "sale_date"],
    )
    return changed


def run(engine=None, months: int = 24, date_from: str | None = None,
        date_to: str | None = None) -> str:
    today = date.today()
    date_from = date_from or _months_ago(today, months).isoformat()
    date_to = date_to or today.isoformat()
    with JobRunner("backfill-sales", engine) as runner:
        session = make_session(runner.engine)
        try:
            rows_seen = 0
            for city in settings.target_cities:
                with runner.item(city):
                    df = fetch_sold(city, date_from, date_to)
                    for _, row in df.iterrows():
                        rows_seen += 1
                        if process_sold(session, row.to_dict()):
                            runner.items_upserted += 1
                    session.commit()
                time.sleep(random.uniform(2, 5))  # polite between cities
            log.info("backfill-sales %s..%s: %d rows seen, %d sales upserted",
                     date_from, date_to, rows_seen, runner.items_upserted)
        finally:
            session.close()
    return runner.status
