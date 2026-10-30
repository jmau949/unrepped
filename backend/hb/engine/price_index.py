"""Price-index consumer — time adjustment for CMA comps (docs/06 §3).

The ``build-index`` pipeline writes one monthly ``price_index`` series per geo
(source='blend'). This module reads it: ZIP→city→county geo fallback, linear
interpolation for missing months, carry-forward past the series end (flagged),
and the ``time_adj_factor`` that scales a comp's sale price to today.

Backtest leakage control: pass ``as_of`` to truncate every series to months at
or before that date, so a comp is never adjusted with an index the market had
not yet printed. Pure interpolation is split from the DB accessor so the
month-math is unit-tested without a session.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.models import PriceIndex

INDEX_SOURCE = "blend"


@dataclass
class IndexLookup:
    value: float
    carried: bool  # target month fell outside the (truncated) series range
    geo_type: str
    geo_id: str


def _month_ord(month: str) -> int:
    """'YYYY-MM' → absolute month ordinal (year*12 + month-1)."""
    year, mon = month[:7].split("-")
    return int(year) * 12 + (int(mon) - 1)


def interpolate(points: list[tuple[str, float]], target_month: str) -> tuple[float, bool]:
    """Value at ``target_month`` over ``[(month, value), ...]``.

    Exact month → that value. Between present months (incl. gaps) → linear
    interpolation on the month ordinal. Outside the range → nearest endpoint,
    with ``carried=True``. Returns ``(value, carried)``.
    """
    if not points:
        raise ValueError("interpolate: no points")
    pts = sorted(points, key=lambda p: p[0])
    months = [_month_ord(m) for m, _ in pts]
    values = [float(v) for _, v in pts]
    t = _month_ord(target_month)

    if t <= months[0]:
        return values[0], t < months[0]
    if t >= months[-1]:
        return values[-1], t > months[-1]
    for i in range(len(months) - 1):
        lo_m, hi_m = months[i], months[i + 1]
        if lo_m <= t <= hi_m:
            if t == lo_m or hi_m == lo_m:
                return values[i], False
            frac = (t - lo_m) / (hi_m - lo_m)
            return values[i] + frac * (values[i + 1] - values[i]), False
    # unreachable given the endpoint guards above
    return values[-1], True


def _geo_candidates(zip5: str) -> list[tuple[str, str]]:
    """(geo_type, geo_id) in fallback order: ZIP → city → county."""
    out: list[tuple[str, str]] = [("zip", zip5)]
    city = settings.geo.zip_to_city.get(zip5)
    if city:
        out.append(("city", city))
        county = settings.geo.city_to_county.get(city)
        if county:
            out.append(("county", county))
    return out


def _series(session: Session, geo_type: str, geo_id: str, as_of: str | None,
            cache: dict | None = None) -> list[tuple[str, float]]:
    """The (month, value) series for a geo. ``cache`` (a plain dict) memoizes the
    DB read within one run — the backtest re-adjusts thousands of comps against
    the same handful of geo series, so this collapses ~millions of queries."""
    if cache is not None:
        key = (geo_type, geo_id, as_of)
        if key in cache:
            return cache[key]
    stmt = select(PriceIndex.month, PriceIndex.index_value).where(
        PriceIndex.geo_type == geo_type,
        PriceIndex.geo_id == geo_id,
        PriceIndex.source == INDEX_SOURCE,
    )
    if as_of:
        stmt = stmt.where(PriceIndex.month <= as_of[:7])
    points = [(m, float(v)) for m, v in session.execute(stmt).all()]
    if cache is not None:
        cache[(geo_type, geo_id, as_of)] = points
    return points


def index_for(
    session: Session, zip5: str, month: str, as_of: str | None = None,
    cache: dict | None = None,
) -> IndexLookup | None:
    """Index value for a geo+month with ZIP→city→county fallback and optional
    ``as_of`` truncation. ``None`` if no covered geo has any (truncated) series.
    """
    for geo_type, geo_id in _geo_candidates(zip5):
        points = _series(session, geo_type, geo_id, as_of, cache)
        if points:
            value, carried = interpolate(points, month)
            return IndexLookup(value=value, carried=carried, geo_type=geo_type, geo_id=geo_id)
    return None


def time_adj_factor(
    session: Session,
    zip5: str,
    sale_month: str,
    today_month: str,
    as_of: str | None = None,
    cache: dict | None = None,
) -> tuple[float, str]:
    """``index(today) / index(sale)`` with the geo/source label actually used.

    No usable index for either month → ``(1.0, "none")`` (no time adjustment).
    """
    now = index_for(session, zip5, today_month, as_of, cache)
    then = index_for(session, zip5, sale_month, as_of, cache)
    if now is None or then is None or then.value == 0:
        return 1.0, "none"
    factor = now.value / then.value
    label = f"{INDEX_SOURCE}@{then.geo_type}"
    if now.carried or then.carried:
        label += "+carried"
    return factor, label
