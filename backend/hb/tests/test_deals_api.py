from datetime import date

import pytest
from fastapi.testclient import TestClient

from hb import closing_spec, packs
from hb.db.models import Listing, Property, TrackedListing


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.contacts as contacts_module
    import hb.api.deals as deals_module
    import hb.api.listings as listings_module
    import hb.api.tracker as tracker_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (listings_module, tracker_module, deals_module, contacts_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))

    from hb.main import app

    return TestClient(app)


def _home(session, *, city: str, year_built: int, sid: str) -> dict:
    prop = Property(address_norm=f"{sid} OAK AVE", zip="94070", city=city,
                    beds=3, baths=2.0, sqft=1600, lot_sqft=6000, year_built=year_built,
                    lat=37.5, lon=-122.26)
    session.add(prop)
    session.flush()
    listing = Listing(property_id=prop.id, source="realtor", source_listing_id=sid,
                      status="pending", list_price=2_290_000, list_date="2026-07-01")
    session.add(listing)
    session.commit()
    return {"property_id": prop.id, "listing_id": listing.id}


@pytest.fixture
def home(session):
    """Pre-1980 San Carlos home — no point-of-sale sewer ordinance (docs/14 §7)."""
    return _home(session, city="San Carlos", year_built=1955, sid="D1")


# --- date math: pure functions, no client ---


def test_anchors_resolve_rpa_defaults_off_acceptance():
    deal = {"accepted_on": "2026-09-14", "close_of_escrow_on": "2026-10-14",
            "investigation_days": 17, "appraisal_days": 17, "loan_days": 21}
    a = closing_spec.anchors(deal)
    assert a["acceptance"] == date(2026, 9, 14)
    # 17 and 21 CALENDAR days after Acceptance — the worked timeline in docs/14 §4
    assert a["investigation_removal"] == date(2026, 10, 1)
    assert a["appraisal_removal"] == date(2026, 10, 1)
    assert a["loan_removal"] == date(2026, 10, 5)
    assert a["coe"] == date(2026, 10, 14)


def test_emd_is_business_days_not_calendar():
    # Monday acceptance -> Thursday (Tue/Wed/Thu), matching the docs/14 §4 table
    assert closing_spec.anchors(
        {"accepted_on": "2026-09-14"})["emd"] == date(2026, 9, 17)
    # Thursday acceptance skips the weekend and lands the following Tuesday
    assert closing_spec.anchors(
        {"accepted_on": "2026-09-17"})["emd"] == date(2026, 9, 22)


def test_waiving_a_contingency_drops_its_whole_chain():
    base = {"accepted_on": "2026-09-14", "close_of_escrow_on": "2026-10-14",
            "investigation_days": 17, "appraisal_days": 17, "loan_days": 21}
    with_loan = {t["key"] for t in closing_spec.schedule(base)}
    without = {t["key"] for t in closing_spec.schedule({**base, "loan_days": None})}

    assert "remove_loan" in with_loan
    # not just the removal task — everything anchored to it goes too
    assert {"remove_loan", "clear_to_close", "underwriting_conditions"} & without == set()
    # tasks anchored elsewhere are untouched
    assert "remove_investigation" in without
    assert "loan_application_complete" in without  # anchored to acceptance, not the removal


def test_unfinanced_deal_drops_the_loan_tasks():
    base = {"accepted_on": "2026-09-14", "close_of_escrow_on": "2026-10-14",
            "investigation_days": 17, "appraisal_days": 17, "loan_days": 21,
            "financed": False}
    keys = {t["key"] for t in closing_spec.schedule(base)}
    assert "loan_application_complete" not in keys
    assert "cd_vs_le_compared" not in keys
    # a cash buyer still walks the house and still wires money
    assert {"final_walkthrough", "wire_cash_to_close", "wire_emd"} <= keys


def test_applies_when_prunes_by_year_and_city():
    deal = {"accepted_on": "2026-09-14", "close_of_escrow_on": "2026-10-14",
            "investigation_days": 17, "appraisal_days": 17, "loan_days": 21}

    old = {t["key"] for t in closing_spec.schedule(deal, {"year_built": 1955,
                                                          "city": "San Carlos"})}
    new = {t["key"] for t in closing_spec.schedule(deal, {"year_built": 2015,
                                                          "city": "Palo Alto"})}
    assert {"lead_paint_disclosure", "structural_engineer", "chimney_inspection"} <= old
    assert {"lead_paint_disclosure", "structural_engineer", "chimney_inspection"} & new == set()

    # Burlingame requires a point-of-sale sewer certificate; San Carlos does not
    burlingame = {t["key"] for t in closing_spec.schedule(deal, {"city": "Burlingame"})}
    san_carlos = {t["key"] for t in closing_spec.schedule(deal, {"city": "San Carlos"})}
    assert "city_pos_report" in burlingame
    assert "city_pos_report" not in san_carlos
    # unknown city keeps it — a missed ordinance is a five-figure surprise
    assert "city_pos_report" in {t["key"] for t in closing_spec.schedule(deal, {})}


def test_evaluate_splits_overdue_from_due_soon():
    deal = {"accepted_on": "2026-09-14", "close_of_escrow_on": "2026-10-14",
            "investigation_days": 17, "appraisal_days": 17, "loan_days": 21}
    roll = closing_spec.evaluate(deal, {}, {}, today=date(2026, 9, 18))

    assert {t["key"] for t in roll["overdue"]} >= {"executed_contract", "wire_emd"}
    assert roll["days_to_close"] == 26
    assert roll["next_action"]["key"] is not None
    assert roll["costs"]["low"] > 0 and roll["costs"]["high"] > roll["costs"]["low"]
    assert roll["waived"] == []


def test_cost_bands_are_deduped_on_rollup():
    deal = {"accepted_on": "2026-09-14", "close_of_escrow_on": "2026-10-14",
            "investigation_days": 17, "appraisal_days": 17, "loan_days": 21}
    roll = closing_spec.evaluate(deal, {}, {}, today=date(2026, 9, 18))
    keys = [item["key"] for item in roll["costs"]["items"]]
    assert len(keys) == len(set(keys))
    assert roll["costs"]["low"] == sum(i["low"] for i in roll["costs"]["items"])


# --- API ---


def test_create_is_idempotent_and_seeds_rpa_defaults(client, home):
    first = client.post("/api/deals", json={"listing_id": home["listing_id"],
                                            "accepted_on": "2026-09-14"}).json()
    second = client.post("/api/deals", json={"listing_id": home["listing_id"]}).json()
    assert first["id"] == second["id"]
    assert len(client.get("/api/deals").json()) == 1

    assert first["investigation_days"] == 17
    assert first["appraisal_days"] == 17
    assert first["loan_days"] == 21
    assert first["purchase_price"] == 2_290_000  # falls back to list price
    assert first["rollup"]["anchors"]["loan_removal"] == "2026-10-05"


def test_create_moves_a_tracked_listing_to_closing(client, home, session):
    session.add(TrackedListing(listing_id=home["listing_id"], stage="won"))
    session.commit()

    client.post("/api/deals", json={"listing_id": home["listing_id"]})

    tracked = client.get("/api/tracker").json()[0]
    assert tracked["stage"] == "closing"
    assert tracked["deal_id"] is not None


def test_patch_merges_checklist_and_recomputes_rollup(client, home):
    deal = client.post("/api/deals", json={"listing_id": home["listing_id"],
                                           "accepted_on": "2026-09-14"}).json()
    before = deal["rollup"]["done"]

    client.patch(f"/api/deals/{deal['id']}",
                 json={"checklist": {"wire_emd": {"done_on": "2026-09-17"}}})
    body = client.patch(f"/api/deals/{deal['id']}",
                        json={"checklist": {"open_escrow": {"done_on": "2026-09-15"}}}).json()

    # the first PATCH's value survives the second — JSON columns merge
    assert body["checklist"]["wire_emd"]["done_on"] == "2026-09-17"
    assert body["checklist"]["open_escrow"]["done_on"] == "2026-09-15"
    # the roll-up is recomputed on read, never stored
    assert body["rollup"]["done"] == before + 2


def test_every_form_code_ships_a_plain_english_name():
    """A badge reading "BNA" is noise to the buyer this spec is written for."""
    pack = packs.current()
    used = {t.form for t in pack.closing.tasks if t.form}
    assert used <= set(pack.closing.forms), f"undocumented forms: {used - set(pack.closing.forms)}"
    for form in pack.closing.forms.values():
        assert form.name and form.what
        assert form.name != form.code

    rows = closing_spec.schedule({"accepted_on": "2026-09-14",
                                  "close_of_escrow_on": "2026-10-14",
                                  "investigation_days": 17, "appraisal_days": 17,
                                  "loan_days": 21})
    for row in rows:
        assert bool(row["form_name"]) == bool(row["form"])


def test_no_task_hides_behind_a_bare_acronym():
    """If a label uses an initialism, why/how has to spell it out on the same card.

    The failure this guards against is real and was reported: "Sign the agency
    disclosures (AD, BNA)" told the reader nothing they didn't already know.
    """
    # Initialisms a first-time buyer cannot be assumed to know.
    jargon = ["AD", "BNA", "TDS", "SPQ", "NHD", "CR", "NBP", "RR", "VP", "ETA", "RPA",
              "EMD", "COE", "CD", "LE", "WDO", "DIC", "CEA"]
    for task in packs.current().closing.tasks:
        body = f"{task.why} {task.how}"
        for word in task.label.replace("(", " ").replace(")", " ").replace(",", " ").split():
            if word.strip(".:—") in jargon:
                assert word.strip(".:—") in body or task.form, (
                    f"{task.key}: label uses '{word}' with no explanation in why/how"
                )


def test_spec_rows_carry_the_checked_state(client, home):
    """The UI renders its checkboxes from `spec`, not from `rollup`.

    Regression: spec_for() used to build rows without the checklist, so every task
    came back done=False while rollup.done reported the true count — every box you
    ticked reappeared empty on reload.
    """
    deal = client.post("/api/deals", json={"listing_id": home["listing_id"],
                                           "accepted_on": "2026-09-14"}).json()
    body = client.patch(f"/api/deals/{deal['id']}", json={
        "checklist": {"wire_emd": {"done_on": "2026-09-17", "note": "voice-verified"}},
    }).json()

    rows = {t["key"]: t for p in body["spec"]["phases"] for t in p["tasks"]}
    assert rows["wire_emd"]["done"] is True
    assert rows["wire_emd"]["done_on"] == "2026-09-17"
    assert rows["wire_emd"]["note"] == "voice-verified"
    assert rows["executed_contract"]["done"] is False
    # and the two views agree on the count
    assert body["rollup"]["done"] == sum(1 for t in rows.values() if t["done"] or t["waived"])

    # survives a plain re-read
    again = client.get(f"/api/deals/{deal['id']}").json()
    assert {t["key"]: t["done"] for p in again["spec"]["phases"]
            for t in p["tasks"]}["wire_emd"] is True


def test_unticking_a_task_clears_it_everywhere(client, home):
    deal = client.post("/api/deals", json={"listing_id": home["listing_id"]}).json()
    client.patch(f"/api/deals/{deal['id']}",
                 json={"checklist": {"wire_emd": {"done_on": "2026-09-17"}}})
    body = client.patch(f"/api/deals/{deal['id']}",
                        json={"checklist": {"wire_emd": {"done_on": None}}}).json()
    rows = {t["key"]: t for p in body["spec"]["phases"] for t in p["tasks"]}
    assert rows["wire_emd"]["done"] is False
    assert body["rollup"]["done"] == 0


def test_patch_merges_within_a_task_entry(client, home):
    deal = client.post("/api/deals", json={"listing_id": home["listing_id"]}).json()
    client.patch(f"/api/deals/{deal['id']}",
                 json={"checklist": {"wire_emd": {"note": "verified by phone"}}})
    body = client.patch(f"/api/deals/{deal['id']}",
                        json={"checklist": {"wire_emd": {"done_on": "2026-09-17"}}}).json()
    assert body["checklist"]["wire_emd"] == {"note": "verified by phone",
                                             "done_on": "2026-09-17"}


def test_waive_clears_a_contingency_and_prunes_tasks(client, home):
    deal = client.post("/api/deals", json={"listing_id": home["listing_id"],
                                           "accepted_on": "2026-09-14"}).json()
    keys = {t["key"] for p in deal["spec"]["phases"] for t in p["tasks"]}
    assert "remove_appraisal" in keys

    body = client.patch(f"/api/deals/{deal['id']}", json={"waive": ["appraisal"]}).json()
    assert body["appraisal_days"] is None
    assert body["rollup"]["waived"] == ["appraisal_removal"]
    keys = {t["key"] for p in body["spec"]["phases"] for t in p["tasks"]}
    assert "remove_appraisal" not in keys
    assert "remove_investigation" in keys


def test_patch_validates_enums_and_dates(client, home):
    deal = client.post("/api/deals", json={"listing_id": home["listing_id"]}).json()
    assert client.patch(f"/api/deals/{deal['id']}",
                        json={"status": "nope"}).status_code == 422
    assert client.patch(f"/api/deals/{deal['id']}",
                        json={"accepted_on": "sept 14"}).status_code == 422
    assert client.patch(f"/api/deals/{deal['id']}",
                        json={"waive": ["termite"]}).status_code == 422


def test_spec_preview_needs_no_deal(client, home):
    body = client.get("/api/deals/spec",
                      params={"listing_id": home["listing_id"]}).json()
    keys = {t["key"] for p in body["phases"] for t in p["tasks"]}
    assert "remove_investigation" in keys
    assert "lead_paint_disclosure" in keys  # 1955 home
    # COE defaults to a 30-day escrow so the preview shows the WHOLE process —
    # an unset anchor would silently drop the final week and everything after close
    assert {p["key"] for p in body["phases"]} == {
        "lock_down", "disclosures", "inspections", "loan", "title_insurance",
        "negotiate", "final_week", "post_close",
    }
    assert {"final_walkthrough", "homeowners_exemption"} <= keys
    # every task carries the first-timer explanation, which is the point of the spec
    assert all(t["why"] and t["how"] for p in body["phases"] for t in p["tasks"])


def test_deal_team_crud(client, home):
    deal = client.post("/api/deals", json={"listing_id": home["listing_id"]}).json()

    made = client.post(f"/api/deals/{deal['id']}/contacts",
                       json={"kind": "escrow", "name": "A. Officer",
                             "company": "Old Republic", "phone": "650-555-0100"}).json()
    assert made["kind"] == "escrow"

    assert client.post(f"/api/deals/{deal['id']}/contacts",
                       json={"kind": "wizard", "name": "X"}).status_code == 422

    client.patch(f"/api/deals/{deal['id']}/contacts/{made['id']}",
                 json={"phone": "650-555-0199"})
    assert client.get(f"/api/deals/{deal['id']}/contacts").json()[0]["phone"] == "650-555-0199"

    assert client.get(f"/api/deals/{deal['id']}").json()["contacts"][0]["id"] == made["id"]

    client.delete(f"/api/deals/{deal['id']}/contacts/{made['id']}")
    assert client.get(f"/api/deals/{deal['id']}/contacts").json() == []


def test_deal_team_adopts_contacts_saved_on_the_listing(client, home):
    """The listing agent reached before the offer is the same person you negotiate
    with in escrow: a contact saved on the listing is part of the deal team, can be
    edited through the deal routes, and outlives the deal (docs/04 §contacts)."""
    lid = home["listing_id"]
    saved = client.post(f"/api/listings/{lid}/contacts",
                        json={"kind": "listing_agent", "name": "J. Lister"}).json()
    assert saved["listing_id"] == lid and saved["deal_id"] is None

    deal = client.post("/api/deals", json={"listing_id": lid}).json()
    assert [c["id"] for c in deal["contacts"]] == [saved["id"]]
    assert client.get(f"/api/deals/{deal['id']}/contacts").json()[0]["id"] == saved["id"]

    assert client.patch(f"/api/deals/{deal['id']}/contacts/{saved['id']}",
                        json={"phone": "650-555-0123"}).json()["phone"] == "650-555-0123"

    # a contact on some other listing is not this deal's business
    assert client.patch(f"/api/deals/{deal['id']}/contacts/nope",
                        json={"phone": "1"}).status_code == 404

    assert client.delete(f"/api/deals/{deal['id']}").status_code == 200
    assert [c["id"] for c in client.get(f"/api/listings/{lid}/contacts").json()] == [saved["id"]]
    assert client.delete(f"/api/deals/{deal['id']}/contacts/{saved['id']}").status_code == 404


def test_delete_deal_takes_its_contacts(client, home):
    deal = client.post("/api/deals", json={"listing_id": home["listing_id"]}).json()
    client.post(f"/api/deals/{deal['id']}/contacts", json={"kind": "lender", "name": "L"})

    assert client.delete(f"/api/deals/{deal['id']}").status_code == 200
    assert client.get("/api/deals").json() == []
    assert client.get(f"/api/deals/{deal['id']}").status_code == 404


def test_unknown_listing_404s(client):
    assert client.post("/api/deals", json={"listing_id": "nope"}).status_code == 404
