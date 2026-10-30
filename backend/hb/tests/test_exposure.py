"""Exposure extractor unit tests — docs/06 §5.6 (episode clock, cut sources,
as-of discipline)."""

from datetime import date, timedelta

from hb.db.models import Listing, ListingEvent, ListingGroup, MarketMetric, Property
from hb.engine import exposure

TODAY = date.today()


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _median_dom(session, value=10.0, period_start="2026-01-01"):
    session.add(MarketMetric(geo_type="city", geo_id="Sunnyvale", period_start=period_start,
                             period="monthly", metric="median_dom", value=value,
                             source="redfin"))


def _prop(session, price_history=None):
    prop = Property(address_norm="1 SUBJECT WAY", zip="94087", city="Sunnyvale",
                    beds=3, baths=2.0, sqft=1600, property_type="single_family",
                    price_history=price_history or [])
    session.add(prop)
    session.flush()
    return prop


def _listing(session, prop, *, list_date, group=None, status="active", list_price=2_650_000,
             original=None, delist_date=None, pending_date=None, sold_date=None,
             dom_source=None, offer_due_at=None, sid="L1"):
    lst = Listing(property_id=prop.id, listing_group_id=group.id if group else None,
                  source="realtor", source_listing_id=sid, status=status,
                  list_price=list_price, original_list_price=original or list_price,
                  list_date=list_date, delist_date=delist_date, pending_date=pending_date,
                  sold_date=sold_date, dom_source=dom_source, offer_due_at=offer_due_at)
    session.add(lst)
    session.flush()
    return lst


def _group(session, prop, episodes=1):
    g = ListingGroup(property_id=prop.id, episode_count=episodes)
    session.add(g)
    session.flush()
    return g


def test_relist_resets_the_clock_but_keeps_cumulative(session):
    """ep1 03-01 → delisted 04-10 (40 days), ep2 05-01 still active: as-of 05-06
    the clock is 5 days into episode 2 while cumulative exposure is 45."""
    _median_dom(session)
    prop = _prop(session)
    g = _group(session, prop, episodes=2)
    _listing(session, prop, list_date="2026-03-01", group=g, status="delisted",
             delist_date="2026-04-10", list_price=2_800_000, sid="EP1")
    ep2 = _listing(session, prop, list_date="2026-05-01", group=g, list_price=2_800_000, sid="EP2")
    session.commit()

    ex = exposure.inputs(session, ep2, prop, as_of="2026-05-06")
    assert (ex.days, ex.episode_days, ex.episode_count) == (45, 5, 2)
    assert ex.relisted is True
    assert ex.ratio == 0.5           # episode clock / median 10
    assert ex.had_cut is False       # same ask as the previous episode
    assert ex.cut_source is None


def test_asof_before_the_relist_sees_a_single_episode(session):
    _median_dom(session)
    prop = _prop(session)
    g = _group(session, prop, episodes=2)
    ep1 = _listing(session, prop, list_date="2026-03-01", group=g, status="delisted",
                   delist_date="2026-04-10", sid="EP1")
    _listing(session, prop, list_date="2026-05-01", group=g, sid="EP2")
    session.commit()

    ex = exposure.inputs(session, ep1, prop, as_of="2026-04-20")
    assert ex.episode_count == 1 and ex.relisted is False
    assert ex.days == ex.episode_days == 40   # clipped at the delist, not at as-of


def test_relisted_lower_counts_as_a_cut(session):
    _median_dom(session)
    prop = _prop(session)
    g = _group(session, prop, episodes=2)
    _listing(session, prop, list_date="2026-03-01", group=g, status="delisted",
             delist_date="2026-04-10", list_price=2_800_000, sid="EP1")
    ep2 = _listing(session, prop, list_date="2026-05-01", group=g, list_price=2_650_000, sid="EP2")
    session.commit()

    ex = exposure.inputs(session, ep2, prop, as_of="2026-05-06")
    assert ex.had_cut is True and ex.cut_source == "relist_lower"
    assert ex.cuts == 0  # nothing observed as an event


def test_viewing_an_older_episode_live_does_not_see_the_relist(session):
    """The withdrawn first episode of a relisted campaign, opened on its own
    detail page today, must read as a single finished episode — never as a
    relist of the episode that came after it, nor compare its price to it."""
    _median_dom(session)
    prop = _prop(session)
    g = _group(session, prop, episodes=2)
    ep1 = _listing(session, prop, list_date=_iso(90), group=g, status="delisted",
                   delist_date=_iso(50), list_price=2_800_000, sid="EP1")
    _listing(session, prop, list_date=_iso(20), group=g, list_price=2_500_000, sid="EP2")
    session.commit()

    ex = exposure.inputs(session, ep1, prop)
    assert (ex.days, ex.episode_days, ex.episode_count) == (40, 40, 1)
    assert ex.relisted is False and ex.had_cut is False


def test_asof_before_the_list_date_has_no_exposure(session):
    """Pass A evaluates the day before listing: the source's frozen DOM is the
    outcome, not evidence, so nothing routes on it."""
    _median_dom(session)
    prop = _prop(session)
    lst = _listing(session, prop, list_date="2026-06-20", dom_source=48)
    session.commit()
    ex = exposure.inputs(session, lst, prop, as_of="2026-06-19")
    assert ex.days is None and ex.episode_days is None and ex.ratio is None
    assert ex.episode_count == 0 and ex.relisted is False


def test_same_day_source_rows_are_one_episode(session):
    """Two source rows that opened the same day are one episode, not a relist,
    and their overlapping spans are not summed twice."""
    _median_dom(session)
    prop = _prop(session)
    g = _group(session, prop, episodes=2)
    _listing(session, prop, list_date=_iso(20), group=g, sid="REDFIN")
    lst = _listing(session, prop, list_date=_iso(20), group=g, sid="REALTOR")
    session.commit()
    ex = exposure.inputs(session, lst, prop)
    assert (ex.days, ex.episode_days, ex.episode_count, ex.relisted) == (20, 20, 1, False)


def test_open_ended_prior_episode_stops_where_the_next_begins(session):
    _median_dom(session)
    prop = _prop(session)
    g = _group(session, prop, episodes=2)
    _listing(session, prop, list_date=_iso(60), group=g, status="active", sid="STALE_ROW")
    cur = _listing(session, prop, list_date=_iso(10), group=g, sid="CUR")
    session.commit()
    ex = exposure.inputs(session, cur, prop)
    assert ex.days == 60 and ex.episode_days == 10   # 50 + 10, not 60 + 10


def test_other_group_episode_is_not_summed(session):
    """A 2024 sale campaign on the same property lives in its own group and must
    not inflate this campaign's exposure."""
    _median_dom(session)
    prop = _prop(session)
    old = _group(session, prop)
    _listing(session, prop, list_date="2024-02-01", group=old, status="sold",
             sold_date="2024-03-15", sid="OLD")
    g = _group(session, prop)
    cur = _listing(session, prop, list_date=_iso(20), group=g, sid="CUR")
    session.commit()

    ex = exposure.inputs(session, cur, prop)
    assert ex.days == ex.episode_days == 20
    assert ex.episode_count == 1


def test_history_cut_is_asof_filtered(session):
    """Realtor's dated "Price Changed" entry is a cut once as-of reaches it —
    the cut we never saw as an event because it pre-dates our first scan."""
    _median_dom(session)
    prop = _prop(session, price_history=[
        {"date": "2026-05-03", "event": "Price Changed", "price": 2_500_000},
        {"date": "2026-05-01", "event": "Listed for sale", "price": 2_600_000},
        {"date": "2024-03-15", "event": "Sold", "price": 2_100_000},
    ])
    lst = _listing(session, prop, list_date="2026-05-01", list_price=2_500_000,
                   original=2_500_000)
    session.commit()

    assert exposure.inputs(session, lst, prop, as_of="2026-05-02").had_cut is False
    ex = exposure.inputs(session, lst, prop, as_of="2026-05-06")
    assert ex.had_cut is True and ex.cut_source == "history" and ex.cuts == 0


def test_history_cut_same_day_pair_and_opening_price_seed(session):
    """Realtor stores newest-first, so a same-day 'Listed'/'Price Changed'
    pair must be replayed list-first; and a 'Price Changed' below the price the
    episode opened at is a cut even when the 'Listed' entry is dated a day
    before our list_date."""
    _median_dom(session)
    same_day = _prop(session, price_history=[
        {"date": "2026-05-01", "event": "Price Changed", "price": 2_500_000},
        {"date": "2026-05-01", "event": "Listed for sale", "price": 2_600_000},
    ])
    lst = _listing(session, same_day, list_date="2026-05-01", list_price=2_500_000,
                   original=2_600_000)
    session.commit()
    assert exposure.inputs(session, lst, same_day, as_of="2026-05-06").cut_source == "history"

    seeded = Property(address_norm="2 SEED CT", zip="94087", city="Sunnyvale", beds=3,
                      baths=2.0, sqft=1600, property_type="single_family",
                      price_history=[
                          {"date": "2026-05-04", "event": "Price Changed", "price": 2_500_000},
                          {"date": "2026-04-30", "event": "Listed for sale", "price": 2_600_000},
                      ])
    session.add(seeded)
    session.flush()
    lst2 = _listing(session, seeded, list_date="2026-05-01", list_price=2_500_000,
                    original=2_600_000, sid="L2")
    session.commit()
    assert exposure.inputs(session, lst2, seeded, as_of="2026-05-06").cut_source == "history"


def test_observed_event_wins_over_history(session):
    _median_dom(session)
    prop = _prop(session)
    lst = _listing(session, prop, list_date=_iso(30))
    session.add(ListingEvent(listing_id=lst.id, event_type="price_change",
                             old_value="2750000", new_value="2650000",
                             observed_at=_iso(10) + "T00:00:00+00:00"))
    session.commit()
    ex = exposure.inputs(session, lst, prop)
    assert ex.cuts == 1 and ex.cut_source == "observed"
    # as-of before the event: no cut
    assert exposure.inputs(session, lst, prop, as_of=_iso(15)).had_cut is False


def test_dom_source_fallback_without_list_date(session):
    _median_dom(session)
    prop = _prop(session)
    lst = _listing(session, prop, list_date=None, dom_source=12)
    session.commit()
    ex = exposure.inputs(session, lst, prop)
    assert ex.days == ex.episode_days == 12
    assert ex.ratio == 1.2


def test_pending_stops_the_clock(session):
    _median_dom(session)
    prop = _prop(session)
    lst = _listing(session, prop, list_date=_iso(40), status="pending", pending_date=_iso(25))
    session.commit()
    assert exposure.inputs(session, lst, prop).days == 15


def test_offer_passed_is_live_only(session):
    _median_dom(session)
    prop = _prop(session)
    lst = _listing(session, prop, list_date=_iso(20), offer_due_at=_iso(5))
    session.commit()
    assert exposure.inputs(session, lst, prop).offer_passed is True
    assert exposure.inputs(session, lst, prop, as_of=_iso(1)).offer_passed is False


def test_area_median_dom_memoises_none(session):
    cache: dict = {}
    assert exposure.area_median_dom(session, None, cache) is None
    assert ("area_median_dom", None) in cache
    _median_dom(session, value=13.0)
    session.commit()
    # cached answer sticks for the page even though a row now exists
    assert exposure.area_median_dom(session, None, cache) is None
    assert exposure.area_median_dom(session, None) == 13.0


def test_inputs_memoised_per_listing(session):
    _median_dom(session)
    prop = _prop(session)
    lst = _listing(session, prop, list_date=_iso(3))
    session.commit()
    cache: dict = {}
    first = exposure.inputs(session, lst, prop, cache=cache)
    assert exposure.inputs(session, lst, prop, cache=cache) is first
