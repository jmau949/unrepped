import pytest

from hb.db.models import Listing, ListingEvent, Property, Sale
from hb.engine import overbid


# --- golden gate: docs/06 §5.5 shrinkage ------------------------------------

def test_shrink_worked_example():
    assert overbid.shrink(1.12, 1.09, 9.1, 8) == pytest.approx(1.106, abs=0.001)
    assert overbid.shrink(1.06, 1.04, 9.1, 8) == pytest.approx(1.051, abs=0.001)
    assert overbid.shrink(1.18, 1.15, 9.1, 8) == pytest.approx(1.166, abs=0.001)


def test_shrink_limits():
    # n_eff -> 0 collapses to the city distribution; huge n_eff -> the ZIP
    assert overbid.shrink(1.20, 1.05, 0.0, 8) == pytest.approx(1.05)
    assert overbid.shrink(1.20, 1.05, 10_000.0, 8) == pytest.approx(1.20, abs=1e-3)
    # no city data -> ZIP unchanged
    assert overbid.shrink(1.20, None, 5.0, 8) == 1.20


# --- end-to-end predict ------------------------------------------------------

def _subject_listing(session, original=2_050_000, current=None, beds=3):
    prop = Property(address_norm="1 SUBJECT WAY", zip="94087", city="Sunnyvale",
                    beds=beds, baths=2.0, sqft=1600, property_type="single_family")
    session.add(prop)
    session.flush()
    lst = Listing(property_id=prop.id, source="realtor", source_listing_id="SUBJ1",
                  status="active", list_price=current or original,
                  original_list_price=original, list_date="2026-06-20", dom_source=10)
    session.add(lst)
    session.flush()
    return lst, prop


def _comp(session, sp_lp, *, original=2_050_000, days=5, beds=3, had_cut=False, n=[0]):
    n[0] += 1
    prop = Property(address_norm=f"{n[0]} COMP RD", zip="94087", city="Sunnyvale",
                    beds=beds, baths=2.0, sqft=1600, property_type="single_family")
    session.add(prop)
    session.flush()
    from datetime import date, timedelta
    sale_date = (date.fromisoformat("2026-07-14") - timedelta(days=days)).isoformat()
    session.add(Sale(property_id=prop.id, sale_date=sale_date, sale_price=round(original * sp_lp),
                     original_list_price=original, sp_lp=sp_lp, had_price_cut=had_cut,
                     source="realtor_sold_scan"))
    session.flush()


def test_asof_routing_ignores_future_cuts_and_dom(session):
    """Leakage regression: a price cut observed AFTER as_of must
    not route the subject to the stale distribution in backtest mode."""
    lst, prop = _subject_listing(session)
    # future cut: observed 2026-07-01, well after as_of 2026-06-19
    session.add(ListingEvent(listing_id=lst.id, event_type="price_change",
                             old_value="2050000", new_value="1990000",
                             observed_at="2026-07-01T12:00:00+00:00"))
    for r in (1.08, 1.10, 1.12, 1.12, 1.14, 1.15, 1.11, 1.13, 1.10, 1.12):
        _comp(session, r, days=40)  # sold before as_of
    session.commit()

    as_of_result = overbid.predict(session, lst, prop, as_of="2026-06-19")
    assert as_of_result.basis == "fresh"  # the cut hadn't happened yet

    live_result = overbid.predict(session, lst, prop)
    assert live_result.basis == "stale"  # live view sees the cut


def test_asof_upper_bound_includes_sales_on_asof_day(session):
    """Comps sold ON as_of count (docs/10: as_of = list_date − 1 keeps every
    pre-list comp); comps sold after as_of are excluded."""
    lst, prop = _subject_listing(session)
    from datetime import date, timedelta

    as_of = "2026-07-01"
    for i, offset in enumerate([0, 0, 0, -5, -10, -15, -20, -25]):  # all ≤ as_of
        sale_date = (date.fromisoformat(as_of) + timedelta(days=offset)).isoformat()
        p = Property(address_norm=f"{i} ASOF ST", zip="94087", city="Sunnyvale",
                     beds=3, baths=2.0, sqft=1600, property_type="single_family")
        session.add(p)
        session.flush()
        session.add(Sale(property_id=p.id, sale_date=sale_date, sale_price=2_255_000,
                         original_list_price=2_050_000, sp_lp=1.1,
                         had_price_cut=False, source="realtor_sold_scan"))
    # one future sale that must be excluded
    p = Property(address_norm="FUTURE ST", zip="94087", city="Sunnyvale",
                 beds=3, baths=2.0, sqft=1600, property_type="single_family")
    session.add(p)
    session.flush()
    session.add(Sale(property_id=p.id, sale_date="2026-07-02", sale_price=3_000_000,
                     original_list_price=2_050_000, sp_lp=1.4634,
                     had_price_cut=False, source="realtor_sold_scan"))
    session.commit()

    result = overbid.predict(session, lst, prop, as_of=as_of)
    assert result.n_comps == 8  # the three sold ON as_of are included; future one is not
    assert all(c["sale_date"] <= as_of for c in result.comps)


def test_predict_fresh_basis(session):
    lst, prop = _subject_listing(session)
    for r in (1.08, 1.10, 1.12, 1.12, 1.14, 1.15, 1.11, 1.13, 1.10, 1.12):
        _comp(session, r)
    session.commit()
    result = overbid.predict(session, lst, prop, cma_estimate=2_260_000, as_of="2026-07-14")
    assert result.basis == "fresh"
    assert result.n_comps == 10
    assert 2_150_000 < result.predicted["point"] < 2_400_000
    assert result.predicted["low"] <= result.predicted["point"] <= result.predicted["high"]
    assert result.atypical_pricing is False
    assert sum(h["weight"] for h in result.histogram) > 0


def test_routing_to_stale_on_price_cut(session):
    lst, prop = _subject_listing(session, original=2_100_000, current=1_990_000)
    session.add(ListingEvent(listing_id=lst.id, event_type="price_change",
                             old_value="2100000", new_value="1990000",
                             observed_at="2026-07-01T00:00:00+00:00"))
    for r in (1.05, 1.06, 1.07, 1.05, 1.08):  # fresh comps
        _comp(session, r)
    for r in (0.98, 0.99, 1.00):  # stale comps
        _comp(session, r, had_cut=True)
    session.commit()
    result = overbid.predict(session, lst, prop, as_of="2026-07-14")
    assert result.basis == "stale"
    assert result.basis_reason == "price cut"
    # stale distribution centers well below the fresh one
    assert result.p50 < 1.03


def test_sp_lp_uses_original_list(session):
    lst, prop = _subject_listing(session)
    # comp sold 2.3M against a 2.0M ORIGINAL list -> sp_lp = 1.15 flows through
    _comp(session, 1.15, original=2_000_000)
    for r in (1.10, 1.12, 1.11):
        _comp(session, r)
    session.commit()
    result = overbid.predict(session, lst, prop, as_of="2026-07-14")
    cut_comp = next(c for c in result.comps if c["original_list_price"] == 2_000_000
                    and c["sale_price"] == 2_300_000)
    assert cut_comp["sp_lp"] == pytest.approx(1.15)


def test_atypical_flag_when_list_diverges_from_cma(session):
    lst, prop = _subject_listing(session)
    for r in (1.10, 1.11, 1.12, 1.10, 1.13):
        _comp(session, r)
    session.commit()
    # CMA estimate far below the ratio-implied point -> atypical
    result = overbid.predict(session, lst, prop, cma_estimate=1_800_000, as_of="2026-07-14")
    assert result.atypical_pricing is True


def test_no_comps_returns_empty(session):
    lst, prop = _subject_listing(session)
    session.commit()
    result = overbid.predict(session, lst, prop, as_of="2026-07-14")
    assert result.n_comps == 0
    assert result.predicted is None
