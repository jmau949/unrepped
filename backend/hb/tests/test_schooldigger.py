import json

import httpx
import pytest
from sqlalchemy import select

from hb.db.engine import make_session
from hb.db.models import (
    AppSetting,
    Property,
    School,
    SchoolDistrict,
    SchoolRatingSnapshot,
)
from hb.pipelines import schooldigger as sd


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr(sd.settings, "schooldigger_app_id", "test-id")
    monkeypatch.setattr(sd.settings, "schooldigger_app_key", "test-key")


def _square(lat_min, lat_max, lon_min, lon_max) -> str:
    return json.dumps({"type": "Polygon", "coordinates": [[
        [lon_min, lat_min], [lon_max, lat_min], [lon_max, lat_max],
        [lon_min, lat_max], [lon_min, lat_min]]]})


def _seed(engine):
    """One property inside one unified district with two schools."""
    with make_session(engine) as s:
        s.add(SchoolDistrict(
            geoid="0601001", name="Test Unified", kind="unified",
            geometry_json=_square(37.25, 37.35, -122.05, -121.95),
            bbox_lat_min=37.25, bbox_lat_max=37.35,
            bbox_lon_min=-122.05, bbox_lon_max=-121.95))
        s.add(Property(address_norm="1 TEST ST", zip="94087",
                       lat=37.3, lon=-122.0))
        s.add_all([
            School(nces_id="060000112345", name="Cherry Chase Elementary",
                   level="elementary", lat=37.31, lon=-122.0,
                   leaid="0601001", zip="94087"),
            School(nces_id="OTHER", name="Zip Match High", level="high",
                   lat=37.32, lon=-122.0, leaid="0601001", zip="94040"),
        ])
        s.commit()


def _rec(**over):
    # rankStatewidePercentage = ranks above X% of CA schools (high = good)
    r = {"schoolid": "060000112345", "schoolName": "Cherry Chase Elementary",
         "address": {"zip": "94087-1234"},
         "rankHistory": [{"year": 2025, "rank": 120, "rankOf": 5856,
                          "rankStars": 5, "rankStatewidePercentage": 97.95}]}
    r.update(over)
    return r


def test_to_snap_normalization():
    snap = sd._to_snap(_rec())
    assert snap["rating_10"] == 10.0            # beats 98% of CA -> 10
    assert snap["label"] == "#120 of 5856 in CA"
    assert snap["as_of"] == "2025"
    assert snap["nces_id"] == "060000112345" and snap["zip"] == "94087"

    # near-bottom school (beats only 4%) -> 1, matching live data + rankStars=0
    low = sd._to_snap(_rec(rankHistory=[{"year": 2025, "rank": 5618,
                                         "rankOf": 5857, "rankStars": 0,
                                         "rankStatewidePercentage": 4.08}]))
    assert low["rating_10"] == 1.0
    # percentage missing -> derived from rank/rankOf (midpack -> 5)
    mid = sd._to_snap(_rec(rankHistory=[{"year": 2025, "rank": 2928, "rankOf": 5856}]))
    assert mid["rating_10"] == 5.0
    # unranked -> skipped
    assert sd._to_snap(_rec(rankHistory=[])) is None
    assert sd._to_snap(_rec(rankHistory=None)) is None


def test_run_without_credentials_is_clean_noop(engine, monkeypatch):
    monkeypatch.setattr(sd.settings, "schooldigger_app_id", "")
    monkeypatch.setattr(sd.settings, "schooldigger_app_key", "")
    assert sd.run(engine) == "noop"


def test_target_districts_from_assigned_properties(engine):
    _seed(engine)
    with make_session(engine) as s:
        assert sd.target_districts(s) == ["0601001"]


def test_run_rates_matched_then_noops(engine, creds, monkeypatch):
    _seed(engine)
    calls: list[tuple[str, int]] = []

    def fake_page(district_id, page):
        calls.append((district_id, page))
        return {"numberOfPages": 1, "schoolList": [
            _rec(),  # matches by NCES id
            _rec(schoolid="somethingelse", schoolName="Zip Match High",
                 address={"zip": "94040"},
                 rankHistory=[{"year": 2025, "rank": 100, "rankOf": 2162,
                               "rankStatewidePercentage": 95.4}]),
            _rec(schoolid="nomatch", schoolName="Unknown School",
                 address={"zip": "99999"}),
        ]}

    monkeypatch.setattr(sd, "fetch_district_page", fake_page)
    assert sd.run(engine) == "ok"
    assert calls == [("0601001", 1)]
    with make_session(engine) as s:
        snaps = s.execute(select(SchoolRatingSnapshot)).scalars().all()
        assert len(snaps) == 2  # nces-id match + (zip, name) match; unknown dropped
        assert all(sn.source == "schooldigger" for sn in snaps)
        assert s.get(AppSetting, "schooldigger_budget").value["calls"] == 1
        assert "0601001" in s.get(AppSetting, "schooldigger_progress").value

    # every assigned district freshly rated -> noop, no further calls
    assert sd.run(engine) == "noop"
    assert len(calls) == 1


def test_budget_exhaustion_stops_cleanly(engine, creds, monkeypatch):
    _seed(engine)
    monkeypatch.setattr(sd.settings, "schooldigger_daily_limit", 0)
    monkeypatch.setattr(sd, "fetch_district_page",
                        lambda district_id, page: (_ for _ in ()).throw(
                            AssertionError("must not call the API at 0 budget")))
    # zero budget left today -> nothing fetched, clean noop (rerun tomorrow)
    assert sd.run(engine) == "noop"
    with make_session(engine) as s:
        assert s.execute(select(SchoolRatingSnapshot)).scalars().all() == []
        assert s.get(AppSetting, "schooldigger_progress") is None


def test_api_429_midrun_keeps_progress(engine, creds, monkeypatch):
    _seed(engine)
    with make_session(engine) as s:  # a second property in a second district
        s.add(SchoolDistrict(
            geoid="0602002", name="Other Unified", kind="unified",
            geometry_json=_square(37.45, 37.55, -122.05, -121.95),
            bbox_lat_min=37.45, bbox_lat_max=37.55,
            bbox_lon_min=-122.05, bbox_lon_max=-121.95))
        s.add(Property(address_norm="2 TEST ST", zip="94040",
                       lat=37.5, lon=-122.0))
        s.commit()

    def fake_page(district_id, page):
        if district_id == "0602002":  # second district hits the API day-cap
            resp = httpx.Response(429, request=httpx.Request("GET", sd.API_URL))
            raise httpx.HTTPStatusError("429", request=resp.request, response=resp)
        return {"numberOfPages": 1, "schoolList": [_rec()]}

    monkeypatch.setattr(sd, "fetch_district_page", fake_page)
    assert sd.run(engine) == "ok"  # first district landed; 429 is pacing, not failure
    with make_session(engine) as s:
        assert len(s.execute(select(SchoolRatingSnapshot)).scalars().all()) == 1
        prog = s.get(AppSetting, "schooldigger_progress").value
        assert "0601001" in prog and "0602002" not in prog  # resumes tomorrow
