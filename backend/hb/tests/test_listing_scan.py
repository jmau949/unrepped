import logging
from collections import defaultdict

import pandas as pd
import pytest
from sqlalchemy import func, select

from hb.db.models import Listing, ListingEvent, Property, Sale, PipelineRun
from hb.pipelines import listing_scan


def _row(**over):
    r = {
        "property_id": "P100", "listing_id": "L100", "mls_id": "ML100",
        "status": "FOR_SALE", "mls_status": "Active",
        "full_street_line": "811 Sample Cir", "street": "811 Sample Cir",
        "unit": None, "city": "Menlo Park", "state": "CA", "zip_code": "94025",
        "latitude": 37.45, "longitude": -122.17,
        "beds": 3, "full_baths": 2, "half_baths": 1, "sqft": 1800,
        "lot_sqft": 5000, "year_built": 1990,
        "list_price": 2500000, "list_date": "2026-07-06 12:00:00",
        "pending_date": None, "sold_price": None, "last_sold_date": None,
        "last_sold_price": None, "days_on_mls": 8,
        "primary_photo": "https://cdn.example/photo-l100.jpg",
        "property_url": "https://realtor.com/x",
    }
    r.update(over)
    return r


@pytest.fixture
def scan_env(monkeypatch, tmp_path, set_geography):
    """One target city, no sleeps, no photo downloads unless a test opts in."""
    from hb import config
    from hb.pipelines import price_history

    set_geography(cities=["Menlo Park"])
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "save_photos", False)
    monkeypatch.setattr(listing_scan.time, "sleep", lambda *_: None)
    # the scan's price-history tail is a live Realtor scrape; without this seam
    # the suite hits the network and the derived history overwrites what the
    # test set up (CLAUDE.md: no network)
    monkeypatch.setattr(price_history, "fetch_price_history", lambda *a, **k: [])

    fixtures: dict[str, list[dict]] = {"for_sale": [], "pending": [], "sold": []}

    def fake_fetch(city, listing_type, past_days):
        return pd.DataFrame(fixtures[listing_type])

    monkeypatch.setattr(listing_scan, "fetch_homeharvest", fake_fetch)
    return fixtures


def _counts(session):
    return (
        session.execute(select(func.count()).select_from(Listing)).scalar_one(),
        session.execute(select(func.count()).select_from(ListingEvent)).scalar_one(),
        session.execute(select(func.count()).select_from(Sale)).scalar_one(),
    )


def test_d1_d3_rerun_is_silent(engine, session, scan_env):
    scan_env["for_sale"] = [_row()]
    assert listing_scan.run(engine) == "ok"
    assert _counts(session) == (1, 1, 0)  # one listing, one 'new' event

    assert listing_scan.run(engine) == "ok"  # identical second run
    assert _counts(session) == (1, 1, 0)  # zero new rows, zero new events

    listing = session.execute(select(Listing)).scalar_one()
    assert listing.original_list_price == 2500000
    assert listing.status == "active"


def test_d14_price_up_then_down(engine, session, scan_env):
    scan_env["for_sale"] = [_row(list_price=2500000)]
    listing_scan.run(engine)
    scan_env["for_sale"] = [_row(list_price=3100000)]
    listing_scan.run(engine)
    scan_env["for_sale"] = [_row(list_price=2500000)]
    listing_scan.run(engine)

    events = session.execute(
        select(ListingEvent).where(ListingEvent.event_type == "price_change")
    ).scalars().all()
    assert len(events) == 2
    listing = session.execute(select(Listing)).scalar_one()
    assert listing.original_list_price == 2500000  # first observed price sticks


def test_delist_detection(engine, session, scan_env):
    scan_env["for_sale"] = [_row()]
    listing_scan.run(engine)
    scan_env["for_sale"] = []  # absent from today's full scan
    listing_scan.run(engine)

    listing = session.execute(select(Listing)).scalar_one()
    assert listing.status == "delisted"
    assert listing.delist_date is not None
    delist_events = session.execute(
        select(ListingEvent).where(ListingEvent.event_type == "delisted")
    ).scalars().all()
    assert len(delist_events) == 1

    listing_scan.run(engine)  # third run: still delisted, no duplicate event
    assert len(session.execute(
        select(ListingEvent).where(ListingEvent.event_type == "delisted")
    ).scalars().all()) == 1


def test_sold_uses_our_original_list_price(engine, session, scan_env):
    # seen active at 2.75M first
    scan_env["for_sale"] = [_row(list_price=2750000)]
    listing_scan.run(engine)
    # later sold at 3.25M; source reports a different (post-cut) list price
    scan_env["for_sale"] = []
    scan_env["sold"] = [_row(status="SOLD", mls_status="Sold", list_price=2800000,
                             sold_price=3250000, last_sold_price=3250000,
                             last_sold_date="2026-07-09 22:56:59", days_on_mls=20)]
    listing_scan.run(engine)

    sale = session.execute(select(Sale)).scalar_one()
    assert sale.sale_price == 3250000
    assert sale.original_list_price == 2750000  # ours, not the source's
    assert sale.sp_lp == pytest.approx(3250000 / 2750000, abs=1e-4)
    assert sale.had_price_cut is False


def test_raw_source_record_is_persisted(engine, session, scan_env):
    """docs/05 §4.2: the full source record is kept on `raw`, so fields we don't
    model yet (mls_status, hoa_fee, estimated_value, description text) survive
    ingest. Photo URL blobs are excluded — they live in `photo_urls`."""
    phones = [{"ext": None, "primary": True, "type": "Mobile", "number": "6505550123"}]
    scan_env["for_sale"] = [_row(mls_status="Active Contingent Release",
                                 hoa_fee=250, estimated_value=3_100_000,
                                 text="Beautifully remodeled 2023. Offers due 7/21.",
                                 alt_photos="https://cdn/a.jpg",
                                 agent_name="Jane Lister", agent_email="jlister@example.com",
                                 agent_phones=phones)]
    listing_scan.run(engine)

    listing = session.execute(select(Listing)).scalar_one()
    assert listing.raw["mls_status"] == "Active Contingent Release"
    assert listing.raw["hoa_fee"] == 250
    assert listing.raw["estimated_value"] == 3_100_000
    assert "Offers due" in listing.raw["text"]
    assert listing.raw["mls_id"] == "ML100"
    assert "alt_photos" not in listing.raw and "primary_photo" not in listing.raw
    # the listing side survives as JSON the detail page can walk — a list, never
    # the str() of one (hb/listing_contact.py reads exactly this)
    assert listing.raw["agent_name"] == "Jane Lister"
    assert listing.raw["agent_phones"] == phones
    assert not isinstance(listing.raw["agent_phones"], str)


def test_json_scalar_recurses_into_nested_values():
    nested = [{"a": float("nan"), "b": [1, "x", pd.NaT], "c": {"d": None}}]
    assert listing_scan._json_scalar(nested) == [{"a": None, "b": [1, "x", None], "c": {"d": None}}]
    assert listing_scan._json_scalar(("t", 2)) == ["t", 2]


def test_raw_refresh_does_not_break_rerun_idempotency(engine, session, scan_env):
    scan_env["for_sale"] = [_row(text="original copy")]
    listing_scan.run(engine)
    scan_env["for_sale"] = [_row(text="price improved!")]
    listing_scan.run(engine)

    listing = session.execute(select(Listing)).scalar_one()
    assert listing.raw["text"] == "price improved!"  # snapshot follows the source
    # a raw-only change is audit metadata: no event, no duplicate rows
    assert _counts(session) == (1, 1, 0)


def test_remarks_populate_condition_and_offer_date(engine, session, scan_env):
    """docs/05 §4.7: the two signals that live only in the public remarks."""
    from hb.db.models import Property

    scan_env["for_sale"] = [_row(
        list_date="2026-07-06 12:00:00",
        text="Beautifully remodeled in 2024 with a new kitchen and new roof. "
             "Offers due Tuesday, July 21st at 5pm.",
    )]
    listing_scan.run(engine)

    prop = session.execute(select(Property)).scalar_one()
    assert prop.condition_tag == "renovated"
    assert prop.condition_notes.startswith("auto: ")
    assert session.execute(select(Listing)).scalar_one().offer_due_at == "2026-07-21"


def test_manual_condition_survives_a_rescan(engine, session, scan_env):
    from hb.db.models import Property

    scan_env["for_sale"] = [_row(text="Charming home near parks.")]
    listing_scan.run(engine)

    prop = session.execute(select(Property)).scalar_one()
    prop.condition_tag = "fixer"
    prop.condition_notes = "toured 8/2 - foundation cracked"
    session.commit()

    scan_env["for_sale"] = [_row(text="Beautifully remodeled, new kitchen, new roof.")]
    listing_scan.run(engine)

    session.expire_all()
    prop = session.execute(select(Property)).scalar_one()
    assert prop.condition_tag == "fixer"  # the walk-through beats the copywriter
    assert prop.condition_notes == "toured 8/2 - foundation cracked"


def test_offer_date_is_fill_only(engine, session, scan_env):
    scan_env["for_sale"] = [_row(text="Offers due 7/21.", list_date="2026-07-06 00:00:00")]
    listing_scan.run(engine)
    listing = session.execute(select(Listing)).scalar_one()
    assert listing.offer_due_at == "2026-07-21"

    listing.offer_due_at = "2026-07-23"  # user moved it in the UI
    session.commit()
    scan_env["for_sale"] = [_row(text="Offers due 7/21.", list_date="2026-07-06 00:00:00")]
    listing_scan.run(engine)

    session.expire_all()
    assert session.execute(select(Listing)).scalar_one().offer_due_at == "2026-07-23"


def test_sale_cumulative_dom_synced_from_group(engine, session, scan_env):
    """relist.stitch writes CDOM to the group; the overbid model's stale routing
    (docs/06 §5.2) reads it off the sale."""
    scan_env["for_sale"] = [_row(list_price=2750000)]
    listing_scan.run(engine)
    scan_env["for_sale"] = []
    scan_env["sold"] = [_row(status="SOLD", mls_status="Sold", list_price=2750000,
                             sold_price=3250000, last_sold_price=3250000,
                             last_sold_date="2026-07-09 22:56:59", days_on_mls=20)]
    listing_scan.run(engine)

    from hb.db.models import ListingGroup

    sale = session.execute(select(Sale)).scalar_one()
    group = session.execute(select(ListingGroup)).scalar_one()
    assert group.cumulative_dom is not None
    assert sale.cumulative_dom == group.cumulative_dom


def test_d7_overlapping_sold_windows(engine, session, scan_env):
    sold = _row(status="SOLD", mls_status="Sold", sold_price=3250000,
                last_sold_date="2026-07-09 22:56:59")
    scan_env["sold"] = [sold]
    listing_scan.run(engine)
    listing_scan.run(engine)  # same sold record in tomorrow's overlapping window

    assert session.execute(select(func.count()).select_from(Sale)).scalar_one() == 1


def _sold_row():
    return _row(status="SOLD", mls_status="Sold", sold_price=3250000,
                last_sold_date="2026-07-09 22:56:59")


def test_closing_clears_viewed_at(engine, session, scan_env):
    """docs/08 §2b: a home opened while it was on the market is unread again
    once it closes — the sale price is the new thing to read."""
    scan_env["for_sale"] = [_row()]
    listing_scan.run(engine)
    listing = session.execute(select(Listing)).scalar_one()
    listing.viewed_at = "2026-07-07T04:52:10+00:00"  # read it while active
    session.commit()

    scan_env["for_sale"] = []
    scan_env["sold"] = [_sold_row()]
    listing_scan.run(engine)

    session.refresh(listing)
    assert listing.viewed_at is None
    types = [e.event_type for e in session.execute(select(ListingEvent)).scalars().all()]
    assert types.count("sold") == 1


def test_rescanning_a_sale_keeps_the_viewed_stamp(engine, session, scan_env):
    """The clear fires on the transition, not on `status == "sold"`. The sold
    scan re-pulls a rolling 30-day window, so a state-triggered clear would wipe
    the stamp every day for a month and the row could never be marked read."""
    scan_env["sold"] = [_sold_row()]
    listing_scan.run(engine)
    listing = session.execute(select(Listing)).scalar_one()
    listing.viewed_at = "2026-07-10T09:00:00+00:00"  # read it after it closed
    session.commit()

    listing_scan.run(engine)  # same sold record in tomorrow's overlapping window

    session.refresh(listing)
    assert listing.viewed_at == "2026-07-10T09:00:00+00:00"


def test_pending_then_back_on_market(engine, session, scan_env):
    scan_env["for_sale"] = [_row()]
    listing_scan.run(engine)
    scan_env["for_sale"] = []
    scan_env["pending"] = [_row(status="PENDING", mls_status="Pending",
                                pending_date="2026-07-10 00:00:00")]
    listing_scan.run(engine)
    scan_env["pending"] = []
    scan_env["for_sale"] = [_row()]
    listing_scan.run(engine)

    types = [e.event_type for e in session.execute(
        select(ListingEvent).order_by(ListingEvent.observed_at)
    ).scalars().all()]
    assert types.count("pending") == 1
    assert types.count("back_on_market") == 1


def test_historical_last_sold_not_stored_on_active(engine, session, scan_env):
    """A for_sale record carries the property's PREVIOUS sale in last_sold_* —
    it must not become this episode's sold_date (it zeroed all CDOMs)."""
    scan_env["for_sale"] = [_row(last_sold_date="1998-02-06 00:00:00",
                                 last_sold_price=450000)]
    listing_scan.run(engine)

    listing = session.execute(select(Listing)).scalar_one()
    assert listing.sold_date is None
    assert listing.sold_price is None

    # and the stitched group counts real market days, not zero
    from hb.db.models import ListingGroup
    group = session.execute(select(ListingGroup)).scalar_one()
    assert group.cumulative_dom > 0


def test_d15_existing_photo_never_refetched(engine, session, scan_env, monkeypatch, tmp_path):
    from hb import config

    monkeypatch.setattr(config.settings, "save_photos", True)
    calls = []

    def fake_photo(url):
        calls.append(url)
        return b"jpegbytes"

    monkeypatch.setattr(listing_scan, "fetch_photo", fake_photo)

    scan_env["for_sale"] = [_row()]
    listing_scan.run(engine)
    assert len(calls) == 1
    photos = list((tmp_path / "photos").rglob("*.jpg"))
    assert len(photos) == 1

    listing_scan.run(engine)  # file exists -> fetcher must not be called again
    assert len(calls) == 1

    listing = session.execute(select(Listing)).scalar_one()
    assert len(listing.photo_paths) == 1


def test_photo_tail_announces_its_size_and_logs_progress(engine, scan_env, monkeypatch, caplog):
    """A first run's photo tail is hours long; it must say how many are coming
    and report progress with the time left, not sit silent."""
    from hb import config

    monkeypatch.setattr(config.settings, "save_photos", True)
    monkeypatch.setattr(listing_scan, "fetch_photo", lambda url: b"jpegbytes")
    monkeypatch.setattr(listing_scan, "PHOTO_PROGRESS_EVERY", 2)
    scan_env["for_sale"] = [_row(alt_photos="https://cdn/a.jpg,https://cdn/b.jpg,https://cdn/c.jpg")]

    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)
    lines = [r.getMessage() for r in caplog.records]
    assert any("4 photos to download for 1 listings" in m and "roughly" in m for m in lines)
    assert any(m.startswith("listing-scan: photos 2/4 saved, about") for m in lines)
    assert any(m.startswith("listing-scan: photos 4/4 saved") for m in lines)
    assert any(m.startswith("listing-scan: photos done: 4 saved in") for m in lines)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)  # everything on disk: nothing announced
    assert not any("photos to download" in r.getMessage() for r in caplog.records)


def test_a_first_scan_announces_itself_once(engine, scan_env, caplog):
    """A new user's first scan is the long one: it says so up front, with the
    cities and a rough duration, and every scan logs each fetch as it starts.
    Once a completed run exists the announcement goes away."""
    scan_env["for_sale"] = [_row()]
    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)
    lines = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("listing-scan: first scan of") and "Menlo Park" in m
               and "about an hour" in m for m in lines)
    assert "listing-scan: Menlo Park (1/1): for sale" in lines

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)
    lines = [r.getMessage() for r in caplog.records]
    assert not any("first scan of" in m for m in lines)
    assert "listing-scan: Menlo Park" in lines


def test_a_slow_down_from_the_photo_cdn_pauses_and_retries(engine, scan_env, monkeypatch,
                                                            caplog, tmp_path):
    """A 429 from the image CDN is a request to back off, not a failed photo:
    every worker pauses, the file is retried, and the pause is logged."""
    import httpx

    from hb import config

    monkeypatch.setattr(config.settings, "save_photos", True)
    monkeypatch.setattr(listing_scan, "PHOTO_BACKOFF_S", 0.01)
    attempts: list[str] = []

    def flaky(url):
        attempts.append(url)
        if len(attempts) == 1:
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("slow down", request=req,
                                        response=httpx.Response(429, request=req))
        return b"jpegbytes"

    monkeypatch.setattr(listing_scan, "fetch_photo", flaky)
    scan_env["for_sale"] = [_row()]
    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)

    assert len(attempts) == 2  # the 429, then the retry
    assert len(list((tmp_path / "photos").rglob("*.jpg"))) == 1
    assert any("asked us to slow down (429)" in r.getMessage() for r in caplog.records)
    assert not any("photo download failed" in r.getMessage() for r in caplog.records)

def test_a_dropped_connection_or_5xx_is_retried_by_its_worker(engine, scan_env, monkeypatch,
                                                               caplog, tmp_path):
    """A timeout or a 502 on one photo is that request's bad luck: the worker
    pauses 2 s, then 4 s, and tries again, without pausing the others. A 404
    is not retried (the file is gone); the photo simply waits for the next scan."""
    import httpx

    from hb import config

    monkeypatch.setattr(config.settings, "save_photos", True)
    monkeypatch.setattr(listing_scan, "PHOTO_WORKERS", 1)  # deterministic order
    pauses: list[float] = []
    monkeypatch.setattr(listing_scan.time, "sleep", pauses.append)
    calls: dict[str, int] = defaultdict(int)

    def flaky(url):
        calls[url] += 1
        req = httpx.Request("GET", url)
        if url.endswith("/timeout.jpg") and calls[url] < 3:
            raise httpx.ReadTimeout("slow", request=req)
        if url.endswith("/gateway.jpg") and calls[url] == 1:
            raise httpx.HTTPStatusError("bad gateway", request=req,
                                        response=httpx.Response(502, request=req))
        if url.endswith("/gone.jpg"):
            raise httpx.HTTPStatusError("gone", request=req,
                                        response=httpx.Response(404, request=req))
        return b"jpegbytes"

    monkeypatch.setattr(listing_scan, "fetch_photo", flaky)
    scan_env["for_sale"] = [_row(alt_photos="https://cdn/timeout.jpg,https://cdn/gateway.jpg,"
                                         "https://cdn/gone.jpg")]
    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)

    assert calls["https://cdn/timeout.jpg"] == 3  # two timeouts, then the file
    assert calls["https://cdn/gateway.jpg"] == 2
    assert calls["https://cdn/gone.jpg"] == 1  # a 404 is final
    assert len(list((tmp_path / "photos").rglob("*.jpg"))) == 3  # primary + the two retried
    assert pauses.count(2.0) == 2 and pauses.count(4.0) == 1  # per-worker, doubling
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("listing-scan: photo fetch failed (ReadTimeout), retrying in 2 s")
               for m in messages)
    assert any(m.startswith("listing-scan: photo fetch failed (502), retrying in 2 s")
               for m in messages)
    assert sum("photo download failed" in m for m in messages) == 1  # only the 404
    assert not any("slow down" in m for m in messages)  # the shared throttle stayed out of it


def test_a_first_scan_creates_no_alerts(engine, session, scan_env, monkeypatch, caplog):
    """Every home is new to the database on a first scan, not to the buyer: a
    fresh install must not open with an alert per listing. Alerts start with
    the next scan, which sees what actually changed."""
    from sqlalchemy import func

    from hb.db.models import Alert

    # each run stamps its events with its own observed_at; two runs inside one
    # second would share it, so pin a different stamp per run
    monkeypatch.setattr(listing_scan, "utcnow_iso", lambda: "2026-07-06T12:00:00+00:00")
    scan_env["for_sale"] = [_row()]  # in band, in a target ZIP, 3 beds: a match any other day
    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)
    assert session.execute(select(func.count()).select_from(Alert)).scalar_one() == 0
    assert "listing-scan: first scan: no alerts; they start with the next scan" in [
        r.getMessage() for r in caplog.records]
    session.rollback()  # end this read snapshot before the second run

    monkeypatch.setattr(listing_scan, "utcnow_iso", lambda: "2026-07-07T12:00:00+00:00")
    scan_env["for_sale"] = [_row(), _row(property_id="P101", listing_id="L101", mls_id="ML101",
                                     full_street_line="812 Sample Cir", street="812 Sample Cir")]
    listing_scan.run(engine)
    assert session.execute(select(Alert.type)).scalars().all() == ["new_listing_match"]


def test_a_lone_403_skips_that_file_only(engine, session, scan_env, monkeypatch, caplog,
                                         tmp_path):
    """One forbidden file is that file's problem: skipped for this run (the next
    scan tries it again), no pause for anyone, the rest download, the run is ok."""
    import httpx

    from hb import config

    monkeypatch.setattr(config.settings, "save_photos", True)
    monkeypatch.setattr(listing_scan, "PHOTO_WORKERS", 1)

    def fetch(url):
        if url.endswith("/forbidden.jpg"):
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("forbidden", request=req,
                                        response=httpx.Response(403, request=req))
        return b"jpegbytes"

    monkeypatch.setattr(listing_scan, "fetch_photo", fetch)
    scan_env["for_sale"] = [_row(alt_photos="https://cdn/forbidden.jpg,https://cdn/ok.jpg")]
    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)

    assert len(list((tmp_path / "photos").rglob("*.jpg"))) == 2  # primary + ok.jpg
    messages = [r.getMessage() for r in caplog.records]
    assert sum("photo download failed" in m for m in messages) == 1
    assert not any("refusing" in m for m in messages)
    assert session.execute(select(PipelineRun.status)
                           .where(PipelineRun.job == "listing-scan")).scalar_one() == "ok"


def test_the_cdn_refusing_everything_pauses_then_stops_the_tail(engine, session, scan_env,
                                                                monkeypatch, caplog, tmp_path):
    """The CDN's rate limit answers 403, to every request. PHOTO_BLOCK_AFTER of
    them in a row pause every worker (doubling); refused again after
    PHOTO_BLOCK_ROUNDS pauses, the tail stops for this run with one line and
    the run is partial, instead of a 403 logged for every queued file. The
    next scan fetches what is missing."""
    import httpx

    from hb import config

    monkeypatch.setattr(config.settings, "save_photos", True)
    monkeypatch.setattr(listing_scan, "PHOTO_WORKERS", 1)  # deterministic order
    monkeypatch.setattr(listing_scan, "PHOTO_BLOCK_AFTER", 2)
    monkeypatch.setattr(listing_scan, "PHOTO_BLOCK_PAUSE_S", 0.0)  # no real waiting
    calls: dict[str, int] = defaultdict(int)

    def refused(url):
        calls[url] += 1
        if url.endswith("/first.jpg"):
            return b"jpegbytes"
        req = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("forbidden", request=req,
                                    response=httpx.Response(403, request=req))

    monkeypatch.setattr(listing_scan, "fetch_photo", refused)
    scan_env["for_sale"] = [_row(primary_photo="https://cdn/first.jpg",
                                 alt_photos=",".join(f"https://cdn/p{n}.jpg" for n in range(1, 7)))]
    with caplog.at_level(logging.INFO, logger="hb.pipelines.listing_scan"):
        listing_scan.run(engine)

    assert calls["https://cdn/p1.jpg"] == 1  # a lone 403: skipped
    assert calls["https://cdn/p2.jpg"] == 4  # the second in a row: three pauses, then the stop
    assert calls["https://cdn/p3.jpg"] == 0 and calls["https://cdn/p6.jpg"] == 0  # never tried
    messages = [r.getMessage() for r in caplog.records]
    assert sum("the photo CDN is refusing requests (403)" in m for m in messages) == 3
    assert any("stopping the photos for this run, 1 of 7 saved" in m for m in messages)
    run = session.execute(select(PipelineRun)
                          .where(PipelineRun.job == "listing-scan")).scalar_one()
    assert run.status == "partial"
    assert "the CDN refused requests (403); 6 left for the next scan" in run.error_summary


def test_gallery_download_idempotent_across_db_changes(engine, session, scan_env, monkeypatch):
    """The full gallery is downloaded once; a re-scan (or a future DB change)
    NEVER re-downloads images already on disk — files are the source of truth."""
    from hb import config

    monkeypatch.setattr(config.settings, "save_photos", True)
    calls: list[str] = []
    monkeypatch.setattr(listing_scan, "fetch_photo", lambda url: calls.append(url) or b"jpg")

    scan_env["for_sale"] = [_row(
        primary_photo="https://cdn/p.jpg",
        alt_photos="https://cdn/a.jpg, https://cdn/b.jpg",   # 3-image gallery
    )]
    listing_scan.run(engine)
    assert len(calls) == 3  # whole gallery fetched once
    listing = session.execute(select(Listing)).scalar_one()
    assert len(listing.photo_paths) == 3

    listing_scan.run(engine)  # every file on disk -> zero re-downloads
    assert len(calls) == 3

    # A future DB change wipes the recorded paths, but the files remain on disk:
    # the next scan backfills photo_paths from disk WITHOUT re-downloading anything.
    listing.photo_paths = []
    session.commit()
    listing_scan.run(engine)
    assert len(calls) == 3  # still no new fetches
    session.expire_all()
    assert len(session.execute(select(Listing)).scalar_one().photo_paths) == 3


def test_watched_home_off_market_still_refreshes_history(engine, session, scan_env, monkeypatch):
    """A delisted home drops out of the city scan, so only the Watchlist ride-along
    in the price-history tail can surface its later off-market sale."""
    from hb import watchlist
    from hb.db.models import Property, PropertyTour
    from hb.pipelines import price_history

    scan_env["for_sale"] = [_row()]
    listing_scan.run(engine)
    prop = session.execute(select(Property)).scalar_one()
    session.add(PropertyTour(property_id=prop.id, toured_on="2026-07-08"))
    watchlist.set_watching(prop, True)  # what logging the tour does
    prop.price_history_fetched_at = None  # a week has gone by
    session.commit()

    sold = [{"date": "2026-10-05", "event": "Sold", "price": 2900000}]
    monkeypatch.setattr(price_history, "fetch_price_history", lambda *a, **k: sold)
    scan_env["for_sale"] = []  # delisted: the scan no longer touches it
    listing_scan.run(engine)

    session.expire_all()
    (row,) = watchlist.rows(session)
    assert row["status"] == "sold"
    assert (row["sold_price"], row["sold_source"]) == (2900000, "public_record")


def test_d17_live_listing_revises_stale_attributes(engine, session, scan_env):
    # the home sold as a 2/1 820 sqft, was renovated, and comes back on the
    # market as a 3/2.5 1750 sqft: the for-sale record is the freshest
    # description, so it revises the property instead of being logged
    scan_env["sold"] = [_row(
        listing_id="L1", status="SOLD", mls_status="Sold", beds=2, full_baths=1, half_baths=0,
        sqft=820, list_price=1175000, list_date="2025-10-10 00:00:00",
        sold_price=1350000, last_sold_date="2025-10-28 00:00:00", last_sold_price=1350000,
    )]
    assert listing_scan.run(engine) == "ok"
    prop = session.execute(select(Property)).scalar_one()
    assert (prop.beds, prop.baths, prop.sqft) == (2, 1.0, 820)

    scan_env["sold"] = []
    scan_env["for_sale"] = [_row(listing_id="L2", beds=3, full_baths=2, half_baths=1, sqft=1750)]
    assert listing_scan.run(engine) == "ok"
    session.expire_all()
    prop = session.execute(select(Property)).scalar_one()
    assert (prop.beds, prop.baths, prop.sqft) == (3, 2.5, 1750)
    assert {"field": "sqft", "kept": 1750, "replaced": 820} in prop.source_ids["conflicts"]

    # the old sold record re-observed in a rolling window is history: it logs,
    # it does not revert the live description
    scan_env["sold"] = [_row(
        listing_id="L1", status="SOLD", mls_status="Sold", beds=2, full_baths=1, half_baths=0,
        sqft=820, list_price=1175000, list_date="2025-10-10 00:00:00",
        sold_price=1350000, last_sold_date="2025-10-28 00:00:00", last_sold_price=1350000,
    )]
    assert listing_scan.run(engine) == "ok"
    session.expire_all()
    prop = session.execute(select(Property)).scalar_one()
    assert (prop.beds, prop.baths, prop.sqft) == (3, 2.5, 1750)
