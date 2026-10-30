import pytest
from sqlalchemy.orm import Session, sessionmaker

import hb.schools_match
from hb import geography
from hb.config import settings
from hb.db.engine import make_engine
from hb.db.models import Base
from hb.geography import Geography

TEST_GEOGRAPHY = "sf_peninsula"


@pytest.fixture(autouse=True)
def _pinned_geography():
    """Every test runs against the packaged SF Peninsula example — never the
    developer's geography.toml or GEOGRAPHY_FILE — and starts from a fresh copy,
    so a test that narrows the geography cannot leak into the next one."""
    settings._geo = geography.load_packaged(TEST_GEOGRAPHY)
    yield


@pytest.fixture
def set_geography():
    """Narrow the pinned geography to `cities`, and/or bolt `extra_zips` on as a
    synthetic city in the first county — the replacement for monkeypatching
    `settings.target_cities` / `target_zips`, which are now read-only views."""

    def _set(*, cities: list[str] | None = None, extra_zips: list[str] | None = None) -> Geography:
        data = settings.geo.model_dump(by_alias=True)
        if cities is not None:
            data["cities"] = [c for c in data["cities"] if c["name"] in cities]
        if extra_zips:
            data["cities"].append({
                "name": "Test City", "county": data["counties"][0]["name"],
                "zips": list(extra_zips),
            })
        settings._geo = Geography.model_validate(data)
        return settings._geo

    return _set


@pytest.fixture(autouse=True)
def _reset_schools_match_cache():
    """The district STRtree is cached per process keyed on (count, max
    updated_at) — two test DBs can collide on that key, so always start cold."""
    hb.schools_match._cache = None


@pytest.fixture(autouse=True)
def _no_live_open_houses(monkeypatch):
    """listing-scan runs the open-houses job in its tail; keep every test off
    the network unless it stubs the source itself."""
    import hb.open_houses.sources.realtor as realtor
    import hb.open_houses.sources.redfin as redfin

    monkeypatch.setattr(realtor, "fetch_properties", lambda city: [])
    monkeypatch.setattr(redfin, "fetch_gis", lambda params: {"homes": []})


@pytest.fixture
def engine(tmp_path):
    """Fresh throwaway SQLite DB with the full schema (fast create_all path)."""
    eng = make_engine(tmp_path / "test.sqlite3")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine) -> Session:
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
