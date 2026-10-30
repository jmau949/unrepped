# State packs and the geography file

Two layers make the app work outside the market it was built in:

1. **The geography** (`geography.toml`) — *where* you are buying: cities, ZIPs, counties, tax
   rates, time zone, map view, price band. One file per instance, gitignored, written by
   `make setup`.
2. **The state pack** (`backend/hb/packs/<key>/`) — *how transactions work there*: contingency
   defaults, named forms, the closing / tour / prep task prose, hazard polygon layers, school
   rating sources, the Tracker's disclosure checklist. Packs ship with the
   repo; the geography picks one.

The engines (`hb/closing_spec.py`, `hb/tour_spec.py`, `hb/prep_spec.py`, `hb/brief.py`) are
generic and take the pack as data. **No city, ZIP, county or state literal lives outside
`geography.toml` and `hb/packs/`.** The frontend reads both from `GET /api/config`
(`docs/07`), never from literals.

## 1. The geography file

Resolution order (`hb/geography.py` → `settings.geo`): `GEOGRAPHY_FILE=<path>` in `.env`,
then `<repo-root>/geography.toml`, then the packaged example named by `GEOGRAPHY` in `.env`
(`backend/hb/geographies/<name>.toml`, default `sf_peninsula`). The settings load it on first
use, not at import, so `hb setup` still runs when a hand-edited file no longer parses. With
neither `GEOGRAPHY_FILE` nor `geography.toml` present (`settings.geo_is_example`), `hb serve`
and `hb pipeline daily` print a note that the packaged example is in use.

### Writing it: `make setup`

`make setup` (`hb setup`, `hb/setup_geo.py`) asks for a state, city names and a price range,
then writes `geography.toml` to `GEOGRAPHY_FILE` if set, else the repo root:

```
$ make setup
State (e.g. TX or Texas): Texas
Cities or towns you're shopping in, comma-separated (e.g. Austin, Round Rock): Austin TX, Round Rock, Cedar Pk
Downloading Census reference data (about 75 MB, first run only)...
  "Cedar Pk" is not a city or town in Texas. Did you mean Cedar Park city, Williamson County? [Y/n]:
The price range sets alerts and default filters; every listing is still loaded.
Price range (e.g. 500k-800k or 1.2m-1.8m): 500-800k
Texas has more than one time zone:
  1) Central (America/Chicago)
  2) Mountain (America/Denver)
Which one are your cities in [1]:
FRED API key for mortgage rates, free at fred.stlouisfed.org/docs/api/api_key.html (Enter to skip):

  Price range: $500,000 - $800,000  (alerts and default filters; every listing is still loaded)
  Austin      Travis County      37 ZIPs: 78701 78702 78703 78704 78705 78712 ...
  Round Rock  Williamson County   3 ZIPs: 78664 78665 78681
  Cedar Park  Williamson County   1 ZIP: 78613
  Property tax: Travis 1.31%   Williamson 1.50%
    (Census ACS 2020-2024: aggregate taxes / value of owner-occupied homes)
  Time zone: America/Chicago
Saved /home/you/home-buying/geography.toml.
Created .env from .env.example.
Next: make start  (the first run takes an hour or more; it prints its progress)
```

What each prompt accepts (`setup_geo.parse_state`, `split_cities`, `parse_price_band`,
`clean_fred_key`; every case below is a test in `test_setup_geo.py`):

- **State**: `TX`, `Texas`, `texas.`; `Washington DC` / `dc`. A typo with one close match asks
  "Did you mean Texas?"; a territory (`PR`, `Guam`) is told only the 50 states and DC are
  supported.
- **Cities**: separated by commas, semicolons or new lines; a trailing state is dropped
  (`Austin, TX`, `Austin TX`); `Saint`/`St.`, `Fort`/`Ft`, `Mount`/`Mt` compare equal; hyphens
  are kept (`Winston-Salem`); duplicates collapse. A ZIP code or `X County` is skipped with
  the reason. Names are resolved right after this prompt (the Census download happens here):
  a name matching more than one incorporated city asks which (an incorporated city beats a
  same-named CDP silently; the summary shows its county); a near spelling asks "Did you mean
  …?"; anything else is skipped with a note that a neighborhood needs its city and another
  state needs its own run. If nothing matched, it asks for the cities again.
- **Price range**: `500k-800k`, `1.2m-1.8m`, `$1,200,000 to $1,800,000`, `between 500k and
  800k`, `1.2 - 1.8 million`, en or em dashes. A suffix only on the top applies to both
  (`1.2-1.8m`, `500-800k`); bare numbers are millions below 100 (`2-3`) and thousands below
  10,000 (`500-800`); `under 800k` / `up to 800k` / `800k max` is 0–800k; a reversed range is
  swapped; `800k+` and a single number ask for the other end. The summary echoes the range in
  dollars before anything is saved.
- **Time zone**: asked only in a state with several; by number or by name (`central`).
- **FRED key**: shown as typed; quotes and a `FRED_API_KEY=` prefix are stripped; a key that is
  not 32 hex characters asks before it is saved. Enter skips.

If the Census download fails (no internet), it says so and exits without writing anything.
On a first run it also creates `.env` from `.env.example`, with the FRED key if one was
given; on a later run a key given with `--fred-key` or typed at the prompt is written into
the existing `.env` in place (`setup_geo.write_env`, which then prints "Saved your FRED key
in .env."). The "Saved" line carries the full path of the file written. A chosen city whose
every ZIP went to another chosen city is left out of the file, and the summary says so:
"Left out <city>: every ZIP it touches belongs to another city above." An existing
`geography.toml` is replaced without asking (running setup again is the
decision; the output says "Replaced"), so a hand edit there should be redone afterwards.
Options for scripts:
`--state --cities --price --timezone --fred-key --yes` (`--yes` asks nothing, takes every
default, and fails on anything it cannot resolve).

Where each value comes from. The Census files are downloaded once into
`data/raw/census/<date>/` and reused; each `{year}` source is tried newest year first, so a new
release is picked up without a code change.

| Field | Source |
|---|---|
| city names, centre points | Census places Gazetteer; the legal suffix ("city", "town", "CDP", …) is stripped, and the match is case-insensitive |
| `zips` | 2020 ZCTA↔place relationship file: a ZCTA belongs to a city when ≥ 25% of its land is in it (`KEEP_SHARE`); a ZCTA in two chosen cities goes to the larger share, since a ZIP may appear under one city only. A city with no such ZIP keeps its largest ZIP no other city holds. ZCTAs 5–25% in a city are written as a `# partly in <city>: …` comment to add by hand |
| `county`, `[[counties]] name`, `fips` | ZCTA↔county relationship file: the county holding most of the city's land. Census county names are Redfin's region names |
| `effective_tax_rate` | ACS 5-year tables B25090 ÷ B25082 (aggregate real-estate taxes ÷ aggregate value of owner-occupied homes) per county, the state's ratio where a county's is suppressed — unless the pack sets `Affordability.purchase_tax_rate` (the `ca` pack: 1.15%, since Prop 13 owners pay far less than a buyer) |
| `state_fips`, `timezone` | `backend/hb/us_states.toml` (FIPS and the zones each state uses) |
| `[map]` | centre = mean of the cities' Gazetteer points; zoom from the spread of their ZIPs |
| `[market] hazard_bbox` | the ZIPs' ZCTA Gazetteer points, padded 0.25° |
| `name` | "<first city> area" |

`pack` is left out (the loader picks the state's pack, else `us`); `case_shiller_fred_id`,
`[costs]` and the optional county text (`assessor_label`, `assessor_url`,
`transfer_tax_note`) are left for a hand edit. ZCTAs approximate ZIP codes: a PO-box-only ZIP
has no ZCTA, so add one by hand if you need it.

### Editing it by hand

The file is plain TOML. Every field, as `make setup` writes it or as the packaged example spells
it out:

```toml
schema = 1
name = "SF Peninsula"            # metro label for UI copy ("2026 SF-Peninsula ranges", the brief)
state = "CA"                     # two letters; drives every state-filtered source (NCES, SchoolDigger, HomeHarvest)
state_fips = "06"                # two digits; with county fips builds FEMA DFIRM ids
timezone = "America/Los_Angeles" # IANA name, validated
pack = "ca"                      # optional; default = lower-cased state; any key not in the registry (a state with no pack, or an unknown name) falls back to "us" silently

[map]
center = [-122.2, 37.55]         # [lon, lat]
zoom = 9

[price_band]                     # alerts + default UI filters ONLY — never an ingestion filter
min = 2_000_000
max = 3_000_000

[market]
case_shiller_fred_id = "SFXRSA"  # optional metro index; omit where FRED has none
hazard_bbox = [-122.55, 37.05, -121.20, 37.95]   # lon_min, lat_min, lon_max, lat_max — for bbox-driven layers

[costs]                          # optional: re-label / override the pack's cost books
year = 2026
label = "SF-Peninsula contractor ranges"
# tour = { panel_replace = [4000, 8000] }
# closing = { attorney = [1500, 4000] }

[[counties]]
name = "San Mateo County"        # MUST equal Redfin's county region name minus ", <ST>"
fips = "081"                     # 3-digit county FIPS
effective_tax_rate = 0.0115      # all-in, incl. typical parcel taxes / bonds; verify against a real bill
assessor_label = "San Mateo County Assessor-County Clerk-Recorder"
assessor_url = "https://www.smcacre.org/"
transfer_tax_note = "County transfer tax customarily paid by the seller; no city transfer tax in the target cities."

[[cities]]
name = "San Mateo"               # as Redfin / Realtor spell it
county = "San Mateo County"      # must name a county above
zips = ["94401", "94402", "94403", "94404"]
# tax_rate = 0.0120              # optional override of the county rate
flags = ["sewer_lateral_pos"]    # pack-interpreted; see §2
```

Rules the loader enforces (`hb/geography.py`, pydantic models with `extra="forbid"`, so an
unknown key anywhere in the file is rejected): ZIP5s, unique across cities and not repeated
within a city, at least one per city; unique county names and unique city names; every city's
county exists; a valid time zone; at least one county and one city; `price_band.max` above
`price_band.min`; `state` two uppercase letters, `state_fips` two digits, a county `fips` three
digits; `effective_tax_rate` and a city `tax_rate` strictly between 0 and 0.1. Everything else in the app derives from these
lists — `settings.target_cities`, `settings.target_zips`, `sibling_zips`, `tax_rate_for`,
`cities_with_flag`, `dfirm_ids` — so adding a city is one `[[cities]]` block.

**Where to find the values.** County FIPS codes: the Census Bureau's county FIPS list.
Effective tax rate: a recent tax bill for a comparable home in the county (assessed value ×
base rate, plus the fixed parcel charges) ÷ purchase price; the number on the bill, not the
statutory 1%. Redfin's county and city names: open
`https://www.redfin.com/county/<id>/…` or grep the Data Center CSV once (`docs/03` §1.1).
Case-Shiller FRED ids: the FRED series search ("Home Price Index (Metro)"). Hazard bbox: a
lon/lat envelope around your counties (any map tool).

## 2. Pack anatomy

```
backend/hb/packs/
  types.py        frozen dataclasses — the records a pack is made of (no hb imports)
  compose.py      override(records, {key: {field: value}}), add(records, *new, after=),
                  without(records, *keys); override_items / add_items / without_items for tour sections
  __init__.py     REGISTRY = {"us": us.PACK, "ca": ca.PACK}; current(); for_geography(geo); validate(pack)
  us/             the base: closing.py, tour.py, prep.py, content.py, sources.py, __init__.py (PACK)
  ca/             California: the same five modules, each composing on us/, plus the Guide
```

A `Pack` carries:

| Field | What it holds | Consumed by |
|---|---|---|
| `closing.contingency` | default investigation / appraisal / loan days + EMD business days + a label | `api/deals.py` (new deals, `/spec` preview), the Closing page |
| `closing.forms` | `{code: Form(code, name, what)}` — plain-English names for form codes | task rows (`form_name`, `form_what`) |
| `closing.phases`, `closing.tasks` | the dated task list; `applies_when` prunes per home | `hb/closing_spec.py`, `deal-deadlines` |
| `closing.costs` | `CostBook(year, label, bands)` for settlement / inspection costs | roll-ups, the Closing page |
| `tour.sections`, `tour.agent_questions`, `tour.cost_bands`, `tour.age_notes` | the walk-through checklist | `hb/tour_spec.py`, the tour panel, `/field`, the brief |
| `prep.phases`, `prep.tasks`, `prep.owners`, `prep.needed_by` | the Get Ready checklist | `hb/prep_spec.py` |
| `content.disclosure_packet`, `content.brief_tax_note`, `content.attorney_phrase` | brief and Closing-page copy | `hb/brief.py`, `/closing` |
| `content.tracker_checklist` | the Tracker's disclosure checklist fields (keys are the storage contract) | `/tracker` |
| `affordability` | optional-peril rider default + label, the reassessment note template (`{amount}`); optional `purchase_tax_rate` + `purchase_tax_note`, the rate a buyer pays where assessments reset at sale and are capped after (owners' averages understate it) | `hb/engine/affordability.py`, `/affordability`; the rate and note: `hb setup` |
| `hazards` | `HazardLayer(key, label, tone, url, query(geo), zone_value(props))` | `hazards-fetch`, `hazards`, `HazardChips` |
| `rating_sources` | `RatingSource(key, label, blurb)`; the first is primary | `hb/schools_match.py`, `SchoolRatings` |
| `guide` | `Guide(doc, section_ids, exclude, phase_map)` or `None` | `GET /api/guide/closing`, the Closing page |

`packs.current()` returns the pack for `settings.geo` with the geography's `[costs]` layered
on, so cost labels are a geography fact and the pack stays state-wide.

### Keys are the contract

Checklist state is JSON keyed on task / item keys: `deals.checklist`,
`property_tours.checklist`, `tracked_listings.disclosure_checklist`, the `prep_checklist`
settings row. So **the same key must mean the same task in every pack**. A state pack
therefore never renames a base task; it

- **overrides fields** on a base task (`compose.override(us.TASKS, {"remove_loan": {"label": …, "why": …, "form": "CR"}})`),
- **removes** base tasks whose state counterpart is a different task (`compose.without(…, "seller_disclosures_read")`), and
- **adds** its own (`compose.add(…, T("tds_read", …))`).

`ca/closing.py` is the worked example: 29 overrides, 8 replacements, 10 extras on a 69-task
base. The composition helpers raise at import on an unknown key, and `test_packs.py` asserts
that `ca`'s keys are the base's plus its declared extras.

### `applies_when`

Closing tasks prune per home on `year_built_before` (lead paint, foundation, chimney),
`financed` (loan tasks), `hoa` / `pool`, and `city_flag` — a flag the geography puts on cities
(`flags = ["sewer_lateral_pos"]`) and the pack interprets (the `ca` pack's `city_pos_report`
task). An unknown fact keeps the task: if the year is unknown, still ask. Tour items prune on
`year_built_before` only.

## 3. Adding a pack

1. `mkdir backend/hb/packs/<key>` with `closing.py`, `tour.py`, `prep.py`, `content.py`,
   `sources.py`, `__init__.py`, each composing on `hb.packs.us` (copy `ca/` and edit the
   dicts). Start from the base task text and change only what your state does differently:
   contingency defaults and whether contingencies expire or must be removed in writing, the
   seller disclosure form(s), the agency disclosure, point-of-sale ordinances, reassessment
   timing and any exemption, insurance structure, named forms. If your state caps
   assessments after a sale resets them, set `Affordability.purchase_tax_rate` and
   `purchase_tax_note` so `hb setup` writes a buyer's rate, not the owners' average.
2. `sources.py`: keep `us.FEMA_FLOOD`; add state hazard layers only if a public ArcGIS REST
   endpoint exists (query by `geo.market.hazard_bbox` or a state attribute). Keep
   `us.SCHOOLDIGGER`; add a state test-score source only if you also write its pipeline (the
   `school-ratings` job is CAASPP / California only and no-ops elsewhere).
3. Register it in `hb/packs/__init__.py` (`REGISTRY["<key>"] = <key>.PACK`).
4. A playbook is optional. If you write one, put it at `docs/packs/<key>/closing-playbook.md`
   with `## N. Title` headings and declare it in the pack's `Guide` (`section_ids` maps
   numbers to stable ids the Closing page links to; `phase_map` lists the sections behind each
   closing phase; `exclude` hides developer sections). `docs/13`, `docs/14` and `docs/15` are
   the `ca` pack's playbooks and stay where they are because a hundred cross-references point
   at them.
5. Run `make test`: `test_packs.py` validates every registered pack (unique keys, known
   phases / forms / cost bands / owners, no bare acronym in a label without its expansion).
6. Point your geography at it (`pack = "<key>"`, or just `state = "<ST>"` when the key is the
   lower-cased state).

A geography in a state with no pack gets the `us` base: a working tracker with the federal
forms (lead paint, Loan Estimate, Closing Disclosure), all six anchors, generic disclosure and
reassessment tasks, FEMA flood only, SchoolDigger ratings, and no in-app guide (the Closing
page says so).

## 4. What stays California-specific on purpose

- `docs/01` (the market primer), `docs/13`–`15` (the playbooks) are written for the Bay Area
  and the `ca` pack, with a banner saying so. They are the worked example of the knowledge to
  gather for another market, not a template.
- `hb pipeline school-ratings` (CAASPP) is California only and records a `noop` elsewhere.
- Everything else — the CMA, overbid model, posture classifier, listing radar, alerts, open
  houses, tours, the closing tracker's date math — is market-agnostic and configured by the
  two layers above.
