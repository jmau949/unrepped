import pytest

from hb.engine.supply import classify_band, pct_rank, window_end, window_months


def test_bands_are_peninsula_calibrated_not_national():
    # every target ZIP sits under the NAR "seller's market" line, so the bands
    # have to split that range rather than the 3/6-month national one
    assert classify_band(0.3) == "very_tight"
    assert classify_band(0.99) == "very_tight"
    assert classify_band(1.0) == "tight"
    assert classify_band(1.9) == "tight"
    assert classify_band(2.0) == "balancing"
    assert classify_band(3.9) == "balancing"
    assert classify_band(4.0) == "soft"
    assert classify_band(None) == "unknown"


def test_pct_rank_positions_value_in_its_own_history():
    history = [float(i) for i in range(1, 21)]  # 1.0 .. 20.0
    assert pct_rank(history, 5.0) == pytest.approx(0.25)
    assert pct_rank(history, 20.0) == pytest.approx(1.0)
    assert pct_rank(history, 0.5) == pytest.approx(0.0)


def test_pct_rank_refuses_thin_history():
    assert pct_rank([1.0] * 11, 1.0) is None  # under MIN_HISTORY_POINTS
    assert pct_rank([1.0] * 12, 1.0) == pytest.approx(1.0)
    assert pct_rank([1.0] * 12, None) is None


def test_window_covers_three_calendar_months_and_wraps_the_year():
    assert window_months("2026-03-01") == ["2026-03-01", "2026-04-01", "2026-05-01"]
    assert window_months("2025-11-01") == ["2025-11-01", "2025-12-01", "2026-01-01"]
    # the live Redfin window: period_begin 2026-03-01 -> period_end 2026-05-31
    assert window_end("2026-03-01") == "2026-05-31"
    assert window_end("2025-11-01") == "2026-01-31"
    assert window_end("2025-12-01") == "2026-02-28"


def test_months_ago_walks_calendar_months_and_clamps_short_ones():
    from datetime import date

    from hb.engine.supply import LIVE_WINDOWS, live_period, months_ago

    assert months_ago(date(2026, 9, 26), 3) == date(2026, 6, 26)
    assert months_ago(date(2026, 9, 26), 12) == date(2025, 9, 26)
    assert months_ago(date(2026, 1, 15), 3) == date(2025, 10, 15)  # wraps the year
    assert months_ago(date(2026, 5, 31), 3) == date(2026, 2, 28)  # clamps to Feb
    assert [live_period(m) for m in LIVE_WINDOWS] == ["3m", "6m", "9m", "12m"]
