"""`hb setup` — write geography.toml from a state, city names and a price range
(docs/packs/README.md §1).

The wizard asks only what a buyer knows. Every other value in the file comes from
free Census Bureau reference files, downloaded once into data/raw/census/<date>/
(about 75 MB, no key) and reused by later runs:

- places Gazetteer       city names, incorporated or not, centre points
- ZCTA Gazetteer         ZIP centre points (map zoom, hazard bbox)
- ZCTA-place relation    which ZIPs make up each city, by share of the ZIP's land
- ZCTA-county relation   each city's county, its name and FIPS code
- ACS 5-year B25090 / B25082   aggregate real-estate taxes paid / aggregate value
                         of owner-occupied homes per county = the owners'
                         effective tax rate, unless the pack names the rate a
                         buyer pays (`Affordability.purchase_tax_rate`)

ZCTAs are the Census Bureau's approximation of ZIP codes (PO-box-only ZIPs have
none). Census county names ("Travis County") are the ones Redfin uses, which
the redfin-market job matches on.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import tomllib
import zipfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path

import httpx
from rapidfuzz import fuzz, process

from hb import geography

KEEP_SHARE = 0.25  # a ZIP belongs to a city when this much of its land is in it
NEARBY_SHARE = 0.05  # below KEEP_SHARE but above this: listed as a nearby ZIP

GAZETTEER = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
             "{year}_Gazetteer/{year}_Gaz_{kind}_national.zip")
RELATION = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
            "tab20_zcta520_{kind}20_natl.txt")
ACS = ("https://www2.census.gov/programs-surveys/acs/summary_file/{year}/table-based-SF/"
       "data/5YRData/acsdt5y{year}-{table}.dat")

# key -> (URL template, template fields); a template with {year} is tried
# newest year first, so the wizard picks up each release without a code change.
SOURCES: dict[str, tuple[str, dict[str, str]]] = {
    "places": (GAZETTEER, {"kind": "place"}),
    "zctas": (GAZETTEER, {"kind": "zcta"}),
    "zcta_place": (RELATION, {"kind": "place"}),
    "zcta_county": (RELATION, {"kind": "county"}),
    "acs_taxes": (ACS, {"table": "b25090"}),
    "acs_values": (ACS, {"table": "b25082"}),
}

# Gazetteer names end in the place's legal description; the buyer types without it.
_SUFFIX = re.compile(
    r"\s+(city and borough|city|town|village|borough|CDP|municipality|plantation|"
    r"(consolidated|unified|metropolitan|metro) government|urban county|corporation)"
    r"(\s+\(balance\))?$"
)


# ---------------------------------------------------------------- states


@dataclass(frozen=True)
class State:
    abbr: str
    name: str
    fips: str
    zones: tuple[str, ...]


def _states_file() -> dict:
    return tomllib.loads((resources.files("hb") / "us_states.toml").read_text(encoding="utf-8"))


def states() -> dict[str, State]:
    return {
        abbr: State(abbr, s["name"], s["fips"], tuple(s["zones"]))
        for abbr, s in _states_file()["states"].items()
    }


def zone_labels() -> dict[str, str]:
    return _states_file()["zones"]


# ---------------------------------------------------------------- downloads


def cache_dir() -> Path:
    from hb.config import settings

    return settings.raw_dir / "census"


def cached(key: str) -> Path | None:
    """The newest cached copy of one reference file, if any run fetched it."""
    root = cache_dir()
    if not root.is_dir():
        return None
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        hits = sorted(folder.glob(f"{key}-*.txt")) + sorted(folder.glob(f"{key}.txt"))
        if hits:
            return hits[-1]
    return None


def _candidates(key: str) -> list[tuple[str, str]]:
    """(url, saved name) pairs to try for a source, newest release first."""
    template, fields = SOURCES[key]
    if "{year}" not in template:
        return [(template.format(**fields), f"{key}.txt")]
    this_year = date.today().year
    return [(template.format(year=y, **fields), f"{key}-{y}.txt")
            for y in range(this_year, this_year - 4, -1)]


def fetch_reference(key: str) -> Path:
    """Seam for tests: a local path to one reference file, downloading it into
    the raw cache on first use. A Gazetteer .zip is unpacked to its .txt."""
    hit = cached(key)
    if hit:
        return hit
    folder = cache_dir() / date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    for url, name in _candidates(key):
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as resp:
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            body = b"".join(resp.iter_bytes(1 << 20))
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                member = next(n for n in z.namelist() if n.endswith(".txt"))
                body = z.read(member)
        path = folder / name
        path.write_bytes(body)
        return path
    raise FileNotFoundError(f"no Census release found for {key} (tried {_candidates(key)[0][0]})")


def needs_download() -> bool:
    return any(cached(key) is None for key in SOURCES)


def _year(path: Path) -> int | None:
    m = re.search(r"-(\d{4})\.txt$", path.name)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- reference data


@dataclass(frozen=True)
class Place:
    geoid: str
    name: str  # without the legal suffix: "Round Rock"
    full: str  # as the Census Bureau writes it: "Round Rock city"
    incorporated: bool
    lat: float
    lon: float
    land: int


@dataclass
class Reference:
    """One state's slice of the reference files."""

    state: State
    places: list[Place]
    # place geoid -> [(zcta, land of the zcta inside the place, the zcta's land)]
    zcta_place: dict[str, list[tuple[str, int, int]]]
    zcta_county: dict[str, dict[str, int]]  # zcta -> {county geoid: shared land}
    county_names: dict[str, str]  # county geoid (5 digits) -> "Travis County"
    zcta_points: dict[str, tuple[float, float]]  # zcta -> (lat, lon)
    tax_rates: dict[str, float]  # county geoid -> owners' effective rate
    state_tax_rate: float | None
    acs_label: str  # "ACS 2020-2024"


def _gazetteer(path: Path) -> list[dict[str, str]]:
    """A Gazetteer file as dicts. Releases up to 2025 are tab-delimited with
    padded values; 2026 switched to pipes."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        delimiter = "|" if "|" in fh.readline() else "\t"
        fh.seek(0)
        rows = csv.reader(fh, delimiter=delimiter)
        header = [h.strip() for h in next(rows)]
        return [dict(zip(header, (v.strip() for v in row), strict=False)) for row in rows]


def _pipe(path: Path, column: str, keep: Callable[[str], bool]) -> tuple[list[str], list[list[str]]]:
    """A pipe-delimited file's header and the rows whose `column` passes `keep`."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = csv.reader(fh, delimiter="|")
        header = next(rows)
        i = header.index(column)
        return header, [row for row in rows if len(row) > i and keep(row[i])]


def base_name(full: str) -> str:
    return _SUFFIX.sub("", full).strip()


def load_reference(state: State) -> Reference:
    fips = state.fips

    places = [
        Place(
            geoid=r["GEOID"], name=base_name(r["NAME"]), full=r["NAME"],
            incorporated=r["FUNCSTAT"] == "A", lat=float(r["INTPTLAT"]),
            lon=float(r["INTPTLONG"]), land=int(r["ALAND"]),
        )
        for r in _gazetteer(fetch_reference("places")) if r["USPS"] == state.abbr
    ]

    head, rows = _pipe(fetch_reference("zcta_place"), "GEOID_PLACE_20",
                       lambda g: g.startswith(fips))
    i_zcta, i_place = head.index("GEOID_ZCTA5_20"), head.index("GEOID_PLACE_20")
    i_zland, i_part = head.index("AREALAND_ZCTA5_20"), head.index("AREALAND_PART")
    zcta_place: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for r in rows:
        if r[i_zcta] and int(r[i_zland]):  # skip land outside any ZCTA, and water-only ZCTAs
            zcta_place[r[i_place]].append((r[i_zcta], int(r[i_part]), int(r[i_zland])))

    head, rows = _pipe(fetch_reference("zcta_county"), "GEOID_COUNTY_20",
                       lambda g: g.startswith(fips))
    i_zcta, i_county = head.index("GEOID_ZCTA5_20"), head.index("GEOID_COUNTY_20")
    i_name, i_part = head.index("NAMELSAD_COUNTY_20"), head.index("AREALAND_PART")
    zcta_county: dict[str, dict[str, int]] = defaultdict(dict)
    county_names: dict[str, str] = {}
    for r in rows:
        county_names[r[i_county]] = r[i_name]
        if r[i_zcta]:
            zcta_county[r[i_zcta]][r[i_county]] = int(r[i_part])

    zcta_points = {
        r["GEOID"]: (float(r["INTPTLAT"]), float(r["INTPTLONG"]))
        for r in _gazetteer(fetch_reference("zctas")) if r["GEOID"] in zcta_county
    }

    taxes_path = fetch_reference("acs_taxes")
    geos = {f"0400000US{fips}"}

    def ours(geo_id: str) -> bool:
        return geo_id in geos or geo_id.startswith(f"0500000US{fips}")

    def first_column(path: Path) -> dict[str, float]:
        head, rows = _pipe(path, "GEO_ID", ours)
        col = next(i for i, h in enumerate(head) if h.endswith("_E001"))
        out = {}
        for r in rows:
            try:
                out[r[0]] = float(r[col])
            except ValueError:  # suppressed estimate
                continue
        return out

    taxes, values = first_column(taxes_path), first_column(fetch_reference("acs_values"))
    rates = {g: taxes[g] / values[g] for g in taxes if values.get(g, 0) > 0 and taxes[g] > 0}
    year = _year(taxes_path)

    return Reference(
        state=state,
        places=places,
        zcta_place=dict(zcta_place),
        zcta_county=dict(zcta_county),
        county_names=county_names,
        zcta_points=zcta_points,
        tax_rates={g[-5:]: r for g, r in rates.items() if g.startswith("0500000US")},
        state_tax_rate=rates.get(f"0400000US{fips}"),
        acs_label=f"ACS {year - 4}-{year}" if year else "ACS 5-year",
    )


# ---------------------------------------------------------------- matching


@dataclass
class Match:
    query: str
    candidates: list[Place]  # exact name matches, the most likely first
    suggestions: list[Place]  # near spellings, when there is no exact match

    @property
    def obvious(self) -> Place | None:
        """The one candidate, or the only incorporated one among same-named
        CDPs; None when the buyer has to choose."""
        if len(self.candidates) == 1:
            return self.candidates[0]
        cities = [p for p in self.candidates if p.incorporated]
        return cities[0] if len(cities) == 1 else None


_WORDS = {"saint": "st", "fort": "ft", "mount": "mt"}


def normalize_place(name: str) -> str:
    """'Saint Louis', 'St. Louis' and 'st louis' compare equal; so do 'Ft Worth' /
    'Fort Worth' and 'Mt Vernon' / 'Mount Vernon'. Hyphens stay: Winston-Salem."""
    words = name.casefold().replace(".", "").replace("'", "").split()
    return " ".join(_WORDS.get(w, w) for w in words)


def match_city(ref: Reference, query: str) -> Match:
    q = normalize_place(query)
    exact = [p for p in ref.places if normalize_place(p.name) == q or normalize_place(p.full) == q]
    # an incorporated city before a same-named unincorporated CDP, then the larger
    exact.sort(key=lambda p: (not p.incorporated, -p.land))
    suggestions: list[Place] = []
    if not exact:
        names = [p.name for p in ref.places]
        for _name, _score, i in process.extract(query, names, scorer=fuzz.ratio,
                                                limit=3, score_cutoff=80):
            suggestions.append(ref.places[i])
    return Match(query=query, candidates=exact, suggestions=suggestions)


def place_county(ref: Reference, place: Place) -> str:
    """The county holding most of the place's land, as a 5-digit geoid."""
    weight: dict[str, float] = defaultdict(float)
    for zcta, part, zland in ref.zcta_place.get(place.geoid, []):
        for county, shared in ref.zcta_county.get(zcta, {}).items():
            weight[county] += part * shared / zland
    if not weight:
        raise ValueError(f"{place.full} has no ZIP data in the Census files")
    return max(weight, key=weight.get)


def describe(ref: Reference, place: Place) -> str:
    """'Mountain View city, Santa Clara County' — how a choice is shown."""
    try:
        county = ref.county_names[place_county(ref, place)]
    except ValueError:
        return place.full
    return f"{place.full}, {county}"


# ---------------------------------------------------------------- the plan


@dataclass
class CityPlan:
    name: str
    county: str  # 5-digit geoid
    zips: list[str]
    nearby: list[tuple[str, float]] = field(default_factory=list)  # (zip, share in city)


@dataclass
class CountyPlan:
    geoid: str
    name: str
    tax_rate: float


@dataclass
class Plan:
    state: State
    timezone: str
    price_min: int
    price_max: int
    cities: list[CityPlan]
    counties: list[CountyPlan]
    tax_source: str  # where the county rates came from, for the summary and the file
    dropped: list[str]  # cities left out because every ZIP belongs to another city
    center: tuple[float, float]  # (lon, lat)
    zoom: int
    bbox: tuple[float, float, float, float]


def _pack_tax(state: State) -> tuple[float | None, str]:
    from hb.packs import DEFAULT_KEY, REGISTRY

    pack = REGISTRY.get(state.abbr.lower(), REGISTRY[DEFAULT_KEY])
    return pack.affordability.purchase_tax_rate, pack.affordability.purchase_tax_note


def make_plan(ref: Reference, places: list[Place], timezone: str,
              price_min: int, price_max: int) -> Plan:
    shares: dict[str, dict[str, float]] = defaultdict(dict)  # zcta -> {place geoid: share}
    for p in places:
        for zcta, part, zland in ref.zcta_place.get(p.geoid, []):
            shares[zcta][p.geoid] = part / zland

    # each ZIP goes to the chosen city holding most of it — the loader allows one city per ZIP
    zips: dict[str, list[str]] = {p.geoid: [] for p in places}
    nearby: dict[str, list[tuple[str, float]]] = {p.geoid: [] for p in places}
    for zcta, by_place in shares.items():
        geoid, share = max(by_place.items(), key=lambda kv: kv[1])
        if share >= KEEP_SHARE:
            zips[geoid].append(zcta)
        elif share >= NEARBY_SHARE:
            nearby[geoid].append((zcta, share))

    # a small city entirely inside a larger ZIP keeps its biggest ZIP, if no other city has it
    taken = {z for zs in zips.values() for z in zs}
    for p in places:
        if not zips[p.geoid]:
            own = sorted(((s[p.geoid], z) for z, s in shares.items()
                          if p.geoid in s and z not in taken), reverse=True)
            if own:
                zips[p.geoid].append(own[0][1])
                taken.add(own[0][1])
                nearby[p.geoid] = [n for n in nearby[p.geoid] if n[0] != own[0][1]]

    cities, dropped = [], []
    for p in places:
        if not zips[p.geoid]:
            dropped.append(p.name)
            continue
        cities.append(CityPlan(
            name=p.name, county=place_county(ref, p), zips=sorted(zips[p.geoid]),
            nearby=sorted(nearby[p.geoid], key=lambda n: -n[1]),
        ))
    if not cities:
        raise ValueError("none of those cities has a ZIP code of its own")

    pack_rate, pack_note = _pack_tax(ref.state)
    counties = []
    for geoid in dict.fromkeys(c.county for c in cities):
        rate = pack_rate or ref.tax_rates.get(geoid) or ref.state_tax_rate
        if rate is None:
            raise ValueError(f"no Census tax data for {ref.county_names[geoid]}")
        counties.append(CountyPlan(geoid, ref.county_names[geoid], round(rate, 4)))
    tax_source = pack_note or (f"Census {ref.acs_label}: aggregate taxes / value of "
                               "owner-occupied homes")

    points = [ref.zcta_points[z] for c in cities for z in c.zips if z in ref.zcta_points]
    points = points or [(p.lat, p.lon) for p in places]
    lats, lons = [pt[0] for pt in points], [pt[1] for pt in points]
    span = max(max(lats) - min(lats), max(lons) - min(lons), 0.05)
    by_name = {p.name: p for p in places}
    centre = [by_name[c.name] for c in cities]
    pad = 0.25  # ZCTA centre points sit inside the ZIP; pad out to its edges

    return Plan(
        state=ref.state, timezone=timezone, price_min=price_min, price_max=price_max,
        cities=cities, counties=counties, tax_source=tax_source, dropped=dropped,
        center=(round(sum(p.lon for p in centre) / len(centre), 3),
                round(sum(p.lat for p in centre) / len(centre), 3)),
        zoom=max(7, min(12, round(math.log2(360 / span)))),
        bbox=(round(min(lons) - pad, 2), round(min(lats) - pad, 2),
              round(max(lons) + pad, 2), round(max(lats) + pad, 2)),
    )


# ---------------------------------------------------------------- output


def _s(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # a valid TOML basic string


def render(plan: Plan, today: date | None = None) -> str:
    """The geography.toml text, commented for a later hand edit."""
    names = ", ".join(c.name for c in plan.cities)
    county_names = {c.geoid: c.name for c in plan.counties}
    lines = [
        f"# Written by `hb setup` on {(today or date.today()).isoformat()} "
        f"for {names} ({plan.state.abbr}).",
        "# Edit any value by hand (docs/packs/README.md §1 explains each one), or run",
        "# `make setup` again to start over.",
        "",
        "schema = 1",
        f"name = {_s(plan.cities[0].name + ' area')}",
        f"state = {_s(plan.state.abbr)}",
        f"state_fips = {_s(plan.state.fips)}",
        f"timezone = {_s(plan.timezone)}",
        "",
        "[map]",
        f"center = [{plan.center[0]}, {plan.center[1]}]  # [lon, lat]",
        f"zoom = {plan.zoom}",
        "",
        "[price_band]  # alerts and default filters only; every price is still downloaded",
        f"min = {plan.price_min}",
        f"max = {plan.price_max}",
        "",
        "[market]",
        "hazard_bbox = [{}, {}, {}, {}]  # lon/lat box around your ZIPs".format(*plan.bbox),
        '# case_shiller_fred_id = ""  # your metro\'s Case-Shiller index on FRED, if it has one',
        "",
        f"# effective_tax_rate: {plan.tax_source}.",
        "# An estimate: replace it with the rate on a recent tax bill if you have one.",
    ]
    for c in plan.counties:
        lines += [
            "",
            "[[counties]]",
            f"name = {_s(c.name)}",
            f'fips = "{c.geoid[2:]}"',
            f"effective_tax_rate = {c.tax_rate}",
        ]
    lines += [
        "",
        f"# ZIPs: Census ZCTAs with at least {KEEP_SHARE:.0%} of their land in the city.",
        "# The 'partly in' ZIPs below each city can be added to its list.",
    ]
    for c in plan.cities:
        zips = ", ".join(_s(z) for z in c.zips)
        lines += [
            "",
            "[[cities]]",
            f"name = {_s(c.name)}",
            f"county = {_s(county_names[c.county])}",
            f"zips = [{zips}]",
        ]
        if c.nearby:
            near = ", ".join(f"{z} ({s:.0%})" for z, s in c.nearby)
            lines.append(f"# partly in {c.name}: {near}")
    text = "\n".join(lines) + "\n"
    geography.parse(text, "geography.toml")  # never write a file the app would reject
    return text


def summary(plan: Plan) -> list[str]:
    county_names = {c.geoid: c.name for c in plan.counties}
    width = max(len(c.name) for c in plan.cities)
    cwidth = max(len(n) for n in county_names.values())
    out = [f"  Price range: ${plan.price_min:,} - ${plan.price_max:,}  "
           "(alerts and default filters; every listing is still loaded)"]
    for c in plan.cities:
        shown = " ".join(c.zips[:6]) + (" ..." if len(c.zips) > 6 else "")
        noun = "ZIP" if len(c.zips) == 1 else "ZIPs"
        out.append(f"  {c.name:<{width}}  {county_names[c.county]:<{cwidth}}  "
                   f"{len(c.zips):>2} {noun}: {shown}")
    rates = "   ".join(f"{c.name.removesuffix(' County')} {c.tax_rate:.2%}"
                       for c in plan.counties)
    out.append(f"  Property tax: {rates}")
    out.append(f"    ({plan.tax_source})")
    out.append(f"  Time zone: {plan.timezone}")
    for name in plan.dropped:
        out.append(f"  Left out {name}: every ZIP it touches belongs to another city above.")
    return out


# ---------------------------------------------------------------- what people type
#
# Every prompt forgives the spellings people actually use. Each parser is pure so
# the cases live in tests; the wizard echoes what it understood in the summary
# before anything is saved.

NOT_SUPPORTED = {"pr": "Puerto Rico", "gu": "Guam", "vi": "the U.S. Virgin Islands",
                 "as": "American Samoa", "mp": "the Northern Mariana Islands"}
_STATE_ALIASES = {"dc": "DC", "washington dc": "DC", "washington d.c.": "DC", "d.c.": "DC",
                  "district of columbia": "DC"}


def parse_state(text: str, all_states: dict[str, State]) -> tuple[State | None, list[State], str]:
    """'TX', 'tx', 'Texas', 'texas.' -> (state, [], ""). Otherwise (None, close
    matches, reason) where reason is a sentence for the person."""
    t = text.strip().strip(".,").casefold()
    if not t:
        return None, [], "Type your state, e.g. TX or Texas."
    if t in NOT_SUPPORTED:
        return None, [], f"{NOT_SUPPORTED[t]} is not supported: only the 50 states and DC."
    if t in _STATE_ALIASES:
        return all_states[_STATE_ALIASES[t]], [], ""
    if t.upper() in all_states:
        return all_states[t.upper()], [], ""
    by_name = {st.name.casefold(): st for st in all_states.values()}
    if t in by_name:
        return by_name[t], [], ""
    if t in {n.casefold() for n in NOT_SUPPORTED.values()}:
        return None, [], f"{text.strip()} is not supported: only the 50 states and DC."
    hits = process.extract(t, list(by_name), scorer=fuzz.WRatio, limit=3, score_cutoff=75)
    close = [by_name[name] for name, _score, _i in hits]
    return None, close, f"{text.strip()!r} is not a US state."


def split_cities(text: str, state: State) -> tuple[list[str], list[tuple[str, str]]]:
    """'Austin, TX; Round Rock, TX' / 'Austin TX' / one per line -> the city names,
    deduplicated, with the state dropped — plus (token, reason) for anything that
    is clearly not a city name, so the wizard can say why it was skipped."""
    state_words = {state.abbr.casefold(), state.name.casefold()}
    names: list[str] = []
    rejected: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;\n]+", text):
        tok = raw.strip().strip("\"'").strip()
        if not tok or tok.casefold() in state_words:
            continue  # the ", TX" after a city name
        words = tok.split()
        if len(words) > 1 and words[-1].casefold().strip(".") in state_words:
            tok = " ".join(words[:-1])  # 'Austin TX'
        if re.fullmatch(r"\d{5}(-\d{4})?", tok):
            rejected.append((tok, "that is a ZIP code; type the city, and the ZIPs come "
                                  "from Census data"))
            continue
        if tok.casefold().endswith(" county"):
            rejected.append((tok, "that is a county; type the cities in it"))
            continue
        key = normalize_place(tok)
        if key in seen:
            continue
        seen.add(key)
        names.append(tok)
    return names, rejected


_MULT = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "mm": 1_000_000, "mil": 1_000_000,
         "million": 1_000_000}
_RANGE_WORDS = [(r"^\s*(between|from|about|around|roughly|~)\s+", ""),
                (r"\s+(and|to|through|thru)\s+", "-")]
_UP_TO = re.compile(r"^(?:under|up ?to|at most|below|max(?:imum)?|less than|<=?)\s*(.+)$"
                    r"|^(.+?)\s*(?:max(?:imum)?|or less|or under|and under|and below|tops)$")
_AT_LEAST = re.compile(r"^(?:over|above|at least|min(?:imum)?|more than|>=?)\s*(.+)$"
                       r"|^(.+?)\s*(?:\+|and up|or more|or above|plus|minimum)$")


def _money(text: str) -> tuple[float, int | None]:
    """'800k' -> (800, 1000); '1.2 million' -> (1.2, 1_000_000); '750000' -> (750000, None)."""
    t = text.strip().casefold().replace("$", "").replace(",", "").replace("usd", "")
    t = re.sub(r"\s*dollars?$", "", t).replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?|\.\d+)([a-z]*)", t)
    if not m or (m.group(2) and m.group(2) not in _MULT):
        raise ValueError(f"I can't read {text.strip()!r} as a price. Write it like 800k, "
                         "1.2m or 800000.")
    return float(m.group(1)), _MULT.get(m.group(2)) if m.group(2) else None


def parse_price_band(text: str) -> tuple[int, int]:
    """The price range as people type it -> (min, max) in dollars.

    '500k-800k', '1.2m-1.8m', '$1,200,000 to $1,800,000', 'between 500k and 800k',
    '1.2 - 1.8 million'. A suffix only on the top applies to both ('1.2-1.8m',
    '500-800k'); bare numbers are millions below 100 ('2-3') and thousands below
    10,000 ('500-800'); 'under 800k' is 0-800k; a reversed range is swapped. The
    wizard echoes the result in dollars before anything is saved."""
    t = re.sub(r"[\u2013\u2014\u2212]", "-", text.strip().casefold())
    if not t:
        raise ValueError("Type a range such as 500k-800k or 1.2m-1.8m.")

    if "-" not in t:  # one bound only: 'under 800k' / '800k max' / '800k+'
        m = _UP_TO.match(t)
        if m:
            high, mult = _money(m.group(1) or m.group(2))
            return 0, _dollars(high, mult, bare_hint=high)
        if _AT_LEAST.match(t):
            raise ValueError("I need the top of the range too, e.g. 800k-1.2m.")
    for pattern, repl in _RANGE_WORDS:
        t = re.sub(pattern, repl, t)

    parts = [p for p in re.split(r"\s*-\s*", t) if p]
    if len(parts) == 1:
        _money(parts[0])  # a non-number says so; a lone number needs its other end
        raise ValueError("Give both ends of the range, e.g. 500k-800k or 1.2m-1.8m "
                         "(or 'under 800k').")
    if len(parts) != 2:
        raise ValueError("I see more than one dash. Write it like 500k-800k.")
    (low, lmult), (high, hmult) = _money(parts[0]), _money(parts[1])
    if lmult is None and hmult is not None and low < 1000:
        lmult = hmult  # '1.2-1.8m', '500-800k'
    hint = max(low, high)
    low_d, high_d = _dollars(low, lmult, hint), _dollars(high, hmult, hint)
    if low_d > high_d:
        low_d, high_d = high_d, low_d
    if low_d == high_d:
        raise ValueError("The top of the range must be above the bottom.")
    return low_d, high_d


def _dollars(value: float, mult: int | None, bare_hint: float) -> int:
    """Apply a suffix, or guess the unit of a bare number from the larger number
    in the range: below 100 means millions, below 10,000 thousands."""
    if mult is None:
        mult = 1_000_000 if bare_hint < 100 else 1_000 if bare_hint < 10_000 else 1
    dollars = int(round(value * mult))
    if dollars > 2_000_000_000:
        raise ValueError(f"${dollars:,} is more than any home costs; check the units.")
    return dollars


def clean_fred_key(text: str) -> tuple[str, str]:
    """A pasted key as people paste it -> (key, warning). Strips quotes, spaces and a
    'FRED_API_KEY=' prefix; warns when the shape is wrong (32 hex characters)."""
    key = text.strip().strip("\"'").strip()
    key = re.sub(r"^(?:export\s+)?FRED_API_KEY\s*=\s*", "", key, flags=re.IGNORECASE)
    key = key.strip().strip("\"'")
    if not key:
        return "", ""
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        return key, (f"FRED keys are 32 lowercase letters and digits; this one is "
                     f"{len(key)} characters.")
    return key, ""


# ---------------------------------------------------------------- .env


def env_value(text: str, key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def write_env(repo_root: Path, fred_key: str | None) -> str:
    """Create .env from .env.example if missing and set FRED_API_KEY when given.
    Returns what was done, for the wizard to print."""
    env, example = repo_root / ".env", repo_root / ".env.example"
    created = not env.is_file()
    text = env.read_text(encoding="utf-8") if not created else (
        example.read_text(encoding="utf-8") if example.is_file() else "")
    if fred_key:
        line = f"FRED_API_KEY={fred_key.strip()}"
        if re.search(r"^FRED_API_KEY=", text, re.MULTILINE):
            text = re.sub(r"^FRED_API_KEY=.*$", lambda _m: line, text, flags=re.MULTILINE)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    if created or fred_key:
        env.write_text(text, encoding="utf-8")
    if created:
        return "Created .env from .env.example" + (" with your FRED key." if fred_key else ".")
    return "Saved your FRED key in .env." if fred_key else ""
