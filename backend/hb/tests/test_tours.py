import pytest
from fastapi.testclient import TestClient

from hb import packs, tour_spec
from hb.db.models import (
    BuyerProfile,
    CmaComp,
    CmaRun,
    Listing,
    Property,
    Sale,
)


@pytest.fixture
def client(engine, monkeypatch):
    import hb.api.contacts as contacts_module
    import hb.api.listings as listings_module
    import hb.api.tours as tours_module
    import hb.db.engine as engine_module

    monkeypatch.setattr(engine_module, "_engine", engine)
    for mod in (listings_module, tours_module, contacts_module):
        monkeypatch.setattr(mod, "make_session", lambda: engine_module.make_session(engine))

    from hb.main import app

    return TestClient(app)


@pytest.fixture
def home(session):
    """One pre-1980 raised-foundation home — the case the checklist cares about."""
    session.add(BuyerProfile(id="default", cash_available=800_000, down_payment=600_000,
                             rate_assumption=6.5))
    prop = Property(address_norm="1204 OAK AVE", zip="94070", city="San Carlos",
                    beds=3, baths=2.0, sqft=1600, lot_sqft=6000, year_built=1955,
                    lat=37.5, lon=-122.26)
    session.add(prop)
    session.flush()
    listing = Listing(property_id=prop.id, source="realtor", source_listing_id="T1",
                      status="active", list_price=2_290_000,
                      original_list_price=2_450_000, list_date="2026-07-01")
    session.add(listing)
    session.commit()
    return {"property_id": prop.id, "listing_id": listing.id}


# --- spec ---


def test_spec_prunes_by_year_built():
    old = {i["key"] for s in tour_spec.spec_for({"year_built": 1955})["sections"]
           for i in s["items"]}
    new = {i["key"] for s in tour_spec.spec_for({"year_built": 2015})["sections"]
           for i in s["items"]}
    # a 1955 home gets the age-specific items
    assert {"retrofit_visible", "wiring_vintage", "sewer_lateral_cert"} <= old
    # a 2015 home is not asked about cripple walls or clay laterals
    assert not ({"retrofit_visible", "wiring_vintage", "sewer_lateral_cert"} & new)
    # everything else is still asked
    assert "panel_brand" in new and "grading_slopes_away" in new


def test_spec_keeps_age_items_when_year_unknown():
    keys = {i["key"] for s in tour_spec.spec_for({})["sections"] for i in s["items"]}
    assert "retrofit_visible" in keys  # unknown year means ask, not skip


def test_context_notes_call_out_sqft_mismatch():
    notes = tour_spec.spec_for({"year_built": 1955, "sqft_mismatch": True})["context_notes"]
    assert any("permitted" in n for n in notes)
    assert any("1980" in n for n in notes)


def test_evaluate_flags_and_prices_defects():
    result = tour_spec.evaluate({
        "panel_brand": "Federal Pacific",
        "supply_pipe": "galvanized steel",
        "water_heater_year": 2004,
    }, year=2026)
    flagged = {f["key"] for f in result["flags"]}
    assert flagged == {"panel_brand", "supply_pipe", "water_heater_year"}
    bands = {b["key"] for b in result["costs"]["items"]}
    assert bands == {"panel_replace", "repipe", "water_heater"}
    assert result["costs"]["low"] == 4_000 + 10_000 + 2_000


def test_evaluate_dedupes_cost_bands():
    """Two flagged items pointing at one trade must not bill twice."""
    both = tour_spec.evaluate({"panel_brand": "Zinsco", "panel_fuses": True}, year=2026)
    assert len(both["flags"]) == 2
    assert [b["key"] for b in both["costs"]["items"]] == ["panel_replace"]
    assert both["costs"]["low"] == packs.current().tour.cost_bands.bands["panel_replace"].low


def test_evaluate_does_not_flag_clean_answers():
    result = tour_spec.evaluate({"panel_brand": "Square D", "supply_pipe": "copper"},
                                year=2026)
    assert result["flags"] == []
    assert result["costs"]["low"] == 0


def test_unchecked_bool_is_unanswered_not_negative():
    result = tour_spec.evaluate({"ceiling_stains": False}, year=2026)
    assert result["flags"] == []
    assert any(g["key"] == "ceiling_stains" for g in result["unanswered"])


def test_water_heater_recent_year_is_not_flagged():
    assert tour_spec.evaluate({"water_heater_year": 2024}, year=2026)["flags"] == []


# --- checklist endpoint ---


def test_checklist_endpoint_is_tailored(client, home):
    resp = client.get("/api/tours/checklist", params={"listing_id": home["listing_id"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["property_id"] == home["property_id"]
    assert body["facts"]["year_built"] == 1955
    keys = {i["key"] for s in body["sections"] for i in s["items"]}
    assert "retrofit_visible" in keys
    assert body["photo_shot_list"]
    assert body["agent_questions"]


def test_checklist_requires_an_id(client, home):
    assert client.get("/api/tours/checklist").status_code == 422


# --- CRUD ---


def test_create_tour_is_idempotent_per_day(client, home):
    body = {"listing_id": home["listing_id"], "toured_on": "2026-08-14"}
    first = client.post("/api/tours", json=body).json()
    second = client.post("/api/tours", json=body).json()
    assert first["id"] == second["id"]
    assert len(client.get("/api/tours", params={"listing_id": home["listing_id"]}).json()) == 1


def test_patch_merges_checklist_and_returns_rollup(client, home):
    tour = client.post("/api/tours", json={"listing_id": home["listing_id"],
                                           "toured_on": "2026-08-14"}).json()
    client.patch(f"/api/tours/{tour['id']}", json={"checklist": {"panel_brand": "Zinsco"}})
    resp = client.patch(f"/api/tours/{tour['id']}",
                        json={"checklist": {"supply_pipe": "copper"}, "gut_score": 4})
    body = resp.json()
    # the first PATCH's value survives the second — JSON columns merge
    assert body["checklist"] == {"panel_brand": "Zinsco", "supply_pipe": "copper"}
    assert body["gut_score"] == 4
    assert {f["key"] for f in body["flags"]} == {"panel_brand"}
    assert body["costs"]["low"] == 4_000


def test_repair_override_wins_over_rollup(client, home):
    tour = client.post("/api/tours", json={"listing_id": home["listing_id"],
                                           "toured_on": "2026-08-14"}).json()
    client.patch(f"/api/tours/{tour['id']}", json={"checklist": {"panel_brand": "Zinsco"}})
    body = client.patch(f"/api/tours/{tour['id']}",
                        json={"repair_low": 9_000, "repair_high": 11_000}).json()
    assert body["costs"]["low"] == 9_000
    assert body["costs"]["overridden"] is True


def test_patch_validates_enums(client, home):
    tour = client.post("/api/tours", json={"listing_id": home["listing_id"],
                                           "toured_on": "2026-08-14"}).json()
    assert client.patch(f"/api/tours/{tour['id']}", json={"verdict": "nope"}).status_code == 422
    assert client.patch(f"/api/tours/{tour['id']}", json={"gut_score": 9}).status_code == 422
    assert client.patch(f"/api/tours/{tour['id']}", json={"kind": "seance"}).status_code == 422


def test_delete_tour(client, home):
    tour = client.post("/api/tours", json={"listing_id": home["listing_id"],
                                           "toured_on": "2026-08-14"}).json()
    assert client.delete(f"/api/tours/{tour['id']}").status_code == 200
    assert client.get("/api/tours", params={"listing_id": home["listing_id"]}).json() == []


# --- import ---


def _payload(home, **over):
    tour = {"property_id": home["property_id"], "listing_id": home["listing_id"],
            "toured_on": "2026-08-14", "kind": "open_house",
            "checklist": {"panel_brand": "Federal Pacific", "roof_age_est": 25},
            "agent_answers": {"3": "four packets out"},
            "gut_score": 4, "verdict": "maybe", "notes": "good bones, bad panel"}
    tour.update(over)
    return {"tours": [tour]}


def test_import_creates_then_is_a_noop(client, home):
    first = client.post("/api/tours/import", json=_payload(home)).json()
    assert (first["created"], first["updated"]) == (1, 0)

    # re-importing the same file must change nothing — this is the whole point
    second = client.post("/api/tours/import", json=_payload(home)).json()
    assert (second["created"], second["updated"], second["unchanged"]) == (0, 0, 1)
    assert second["conflicts"] == []

    tours = client.get("/api/tours", params={"listing_id": home["listing_id"]}).json()
    assert len(tours) == 1
    assert tours[0]["source"] == "offline_kit"
    assert tours[0]["gut_score"] == 4
    assert {f["key"] for f in tours[0]["flags"]} == {"panel_brand", "roof_age_est"}


def test_import_fills_gaps_without_clobbering_edits(client, home):
    client.post("/api/tours/import", json=_payload(home))
    tour = client.get("/api/tours", params={"listing_id": home["listing_id"]}).json()[0]
    # the user then corrects the panel in the app and adds a new observation
    client.patch(f"/api/tours/{tour['id']}",
                 json={"checklist": {"panel_brand": "Square D"}, "notes": "edited in app"})

    # importing the stale export again must not revert either edit
    result = client.post("/api/tours/import", json=_payload(home)).json()
    after = client.get("/api/tours", params={"listing_id": home["listing_id"]}).json()[0]
    assert after["checklist"]["panel_brand"] == "Square D"
    assert after["notes"] == "edited in app"
    fields = {c["field"] for c in result["conflicts"]}
    assert "checklist.panel_brand" in fields and "notes" in fields


def test_import_adds_new_keys_to_an_existing_tour(client, home):
    client.post("/api/tours/import", json=_payload(home))
    grown = _payload(home)
    grown["tours"][0]["checklist"]["supply_pipe"] = "galvanized steel"
    result = client.post("/api/tours/import", json=grown).json()
    assert result["updated"] == 1
    after = client.get("/api/tours", params={"listing_id": home["listing_id"]}).json()[0]
    assert after["checklist"]["supply_pipe"] == "galvanized steel"
    assert result["conflicts"] == []


def test_import_reports_unknown_property(client, home):
    result = client.post("/api/tours/import",
                         json=_payload(home, property_id="nope")).json()
    assert result["created"] == 0
    assert result["errors"][0]["error"] == "unknown property"


# --- field-data seed + Field save ---


def test_field_data_carries_spec_and_existing_tour(client, home):
    # a tour already on file so the seed's `existing` is populated
    client.post("/api/tours/import", json=_payload(home))
    body = client.get("/api/tours/field-data",
                      params={"listing_ids": home["listing_id"]}).json()
    assert body["generated_at"]
    assert len(body["homes"]) == 1
    h = body["homes"][0]
    assert h["listing_id"] == home["listing_id"]
    assert "1204" in h["address"]
    # the age-pruned spec travels with the seed so the phone raises flags offline
    keys = {i["key"] for s in h["spec"]["sections"] for i in s["items"]}
    assert "retrofit_visible" in keys                  # 1955 home keeps age items
    assert "flag_when" in h["spec"]["sections"][0]["items"][0]
    # and the tour already recorded comes along, rolled up
    assert h["existing"] is not None
    assert {f["key"] for f in h["existing"]["flags"]} == {"panel_brand", "roof_age_est"}


def test_field_data_404s_on_unknown_listing(client, home):
    assert client.get("/api/tours/field-data",
                      params={"listing_ids": "nope"}).status_code == 404


def test_field_data_rejects_empty_ids(client, home):
    assert client.get("/api/tours/field-data",
                      params={"listing_ids": " "}).status_code == 422


def test_sync_post_then_patch_is_idempotent(client, home):
    """The Field page's save: POST to get-or-create the tour, then PATCH the
    accumulated local state. Replaying the whole thing must converge to one tour,
    not duplicate."""
    def sync():
        tour = client.post("/api/tours",
                           json={"listing_id": home["listing_id"],
                                 "toured_on": "2026-08-14"}).json()
        return client.patch(f"/api/tours/{tour['id']}", json={
            "checklist": {"panel_brand": "Zinsco", "supply_pipe": "copper"},
            "agent_answers": {"3": "four packets"},
            "gut_score": 4, "verdict": "maybe", "notes": "from the field",
        }).json()

    first, second = sync(), sync()
    assert first["id"] == second["id"]                 # POST is idempotent per day
    rows = client.get("/api/tours", params={"listing_id": home["listing_id"]}).json()
    assert len(rows) == 1                               # no duplicate tour
    assert second["checklist"] == {"panel_brand": "Zinsco", "supply_pipe": "copper"}
    assert second["gut_score"] == 4 and second["verdict"] == "maybe"
    assert second["notes"] == "from the field"


def test_sync_patch_overwrites_a_scalar_the_import_would_refuse(client, home):
    """The behavioural difference the sync model depends on: the phone is the
    authority for what it just observed, so its PATCH overwrites; the recovery
    import keeps the existing value and reports a conflict instead."""
    tour = client.post("/api/tours", json={"listing_id": home["listing_id"],
                                           "toured_on": "2026-08-14"}).json()
    client.patch(f"/api/tours/{tour['id']}", json={"gut_score": 2, "verdict": "pass"})

    # import path: refuses to overwrite, reports a conflict
    imported = client.post("/api/tours/import",
                           json=_payload(home, gut_score=5, verdict="offer")).json()
    kept = client.get("/api/tours", params={"listing_id": home["listing_id"]}).json()[0]
    assert kept["gut_score"] == 2                       # import kept the existing value
    assert any(c["field"] == "gut_score" for c in imported["conflicts"])

    # sync PATCH: overwrites outright, no conflict machinery
    synced = client.patch(f"/api/tours/{tour['id']}",
                          json={"gut_score": 5, "verdict": "offer"}).json()
    assert synced["gut_score"] == 5 and synced["verdict"] == "offer"


# --- brief ---


def test_brief_covers_every_section(client, home):
    md = client.get(f"/api/listings/{home['listing_id']}/brief").text
    for heading in ("## 1. Subject", "## 2. Market position", "## 3. Valuation",
                    "## 4. Neighborhood", "## 5. Money",
                    "## 6. What I observed on the walk-through",
                    "## 7. Deferred maintenance observed",
                    "## 8. What I could NOT verify", "## 9. What I am attaching",
                    "## 10. What I want from you"):
        assert heading in md
    assert "1204 Oak Ave" in md
    assert "pest report" in md


def test_brief_names_the_listing_side(client, home, session):
    listing = session.get(Listing, home["listing_id"])
    listing.raw = {
        "agent_name": "Jane Lister", "agent_email": "jlister@example.com",
        "agent_phones": [{"number": "6505550123", "type": "Mobile", "primary": True}],
        "office_name": "Example Realty Group",
    }
    session.commit()
    client.post(f"/api/listings/{home['listing_id']}/contacts",
                json={"kind": "owner", "name": "J. Seller", "phone": "650-555-0100"})

    md = client.get(f"/api/listings/{home['listing_id']}/brief").text
    assert "**Listing side** (represents the seller, not me): Jane Lister · " \
           "Example Realty Group · 650-555-0123 · jlister@example.com" in md
    assert "**Contact (owner)**: J. Seller · 650-555-0100" in md

    listing.raw = {}
    session.commit()
    assert "Listing side" not in client.get(f"/api/listings/{home['listing_id']}/brief").text


def test_brief_without_a_tour_says_so(client, home):
    md = client.get(f"/api/listings/{home['listing_id']}/brief").text
    assert "No tour recorded" in md
    assert "the home has not been walked" in md


def test_brief_lists_observations_costs_and_gaps(client, home):
    client.post("/api/tours/import", json=_payload(home))
    md = client.get(f"/api/listings/{home['listing_id']}/brief").text

    # observed
    assert "Federal Pacific" in md
    assert "four packets out" in md
    assert "good bones, bad panel" in md
    # priced
    assert "Electrical panel replacement" in md
    assert "Total deferred maintenance" in md
    # and, most importantly, the gaps
    gaps = md.split("## 8. What I could NOT verify")[1]
    assert "Supply piping" in gaps          # never answered
    assert "Panel brand" not in gaps        # answered, so not a gap
    assert "Is there an offer date?" in gaps  # unasked agent question


def test_brief_renders_the_comps_table(client, home, session):
    """The comps branch only runs when a CMA exists — it is the part of the brief
    a bare fixture never reaches."""
    comp_prop = Property(address_norm="1400 ELM ST", zip="94070", city="San Carlos",
                         beds=3, baths=2.0, sqft=1550, year_built=1957)
    session.add(comp_prop)
    session.flush()
    sale = Sale(property_id=comp_prop.id, sale_date="2026-05-02", sale_price=2_350_000,
                source="realtor")
    run = CmaRun(property_id=home["property_id"], estimate=2_400_000, low=2_300_000,
                 high=2_500_000, confidence="medium", params={})
    session.add_all([sale, run])
    session.flush()
    session.add(CmaComp(cma_run_id=run.id, sale_id=sale.id, similarity_score=0.87,
                        included=True, adjusted_price=2_412_000,
                        adjustments={"time": 41_000, "sqft": 21_000, "baths": 0}))
    session.commit()

    md = client.get(f"/api/listings/{home['listing_id']}/brief").text
    assert "| Comp | Sold | Sale price | Adjustments | Adjusted | Similarity |" in md
    assert "1400 ELM ST" in md
    assert "0.87" in md
    assert "time +41,000" in md
    assert "baths" not in md.split("1400 ELM ST")[1].split("\n")[0]  # zero adjustments omitted
    assert "$2,400,000" in md


def test_brief_marks_workbench_overrides(client, home, session):
    """A comp with hand-overridden line items stores them under ``_overrides``
    (engine/cma.py); the table must skip that key and star the overridden items."""
    comp_prop = Property(address_norm="1402 ELM ST", zip="94070", city="San Carlos",
                         beds=4, baths=3.0, sqft=1900, year_built=1950)
    session.add(comp_prop)
    session.flush()
    sale = Sale(property_id=comp_prop.id, sale_date="2026-06-10", sale_price=2_600_000,
                source="realtor")
    run = CmaRun(property_id=home["property_id"], estimate=2_700_000, low=2_600_000,
                 high=2_800_000, confidence="medium", params={})
    session.add_all([sale, run])
    session.flush()
    session.add(CmaComp(cma_run_id=run.id, sale_id=sale.id, similarity_score=0.41,
                        included=True, adjusted_price=2_690_000,
                        adjustments={"time": 30_000, "sqft": 25_000, "baths": 15_000,
                                     "lot": 20_000, "condition": 0,
                                     "_overrides": {"baths": 15_000, "lot": 20_000}}))
    session.commit()

    resp = client.get(f"/api/listings/{home['listing_id']}/brief")
    assert resp.status_code == 200
    row = resp.text.split("1402 ELM ST")[1].split("\n")[0]
    assert "time +30,000" in row and "sqft +25,000" in row
    assert "baths +15,000*" in row and "lot +20,000*" in row
    assert "_overrides" not in resp.text
    assert "A trailing * marks a line item overridden by hand" in resp.text


def test_brief_404s_on_unknown_listing(client, home):
    assert client.get("/api/listings/nope/brief").status_code == 404
