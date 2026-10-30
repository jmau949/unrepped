"""zillow-research pipeline — docs/05-pipelines.md §3.2.

ZHVI (single-family, ZIP + city) and ZORI (ZIP) research CSVs. Zillow restates
the ENTIRE history each monthly release, so price_index rows from this source
are truncate-and-replaced, never diffed. Level values also land in
market_metrics as metric=zhvi/zori, source=zillow.
"""

import hashlib
import io
import logging

import pandas as pd

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import MarketMetric, PriceIndex
from hb.db.upsert import bulk_upsert
from hb.pipelines.base import JobRunner, geo_fingerprint

log = logging.getLogger(__name__)

def _files() -> list[tuple[str, str, str]]:
    """(dataset, geo_type, url) — URLs live in config, env-overridable, because
    they drift (docs/03 §1.2); failures leave prior data intact. ZORI has no
    single-family-only ZIP cut; sfrcondomfr (all homes) is the finest available."""
    return [
        ("zhvi", "zip", settings.zillow_zhvi_zip_url),
        ("zhvi", "city", settings.zillow_zhvi_city_url),
        ("zori", "zip", settings.zillow_zori_zip_url),
    ]

METRIC_KEY = ["geo_type", "geo_id", "period_start", "period", "metric", "source"]


def melt_wide_csv(csv_bytes: bytes, geo_type: str) -> pd.DataFrame:
    """Zillow wide format (RegionName + one column per month) -> long
    [geo_id, month(YYYY-MM), value], filtered to target geos."""
    df = pd.read_csv(io.BytesIO(csv_bytes), dtype={"RegionName": str})
    if "RegionName" not in df.columns:
        raise RuntimeError("zillow schema drift — RegionName column missing")

    if geo_type == "zip":
        df = df[df["RegionName"].isin(settings.target_zips)]
    else:
        state_col = "StateName" if "StateName" in df.columns else "State"
        df = df[
            df["RegionName"].isin(settings.target_cities)
            & (df[state_col].astype(str).str.strip().str.upper() == settings.geo.state)
        ]

    month_cols = [c for c in df.columns if c[:2] in ("19", "20") and "-" in c]
    if not month_cols:
        raise RuntimeError("zillow schema drift — no month columns found")

    long = df.melt(
        id_vars=["RegionName"], value_vars=month_cols, var_name="date", value_name="value"
    ).dropna(subset=["value"])
    long["month"] = long["date"].str[:7]  # YYYY-MM-DD -> YYYY-MM
    long = long.rename(columns={"RegionName": "geo_id"})
    return long[["geo_id", "month", "value"]]


def run(engine=None) -> str:
    with JobRunner("zillow-research", engine) as runner:
        downloads: list[tuple[str, str, bytes]] = []
        digests: list[str] = []
        for dataset, geo_type, url in _files():
            name = f"{dataset}_{geo_type}.csv"
            path, digest = runner.download_to_raw(url, "zillow", name)
            with open(path, "rb") as fh:
                downloads.append((dataset, geo_type, fh.read()))
            digests.append(digest)

        digests.append(geo_fingerprint())  # a new target ZIP/city must reload
        combined = hashlib.sha256("|".join(digests).encode()).hexdigest()
        previous = runner.last_content_hash()
        runner.content_hash = combined
        if combined == previous:
            runner.mark_noop()
        else:
            session = make_session(runner.engine)
            try:
                for dataset, geo_type, content in downloads:
                    with runner.item(f"{dataset}/{geo_type}"):
                        long = melt_wide_csv(content, geo_type)

                        if dataset == "zhvi":
                            # truncate-and-replace: history is restated upstream
                            session.query(PriceIndex).filter(
                                PriceIndex.source == "zhvi",
                                PriceIndex.geo_type == geo_type,
                            ).delete()
                            session.add_all(
                                PriceIndex(
                                    geo_type=geo_type,
                                    geo_id=r.geo_id,
                                    month=r.month,
                                    index_value=float(r.value),
                                    source="zhvi",
                                )
                                for r in long.itertuples(index=False)
                            )
                            runner.items_upserted += len(long)

                        metric_rows = [
                            {
                                "geo_type": geo_type,
                                "geo_id": r.geo_id,
                                "period_start": f"{r.month}-01",
                                "period": "monthly",
                                "metric": dataset,
                                "value": float(r.value),
                                "source": "zillow",
                            }
                            for r in long.itertuples(index=False)
                        ]
                        runner.items_upserted += bulk_upsert(
                            session, MarketMetric, metric_rows, METRIC_KEY
                        )
                        session.commit()
                        log.info("zillow %s/%s: %d months", dataset, geo_type, len(long))
            finally:
                session.close()
    return runner.status
