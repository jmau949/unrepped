"""`GET /api/guide/closing` — docs/14 served as the pack's closing guide."""

from pathlib import Path

from fastapi.testclient import TestClient

from hb import geography
from hb.api.guide import split_sections
from hb.config import settings
from hb.main import app
from hb.packs.ca import GUIDE

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_IDS = ["lost", "forms", "lock_down", "clocks", "disclosures", "inspections",
                "city_rules", "loan", "insurance", "repairs", "removal", "final_week",
                "cash", "post_close"]


def test_closing_guide_splits_the_playbook_into_linkable_sections():
    r = TestClient(app).get("/api/guide/closing")
    assert r.status_code == 200
    body = r.json()
    assert body["pack"] == "ca" and body["doc"] == "docs/14-closing-playbook.md"
    assert body["title"].startswith("14 — Closing Playbook")
    assert "not legal advice" in body["intro_md"].lower() or body["intro_md"]
    assert [s["id"] for s in body["sections"]] == EXPECTED_IDS  # §15 (app model) hidden
    assert [s["n"] for s in body["sections"]] == list(range(1, 15))
    assert all(s["title"] and s["markdown"] for s in body["sections"])
    # every deep link the Closing page offers resolves to a served section
    ids = {s["id"] for s in body["sections"]}
    for links in body["phase_map"].values():
        assert {link["id"] for link in links} <= ids
    assert "lock_down" in body["phase_map"]


def test_split_sections_keeps_heading_text_out_of_the_body():
    text = ("# 14 — Title\n\nintro line\n\n## 1. First\n\nbody one\n\n### 1.1 sub\n\nmore\n\n"
            "## 2. Second\n\nbody two\n\n## 15. How the app models this\n\ndev notes\n")
    title, intro, sections = split_sections(text, GUIDE)
    assert title == "14 — Title" and intro == "intro line"
    assert [s["id"] for s in sections] == ["lost", "forms"]
    assert sections[0]["markdown"] == "body one\n\n### 1.1 sub\n\nmore"
    assert sections[1]["markdown"] == "body two"


def test_no_guide_for_a_pack_without_one():
    settings._geo = geography.load(FIXTURES / "geography_tx_minimal.toml", "x", FIXTURES)
    r = TestClient(app).get("/api/guide/closing")
    assert r.status_code == 404
    assert "us" in r.json()["detail"]
