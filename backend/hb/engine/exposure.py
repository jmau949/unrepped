"""Market exposure — how long, and at what price, a listing has been tested (docs/06 §5.6).

One extractor for every consumer (overbid routing, the posture classifier, the
market-evidence adjustment, the listings `stale_only` filter, the brief) and one
code path for live and as-of: `as_of` defaults to today and every span is
computed from the listing group's episode rows, so a backtest replay and the
served page agree on a quiet listing and a later episode can never leak into an
earlier as-of (summing every episode of the *property* let an old sale campaign
inflate the as-of cumulative DOM, and `group.episode_count` saw the future).

The clock that matters for "has THIS asking price been tested" is the current
episode's: a relist at a new price is a new price test (relists ≤1× the area
median into their new episode sold below list only 17% of the time), so `ratio`
uses `episode_days` for a relisted home and cumulative `days` otherwise.
`had_cut` is the comp definition (`sales.had_price_cut`): an observed downward
`price_change`, a dated "Price Changed" entry in Realtor's `price_history` for
the current episode (cuts that pre-date our first observation), or an episode
that opened below the previous one's final ask.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.db.models import Listing, ListingEvent, MarketMetric, Property
from hb.pipelines.relist import _episode_end
from hb.pipelines.sale_history import _d, _kind

OFFER_PASSED_GRACE_DAYS = 2  # published offer dates slip a day or two routinely


@dataclass
class Exposure:
    days: int | None          # cumulative over the group's episodes with list_date <= as_of
    episode_days: int | None  # days into the current episode
    episode_count: int        # episodes with list_date <= as_of
    relisted: bool            # episode_count > 1
    had_cut: bool             # see module docstring
    cuts: int                 # observed downward price_change events (display)
    cut_source: str | None    # observed | history | relist_lower | None
    median_dom: float | None  # area median DOM (Redfin city series)
    ratio: float | None       # clock / median_dom; clock = episode_days if relisted else days
    offer_passed: bool        # live-only: offer_due_at + grace elapsed, still active


def area_median_dom(session: Session, as_of: str | None = None,
                    cache: dict | None = None) -> float | None:
    """Median of the trailing city-level median-DOM series. The answer depends
    only on `as_of`, but a 250-row page consults it per listing — memoized on
    the page cache; `None` is a real answer (no metrics yet), hence the
    membership check rather than a falsy one."""
    key = ("area_median_dom", as_of)
    if cache is not None and key in cache:
        return cache[key]
    stmt = (
        select(MarketMetric.value)
        .where(MarketMetric.geo_type == "city", MarketMetric.metric == "median_dom",
               MarketMetric.source == "redfin")
        .order_by(MarketMetric.period_start.desc())
        .limit(24)
    )
    if as_of:
        stmt = stmt.where(MarketMetric.period_start <= as_of)
    rows = sorted(session.execute(stmt).scalars().all())
    value = rows[len(rows) // 2] if rows else None
    if cache is not None:
        cache[key] = value
    return value


def price_cut_count(session: Session, listing_id: str, upper: str | None = None) -> int:
    """Downward `price_change` events on this listing; with `upper` only events
    observed before it count (as-of discipline — a replay must not see the
    future)."""
    stmt = select(ListingEvent).where(
        ListingEvent.listing_id == listing_id,
        ListingEvent.event_type == "price_change",
    )
    if upper:
        stmt = stmt.where(ListingEvent.observed_at < upper)
    events = session.execute(stmt).scalars().all()
    return sum(1 for e in events
               if e.old_value and e.new_value and int(e.new_value) < int(e.old_value))


def _episodes(session: Session, listing: Listing, cache: dict | None) -> list[Listing]:
    """All of the listing's group members ordered by list_date (just the
    listing when it has no group); `_prior_episodes` trims them to the ones
    this episode may see."""
    if not listing.listing_group_id:
        return [listing]
    key = ("episodes", listing.listing_group_id)
    if cache is not None and key in cache:
        return cache[key]
    rows = session.execute(
        select(Listing)
        .where(Listing.listing_group_id == listing.listing_group_id,
               Listing.list_date.is_not(None))
        .order_by(Listing.list_date)
    ).scalars().all()
    if cache is not None:
        cache[key] = rows
    return rows


def _history_cut(prop: Property, start: date, end: date, opening_price: int | None) -> bool:
    """A dated downward "Price Changed" entry in Realtor's history inside
    [start, end] — the cut we never observed because it pre-dates our first
    scan of the listing. Entries are replayed in date order with a day's
    "Listed" before its "Price Changed" (Realtor stores newest-first, so a
    same-day pair would otherwise read backwards), seeded with the price the
    episode opened at."""
    dated = []
    for e in prop.price_history or []:
        kind = _kind(e)
        if kind not in ("list", "price") or not e.get("price"):
            continue
        d = _d(e.get("date"))
        if d is not None and start <= d <= end:
            dated.append((d, 0 if kind == "list" else 1, int(e["price"])))
    last = opening_price
    for _, is_change, price in sorted(dated):
        if is_change and last is not None and price < last:
            return True
        last = price
    return False


def _prior_episodes(session: Session, listing: Listing, start: date,
                    cache: dict | None) -> list[Listing]:
    """The campaign's episodes up to and including this one, oldest first:
    only episodes that began on or before this one count (viewing a withdrawn
    first episode must not see the relist that followed it), and two source
    rows that opened the same day are one episode."""
    by_date: dict[str, Listing] = {}
    for ep in _episodes(session, listing, cache):
        ep_start = _d(ep.list_date)
        if ep.id == listing.id or ep_start is None or ep_start > start:
            continue
        by_date.setdefault(ep.list_date[:10], ep)
    by_date[listing.list_date[:10]] = listing
    return [by_date[k] for k in sorted(by_date)]


def inputs(session: Session, listing: Listing, prop: Property,
           as_of: str | None = None, cache: dict | None = None) -> Exposure:
    """The exposure evidence for one listing as of `as_of` (default today).
    Memoized per (listing, as_of) on the page cache — overbid, valuation and
    posture all ask for it on the same request."""
    key = ("exposure", listing.id, as_of)
    if cache is not None and key in cache:
        return cache[key]

    today = date.fromisoformat(as_of[:10]) if as_of else date.today()
    upper = (today + timedelta(days=1)).isoformat()

    start = _d(listing.list_date)
    window_end = today
    if start is None:
        # no usable list date — the source's frozen counter is all there is
        days = episode_days = listing.dom_source
        episode_count, relisted, relist_lower = 1, False, False
    elif start > today:
        # as-of a date before this episode began: not on the market yet, and
        # the source's counter is the outcome, never evidence
        days = episode_days = None
        episode_count, relisted, relist_lower = 0, False, False
    else:
        episodes = _prior_episodes(session, listing, start, cache)
        spans = []
        for i, ep in enumerate(episodes):
            # an episode with no recorded end stops where the next one begins
            nxt = _d(episodes[i + 1].list_date) if i + 1 < len(episodes) else None
            end = _episode_end(ep) or nxt or today
            if nxt is not None:
                end = min(end, nxt)
            spans.append(max(0, (min(end, today) - _d(ep.list_date)).days))
        days = sum(spans)
        window_end = min(_episode_end(listing) or today, today)
        episode_days = max(0, (window_end - start).days)
        episode_count = len(episodes)
        relisted = episode_count > 1
        prev = episodes[-2] if relisted else None
        prev_price = (prev.list_price or prev.original_list_price) if prev else None
        relist_lower = bool(prev_price and listing.original_list_price
                            and listing.original_list_price < prev_price)

    cuts = price_cut_count(session, listing.id, upper)
    cut_source = None
    if cuts:
        cut_source = "observed"
    elif (start is not None and start <= today
          and _history_cut(prop, start, window_end, listing.original_list_price)):
        cut_source = "history"
    elif relist_lower:
        cut_source = "relist_lower"

    median = area_median_dom(session, as_of, cache)
    clock = episode_days if relisted else days
    ratio = (clock / median) if (clock is not None and median) else None

    offer_passed = False
    if not as_of and listing.offer_due_at and listing.status == "active":
        try:
            due = date.fromisoformat(listing.offer_due_at[:10])
            offer_passed = today > due + timedelta(days=OFFER_PASSED_GRACE_DAYS)
        except ValueError:
            pass

    ex = Exposure(days=days, episode_days=episode_days, episode_count=episode_count,
                  relisted=relisted, had_cut=cut_source is not None, cuts=cuts,
                  cut_source=cut_source, median_dom=median, ratio=ratio,
                  offer_passed=offer_passed)
    if cache is not None:
        cache[key] = ex
    return ex
