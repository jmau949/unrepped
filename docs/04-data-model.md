# 04 — Data Model

SQLite via SQLAlchemy 2.0 declarative models in `backend/hb/db/models.py`; migrations via Alembic. Conventions: TEXT UUID4 PKs (`id`), UTC ISO-8601 TEXT timestamps (`created_at`, `updated_at` where noted), integer dollars for money, REAL for ratios/coordinates. **Every table lists its natural unique key — the UPSERT key that guarantees duplicate-free re-runs.** Pipeline UPSERTs go through the single helper `db/upsert.py`; alert inserts (`alerts/rules.py`, `pipelines/deal_deadlines.py`) use the SQLite dialect's INSERT-or-ignore directly, and API writes are plain ORM adds and updates.

## FK graph (overview)

```
properties ──< listings ──< listing_events
    │             ├──< open_houses
    │             │
    │             └──> listing_groups (via listing_group_id)
    ├──< sales (comps)
    ├──< avm_snapshots
    ├──< cma_runs ──< cma_comps >── sales
    ├──< property_tours (listing_id nullable)
    └──< hazard_flags
listings ──< tracked_listings ──< alerts (nullable FKs)
listings ──< deals ──< contacts (deal_id nullable)
properties ──< deals (property_id)
listings ──< contacts (listing_id nullable)
schools ──< school_rating_snapshots
market_metrics, price_index, rate_snapshots,
buyer_profile, settings, pipeline_runs, preapprovals,
schools, school_districts (no FK to properties — school assignment is a spatial join at read time)   — standalone
```

## Tables

### properties — canonical physical home (entity-resolution target)
| column | type | notes |
|---|---|---|
| id | TEXT PK | uuid4 |
| address_norm | TEXT NOT NULL | scourgify-normalized line1, uppercase (e.g. `123 MAIN ST`) |
| unit | TEXT NOT NULL default `''` | normalized unit, separate from line1; `''` when there is none, so the unique constraint treats "no unit" as one value |
| street, city, state, zip | TEXT | display form; zip = ZIP5; `state` defaults to the geography's |
| lat, lon | REAL NULL | indexed for bbox prefilter |
| beds | INTEGER NULL | |
| baths | REAL NULL | half-baths as .5 |
| sqft, lot_sqft | INTEGER NULL | living area / lot |
| year_built | INTEGER NULL | |
| property_type | TEXT | `single_family` (others tolerated but filtered out of scans) |
| apn | TEXT NULL | assessor parcel number — defined; nothing writes it (there is no assessor feed) |
| assessor_sqft | INTEGER NULL | defined; nothing writes it — the sqft-mismatch flag (05 §8) reads it and stays blank unless the value is filled in by hand |
| condition_tag | TEXT NULL | `renovated` \| `dated` \| `fixer` (user-set, F10) |
| condition_notes | TEXT NULL | free text |
| source_ids | TEXT JSON | `{ "realtor": ["<id>", ...], "redfin": [...], "raw_addresses": [...], "conflicts": [{field, kept, seen} \| {field, kept, replaced}] }` — audit trail for entity resolution (05 §5): `seen` is a disagreeing value that was not applied, `replaced` the value a live listing superseded |
| price_history | TEXT JSON | Realtor.com sale/listing history, lazily fetched and cached (`pipelines/price_history.py`, 05 §14); `[]` = fetched, no history available |
| price_history_fetched_at | TEXT NULL | when `price_history` was last fetched; NULL = never |
| watched_at | TEXT NULL | set = the buyer put this home on the Watchlist (08 §5b): the detail page's Watch button, `POST /api/tracker` (tracking a home watches it, so untracking never drops it), or logging a tour (`POST /api/tours` / a new row from `/api/tours/import`). Watchlist membership = `watched_at` set (`hb/watchlist.py`); **Remove** clears it, and the home's tours and tracker rows are kept |
| created_at, updated_at | TEXT | |

**Unique key**: `(address_norm, zip, unit)` (unit is `''` when absent, never NULL). **Indexes**: `(zip)`, `(lat, lon)`, unique on the key.

### listings — one marketing episode of a property on one source
| column | type | notes |
|---|---|---|
| id | TEXT PK | |
| property_id | TEXT FK→properties NOT NULL | |
| listing_group_id | TEXT FK→listing_groups NULL | set by relist stitcher |
| source | TEXT NOT NULL | `realtor` (`redfin` and `manual` are defined; nothing writes them) |
| source_listing_id | TEXT NOT NULL | MLS/listing id from the source |
| url | TEXT | |
| status | TEXT NOT NULL | `active` \| `pending` \| `sold` \| `delisted` |
| list_price | INTEGER NULL | current |
| original_list_price | INTEGER NULL | first observed list price of this episode |
| list_date, pending_date, sold_date, delist_date | TEXT NULL | |
| sold_price | INTEGER NULL | |
| dom_source | INTEGER NULL | DOM as reported by the source (the gameable number) |
| offer_due_at | TEXT NULL | user-editable (a date input on the detail page, `PATCH /api/listings/{id}`); the scan fills it only from an explicit offer date in the remarks (05 §4). Drives `offer_date_soon` alerts and the posture signal |
| photo_urls | TEXT JSON | source image URLs |
| photo_paths | TEXT JSON | local files under `data/photos/<property_id>/`, relative to DATA_DIR; downloaded per 05 §4.6 |
| raw | TEXT JSON | last raw source record minus the photo-URL blobs already in `photo_urls` (debugging/audit, and the holding pen for source fields we don't model yet — `mls_status` contingency detail, `hoa_fee`, `estimated_value`, description text). The listing side lives here — `agent_name/agent_email/agent_phones/agent_mls_set/agent_nrds_id`, `office_name/office_email/office_phones`, `broker_name`, `builder_name`, `mls` — and is read by `hb/listing_contact.py` for the detail page (07 §Listings). Nested values such as the phone lists are stored as real JSON arrays, never stringified |
| viewed_at | TEXT NULL | when the user opened the detail page in the listing's current status (08 §2b); NULL = unread. Stamped by `GET /api/listings/{id}`, never overwritten while the status holds, and cleared by `listing-scan` on the transition to sold (05 §4.3); backfilled from the property's earliest `cma_runs.created_at` |
| first_seen, last_seen | TEXT NOT NULL | scan bookkeeping |

**Unique key**: `(source, source_listing_id)`. **Indexes**: `(property_id)`, `(status)`, `(listing_group_id)`.

### open_houses — scheduled open houses per listing (05 §4c)
| column | type | notes |
|---|---|---|
| id | TEXT PK | |
| listing_id | TEXT FK→listings NOT NULL | the active listing the slot was matched to on `(source, source_listing_id)` |
| source | TEXT NOT NULL | the first source in `OPEN_HOUSE_SOURCES` order that reported the slot (`realtor` \| `redfin`, names from `hb/open_houses/sources/REGISTRY`) |
| start_at, end_at | TEXT NOT NULL | UTC ISO-8601; the source's local wall-clock time converted at ingest |
| description | TEXT NULL | host / blurb as the source gives it |
| href | TEXT NULL | event or virtual-tour link when the source has one |
| methods | TEXT JSON | `["in_person"]`, `["virtual"]`, or both |
| scheduled_at | TEXT NULL | set = on the buyer's open-house schedule (`PUT/DELETE /api/open-houses/{id}/schedule`) |
| schedule_position | INTEGER NULL | the buyer's visiting order across the schedule (a day reads its slots in this order); set with `scheduled_at` — a new slot goes last — cleared with it, rearranged by `PUT /api/open-houses/schedule/order` |
| cancelled_at | TEXT NULL | set = a scheduled slot the source stopped reporting; cleared if it reappears |
| first_seen, last_seen | TEXT NOT NULL | ingest bookkeeping |

**Unique key**: `(listing_id, start_at)` — one row per slot however many sources report it. **Index**: `(start_at)`. Future slots no source reports any more are deleted by the next clean run (cancelled, or the home went pending) — unless scheduled, in which case they are stamped `cancelled_at` and kept so the schedule can say the visit is off; past slots stay as history. Feeds `ListingSummary.next_open_house` and the Open Houses page (08 §14).

### listing_events — append-only diff log (drives alerts + timeline)
| column | type | notes |
|---|---|---|
| id | TEXT PK | |
| listing_id | TEXT FK→listings NOT NULL | |
| event_type | TEXT NOT NULL | `new` \| `price_change` \| `status_change` \| `pending` \| `back_on_market` \| `delisted` \| `relisted` \| `sold` |
| old_value, new_value | TEXT NULL | stringified (prices as digits) |
| observed_at | TEXT NOT NULL | scan timestamp (one shared timestamp per scan run) |

**Unique key**: `(listing_id, event_type, observed_at, new_value)` — combined with diff-only emission (05 §4.4) this makes event writes idempotent. **Index**: `(listing_id, observed_at)`.

### listing_groups — relist stitching (true cumulative DOM)
| column | type | notes |
|---|---|---|
| id | TEXT PK | |
| property_id | TEXT FK→properties NOT NULL | |
| first_list_date | TEXT | earliest episode start since last sale |
| cumulative_dom | INTEGER | Σ active-span days across member episodes (recomputed by stitcher) |
| episode_count | INTEGER | |
| ended_by | TEXT | `sale` \| `withdrawn` \| `open` |

**Unique key**: none natural — groups are created/merged only by `relist.py`, which is deterministic given the listings table (re-running it rebuilds the same groups; it recomputes rather than appends).

### sales — closed transactions used as comps
| column | type | notes |
|---|---|---|
| id | TEXT PK | |
| property_id | TEXT FK→properties NOT NULL | |
| listing_id | TEXT FK→listings NULL | when the sale came from our own tracked listing |
| sale_date | TEXT NOT NULL | |
| sale_price | INTEGER NOT NULL | |
| list_price_at_sale | INTEGER NULL | final list |
| original_list_price | INTEGER NULL | **SP/LP is always computed against this** |
| sp_lp | REAL NULL | sale_price / original_list_price, precomputed |
| dom | INTEGER NULL | source DOM |
| cumulative_dom | INTEGER NULL | from listing_groups (scan, 05 §4.5) or the replayed Realtor timeline (05 §14) |
| had_price_cut | INTEGER (bool) | feeds fresh/stale overbid split |
| source | TEXT | `realtor_sold_scan` \| `rentcast` (`manual` and `assessor` are defined; nothing writes them) |

**Unique key**: `(property_id, sale_date)`. **Indexes**: `(sale_date)`, and the comps query uses properties' `(zip)`/`(lat,lon)` via join.

**Two writers, one precedence rule.** The scan records what it *observed*; `derive-sales-history` (05 §14) reconstructs what happened before the scan existed. Reconstruction is monotone and never overrides observation: `had_price_cut` only goes False→True, `original_list_price` is only ever *raised* (a stored value below the derived original means observation started mid-campaign, after a cut — and `sp_lp` is recomputed whenever it moves), and `dom`/`cumulative_dom` fill NULLs only. Without this pass every backfilled comp looks "fresh", which silently collapses the overbid model's fresh/stale split (06 §5.2).

### market_metrics — tidy geo time series
`id, geo_type (zip|neighborhood|city|county), geo_id (e.g. '94087' or 'Sunnyvale'), period_start (date), period (monthly|3m|6m|9m|12m — the window length), metric, value REAL, source (redfin|zillow|derived|derived_city; `car` is defined — nothing writes it)`
Metric vocabulary: `median_sale_price, median_list_price, median_ppsf, homes_sold, inventory, new_listings, median_dom, avg_sp_lp, pct_sold_above_list, months_supply, months_supply_live` (Redfin and `market-supply`), plus `zhvi, zori` (source `zillow`, written by `pipelines/zillow_research.py` alongside `price_index`); `median_sp_lp` is defined — nothing writes it.
`source='derived'` marks a value this platform computed rather than ingested; `source='derived_city'` marks one **borrowed from the parent city** because the geo's own sample was too thin (05 §3.5). Both are written only by `market-supply`, and only for `months_supply_live`. Because `source` is part of the unique key, a geo flipping between the two would leave a stale row — that job truncate-and-replaces its own rows rather than upserting alone.
**`period` is the window length.** Redfin ZIP and city rows are rolling 3-month windows (`3m`, labelled by window start); Redfin county rows and Zillow rows are calendar months (`monthly`). `months_supply_live` is stored once per trailing window (`3m` | `6m` | `9m` | `12m`) with every other key column identical, so **always filter on `period` when reading the live series**; Redfin metrics have one series per geo and need no filter. Redfin restates history every release, so `redfin-market` deletes all `source='redfin'` rows for a geo level and reinserts (05 §3.1) — relabeling in place would create duplicate series, since `period` is part of the unique key.
**Unique key**: `(geo_type, geo_id, period_start, period, metric, source)`. **Index**: `(geo_type, geo_id, metric, period_start)`.

### price_index — CMA time-adjustment series
`id, geo_type, geo_id, month (YYYY-MM), index_value REAL, source (zhvi|blend; `redfin_ppsf` is defined — nothing writes it)`
Normalized at read time (latest month = 1.0). **Unique key**: `(geo_type, geo_id, month, source)`. Zillow-sourced rows are truncate-and-replaced wholesale each successful download (03 §1.2).

### avm_snapshots — per-property valuation observations
`id, property_id FK, source (own_cma|realtor_estimate|zestimate|rentcast), value INTEGER, low INTEGER NULL, high INTEGER NULL, as_of TEXT`
**Unique key**: `(property_id, source, as_of)` (as_of = date granularity; one snapshot per source per day).

### cma_runs / cma_comps — persisted CMA workbench state
`cma_runs: id, property_id FK, created_at, params TEXT JSON (radius, months, overrides), estimate INTEGER, low INTEGER, high INTEGER, confidence (low|medium|high), index_source TEXT`
`cma_comps: id, cma_run_id FK, sale_id FK, similarity_score REAL, auto_selected BOOL, included BOOL (user swap state), time_adj_factor REAL, adjustments TEXT JSON ({"time": 38000, "sqft": -42000, "bath": 15000, "condition": 0, ...}), adjusted_price INTEGER`
**Unique key** on cma_comps: `(cma_run_id, sale_id)`. Runs are append-only history (each recompute = new run).

### tracked_listings — the user's pipeline
`id, listing_id FK UNIQUE, stage (saved|toured|disclosures|offer_prep|offered|won|closing|lost|passed), notes TEXT, disclosure_checklist TEXT JSON (keyed on the pack's `tracker_checklist` fields; `ca`: {"packet_received": false, "tds_spq_read": false, "pest_section1_total": null, "nhd_read": false, "hoa_docs": null, "insurance_quoted": false}; `us`: {"packet_received", "seller_disclosure_read", "pest_section1_total", "hoa_docs", "insurance_quoted"}), my_max_bid INTEGER NULL, created_at, updated_at`
**Unique key**: `(listing_id)`. `won` is acceptance; `closing` is the escrow that follows it —
kept as two stages because the work, the clock and the page are different (`deals`, docs/14).
`POST /api/deals` moves a tracked row to `closing` on create.

### property_tours — one visit, the buyer's own observations
`id, property_id FK NOT NULL, listing_id FK NULL, toured_on TEXT NOT NULL (YYYY-MM-DD), kind (open_house|private|drive_by|second_visit), checklist TEXT JSON ({item_key: value}, keys from the pack's tour items (`hb/packs/<key>/tour.py`); `photo:<key>` entries record shot-list ticks), agent_answers TEXT JSON ({question_index: answer}), gut_score INTEGER NULL (1-5), verdict TEXT NULL (offer|maybe|pass), notes TEXT NULL, repair_low INTEGER NULL, repair_high INTEGER NULL, source (app|offline_kit), created_at, updated_at`
**Unique key**: `(property_id, toured_on)`. **Indexes**: `(property_id)`.

Keyed on the **property**, not the listing: a home toured during one marketing episode and
relisted later is the same home and the same tour. Keyed on the **date** rather than a
surrogate so the Field page's save (`POST`→`PATCH`), a re-entered visit and a backup
re-import all land on the existing visit instead of stacking duplicates (`07 §Tours`,
`08 §11`).

`repair_low`/`repair_high` are optional overrides. When NULL, the served `costs` are
derived from `checklist` by `hb.tour_spec.evaluate()` — flagged items map to the pack's `COST_BANDS`,
**deduped by band key** so two findings in one trade are billed once. The API never stores
the roll-up; it is recomputed on read so a spec change reprices old tours (13 §10).

### alerts
`id, type (price_cut|relist|back_on_market|new_comp_sold|offer_date_soon|new_listing_match|watched_status|scan_failure|deal_deadline_soon|deal_deadline_overdue — the ten the code creates; `rate_move` has a seeded rule toggle and nothing writes it), listing_id FK NULL, tracked_listing_id FK NULL, payload TEXT JSON, dedup_key TEXT NOT NULL, created_at, delivered_at TEXT NULL, channel TEXT NULL`
**Unique key**: `(dedup_key)` — construction rules in `09-alerts-spec.md` §3.

### rate_snapshots
`id, date, series (MORTGAGE30US|MORTGAGE15US|CASESHILLER), value REAL` — **unique** `(date, series)`. `CASESHILLER` is the metro index named by `[market].case_shiller_fred_id` in the geography file, absent when none is configured.

### buyer_profile — single row (id fixed = 'default')
`id, cash_available INTEGER, down_payment INTEGER (dollars, not a percentage), rate_assumption REAL NULL (null ⇒ use latest MORTGAGE30US), appraisal_gap_tolerance_pct REAL, insurance_monthly_est INTEGER, include_earthquake_ins BOOL, target_zips TEXT JSON, annual_income INTEGER (gross $/yr; 0 = not entered, payment limit off), monthly_debts INTEGER (other debt payments $/mo), updated_at`

### Property-tax rates — configuration, not a table
Effective rates live in `geography.toml`: `effective_tax_rate` per county (all-in, incl. typical parcel taxes/bonds) and an optional `tax_rate` override per city. `hb/engine/affordability.py` reads them through `settings.geo.tax_rate_for(city)` (city override → county → `DEFAULT_TAX_RATE` 1.25% for a city outside the geography). The packaged example carries San Mateo County 1.15% and Santa Clara County 1.28%, marked as estimates to verify against a real bill. One source of truth per instance, so there is no seeded copy in the DB.

### settings — small JSON key-value store
`key TEXT PK, value TEXT JSON, updated_at`
Known keys: `alert_rules` (rule toggles + thresholds, `09-alerts-spec.md` §2; seeded by data migration), `rentcast_budget` (`{"month": "YYYY-MM", "calls": n}` — the enrich budget guard resets the counter on month rollover, `03-data-sources.md` §3.1), `schooldigger_budget` / `schooldigger_progress` (`05` §13), `prep_checklist` (`{task_key: {done_on, note}}`, keys from the pack's prep tasks (`hb/packs/<key>/prep.py`) — the Get Ready checklist, `docs/15`), `home_location` (`{address, lat, lon}` — the Open Houses distance and route origin; seeded from `HOME_ADDRESS` on first read, then edited on the page, `07` §Open houses), `watchlist_seen` (`{at}` — the buyer's last Watchlist visit, which the page highlights changes against, `07` §Watchlist).

`prep_checklist` lives here rather than in a table on purpose: it is a **single global
checklist**, not per-property and not per-deal — you get pre-approved once, not once per house
— so there is no natural key to build a table on. Created lazily on first PATCH. Roll-up is
recomputed on read like every other checklist in this schema.

### pipeline_runs — job bookkeeping (powers no-op logic + observability)
`id, job TEXT, started_at, finished_at, status (running|ok|noop|partial|failed — `running` is the default, held while the run is open), items_seen INTEGER, items_upserted INTEGER, events_emitted INTEGER, error_summary TEXT NULL, content_hash TEXT NULL (bulk downloads)`
**Index**: `(job, started_at)`.

### deals — one accepted offer, from Acceptance to keys (docs/14)
`id, listing_id FK UNIQUE, property_id FK, accepted_on TEXT (YYYY-MM-DD), purchase_price INTEGER, emd_amount INTEGER, emd_sent_on TEXT NULL, emd_business_days INTEGER, close_of_escrow_on TEXT NULL, investigation_days INTEGER NULL, appraisal_days INTEGER NULL, loan_days INTEGER NULL, financed INTEGER, loan_type TEXT NULL, escrow_company TEXT NULL, escrow_number TEXT NULL, status (open|closed|cancelled), checklist TEXT JSON ({task_key: {done_on, note, waived, due_override}}, keys from the pack's closing tasks (`hb/packs/<key>/closing.py`)), notes TEXT NULL, created_at, updated_at`
**Unique key**: `(listing_id)` — the same key `tracked_listings` uses, so a deal is the
continuation of a tracked row. **Index**: `(status)`.

Keyed on the **listing**, not the property (unlike `property_tours`): a deal belongs to one
marketing episode and one contract. The same home bought in a later episode is a different
transaction with different numbers.

The row stores only what the buyer reads off the contract — **every task date is derived** by
`hb/closing_spec.py` from `accepted_on` plus the three contingency day-counts, so correcting
the acceptance date re-dates the whole transaction. There is deliberately no `deal_tasks`
table: definitions live in the spec, per-task state lives in `checklist`, and adding a task is
a spec edit rather than a migration (same contract as `property_tours`).

**A NULL contingency day-count means WAIVED, not unset.** `closing_spec.anchors()` resolves
that anchor to None, which prunes the removal task *and every task hanging off it*. The RPA
defaults (17/17/21) are applied by the API on create, never by the column, so a deliberate
NULL survives a later PATCH. `PATCH /api/deals/{id}` therefore takes an explicit `waive: []`
list — `None` in a patch body already means "not supplied".

The API never stores the roll-up; `evaluate()` recomputes overdue / due-soon / blocking /
costs on read, so a spec correction reprices an open deal.

### contacts / preapprovals (mini-CRM — contacts adopted as the deal team, docs/14 §1)
`contacts: id, kind (escrow|title|lender|inspector|insurance|attorney|tc|listing_agent|owner|contractor|other), name, deal_id FK NULL, listing_id FK NULL, company TEXT, role TEXT, phone, email, notes`
**Indexes**: `(deal_id)`, `(listing_id)`. `deal_id` set = a member of that deal's roster. `listing_id` set = saved from that listing's detail page before any offer exists (08 §3 1c) — the listing agent reached in week one, the owner of record found on the assessor roll. A deal on that listing lists those rows in its team alongside its own `deal_id` rows and can edit them through the deal routes, but `DELETE /api/deals/{id}` removes only the `deal_id` rows: the listing's contacts outlive the deal. Both NULL = a general contact tied to nothing.
`preapprovals: id, contact_id FK, amount INTEGER, rate REAL, expires_on TEXT, notes` (defined; nothing writes it)

### hazard_flags
`id, property_id FK, hazard (a pack hazard-layer key — `fema_flood` everywhere; the `ca` pack adds `calfire_fhsz`, `liquefaction`, `fault_zone`), zone_value TEXT, checked_at`
**Unique key**: `(property_id, hazard)`.

### schools — public-school directory for the geography's state (NCES CCD, docs/05 §9)
`id, nces_id, name, level (elementary|middle|high), lat, lon, district TEXT (LEA display name), county, zip, leaid TEXT (7-char NCES LEA id — the join key to school_districts.geoid), is_charter INTEGER (charters are not zoned; excluded from assignment), rating INTEGER (CAASPP decile fast-path), pct_met REAL, updated_at`
**Unique key**: `nces_id`. **Indexes**: `(lat, lon)`, `(level)`, `(leaid)`. Not FK-linked to properties — assignment is spatial at read time (docs/05 §12).

### school_districts — NCES TIGER district boundary polygons (docs/05 §12)
`id, geoid TEXT (LEAID), name, kind (elementary|secondary|unified), lo_grade, hi_grade, geometry_json TEXT (GeoJSON), bbox_lat_min/max + bbox_lon_min/max REAL, school_year, updated_at`
**Unique key**: `geoid`. **Index**: bbox columns. ~940 rows for California; point-in-polygon via a process-cached STRtree in `hb/schools_match.py`.

### school_rating_snapshots — per-source school ratings (docs/05 §10, §13)
`id, school_id FK→schools, source (caaspp|schooldigger|greatschools), rating_10 REAL (normalized 1-10 badge scale), label TEXT (source-native, e.g. "#123 of 5,856 in CA"), detail JSON, as_of, updated_at`
**Unique key**: `(school_id, source)` — mirrors the avm_snapshots multi-source pattern; `schools.rating/pct_met` stay as the CAASPP fast-path columns. **Index**: `ix_school_rating_snapshots_school(school_id)`.

## Alembic conventions
- The schema is six migrations in `migrations/versions/`, applied in order by `hb serve`, `hb db upgrade` and every `hb pipeline` / `hb alerts send` / `hb backtest` command (`cli._ready_db`); a fresh clone needs nothing else:
  - `0001_initial` — the whole schema, plus the `buyer_profile` default row and the `alert_rules` settings row (existence-guarded, so re-running is a no-op);
  - `0002_open_house_slot_key` — `open_houses` unique on `(listing_id, start_at)` across sources (duplicate rows already stored for one slot are collapsed first, keeping the scheduled one, else the oldest);
  - `0003_open_house_schedule_position` — `open_houses.schedule_position` (already-scheduled slots numbered soonest first);
  - `0004_watchlist` — `properties.watched_at` / `watch_hidden_at`;
  - `0005_profile_income` — `buyer_profile.annual_income` / `monthly_debts` (NOT NULL, server default 0);
  - `0006_watch_only_watched_at` — Watchlist membership becomes `watched_at` alone: toured, un-hidden homes get it stamped, hidden homes have it cleared, and `watch_hidden_at` is dropped.
- A model change edits `models.py` and adds a hand-reviewed migration on top (autogenerate, then review batch-mode artefacts, JSON types and constraint names): `tests/test_migrations.py::test_migration_matches_models` runs `alembic.autogenerate.compare_metadata` against a DB built by the migrations and fails on any drift.
