import pytest

from hb.db.models import MarketMetric
from hb.engine import adjustments


# --- golden gate: docs/06 §4.3 -> $2,198,766 --------------------------------

def test_worked_example_docs06_4_3():
    subject = {"sqft": 1600, "baths": 2.0, "lot_sqft": 5000, "condition_tag": "dated"}
    comp = {"sale_price": 2_400_000, "sqft": 1750, "baths": 2.5, "lot_sqft": 5200,
            "condition_tag": "renovated"}
    m = 0.45 * 1400  # = 630
    factor = 1.000 / 0.962
    r = adjustments.adjust(subject, comp, m=m, time_adj_factor=factor)

    assert r.line_items["time"] == 94_802
    assert r.line_items["sqft"] == -94_500
    assert r.line_items["baths"] == -8_000
    assert r.line_items["lot"] == -18_900
    assert r.line_items["condition"] == -174_636
    assert r.adjusted_price == pytest.approx(2_198_766, abs=1)
    assert r.gross_feature == 94_500 + 8_000 + 18_900 + 174_636  # time excluded


# --- bath grid ---------------------------------------------------------------

def test_bath_grid_signs_and_magnitudes():
    assert adjustments.bath_adjustment(2.0, 2.5) == -8_000   # comp has extra half
    assert adjustments.bath_adjustment(3.0, 2.0) == 15_000   # subject one more full
    assert adjustments.bath_adjustment(3.5, 2.0) == 23_000   # full + half
    assert adjustments.bath_adjustment(2.0, 2.0) == 0
    assert adjustments.bath_adjustment(None, 2.0) == 0


def test_bath_regression_coef_replaces_grid():
    assert adjustments.bath_adjustment(3.0, 2.0, bath_coef=20_000) == 20_000


# --- lot cap -----------------------------------------------------------------

def test_lot_adjustment_and_cap():
    val, note = adjustments.lot_adjustment(5000, 5200, m=630, comp_price=2_400_000)
    assert val == -18_900 and note == ""
    # huge lot delta gets clamped to ±10% of comp price
    capped, note2 = adjustments.lot_adjustment(50_000, 1000, m=630, comp_price=1_000_000)
    assert capped == 100_000 and note2 == "lot capped"
    assert adjustments.lot_adjustment(None, 5000, m=630, comp_price=1_000_000) == (0, "lot unknown")


# --- condition ---------------------------------------------------------------

def test_condition_relative_baseline():
    # comp renovated superior to subject dated -> subtract 7% of adj_price0
    val, _ = adjustments.condition_adjustment("dated", "renovated", 2_494_802)
    assert val == -174_636
    # renovated vs fixer composes to 22%
    val2, _ = adjustments.condition_adjustment("renovated", "fixer", 1_000_000)
    assert val2 == 220_000
    # unknown tag -> 0 with note
    val3, note = adjustments.condition_adjustment("dated", None, 1_000_000)
    assert val3 == 0 and note == "condition unknown"


# --- default m from market_metrics ------------------------------------------

def test_default_m_from_median_ppsf(session):
    session.add_all([
        MarketMetric(geo_type="zip", geo_id="94087", period_start="2026-05-01",
                     period="monthly", metric="median_ppsf", value=1350, source="redfin"),
        MarketMetric(geo_type="zip", geo_id="94087", period_start="2026-06-01",
                     period="monthly", metric="median_ppsf", value=1400, source="redfin"),
        MarketMetric(geo_type="zip", geo_id="94087", period_start="2026-07-01",
                     period="monthly", metric="median_ppsf", value=1450, source="redfin"),
    ])
    session.commit()
    m, avg = adjustments.default_m(session, "94087")
    assert avg == 1400  # median of last 3
    assert m == pytest.approx(630)


def test_default_m_none_without_data(session):
    assert adjustments.default_m(session, "94087") == (None, None)


# --- RLM override ------------------------------------------------------------

def _synthetic_rows(n=50, sqft_price=1000.0):
    """Clean linear data: detrended = sqft_price·sqft + 15000·baths + 5·lot − 500·age."""
    rows = []
    for i in range(n):
        sqft = 1000 + (i * 53) % 1200
        baths = 1 + (i % 5) * 0.5
        lot = 3000 + (i * 137) % 5000
        age = (i * 7) % 45
        price = sqft_price * sqft + 15_000 * baths + 5 * lot - 500 * age
        rows.append({"detrended_price": price, "sqft": sqft, "baths": baths,
                     "lot_sqft": lot, "age": age})
    return rows


def test_regression_accepted_in_band():
    rows = _synthetic_rows(sqft_price=1000.0)
    fit = adjustments.regression_override(rows, avg_ppsf=2000.0)  # band [500,1400]
    assert fit is not None and fit.accepted is True
    assert fit.sqft_coef == pytest.approx(1000, abs=50)


def test_regression_rejected_out_of_band():
    rows = _synthetic_rows(sqft_price=1000.0)
    fit = adjustments.regression_override(rows, avg_ppsf=1000.0)  # band [250,700]
    assert fit is not None and fit.accepted is False  # 1000 > 700 -> keep heuristic


def test_regression_none_when_thin():
    assert adjustments.regression_override(_synthetic_rows(n=20), avg_ppsf=2000.0) is None
