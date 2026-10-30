from datetime import date, timedelta

from hb.pipelines.raw_cache import prune_raw

TODAY = date(2026, 10, 26)


def _dated(root, source, days_ago, today=TODAY):
    folder = root / source / (today - timedelta(days=days_ago)).isoformat()
    folder.mkdir(parents=True)
    (folder / "file.csv").write_bytes(b"x")
    (folder / "file.csv.sha256").write_text("abc")
    return folder


def test_prune_removes_only_dated_folders_past_the_cutoff(tmp_path):
    old = _dated(tmp_path, "redfin", 120)
    boundary = _dated(tmp_path, "redfin", 90)
    recent = _dated(tmp_path, "zillow", 3)
    todays = _dated(tmp_path, "zillow", 0)
    hazards = tmp_path / "hazards"
    hazards.mkdir()
    (hazards / "fema_flood.geojson").write_text("{}")
    undated = tmp_path / "caaspp" / "latest"
    undated.mkdir(parents=True)
    stray_file = tmp_path / "zillow" / "notes.txt"
    stray_file.write_text("keep")

    removed = prune_raw(raw_dir=tmp_path, keep_days=90, today=TODAY)

    assert removed == [old]
    assert not old.exists()
    assert boundary.exists()  # exactly keep_days old is kept
    assert recent.exists() and todays.exists()
    assert (hazards / "fema_flood.geojson").exists()  # undated reference data
    assert undated.exists() and stray_file.exists()  # non-date names never pruned


def test_zero_keeps_everything(tmp_path):
    old = _dated(tmp_path, "redfin", 400)
    assert prune_raw(raw_dir=tmp_path, keep_days=0, today=TODAY) == []
    assert old.exists()


def test_missing_raw_dir_is_a_noop(tmp_path):
    assert prune_raw(raw_dir=tmp_path / "nope", keep_days=90, today=TODAY) == []


def test_defaults_come_from_settings(tmp_path, monkeypatch):
    from hb import config

    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "raw_keep_days", 10)
    old = _dated(tmp_path / "raw", "redfin", 11, today=date.today())
    kept = _dated(tmp_path / "raw", "redfin", 9, today=date.today())

    assert prune_raw() == [old]
    assert kept.exists()
