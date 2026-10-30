# 02 — Architecture

## 0. System components — what applications exist

The platform is **two codebases** producing **three runtime pieces**, plus the OS scheduler and an embedded database. There is no separate "scraper service" process — the scraper is the same Python package as the backend, invoked as CLI commands by the scheduler.

| # | Component | What it is | How it runs |
|---|---|---|---|
| 1 | **Data scraper / pipelines** | Python CLI (`hb pipeline <job>`) inside the `backend/hb` package: downloads bulk market data, scrapes listings, downloads photos, resolves entities, writes the DB, evaluates alerts | Fired **daily by the OS scheduler** (Task Scheduler / cron); also on-demand from the terminal or via API-triggered enrichment |
| 2 | **Backend API server** | FastAPI app (`hb serve`, port 18800; `uvicorn hb.main:app` on port 8000 in dev): JSON API under `/api`, serves the built UI at `/`, serves downloaded photos at `/photos` | Long-running process (dev: `uvicorn --reload`; otherwise `hb serve` on 18800 under the always-on task or systemd unit) |
| 3 | **Web UI** | React SPA (separate `frontend/` codebase). `vite build` outputs static files; there is **no Node server at runtime** — the API server serves the files, the browser runs the app | In the user's browser |
| 4 | **Scheduler** | The per-user OS schedule `hb schedule install` writes (`backend/hb/schedule_install.py`): Task Scheduler on Windows, launchd on macOS, systemd --user timers on Linux, or a crontab block where there is no systemd user instance — the only thing that "runs" the scraper | OS-level; the Windows branch runs `ops/windows-tasks.ps1`, and `ops/crontab.txt` is the template for installing the cron lines by hand |
| 5 | **Database + file store** | SQLite file `data/hb.sqlite3` (embedded — no DB server) + `data/raw/` download cache + `data/photos/` image store | Opened in-process by components 1 and 2 |

```
                          ┌────────────────────────────────────────────────┐
  Redfin S3 / Zillow CSVs │  [4] Scheduler (Task Scheduler / launchd /      │
  FRED / Realtor.com      │        │     systemd / cron; hourly catch-up)   │
  Redfin GIS / RentCast   │        ▼ 04:00 / 05:00+15:00                   │
        ───────────────►  │  [1] Scraper / pipelines  (hb CLI)             │
         HTTP (1 req/s)   │        │ writes rows, photos, alerts           │
                          │        ▼                                       │
                          │  [5] data/  hb.sqlite3 · raw/ · photos/        │
                          │        ▲ reads/writes                          │
                          │  [2] Backend API (FastAPI :8000)               │
                          │        ▲ /api JSON · / static UI · /photos     │
                          └────────┼───────────────────────────────────────┘
                                   │ HTTP
                          [3] Web UI (React SPA in the browser)
```

Consequences worth stating plainly:
- **Local dev = two terminals**: `uvicorn` (component 2) and `vite dev` (component 3's dev server); the scraper runs whenever invoked.
- Components 1 and 2 share `hb/db`, `hb/engine`, `hb/config` — one Python package, two entry points (`hb.cli` and `hb.main`).
- Killing the API server never affects scraping, and vice versa; they meet only at the SQLite file (WAL mode makes concurrent reader/writer safe).
- The home server (`16`) runs all five pieces unchanged under systemd, and Tailscale on either machine makes them reachable from anywhere (§4–5).

## 1. Stack (decided — do not relitigate per story)

| Layer | Choice | Rationale |
|---|---|---|
| Language | **Python 3.12** everywhere on the backend | HomeHarvest, pandas, usaddress-scourgify, rapidfuzz, scipy, statsmodels, shapely, curl_cffi are all Python; one language for API + pipelines + engines |
| API | **FastAPI + Pydantic v2 + SQLAlchemy 2.0 (sync)** | Typed JSON API, auto OpenAPI docs; sync SQLAlchemy is simpler and plenty fast for one user |
| CLI / jobs | **Typer** — `hb pipeline <job>`, `hb alerts send`, `hb db upgrade` | Jobs as CLI commands are testable, re-runnable, and schedule identically via Task Scheduler, launchd, systemd or cron |
| Package mgmt | **uv** (`backend/pyproject.toml`) | Fast, lockfile, Windows-friendly |
| Frontend | **Vite + React 18 + TypeScript SPA**; TanStack Query + TanStack Router; Tailwind CSS; Recharts (charts); MapLibre GL JS + OSM raster tiles (maps) | Single user, no SEO → no SSR/Next.js. `vite build` output is static files served by FastAPI (one process) |
| Database | **SQLite, WAL mode**, accessed only via SQLAlchemy; migrations via **Alembic** | Tiny scale (27 ZIPs in 12 cities for the packaged geography, thousands of listings, 10–20k sales/yr). Geo = indexed lat/lon bounding-box prefilter + haversine in Python — no PostGIS/SpatiaLite. Postgres escape hatch preserved: no SQLite-only SQL, TEXT UUIDs, UTC ISO timestamps |
| Bulk crunching | **DuckDB** inside pipeline jobs | `read_csv` parses the multi-GB national Redfin CSVs in seconds and filters to target ZIPs before anything touches SQLite |
| Scheduling | **OS scheduler**, installed per user by `hb schedule install` (`backend/hb/schedule_install.py`): Task Scheduler jobs on Windows (through `ops/windows-tasks.ps1`), launchd agents on macOS, systemd `--user` timers on Linux, or a crontab block where there is no systemd user instance (`ops/crontab.txt` is the template); system-level systemd timers on the home server (`ops/linux/`). No APScheduler/Celery | Survives laptop sleep/reboot; in-process schedulers die with the process. Jobs are idempotent so re-runs are always safe |
| HTTP client | **httpx** with a shared retry/backoff wrapper | |
| Notifications | Alerts written to DB first; delivery adapters: server log, desktop toast (`win11toast`, Windows-only adapter), Pushover push, SMTP email (Gmail app password). Channel selection via env | Pushover and email work unchanged on a headless host |
| Packaging | None: the app runs bare under a scheduled task or a systemd unit (`11`, `16`); **local dev runs bare** too (`uvicorn --reload` + `vite dev`) | |

## 2. Repository layout

```
unrepped/
├── .env.example                  # all env vars, documented, no secrets
├── geography.toml                # YOUR geography (gitignored) — written by `make setup`
├── config.mk.example             # per-checkout DEPLOY = local | server for `make deploy` (gitignored copy: config.mk)
├── Makefile                      # install, setup, start, schedule, schedule-remove, load, serve, dev-api, dev-ui, daily, scan,
│                                 #   alerts, test, lint, migrate, build, backfill, build-index, enrich, backtest,
│                                 #   deploy (→ deploy-local | deploy-windows | deploy-server)
├── LICENSE, CONTRIBUTING.md, SECURITY.md
├── AGENTS.md                     # points AI coding agents at CLAUDE.md
├── .github/workflows/ci.yml      # CI: ruff + pytest, then tsc + vite build, on Ubuntu
├── backend/
│   ├── pyproject.toml            # uv-managed
│   ├── alembic.ini
│   └── hb/
│       ├── main.py               # FastAPI app; mounts /api routers; serves ../frontend/dist
│       ├── cli.py                # Typer entry point (`hb`)
│       ├── config.py             # pydantic-settings: env vars; exposes settings.geo
│       ├── geography.py          # Geography model + TOML loader (GEOGRAPHY_FILE → geography.toml → packaged)
│       ├── geographies/          # packaged examples (sf_peninsula.toml)
│       ├── setup_geo.py          # `hb setup`: geography.toml from Census reference files (docs/packs/README.md §1)
│       ├── schedule_install.py   # `hb schedule install|remove`: the per-user OS schedule (Task Scheduler / launchd / systemd --user / cron)
│       ├── scheduler.py          # the hourly catch-up check inside `hb serve` (HB_SERVE_SCHEDULER)
│       ├── us_states.toml        # state FIPS codes + time zones, read only by `hb setup`
│       ├── packs/                # state packs: types, compose helpers, us/ (base), ca/ (docs/packs/README.md)
│       ├── serve.py              # `hb serve`: the API + built SPA on one plain-HTTP listener, 0.0.0.0:HB_HTTP_PORT (18800)
│       ├── geo.py                # haversine distance + bounding-box prefilter (06 §2.1)
│       ├── brief.py              # AI deep-dive brief: everything known about one home as pasteable markdown (13 §9)
│       ├── watchlist.py          # Watchlist membership + what happened to each watched home (08 §5b)
│       ├── schools_match.py      # boundary-aware school assignment: district point-in-polygon over a process-cached STRtree (05 §12)
│       ├── backtest.py           # `hb backtest`: golden backtest, CMA + overbid replayed as of the day before listing (10 §4)
│       ├── open_houses/          # open-house sources, geocoder and day planner (05 §4c)
│       │   ├── geocode.py        # address → coordinates for the distance origin: the Census geocoder behind the `Geocoder` Protocol
│       │   ├── route.py          # day routes: drive legs, suggested order, multi-stop Google Maps URL (pure: no DB, no network)
│       │   └── sources/          # base.py (the source contract), realtor.py (HomeHarvest), redfin.py (stingray GIS via curl_cffi)
│       ├── db/
│       │   ├── engine.py         # engine/session factory; PRAGMA journal_mode=WAL
│       │   ├── models.py         # ALL SQLAlchemy models (see 04-data-model.md)
│       │   ├── upsert.py         # the pipelines' UPSERT helper (§5.2); alert inserts use sqlite.insert directly
│       │   ├── backup.py         # nightly SQLite online backup to data/backups/, 14-day retention
│       │   ├── migrate.py        # programmatic alembic upgrade (`hb db upgrade`, `hb serve`, `cli._ready_db`, tests)
│       │   └── migrations/       # alembic
│       ├── tour_spec.py         # tour checklist engine over the pack's items: pruning, flags, cost roll-up (13)
│       ├── closing_spec.py      # closing task engine over the pack's tasks: date math + roll-up (14)
│       ├── prep_spec.py        # prep checklist engine over the pack's tasks (15)
│       ├── listing_contact.py  # the listing side (agent/office/broker) parsed out of listings.raw (07 §Listings)
│       ├── api/                  # routers: config.py (geography + pack for the UI), guide.py (docs/14 as
│       │                         #   markdown), market.py, listings.py, open_houses.py, contacts.py, cma.py,
│       │                         #   overbid.py, offer.py, tracker.py, watchlist.py, tours.py, deals.py, prep.py,
│       │                         #   affordability.py, alerts.py, compare.py, ops.py
│       ├── pipelines/
│       │   ├── base.py           # job runner: run-log, content-hash no-op, error capture
│       │   ├── schedule.py       # slot-based `--catch-up` check against SCAN_TIMES / DAILY_TIMES (05 §2)
│       │   ├── raw_cache.py      # raw-cache retention: prune dated folders past RAW_KEEP_DAYS (05 §2)
│       │   ├── redfin_market.py  # bulk market CSVs → market_metrics
│       │   ├── zillow_research.py# ZHVI/ZORI CSVs → price_index (truncate-and-replace) + market_metrics zhvi/zori
│       │   ├── fred.py           # rates + Case-Shiller → rate_snapshots
│       │   ├── build_index.py    # blended per-geo monthly price index
│       │   ├── market_supply.py  # `months_supply_live` now-cast from our own listings/sales (05 §3.5)
│       │   ├── listing_scan.py   # twice-daily HomeHarvest scan + diff + events
│       │   ├── listing_text.py   # condition tag + offer date parsed out of the listing remarks (05 §4)
│       │   ├── open_houses.py    # open-house slots from each enabled source onto the scan's listings (05 §4c)
│       │   ├── realtor_gql.py    # shared Realtor.com frontdoor GraphQL client + mpr_id resolution
│       │   ├── enrich.py         # per-property Realtor.com estimate/details/gallery + RentCast AVM (+ optional Zestimate)
│       │   ├── price_history.py  # Realtor.com sale/listing history per property, cached on properties.price_history
│       │   ├── sale_history.py   # `derive-sales-history`: replay cached Realtor timelines onto sales (05 §14)
│       │   ├── backfill_sales.py # one-time historical comp backfill via HomeHarvest (`--months`)
│       │   ├── hazards.py        # point-in-polygon hazard flags over the pack's layers
│       │   ├── hazards_fetch.py  # one-time download of those layers, scoped to the geography
│       │   ├── schools.py        # NCES CCD public-school directory → schools (05 §9)
│       │   ├── school_districts.py # NCES TIGER district polygons → school_districts (05 §12)
│       │   ├── school_ratings.py # CAASPP test-score deciles → schools.rating + snapshots (05 §10; `ca` only)
│       │   ├── schooldigger.py   # SchoolDigger statewide rankings → school_rating_snapshots, day-capped budget (05 §13)
│       │   ├── resolve.py        # address normalization + entity resolution
│       │   ├── relist.py         # listing-group stitching, cumulative DOM
│       │   └── deal_deadlines.py # closing deadline alerts over open deals (05 §15)
│       ├── engine/
│       │   ├── cma.py            # comp selection/scoring/bracketing, estimate
│       │   ├── adjustments.py    # regression + fallback adjustment grid
│       │   ├── price_index.py    # index lookup/interpolation helpers
│       │   ├── stats.py          # weighted-quantile helpers shared by the CMA and the overbid model
│       │   ├── overbid.py        # SP/LP distribution model
│       │   ├── exposure.py       # market exposure: how long, and at what price, a listing has been tested (06 §5.6)
│       │   ├── posture.py        # pricing posture: calibrated probability a listing sells below asking (06 §5.6)
│       │   ├── valuation.py      # blended predicted sale value: CMA_WEIGHT·CMA + the overbid point
│       │   ├── supply.py         # months-of-supply interpretation helpers (06 §9)
│       │   ├── affordability.py  # PITI with the geography's tax rate, PMI, closing costs, pack tax note
│       │   └── offer.py          # back-solver + verdict text
│       ├── alerts/
│       │   ├── rules.py          # rule evaluation over listing_events + market state
│       │   └── channels.py       # log + toast + Pushover + email adapters; delivery loop
│       └── tests/
├── frontend/
│   ├── package.json, vite.config.ts, tsconfig.json   # Tailwind v4 via @tailwindcss/vite — no tailwind.config.js
│   ├── index.html                # Vite entry page: links the tab icons below, theme-color slate-900
│   ├── public/                   # favicon.svg, favicon.ico (32 px), apple-touch-icon.png (180 px): a house
│   │                             #   on slate; sw.js: a self-unregistering service worker, for a browser that
│   │                             #   still has one from whatever ran on this port before (main.tsx also
│   │                             #   unregisters any it finds). Vite copies them to the dist root, served by
│   │                             #   main.py's SPA route
│   └── src/
│       ├── main.tsx              # React root: persisted TanStack Query client + RouterProvider
│       ├── router.tsx            # TanStack Router route table (lazy page components)
│       ├── api/client.ts         # typed fetch client (hand-written types matching 07-api-spec.md)
│       ├── pages/                # Dashboard, Listings, Sold, ListingDetail, Tracker, Watchlist, Compare,
│       │                         #   Affordability, Alerts, Supply, DataLog, Field, Prep, Closing, OpenHouses
│       ├── components/           # shared: Layout, MetricTile, ListingBadges, PostureBadge, HazardChips, SchoolRatings,
│       │                         #   MapView, LazyMapView, CmaMap, CmaWorkbench, AvmSpreadBar, AdjustmentGrid,
│       │                         #   OverbidHistogram, VerdictCard, PhotoGallery, ContactPanel, TourPanel, MoneyInput,
│       │                         #   RateChart, SeriesExplorer, ZipTable,
│       │                         #   MarkdownGuide (the pack's closing playbook from /api/guide/closing)
│       └── lib/                  # formatters (money, pct), config.ts (useConfig/useCities), chartColors.ts (the 8-slot
│                                 #   categorical series palette), clipboard.ts (copy with the plain-http fallback),
│                                 #   tourFlags.ts (`isFlagged`, the `flag_when` interpreter mirrored from hb.tour_spec)
├── backend/data/                 # gitignored — DATA_DIR, created on first run
│   ├── hb.sqlite3
│   ├── backups/                     # nightly DB backups (`hb pipeline daily`, `hb db backup`), 14-day retention
│   ├── raw/<source>/<YYYY-MM-DD>/   # cached raw downloads + .sha256 sidecars
│   └── photos/<property_id>/        # downloaded listing images (05 §4.6), served at /photos
├── ops/
│   ├── crontab.txt               # crontab template: the block `hb schedule install` writes without a systemd user instance (11 §2a)
│   ├── windows-tasks.ps1         # registers the hourly catch-up Task Scheduler jobs (Windows)
│   ├── windows-lan.ps1, serve.ps1 # the always-on "HB API Server" task + LAN firewall rule (Windows)
│   ├── linux/                    # home server: hb.service, hourly pipeline + alerts timers,
│   │                             #   hb.sudoers, install.sh (11 §2b, 16)
│   └── deploy-server.sh          # `make deploy-server`: ship the working tree to the server, restart, health-poll
└── docs/                         # this documentation (16 is the home-server walk-through)
    └── packs/README.md           # the geography file, pack anatomy, and how to add a state pack
```

## 3. Conventions

- **Config**: secrets, paths and knobs via env vars parsed by `pydantic-settings` in `config.py`; `.env` loaded locally. No config in code except defaults. `DATA_DIR` (default `backend/data`; a relative value resolves against `backend/`, never the shell CWD) prefixes the DB path, raw cache and photos.
- **Target geography**: one TOML file validated by `hb/geography.py` — cities (name, county, ZIP5s, optional tax-rate override, pack flags), counties (name as Redfin spells it, 3-digit FIPS, effective tax rate, assessor link, transfer-tax note), `state`/`state_fips`, `timezone`, `[map]` centre/zoom, `[price_band]`, optional `[market]` Case-Shiller FRED id and hazard bbox, optional `[costs]` year/label. Resolution: `GEOGRAPHY_FILE`, then `<repo>/geography.toml` (gitignored), then the packaged example `hb/geographies/<GEOGRAPHY>.toml` (default `sf_peninsula`). Everything geo-scoped reads `settings.geo` (`zip_to_city`, `city_to_county`, `sibling_zips`, `tax_rate_for`, `cities_with_flag`, `dfirm_ids`, …); `settings.target_cities/target_zips/timezone/target_price_*` are read-through views. No city, ZIP, county or state literal lives in code.
- **State packs**: everything that differs by state — contingency defaults, named forms, the closing / tour / prep prose, hazard layers, school-rating sources, the Tracker checklist fields — is data under `hb/packs/<key>/` (`us` base, `ca`), resolved by `hb.packs.current()` from the geography (`pack = "ca"`, else the lower-cased `state`, else `us`) with the geography's `[costs]` overrides layered on. The engines (`closing_spec`, `tour_spec`, `prep_spec`, `brief`) are generic and take the pack as data; task keys are stable across packs because checklist JSON is keyed on them. **No state literal outside `hb/packs/`.** The UI reads the same data from `GET /api/config`. Anatomy and authoring rules: `docs/packs/README.md`.
- **IDs**: TEXT UUID4 primary keys generated in Python. **Timestamps**: UTC ISO-8601 TEXT. **Money**: integer dollars (no floats in storage). **Ratios**: REAL.
- **Idempotency invariant** (platform-wide): every write path is an UPSERT keyed on the natural unique key (`04-data-model.md`); every job may be re-run at any time. See `05-pipelines.md` §1.
- **Windows-specific code** allowed only in `alerts/channels.py` (toast adapter), `schedule_install.py` (the Task Scheduler branch), the Makefile's `deploy-windows` target and `ops/*.ps1`; everything else runs on any OS (`make serve`).
- **Logging**: stdlib `logging`, one line per significant action, job runs summarized in `pipeline_runs` table.
- **Errors in pipelines**: catch per-item, count, continue; fail the run only on total failure (see 05 §1).
- **Frontend/backend contract**: `07-api-spec.md` is authoritative; keep `frontend/src/api/client.ts` types in sync manually.
- **Testing**: pytest; test DB = throwaway SQLite file per test (tmp_path fixture); fixtures with realistic data for the packaged `sf_peninsula` geography, which `conftest.py` pins for every test; `tests/fixtures/geography_tx_minimal.toml` exercises the `us` pack. See `10-testing-strategy.md`.

## 4. Process topology

- **Local dev**: `uvicorn hb.main:app --reload` (port 8000) + `vite dev` (port 5173, proxies `/api` and `/photos` → 8000).
- **Local "production"**: `vite build` → `hb serve` applies migrations, then serves the API + `frontend/dist` at `/` on 18800 (`11-deployment.md`); the per-user OS schedule (`hb schedule install`: Task Scheduler, launchd, systemd `--user` or a crontab block) fires `hb pipeline daily --catch-up` and `hb pipeline listing-scan --catch-up` hourly; each runs only when its slot (04:00; 05:00 and 15:00) has no completed run yet, and the scan runs `open-houses` in its tail (see `05-pipelines.md` §2).
- **Home server** (`11` §2b, `16`): the same `hb serve` under systemd on an always-on Linux host, three systemd timers in place of Task Scheduler, `tailscale serve` terminating HTTPS in front of the plain port; `make deploy` with `DEPLOY = server` ships the working tree over Tailscale SSH.

## 5. Portability rules

1. All config via env vars; no absolute Windows paths anywhere; all file paths derive from `DATA_DIR`.
2. DB access only through SQLAlchemy; no SQLite-only SQL in application code (pipeline UPSERTs use SQLAlchemy's `sqlite.insert().on_conflict_do_update()` isolated in a small helper `db/upsert.py`; the alert inserts in `alerts/rules.py` and `pipelines/deal_deadlines.py` use `sqlite.insert().on_conflict_do_nothing()` directly, so a Postgres variant touches those three modules).
3. Notification channels are adapters behind one interface; toast adapter no-ops on non-Windows.
4. The CLI is the only scheduler interface — anything cron can run, Task Scheduler can run, and vice versa.
