from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import hb.open_houses.sources.realtor as realtor
import hb.open_houses.sources.redfin as redfin
from hb.open_houses.sources import REGISTRY, enabled_sources
from hb.open_houses.sources.base import localize


def _oh(start, end, tz="PST", **kw):
    return SimpleNamespace(start_date=start, end_date=end, time_zone=tz,
                           description=kw.get("description"), href=kw.get("href"),
                           methods=kw.get("methods", ["in_person"]))


def _prop(listing_id="L1", mls_id="M1", property_id="P1", open_houses=None):
    return SimpleNamespace(listing_id=listing_id, mls_id=mls_id, property_id=property_id,
                           open_houses=open_houses)


def test_localize_pacific_across_dst():
    # Realtor says "PST" year-round; the IANA zone decides DST from the date
    summer = localize(datetime(2026, 10, 17, 13, 0), "PST", "America/New_York")
    winter = localize(datetime(2026, 12, 5, 13, 0), "PST", "America/New_York")
    assert summer == datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc)
    assert winter == datetime(2026, 12, 5, 21, 0, tzinfo=timezone.utc)


def test_localize_unknown_zone_falls_back_to_default():
    assert localize(datetime(2026, 10, 17, 13, 0), "ZZZ", "America/Los_Angeles") \
        == datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc)
    assert localize(datetime(2026, 10, 17, 13, 0), None, "America/Chicago") \
        == datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)


def test_realtor_source_parses_slots_and_skips_homes_without(monkeypatch):
    props = [
        _prop(open_houses=[_oh(datetime(2026, 10, 17, 13), datetime(2026, 10, 17, 16),
                               description="  Hosted by A  ")]),
        _prop(listing_id="L2", open_houses=None),
        _prop(listing_id="L3", open_houses=[]),
    ]
    monkeypatch.setattr(realtor, "fetch_properties", lambda city: props)

    recs = list(realtor.RealtorOpenHouses().fetch("Mountain View", None))

    assert len(recs) == 1
    rec = recs[0]
    assert rec.listing_source == "realtor"
    assert rec.source_listing_id == "L1"
    assert rec.start_at == datetime(2026, 10, 17, 20, tzinfo=timezone.utc)
    assert rec.end_at == datetime(2026, 10, 17, 23, tzinfo=timezone.utc)
    assert rec.description == "Hosted by A"
    assert rec.methods == ["in_person"]


def test_realtor_source_id_precedence_matches_listing_scan(monkeypatch):
    # listing_id -> mls_id -> property_id, the same key listing-scan stores
    props = [
        _prop(listing_id=None, mls_id="M9", property_id="P9",
              open_houses=[_oh(datetime(2026, 10, 18, 13), datetime(2026, 10, 18, 15))]),
        _prop(listing_id=None, mls_id=None, property_id="P8",
              open_houses=[_oh(datetime(2026, 10, 18, 13), datetime(2026, 10, 18, 15))]),
    ]
    monkeypatch.setattr(realtor, "fetch_properties", lambda city: props)

    assert [r.source_listing_id for r in realtor.RealtorOpenHouses().fetch("X", None)] == ["M9", "P8"]


def test_enabled_sources_rejects_unknown_names(monkeypatch):
    from hb.config import settings

    monkeypatch.setattr(settings, "open_house_sources", ["realtor", "redfin"])
    assert [s.name for s in enabled_sources()] == ["realtor", "redfin"]
    monkeypatch.setattr(settings, "open_house_sources", ["nope"])
    with pytest.raises(ValueError, match="nope"):
        enabled_sources()
    assert "realtor" in REGISTRY


def _home(mls="ML1", zip5="94040", start=1792875600000, end=1792886400000):
    return {"mlsId": {"label": "MLS#", "value": mls}, "zip": zip5,
            "openHouseStart": start, "openHouseEnd": end,
            "openHouseEventName": "Open House - 2:00 - 5:00 PM"}


def test_redfin_source_parses_next_slot_in_utc(monkeypatch):
    calls = []

    def gis(params):
        calls.append(params)
        return {"homes": [_home(), _home(mls="ML2", start=None, end=None), _home(mls="")]}

    monkeypatch.setattr(redfin, "fetch_gis", gis)
    recs = redfin.RedfinOpenHouses().fetch("Mountain View", (-122.1, 37.3, -122.0, 37.4))

    assert len(recs) == 1
    rec = recs[0]
    assert (rec.mls_id, rec.zip, rec.listing_source) == ("ML1", "94040", None)
    assert rec.start_at == datetime(2026, 10, 24, 21, tzinfo=timezone.utc)
    assert rec.end_at == datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
    assert rec.description == "Open House - 2:00 - 5:00 PM"
    assert rec.href is None
    assert calls[0]["poly"].startswith("-122.1 37.3,-122.0 37.3,")
    assert calls[0]["uipt"] == 1 and calls[0]["status"] == 1
    # without the map's paging params Redfin ignores the polygon
    assert {"ord", "page_number", "start", "sf"} <= calls[0].keys()


def test_redfin_source_splits_a_capped_box_and_dedupes(monkeypatch):
    calls = []

    def gis(params):
        calls.append(params["poly"])
        if len(calls) == 1:  # the whole box hits the cap
            return {"homes": [_home(mls=f"X{i}", start=None) for i in range(redfin.NUM_HOMES)]}
        return {"homes": [_home(mls="EDGE")]}  # every quadrant sees the edge home

    monkeypatch.setattr(redfin, "fetch_gis", gis)
    recs = redfin.RedfinOpenHouses().fetch("Mountain View", (-122.2, 37.2, -122.0, 37.4))

    assert len(calls) == 5
    assert [r.mls_id for r in recs] == ["EDGE"]


def test_redfin_source_without_a_bbox_fetches_nothing(monkeypatch):
    monkeypatch.setattr(redfin, "fetch_gis", lambda params: pytest.fail("no area to search"))
    assert redfin.RedfinOpenHouses().fetch("Nowhere", None) == []
