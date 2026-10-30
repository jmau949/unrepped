import pandas as pd
import pytest
from sqlalchemy import func, select

from hb.db.models import MarketMetric, PriceIndex
from hb.pipelines import build_index


def _df(rows, cols=("geo_type", "geo_id", "month", "value")):
    return pd.DataFrame(rows, columns=list(cols))


def test_blend_is_mean_of_normalized_sources():
    ppsf = _df([("zip", "94087", m, v) for m, v in
                [("2026-04", 1300.0), ("2026-05", 1350.0), ("2026-06", 1400.0)]])
    zhvi = _df([("zip", "94087", m, v) for m, v in
                [("2026-04", 2400000.0), ("2026-05", 2450000.0), ("2026-06", 2500000.0)]])
    sold = _df([("zip", "94087", m, 20.0) for m in ["2026-04", "2026-05", "2026-06"]])

    rows = build_index.compute_blend(ppsf, zhvi, sold)
    by_month = {r["month"]: r["index_value"] for r in rows}

    assert by_month["2026-06"] == pytest.approx(1.0)
    # April: ppsf smoothed (rolling-3 centered median of 1300,1350 -> 1325) /1375(last smoothed)
    # keep the assertion structural: April strictly below June, May between
    assert by_month["2026-04"] < by_month["2026-05"] < by_month["2026-06"]
    # blend is mean of two normalized sources: April zhvi = 0.96, so blend must
    # sit between the two source values for April
    assert 0.94 < by_month["2026-04"] < 1.0


def test_single_source_geo_uses_that_source():
    zhvi = _df([("city", "Sunnyvale", "2026-05", 2400000.0), ("city", "Sunnyvale", "2026-06", 2440000.0)])
    rows = build_index.compute_blend(_df([]), zhvi, _df([]))
    by_month = {r["month"]: r["index_value"] for r in rows}
    assert by_month["2026-06"] == pytest.approx(1.0)
    assert by_month["2026-05"] == pytest.approx(2400000.0 / 2440000.0, rel=1e-6)


def test_thin_zip_month_borrows_city_value():
    months = ["2026-04", "2026-05", "2026-06"]
    ppsf = _df(
        [("zip", "94087", m, v) for m, v in zip(months, [1000.0, 5000.0, 1010.0])]  # May is a 2-sale outlier
        + [("city", "Sunnyvale", m, v) for m, v in zip(months, [1000.0, 1005.0, 1010.0])]
    )
    sold = _df(
        [("zip", "94087", m, v) for m, v in zip(months, [20.0, 2.0, 20.0])]  # May thin
        + [("city", "Sunnyvale", m, 200.0) for m in months]
    )
    rows = build_index.compute_blend(ppsf, _df([]), sold)
    zip_rows = {r["month"]: r["index_value"] for r in rows if r["geo_type"] == "zip"}
    city_rows = {r["month"]: r["index_value"] for r in rows if r["geo_type"] == "city"}

    # thin May borrowed the city's May index value (before renormalization both
    # series end at 1.0, so the values match directly)
    assert zip_rows["2026-05"] == pytest.approx(city_rows["2026-05"], rel=1e-6)


def test_deterministic():
    ppsf = _df([("zip", "94301", "2026-05", 2000.0), ("zip", "94301", "2026-06", 2050.0)])
    rows1 = build_index.compute_blend(ppsf, _df([]), _df([]))
    rows2 = build_index.compute_blend(ppsf, _df([]), _df([]))
    assert rows1 == rows2


def test_run_truncate_replaces(engine, session):
    session.add_all([
        MarketMetric(geo_type="zip", geo_id="94087", period_start=f"2026-0{m}-01",
                     period="monthly", metric="median_ppsf", value=1300.0 + m,
                     source="redfin")
        for m in (4, 5, 6)
    ])
    session.add(PriceIndex(geo_type="zip", geo_id="94087", month="2026-01",
                           index_value=99.0, source="blend"))  # stale row to be replaced
    session.commit()

    assert build_index.run(engine) == "ok"
    assert build_index.run(engine) == "ok"  # idempotent re-run

    rows = session.execute(
        select(PriceIndex).where(PriceIndex.source == "blend")
    ).scalars().all()
    months = sorted(r.month for r in rows)
    assert months == ["2026-04", "2026-05", "2026-06"]  # stale 2026-01 gone, no dups
    n_zhvi = session.execute(
        select(func.count()).select_from(PriceIndex).where(PriceIndex.source == "zhvi")
    ).scalar_one()
    assert n_zhvi == 0  # zhvi rows untouched (none existed)
