import logging
from contextlib import contextmanager
from sqlalchemy import select

from hb.db.models import PipelineRun
from hb.pipelines.base import JobRunner


def _run_with_failures(engine, n_items: int, n_fail: int) -> JobRunner:
    with JobRunner("test-job", engine) as runner:
        for i in range(n_items):
            with runner.item(f"item-{i}"):
                if i < n_fail:
                    raise ValueError(f"boom {i}")
                runner.items_upserted += 1
    return runner


def test_one_of_three_failing_is_partial(engine, session):
    runner = _run_with_failures(engine, 3, 1)
    assert runner.status == "partial"
    assert runner.items_seen == 3
    assert runner.items_upserted == 2

    row = session.execute(select(PipelineRun)).scalar_one()
    assert row.status == "partial"
    assert row.items_seen == 3
    assert "boom 0" in row.error_summary
    assert row.finished_at is not None


def test_all_failing_is_failed(engine):
    runner = _run_with_failures(engine, 3, 3)
    assert runner.status == "failed"


def test_no_failures_is_ok(engine):
    runner = _run_with_failures(engine, 3, 0)
    assert runner.status == "ok"


def test_job_level_exception_recorded_and_suppressed(engine, session):
    with JobRunner("test-job", engine):
        raise RuntimeError("total failure")
    row = session.execute(select(PipelineRun)).scalar_one()
    assert row.status == "failed"
    assert "total failure" in row.error_summary


def test_download_to_raw_reports_size_and_progress(engine, tmp_path, monkeypatch, caplog):
    """A bulk download says what it is fetching and how big, logs progress every
    PROGRESS_EVERY_BYTES, and a closing line: a 5.5 GB first run is not silent."""
    from hb import config
    from hb.pipelines import base

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(base, "PROGRESS_EVERY_BYTES", 3)
    chunks = [b"ab", b"cd", b"ef", b"g"]

    class Resp:
        headers = {"content-length": "7"}

        def raise_for_status(self):
            pass

        def iter_bytes(self, _size):
            yield from chunks

    @contextmanager
    def fake_stream(method, url, **_kw):
        assert (method, url) == ("GET", "https://x/f.gz")
        yield Resp()

    monkeypatch.setattr(base.httpx, "stream", fake_stream)
    with caplog.at_level(logging.INFO, logger="hb.pipelines.base"), \
            JobRunner("redfin-market", engine) as runner:
        path, digest = runner.download_to_raw("https://x/f.gz", "redfin", "f.gz")
    assert open(path, "rb").read() == b"abcdefg"
    assert len(digest) == 64
    lines = [r.getMessage() for r in caplog.records]
    assert "redfin-market: downloading f.gz (7 B)" in lines
    assert "redfin-market: f.gz: 4 B of 7 B" in lines  # the first 3-byte mark, passed at 4
    assert "redfin-market: f.gz: 6 B of 7 B" in lines
    assert "redfin-market: f.gz downloaded (7 B)" in lines
    assert base.human_size(5_900_000_000) == "5.5 GB"
    assert base.human_size(220_000_000) == "210 MB"
