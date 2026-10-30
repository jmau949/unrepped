import json

from sqlalchemy import func, select

from hb.db.engine import make_session
from hb.db.models import School, SchoolDistrict, SchoolRatingSnapshot
from hb.pipelines import schools as schools_pipe
from hb.schools_match import schools_for_property


def _attrs(**over):
    a = {"NCESSCH": "060001", "SCH_NAME": "Cherry Chase Elementary",
         "SCHOOL_LEVEL": "Elementary", "LEA_NAME": "Test USD",
         "LEAID": "0601001", "CHARTER_TEXT": "No",
         "NMCNTY": "Santa Clara County", "LZIP": "94087-1234",
         "LATCOD": 37.35, "LONCOD": -122.03, "SY_STATUS_TEXT": "Open"}
    a.update(over)
    return a


def _square(lat_min, lat_max, lon_min, lon_max) -> str:
    """GeoJSON polygon for a lat/lon square (stored geometry format)."""
    return json.dumps({"type": "Polygon", "coordinates": [[
        [lon_min, lat_min], [lon_max, lat_min], [lon_max, lat_max],
        [lon_min, lat_max], [lon_min, lat_min]]]})


def _district(geoid, name, kind, lat_min, lat_max, lon_min, lon_max) -> SchoolDistrict:
    return SchoolDistrict(
        geoid=geoid, name=name, kind=kind,
        geometry_json=_square(lat_min, lat_max, lon_min, lon_max),
        bbox_lat_min=lat_min, bbox_lat_max=lat_max,
        bbox_lon_min=lon_min, bbox_lon_max=lon_max)


def test_to_row_maps_and_filters():
    assert schools_pipe._to_row(_attrs()) == {
        "nces_id": "060001", "name": "Cherry Chase Elementary", "level": "elementary",
        "lat": 37.35, "lon": -122.03, "district": "Test USD",
        "leaid": "0601001", "is_charter": False,
        "county": "Santa Clara County", "zip": "94087"}
    # non-mapped levels -> skipped
    assert schools_pipe._to_row(_attrs(SCHOOL_LEVEL="Other")) is None
    assert schools_pipe._to_row(_attrs(SCHOOL_LEVEL="Adult Education")) is None
    # closed -> skipped
    assert schools_pipe._to_row(_attrs(SY_STATUS_TEXT="Closed")) is None
    # missing coordinates -> skipped
    assert schools_pipe._to_row(_attrs(LATCOD=None, LONCOD=None)) is None
    # middle / high mapping
    assert schools_pipe._to_row(_attrs(SCHOOL_LEVEL="Middle"))["level"] == "middle"
    assert schools_pipe._to_row(_attrs(SCHOOL_LEVEL="High"))["level"] == "high"
    # charter flag
    assert schools_pipe._to_row(_attrs(CHARTER_TEXT="Yes"))["is_charter"] is True
    assert schools_pipe._to_row(_attrs(LEAID=None))["leaid"] is None


def test_run_upserts_then_noops(engine, monkeypatch):
    attrs = [_attrs(NCESSCH="1"),
             _attrs(NCESSCH="2", SCHOOL_LEVEL="Middle"),
             _attrs(NCESSCH="3", SCHOOL_LEVEL="Other")]  # 3rd skipped
    monkeypatch.setattr(schools_pipe, "fetch_schools", lambda: attrs)

    assert schools_pipe.run(engine) == "ok"
    with make_session(engine) as s:
        assert s.execute(select(func.count()).select_from(School)).scalar_one() == 2

    # identical data on the next run -> content hash unchanged -> noop
    assert schools_pipe.run(engine) == "noop"


# --- boundary-aware matching (hb.schools_match) ------------------------------
#
# The regression scenario for "a house shows a school from the wrong district":
# overlapping elementary + secondary districts (CA split-district geography),
# with a CLOSER school that belongs to a different district. Distance must
# lose to the boundary.

def _seed_split_districts(session):
    session.add_all([
        # elementary + secondary districts overlap on the same square (the
        # house at 37.3,-122.0 sits in both); unified is a disjoint square
        _district("0601001", "Sunny Elementary SD", "elementary",
                  37.25, 37.35, -122.05, -121.95),
        _district("0602002", "Union High SD", "secondary",
                  37.25, 37.35, -122.05, -121.95),
        _district("0603003", "Other Unified", "unified",
                  37.45, 37.55, -122.05, -121.95),
    ])
    session.add_all([
        # in-district elementary, ~0.8 mi away
        School(nces_id="E1", name="In-District El", level="elementary",
               lat=37.312, lon=-122.0, leaid="0601001", rating=7),
        # WRONG-district elementary that is CLOSER (~0.1 mi) — must lose
        School(nces_id="E2", name="Closer Wrong-District El", level="elementary",
               lat=37.301, lon=-122.0, leaid="0603003", rating=10),
        # charter inside the district, closest of all — not zoned, excluded
        School(nces_id="E3", name="Charter El", level="elementary",
               lat=37.3005, lon=-122.0, leaid="0601001", is_charter=True),
        # high school from the secondary district
        School(nces_id="H1", name="Union High", level="high",
               lat=37.32, lon=-122.01, leaid="0602002"),
        # closer high school from the unified district — must lose too
        School(nces_id="H2", name="Closer Wrong-District High", level="high",
               lat=37.302, lon=-122.0, leaid="0603003"),
        # no middle school in-district: nearest fallback kicks in
        School(nces_id="M1", name="Fallback Mid", level="middle",
               lat=37.305, lon=-122.004, leaid="0603003", district="Other Unified"),
    ])
    session.commit()


def test_district_match_beats_closer_school(session):
    _seed_split_districts(session)
    out = schools_for_property(session, 37.3, -122.0)
    by_level = {s["level"]: s for s in out}

    el = by_level["elementary"]
    assert el["name"] == "In-District El"          # boundary beats distance
    assert el["assignment"] == "district"
    assert el["district"] == "Sunny Elementary SD"  # polygon name, not LEA string

    hi = by_level["high"]
    assert hi["name"] == "Union High"              # secondary district governs high
    assert hi["assignment"] == "district"
    assert hi["district"] == "Union High SD"

    # no in-district middle school -> flagged nearest fallback
    mid = by_level["middle"]
    assert mid["name"] == "Fallback Mid"
    assert mid["assignment"] == "nearest"


def test_unified_district_governs_all_levels(session):
    _seed_split_districts(session)
    session.add(School(nces_id="U1", name="Unified El", level="elementary",
                       lat=37.5, lon=-122.0, leaid="0603003"))
    session.commit()
    out = schools_for_property(session, 37.5, -122.0)  # inside "Other Unified"
    el = next(s for s in out if s["level"] == "elementary")
    assert el["name"] == "Unified El"
    assert el["assignment"] == "district"
    assert el["district"] == "Other Unified"


def test_no_polygon_falls_back_to_nearest(session):
    # schools but no district rows at all -> pre-boundary nearest behavior
    session.add_all([
        School(nces_id="N", name="Near El", level="elementary", lat=37.301, lon=-122.001),
        School(nces_id="F", name="Far El", level="elementary", lat=38.0, lon=-121.0, rating=10),
        School(nces_id="M", name="Near Mid", level="middle", lat=37.305, lon=-122.004),
    ])
    session.commit()
    out = schools_for_property(session, 37.3, -122.0)
    assert [s["name"] for s in out] == ["Near El", "Near Mid"]  # no high in range
    assert all(s["assignment"] == "nearest" for s in out)


def test_empty_without_coords_or_data(session):
    session.add(School(nces_id="Z", name="Somewhere El", level="elementary",
                       lat=37.3, lon=-122.0))
    session.commit()
    assert schools_for_property(session, None, None) == []       # no coords, no zip
    assert schools_for_property(session, 34.0, -118.0) == []     # ~300mi away, outside bbox


def test_zip_fallback_without_coords(session):
    session.add_all([
        School(nces_id="E", name="Zip El", level="elementary", lat=1, lon=1, zip="95050", rating=8),
        School(nces_id="E2", name="Zip El Low", level="elementary", lat=1, lon=1, zip="95050", rating=3),
        School(nces_id="H", name="Zip High", level="high", lat=1, lon=1, zip="95050"),
    ])
    session.commit()
    # coordinate-less property -> fall back to schools in its ZIP
    out = schools_for_property(session, None, None, "95050")
    assert [s["level"] for s in out] == ["elementary", "high"]
    assert out[0]["name"] == "Zip El"        # top-rated elementary in the zip (8 > 3)
    assert out[0]["distance_mi"] is None      # distance unknown without coords
    assert out[0]["assignment"] == "zip"
    assert schools_for_property(session, None, None, "99999") == []  # unknown zip -> empty


def test_ratings_attached_per_source(session):
    _seed_split_districts(session)
    el = session.execute(
        select(School).where(School.nces_id == "E1")).scalar_one()
    session.add_all([
        SchoolRatingSnapshot(school_id=el.id, source="schooldigger",
                             rating_10=9.0, label="#12 of 5,856 in CA"),
        SchoolRatingSnapshot(school_id=el.id, source="caaspp",
                             rating_10=7.0, label="68% met standard"),
    ])
    session.commit()
    out = schools_for_property(session, 37.3, -122.0)
    el_row = next(s for s in out if s["level"] == "elementary")
    assert [r["source"] for r in el_row["ratings"]] == ["caaspp", "schooldigger"]
    assert el_row["ratings"][1]["rating_10"] == 9.0
    assert el_row["ratings"][1]["label"] == "#12 of 5,856 in CA"
    # schools without snapshots still carry the (empty) list
    assert all("ratings" in s for s in out)
