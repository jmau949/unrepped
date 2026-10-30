from sqlalchemy import func, select

from hb.db.models import Listing, ListingEvent, ListingGroup, Property
from hb.pipelines.relist import stitch

OBS = "2026-07-14T12:00:00+00:00"


def _prop(session):
    p = Property(address_norm="1 ELM ST", zip="94025")
    session.add(p)
    session.flush()
    return p


def _episode(session, prop, source_id, list_date, *, delist=None, sold=None, pending=None,
             status="active", source="realtor"):
    lst = Listing(
        property_id=prop.id, source=source, source_listing_id=source_id,
        status=status, list_price=2_000_000, original_list_price=2_000_000,
        list_date=list_date, delist_date=delist, sold_date=sold, pending_date=pending,
    )
    session.add(lst)
    session.flush()
    return lst


def test_d9_gap_under_90_joins_group(session):
    p = _prop(session)
    _episode(session, p, "E1", "2026-01-01", delist="2026-03-01", status="delisted")
    e2 = _episode(session, p, "E2", "2026-04-15", pending="2026-05-15", status="pending")
    session.commit()

    stitch(session, {p.id}, OBS)
    session.commit()

    group = session.execute(select(ListingGroup)).scalar_one()
    assert group.episode_count == 2
    assert group.cumulative_dom == 59 + 30  # jan1->mar1 (31+28) + apr15->may15
    assert group.first_list_date == "2026-01-01"
    relists = session.execute(
        select(ListingEvent).where(ListingEvent.event_type == "relisted")
    ).scalars().all()
    assert len(relists) == 1
    assert relists[0].listing_id == e2.id

    # deterministic re-run: nothing changes
    stitch(session, {p.id}, OBS)
    session.commit()
    assert session.execute(select(func.count()).select_from(ListingGroup)).scalar_one() == 1
    assert len(session.execute(
        select(ListingEvent).where(ListingEvent.event_type == "relisted")
    ).scalars().all()) == 1


def test_d10_gap_90_plus_new_group_no_event(session):
    p = _prop(session)
    _episode(session, p, "E1", "2026-01-01", delist="2026-03-01", status="delisted")
    _episode(session, p, "E2", "2026-06-15")  # 106-day gap
    session.commit()

    stitch(session, {p.id}, OBS)
    session.commit()

    assert session.execute(select(func.count()).select_from(ListingGroup)).scalar_one() == 2
    assert session.execute(
        select(func.count()).select_from(ListingEvent).where(ListingEvent.event_type == "relisted")
    ).scalar_one() == 0


def test_intervening_sale_breaks_group(session):
    p = _prop(session)
    _episode(session, p, "E1", "2026-01-01", sold="2026-02-15", status="sold")
    _episode(session, p, "E2", "2026-03-01")  # 15 days after sale — still a NEW group
    session.commit()

    stitch(session, {p.id}, OBS)
    session.commit()
    assert session.execute(select(func.count()).select_from(ListingGroup)).scalar_one() == 2


def test_cross_source_episodes_share_group(session):
    p = _prop(session)
    _episode(session, p, "R1", "2026-01-01", delist="2026-03-01", status="delisted",
             source="realtor")
    _episode(session, p, "RF1", "2026-03-20", source="redfin")
    session.commit()

    stitch(session, {p.id}, OBS)
    session.commit()

    group = session.execute(select(ListingGroup)).scalar_one()
    assert group.episode_count == 2
    assert group.ended_by == "open"


def test_open_episode_cdom_counts_to_today(session):
    from datetime import date, timedelta

    p = _prop(session)
    start = (date.today() - timedelta(days=12)).isoformat()
    _episode(session, p, "E1", start)
    session.commit()

    stitch(session, {p.id}, OBS)
    session.commit()
    assert session.execute(select(ListingGroup)).scalar_one().cumulative_dom == 12
