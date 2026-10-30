from datetime import date, timedelta

from sqlalchemy import func, select

from hb.alerts import channels, rules
from hb.db.models import Alert, Listing, ListingEvent, PipelineRun, Property, TrackedListing

OBS = "2026-07-14T12:00:00+00:00"


def _listing(session, price=2_500_000, zip5="94087", beds=3, tracked=False, **over):
    prop = Property(address_norm=f"{price} TEST ST", zip=zip5, city="Sunnyvale", beds=beds,
                    sqft=1600)
    session.add(prop)
    session.flush()
    lst = Listing(property_id=prop.id, source="realtor",
                  source_listing_id=f"L{price}{zip5}{beds}", status="active",
                  list_price=price, original_list_price=price, list_date="2026-07-01",
                  **over)
    session.add(lst)
    session.flush()
    if tracked:
        session.add(TrackedListing(listing_id=lst.id))
        session.flush()
    return lst


def _event(session, listing, etype, old=None, new=None, observed=OBS):
    e = ListingEvent(listing_id=listing.id, event_type=etype,
                     old_value=None if old is None else str(old),
                     new_value=None if new is None else str(new), observed_at=observed)
    session.add(e)
    session.flush()
    return e


def _alert_count(session):
    return session.execute(select(func.count()).select_from(Alert)).scalar_one()


def test_price_cut_in_band_fires_once_d11(session):
    lst = _listing(session, price=2_450_000)
    ev = _event(session, lst, "price_change", 2_500_000, 2_450_000)
    session.commit()

    assert rules.evaluate(session, [ev], OBS) == 1
    session.commit()
    # D11: same events re-evaluated -> nothing new
    assert rules.evaluate(session, [ev], OBS) == 0
    assert _alert_count(session) == 1

    alert = session.execute(select(Alert)).scalar_one()
    assert alert.type == "price_cut"
    assert alert.payload["pct"] > 0


def test_out_of_band_not_alerted_unless_tracked(session):
    cheap = _listing(session, price=900_000)  # far below $2M-20%
    ev1 = _event(session, cheap, "price_change", 950_000, 900_000)
    assert rules.evaluate(session, [ev1], OBS) == 0

    tracked_cheap = _listing(session, price=900_001, tracked=True)
    ev2 = _event(session, tracked_cheap, "price_change", 950_000, 900_001)
    assert rules.evaluate(session, [ev2], OBS) == 1  # tracked overrides band


def test_new_comp_sold_within_radius_fires_once(session):
    from hb.db.models import Sale

    # tracked listing at a known location
    tprop = Property(address_norm="1 TRACKED WAY", zip="94087", city="Sunnyvale",
                     lat=37.350, lon=-122.030, beds=3, sqft=1600)
    session.add(tprop)
    session.flush()
    tlst = Listing(property_id=tprop.id, source="realtor", source_listing_id="T1",
                   status="active", list_price=2_500_000, original_list_price=2_500_000)
    session.add(tlst)
    session.flush()
    session.add(TrackedListing(listing_id=tlst.id))

    def _sale(dlat, dlon, price):
        p = Property(address_norm=f"{dlat}{dlon} COMP CT", zip="94087", city="Sunnyvale",
                     lat=37.350 + dlat, lon=-122.030 + dlon, beds=3, sqft=1600)
        session.add(p)
        session.flush()
        s = Sale(property_id=p.id, sale_date="2026-07-10", sale_price=price,
                 original_list_price=price, sp_lp=1.0, dom=8, source="realtor_sold_scan")
        session.add(s)
        session.flush()
        return s

    near = _sale(0.002, 0.0, 2_310_000)   # ~0.14 mi
    far = _sale(0.02, 0.0, 2_400_000)     # ~1.4 mi
    session.commit()

    n = rules.evaluate(session, [], OBS, new_sale_ids={near.id, far.id})
    session.commit()
    assert n == 1  # only the nearby comp
    alert = session.execute(select(Alert).where(Alert.type == "new_comp_sold")).scalar_one()
    assert alert.payload["price"] == 2_310_000
    assert alert.payload["ppsf"] == round(2_310_000 / 1600)
    assert alert.payload["distance_mi"] <= 0.5

    # D11: re-evaluation over the same sales emits nothing new
    assert rules.evaluate(session, [], OBS, new_sale_ids={near.id, far.id}) == 0


def test_price_increase_not_a_cut(session):
    lst = _listing(session)
    ev = _event(session, lst, "price_change", 2_400_000, 2_500_000)
    assert rules.evaluate(session, [ev], OBS) == 0


def test_new_listing_match_band_zip_beds(session):
    hit = _listing(session, price=2_500_000, zip5="94087", beds=4)
    miss_band = _listing(session, price=3_500_000, zip5="94087", beds=4)
    miss_beds = _listing(session, price=2_500_000, zip5="94301", beds=2)
    events = [
        _event(session, hit, "new", None, 2_500_000),
        _event(session, miss_band, "new", None, 3_500_000),
        _event(session, miss_beds, "new", None, 2_500_000),
    ]
    assert rules.evaluate(session, events, OBS) == 1
    alert = session.execute(select(Alert)).scalar_one()
    assert alert.type == "new_listing_match"
    assert alert.payload["zip"] == "94087"


def test_d12_offer_date_buckets_exactly_two(session, monkeypatch):
    real_today = date.today()
    due = real_today + timedelta(days=5)
    _listing(session, tracked=True, offer_due_at=due.isoformat())
    session.commit()

    # fixed deadline; advance the clock one day at a time (matrix D12)
    class FakeDate(date):
        _now = real_today

        @classmethod
        def today(cls):
            return cls._now

    monkeypatch.setattr(rules, "date", FakeDate)
    for days_out in range(5, -1, -1):
        FakeDate._now = due - timedelta(days=days_out)
        rules.evaluate(session, [], OBS)
        session.commit()

    n = session.execute(
        select(func.count()).select_from(Alert).where(Alert.type == "offer_date_soon")
    ).scalar_one()
    assert n == 2  # 3-day bucket + 1-day bucket, never more


def test_delivery_marks_and_retries(session, monkeypatch):
    lst = _listing(session, price=2_450_000)
    ev = _event(session, lst, "price_change", 2_500_000, 2_450_000)
    rules.evaluate(session, [ev], OBS)
    session.commit()

    monkeypatch.setattr(channels.settings, "alert_channels", "toast")
    monkeypatch.setattr(channels, "send_toast", lambda *a: False)  # channel down
    assert channels.deliver_pending(session) == 0
    assert session.execute(select(Alert)).scalar_one().delivered_at is None  # retry-safe

    monkeypatch.setattr(channels, "send_toast", lambda *a: True)
    assert channels.deliver_pending(session) == 1
    alert = session.execute(select(Alert)).scalar_one()
    assert alert.delivered_at is not None
    assert alert.channel == "toast"

    assert channels.deliver_pending(session) == 0  # nothing pending anymore


def test_every_alert_gets_its_own_notification_committed_as_it_goes(session, monkeypatch):
    """One toast and one push per alert, each linking to its own listing,
    however many are pending; and each alert is committed on its own, so the
    database's write lock is never held while a toast is on screen."""
    for n in range(5):
        lst = _listing(session, price=2_400_000 + n * 10_000)
        _event(session, lst, "price_change", 2_600_000, lst.list_price)
    rules.evaluate(session, session.execute(select(ListingEvent)).scalars().all(), OBS)
    session.commit()
    assert _alert_count(session) == 5

    monkeypatch.setattr(channels.settings, "alert_channels", "toast,pushover,log")
    monkeypatch.setattr(channels.settings, "pushover_token", "app-token")
    monkeypatch.setattr(channels.settings, "pushover_user", "user-key")
    monkeypatch.setattr(channels.settings, "app_base_url", "https://hb.example.ts.net")
    toasts: list[tuple] = []
    pushes: list[dict] = []
    monkeypatch.setattr(channels, "send_toast", lambda *a: toasts.append(a) or True)
    monkeypatch.setattr(channels, "_pushover_post",
                        lambda data: pushes.append(data) or _PushoverReply(200, {"status": 1}))
    commits: list[int] = []
    real_commit = session.commit
    monkeypatch.setattr(session, "commit", lambda: commits.append(1) or real_commit())

    assert channels.deliver_pending(session) == 5
    assert len(toasts) == 5 and len(pushes) == 5  # one each per alert
    assert {t[0] for t in toasts} == {"price cut"}
    assert len({t[2] for t in toasts}) == 5  # each toast opens its own listing
    assert len({p["url"] for p in pushes}) == 5
    assert all(p["url"].startswith("https://hb.example.ts.net/listings/") for p in pushes)
    assert len(commits) == 5  # one commit per alert, not one at the end
    rows = session.execute(select(Alert)).scalars().all()
    assert all(a.delivered_at and a.channel == "toast,pushover,log" for a in rows)


class _PushoverReply:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def test_pushover_posts_each_alert_with_its_link(session, monkeypatch):
    lst = _listing(session, price=2_450_000)
    ev = _event(session, lst, "price_change", 2_500_000, 2_450_000)
    rules.evaluate(session, [ev], OBS)
    session.commit()

    monkeypatch.setattr(channels.settings, "alert_channels", "pushover")
    monkeypatch.setattr(channels.settings, "pushover_token", "")
    monkeypatch.setattr(channels.settings, "pushover_user", "")
    assert channels.deliver_pending(session) == 0  # unconfigured never counts as delivered

    monkeypatch.setattr(channels.settings, "pushover_token", "app-token")
    monkeypatch.setattr(channels.settings, "pushover_user", "user-key")
    monkeypatch.setattr(channels.settings, "app_base_url", "https://hb.example.ts.net")
    posted = []
    monkeypatch.setattr(channels, "_pushover_post",
                        lambda data: posted.append(data) or _PushoverReply(200, {"status": 1}))

    assert channels.deliver_pending(session) == 1
    alert = session.execute(select(Alert)).scalar_one()
    assert alert.channel == "pushover"
    (data,) = posted
    assert data["token"] == "app-token" and data["user"] == "user-key"
    assert data["title"] == "price cut"
    assert data["message"].startswith("↓ $50,000")
    assert data["url"] == f"https://hb.example.ts.net/listings/{alert.listing_id}"


def test_pushover_rejection_leaves_alert_pending(session, monkeypatch):
    lst = _listing(session, price=2_450_000)
    ev = _event(session, lst, "price_change", 2_500_000, 2_450_000)
    rules.evaluate(session, [ev], OBS)
    session.commit()

    monkeypatch.setattr(channels.settings, "alert_channels", "pushover")
    monkeypatch.setattr(channels.settings, "pushover_token", "app-token")
    monkeypatch.setattr(channels.settings, "pushover_user", "user-key")
    rejected = _PushoverReply(400, {"status": 0, "errors": ["user identifier is invalid"]})
    monkeypatch.setattr(channels, "_pushover_post", lambda data: rejected)

    assert channels.deliver_pending(session) == 0
    assert session.execute(select(Alert)).scalar_one().delivered_at is None  # retried next run


def test_formatter_price_cut(session):
    lst = _listing(session, price=2_100_000)
    ev = _event(session, lst, "price_change", 2_200_000, 2_100_000)
    rules.evaluate(session, [ev], OBS)
    session.commit()
    alert = session.execute(select(Alert)).scalar_one()
    text = channels.format_alert(session, alert)
    assert "$100,000" in text and "Sunnyvale" in text and "$2,100,000" in text


def _scan_run(session, status, started_at):
    session.add(PipelineRun(job="listing-scan", status=status, started_at=started_at))
    session.flush()


def test_scan_failure_skips_the_running_scan(session):
    _scan_run(session, "failed", "2026-07-13T05:00:00+00:00")
    _scan_run(session, "failed", "2026-07-13T15:00:00+00:00")
    _scan_run(session, "running", "2026-07-14T05:00:00+00:00")
    assert rules.check_scan_failure(session) == 1
    assert rules.check_scan_failure(session) == 0  # one alert per day
    alert = session.execute(select(Alert)).scalar_one()
    assert alert.type == "scan_failure"
    assert alert.payload["runs"] == ["2026-07-13T15:00:00+00:00", "2026-07-13T05:00:00+00:00"]
    assert "last 2 listing scans failed" in channels.format_alert(session, alert)


def test_scan_failure_needs_two_failed_in_a_row(session):
    _scan_run(session, "failed", "2026-07-13T05:00:00+00:00")
    _scan_run(session, "ok", "2026-07-13T15:00:00+00:00")
    _scan_run(session, "failed", "2026-07-14T05:00:00+00:00")
    assert rules.check_scan_failure(session) == 0
    assert _alert_count(session) == 0
