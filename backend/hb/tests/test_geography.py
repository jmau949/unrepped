"""hb/geography — the TOML-backed target geography (docs/02 §3)."""

from pathlib import Path

import pytest

from hb import geography

FIXTURES = Path(__file__).parent / "fixtures"

MINIMAL = """
schema = 1
name = "T"
state = "TX"
state_fips = "48"
timezone = "America/Chicago"
[map]
center = [-97.7, 30.3]
[price_band]
min = 1
max = 2
[[counties]]
name = "Travis County"
fips = "453"
effective_tax_rate = 0.019
[[cities]]
name = "Austin"
county = "Travis County"
zips = ["78701"]
"""


def _parse(toml: str):
    return geography.parse(toml, "test")


def test_packaged_example_loads_and_derives_views():
    geo = geography.load_packaged("sf_peninsula")
    assert "sf_peninsula" in geography.packaged_names()
    assert geo.zip_to_city["94087"] == "Sunnyvale"
    assert geo.city_to_county["Sunnyvale"] == "Santa Clara County"
    assert geo.sibling_zips("94087") == ["94085", "94086", "94087", "94089"]
    assert geo.sibling_zips("00000") == ["00000"]  # unknown ZIP stands alone
    assert geo.zips_in_city("Nowhere") == []
    assert geo.county_names == ["San Mateo County", "Santa Clara County"]
    assert geo.dfirm_ids == ["06081C", "06085C"]
    assert geo.cities_with_flag("sewer_lateral_pos") == ["San Mateo", "Burlingame", "Millbrae", "San Bruno"]
    assert geo.pack_key == "ca"
    assert geo.market.case_shiller_fred_id == "SFXRSA"


def test_tax_rate_city_override_then_county_then_none():
    geo = geography.load(FIXTURES / "geography_tx_minimal.toml", "ignored", FIXTURES)
    assert geo.tax_rate_for("Austin") == 0.0190         # county rate
    assert geo.tax_rate_for("Pflugerville") == 0.0215   # city override
    assert geo.tax_rate_for("austin ") == 0.0190        # case/space tolerant
    assert geo.tax_rate_for("Elsewhere") is None
    assert geo.tax_rate_for(None) is None
    assert geo.pack_key == "tx"  # no pack set: lower-cased state


def test_minimal_file_fills_optional_sections():
    geo = _parse(MINIMAL)
    assert geo.market.case_shiller_fred_id is None and geo.market.hazard_bbox is None
    assert geo.costs.year is None
    assert geo.map.zoom == 9
    assert geo.county_of("Austin").fips == "453"


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ('zips = ["78701"]', 'zips = ["7870"]'),
        ('county = "Travis County"\nzips', 'county = "Nowhere County"\nzips'),
        ('timezone = "America/Chicago"', 'timezone = "Mars/Olympus"'),
        ('state = "TX"', 'state = "Texas"'),
        ("max = 2", "max = 1"),
    ],
    ids=["zip5", "unknown-county", "timezone", "state-code", "price-band"],
)
def test_validation_errors_name_the_problem(bad, message):
    with pytest.raises(ValueError, match="invalid geography"):
        _parse(MINIMAL.replace(bad, message))


def test_duplicate_zip_across_cities_is_rejected():
    dup = MINIMAL + '\n[[cities]]\nname = "Round Rock"\ncounty = "Travis County"\nzips = ["78701"]\n'
    with pytest.raises(ValueError, match="78701"):
        _parse(dup)


def test_bad_toml_is_reported_with_its_source():
    with pytest.raises(ValueError, match="test: not valid TOML"):
        _parse("this is = not = toml")


def test_unknown_packaged_name_lists_known_ones():
    with pytest.raises(FileNotFoundError, match="sf_peninsula"):
        geography.load_packaged("atlantis")
