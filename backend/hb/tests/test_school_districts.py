from sqlalchemy import func, select

from hb.db.engine import make_session
from hb.db.models import SchoolDistrict
from hb.pipelines import school_districts as sd_pipe


def _feature(**over):
    # NB: the real layer pads empty attributes with a single space, not null
    props = {"GEOID": "0601001", "NAME": "Sunny Elementary SD",
             "ELSDLEA": "01001", "SCSDLEA": " ", "UNSDLEA": " ",
             "LOGRADE": "KG", "HIGRADE": "08", "SDTYP": " ",
             "FUNCSTAT": "E", "SCHOOLYEAR": "2024-2025"}
    props.update({k: v for k, v in over.items() if k != "geometry"})
    geom = over.get("geometry", {"type": "Polygon", "coordinates": [[
        [-122.05, 37.25], [-121.95, 37.25], [-121.95, 37.35],
        [-122.05, 37.35], [-122.05, 37.25]]]})
    return {"type": "Feature", "properties": props, "geometry": geom}


def test_to_row_kind_and_filters():
    row = sd_pipe._to_row(_feature())
    assert row["geoid"] == "0601001" and row["kind"] == "elementary"
    assert row["name"] == "Sunny Elementary SD"
    assert row["lo_grade"] == "KG" and row["hi_grade"] == "08"
    assert row["school_year"] == "2024-2025"
    # bbox derived from the polygon (lon/lat order per shapely bounds)
    assert (row["bbox_lat_min"], row["bbox_lat_max"]) == (37.25, 37.35)
    assert (row["bbox_lon_min"], row["bbox_lon_max"]) == (-122.05, -121.95)

    # kind derivation for secondary / unified
    assert sd_pipe._to_row(_feature(ELSDLEA=" ", SCSDLEA="02002"))["kind"] == "secondary"
    assert sd_pipe._to_row(_feature(ELSDLEA=" ", UNSDLEA="03003"))["kind"] == "unified"
    # no LEA class at all -> skipped
    assert sd_pipe._to_row(_feature(ELSDLEA=" ")) is None
    # not operational -> skipped
    assert sd_pipe._to_row(_feature(FUNCSTAT="F")) is None
    # pseudo-districts (grade-splits/DoD/interstate/BIE) -> skipped
    assert sd_pipe._to_row(_feature(SDTYP="A")) is None
    assert sd_pipe._to_row(_feature(SDTYP="B")) is None
    # 'E' just flags a duplicate NAME — a real district, kept
    assert sd_pipe._to_row(_feature(SDTYP="E")) is not None
    # missing geometry / id -> skipped
    assert sd_pipe._to_row(_feature(geometry=None)) is None
    assert sd_pipe._to_row(_feature(GEOID=None)) is None


def test_run_upserts_then_noops(engine, monkeypatch):
    feats = [
        _feature(),
        _feature(GEOID="0602002", NAME="Union High SD",
                 ELSDLEA=None, SCSDLEA="02002"),
        _feature(GEOID="0699999", FUNCSTAT="F"),  # skipped
    ]
    monkeypatch.setattr(sd_pipe, "fetch_districts", lambda: feats)

    assert sd_pipe.run(engine) == "ok"
    with make_session(engine) as s:
        assert s.execute(select(func.count()).select_from(SchoolDistrict)).scalar_one() == 2
        kinds = dict(s.execute(select(SchoolDistrict.geoid, SchoolDistrict.kind)).all())
    assert kinds == {"0601001": "elementary", "0602002": "secondary"}

    # identical data on the next run -> content hash unchanged -> noop
    assert sd_pipe.run(engine) == "noop"
