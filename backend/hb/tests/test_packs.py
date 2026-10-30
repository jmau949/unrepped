"""State packs (hb/packs): every registered pack is well-formed, the `us` base
carries no California wording, state packs stay key-compatible with the base,
and the engines follow whichever pack the geography selects."""

import re
from pathlib import Path

import pytest

from hb import closing_spec, geography, packs, prep_spec, tour_spec
from hb.config import settings
from hb.db.models import School, SchoolRatingSnapshot
from hb.packs import REGISTRY, validate
from hb.packs.ca import closing as ca_closing
from hb.packs.types import Pack
from hb.schools_match import _attach_ratings

FIXTURES = Path(__file__).parent / "fixtures"


def _use_tx() -> None:
    settings._geo = geography.load(FIXTURES / "geography_tx_minimal.toml", "x", FIXTURES)


def _texts(pack: Pack):
    """Every human-readable string in a pack."""
    for t in pack.closing.tasks:
        yield from (t.label, t.why, t.how)
    for p in (*pack.closing.phases, *pack.prep.phases):
        yield from (p.title, p.blurb)
    for f in pack.closing.forms.values():
        yield from (f.name, f.what)
    for b in (*pack.closing.costs.bands.values(), *pack.tour.cost_bands.bands.values()):
        yield b.label
    yield pack.closing.costs.label
    yield pack.tour.cost_bands.label
    yield pack.closing.contingency.label
    for s in pack.tour.sections:
        yield from (s.title, s.blurb)
        for i in s.items:
            yield from (i.label, i.hint, i.photo, *i.choices)
    yield from pack.tour.agent_questions
    yield from (n.text for n in pack.tour.age_notes)
    for t in pack.prep.tasks:
        yield from (t.label, t.why, t.how)
    yield from pack.content.disclosure_packet
    yield pack.content.brief_tax_note
    yield pack.content.attorney_phrase
    yield from (f.label for f in pack.content.tracker_checklist)
    yield pack.affordability.optional_insurance_label
    yield pack.affordability.supplemental_tax_note
    yield from (h.label for h in pack.hazards)
    yield from (r.label + " " + r.blurb for r in pack.rating_sources)


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_every_pack_is_internally_consistent(key):
    assert validate(REGISTRY[key]) == []


CALIFORNIA = re.compile(
    r"C\.A\.R\.|California|Peninsula|Bay Area|Prop 13|Caltrain|CAASPP|Megan"
    r"|PG&E|\bRPA\b|\bTDS\b|\bSPQ\b|\bNHD\b|\bCEA\b|\bBNA\b|\bNBP\b|\bCR\b|\bRR\b|\bVP\b"
    r"|\bETA\b|Section 1|supplemental tax|meganslaw|CAL FIRE|liquefaction"
)


def test_us_base_pack_has_no_california_wording():
    hits = [t for t in _texts(REGISTRY["us"]) if CALIFORNIA.search(t)]
    assert hits == []


def test_us_base_pack_is_us_generic_in_structure():
    us = REGISTRY["us"]
    assert us.guide is None
    assert [h.key for h in us.hazards] == ["fema_flood"]
    assert us.rating_sources[0].key == "schooldigger"
    assert set(us.closing.forms) == {"PA", "FLD", "LE", "CD"}
    # the federal forms + the generic contract stand in for the state forms
    assert {t.form for t in us.closing.tasks if t.form} <= set(us.closing.forms)


def test_ca_pack_shares_task_keys_with_the_base():
    """Checklist JSON is keyed on task keys, so a key must mean the same task in
    every pack: CA may re-word a base task or add its own, never rename one."""
    us_keys = {t.key for t in REGISTRY["us"].closing.tasks}
    ca_keys = {t.key for t in REGISTRY["ca"].closing.tasks}
    extra = {t.key for t in ca_closing.EXTRA}
    assert ca_keys - us_keys == extra
    assert us_keys - ca_keys == set(ca_closing.REPLACED)
    assert set(ca_closing.OVERRIDES) <= us_keys & ca_keys
    # tour and prep: CA only adds items / re-words tasks
    us_items = {i.key for s in REGISTRY["us"].tour.sections for i in s.items}
    ca_items = {i.key for s in REGISTRY["ca"].tour.sections for i in s.items}
    assert us_items <= ca_items
    assert ca_items - us_items == {"retrofit_visible", "water_heater_strapped"}
    assert {t.key for t in REGISTRY["us"].prep.tasks} == {t.key for t in REGISTRY["ca"].prep.tasks}


def test_ca_pack_carries_the_california_specifics():
    ca = REGISTRY["ca"]
    c = ca.closing.contingency
    assert (c.investigation_days, c.appraisal_days, c.loan_days, c.emd_business_days) == (17, 17, 21, 3)
    keys = {t.key for t in ca.closing.tasks}
    assert {"tds_read", "spq_read", "nhd_read", "city_pos_report", "know_the_nbp",
            "supplemental_tax_reserve", "homeowners_exemption"} <= keys
    assert {t.key: t.form for t in ca.closing.tasks}["remove_loan"] == "CR"
    assert [h.key for h in ca.hazards] == ["fema_flood", "calfire_fhsz", "liquefaction", "fault_zone"]
    assert ca.rating_sources[0].key == "caaspp"
    assert ca.guide is not None and ca.guide.doc == "docs/14-closing-playbook.md"


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_no_task_hides_behind_a_bare_acronym(key):
    """If a label uses an initialism, why/how has to spell it out on the same card
    (or the task names a form, which ships its plain-English name)."""
    jargon = ["AD", "BNA", "TDS", "SPQ", "NHD", "CR", "NBP", "RR", "VP", "ETA", "RPA",
              "EMD", "COE", "CD", "LE", "WDO", "DIC", "CEA", "PA", "FLD", "TRID"]
    for task in REGISTRY[key].closing.tasks:
        body = f"{task.why} {task.how}"
        for word in task.label.replace("(", " ").replace(")", " ").replace(",", " ").split():
            if word.strip(".:—") in jargon:
                assert word.strip(".:—") in body or task.form, (
                    f"{key}/{task.key}: label uses '{word}' with no explanation in why/how"
                )


def test_packaged_geography_selects_ca_with_its_cost_label():
    pack = packs.current()
    assert pack.key == "ca"
    # the geography's [costs] table re-labels both cost books
    assert pack.closing.costs.label == "SF-Peninsula contractor ranges"
    assert pack.tour.cost_bands.label == "SF-Peninsula contractor ranges"
    assert pack.closing.costs.year == 2026
    # bands themselves are the pack's unless overridden
    assert pack.tour.cost_bands.bands["panel_replace"].low == 4_000


def test_geography_can_override_individual_cost_bands():
    data = settings.geo.model_dump(by_alias=True)
    data["costs"] = {"year": 2027, "label": "my quotes", "tour": {"panel_replace": [1, 2]},
                     "closing": {"attorney": [10, 20]}}
    settings._geo = geography.Geography.model_validate(data)
    pack = packs.current()
    assert (pack.tour.cost_bands.year, pack.tour.cost_bands.label) == (2027, "my quotes")
    assert (pack.tour.cost_bands.bands["panel_replace"].low,
            pack.tour.cost_bands.bands["panel_replace"].high) == (1, 2)
    assert pack.closing.costs.bands["attorney"].high == 20
    assert pack.closing.costs.bands["attorney"].label == "Real estate attorney, flat fee"


def test_geography_without_a_pack_falls_back_to_us():
    _use_tx()
    pack = packs.current()
    assert pack.key == "us"
    assert pack.closing.costs.label == "national contractor ranges (rough)"


def test_engines_follow_the_current_pack():
    deal = {"accepted_on": "2026-09-14", "close_of_escrow_on": "2026-10-14",
            "investigation_days": 10, "appraisal_days": 21, "loan_days": 21}
    ca_keys = {t["key"] for t in closing_spec.schedule(deal, {"city": "Burlingame"})}
    assert {"tds_read", "city_pos_report", "know_the_nbp"} <= ca_keys
    assert "seller_disclosures_read" not in ca_keys

    _use_tx()
    us_keys = {t["key"] for t in closing_spec.schedule(deal, {"city": "Austin"})}
    assert {"seller_disclosures_read", "local_pos_requirements", "reassessment_check"} <= us_keys
    assert not ({"tds_read", "city_pos_report"} & us_keys)
    assert closing_spec.spec_for(deal)["contingency"]["investigation_days"] == 10

    items = {i["key"] for s in tour_spec.spec_for({"year_built": 1950})["sections"]
             for i in s["items"]}
    assert "retrofit_visible" not in items and "panel_brand" in items
    notes = tour_spec.spec_for({"year_built": 1950})["context_notes"]
    assert not any("cripple" in n for n in notes)
    assert any("Lead-based paint" in n for n in notes)

    prep = prep_spec.spec_for()
    how = {t["key"]: t["how"] for p in prep["phases"] for t in p["tasks"]}
    assert "Prop 13" not in " ".join(how.values())


def test_rating_order_follows_the_pack(session):
    school = School(nces_id="X1", name="Any", level="elementary", lat=1, lon=1, zip="94087")
    session.add(school)
    session.flush()
    session.add_all([
        SchoolRatingSnapshot(school_id=school.id, source="schooldigger", rating_10=9.0, label="a"),
        SchoolRatingSnapshot(school_id=school.id, source="caaspp", rating_10=7.0, label="b"),
    ])
    session.commit()
    rows = _attach_ratings(session, [{"_school_id": school.id}])
    assert [r["source"] for r in rows[0]["ratings"]] == ["caaspp", "schooldigger"]  # ca pack

    _use_tx()
    rows = _attach_ratings(session, [{"_school_id": school.id}])
    assert [r["source"] for r in rows[0]["ratings"]] == ["schooldigger", "caaspp"]  # us pack
