import logging

import pytest
from sqlalchemy import func, select

from hb.db.models import MarketMetric, PipelineRun
from hb.pipelines import redfin_market
from hb.pipelines.base import JobRunner

# The real files carry ~50 columns; the fixture keeps the ones the parser needs
# plus one it ignores, so an unexpected extra column is exercised too.
COLUMNS = [
    "LAST UPDATED", "FREQUENCY", "PERIOD BEGIN", "PERIOD END", "REGION ID", "REGION TYPE",
    "REGION NAME", "PROPERTY TYPE", "IS SEASONALLY ADJUSTED", "HOMES SOLD",
    "MEDIAN SALE PRICE NSA ($)", "MEDIAN DAYS ON MARKET (DAYS)",
    "AVERAGE SALE TO LIST RATIO (%)", "SHARE SOLD ABOVE ORIGINAL LIST (%)", "NEW LISTINGS",
    "INVENTORY", "MEDIAN NEW LISTING PRICE ($)", "MEDIAN SALE PRICE PER SQ.FT. ($)",
    "MONTHS OF SUPPLY", "PERCENT OFF MARKET IN TWO WEEKS (%)",
]


def _row(region_type, region_id, region, ptype="Single Family Residential", *,
         freq="Rolling 3 Months", begin="2026-06-01", end="2026-08-31", sold=14,
         price=2500000, dom=12, sp_lp=112.0, above=78.0, new=18, inv=20, list_price=2050000,
         ppsf=1400.5, mos=1.2, sa="false"):
    values = ["2026-09-03", freq, begin, end, region_id, region_type, region, ptype, sa, sold,
              price, dom, sp_lp, above, new, inv, list_price, ppsf, mos, "NA"]
    return ",".join(f'"{v}"' if isinstance(v, str) else str(v) for v in values)


HEADER = ",".join(f'"{c}"' for c in COLUMNS)
ROW_94087 = _row("Zip", "1", "94087")
ROW_CONDO = _row("Zip", "1", "94087", "Condo/Co-op", price=900000, mos=2.0)
ROW_OTHER_ZIP = _row("Zip", "2", "75201", price=600000)
ROW_CITY = _row("City", "19457", "Sunnyvale, CA", sold=60, inv=30, mos=1.5)
ROW_COUNTY = _row("County", "9", "Santa Clara County, CA", freq="Monthly",
                  begin="2026-08-01", end="2026-08-31", sold=400, inv=300, mos=0.8)


def _write(path, rows):
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def fixture_csv(tmp_path):
    return _write(tmp_path / "all_zips.csv", [ROW_94087, ROW_CONDO, ROW_OTHER_ZIP])


@pytest.fixture
def fixture_files(tmp_path, fixture_csv):
    """One fixture per Redfin file, keyed the way run() names its downloads."""
    return {
        "all_zips.csv": fixture_csv,
        "all_cities.csv": _write(tmp_path / "all_cities.csv", [ROW_CITY]),
        "all_counties.csv": _write(tmp_path / "all_counties.csv", [ROW_COUNTY]),
    }


def test_parse_tracker_mapping(fixture_csv):
    rows = redfin_market.parse_tracker(fixture_csv, "zip")

    # only the target-ZIP single-family row survives; one row per metric
    assert len(rows) == len(redfin_market.COLUMN_MAP)
    assert {r["geo_id"] for r in rows} == {"94087"}
    by_metric = {r["metric"]: r for r in rows}
    # percent columns land as fractions
    assert by_metric["avg_sp_lp"]["value"] == pytest.approx(1.12)
    assert by_metric["pct_sold_above_list"]["value"] == pytest.approx(0.78)
    assert by_metric["months_supply"]["value"] == pytest.approx(1.2)
    assert by_metric["median_list_price"]["value"] == pytest.approx(2050000)
    # rolling 3-month window => period '3m', labelled by window start
    assert all(r["period"] == "3m" for r in rows)
    assert all(r["period_start"] == "2026-06-01" for r in rows)
    assert all(r["source"] == "redfin" for r in rows)


def test_parse_tracker_keeps_leading_zeros_and_na_is_null(tmp_path, set_geography):
    set_geography(extra_zips=["07002"])
    path = _write(tmp_path / "all_zips.csv", [_row("Zip", "3", "07002", mos="NA")])
    rows = redfin_market.parse_tracker(path, "zip")
    assert {r["geo_id"] for r in rows} == {"07002"}
    assert "months_supply" not in {r["metric"] for r in rows}


def test_parse_tracker_city_and_county_windows(fixture_files):
    city_rows = redfin_market.parse_tracker(fixture_files["all_cities.csv"], "city")
    assert {r["geo_id"] for r in city_rows} == {"Sunnyvale"}
    assert {r["period"] for r in city_rows} == {"3m"}
    county_rows = redfin_market.parse_tracker(fixture_files["all_counties.csv"], "county")
    assert {r["geo_id"] for r in county_rows} == {"Santa Clara County"}
    assert {r["period"] for r in county_rows} == {"monthly"}
    assert {r["period_start"] for r in county_rows} == {"2026-08-01"}


def test_parse_tracker_drops_the_namesake_city(tmp_path):
    """Redfin has two 'Mountain View, CA' region ids; the real city out-sells
    the namesake every window, so it is the one kept."""
    rows = [
        _row("City", "12739", "Mountain View, CA", sold=50, mos=0.9),
        _row("City", "24455", "Mountain View, CA", sold=5, mos=2.6),
        _row("City", "12739", "Mountain View, CA", begin="2026-05-01", end="2026-07-31",
             sold=66, mos=1.0),
        _row("City", "24455", "Mountain View, CA", begin="2026-05-01", end="2026-07-31",
             sold=8, mos=1.5),
    ]
    parsed = redfin_market.parse_tracker(_write(tmp_path / "all_cities.csv", rows), "city")
    mos = {r["period_start"]: r["value"] for r in parsed if r["metric"] == "months_supply"}
    assert mos == {"2026-06-01": 0.9, "2026-05-01": 1.0}


def test_parse_tracker_missing_column_fails_loudly(tmp_path):
    header = HEADER.replace(',"MEDIAN SALE PRICE PER SQ.FT. ($)"', "")
    row = ROW_94087.replace(",1400.5", "")
    path = tmp_path / "bad.csv"
    path.write_text(header + "\n" + row + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"MEDIAN SALE PRICE PER SQ\.FT"):
        redfin_market.parse_tracker(str(path), "zip")


def test_parse_tracker_unknown_frequency_fails_loudly(tmp_path):
    path = _write(tmp_path / "all_zips.csv", [_row("Zip", "1", "94087", freq="Weekly")])
    with pytest.raises(RuntimeError, match="Weekly"):
        redfin_market.parse_tracker(path, "zip")


def _patch_remote(monkeypatch, files: dict[str, str], signature: str) -> list[str]:
    """Stub the HEAD signature and the download; returns the download log."""
    monkeypatch.setattr(redfin_market, "fetch_signature", lambda url: signature)
    downloads: list[str] = []

    def fake(self, url, source, name):
        downloads.append(name)
        return files[name], "unused"

    monkeypatch.setattr(JobRunner, "download_to_raw", fake)
    return downloads


def _count(session) -> int:
    return session.execute(select(func.count()).select_from(MarketMetric)).scalar_one()


def test_run_rerun_is_stable_and_noop_without_downloading(engine, session, fixture_files, monkeypatch):
    # first run with signature A downloads and ingests one SFR row per level
    downloads = _patch_remote(monkeypatch, fixture_files, "etag-a")
    assert redfin_market.run(engine) == "ok"
    assert sorted(downloads) == sorted(fixture_files)
    count_after_first = _count(session)
    assert count_after_first == 3 * len(redfin_market.COLUMN_MAP)

    # same signatures again -> noop, and nothing was downloaded (matrix D2)
    assert redfin_market.run(engine) == "noop"
    assert len(downloads) == len(fixture_files)

    # changed signature but identical data -> re-ingest, still same rows (matrix D1)
    _patch_remote(monkeypatch, fixture_files, "etag-b")
    assert redfin_market.run(engine) == "ok"
    assert _count(session) == count_after_first

    statuses = session.execute(select(PipelineRun.status)).scalars().all()
    assert statuses == ["ok", "noop", "ok"]


def test_run_says_how_much_it_is_about_to_download(engine, fixture_files, monkeypatch, caplog):
    """A first run downloads ~5.5 GB; it says how many files and how big before
    it starts (the Content-Length from the HEAD signatures), not silence."""
    _patch_remote(monkeypatch, fixture_files, "etag|Mon, 01 Jan 2026|1073741824")
    with caplog.at_level(logging.INFO, logger="hb.pipelines.redfin_market"):
        assert redfin_market.run(engine) == "ok"
    assert any("3 files to download, about 3.0 GB" in r.getMessage()
               for r in caplog.records)

    assert redfin_market._total_bytes(["etag-a", "zips|cities"]) == 0  # unknown sizes


def test_run_reloads_when_the_target_geography_changes(
        engine, session, fixture_files, monkeypatch, set_geography):
    """Adding a ZIP or city must re-download the unchanged release — the target
    geography is part of the fingerprint, not just Redfin's ETags."""
    downloads = _patch_remote(monkeypatch, fixture_files, "etag-a")
    assert redfin_market.run(engine) == "ok"
    assert redfin_market.run(engine) == "noop"
    assert len(downloads) == len(fixture_files)

    set_geography(extra_zips=["94027"])
    assert redfin_market.run(engine) == "ok"
    assert len(downloads) == 2 * len(fixture_files)


def test_run_never_wipes_a_level_that_matched_nothing(engine, session, fixture_files, monkeypatch):
    """The zip fixture standing in for the city file matches no target city:
    that level is an item failure (partial) and its existing rows survive."""
    session.add(MarketMetric(
        geo_type="city", geo_id="Sunnyvale", period_start="2026-05-01", period="3m",
        metric="months_supply", value=1.4, source="redfin",
    ))
    session.commit()
    files = {**fixture_files, "all_cities.csv": fixture_files["all_zips.csv"]}
    _patch_remote(monkeypatch, files, "etag-a")

    assert redfin_market.run(engine) == "partial"
    city = session.execute(
        select(MarketMetric).where(MarketMetric.geo_type == "city")
    ).scalars().all()
    assert [(r.period_start, r.value) for r in city] == [("2026-05-01", 1.4)]
    assert _count(session) == 1 + 2 * len(redfin_market.COLUMN_MAP)


def test_run_replaces_the_restated_history(engine, session, fixture_files, monkeypatch):
    """Redfin restates every release, so a stale published row (old window
    label, old value) must not survive next to the fresh one — while derived
    rows, which belong to market-supply, are left alone."""
    session.add(MarketMetric(
        geo_type="zip", geo_id="94087", period_start="2026-06-01", period="monthly",
        metric="months_supply", value=9.9, source="redfin",
    ))
    session.add(MarketMetric(
        geo_type="zip", geo_id="94087", period_start="2026-09-01", period="3m",
        metric="months_supply_live", value=0.5, source="derived",
    ))
    session.commit()
    _patch_remote(monkeypatch, fixture_files, "etag-a")
    assert redfin_market.run(engine) == "ok"

    rows = session.execute(
        select(MarketMetric).where(MarketMetric.geo_id == "94087")
    ).scalars().all()
    by_key = {(r.metric, r.source, r.period): r.value for r in rows}
    assert ("months_supply", "redfin", "monthly") not in by_key
    assert by_key[("months_supply", "redfin", "3m")] == pytest.approx(1.2)
    assert by_key[("months_supply_live", "derived", "3m")] == pytest.approx(0.5)
