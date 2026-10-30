"""build-index pipeline — docs/05-pipelines.md §3.4.

Derives one monthly price index per target geo for CMA time adjustments
(docs/06 §3): 3-month-smoothed Redfin median $/sqft blended 50/50 with ZHVI,
normalized latest=1.0, with thin/gappy ZIP months borrowing city then county
values. Deterministic: same inputs -> same rows; output is truncate-and-replaced.
"""

import logging

import pandas as pd
from sqlalchemy import select

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import MarketMetric, PriceIndex
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

THIN_SALES_THRESHOLD = 5


def _monthly_normalized(df: pd.DataFrame, smooth: bool) -> dict[tuple, pd.Series]:
    """(geo_type, geo_id) -> monthly Series normalized so the latest month = 1.0."""
    out: dict[tuple, pd.Series] = {}
    if df.empty:
        return out
    for key, group in df.groupby(["geo_type", "geo_id"]):
        s = group.groupby("month")["value"].median().sort_index()
        if smooth:
            s = s.rolling(3, center=True, min_periods=1).median()
        s = s.dropna()
        if s.empty or s.iloc[-1] == 0:
            continue
        out[key] = s / s.iloc[-1]
    return out


def compute_blend(
    ppsf: pd.DataFrame,      # geo_type, geo_id, month, value (redfin median_ppsf)
    zhvi: pd.DataFrame,      # geo_type, geo_id, month, value
    homes_sold: pd.DataFrame,  # geo_type, geo_id, month, value
) -> list[dict]:
    """Pure function: input frames -> price_index 'blend' row dicts."""
    r_norm = _monthly_normalized(ppsf, smooth=True)
    z_norm = _monthly_normalized(zhvi, smooth=False)

    sold: dict[tuple, pd.Series] = {}
    if not homes_sold.empty:
        for key, group in homes_sold.groupby(["geo_type", "geo_id"]):
            sold[key] = group.groupby("month")["value"].median()

    blends: dict[tuple, pd.Series] = {}
    for key in sorted(set(r_norm) | set(z_norm), key=str):
        r, z = r_norm.get(key), z_norm.get(key)
        if r is not None and z is not None:
            blend = pd.concat([r, z], axis=1).mean(axis=1)  # 0.5/0.5 where both
        else:
            blend = (r if r is not None else z).copy()
        blends[key] = blend

    # thin/gap fallback for ZIPs: borrow city, then county, for months where the
    # ZIP has no value or too few underlying sales
    for key in list(blends):
        geo_type, geo_id = key
        if geo_type != "zip":
            continue
        city = settings.geo.zip_to_city.get(geo_id)
        county = settings.geo.city_to_county.get(city) if city else None
        parents = [
            blends.get(("city", city)) if city else None,
            blends.get(("county", county)) if county else None,
        ]
        parents = [p for p in parents if p is not None]
        if not parents:
            continue

        series = blends[key]
        months = parents[0].index.union(series.index)
        zip_sold = sold.get(key, pd.Series(dtype=float))
        values = {}
        for month in months:
            own = series.get(month)
            thin = pd.isna(zip_sold.get(month)) or zip_sold.get(month) < THIN_SALES_THRESHOLD
            if own is not None and not pd.isna(own) and not thin:
                values[month] = own
            else:
                fallback = next(
                    (p.get(month) for p in parents if p.get(month) is not None), own
                )
                if fallback is not None and not pd.isna(fallback):
                    values[month] = fallback
        result = pd.Series(values).sort_index().dropna()
        if not result.empty:
            blends[key] = result / result.iloc[-1]  # renormalize after substitution

    return [
        {
            "geo_type": key[0],
            "geo_id": key[1],
            "month": month,
            "index_value": round(float(value), 6),
            "source": "blend",
        }
        for key, series in sorted(blends.items(), key=lambda kv: str(kv[0]))
        for month, value in series.items()
    ]


def _load_metric(session, metric: str) -> pd.DataFrame:
    rows = session.execute(
        select(
            MarketMetric.geo_type,
            MarketMetric.geo_id,
            MarketMetric.period_start,
            MarketMetric.value,
        ).where(MarketMetric.metric == metric, MarketMetric.source == "redfin")
    ).all()
    df = pd.DataFrame(rows, columns=["geo_type", "geo_id", "period_start", "value"])
    if not df.empty:
        df["month"] = df["period_start"].str[:7]
    return df


def run(engine=None) -> str:
    with JobRunner("build-index", engine) as runner:
        session = make_session(runner.engine)
        try:
            ppsf = _load_metric(session, "median_ppsf")
            homes_sold = _load_metric(session, "homes_sold")
            zhvi_rows = session.execute(
                select(
                    PriceIndex.geo_type, PriceIndex.geo_id, PriceIndex.month, PriceIndex.index_value
                ).where(PriceIndex.source == "zhvi")
            ).all()
            zhvi = pd.DataFrame(zhvi_rows, columns=["geo_type", "geo_id", "month", "value"])

            with runner.item("blend"):
                rows = compute_blend(ppsf, zhvi, homes_sold)
                session.query(PriceIndex).filter(PriceIndex.source == "blend").delete()
                session.add_all(PriceIndex(**r) for r in rows)
                session.commit()
                runner.items_upserted = len(rows)
                log.info("build-index: %d blend rows across %d geos",
                         len(rows), len({(r['geo_type'], r['geo_id']) for r in rows}))
        finally:
            session.close()
    return runner.status
