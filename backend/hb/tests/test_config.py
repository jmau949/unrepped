from pathlib import Path

import pytest

from hb import config, geography
from hb.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_checkout_geography(tmp_path, monkeypatch):
    """Settings() resolves geography.toml at the repo root: point that at an
    empty folder so a developer's own geography.toml or GEOGRAPHY_FILE never
    decides these tests."""
    monkeypatch.setattr(config, "_REPO_ROOT", tmp_path)
    monkeypatch.delenv("GEOGRAPHY_FILE", raising=False)
    monkeypatch.delenv("GEOGRAPHY", raising=False)


def test_packaged_default_geography_is_sf_peninsula():
    s = Settings(_env_file=None)
    assert s.geography == "sf_peninsula"
    assert s.geo.name == "SF Peninsula"
    assert s.geo.state == "CA" and s.geo.state_fips == "06"
    assert len(s.geo.cities) == 12
    assert len(s.geo.zips) == len(set(s.geo.zips)) == 27
    assert all(len(z) == 5 and z.isdigit() for z in s.geo.zips)


def test_target_properties_are_views_of_the_geography():
    s = Settings(_env_file=None)
    assert s.target_cities == s.geo.city_names
    assert s.target_zips == s.geo.zips
    assert s.timezone == "America/Los_Angeles"
    assert (s.target_price_min, s.target_price_max) == (2_000_000, 3_000_000)
    with pytest.raises(AttributeError):
        s.target_cities = ["Elsewhere"]  # read-only: edit the geography file instead


def test_geography_file_env_wins(monkeypatch):
    monkeypatch.setenv("GEOGRAPHY_FILE", str(FIXTURES / "geography_tx_minimal.toml"))
    s = Settings(_env_file=None)
    assert s.geo.state == "TX"
    assert s.target_cities == ["Austin", "Pflugerville"]
    assert s.timezone == "America/Chicago"


def test_geography_name_env_selects_a_packaged_example(monkeypatch):
    monkeypatch.setenv("GEOGRAPHY", "sf_peninsula")
    assert Settings(_env_file=None).geo.state == "CA"
    monkeypatch.setenv("GEOGRAPHY", "nowhere")
    with pytest.raises(FileNotFoundError, match="nowhere"):
        Settings(_env_file=None).geo


def test_repo_root_geography_toml_beats_the_packaged_default(tmp_path):
    (tmp_path / "geography.toml").write_text(
        (FIXTURES / "geography_tx_minimal.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    geo = geography.load(None, "sf_peninsula", tmp_path)
    assert geo.state == "TX"
    # and without the local file the packaged example is used
    assert geography.load(None, "sf_peninsula", tmp_path / "empty").state == "CA"


def test_relative_paths_anchor_to_backend(tmp_path):
    s = Settings(_env_file=None, data_dir=Path("./data"))
    assert s.data_dir.is_absolute() and s.data_dir.name == "data"
    assert s.data_dir.parent.name == "backend"


def test_db_path_derives_from_data_dir(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.db_path == tmp_path / "hb.sqlite3"
    assert s.photos_dir == tmp_path / "photos"


def test_db_path_explicit_override(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path, database_path=tmp_path / "x.db")
    assert s.db_path == tmp_path / "x.db"
