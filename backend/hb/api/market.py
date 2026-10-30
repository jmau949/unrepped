"""Market endpoints — docs/07-api-spec.md §Market."""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import MarketMetric, RateSnapshot
from hb.engine.supply import (
    DEFAULT_LIVE_WINDOW,
    LIVE_WINDOWS,
    classify_band,
    live_period,
    pct_rank,
    window_end,
)

router = APIRouter(prefix="/api/market", tags=["market"])

SUMMARY_METRICS = [
    "median_sale_price",
    "median_ppsf",
    "avg_sp_lp",
    "median_dom",
    "inventory",
    "months_supply",
    "months_supply_live",
]

# months_supply_live is ours, not Redfin's (docs/05 §3.5); 'derived_city' marks
# a ZIP too thin to stand on its own.
SUMMARY_SOURCES = ("redfin", "derived", "derived_city")

SUPPLY_HISTORY_YEARS = 3

LIVE_METRIC = "months_supply_live"


class TargetBand(BaseModel):
    min: int
    max: int


class ZipSummary(BaseModel):
    geo_id: str
    city: str | None
    metrics: dict[str, float | None]
    deltas_90d: dict[str, float | None]
    # per-metric provenance of the latest value: 'redfin' | 'derived' |
    # 'derived_city' (borrowed from the parent city because the ZIP was too thin)
    sources: dict[str, str | None]


class MarketSummary(BaseModel):
    target_band: TargetBand
    zips: list[ZipSummary]


class SeriesPoint(BaseModel):
    period_start: str
    value: float
    source: str


class RatePoint(BaseModel):
    date: str
    value: float


@router.get("/summary", response_model=MarketSummary)
def summary() -> MarketSummary:
    """Latest value per metric for the Dashboard tiles. The live series is
    stored once per trailing window; the Dashboard shows the default one."""
    with make_session() as session:
        rows = session.execute(
            select(
                MarketMetric.geo_id,
                MarketMetric.metric,
                MarketMetric.period,
                MarketMetric.period_start,
                MarketMetric.value,
                MarketMetric.source,
            ).where(
                MarketMetric.geo_type == "zip",
                MarketMetric.source.in_(SUMMARY_SOURCES),
                MarketMetric.metric.in_(SUMMARY_METRICS),
                MarketMetric.geo_id.in_(settings.target_zips),
            )
        ).all()

    default_period = live_period(DEFAULT_LIVE_WINDOW)
    # (geo_id, metric) -> sorted [(period_start, value, source)]
    series: dict[tuple[str, str], list[tuple[str, float, str]]] = {}
    for geo_id, metric, period, period_start, value, source in rows:
        if metric == LIVE_METRIC and period != default_period:
            continue
        series.setdefault((geo_id, metric), []).append((period_start, value, source))

    zips: list[ZipSummary] = []
    for zip_code in settings.target_zips:
        metrics: dict[str, float | None] = {}
        deltas: dict[str, float | None] = {}
        sources: dict[str, str | None] = {}
        for metric in SUMMARY_METRICS:
            points = sorted(series.get((zip_code, metric), []))
            if not points:
                metrics[metric] = deltas[metric] = sources[metric] = None
                continue
            latest_period, latest_value, latest_source = points[-1]
            metrics[metric] = latest_value
            sources[metric] = latest_source

            cutoff = (date.fromisoformat(latest_period) - timedelta(days=90)).isoformat()
            older = [v for p, v, _ in points if p <= cutoff]
            deltas[metric] = (
                round(latest_value / older[-1] - 1, 4) if older and older[-1] else None
            )
        if any(v is not None for v in metrics.values()):
            zips.append(
                ZipSummary(
                    geo_id=zip_code,
                    city=settings.geo.zip_to_city.get(zip_code),
                    metrics=metrics,
                    deltas_90d=deltas,
                    sources=sources,
                )
            )

    return MarketSummary(
        target_band=TargetBand(min=settings.target_price_min, max=settings.target_price_max),
        zips=zips,
    )


SUPPLY_METRICS = ("months_supply", LIVE_METRIC)


class SupplyGeo(BaseModel):
    geo_id: str
    city: str | None = None
    months_supply: float | None
    months_supply_basis: str | None
    months_supply_live: float | None
    months_supply_live_basis: str | None
    delta_90d: float | None
    pct_rank_3y: float | None
    band: str


class SupplyAsOf(BaseModel):
    redfin_window_start: str | None
    redfin_window_end: str | None
    live: str | None
    live_window_months: int


class SupplyResponse(BaseModel):
    as_of: SupplyAsOf
    zips: list[SupplyGeo]
    cities: list[SupplyGeo]


@router.get("/supply", response_model=SupplyResponse)
def supply(window: int = Query(default=DEFAULT_LIVE_WINDOW)) -> SupplyResponse:
    """Months of supply per target geo — docs/07 §Market, docs/08 §9.

    `months_supply` is Redfin's published rolling 3-month figure; `band`,
    `delta_90d` and `pct_rank_3y` describe that series. `months_supply_live`
    is this app's own now-cast over a trailing `window` of 3/6/9/12 calendar
    months (docs/05 §3.5) and stands on its own. `*_basis` is the row's
    source: 'redfin', 'derived', or 'derived_city' (borrowed from the parent
    city because the geo had too few closed sales to be meaningful).
    """
    if window not in LIVE_WINDOWS:
        raise HTTPException(
            status_code=422, detail=f"window must be one of {list(LIVE_WINDOWS)}"
        )
    period = live_period(window)

    with make_session() as session:
        rows = session.execute(
            select(
                MarketMetric.geo_type,
                MarketMetric.geo_id,
                MarketMetric.metric,
                MarketMetric.period,
                MarketMetric.period_start,
                MarketMetric.value,
                MarketMetric.source,
            ).where(
                MarketMetric.metric.in_(SUPPLY_METRICS),
                MarketMetric.geo_type.in_(("zip", "city")),
            )
        ).all()

    # (geo_type, geo_id, metric) -> sorted [(period_start, value, source)]
    series: dict[tuple[str, str, str], list[tuple[str, float, str]]] = {}
    for geo_type, geo_id, metric, row_period, period_start, value, source in rows:
        if metric == LIVE_METRIC and row_period != period:
            continue
        series.setdefault((geo_type, geo_id, metric), []).append((period_start, value, source))
    for points in series.values():
        points.sort()

    since = (date.today() - timedelta(days=365 * SUPPLY_HISTORY_YEARS)).isoformat()

    def build(geo_type: str, geo_id: str) -> SupplyGeo | None:
        history = series.get((geo_type, geo_id, "months_supply"), [])
        live = series.get((geo_type, geo_id, LIVE_METRIC), [])
        if not history and not live:
            return None

        mos = mos_basis = latest_period = None
        if history:
            latest_period, mos, mos_basis = history[-1]
        live_value = live_basis = None
        if live:
            _, live_value, live_basis = live[-1]

        delta = None
        if mos and latest_period:
            cutoff = (date.fromisoformat(latest_period) - timedelta(days=90)).isoformat()
            older = [v for p, v, _ in history if p <= cutoff]
            if older and older[-1]:
                delta = round(mos / older[-1] - 1, 4)

        return SupplyGeo(
            geo_id=geo_id,
            city=settings.geo.zip_to_city.get(geo_id) if geo_type == "zip" else None,
            months_supply=mos,
            months_supply_basis=mos_basis,
            months_supply_live=live_value,
            months_supply_live_basis=live_basis,
            delta_90d=delta,
            pct_rank_3y=pct_rank([v for p, v, _ in history if p >= since], mos),
            band=classify_band(mos if mos is not None else live_value),
        )

    zips = [g for z in settings.target_zips if (g := build("zip", z))]
    cities = [g for c in settings.target_cities if (g := build("city", c))]

    redfin_start = max(
        (pts[-1][0] for (gt, _, m), pts in series.items() if gt == "zip" and m == SUPPLY_METRICS[0]),
        default=None,
    )
    live_asof = max(
        (pts[-1][0] for (_, _, m), pts in series.items() if m == LIVE_METRIC),
        default=None,
    )

    return SupplyResponse(
        as_of=SupplyAsOf(
            redfin_window_start=redfin_start,
            redfin_window_end=window_end(redfin_start) if redfin_start else None,
            live=live_asof,
            live_window_months=window,
        ),
        zips=zips,
        cities=cities,
    )


@router.get("/series", response_model=list[SeriesPoint])
def get_series(
    geo_type: str = Query(...),
    geo_id: str = Query(...),
    metric: str = Query(...),
    period: str | None = Query(default=None),
    since: str | None = Query(default=None),
) -> list[SeriesPoint]:
    with make_session() as session:
        stmt = (
            select(MarketMetric.period_start, MarketMetric.value, MarketMetric.source)
            .where(
                MarketMetric.geo_type == geo_type,
                MarketMetric.geo_id == geo_id,
                MarketMetric.metric == metric,
            )
            .order_by(MarketMetric.period_start)
        )
        if period:
            stmt = stmt.where(MarketMetric.period == period)
        if since:
            stmt = stmt.where(MarketMetric.period_start >= since)
        rows = session.execute(stmt).all()
    return [SeriesPoint(period_start=p, value=v, source=s) for p, v, s in rows]


@router.get("/rates", response_model=list[RatePoint])
def get_rates(
    series: str = Query(default="MORTGAGE30US"),
    since: str | None = Query(default=None),
) -> list[RatePoint]:
    with make_session() as session:
        stmt = (
            select(RateSnapshot.date, RateSnapshot.value)
            .where(RateSnapshot.series == series)
            .order_by(RateSnapshot.date)
        )
        if since:
            stmt = stmt.where(RateSnapshot.date >= since)
        rows = session.execute(stmt).all()
    return [RatePoint(date=d, value=v) for d, v in rows]
