"""Months-of-supply interpretation helpers — docs/06-algorithms.md §9.

Months of supply (MOS) = active inventory / monthly closed-sale rate: how long
it would take to clear every listed home at the current pace. The raw number is
only half the signal — a bare "1.1" says nothing until you know this market's
entire observed range is roughly 0.2–2.5 months. The pure functions here supply
the missing context (an absolute band calibrated to the peninsula, and each
geo's percentile against its own history) plus the window arithmetic the
`market-supply` pipeline and the Supply API share.

No DB, no session.
"""

import calendar
from collections.abc import Sequence
from datetime import date, timedelta

# Redfin ZIP and city rows are rolling 3-month windows (period_begin 2026-06-01
# -> period_end 2026-08-31) labelled by window *start* (docs/03 §1.1).
ZIP_WINDOW_MONTHS = 3

# Trailing windows the live now-cast is computed for, in calendar months. Each
# is stored as its own series, distinguished by `market_metrics.period`
# ('3m' | '6m' | '9m' | '12m'), so any of them can be charted with history.
LIVE_WINDOWS = (3, 6, 9, 12)
DEFAULT_LIVE_WINDOW = 3

# A percentile over a handful of points is noise dressed as precision.
MIN_HISTORY_POINTS = 12

# Band thresholds, in months. Deliberately NOT the national NAR convention
# (<3 seller's / 3–6 balanced / >6 buyer's): every target ZIP sits well under 3
# months, so national bands would paint the whole peninsula one colour and teach
# the buyer nothing. Calibrated to the observed 2012–2026 Redfin distribution
# for the target geos (docs/06 §9).
BAND_TIGHT = 1.0
BAND_BALANCING = 2.0
BAND_SOFT = 4.0


def live_period(months: int) -> str:
    """`market_metrics.period` label for a live window: 3 -> '3m'."""
    return f"{months}m"


def months_ago(d: date, n: int) -> date:
    """`d` shifted back n calendar months, clamped to the target month's length."""
    total = d.year * 12 + d.month - 1 - n
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def window_months(period_start: str, n: int = ZIP_WINDOW_MONTHS) -> list[str]:
    """The n first-of-month dates a window starting at `period_start` covers."""
    year, month, _ = (int(p) for p in period_start.split("-"))
    out = []
    for i in range(n):
        total = month + i
        out.append(f"{year + (total - 1) // 12:04d}-{(total - 1) % 12 + 1:02d}-01")
    return out


def window_end(period_start: str, n: int = ZIP_WINDOW_MONTHS) -> str:
    """Last calendar day covered by a window starting at `period_start`."""
    last = window_months(period_start, n)[-1]
    year, month, _ = (int(p) for p in last.split("-"))
    first_of_next = date(year + month // 12, month % 12 + 1, 1)
    return (first_of_next - timedelta(days=1)).isoformat()


def classify_band(mos: float | None) -> str:
    """Absolute supply band: `very_tight | tight | balancing | soft | unknown`."""
    if mos is None:
        return "unknown"
    if mos < BAND_TIGHT:
        return "very_tight"
    if mos < BAND_BALANCING:
        return "tight"
    if mos < BAND_SOFT:
        return "balancing"
    return "soft"


def pct_rank(history: Sequence[float], value: float | None) -> float | None:
    """Fraction of `history` at or below `value`, 0..1.

    The local signal the absolute band cannot give: 1.1 months is tight in
    absolute terms but *loose* for a ZIP whose own three-year range is 0.3–1.2.
    Returns None below MIN_HISTORY_POINTS observations.
    """
    if value is None:
        return None
    points = [h for h in history if h is not None]
    if len(points) < MIN_HISTORY_POINTS:
        return None
    return round(sum(1 for h in points if h <= value) / len(points), 4)
