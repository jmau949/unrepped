from hb.db.models import Property
from hb.pipelines import price_history as sr
from hb.pipelines.listing_scan import _photo_urls
from hb.pipelines.price_history import _parse_history


def test_parse_history_dedup_sort_truncate():
    raw = [
        {"date": "2026-07-14T00:00:00", "event_name": "Listed", "price": 2_890_000},
        {"date": "2026-07-14T00:00:00", "event_name": "Listed", "price": 2_890_000},  # dup
        {"date": "1984-01-13", "event_name": "Sold", "price": 205_000},
        {"date": None, "event_name": "Ignored", "price": 1},          # no date -> dropped
        {"date": "2021-06-30", "event_name": "Sold", "price": None},  # null price kept
    ]
    out = _parse_history(raw)
    assert [e["date"] for e in out] == ["2026-07-14", "2021-06-30", "1984-01-13"]  # newest first
    assert out[0] == {"date": "2026-07-14", "event": "Listed", "price": 2_890_000}
    assert out[1]["price"] is None


def test_refresh_one_stores_and_gates(session, monkeypatch):
    calls = []
    monkeypatch.setattr(sr, "fetch_price_history",
                        lambda addr, mpr=None: calls.append(mpr) or
                        [{"date": "2001-12-21", "event": "Sold", "price": 480_000}])
    prop = Property(address_norm="1 X ST", zip="94087", city="Sunnyvale", street="1 X St",
                    source_ids={"realtor": ["123"]})
    session.add(prop)
    session.commit()

    assert sr.refresh_one(session, prop) is True
    assert prop.price_history == [{"date": "2001-12-21", "event": "Sold", "price": 480_000}]
    assert prop.price_history_fetched_at is not None
    assert calls == ["123"]  # used the stored mpr_id, not an address search

    # fresh cache -> gated, no refetch
    assert sr.refresh_one(session, prop) is False
    assert calls == ["123"]


def _prop(session, addr, realtor_id, **over):
    p = Property(address_norm=addr, zip="94087", city="Sunnyvale", street=addr,
                 source_ids={"realtor": [realtor_id]}, **over)
    session.add(p)
    session.flush()
    return p


def test_backfill_scope_covers_the_comp_pool(session, monkeypatch):
    """The derivation exists to repair comps, and comps are sold properties — an
    inventory-only scope would leave the overbid model exactly as blind."""
    from hb.db.models import Listing, Sale

    inventory = _prop(session, "1 ACTIVE ST", "A1")
    comp = _prop(session, "2 SOLD ST", "S1")
    orphan = _prop(session, "3 NOTHING ST", "N1")  # no listing, no sale
    session.add(Listing(property_id=inventory.id, source="realtor",
                        source_listing_id="L1", status="active"))
    session.add(Sale(property_id=comp.id, sale_date="2026-03-01", sale_price=2_000_000))
    session.commit()

    scoped = {p.id for p in sr._backfill_candidates(session)}
    assert inventory.id in scoped
    assert comp.id in scoped
    assert orphan.id not in scoped


def test_backfill_limit_is_resumable(session, monkeypatch):
    """--limit caps fetches, and never-fetched properties sort first so a chunked
    backfill always advances instead of re-walking the same head."""
    from hb.db.models import Sale

    calls = []
    monkeypatch.setattr(sr, "fetch_price_history", lambda a, m=None: calls.append(a) or [])
    monkeypatch.setattr(sr.time, "sleep", lambda *_: None)

    for i in range(4):
        p = _prop(session, f"{i} COMP ST", f"C{i}")
        session.add(Sale(property_id=p.id, sale_date="2026-03-01", sale_price=2_000_000))
    session.commit()

    assert sr.refresh_many(session, limit=2) == 2
    assert len(calls) == 2
    # the two already fetched now sort last -> the next chunk covers the rest
    assert sr.refresh_many(session, limit=2) == 2
    assert len(set(calls)) == 4


def test_photo_urls_extracts_full_gallery():
    row = {"primary_photo": "http://x/p.jpg",
           "alt_photos": "http://x/a.jpg, http://x/b.jpg, http://x/p.jpg"}
    # primary first, alt_photos split on comma, deduped (primary appears in alt too)
    assert _photo_urls(row) == ["http://x/p.jpg", "http://x/a.jpg", "http://x/b.jpg"]
    assert _photo_urls({"primary_photo": None, "alt_photos": None}) == []
    assert _photo_urls({"primary_photo": "http://x/only.jpg", "alt_photos": None}) == \
        ["http://x/only.jpg"]
