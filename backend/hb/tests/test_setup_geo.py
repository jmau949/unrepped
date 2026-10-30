"""hb/setup_geo + `hb setup` — geography.toml from Census reference files
(docs/packs/README.md §1). The fixtures under fixtures/census/ are tiny
synthetic files in the real formats; nothing here touches the network."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hb import config, geography, setup_geo
from hb.cli import app

CENSUS = Path(__file__).parent / "fixtures" / "census"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _fixture_census(monkeypatch):
    def fetch(key: str) -> Path:
        return next(p for p in CENSUS.iterdir() if p.name.startswith(f"{key}-")
                    or p.name == f"{key}.txt")

    monkeypatch.setattr(setup_geo, "fetch_reference", fetch)
    monkeypatch.setattr(setup_geo, "needs_download", lambda: False)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A scratch repo root: geography.toml and .env land here, not in the checkout."""
    monkeypatch.setattr(config, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(config.settings, "geography_file", None)
    monkeypatch.setattr(config.settings, "fred_api_key", "")
    (tmp_path / ".env.example").write_text("DATA_DIR=./data\nFRED_API_KEY=\nSAVE_PHOTOS=true\n",
                                           encoding="utf-8")
    return tmp_path


def tx():
    return setup_geo.load_reference(setup_geo.states()["TX"])


def places(ref, *names):
    return [setup_geo.match_city(ref, n).candidates[0] for n in names]


def test_every_state_has_a_valid_fips_and_time_zones():
    states = setup_geo.states()
    assert len(states) == 51  # 50 states + DC
    labels = setup_geo.zone_labels()
    for st in states.values():
        assert len(st.fips) == 2 and st.fips.isdigit()
        assert st.zones and all(z in labels for z in st.zones)
    assert len({st.fips for st in states.values()}) == 51


def test_reads_both_gazetteer_formats_and_strips_the_legal_suffix():
    ref = tx()
    assert {p.name for p in ref.places} == {"Oak Hill", "Cedar Grove", "Tiny", "St. Cedar"}
    assert "90001" not in ref.zcta_points  # another state's ZIP
    assert ref.zcta_points["78001"] == (30.0, -97.0)  # tab-delimited, padded file


def test_an_incorporated_city_comes_before_a_same_named_cdp():
    m = setup_geo.match_city(tx(), "oak hill")
    assert [p.full for p in m.candidates] == ["Oak Hill city", "Oak Hill CDP"]
    assert m.obvious.full == "Oak Hill city"  # no question to ask
    assert setup_geo.describe(tx(), m.candidates[1]) == "Oak Hill CDP, Bravo County"


def test_a_misspelling_gets_suggestions_not_a_match():
    m = setup_geo.match_city(tx(), "Cedar Grov")
    assert m.candidates == []
    assert [p.name for p in m.suggestions] == ["Cedar Grove"]
    assert setup_geo.match_city(tx(), "Nowhere").suggestions == []


def test_zips_go_to_the_city_holding_most_of_them():
    ref = tx()
    plan = setup_geo.make_plan(ref, places(ref, "Oak Hill", "Cedar Grove"),
                               "America/Chicago", 1, 2)
    by_name = {c.name: c for c in plan.cities}
    # 78002 is 60% Oak Hill and 30% Cedar Grove: one city per ZIP, the larger share wins
    assert by_name["Oak Hill"].zips == ["78001", "78002"]
    assert by_name["Cedar Grove"].zips == ["78003"]
    # 10% in Oak Hill: offered as a nearby ZIP, not tracked
    assert by_name["Oak Hill"].nearby == [("78004", pytest.approx(0.1))]


def test_a_city_with_no_majority_zip_keeps_its_biggest_free_one():
    ref = tx()
    plan = setup_geo.make_plan(ref, places(ref, "Oak Hill", "Tiny"), "America/Chicago", 1, 2)
    tiny = next(c for c in plan.cities if c.name == "Tiny")
    assert tiny.zips == ["78005"]  # 78002 is Oak Hill's; 78005 is free
    assert plan.dropped == []


def test_county_is_where_most_of_the_city_lies():
    ref = tx()
    plan = setup_geo.make_plan(ref, places(ref, "Oak Hill", "Cedar Grove"),
                               "America/Chicago", 1, 2)
    county = {c.name: ref.county_names[c.county] for c in plan.cities}
    assert county == {"Oak Hill": "Alpha County", "Cedar Grove": "Bravo County"}


def test_tax_rate_is_acs_taxes_over_value_falling_back_to_the_state():
    ref = tx()
    plan = setup_geo.make_plan(ref, places(ref, "Oak Hill", "Cedar Grove"),
                               "America/Chicago", 1, 2)
    rates = {c.name: c.tax_rate for c in plan.counties}
    assert rates == {"Alpha County": 0.015, "Bravo County": 0.02}  # Bravo is suppressed
    assert plan.tax_source.startswith("Census ACS 2020-2024")


def test_the_pack_rate_replaces_owner_averages_where_assessments_reset_at_sale():
    ref = setup_geo.load_reference(setup_geo.states()["CA"])
    plan = setup_geo.make_plan(ref, places(ref, "Seaside"), "America/Los_Angeles", 1, 2)
    assert [c.tax_rate for c in plan.counties] == [0.0115]  # not ACS's 0.6%
    assert "Prop 13" in plan.tax_source


def test_rendered_file_is_a_valid_geography():
    ref = tx()
    plan = setup_geo.make_plan(ref, places(ref, "Oak Hill", "Cedar Grove"),
                               "America/Chicago", 500_000, 800_000)
    geo = geography.parse(setup_geo.render(plan), "test")
    assert geo.city_names == ["Oak Hill", "Cedar Grove"]
    assert geo.state_fips == "48" and geo.timezone == "America/Chicago"
    assert {c.fips for c in geo.counties} == {"001", "003"}
    assert (geo.price_band.min, geo.price_band.max) == (500_000, 800_000)
    assert geo.pack_key == "tx"  # no pack of its own: the loader falls back to `us`


# --- what people type -----------------------------------------------------------


@pytest.mark.parametrize("text,abbr", [
    ("tx", "TX"), ("Texas", "TX"), ("texas.", "TX"), ("new york", "NY"),
    ("Washington DC", "DC"), ("dc", "DC"),
])
def test_state_spellings(text, abbr):
    st, close, why = setup_geo.parse_state(text, setup_geo.states())
    assert st.abbr == abbr and close == [] and why == ""


def test_state_typos_get_a_suggestion_and_territories_an_explanation():
    all_states = setup_geo.states()
    st, close, why = setup_geo.parse_state("Tex", all_states)
    assert st is None and [c.abbr for c in close] == ["TX"] and "not a US state" in why
    st, close, why = setup_geo.parse_state("PR", all_states)
    assert st is None and close == [] and "only the 50 states and DC" in why
    assert "e.g. TX" in setup_geo.parse_state("  ", all_states)[2]


@pytest.mark.parametrize("text,names,rejected", [
    ("Austin, TX; Round Rock, TX", ["Austin", "Round Rock"], []),
    ("Austin TX", ["Austin"], []),
    ("Austin, Texas, Round Rock", ["Austin", "Round Rock"], []),
    ("Austin\nRound Rock", ["Austin", "Round Rock"], []),
    ("austin, Austin", ["austin"], []),
    ("Winston-Salem", ["Winston-Salem"], []),
    ("78701, Austin", ["Austin"], ["78701"]),
    ("Travis County, Austin", ["Austin"], ["Travis County"]),
])
def test_city_lists_as_people_type_them(text, names, rejected):
    got, rej = setup_geo.split_cities(text, setup_geo.states()["TX"])
    assert got == names and [token for token, _reason in rej] == rejected


def test_saint_and_fort_spellings_match():
    n = setup_geo.normalize_place
    assert n("Saint Louis") == n("St. Louis") == n("st louis")
    assert n("Ft Worth") == n("Fort Worth") and n("Mt Vernon") == n("Mount Vernon")
    assert n("Winston-Salem") != n("Winston Salem")
    assert setup_geo.match_city(tx(), "Saint Cedar").obvious.full == "St. Cedar city"


@pytest.mark.parametrize("text,band", [
    ("500k-800k", (500_000, 800_000)),
    ("$1.2M to 1.5m", (1_200_000, 1_500_000)),
    ("600,000 - 900,000", (600_000, 900_000)),
    ("1.2m-1.8m", (1_200_000, 1_800_000)),
    ("$1,200,000 to $1,800,000", (1_200_000, 1_800_000)),
    ("between 500k and 800k", (500_000, 800_000)),
    ("from 500k to 800k", (500_000, 800_000)),
    ("1.2 - 1.8 million", (1_200_000, 1_800_000)),
    ("500k–800k", (500_000, 800_000)),  # en dash
    ("500k — 800k", (500_000, 800_000)),  # em dash
    # a suffix only on the top applies to both
    ("1.2-1.8m", (1_200_000, 1_800_000)),
    ("500-800k", (500_000, 800_000)),
    ("250000-800k", (250_000, 800_000)),  # a real dollar amount keeps its unit
    # bare numbers: millions below 100, thousands below 10,000
    ("2-3", (2_000_000, 3_000_000)),
    ("500-800", (500_000, 800_000)),
    ("900-1200", (900_000, 1_200_000)),
    # reversed is swapped; one bound is 0-X
    ("800k-500k", (500_000, 800_000)),
    ("under 800k", (0, 800_000)),
    ("up to 1.2M", (0, 1_200_000)),
    ("800k max", (0, 800_000)),
])
def test_price_range_parsing(text, band):
    assert setup_geo.parse_price_band(text) == band


@pytest.mark.parametrize("text,fragment", [
    ("500k", "both ends"),
    ("800k+", "top of the range too"),
    ("at least 500k", "top of the range too"),
    ("abc", "can't read 'abc'"),
    ("5b-8b", "can't read '5b'"),
    ("500k-500k", "must be above"),
    ("500k to 800k to 900k", "more than one dash"),
    ("", "Type a range"),
])
def test_bad_price_ranges_say_what_to_type(text, fragment):
    with pytest.raises(ValueError, match=fragment):
        setup_geo.parse_price_band(text)


KEY = "abcdef0123456789abcdef0123456789"


@pytest.mark.parametrize("text,key,warned", [
    (f' "{KEY}" ', KEY, False),
    (f"FRED_API_KEY={KEY}", KEY, False),
    (f"export FRED_API_KEY='{KEY}'", KEY, False),
    ("abc", "abc", True),
    ("", "", False),
])
def test_pasted_fred_keys_are_cleaned_and_odd_ones_flagged(text, key, warned):
    got, warning = setup_geo.clean_fred_key(text)
    assert got == key and bool(warning) is warned


def _all_output(result) -> str:
    try:
        return result.output + result.stderr
    except ValueError:  # older click mixes stderr into output
        return result.output


def test_cli_yes_writes_geography_and_env(repo):
    result = runner.invoke(app, ["setup", "--state", "tx", "--cities", "Oak Hill, Cedar Grove",
                                 "--price", "500k-800k", "--fred-key", "abc123", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Oak Hill" in result.output and "Alpha County" in result.output
    geo = geography.parse((repo / "geography.toml").read_text(encoding="utf-8"), "t")
    assert geo.city_names == ["Oak Hill", "Cedar Grove"]
    env = (repo / ".env").read_text(encoding="utf-8")
    assert "FRED_API_KEY=abc123" in env and "SAVE_PHOTOS=true" in env  # template kept


def test_cli_interactive_asks_and_accepts_a_suggestion(repo):
    # state, cities, "did you mean" yes, price, zone 1, no key
    answers = "TX\nOak Hill, Cedar Grov\ny\n500k-800k\n1\n\n"
    result = runner.invoke(app, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    assert "Did you mean Cedar Grove city, Bravo County?" in result.output
    assert "Central (America/Chicago)" in result.output
    assert geography.parse((repo / "geography.toml").read_text(encoding="utf-8"),
                           "t").city_names == ["Oak Hill", "Cedar Grove"]
    assert "FRED_API_KEY=\n" in (repo / ".env").read_text(encoding="utf-8")


def test_cli_takes_answers_the_way_people_type_them(repo):
    """Full state name; cities with the state after them and a ZIP code mixed in;
    a price with the suffix only on the top; the time zone by name; a key that is
    not a key, then skipped. The summary echoes the range in dollars."""
    answers = "Texas\nOak Hill TX, Cedar Grove, 78701\n1.2-1.8m\ncentral\nabc\nn\n\n"
    result = runner.invoke(app, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    assert "Skipping '78701': that is a ZIP code" in result.output
    assert "Price range: $1,200,000 - $1,800,000" in result.output
    assert "FRED keys are 32 lowercase letters and digits" in result.output
    geo = geography.parse((repo / "geography.toml").read_text(encoding="utf-8"), "t")
    assert geo.city_names == ["Oak Hill", "Cedar Grove"]
    assert (geo.price_band.min, geo.price_band.max) == (1_200_000, 1_800_000)
    assert geo.timezone == "America/Chicago"
    assert "FRED_API_KEY=\n" in (repo / ".env").read_text(encoding="utf-8")  # abc not saved


def test_cli_recovers_from_a_state_typo_and_a_half_price(repo):
    # "Tex" -> did you mean Texas? yes; "500k" -> asked again; reversed range swapped
    answers = "Tex\ny\nOak Hill\n500k\n800k-500k\n1\n\n"
    result = runner.invoke(app, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    assert "Did you mean Texas?" in result.output
    assert "Give both ends of the range" in result.output
    geo = geography.parse((repo / "geography.toml").read_text(encoding="utf-8"), "t")
    assert (geo.price_band.min, geo.price_band.max) == (500_000, 800_000)


def test_cli_asks_for_cities_again_when_none_matched(repo):
    answers = "TX\nNowhere\nOak Hill\n1-2\n1\n\n"
    result = runner.invoke(app, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    assert "one state per setup" in result.output
    assert "Type at least one city or town" in result.output
    assert (repo / "geography.toml").is_file()


def test_cli_explains_a_failed_census_download(repo, monkeypatch):
    import httpx

    def down(_state):
        raise httpx.ConnectError("name resolution failed")

    monkeypatch.setattr(setup_geo, "load_reference", down)
    result = runner.invoke(app, ["setup", "--state", "TX", "--cities", "Oak Hill",
                                 "--price", "1-2", "--yes"])
    assert result.exit_code == 1
    assert "Check your internet connection" in _all_output(result)
    assert not (repo / "geography.toml").exists()


def test_cli_replaces_an_existing_file_and_says_so(repo):
    """Running setup again is itself the decision to change the area: no
    second question, but the output says a file was replaced."""
    (repo / "geography.toml").write_text("old area", encoding="utf-8")
    (repo / ".env").write_text("FRED_API_KEY=set\n", encoding="utf-8")
    result = runner.invoke(app, ["setup", "--state", "TX", "--cities", "Cedar Grove",
                                 "--price", "1-2"], input="\n")  # zone only
    assert result.exit_code == 0, result.output
    assert "Replaced" in result.output and "geography.toml" in result.output
    assert "Cedar Grove" in (repo / "geography.toml").read_text(encoding="utf-8")


def test_cli_yes_fails_on_an_unknown_city(repo):
    result = runner.invoke(app, ["setup", "--state", "TX", "--cities", "Cedar Grov",
                                 "--price", "1-2", "--yes"])
    assert result.exit_code != 0
    assert not (repo / "geography.toml").exists()


def test_serve_and_daily_warn_when_running_on_the_example(repo, monkeypatch):
    from hb import cli

    monkeypatch.setattr(cli.typer, "echo", lambda msg="", err=False: seen.append(msg))
    seen: list[str] = []
    cli._warn_if_example()
    assert any("make setup" in m for m in seen)

    (repo / "geography.toml").write_text("", encoding="utf-8")
    seen.clear()
    cli._warn_if_example()
    assert seen == []
