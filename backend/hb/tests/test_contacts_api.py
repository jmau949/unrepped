"""/api/listings/{id}/contacts — the people behind a listing (docs/07 §Listings)."""

import pytest
from fastapi.testclient import TestClient

from hb.db.models import Listing, Property


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.contacts as contacts_module
    import hb.api.listings as listings_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (listings_module, contacts_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))

    from hb.main import app

    return TestClient(app)


@pytest.fixture
def listings(session):
    ids = []
    for sid in ("C1", "C2"):
        prop = Property(address_norm=f"{sid} ELM ST", zip="94087", city="Sunnyvale",
                        beds=3, baths=2.0, sqft=1500, lat=37.3, lon=-122.0)
        session.add(prop)
        session.flush()
        lst = Listing(property_id=prop.id, source="realtor", source_listing_id=sid,
                      status="active", list_price=2_000_000, list_date="2026-07-01")
        session.add(lst)
        session.flush()
        ids.append(lst.id)
    session.commit()
    return ids


def test_unknown_listing_404s(client):
    assert client.get("/api/listings/nope/contacts").status_code == 404
    assert client.post("/api/listings/nope/contacts",
                       json={"kind": "owner", "name": "X"}).status_code == 404


def test_listing_contacts_crud(client, listings):
    a, b = listings

    made = client.post(f"/api/listings/{a}/contacts",
                       json={"kind": "listing_agent", "name": "J. Lister",
                             "company": "Example Realty", "phone": "650-555-0123"}).json()
    assert made["listing_id"] == a and made["deal_id"] is None
    assert made["kind"] == "listing_agent"

    # the owner of record is a kind here, found on the assessor roll by hand
    owner = client.post(f"/api/listings/{a}/contacts",
                        json={"kind": "owner", "name": "J. Seller"}).json()
    assert owner["kind"] == "owner"

    assert client.post(f"/api/listings/{a}/contacts",
                       json={"kind": "wizard", "name": "X"}).status_code == 422

    listed = client.get(f"/api/listings/{a}/contacts").json()
    assert [c["kind"] for c in listed] == ["listing_agent", "owner"]

    patched = client.patch(f"/api/listings/{a}/contacts/{made['id']}",
                           json={"phone": "650-555-0160", "company": ""}).json()
    assert patched["phone"] == "650-555-0160"
    assert patched["company"] is None  # "" clears
    assert client.patch(f"/api/listings/{a}/contacts/{made['id']}",
                        json={"kind": "wizard"}).status_code == 422

    # a contact belongs to its listing: listing B cannot see, edit or delete it
    assert client.patch(f"/api/listings/{b}/contacts/{made['id']}",
                        json={"phone": "1"}).status_code == 404
    assert client.delete(f"/api/listings/{b}/contacts/{made['id']}").status_code == 404
    assert client.get(f"/api/listings/{b}/contacts").json() == []

    # and it rides along on the detail payload
    detail = client.get(f"/api/listings/{a}").json()
    assert [c["id"] for c in detail["contacts"]] == [made["id"], owner["id"]]

    assert client.delete(f"/api/listings/{a}/contacts/{made['id']}").json() == {
        "deleted": made["id"]}
    assert [c["id"] for c in client.get(f"/api/listings/{a}/contacts").json()] == [owner["id"]]
