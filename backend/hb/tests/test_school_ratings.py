import pandas as pd
from sqlalchemy import select

from hb.db.engine import make_session
from hb.db.models import School, SchoolRatingSnapshot
from hb.pipelines import school_ratings as sr


def test_norm():
    assert sr._norm("Cherry Chase Elementary") == "cherrychaseelementary"
    assert sr._norm("O'Farrell (Ernest R.)") == "ofarrellernestr"
    assert sr._norm(None) == ""


def test_aggregate_pct(tmp_path):
    p = tmp_path / "results.txt"
    p.write_text("\n".join([
        "County Code^District Code^School Code^School Name^Test ID^Student Group ID^Grade^Percentage Standard Met and Above",
        "01^00001^0000001^Alpha Elementary^1^1^13^80.0",   # ELA, all students, all grades
        "01^00001^0000001^Alpha Elementary^2^1^13^60.0",   # Math -> avg 70
        "01^00001^0000001^Alpha Elementary^1^7^13^99.0",   # subgroup 7 -> filtered
        "01^00001^0000000^District Office^1^1^13^50.0",    # district row -> filtered
        "01^00001^0000002^Beta High^1^1^13^40.0",          # ELA only -> 40
    ]), encoding="latin-1")
    df = sr._aggregate_pct(str(p)).sort_values("scode").reset_index(drop=True)
    assert list(df["sch_name"]) == ["Alpha Elementary", "Beta High"]
    assert df.loc[0, "pct"] == 70.0 and df.loc[1, "pct"] == 40.0


def test_zip_by_cds(tmp_path):
    p = tmp_path / "entities.txt"
    p.write_text("\n".join([
        "County Code^District Code^School Code^Type ID^Filler^Test Year^County Name^District Name^School Name^Zip Code",
        "01^00001^0000001^7^^2024^Alameda^Test USD^Alpha Elementary^94010-1234",
        "01^00001^0000002^7^^2024^Alameda^Test USD^Beta High^94010",
    ]), encoding="latin-1")
    m = sr._zip_by_cds(str(p))
    assert m[("01", "00001", "0000001")] == "94010"
    assert m[("01", "00001", "0000002")] == "94010"


def test_build_rating_lookup_deciles():
    df = pd.DataFrame([
        {"cc": "01", "dc": "1", "scode": "1", "sch_name": "Alpha Elementary", "pct": 70.0},
        {"cc": "01", "dc": "1", "scode": "2", "sch_name": "Beta High", "pct": 40.0},
        {"cc": "01", "dc": "1", "scode": "3", "sch_name": "Gamma Middle", "pct": 90.0},
    ])
    zbc = {("01", "1", "1"): "94010", ("01", "1", "2"): "94010", ("01", "1", "3"): "94010"}
    lookup = sr._build_rating_lookup(df, zbc)  # (zip, name) -> (rating, pct_met)
    assert all(1 <= rating <= 10 for rating, _ in lookup.values())
    # higher %-met -> higher rating
    assert lookup[("94010", "betahigh")][0] < lookup[("94010", "alphaelementary")][0] \
        < lookup[("94010", "gammamiddle")][0]
    assert lookup[("94010", "alphaelementary")][1] == 70.0  # raw %-met carried through


def test_run_rates_matched_and_noops(engine, monkeypatch):
    df = pd.DataFrame([
        {"cc": "01", "dc": "1", "scode": "1", "sch_name": "Alpha Elementary", "pct": 90.0},
        {"cc": "01", "dc": "1", "scode": "2", "sch_name": "Beta High", "pct": 30.0},
    ])
    zbc = {("01", "1", "1"): "94010", ("01", "1", "2"): "94010"}
    monkeypatch.setattr(sr, "fetch_caaspp", lambda runner: (df, zbc, "digest-v1"))

    with make_session(engine) as s:
        s.add_all([
            School(nces_id="A", name="Alpha Elementary", level="elementary", lat=1, lon=1, zip="94010"),
            School(nces_id="B", name="Beta High", level="high", lat=1, lon=1, zip="94010"),
            School(nces_id="C", name="Unmatched", level="middle", lat=1, lon=1, zip="99999"),
        ])
        s.commit()

    assert sr.run(engine) == "ok"
    with make_session(engine) as s:
        rated = {sc.name: (sc.rating, sc.pct_met) for sc in s.execute(select(School)).scalars()}
    assert rated["Alpha Elementary"][0] > rated["Beta High"][0]  # 90%-met beats 30%
    assert rated["Alpha Elementary"][1] == 90.0                  # raw %-met stored
    assert rated["Unmatched"] == (None, None)                    # zip mismatch -> unrated

    # multi-source snapshot rows written alongside the fast-path columns
    with make_session(engine) as s:
        snaps = s.execute(select(SchoolRatingSnapshot)).scalars().all()
    assert len(snaps) == 2 and all(sn.source == "caaspp" for sn in snaps)
    assert all(sn.rating_10 is not None and "met standard" in sn.label for sn in snaps)

    assert sr.run(engine) == "noop"                  # same content hash -> noop

    # unchanged file but missing snapshots (e.g. table added after the rating
    # columns were populated) -> the noop path backfills instead of noop-ing
    with make_session(engine) as s:
        for sn in s.execute(select(SchoolRatingSnapshot)).scalars().all():
            s.delete(sn)
        s.commit()
    assert sr.run(engine) == "ok"
    with make_session(engine) as s:
        assert len(s.execute(select(SchoolRatingSnapshot)).scalars().all()) == 2
    assert sr.run(engine) == "noop"                  # converged -> noop again


def test_non_california_geography_records_a_noop(engine, monkeypatch):
    """CAASPP is a California test, declared only by the `ca` pack: under a
    geography that resolves to the `us` pack the job must not download anything
    and must leave a noop run behind, not a failure."""
    from pathlib import Path

    from hb import geography
    from hb.config import settings
    from hb.db.models import PipelineRun

    fixtures = Path(__file__).parent / "fixtures"
    settings._geo = geography.load(fixtures / "geography_tx_minimal.toml", "x", fixtures)
    monkeypatch.setattr(sr, "fetch_caaspp", lambda runner: pytest_fail("must not fetch"))

    assert sr.run(engine) == "noop"
    session = make_session(engine)
    try:
        assert session.execute(select(PipelineRun.status)).scalars().all() == ["noop"]
    finally:
        session.close()


def pytest_fail(msg):
    raise AssertionError(msg)
