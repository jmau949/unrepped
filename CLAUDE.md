# unrepped — CLAUDE.md

Buyer-side home-buying intelligence platform: a single user runs their own instance for one
metro area. Backend: Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic / SQLite in `backend/hb/`.
Frontend: React + TypeScript (Vite, Tailwind) in `frontend/`. The `docs/` folder is the
authoritative spec — keep it in sync with code changes (data model in `docs/04`, pipelines in
`docs/05`, API in `docs/07`, UI in `docs/08`, geography + packs in `docs/packs/README.md`).
`docs/README.md` is the index of every doc. The README is written for people and stays short;
detail belongs in `docs/`. Personal instructions for your own checkout go in `CLAUDE.local.md`
(gitignored), not here.

## Setups

The app runs in one of two setups, which differ only in where it is served, how it is reached
and what `make deploy` ships to (`docs/11` §1):

- **Local** — `hb serve` on one machine, plain HTTP on 18800, reachable on the LAN; on Windows
  the always-on "HB API Server" scheduled task (`ops/windows-lan.ps1`). `DEPLOY = local`.
- **Tailscale** — reached from anywhere over Tailscale with a real HTTPS certificate from
  `tailscale serve`. Either on your own computer (the local setup plus
  `tailscale serve --bg 18800`, `docs/11` §2c; still `DEPLOY = local`), or on its own Ubuntu
  host under systemd (`ops/linux/`, `docs/16`, `docs/11` §2b; `DEPLOY = server`) via two
  independent optional extras: a VM (isolation; on your own computer or another machine) and
  an alternate always-on machine (always on). The reference build uses both: a VM on Proxmox.

The **Field page** (`/field`, `frontend/src/pages/Field.tsx`, docs/08 §11) is part of both:
it is an ordinary page that captures tours one home at a time, keeping each tap in
`localStorage` and saving it 1.5 s after the last tap.

## Running and deploying

`hb serve` is the run command on every OS: it applies pending migrations, then serves the API
and the built SPA (`frontend/dist`) as **plain HTTP on 18800** (`HB_HTTP_PORT`), bound on
`0.0.0.0`. Every `hb pipeline …` and `hb alerts send` command applies pending migrations too
(`cli._ready_db`), so a fresh clone can `make load` before it has ever served. `hb serve` also
runs the hourly catch-up check itself (`hb/scheduler.py`, `HB_SERVE_SCHEDULER`, default on; off
on the home server, whose systemd timers run the jobs); `needs_run` treats a `running` row
younger than 3 h as served so the two never start the same job twice. Neither half refreshes on its own: **a backend change is invisible until the server
restarts**, and a frontend change is invisible until the SPA is rebuilt (`make build`).

Before calling a change done, run `make lint`, `make test` and `make build` (CI runs the same).
If the checkout serves a running instance, ship the change with `make deploy` from the repo
root (Git Bash on Windows). It deploys to the setup named by `DEPLOY` in the gitignored
`config.mk` (template `config.mk.example`); with it unset, `make deploy` fails and says so.

- **`DEPLOY = server`** → `make deploy-server` (`ops/deploy-server.sh`): rebuilds the SPA,
  streams the working tree to the home server (`HB_SSH`, default `hb@hb`) over Tailscale SSH
  (keeping the server's own `.env` and venv), runs `uv sync`, restarts `hb.service`, then
  polls `<APP_BASE_URL>/api/ops/health` for up to 20 s and fails the target if nothing answers.
- **`DEPLOY = local`** → `make deploy-local`: on Windows, `make deploy-windows` — rebuilds the
  SPA and restarts the "HB API Server" scheduled task (`ops/windows-lan.ps1` → `ops/serve.ps1`
  → `hb serve`), then polls `http://localhost:18800/api/ops/health`; on macOS/Linux, rebuilds
  the SPA and prints the restart step, since no service is reachable from the Makefile.

When the checkout serves an instance, a change is not done until `make deploy` has run
successfully. On macOS/Linux with no `config.mk`: `make build`, then restart whatever runs
`make serve` (`docs/11` §2a).

## Commands (run from repo root; Makefile targets `cd backend` themselves)

- `make install` — `uv sync` + `npm install`
- `make setup` — `hb setup`: asks state, cities, price range and writes `geography.toml`
  (+ `.env` on a first run) from Census reference files (`hb/setup_geo.py`, docs/packs §1)
- `make start` — `make build` + `make load` + `make schedule` + `make serve`, the first run;
  `make schedule` / `make schedule-remove` — `hb schedule install|remove`: the per-user OS
  schedule for the scans (`hb/schedule_install.py`; Task Scheduler / launchd / systemd --user /
  crontab, no admin); `make load` — the
  data load (`hazards-fetch --if-missing`, `daily`, `listing-scan`, each step tolerant of the
  previous one failing); it says up front that a first run takes an hour or more, and the
  jobs log download sizes, each city's fetch and photo progress (docs/05 §3.1, §4, §4.6)
- `make serve` — `hb serve` in the foreground (migrates first)
- `make dev-api` / `make dev-ui` — hot reload while editing: uvicorn on :8000 and Vite on :5173
  (proxies `/api` and `/photos`)
- `make test` — backend pytest (`cd backend && uv run pytest`); `make lint` — ruff
- `make build` — frontend typecheck + Vite build (`tsc -b && vite build`)
- `make deploy` — the target `DEPLOY` in `config.mk` names (see above); `make deploy-server`
  — build the SPA, ship the tree to the home server, restart it; `make deploy-local` /
  `make deploy-windows` — build the SPA + restart the Windows LAN task
- `make daily` / `make scan` / `make alerts` — pipeline meta-jobs; `hb pipeline daily` ends by
  taking the nightly DB backup (`data/backups/`, 14-day retention) and pruning the raw cache
- `make backfill` (`hb pipeline backfill-sales --months $(MONTHS)`, default 24),
  `make build-index` (`hb pipeline build-index`), `make enrich` (`hb pipeline enrich
  --all-tracked`), `make backtest` (`hb backtest --n 20`, docs/10 §4)
- `cd backend && uv run hb pipeline <name>` — run one pipeline
  (registry: `backend/hb/pipelines/__init__.py` `JOBS` / `DAILY_SEQUENCE`; not in the daily
  sequence: the scheduled `listing-scan` (which ends with `open-houses`) and the standalone
  `hazards-fetch`, `school-ratings`, `price-history`, `derive-sales-history`,
  `backfill-sales`, `enrich`, `open-houses`)
- `make migrate` / `cd backend && uv run hb db upgrade` — apply migrations by hand;
  `cd backend && uv run hb db backup` — back up the DB by hand (same file and retention as
  the nightly one)

If `uv run` fails to replace `backend/.venv/Scripts/hb.exe` after a `pyproject.toml` change,
the running server holds it: use `uv run --no-sync` until the next `make deploy-windows` (which
syncs while the server is stopped). The scheduled tasks always run `uv run --no-sync … --catch-up`
hourly for exactly this reason (`ops/windows-tasks.ps1`, docs/05 §2).

## Geography and state packs (the rules that keep this US-generic)

- **No city, ZIP, county or state literal in code.** Geography comes from `geography.toml`
  (`GEOGRAPHY_FILE` → `<repo>/geography.toml` → packaged `hb/geographies/<GEOGRAPHY>.toml`,
  default `sf_peninsula`) via `settings.geo` (`city_names`, `zips`, `sibling_zips`,
  `tax_rate_for`, `cities_with_flag`, `dfirm_ids`, `state`, `state_fips`, …);
  `settings.target_cities/target_zips/timezone/target_price_*` are read-through views.
- **Everything that differs by state is pack data** under `hb/packs/<key>/` (`us` base, `ca`),
  resolved by `hb.packs.current()`: contingency defaults, forms, the closing / tour / prep
  prose, hazard layers, school-rating sources, the Tracker checklist fields.
  The engines (`closing_spec`, `tour_spec`, `prep_spec`, `brief`) are generic. State packs
  compose on `us` with `hb/packs/compose.py` and **never rename a task key** — checklist JSON
  is keyed on them. `test_packs.py` asserts the `us` base has no California wording.
- The frontend learns all of this from `GET /api/config` (`lib/config.ts` → `useConfig()`),
  never from literals; hazard/rating colours are a fixed `tone → class` map because Tailwind
  cannot see API strings.
- **`docs/14-closing-playbook.md` is a runtime asset**: `GET /api/guide/closing` serves it to
  the Closing page, split on `## N.` headings (ids in `hb/packs/ca/__init__.py` `GUIDE`). An
  edit there changes the running app; keep the headings numbered and §15 last.
- Tests pin the packaged `sf_peninsula` geography (`conftest.py` autouse); use
  `tests/fixtures/geography_tx_minimal.toml` to exercise the `us` pack.

## Key facts / gotchas

- **Live DB — check `DEPLOY` in `config.mk` first**, before reading or writing any data:
  - **`DEPLOY = server`**: the live data is on the **home server** (`HB_SSH`, default
    `hb@hb`), not this machine: `/srv/hb/data/hb.sqlite3` (`DATA_DIR=/srv/hb/data`; photos
    and the raw cache are beside it). A local `backend/data/hb.sqlite3`, if any, is a stale
    copy — never read it as current and never write to it. Query over Tailscale SSH, read-only:
    `ssh hb@hb 'sqlite3 -readonly /srv/hb/data/hb.sqlite3 "<SQL>"'`, or app code /
    the CLI via `ssh hb@hb 'cd /srv/hb/app/backend && ~/.local/bin/uv run --no-sync <cmd>'`
    (`python -c …`, `hb pipeline <name>`). For heavy analysis pull a fresh snapshot:
    `ssh hb@hb 'sqlite3 /srv/hb/data/hb.sqlite3 ".backup /tmp/hb-snap.sqlite3"'` then
    `scp hb@hb:/tmp/hb-snap.sqlite3 <scratch path>` — reads only; every write (pipelines,
    notes, favorites, `make daily`/`scan`/`alerts`) runs on the server, since a local write is
    lost. The server runs the pipelines itself on systemd timers.
  - **otherwise** (`local`, or no `config.mk`): `backend/data/hb.sqlite3` on this machine
    (`DATA_DIR` defaults to `backend/data`; a relative value resolves against `backend/`,
    never the shell CWD).

- **Secrets**: repo-root `.env` (gitignored); template `.env.example`. Settings in
  `backend/hb/config.py` (pydantic-settings). The geography is **not** in `.env` — it is the
  TOML above.
- **Pipelines**: every job runs inside `JobRunner` (`backend/hb/pipelines/base.py`)
  — one `pipeline_runs` row per run, per-item error tolerance, content-hash
  `noop` for unchanged upstream data. Jobs in `DAILY_SEQUENCE` must be
  daily-safe (hash-noop or self-pacing). Pipeline writes go through
  `backend/hb/db/upsert.py` keyed on each table's natural unique key (alert inserts use
  `sqlite.insert` INSERT-or-ignore on `dedup_key` directly).
- **Tests**: no network — pipelines expose a `fetch_*` seam that tests
  monkeypatch. Follow the existing test style in `backend/hb/tests/`. Fixture people,
  phones, emails and addresses are fictional (`example.com`, `555-01xx`); keep them so.
- **Schools**: houses get schools via district-boundary point-in-polygon
  (`backend/hb/schools_match.py`, NCES polygons in `school_districts`), NOT
  nearest-distance; `schools.leaid` ↔ `school_districts.geoid` is the join
  key (never join on district name strings). Ratings are multi-source in
  `school_rating_snapshots`, ordered by the pack's `rating_sources` (CAASPP first in `ca`;
  the CAASPP job no-ops outside California).
- **Hazards**: `hb pipeline hazards-fetch` downloads the pack's polygon layers once (FEMA by
  DFIRM id from the geography's counties; the `ca` pack's CAL FIRE / CGS layers by
  `[market].hazard_bbox`); `hazards` runs daily over the files.
- **Metered APIs**: budget guards persist in the `settings` table (RentCast
  monthly; SchoolDigger is hard-capped at 20 calls/DAY on the free plan and
  converges across daily runs — don't burn its quota with ad-hoc test calls).
- **NCES ArcGIS layers** pad empty attributes with a single space — always
  `.strip()` before truthiness checks.
- **Redfin Data Center CSVs** (`redfin_data_center/property_types/monthly/`
  `all_{zips,cities,counties}.csv`; the old `redfin_market_tracker/*.tsv000.gz`
  objects froze at May 2026): ZIP and city rows are **rolling 3-month windows**
  (`period='3m'`, labelled by window *start*), so their `homes_sold` is a
  3-month total — divide by 3 for any monthly rate; county rows are calendar
  months (`period='monthly'`). Redfin publishes `months_of_supply` for ZIPs
  directly; there is no price-drops column at all. Ratio columns arrive in
  percent and are stored as fractions. History is restated every release, so
  `redfin-market` truncate-and-replaces `source='redfin'` per geo level, and it
  no-ops on the S3 objects' ETags (plus the target ZIP/city lists) without
  downloading the ~5.5 GB. County names in `geography.toml` must match Redfin's region
  names minus `, <ST>`; a configured region with zero CSV matches is logged.
- **Raw download cache** (`data/raw/<source>/<YYYY-MM-DD>/`): pruned to `RAW_KEEP_DAYS`
  (default 90; 0 keeps all) at the tail of `hb pipeline daily` and by `hb prune-raw`. Only
  date-named folders are candidates; the undated `data/raw/hazards/` is read by the daily
  `hazards` job and never pruned.
- **Live months of supply** (`months_supply_live`) is stored once per trailing
  window, `period` = `3m|6m|9m|12m` — always filter on `period` when reading it.
- **Migrations**: TEXT UUID PKs, ISO-8601 TEXT timestamps, integer dollars. The schema is six
  migrations in `backend/hb/db/migrations/versions/` (`0001_initial` — the whole schema plus the
  default buyer profile and alert rules; `0002_open_house_slot_key` — open-house slots unique on
  `(listing_id, start_at)`; `0003_open_house_schedule_position` — `schedule_position`;
  `0004_watchlist` — `properties.watched_at` / `watch_hidden_at`; `0005_profile_income` —
  `buyer_profile.annual_income` / `monthly_debts`; `0006_watch_only_watched_at` — drops
  `watch_hidden_at`, Watchlist membership is `watched_at` alone); a model change edits `models.py` and adds a
  hand-reviewed migration on top, and `test_migrations.py::test_migration_matches_models` fails
  on any drift.
- **Alert channels**: `log` (every OS), `toast` (Windows only), `pushover` (phone push;
  `_pushover_post` in `alerts/channels.py` is the test seam), `email` (SMTP); default
  `toast,log`. An alert is delivered once any channel succeeds and `log` always succeeds,
  so a headless server runs `pushover` or `email` alone. One toast / push per alert; email
  alone digests above `DIGEST_THRESHOLD` (3). `deliver_pending` commits per alert: a toast
  blocks until dismissed, and the SQLite write lock must not wait on it. A first scan
  creates no alerts (docs/09 §1).
