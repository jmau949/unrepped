"""redfin-market pipeline — docs/05-pipelines.md §3.1.

Downloads the Redfin Data Center property-type market CSVs (zip/city/county),
filters to target geos + single-family with DuckDB before anything touches
SQLite, and truncate-and-replaces the `source='redfin'` rows in market_metrics
per geo level — Redfin restates the whole history on every release. Daily
schedule; upstream updates weekly, so the job first compares the S3 objects'
ETag/Last-Modified signatures against the last run and no-ops without
downloading ~5.5 GB when nothing changed.
"""

import hashlib
import logging

import duckdb
import httpx
import pandas as pd

from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import MarketMetric
from hb.db.upsert import bulk_upsert
from hb.pipelines.base import JobRunner, geo_fingerprint, human_size

log = logging.getLogger(__name__)

S3 = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/property_types/monthly"
FILES = {
    "zip": f"{S3}/all_zips.csv",
    "city": f"{S3}/all_cities.csv",
    "county": f"{S3}/all_counties.csv",
}

# Redfin CSV column -> (our metric vocabulary, scale). Redfin publishes the
# ratio columns in percent; market_metrics stores fractions (docs/04), so
# 109.4 -> 1.094.
COLUMN_MAP: dict[str, tuple[str, float]] = {
    "MEDIAN SALE PRICE NSA ($)": ("median_sale_price", 1),
    "MEDIAN NEW LISTING PRICE ($)": ("median_list_price", 1),
    "MEDIAN SALE PRICE PER SQ.FT. ($)": ("median_ppsf", 1),
    "HOMES SOLD": ("homes_sold", 1),
    "INVENTORY": ("inventory", 1),
    "NEW LISTINGS": ("new_listings", 1),
    "MEDIAN DAYS ON MARKET (DAYS)": ("median_dom", 1),
    "AVERAGE SALE TO LIST RATIO (%)": ("avg_sp_lp", 0.01),
    "SHARE SOLD ABOVE ORIGINAL LIST (%)": ("pct_sold_above_list", 0.01),
    "MONTHS OF SUPPLY": ("months_supply", 1),
}
DIMENSION_COLS = {
    "REGION NAME": "region",
    "REGION ID": "region_id",
    "FREQUENCY": "frequency",
    "PERIOD BEGIN": "period_begin",
    "PERIOD END": "period_end",
}
FILTER_COLS = ("PROPERTY TYPE", "IS SEASONALLY ADJUSTED")

# Redfin FREQUENCY -> market_metrics.period, which records window length
# (docs/04). ZIP and city files are rolling 3-month windows, counties monthly.
PERIODS = {"Monthly": "monthly", "Rolling 3 Months": "3m"}

KEY_COLS = ["geo_type", "geo_id", "period_start", "period", "metric", "source"]

PROPERTY_TYPE = "Single Family Residential"


def _region_values(geo_type: str) -> list[str]:
    if geo_type == "zip":
        return list(settings.target_zips)
    if geo_type == "city":
        return [f"{c}, {settings.geo.state}" for c in settings.target_cities]
    return [f"{c}, {settings.geo.state}" for c in settings.geo.county_names]


def _geo_id(geo_type: str, region: str) -> str:
    if geo_type == "zip":
        return region.strip()
    return region.rsplit(",", 1)[0].strip()  # strip the trailing ", <state>"


def _read_csv(path: str) -> str:
    # all_varchar: DuckDB would otherwise sniff ZIP names as integers and drop
    # the leading zero of e.g. "07002"; numerics are coerced in pandas below.
    return f"read_csv('{path}', header=true, nullstr='NA', all_varchar=true)"


def parse_tracker(path: str, geo_type: str) -> list[dict]:
    """One Redfin CSV -> tidy market_metrics row dicts. Raises RuntimeError on
    upstream drift — missing columns or an unknown FREQUENCY — rather than
    ingesting rows whose window semantics are unknown (docs/03 §1.1).
    """
    con = duckdb.connect()
    try:
        available = {
            r[0].upper()
            for r in con.execute(f"DESCRIBE SELECT * FROM {_read_csv(path)}").fetchall()
        }
        needed = set(COLUMN_MAP) | set(DIMENSION_COLS) | set(FILTER_COLS)
        missing = sorted(needed - available)
        if missing:
            raise RuntimeError(f"redfin schema drift — missing columns: {', '.join(missing)}")

        quoted = ["'" + r.replace("'", "''") + "'" for r in _region_values(geo_type)]
        aliases = [*DIMENSION_COLS.items(), *((c, m) for c, (m, _) in COLUMN_MAP.items())]
        selected = ", ".join(f'"{col}" AS {alias}' for col, alias in aliases)
        df = con.execute(
            f"""
            SELECT {selected}
            FROM {_read_csv(path)}
            WHERE "PROPERTY TYPE" = '{PROPERTY_TYPE}'
              AND "REGION NAME" IN ({", ".join(quoted)})
              AND lower("IS SEASONALLY ADJUSTED") = 'false'
            """
        ).df()
    finally:
        con.close()

    # A city or county that matches nothing is almost always spelled differently
    # from Redfin's region name — say so instead of silently storing nothing.
    if geo_type != "zip":
        matched = set(df["region"]) if not df.empty else set()
        for region in _region_values(geo_type):
            if region not in matched:
                log.warning("redfin-market: no %s rows for %r — check the spelling "
                            "against Redfin's region names", geo_type, region)

    if df.empty:
        return []

    for metric, _ in COLUMN_MAP.values():
        df[metric] = pd.to_numeric(df[metric], errors="coerce")

    unknown = sorted(set(df["frequency"]) - set(PERIODS))
    if unknown:
        raise RuntimeError(f"redfin schema drift — unknown FREQUENCY: {', '.join(unknown)}")
    df["period"] = df["frequency"].map(PERIODS)

    # Redfin keys regions by id, and a name can cover a namesake elsewhere in
    # the state ("Mountain View, CA" is two region ids). Keep, per name, the id
    # with the most closed sales over the whole history — the actual city.
    totals = df.groupby(["region", "region_id"], as_index=False)["homes_sold"].sum()
    keep = totals.sort_values("homes_sold").drop_duplicates("region", keep="last")
    df = df.merge(keep[["region", "region_id"]], on=["region", "region_id"])
    # one row per key: keep the freshest window should periods ever overlap
    df = df.sort_values("period_end").drop_duplicates(
        subset=["region", "period_begin", "period"], keep="last"
    )

    df["geo_id"] = df["region"].map(lambda r: _geo_id(geo_type, r))
    df["period_start"] = pd.to_datetime(df["period_begin"]).dt.date.astype(str)

    rows: list[dict] = []
    for metric, scale in COLUMN_MAP.values():
        sub = df[["geo_id", "period_start", "period", metric]].dropna(subset=[metric])
        rows.extend(
            {
                "geo_type": geo_type,
                "geo_id": r.geo_id,
                "period_start": r.period_start,
                "period": r.period,
                "metric": metric,
                "value": round(float(getattr(r, metric)) * scale, 6),
                "source": "redfin",
            }
            for r in sub.itertuples(index=False)
        )
    return rows


def fetch_signature(url: str) -> str:
    """What changes when Redfin republishes an object: ETag, Last-Modified and
    size from a HEAD request. Tests monkeypatch this seam.
    """
    resp = httpx.head(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    headers = resp.headers
    return "|".join(headers.get(h, "") for h in ("etag", "last-modified", "content-length"))


def _replace(session, geo_type: str, rows: list[dict]) -> int:
    """Truncate-and-replace every published Redfin row for one geo level.

    Redfin restates history on each release, so the previous rows are simply
    wrong once a new file lands — and dropping the whole level also clears
    geos that have since left the target list. Derived rows (`market-supply`)
    are never touched.
    """
    session.query(MarketMetric).filter(
        MarketMetric.source == "redfin", MarketMetric.geo_type == geo_type
    ).delete(synchronize_session=False)
    return bulk_upsert(session, MarketMetric, rows, KEY_COLS)


def _total_bytes(signatures: list[str]) -> int:
    """The Content-Length sum folded into the HEAD signatures; 0 when unknown."""
    total = 0
    for sig in signatures:
        parts = sig.split("|")
        if len(parts) == 3 and parts[2].isdigit():
            total += int(parts[2])
    return total


def run(engine=None) -> str:
    with JobRunner("redfin-market", engine) as runner:
        signatures = [fetch_signature(url) for url in FILES.values()]
        signatures.append(geo_fingerprint())  # a new target ZIP/city must reload
        runner.content_hash = hashlib.sha256("|".join(signatures).encode()).hexdigest()
        if runner.content_hash == runner.last_content_hash():
            runner.mark_noop()  # status finalized by __exit__; return AFTER the with-block
        else:
            total = _total_bytes(signatures)
            log.info("redfin-market: %d files to download, %s", len(FILES),
                     f"about {human_size(total)}" if total else "several GB")
            paths = {
                geo_type: runner.download_to_raw(url, "redfin", url.rsplit("/", 1)[-1])[0]
                for geo_type, url in FILES.items()
            }
            session = make_session(runner.engine)
            try:
                for geo_type, path in paths.items():
                    with runner.item(geo_type):
                        rows = parse_tracker(path, geo_type)
                        if not rows:
                            # replacing with nothing would wipe the level; the
                            # region naming has probably drifted upstream
                            raise RuntimeError("no rows matched the target geos")
                        runner.items_upserted += _replace(session, geo_type, rows)
                        session.commit()
                        log.info("redfin-market %s: %d tidy rows", geo_type, len(rows))
            finally:
                session.close()
    return runner.status
