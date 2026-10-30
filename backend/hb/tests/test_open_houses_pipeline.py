from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from hb.config import settings
from hb.db.models import Listing, OpenHouse, PipelineRun, Property
from hb.open_houses.sources import REGISTRY
from hb.open_houses.sources.base import OpenHouseRecord
from hb.pipelines import open_houses

NOW = datetime.now(timezone.utc).replace(microsecond=0)
SAT = NOW + timedelta(days=3)


class FakeSource:
    name = "fake"
    records: dict[str, list[OpenHouseRecord]] = {}
    fail: set[str] = set()
    bboxes: dict = {}

    def fetch(self, city, bbox):
        type(self).bboxes[city] = bbox
        if city in self.fail:
            raise RuntimeError(f"{city} down")
        yield from self.records.get(city, [])


class MlsSource(FakeSource):
    """A second portal with its own ids: slots carry only MLS number + ZIP."""
    name = "mls"
    records: dict[str, list[OpenHouseRecord]] = {}
    fail: set[str] = set()
    bboxes: dict = {}


def _rec(sid, start, hours=3, source="fake"):
    return OpenHouseRecord(listing_source=source, source_listing_id=sid,
                           start_at=start, end_at=start + timedelta(hours=hours))


def _mls(mls_id, start, zip5="94040", hours=3):
    return OpenHouseRecord(mls_id=mls_id, zip=zip5, start_at=start,
                           end_at=start + timedelta(hours=hours))


@pytest.fixture
def fake(monkeypatch, set_geography):
    FakeSource.records, FakeSource.fail, FakeSource.bboxes = {}, set(), {}
    MlsSource.records, MlsSource.fail, MlsSource.bboxes = {}, set(), {}
    monkeypatch.setitem(REGISTRY, "fake", FakeSource)
    monkeypatch.setitem(REGISTRY, "mls", MlsSource)
    monkeypatch.setattr(settings, "open_house_sources", ["fake"])
    set_geography(cities=["Mountain View", "Sunnyvale"])
    return FakeSource


@pytest.fixture
def both(fake, monkeypatch):
    monkeypatch.setattr(settings, "open_house_sources", ["fake", "mls"])
    return fake, MlsSource


@pytest.fixture
def listings(session):
    out = {}
    for sid, city, status, lat in [("A", "Mountain View", "active", 37.39),
                                   ("B", "Sunnyvale", "active", 37.37),
                                   ("C", "Sunnyvale", "pending", 37.36)]:
        prop = Property(address_norm=f"1 {sid} ST", zip="94040", city=city,
                        lat=lat, lon=-122.05)
        session.add(prop)
        session.flush()
        lst = Listing(property_id=prop.id, source="fake", source_listing_id=sid, status=status,
                      raw={"mls_id": f"ML-{sid}"})
        session.add(lst)
        session.flush()
        out[sid] = lst.id
    session.commit()
    return out


def _slots(session):
    return sorted((oh.listing_id, oh.start_at) for oh in
                  session.execute(select(OpenHouse)).scalars())


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def test_matches_active_listings_and_skips_the_rest(engine, session, fake, listings):
    fake.records = {
        "Mountain View": [_rec("A", SAT), _rec("ZZ", SAT)],     # ZZ: never scanned
        "Sunnyvale": [_rec("B", SAT), _rec("C", SAT)],         # C: pending
    }
    assert open_houses.run(engine) == "ok"

    session.expire_all()
    assert _slots(session) == sorted([(listings["A"], _iso(SAT)), (listings["B"], _iso(SAT))])
    run = session.execute(select(PipelineRun).where(PipelineRun.job == "open-houses")).scalar_one()
    assert run.items_upserted == 2


def test_rerun_is_idempotent(engine, session, fake, listings):
    fake.records = {"Mountain View": [_rec("A", SAT)]}
    open_houses.run(engine)
    open_houses.run(engine)

    session.expire_all()
    assert len(_slots(session)) == 1
    runs = session.execute(select(PipelineRun).order_by(PipelineRun.started_at)).scalars().all()
    assert runs[-1].items_upserted == 0


def test_cancelled_future_slots_deleted_past_kept(engine, session, fake, listings):
    past = NOW - timedelta(days=2)
    session.add(OpenHouse(listing_id=listings["A"], source="fake", start_at=_iso(past),
                          end_at=_iso(past + timedelta(hours=2)), methods=[]))
    session.commit()
    fake.records = {"Mountain View": [_rec("A", SAT), _rec("A", SAT + timedelta(days=1))]}
    open_houses.run(engine)

    fake.records = {"Mountain View": [_rec("A", SAT)]}  # Sunday slot cancelled
    open_houses.run(engine)

    session.expire_all()
    assert _slots(session) == sorted([(listings["A"], _iso(past)), (listings["A"], _iso(SAT))])


def test_failed_city_skips_the_cancellation_sweep(engine, session, fake, listings):
    fake.records = {"Mountain View": [_rec("A", SAT)], "Sunnyvale": [_rec("B", SAT)]}
    open_houses.run(engine)

    fake.records = {"Mountain View": [_rec("A", SAT)]}
    fake.fail = {"Sunnyvale"}
    assert open_houses.run(engine) == "partial"

    session.expire_all()
    assert (listings["B"], _iso(SAT)) in _slots(session)  # not wiped by an outage


def test_scheduled_slot_is_flagged_cancelled_not_deleted(engine, session, fake, listings):
    fake.records = {"Mountain View": [_rec("A", SAT)]}
    open_houses.run(engine)
    oh = session.execute(select(OpenHouse)).scalar_one()
    oh.scheduled_at = _iso(NOW)
    session.commit()

    fake.records = {}  # upstream drops it
    open_houses.run(engine)
    session.expire_all()
    oh = session.execute(select(OpenHouse)).scalar_one()
    assert oh.cancelled_at is not None and oh.scheduled_at is not None

    fake.records = {"Mountain View": [_rec("A", SAT)]}  # and lists it again
    open_houses.run(engine)
    session.expire_all()
    oh = session.execute(select(OpenHouse)).scalar_one()
    assert oh.cancelled_at is None and oh.scheduled_at is not None


def test_city_bbox_covers_its_active_homes(engine, session, fake, listings):
    open_houses.run(engine)
    w, s, e, n = fake.bboxes["Sunnyvale"]
    assert w < -122.05 < e and s < 37.37 < n
    assert s > 37.36  # the pending home C is not part of the envelope


def test_mls_records_match_by_mls_number_and_zip(engine, session, both, listings):
    _, mls = both
    mls.records = {"Mountain View": [
        _mls("ML-A", SAT),
        _mls("ML-A", SAT + timedelta(days=1), zip5="99999"),  # same number, other ZIP
        _mls("ML-C", SAT),                                     # C is pending
    ]}
    open_houses.run(engine)

    session.expire_all()
    assert _slots(session) == [(listings["A"], _iso(SAT))]
    assert session.execute(select(OpenHouse)).scalar_one().source == "mls"


def test_slot_reported_by_two_sources_is_one_row_credited_to_the_first(
        engine, session, both, listings):
    fake, mls = both
    fake.records = {"Mountain View": [_rec("A", SAT)]}
    mls.records = {"Mountain View": [_mls("ML-A", SAT), _mls("ML-A", SAT + timedelta(days=1))]}
    open_houses.run(engine)

    session.expire_all()
    rows = {(oh.start_at, oh.source) for oh in session.execute(select(OpenHouse)).scalars()}
    assert rows == {(_iso(SAT), "fake"), (_iso(SAT + timedelta(days=1)), "mls")}


def test_sweep_spans_sources_and_skips_when_any_source_fails(engine, session, both, listings):
    fake, mls = both
    fake.records = {"Mountain View": [_rec("A", SAT)]}
    mls.records = {"Mountain View": [_mls("ML-A", SAT + timedelta(days=1))]}
    open_houses.run(engine)

    # the first source drops a slot the second still lists: kept
    fake.records = {}
    mls.records = {"Mountain View": [_mls("ML-A", SAT), _mls("ML-A", SAT + timedelta(days=1))]}
    open_houses.run(engine)
    session.expire_all()
    assert len(_slots(session)) == 2

    # the second source is down: nothing is swept although the first lists nothing
    mls.fail = {"Mountain View"}
    assert open_houses.run(engine) == "partial"
    session.expire_all()
    assert len(_slots(session)) == 2
