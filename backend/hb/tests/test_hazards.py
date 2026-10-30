"""Hazards pipeline tests — point-in-polygon flagging + the D1 re-run invariant."""

import json

import pytest
from sqlalchemy import select

from hb.db.models import HazardFlag, Property
from hb.pipelines import hazards

# unit squares around the "inside" point (-122.03, 37.35)
INSIDE = (37.35, -122.03)
OUTSIDE = (37.80, -121.30)


def _square(lon: float, lat: float, half: float = 0.05) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - half, lat - half], [lon + half, lat - half],
            [lon + half, lat + half], [lon - half, lat + half],
            [lon - half, lat - half],
        ]],
    }


LAYER_PROPS = {
    "fema_flood": {"FLD_ZONE": "AE", "ZONE_SUBTY": ""},
    "calfire_fhsz": {"FHSZ_6Class": "SRA Very High"},
    "liquefaction": {"QUAD_NAME": "CUPERTINO"},
    "fault_zone": {"QUAD_NAME": "CUPERTINO"},
}


@pytest.fixture
def hazard_files(tmp_path, monkeypatch):
    monkeypatch.setattr("hb.config.settings.data_dir", tmp_path)
    raw = tmp_path / "raw" / "hazards"
    raw.mkdir(parents=True)
    for hazard, props in LAYER_PROPS.items():
        (raw / f"{hazard}.geojson").write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": props,
                          "geometry": _square(INSIDE[1], INSIDE[0])}],
        }), encoding="utf-8")
    return raw


@pytest.fixture
def props(session):
    inside = Property(address_norm="1 INSIDE WAY", zip="94087", city="Sunnyvale",
                      lat=INSIDE[0], lon=INSIDE[1], property_type="single_family")
    outside = Property(address_norm="2 OUTSIDE RD", zip="94087", city="Sunnyvale",
                       lat=OUTSIDE[0], lon=OUTSIDE[1], property_type="single_family")
    nogeo = Property(address_norm="3 NOWHERE CT", zip="94087", city="Sunnyvale",
                     lat=None, lon=None, property_type="single_family")
    session.add_all([inside, outside, nogeo])
    session.commit()
    return inside, outside, nogeo


def _flags(session, prop_id):
    return session.execute(
        select(HazardFlag).where(HazardFlag.property_id == prop_id)
    ).scalars().all()


def test_inside_point_flags_all_layers(engine, session, hazard_files, props):
    inside, outside, _ = props
    assert hazards.run(engine) == "ok"
    session.expire_all()
    inside_flags = {f.hazard: f.zone_value for f in _flags(session, inside.id)}
    assert inside_flags == {
        "fema_flood": "AE",
        "calfire_fhsz": "SRA Very High",
        "liquefaction": "CUPERTINO",
        "fault_zone": "CUPERTINO",
    }
    assert _flags(session, outside.id) == []


def test_rerun_unchanged_is_noop(engine, session, hazard_files, props):
    assert hazards.run(engine) == "ok"
    before = session.execute(select(HazardFlag)).scalars().all()
    checked = {f.id: f.checked_at for f in before}
    assert hazards.run(engine) == "noop"
    session.expire_all()
    after = session.execute(select(HazardFlag)).scalars().all()
    assert len(after) == len(before)
    assert {f.id: f.checked_at for f in after} == checked  # D1: zero rows touched


def test_new_property_between_runs_gets_flagged(engine, session, hazard_files, props):
    assert hazards.run(engine) == "ok"
    late = Property(address_norm="4 LATE LN", zip="94087", city="Sunnyvale",
                    lat=INSIDE[0], lon=INSIDE[1], property_type="single_family")
    session.add(late)
    session.commit()
    assert hazards.run(engine) == "ok"  # not noop: one unflagged property existed
    session.expire_all()
    assert len(_flags(session, late.id)) == 4


def test_changed_file_reprocesses_all(engine, session, hazard_files, props):
    inside, _, _ = props
    assert hazards.run(engine) == "ok"
    # re-release: flood zone value changes for the same polygon
    path = hazard_files / "fema_flood.geojson"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["features"][0]["properties"]["FLD_ZONE"] = "VE"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert hazards.run(engine) == "ok"
    session.expire_all()
    flags = {f.hazard: f.zone_value for f in _flags(session, inside.id)}
    assert flags["fema_flood"] == "VE"
    assert len(_flags(session, inside.id)) == 4  # updated in place, no dupes


def test_missing_files_fail_with_pointer(engine, tmp_path, monkeypatch, props):
    monkeypatch.setattr("hb.config.settings.data_dir", tmp_path / "empty")
    assert hazards.run(engine) == "failed"


def test_null_latlon_skipped(engine, session, hazard_files, props):
    _, _, nogeo = props
    assert hazards.run(engine) == "ok"
    session.expire_all()
    assert _flags(session, nogeo.id) == []
