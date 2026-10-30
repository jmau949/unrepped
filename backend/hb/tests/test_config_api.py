"""`GET /api/config` — the geography + pack the UI configures itself from."""

from pathlib import Path

from fastapi.testclient import TestClient

from hb import geography
from hb.config import settings
from hb.main import app

FIXTURES = Path(__file__).parent / "fixtures"


def test_config_reflects_the_packaged_geography_and_its_pack():
    body = TestClient(app).get("/api/config").json()

    geo = body["geography"]
    assert geo["name"] == "SF Peninsula" and geo["state"] == "CA"
    assert [c["name"] for c in geo["cities"]][:3] == ["Santa Clara", "Sunnyvale", "Mountain View"]
    assert len(geo["cities"]) == 12 and len(geo["zips"]) == 27
    assert geo["map"] == {"center": [-122.2, 37.55], "zoom": 9}
    assert geo["price_band"] == {"min": 2_000_000, "max": 3_000_000}
    assert {c["name"] for c in geo["counties"]} == {"San Mateo County", "Santa Clara County"}
    assert all(c["assessor_url"].startswith("https://") for c in geo["counties"])
    san_mateo = next(c for c in geo["cities"] if c["name"] == "San Mateo")
    assert san_mateo["flags"] == ["sewer_lateral_pos"]

    pack = body["pack"]
    assert pack["key"] == "ca"
    assert pack["contingency"] == {"investigation_days": 17, "appraisal_days": 17,
                                   "loan_days": 21, "emd_business_days": 3,
                                   "label": "C.A.R. RPA defaults"}
    assert pack["costs"] == {"year": 2026, "label": "SF-Peninsula contractor ranges"}
    assert [h["key"] for h in pack["hazards"]] == ["fema_flood", "calfire_fhsz",
                                                   "liquefaction", "fault_zone"]
    assert all(h["label"] and h["tone"] for h in pack["hazards"])
    assert [r["key"] for r in pack["rating_sources"]] == ["caaspp", "schooldigger"]
    assert [f["key"] for f in pack["tracker_checklist"]] == [
        "packet_received", "tds_spq_read", "pest_section1_total", "nhd_read",
        "hoa_docs", "insurance_quoted",
    ]
    assert pack["affordability"]["earthquake_monthly_default"] == 150
    assert pack["guide"] == {"available": True}


def test_config_for_a_geography_without_a_pack():
    settings._geo = geography.load(FIXTURES / "geography_tx_minimal.toml", "x", FIXTURES)
    body = TestClient(app).get("/api/config").json()
    assert body["geography"]["state"] == "TX"
    assert [c["name"] for c in body["geography"]["cities"]] == ["Austin", "Pflugerville"]
    pack = body["pack"]
    assert pack["key"] == "us"
    assert [h["key"] for h in pack["hazards"]] == ["fema_flood"]
    assert pack["guide"] == {"available": False}
