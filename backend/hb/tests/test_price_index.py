import pytest

from hb.db.models import PriceIndex
from hb.engine import price_index


# --- pure interpolation ------------------------------------------------------

def test_interpolate_exact_month():
    pts = [("2026-02", 0.962), ("2026-07", 1.000)]
    val, carried = price_index.interpolate(pts, "2026-02")
    assert val == pytest.approx(0.962)
    assert carried is False


def test_interpolate_missing_month_linear():
    # midpoint between 2026-01 (0.90) and 2026-03 (1.00) -> 2026-02 = 0.95
    pts = [("2026-01", 0.90), ("2026-03", 1.00)]
    val, carried = price_index.interpolate(pts, "2026-02")
    assert val == pytest.approx(0.95)
    assert carried is False


def test_interpolate_carry_forward_past_end():
    pts = [("2026-01", 0.90), ("2026-03", 1.00)]
    val, carried = price_index.interpolate(pts, "2026-08")
    assert val == pytest.approx(1.00)  # carried last value
    assert carried is True


def test_interpolate_before_start_flagged():
    pts = [("2026-03", 1.00), ("2026-05", 1.10)]
    val, carried = price_index.interpolate(pts, "2026-01")
    assert val == pytest.approx(1.00)
    assert carried is True


# --- DB-backed lookup + factor ----------------------------------------------

@pytest.fixture
def seeded_index(session):
    rows = [
        PriceIndex(geo_type="zip", geo_id="94087", month="2026-02", index_value=0.962, source="blend"),
        PriceIndex(geo_type="zip", geo_id="94087", month="2026-07", index_value=1.000, source="blend"),
    ]
    session.add_all(rows)
    session.commit()
    return session


def test_docs_4_3_factor_exact(seeded_index):
    """docs/06 §4.3: index(2026-07)/index(2026-02) = 1.000/0.962."""
    factor, source = price_index.time_adj_factor(seeded_index, "94087", "2026-02", "2026-07")
    assert factor == pytest.approx(1.000 / 0.962, abs=1e-12)
    assert source.startswith("blend@zip")


def test_geo_fallback_zip_to_city(session):
    # no ZIP series; Sunnyvale city series exists -> ZIP borrows the city
    session.add_all([
        PriceIndex(geo_type="city", geo_id="Sunnyvale", month="2026-02", index_value=0.95, source="blend"),
        PriceIndex(geo_type="city", geo_id="Sunnyvale", month="2026-07", index_value=1.00, source="blend"),
    ])
    session.commit()
    lookup = price_index.index_for(session, "94087", "2026-07")
    assert lookup is not None
    assert lookup.geo_type == "city" and lookup.geo_id == "Sunnyvale"


def test_as_of_truncates_future_months(seeded_index):
    # as_of before 2026-07: only the 2026-02 row survives -> carry forward + flag
    lookup = price_index.index_for(seeded_index, "94087", "2026-07", as_of="2026-04-15")
    assert lookup is not None
    assert lookup.value == pytest.approx(0.962)
    assert lookup.carried is True


def test_no_index_returns_neutral_factor(session):
    factor, source = price_index.time_adj_factor(session, "99999", "2026-02", "2026-07")
    assert factor == 1.0
    assert source == "none"
