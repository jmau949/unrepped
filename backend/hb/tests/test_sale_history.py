"""sale-history derivation — reconstructing pre-observation listing history."""

import pytest

from hb.db.models import Property, Sale
from hb.pipelines import sale_history
from hb.pipelines.sale_history import derive


def _h(*events):
    """Realtor-shaped history, newest first (as price_history stores it)."""
    return [{"date": d, "event": e, "price": p} for d, e, p in reversed(events)]


def test_derive_clean_campaign_no_cut():
    out = derive(
        _h(
            ("2026-05-01", "Listed for sale", 2_500_000),
            ("2026-05-20", "Pending", None),
            ("2026-06-02", "Sold", 2_800_000),
        ),
        sale_date="2026-06-02",
    )
    assert out["original_list_price"] == 2_500_000
    assert out["had_price_cut"] is False
    assert out["episode_count"] == 1
    # exposure ends at pending, not at close (same rule as relist._episode_end)
    assert out["dom"] == 19  # 2026-05-01 -> 2026-05-20
    assert out["cumulative_dom"] == 19


def test_derive_detects_price_cut_and_keeps_original():
    out = derive(
        _h(
            ("2026-03-01", "Listed for sale", 3_200_000),
            ("2026-04-05", "Price Changed", 2_950_000),
            ("2026-05-10", "Sold", 2_900_000),
        ),
        sale_date="2026-05-10",
    )
    assert out["had_price_cut"] is True
    assert out["original_list_price"] == 3_200_000  # pre-cut, not the 2.95M


def test_derive_price_raise_is_not_a_cut():
    out = derive(
        _h(
            ("2026-03-01", "Listed for sale", 2_000_000),
            ("2026-03-20", "Price Changed", 2_100_000),
            ("2026-04-01", "Sold", 2_150_000),
        ),
        sale_date="2026-04-01",
    )
    assert out["had_price_cut"] is False


def test_derive_relist_within_gap_is_one_campaign():
    """Delist and relist 30 days later at a lower price is a cut, and CDOM sums
    both episodes — the exposure the public DOM counter hides (docs/01 §3)."""
    out = derive(
        _h(
            ("2026-01-10", "Listed for sale", 3_000_000),
            ("2026-02-09", "Listing Removed", None),
            ("2026-03-11", "Listed for sale", 2_800_000),
            ("2026-04-20", "Sold", 2_750_000),
        ),
        sale_date="2026-04-20",
    )
    assert out["episode_count"] == 2
    assert out["original_list_price"] == 3_000_000
    assert out["had_price_cut"] is True
    assert out["dom"] == 40  # final episode only: 2026-03-11 -> 2026-04-20
    assert out["cumulative_dom"] == 70  # 30 (first episode) + 40


def test_derive_relist_beyond_gap_starts_a_new_campaign():
    """A gap of 90+ days is a fresh campaign — the old, higher price must not
    leak in as this sale's original list price."""
    out = derive(
        _h(
            ("2025-01-10", "Listed for sale", 3_000_000),
            ("2025-03-01", "Listing Removed", None),
            ("2026-03-11", "Listed for sale", 2_800_000),
            ("2026-04-20", "Sold", 2_750_000),
        ),
        sale_date="2026-04-20",
    )
    assert out["episode_count"] == 1
    assert out["original_list_price"] == 2_800_000
    assert out["had_price_cut"] is False


def test_derive_window_excludes_prior_ownership_cycle():
    history = _h(
        ("2019-02-01", "Listed for sale", 1_400_000),
        ("2019-03-15", "Sold", 1_500_000),
        ("2026-03-01", "Listed for sale", 2_800_000),
        ("2026-04-10", "Sold", 3_000_000),
    )
    out = derive(history, sale_date="2026-04-10", prev_sale_date="2019-03-15")
    assert out["original_list_price"] == 2_800_000
    assert out["episode_count"] == 1


def test_derive_returns_none_without_a_listing_episode():
    assert derive(_h(("2020-01-01", "Sold", 900_000)), sale_date="2026-04-10") is None
    assert derive([], sale_date="2026-04-10") is None


def test_derive_ignores_rental_episodes():
    out = derive(
        _h(
            ("2026-01-05", "Listed for rent", 7_500),
            ("2026-03-01", "Listed for sale", 2_800_000),
            ("2026-04-10", "Sold", 3_000_000),
        ),
        sale_date="2026-04-10",
    )
    assert out["original_list_price"] == 2_800_000
    assert out["episode_count"] == 1


# --- application to sales ----------------------------------------------------

def _seed(session, history, **sale_over):
    prop = Property(address_norm="1 X ST", zip="94087", city="Sunnyvale",
                    street="1 X St", price_history=history)
    session.add(prop)
    session.flush()
    fields = {"property_id": prop.id, "sale_date": "2026-05-10",
              "sale_price": 2_900_000, "had_price_cut": False}
    fields.update(sale_over)
    sale = Sale(**fields)
    session.add(sale)
    session.commit()
    return prop, sale


CUT_HISTORY = _h(
    ("2026-03-01", "Listed for sale", 3_200_000),
    ("2026-04-05", "Price Changed", 2_950_000),
    ("2026-05-10", "Sold", 2_900_000),
)


def test_apply_fills_cut_original_and_dom(session):
    prop, sale = _seed(session, CUT_HISTORY, original_list_price=2_950_000,
                       sp_lp=round(2_900_000 / 2_950_000, 4))

    assert sale_history.apply_all(session) == 1
    session.refresh(sale)
    assert sale.had_price_cut is True
    assert sale.original_list_price == 3_200_000  # raised past the post-cut price
    assert sale.sp_lp == pytest.approx(2_900_000 / 3_200_000, abs=1e-4)
    # single episode, never taken off market -> exposure runs to the sale date
    assert sale.dom == 70   # 2026-03-01 -> 2026-05-10
    assert sale.cumulative_dom == 70


def test_apply_is_idempotent(session):
    _seed(session, CUT_HISTORY, original_list_price=2_950_000)
    assert sale_history.apply_all(session) == 1
    assert sale_history.apply_all(session) == 0  # second pass changes nothing


def test_apply_never_lowers_an_observed_original(session):
    """The scan watched this listing from a HIGHER original than the timeline
    reports — observed truth wins (docs/05 §4.3)."""
    prop, sale = _seed(session, CUT_HISTORY, original_list_price=3_500_000,
                       sp_lp=round(2_900_000 / 3_500_000, 4))

    sale_history.apply_all(session)
    session.refresh(sale)
    assert sale.original_list_price == 3_500_000
    assert sale.sp_lp == pytest.approx(2_900_000 / 3_500_000, abs=1e-4)


def test_apply_never_erases_an_observed_cut(session):
    clean = _h(
        ("2026-03-01", "Listed for sale", 2_800_000),
        ("2026-05-10", "Sold", 2_900_000),
    )
    prop, sale = _seed(session, clean, had_price_cut=True,
                       original_list_price=2_800_000)

    sale_history.apply_all(session)
    session.refresh(sale)
    assert sale.had_price_cut is True


def test_apply_scopes_to_given_properties(session):
    _seed(session, CUT_HISTORY, original_list_price=2_950_000)
    assert sale_history.apply_all(session, property_ids=[]) == 0
    assert sale_history.apply_all(session, property_ids=["nope"]) == 0


def test_run_job_records_a_pipeline_run(engine, session):
    from hb.db.models import PipelineRun
    from sqlalchemy import select

    _seed(session, CUT_HISTORY, original_list_price=2_950_000)
    assert sale_history.run(engine) == "ok"

    run = session.execute(
        select(PipelineRun).where(PipelineRun.job == "derive-sales-history")
    ).scalar_one()
    assert run.items_upserted == 1
