"""hazards-fetch pipeline — downloads the pack's layers, scoped to the geography."""

from pathlib import Path

from hb import geography
from hb.config import settings
from hb.pipelines import hazards_fetch

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_fetch(calls):
    def fetch(url, params):
        calls.append((url, params))
        return [{"type": "Feature", "properties": {"FLD_ZONE": "AE"},
                 "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    return fetch


def test_fetches_every_ca_layer_scoped_to_the_geography(engine, tmp_path, monkeypatch):
    monkeypatch.setattr("hb.config.settings.data_dir", tmp_path)
    calls: list = []
    monkeypatch.setattr(hazards_fetch, "fetch_layer", _fake_fetch(calls))

    assert hazards_fetch.run(engine) == "ok"

    files = sorted(p.name for p in (tmp_path / "raw" / "hazards").glob("*.geojson"))
    assert files == ["calfire_fhsz.geojson", "fault_zone.geojson", "fema_flood.geojson",
                     "liquefaction.geojson"]
    fema = next(p for u, p in calls if "NFHL" in u)
    assert "'06081C'" in fema["where"] and "'06085C'" in fema["where"]  # the two counties
    assert "SFHA_TF='T'" in fema["where"]
    fhsz = next(p for u, p in calls if "fhsz24_1" in u)
    assert fhsz["geometry"] == "-122.55,37.05,-121.2,37.95"  # [market].hazard_bbox
    assert fhsz["geometryType"] == "esriGeometryEnvelope"

    # byte-identical layers on a re-run leave the files alone: noop
    assert hazards_fetch.run(engine) == "noop"


def test_missing_only_fetches_just_the_layers_not_on_disk(engine, tmp_path, monkeypatch):
    """`make load` runs hazards-fetch --if-missing: a first run downloads every
    layer, a later run touches nothing — a network fetch is never spent on a
    layer whose file exists, even when upstream would have changed it."""
    monkeypatch.setattr("hb.config.settings.data_dir", tmp_path)
    folder = tmp_path / "raw" / "hazards"
    folder.mkdir(parents=True)
    (folder / "fema_flood.geojson").write_text("stale", encoding="utf-8")
    calls: list = []
    monkeypatch.setattr(hazards_fetch, "fetch_layer", _fake_fetch(calls))

    assert hazards_fetch.run(engine, missing_only=True) == "ok"
    assert not any("NFHL" in u for u, _ in calls)  # the file on disk was left alone
    assert (folder / "fema_flood.geojson").read_text(encoding="utf-8") == "stale"
    assert len(list(folder.glob("*.geojson"))) == 4

    calls.clear()
    assert hazards_fetch.run(engine, missing_only=True) == "noop"
    assert calls == []


def test_us_pack_fetches_fema_only(engine, tmp_path, monkeypatch):
    monkeypatch.setattr("hb.config.settings.data_dir", tmp_path)
    settings._geo = geography.load(FIXTURES / "geography_tx_minimal.toml", "x", FIXTURES)
    calls: list = []
    monkeypatch.setattr(hazards_fetch, "fetch_layer", _fake_fetch(calls))

    assert hazards_fetch.run(engine) == "ok"

    assert [p.name for p in (tmp_path / "raw" / "hazards").glob("*.geojson")] == ["fema_flood.geojson"]
    assert len(calls) == 1
    assert "'48453C'" in calls[0][1]["where"]  # Travis County, TX
