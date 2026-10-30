from hb.pipelines.base import JobRunner


def test_same_bytes_twice_reports_unchanged(engine, tmp_path, monkeypatch):
    from hb import config

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)

    with JobRunner("hash-job", engine) as r1:
        path, changed = r1.save_raw("testsrc", "file.tsv.gz", b"same bytes")
        assert changed is True  # no prior run
    assert r1.status == "ok"

    with JobRunner("hash-job", engine) as r2:
        _, changed = r2.save_raw("testsrc", "file.tsv.gz", b"same bytes")
        assert changed is False
        r2.mark_noop()
    assert r2.status == "noop"

    with JobRunner("hash-job", engine) as r3:
        _, changed = r3.save_raw("testsrc", "file.tsv.gz", b"DIFFERENT bytes")
        assert changed is True
    assert r3.status == "ok"


def test_sidecar_written(engine, tmp_path, monkeypatch):
    from hb import config

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)

    with JobRunner("hash-job2", engine) as r:
        path, _ = r.save_raw("testsrc", "x.csv", b"abc")
    sidecar = tmp_path / "raw"
    sidecars = list(sidecar.rglob("x.csv.sha256"))
    assert len(sidecars) == 1
    assert len(sidecars[0].read_text()) == 64
