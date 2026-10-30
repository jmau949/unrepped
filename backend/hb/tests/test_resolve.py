from sqlalchemy import func, select

from hb.db.models import Property
from hb.pipelines.resolve import resolve


def _record(**over):
    r = {
        "street": "123 Main St",
        "city": "Sunnyvale",
        "state": "CA",
        "zip": "94087",
        "lat": 37.3688,
        "lon": -122.0363,
        "beds": 3,
        "baths": 2.0,
        "sqft": 1600,
        "property_type": "single_family",
    }
    r.update(over)
    return r


def test_d4_same_home_two_formats_merges(session):
    pid1, created1 = resolve(session, _record(street="123 Main St"), "realtor", "R1")
    session.commit()
    pid2, created2 = resolve(session, _record(street="123 MAIN STREET"), "redfin", "RF9")
    session.commit()

    assert created1 is True and created2 is False
    assert pid1 == pid2
    prop = session.get(Property, pid1)
    assert prop.source_ids["realtor"] == ["R1"]
    assert prop.source_ids["redfin"] == ["RF9"]
    assert len(prop.source_ids["raw_addresses"]) == 2


def test_d5_same_street_400m_apart_stays_separate(session):
    pid1, _ = resolve(session, _record(street="100 Oak Ave", lat=37.3688, lon=-122.0363))
    # ~400 m north, different number — must NOT merge
    pid2, _ = resolve(session, _record(street="900 Oak Ave", lat=37.3724, lon=-122.0363))
    session.commit()
    assert pid1 != pid2


def test_d6_units_stay_separate(session):
    pid_a, _ = resolve(session, _record(street="123 Main St # A"))
    pid_b, _ = resolve(session, _record(street="123 Main St # B"))
    session.commit()
    assert pid_a != pid_b


def test_fuzzy_requires_coordinates(session):
    resolve(session, _record(street="123 Main St"))
    # slightly different street text, no coords -> exact miss, fuzzy skipped -> new row
    pid2, created = resolve(session, _record(street="123 Maine St", lat=None, lon=None))
    session.commit()
    assert created is True


def test_fuzzy_close_match_same_home(session):
    resolve(session, _record(street="123 Main St"))
    session.commit()
    # 20 m away, tiny sqft delta, near-identical street text -> merge
    pid2, created = resolve(
        session, _record(street="123 Main St.", lat=37.36885, lon=-122.03635, sqft=1610)
    )
    session.commit()
    assert created is False
    assert session.execute(select(func.count()).select_from(Property)).scalar_one() == 1


def test_conflict_logged_not_overwritten(session):
    pid, _ = resolve(session, _record(beds=3))
    session.commit()
    resolve(session, _record(beds=4))
    session.commit()

    prop = session.get(Property, pid)
    assert prop.beds == 3  # first value kept
    assert any(c["field"] == "beds" and c["seen"] == 4 for c in prop.source_ids["conflicts"])


def test_null_fill(session):
    pid, _ = resolve(session, _record(year_built=None))
    resolve(session, _record(year_built=1962))
    session.commit()
    assert session.get(Property, pid).year_built == 1962


def test_parse_failure_fallback(session):
    # scourgify chokes on empty/garbage input -> naive fallback, still resolves
    pid, created = resolve(session, _record(street="  "))
    session.commit()
    assert created is True
    assert session.get(Property, pid).address_norm == ""


def test_d16_neighbour_with_same_floor_plan_stays_separate(session):
    # ~70 m apart, identical sqft, street strings one digit apart (ratio 94):
    # every other fuzzy gate passes — only the house number separates them
    pid1, _ = resolve(session, _record(street="1020 Sample Cir", sqft=820))
    pid2, created = resolve(
        session, _record(street="1040 Sample Cir", sqft=820, lat=37.3683, lon=-122.0368)
    )
    session.commit()
    assert created is True
    assert pid1 != pid2


def test_authoritative_record_revises_physical_attributes(session):
    pid, _ = resolve(session, _record(beds=2, baths=1.0, sqft=820))
    session.commit()
    resolve(session, _record(beds=3, baths=2.5, sqft=1750), authoritative=True)
    session.commit()

    prop = session.get(Property, pid)
    assert (prop.beds, prop.baths, prop.sqft) == (3, 2.5, 1750)
    assert {"field": "sqft", "kept": 1750, "replaced": 820} in prop.source_ids["conflicts"]


def test_authoritative_record_never_revises_the_address(session):
    pid, _ = resolve(session, _record(street="123 Main St"))
    session.commit()
    # same home, differently formatted street text -> exact match on the
    # normalized line, but the stored street stays and the difference is logged
    resolve(session, _record(street="123 Main Street"), authoritative=True)
    session.commit()

    prop = session.get(Property, pid)
    assert prop.street == "123 Main St"
    assert {"field": "street", "kept": "123 Main St", "seen": "123 Main Street"} \
        in prop.source_ids["conflicts"]


def test_replacement_prunes_the_stale_conflict(session):
    pid, _ = resolve(session, _record(sqft=820))
    resolve(session, _record(sqft=1750))  # logged, 820 kept
    resolve(session, _record(sqft=1750), authoritative=True)  # now replaces it
    session.commit()

    prop = session.get(Property, pid)
    assert prop.sqft == 1750
    assert prop.source_ids["conflicts"] == [{"field": "sqft", "kept": 1750, "replaced": 820}]
