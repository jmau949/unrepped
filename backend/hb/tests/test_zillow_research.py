import pytest
from sqlalchemy import func, select

from hb.db.models import PipelineRun, PriceIndex
from hb.pipelines import zillow_research
from hb.pipelines.base import JobRunner


def _zip_csv(values: dict[str, float]) -> bytes:
    months = ",".join(values)
    row = ",".join(str(v) for v in values.values())
    return (
        f"RegionID,RegionName,RegionType,StateName,{months}\n"
        f"1,94087,zip,CA,{row}\n"
        f"2,75201,zip,TX,{row}\n"  # non-target, filtered
    ).encode()


def test_melt_filters_and_shapes():
    csv = _zip_csv({"2026-05-31": 2400000.0, "2026-06-30": 2450000.0})
    long = zillow_research.melt_wide_csv(csv, "zip")
    assert set(long["geo_id"]) == {"94087"}
    assert list(long["month"]) == ["2026-05", "2026-06"]
    assert long["value"].tolist() == [2400000.0, 2450000.0]


def test_schema_drift_fails_loudly():
    with pytest.raises(RuntimeError, match="RegionName"):
        zillow_research.melt_wide_csv(b"Foo,Bar\n1,2\n", "zip")


def _patch_downloads(monkeypatch, tmp_path, csv_bytes: bytes, digest: str):
    def fake(self, url, source, name):
        p = tmp_path / f"{digest}-{name}"
        p.write_bytes(csv_bytes)
        return str(p), digest

    monkeypatch.setattr(JobRunner, "download_to_raw", fake)


def test_restated_history_replaced_not_duplicated(engine, session, tmp_path, monkeypatch):
    """Matrix D8: full re-download with restated values -> old rows replaced."""
    v1 = _zip_csv({"2026-05-31": 2400000.0, "2026-06-30": 2450000.0})
    _patch_downloads(monkeypatch, tmp_path, v1, "rel-1")
    assert zillow_research.run(engine) == "ok"

    # restated release: May value revised, July added
    v2 = _zip_csv({"2026-05-31": 2380000.0, "2026-06-30": 2450000.0, "2026-07-31": 2500000.0})
    _patch_downloads(monkeypatch, tmp_path, v2, "rel-2")
    assert zillow_research.run(engine) == "ok"

    rows = session.execute(
        select(PriceIndex).where(PriceIndex.source == "zhvi", PriceIndex.geo_id == "94087")
    ).scalars().all()
    by_month = {r.month: r.index_value for r in rows}
    assert len(by_month) == len(rows) == 3  # no duplicate months
    assert by_month["2026-05"] == 2380000.0  # revised value won


def test_unchanged_release_noops(engine, session, tmp_path, monkeypatch):
    csv = _zip_csv({"2026-06-30": 2450000.0})
    _patch_downloads(monkeypatch, tmp_path, csv, "same-digest")
    assert zillow_research.run(engine) == "ok"
    assert zillow_research.run(engine) == "noop"

    n = session.execute(select(func.count()).select_from(PriceIndex)).scalar_one()
    assert n == 1


def test_target_geography_change_reloads_the_same_release(
        engine, session, tmp_path, monkeypatch, set_geography):
    """Adding a ZIP must re-ingest the unchanged release so the new ZIP's rows
    land — the target geography is part of the fingerprint, not just the digest."""
    csv = _zip_csv({"2026-06-30": 2450000.0})
    _patch_downloads(monkeypatch, tmp_path, csv, "same-digest")
    assert zillow_research.run(engine) == "ok"
    assert zillow_research.run(engine) == "noop"

    set_geography(extra_zips=["75201"])
    assert zillow_research.run(engine) == "ok"
    geo_ids = set(session.execute(select(PriceIndex.geo_id)).scalars().all())
    assert geo_ids == {"94087", "75201"}


def test_download_failure_leaves_prior_data(engine, session, tmp_path, monkeypatch):
    csv = _zip_csv({"2026-06-30": 2450000.0})
    _patch_downloads(monkeypatch, tmp_path, csv, "good")
    assert zillow_research.run(engine) == "ok"

    def boom(self, url, source, name):
        raise RuntimeError("403 forbidden — URL drifted")

    monkeypatch.setattr(JobRunner, "download_to_raw", boom)
    assert zillow_research.run(engine) == "failed"

    # prior data intact
    n = session.execute(select(func.count()).select_from(PriceIndex)).scalar_one()
    assert n == 1
    failed = session.execute(
        select(PipelineRun).where(PipelineRun.status == "failed")
    ).scalar_one()
    assert "403" in failed.error_summary
