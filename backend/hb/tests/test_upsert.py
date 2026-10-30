from sqlalchemy import func, select

from hb.db.models import Property
from hb.db.upsert import upsert

KEY = ["address_norm", "zip", "unit"]


def _values(**over):
    v = {
        "address_norm": "123 MAIN ST",
        "zip": "94087",
        "unit": "",
        "city": "Sunnyvale",
        "beds": 3,
        "sqft": 1600,
    }
    v.update(over)
    return v


def test_double_insert_yields_one_row(session):
    _, changed1 = upsert(session, Property, _values(), KEY)
    session.commit()
    _, changed2 = upsert(session, Property, _values(), KEY)
    session.commit()

    assert changed1 is True
    assert changed2 is False
    assert session.execute(select(func.count()).select_from(Property)).scalar_one() == 1


def test_identical_rerun_does_not_touch_updated_at(session):
    row, _ = upsert(session, Property, _values(), KEY)
    session.commit()
    before = row.updated_at

    row2, changed = upsert(session, Property, _values(), KEY)
    session.commit()
    assert changed is False
    assert row2.updated_at == before


def test_changed_field_detected_and_updated(session):
    upsert(session, Property, _values(), KEY)
    session.commit()

    row, changed = upsert(session, Property, _values(beds=4), KEY)
    session.commit()
    assert changed is True
    assert row.beds == 4
    assert session.execute(select(func.count()).select_from(Property)).scalar_one() == 1


def test_distinct_units_are_distinct_rows(session):
    upsert(session, Property, _values(unit="A"), KEY)
    upsert(session, Property, _values(unit="B"), KEY)
    session.commit()
    assert session.execute(select(func.count()).select_from(Property)).scalar_one() == 2
