"""sale-history derivation — reconstruct pre-observation listing history onto sales.

The daily scan only sees what happens after it started running, so every sale
backfilled by `backfill-sales` (or scraped as a closed record) carries
`had_price_cut=False`, a final-list-price proxy for `original_list_price`, and a
NULL `cumulative_dom`. That silently biases the overbid model: docs/06 §5.2
splits comps into fresh vs stale on exactly those fields, and the fresh
distribution carries 0.8 of the blended prediction weight (docs/06 §5.4).

`properties.price_history` (fetched by `price-history` from Realtor's
`property_history` node) already holds the real Sold / Listed / Price-changed
timeline. This module replays that timeline per sale and fills in what the scan
could not have observed.

Campaign semantics mirror `relist.py`: consecutive listing episodes separated by
less than `RELIST_GAP_DAYS` are ONE marketing campaign, so `original_list_price`
is the first list price of the campaign (not of the final episode) — a seller who
delists and relists lower has still cut, and docs/01 §3 requires SP/LP against
the original.

Write policy (this data is reconstructed, the scan's is observed):
- `had_price_cut` is only ever set False -> True; an observed cut is never erased.
- `original_list_price` is only ever raised, never lowered — a stored value below
  the derived original means we began observing mid-campaign, after a cut.
- `dom` / `cumulative_dom` fill NULLs only.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.db.engine import make_session
from hb.db.models import Property, Sale
from hb.pipelines.base import JobRunner
from hb.pipelines.relist import RELIST_GAP_DAYS

log = logging.getLogger(__name__)


# --- event classification ----------------------------------------------------
# Realtor `event_name` values seen in the wild: "Sold", "Listed for sale",
# "Price Changed", "Listing Removed", "Pending", "Off Market", "Relisted", plus
# rental variants we ignore outright.

def _kind(event: dict) -> str | None:
    name = str(event.get("event") or "").lower()
    if "rent" in name:
        return None  # rental episodes never inform a sale price
    if "sold" in name:
        return "end"
    if "listed" in name or "relist" in name:
        return "list"
    if "price" in name:
        return "price"
    # anything that takes the home off the open market ends the episode's
    # exposure — same set relist._episode_end uses (sold | pending | delisted)
    if ("removed" in name or "off market" in name or "delist" in name
            or "pending" in name or "conting" in name):
        return "end"
    return None


def _d(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _episodes(events: list[dict]) -> list[list[dict]]:
    """Ascending events -> episodes, each starting at a `list` event."""
    eps: list[list[dict]] = []
    for event in events:
        if _kind(event) == "list":
            eps.append([event])
        elif eps:
            eps[-1].append(event)
    return eps


def _episode_end(episode: list[dict]) -> date | None:
    """When the episode stopped being exposed to the market. A price change does
    not end an episode — only an `end` event does. None means it ran straight to
    the sale (the caller substitutes the sale date)."""
    for event in reversed(episode):
        if _kind(event) == "end":
            return _d(event["date"])
    return None


def _campaign(episodes: list[list[dict]]) -> list[list[dict]]:
    """The final marketing campaign: trailing episodes chained by gaps shorter
    than RELIST_GAP_DAYS (same rule as relist._cluster)."""
    clusters: list[list[list[dict]]] = []
    for episode in episodes:
        start = _d(episode[0]["date"])
        if clusters and start is not None:
            prev_end = _episode_end(clusters[-1][-1])
            if prev_end is not None and 0 <= (start - prev_end).days < RELIST_GAP_DAYS:
                clusters[-1].append(episode)
                continue
        clusters.append([episode])
    return clusters[-1] if clusters else []


def derive(history: list[dict], sale_date: str,
           prev_sale_date: str | None = None) -> dict | None:
    """Replay a property's Realtor timeline for the campaign that ended in the
    sale on `sale_date`. Returns
    ``{original_list_price, had_price_cut, dom, cumulative_dom, episode_count}``
    or None when the window holds no usable listing episode.

    `prev_sale_date` bounds the window so an earlier ownership cycle can never
    leak into this sale's campaign.
    """
    sale_dt = _d(sale_date)
    if sale_dt is None:
        return None
    prev_dt = _d(prev_sale_date) if prev_sale_date else None

    window = []
    for event in history or []:
        event_dt = _d(event.get("date"))
        if event_dt is None or _kind(event) is None:
            continue
        if event_dt >= sale_dt:
            continue  # the sale itself, and anything after it
        if prev_dt is not None and event_dt <= prev_dt:
            continue
        window.append(event)
    window.sort(key=lambda e: str(e["date"])[:10])

    campaign = _campaign(_episodes(window))
    if not campaign:
        return None

    priced = [
        int(e["price"]) for ep in campaign for e in ep
        if e.get("price") and _kind(e) in ("list", "price")
    ]
    original = priced[0] if priced else None
    had_cut = any(nxt < cur for cur, nxt in zip(priced, priced[1:]))

    def _span(episode: list[dict]) -> int:
        start = _d(episode[0]["date"])
        if start is None:
            return 0
        end = min(_episode_end(episode) or sale_dt, sale_dt)
        return max(0, (end - start).days)

    return {
        "original_list_price": original,
        "had_price_cut": had_cut,
        "dom": _span(campaign[-1]),          # public DOM: the final episode only
        "cumulative_dom": sum(_span(ep) for ep in campaign),
        "episode_count": len(campaign),
    }


# --- application -------------------------------------------------------------

def apply_to_property(session: Session, prop: Property) -> int:
    """Derive and apply history onto every sale of one property. Returns the
    number of sales changed."""
    history = prop.price_history or []
    if not history:
        return 0

    sales = session.execute(
        select(Sale).where(Sale.property_id == prop.id).order_by(Sale.sale_date)
    ).scalars().all()

    changed = 0
    prev_sale_date = None
    for sale in sales:
        derived = derive(history, sale.sale_date, prev_sale_date)
        prev_sale_date = sale.sale_date
        if derived is None:
            continue
        touched = False

        # never erase an observed cut; only add one the scan could not have seen
        if derived["had_price_cut"] and not sale.had_price_cut:
            sale.had_price_cut = True
            touched = True

        # only ever raise the original — a lower stored value means we started
        # observing mid-campaign, after a cut
        original = derived["original_list_price"]
        if original and (sale.original_list_price is None
                         or original > sale.original_list_price):
            sale.original_list_price = original
            sale.sp_lp = round(sale.sale_price / original, 4)
            touched = True

        if sale.dom is None and derived["dom"] is not None:
            sale.dom = derived["dom"]
            touched = True
        if sale.cumulative_dom is None and derived["cumulative_dom"] is not None:
            sale.cumulative_dom = derived["cumulative_dom"]
            touched = True

        changed += touched
    return changed


def apply_all(session: Session, property_ids=None) -> int:
    """Apply derivation across properties that have a cached price history
    (all of them when `property_ids` is None). Returns sales changed."""
    query = select(Property).where(Property.price_history.is_not(None))
    if property_ids is not None:
        ids = list(property_ids)
        if not ids:
            return 0
        query = query.where(Property.id.in_(ids))

    changed = 0
    for prop in session.execute(query).scalars().all():
        try:
            changed += apply_to_property(session, prop)
        except Exception as exc:  # noqa: BLE001 — one property never aborts the batch
            log.warning("sale-history derive failed for %s: %s", prop.id, exc)
    session.commit()
    return changed


def run(engine=None) -> str:
    """`hb pipeline derive-sales-history` — replay cached Realtor timelines onto
    sales. Pure derivation, no network; safe to re-run (idempotent by the
    monotone write policy above)."""
    with JobRunner("derive-sales-history", engine) as runner:
        session = make_session(runner.engine)
        try:
            with runner.item("sales"):
                runner.items_upserted = apply_all(session)
        finally:
            session.close()
    return runner.status
