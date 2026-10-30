# 11 — Deployment

## 1. Run it (any OS)
```
make install                                           # uv sync + npm install
make setup                                             # state, cities, price range -> geography.toml (+ .env)
make start                                             # = make build (SPA) + make load (data) + make schedule + make serve → http://localhost:18800
```
`make load` is the first data load and a manual refresh: `hb pipeline hazards-fetch --if-missing` (the pack's hazard polygons for your counties, fetched only when not on disk yet; first, because the daily `hazards` job reads them), `hb pipeline daily` (Redfin CSVs ~5.5 GB, cached in `backend/data/raw`), then `hb pipeline listing-scan`. Each step runs even if the one before it failed, so one unreachable source does not leave the app empty. The scan's photo tail is the slow part of a first run: four downloads at a time from the image CDN, each with a 0.3–0.6 s pause, and a city with 500 homes for sale has around 15,000 photos, so **allow about an hour for a first run**. It is never silent about it: `make load` prints up front that a first run takes an hour or more, each bulk download logs its size and its progress every 512 MiB (`JobRunner.download_to_raw`), `redfin-market` says how many files and how many GB it is about to fetch, a first scan (no completed `listing-scan` run yet) announces itself with the cities and a rough duration, every scan logs each city's fetch as it starts, and the photo tail says how many files are coming with a rough time, then logs its progress and remaining time every 200 photos. `make serve` in a second terminal opens the app on what is loaded so far (WAL + `busy_timeout` let the two share the database). `make start` runs `build`, `load`, `schedule` and `serve` in that order — the SPA first, so `make serve` in a second terminal works while the load runs, and the OS schedule after the load so its first hourly tick finds today's slots already served; later, `make serve` alone starts the app without the refresh (and builds the SPA itself if it has never been built).
`hb serve` (what `make serve` runs) and every `hb pipeline …` / `hb alerts send` command apply pending migrations first (`cli._ready_db` → `db.migrate.ensure_schema`; one query when already at head), so an empty database is created and seeded by whichever runs first — `make load` on a fresh clone included; `/api/ops/health` reports `db: "unmigrated"` if the API is ever started another way against an empty file. Port: plain HTTP on 18800, bound on `0.0.0.0`; override with `HB_HTTP_PORT`.

Setup notes:

- **Geography**: `geography.toml` is yours and gitignored. `make setup` (`hb setup`) writes it from your state, cities and price range, filling ZIPs, counties, FIPS codes, tax rates, time zone and map from Census reference files (~75 MB, downloaded once to `data/raw/census/`); it also creates `.env` from `.env.example` on a first run and offers to save a FRED key. Re-run it to change the area; `hb setup --state TX --cities "Austin, Round Rock" --price 500k-800k --yes` asks nothing. `docs/packs/README.md` §1 documents every field and where to check the values by hand. With no `geography.toml` the app runs on the packaged SF Peninsula example, and `hb serve` and `hb pipeline daily` print a note saying so.
- **State pack**: picked by `pack = "ca"` or your `state`; a state without a pack gets the generic `us` base. See `docs/packs/README.md`.
- **API keys** (`docs/12`): everything core works with none. `FRED_API_KEY` (free) adds live mortgage rates (without it the `fred` job records a `noop` and affordability assumes 6.5%); `RENTCAST_API_KEY` adds a second AVM under a monthly budget guard; `SCHOOLDIGGER_APP_ID/KEY` (free, 20 calls/day) add school rankings. Alerts default to `toast,log` (`ALERT_CHANNELS`): `log` writes one line per alert to the server log on every OS, `toast` is Windows-only, `pushover` needs a Pushover app token and user key, `email` needs SMTP.
- **Disk**: the Redfin CSVs are ~5.5 GB per release, cached under `backend/data/raw/` in dated folders that are pruned after `RAW_KEEP_DAYS` (default 90); the SQLite DB is ~100 MB after a few months; photos are optional (`SAVE_PHOTOS`).
- **Schedule**: `make start` ends with `make schedule` (`hb schedule install`), which makes the OS run the three commands hourly as the current user (`hb pipeline daily --catch-up`, `hb pipeline listing-scan --catch-up`, `hb alerts send`; `--catch-up` runs a job only when its 04:00 / 05:00+15:00 slot has no completed run yet): Task Scheduler via `ops/windows-tasks.ps1`, launchd agents on macOS, systemd `--user` timers or a crontab block on Linux (05 §2). No administrator step; `make schedule-remove` undoes it; rerun after moving the checkout. The launchd, systemd `--user` and crontab variants write each job's output to `DATA_DIR/logs/hb-<job>.log` (`schedule_install.logs_dir`); the Windows tasks run headless through `conhost.exe` and keep no log file. `hb serve` also runs the same hourly check in-process while it is up (`HB_SERVE_SCHEDULER`, default on). The home server uses the system-level timers in `ops/linux/` with the in-process check off.

Hot-reload while editing code:
```
cd backend && uv run uvicorn hb.main:app --reload --port 8000      # make dev-api
cd frontend && npm run dev                                         # make dev-ui: 5173, proxies /api → 8000
```
Makefile targets: `make install`, `make setup`, `make start`, `make schedule`, `make schedule-remove`, `make load`, `make serve`, `make dev-api`, `make dev-ui`, `make daily`, `make scan`, `make alerts`, `make test`, `make lint`, `make migrate`, `make build`, `make backfill`, `make build-index`, `make enrich`, `make backtest`, `make deploy-local`, `make deploy-windows` (§2), `make deploy-server` (§2b), and `make deploy`, which runs `deploy-$(DEPLOY)` from the gitignored `config.mk` (template `config.mk.example`): `DEPLOY = local` for the machine the checkout runs on (`deploy-local` is `deploy-windows` on Windows; on macOS/Linux it rebuilds the SPA and prints the restart step), `server` for the home server; unset or anything else, it fails with instructions. `HB_SSH` in the same file overrides the home server's SSH target (default `hb@hb`).

**Choosing a setup.** One codebase, two ways to run it, and nothing about either is a branch:

| | **Local** | **Tailscale** |
|---|---|---|
| Use it when | the app is used at home only | the app should open on your phone anywhere — cellular, an open house |
| Open it from | that computer, and devices on the same home network | any of your devices, anywhere |
| Runs on | your computer (§2 Windows, §2a macOS/Linux) | your computer (§2c) |
| Setup | none | a free Tailscale account and two commands |
| Benefits | simplest | HTTPS with a real certificate; nothing opened on the router |
| Drawbacks | home network only; off when the computer is off | off when the computer is off; scans and alerts catch up when it wakes |
| Security | plain http on the LAN; the app runs as you, beside your files | only your devices and anyone you share the machine with reach it; the app still runs as you, beside your files; restrict sharing to port 443 (§2c) |
| `DEPLOY` in `config.mk` | `local` | `local` |

Two independent extras build on Tailscale (§2b, `docs/16`); use either, both or neither:

| Extra | Gives you | Runs on | `DEPLOY` |
|---|---|---|---|
| **A VM** | the app isolated from your computer's files and the LAN: a compromise stays in the VM (`docs/16` §4.4, plus A.3 at a hypervisor) | your own computer (Hyper-V, VirtualBox, UTM) or an alternate machine | `server` |
| **An alternate machine** | always on: scans and alerts on time while your computer is off | any always-on x86 machine, the app installed directly or in a VM | `server` |

Field, alerts and every page behave the same in all of them; only where the server runs and how it is reached differ. Nothing needs `config.mk` until the app should stay up on its own.

### Commands

All `make` targets run from the repo root and wrap `uv`/`npm` (the Makefile does its own `cd backend`); the `hb` CLI is what the scheduler invokes.

| Command | What it does |
|---|---|
| `make install` | `uv sync` + `npm install` |
| `make setup` | `hb setup`: state, cities and price range → `geography.toml` (+ `.env` on a first run) from Census reference files (`docs/packs/README.md` §1) |
| `make start` | `make build`, `make load`, `make schedule`, then `make serve` — the first run and a refresh-then-serve later |
| `make load` | the data load: `hb pipeline hazards-fetch --if-missing`, `hb pipeline daily`, `hb pipeline listing-scan`, each step tolerant of the previous one failing |
| `make schedule` / `make schedule-remove` | `hb schedule install` / `remove`: the per-user OS schedule for the scans (Task Scheduler, launchd, systemd `--user` or crontab); `make start` runs `schedule` after `load` |
| `make serve` | `hb serve`: apply migrations, then serve the API + built SPA as plain HTTP on 18800 (`HB_HTTP_PORT`) |
| `make build` / `make test` / `make lint` | frontend typecheck + Vite build / backend pytest / ruff |
| `make daily` / `make scan` / `make alerts` | the scheduled meta-jobs (`scan` also refreshes open houses in its tail; `hb pipeline open-houses` reruns just that) |
| `make backfill [MONTHS=24]`, `make build-index`, `make enrich` | one-time historical comp backfill, price-index rebuild, AVM refresh |
| `make backtest` | golden CMA/overbid backtest (docs/10 §4) |
| `make deploy` | Run the deploy target named by `DEPLOY` in `config.mk` (`local` or `server`; Choosing a setup above) |
| `make deploy-local` | Windows: `make deploy-windows`. macOS/Linux: rebuild the SPA and remind you to restart the service |
| `make deploy-server` | Home server: rebuild the SPA, ship the working tree over Tailscale SSH to `HB_SSH` (default `hb@hb`), restart it and poll its health (`docs/16` §7, §2b) |
| `make deploy-windows` | Windows only: rebuild the SPA and restart the always-on "HB API Server" task (§2) |
| `make dev-api` / `make dev-ui` | hot-reload while editing code: uvicorn `--reload` on :8000, Vite on :5173 (proxies `/api` + `/photos` → :8000) |
| `hb db upgrade` / `hb db backup` | apply migrations by hand / snapshot the DB (14-day retention) |
| `hb pipeline <job>` | run one ingestion job — `hb pipeline --help` lists them; the registry (`JOBS` / `DAILY_SEQUENCE`) is `backend/hb/pipelines/__init__.py`. `hazards-fetch` and `school-ratings` (CAASPP, California only) are standalone |
| `hb alerts send` | deliver undelivered alerts (log/toast/pushover/email) |

## 2. Always-on on a Windows box
1. `npm run build` → `frontend/dist`; FastAPI serves it at `/` (SPA fallback to index.html); a request path is resolved and served only if it stays inside `frontend/dist`, so `..` or an absolute path can never reach other files on the host.
2. `ops/windows-tasks.ps1` registers Task Scheduler jobs, each firing **hourly** and 10 min after logon (05 §2 — `--catch-up` runs a job only when its latest slot has no completed run, so missed slots are retried within the hour):
   - `uv run --no-sync hb pipeline daily --catch-up` (slot `DAILY_TIMES`, 04:00)
   - `uv run --no-sync hb pipeline listing-scan --catch-up` (slots `SCAN_TIMES`, 05:00 + 15:00)
   - `uv run --no-sync hb alerts send` (hourly at :30)

   `--no-sync` because a syncing `uv run` rewrites `.venv\Scripts\hb.exe`, which the always-on server holds open — after a `pyproject.toml`/`uv.lock` change every task would exit 2 before `hb` starts. `make deploy-windows` runs `uv sync` while the server is stopped; it fails loudly if a pipeline run is holding `hb.exe` (rerun once it finishes). Each action is launched through `conhost.exe --headless`, so the hourly runs open no terminal window; they still run in the user's session, which the `toast` channel needs. Re-run `ops/windows-tasks.ps1` after changing it.
3. Backups: nightly copy of `data/hb.sqlite3` to `data/backups/` keeping 14 days (part of the `daily` command tail; simple file copy is safe under WAL with `sqlite3 .backup` semantics via Python's `sqlite3.Connection.backup`). The same tail prunes the raw download cache: dated `data/raw/<source>/<YYYY-MM-DD>/` folders older than `RAW_KEEP_DAYS` (default 90) are deleted (05 §2); `hb prune-raw` runs that step by hand.
4. LAN access: `ops/windows-lan.ps1` registers the "HB API Server" task (at logon → `ops/serve.ps1` → `hb serve`, plain HTTP on 18800 bound to `0.0.0.0`) and opens a firewall rule for that port scoped to **`Private` profile + `LocalSubnet`** — nothing is reachable off the LAN, and the router must never port-forward/UPnP it. One process, one event loop, one engine (a second uvicorn process would mean two SQLite writers). The task never reloads Python — `make deploy-windows` (`make deploy` with `DEPLOY = local`) is the only way a backend change takes effect; its health poll on 18800 is the gate.

From another device on the wifi: `http://<pc-name>.local:18800` — the mDNS name, which Windows advertises automatically and Windows/macOS/iOS/Android 12+ all resolve. (Bare `http://<PC-NAME>:18800` also works Windows-to-Windows; the computer's IP is the fallback if a device resolves neither.) The Vite dev server (`make dev-ui`) stays localhost-only; other devices use the built SPA. The port is outside the common dev range, so it never collides with `make dev-api` (8000) or other tools.

**Securing the LAN server.** The app has no authentication (`SECURITY.md`), so the network boundary is the boundary. Two lessons from running it: scope the firewall rule to the port, `LocalSubnet` and the `Private` profile only (what `ops/windows-lan.ps1` does — never a blanket allow for `python.exe`), and never click "Allow" on the Windows Firewall popup that appears when a new listener binds, because that creates a rule with no address scope. Treat a change of Wi-Fi network as a reason to re-check the rule, and never add a router port-forward or UPnP entry for the port.

## 2a. Always-on on macOS / Linux
There is no `deploy-windows` equivalent: run `make build`, then keep `make serve` (or `cd backend && uv run hb serve`) running under launchd or a systemd `--user` service. The three scan commands are scheduled by `make schedule` (what `make start` runs): launchd agents on macOS, systemd `--user` timers on Linux, or a crontab block where there is no systemd user instance — hourly `hb pipeline daily --catch-up` and `hb pipeline listing-scan --catch-up`, hourly at :30 `hb alerts send`, all via `uv run --no-sync` with the paths filled in and each job's output appended to `DATA_DIR/logs/hb-<job>.log` (`ops/crontab.txt` is the same as a hand template; run `uv sync` yourself after a dependency change). User timers and agents run while you are logged in; on Linux `loginctl enable-linger $USER` keeps the timers running after logout. After a code change, rebuild the SPA and restart the service: `make deploy` with `DEPLOY = local` does the rebuild and prints the restart reminder, since there is no service the Makefile can restart here. Alerts: `toast` is Windows-only, so leave `log` in `ALERT_CHANNELS` (the default) or configure `pushover` (phone push) or `email` — and run that one channel alone, since `log` always succeeds and would mark a failed push delivered (09 §4).

## 2b. Tailscale extras: a VM, an alternate machine, or both
Both extras run the app on its own Ubuntu Server host (`hb`) — a VM (on your own computer or another machine), an alternate always-on machine, or a VM on an alternate machine (x86 recommended; untested on ARM) — with Tailscale for access from your devices. The walk-through from a blank box to the first deploy (host prep, tailnet policy, install, moving data, backups, restore test) is `docs/16`; the reference build, Proxmox VE on a small x86 PC with the app in one VM, is its appendix. This section is the part the repo itself implements.

**Layout on the server.** The tree lives at `/srv/hb/app`; `DATA_DIR=/srv/hb/data`. Optionally a second disk is mounted at `/srv/hb/bulk` and bind-mounted onto `data/raw` and `data/photos`, so the app sees one tree while everything that grows sits on a disk a host backup can skip (`docs/16` §4.2); without one the two are plain directories. The server's own `.env` (`/srv/hb/app/.env`, mode 600) sets `DATA_DIR=/srv/hb/data`, `HB_HTTP_PORT=18800`, `HB_SERVE_SCHEDULER=false` (the timers run the jobs; `hb.service` sets it too), `APP_BASE_URL=https://hb.<tailnet>.ts.net` and `ALERT_CHANNELS=pushover` (alone, §2a) plus the API keys; `.env.example` lists them as comments.

**Front door.** `hb serve` still listens on plain HTTP 18800 bound on `0.0.0.0`; `tailscale serve --bg 18800` terminates HTTPS with the tailnet's Let's Encrypt certificate and proxies to it. The host's ufw admits only `tailscale0`, and the tailnet policy grants port 443 on `tag:hb` to the tailnet's members and to anyone the machine is shared with (`autogroup:shared`), port 22 and Tailscale SSH as `hb` to your own login alone, and the server itself nothing, so the plain port is never reachable from the LAN or the tailnet directly. The phone uses the same front door for everything, including the Field page (`/field`, docs/08 §11) at the open house.

**systemd units** (`ops/linux/`, installed by `sudo bash ops/linux/install.sh`, idempotent):

| Unit | Runs | When |
|---|---|---|
| `hb.service` | `uv run --no-sync hb serve` | always; `Restart=always` |
| `hb-daily.service` / `.timer` | `hb pipeline daily --catch-up` | hourly at :00 |
| `hb-scan.service` / `.timer` | `hb pipeline listing-scan --catch-up` | hourly at :00 |
| `hb-alerts.service` / `.timer` | `hb alerts send` | hourly at :30 |

The three pipeline timers mirror `ops/windows-tasks.ps1`: same commands, same slots, `--catch-up` so a missed slot runs within the hour, plus `Persistent=true` so a slot missed while the host was off fires at boot. Everything runs as user `hb` from `/srv/hb/app/backend`, calling `/home/hb/.local/bin/uv`. Units that write data carry `RequiresMountsFor=` the two bind mounts: with the second disk missing they stay down rather than fill the empty mountpoints on the system disk. On a host without a second disk the two paths are plain directories, the requirement resolves to the root filesystem's mount, and the units start normally.

`install.sh` also installs `hb.sudoers` as `/etc/sudoers.d/hb` (checked with `visudo` first), which lets `hb` run exactly `systemctl stop|start|restart hb` without a password. It enables `hb.service` only. The three timers are enabled by hand (`sudo systemctl enable --now hb-daily.timer hb-scan.timer hb-alerts.timer`): right away on a fresh install, or once any existing data has moved (`docs/16` §8), because a pipeline run before then writes into the fresh database the move replaces.

**Deploy.** `make deploy` with `DEPLOY = server` (`make deploy-server`) runs `ops/deploy-server.sh` from the machine you develop on (Git Bash on Windows; any POSIX shell with `tar`, `ssh`, `curl`):
1. `npm run build` locally; the server has no Node.
2. Streams the working tree over Tailscale SSH (`hb@hb`; `HB_SSH` in `config.mk` or the environment overrides) into a fresh `/srv/hb/app.new`, excluding `.env`, `.git`, `backend/data`, `data`, `node_modules`, `.venv`, the Python caches, `.claude`, `home-server.local.md`, `CLAUDE.local.md` and `config.mk`. The built `frontend/dist` rides along. A repo-root `geography.toml` ships with the tree, so the two copies always match.
3. On the server, moves its own `.env` and `backend/.venv` into `app.new` and swaps it into place, so a file deleted or renamed in your checkout never lingers (a stale migration file would give alembic two heads). It refuses to run if the server has no `.env` yet.
4. `uv sync`, then `sudo -n systemctl restart hb`. On Linux a running process does not lock the venv, so syncing under it is safe.
5. Reads `APP_BASE_URL` from the server's `.env` and polls `<APP_BASE_URL>/api/ops/health` through the `tailscale serve` front door for up to 20 s; the target fails if nothing answers.

The tar ships the working tree byte for byte, so `.gitattributes` keeps `*.sh` and `ops/linux/**` LF on Windows checkouts: bash, systemd and sudo reject CRLF.

## 2c. Tailscale on your own computer
The local setup (§2 or §2a) plus Tailscale, so the same app on the same computer opens from your phone anywhere — cellular, an open house — over HTTPS. No second machine, no router change, nothing exposed to the internet.

1. Install Tailscale on the computer and on your phone, signed in to the same free account.
2. Tailscale admin console → **DNS**: enable **MagicDNS** and **HTTPS Certificates**.
3. On the computer: `tailscale serve --bg 18800` (on Windows, from an administrator terminal if it says access is denied). The app is now `https://<computer-name>.<tailnet>.ts.net`; the first visit takes up to a minute while the certificate is issued.
4. Set `APP_BASE_URL=https://<computer-name>.<tailnet>.ts.net` in `.env` so alert links open from the phone, then restart the server (`make deploy` with `DEPLOY = local`).

What to know:
- **The computer must stay on and awake.** While it sleeps or is off the app is unreachable, and scans and alerts pause; `--catch-up` runs the missed slots when it wakes, so an alert can arrive hours late.
- **The app shares your computer.** It has no login (`SECURITY.md`), scrapes third-party sites and runs many third-party packages; if it were ever compromised it would run as you, beside your files and browser. Running it in a VM (§2b) is the extra that walls it off.
- **Sharing with someone else.** Under Tailscale's default policy, a person you share a machine with can reach *every* port on it, not just the app. Before sharing the computer, limit shared users to the app in the policy file (Access controls), keeping your own access rule:
  ```json
  "acls": [
    { "action": "accept", "src": ["autogroup:member"], "dst": ["*:*"] },
    { "action": "accept", "src": ["autogroup:shared"], "dst": ["*:443"] }
  ]
  ```
  They can then change anything in the app — favorites, notes, the buyer profile — since it has no logins.
- **The name is public.** Issuing the certificate records `<computer-name>.<tailnet>.ts.net` in public certificate-transparency logs; only the name, never access.

## 3. Cost table
| Item | Monthly |
|---|---|
| Local only (+ optional Tailscale) | $0 |
| RentCast Foundation (hunt months only) | $74.00 |
| RapidAPI Zillow wrapper (optional flag) | free tier varies; paid plans above it |
| After closing (cancel RentCast) | $0 |

## 4. Env vars (see `.env.example` for the authoritative list)
`DATA_DIR`, `DATABASE_PATH` (derived default), `GEOGRAPHY` (packaged example name, default `sf_peninsula`), `GEOGRAPHY_FILE` (explicit TOML path; otherwise `<repo>/geography.toml` wins when present), `HOME_ADDRESS`, `OPEN_HOUSE_SOURCES` (comma-separated, default `realtor,redfin`), `SCAN_TIMES` (default `05:00,15:00`), `DAILY_TIMES` (default `04:00`), `RAW_KEEP_DAYS` (default `90`; `0` keeps every dated raw folder), `ROUTE_AVG_MPH`, `ROUTE_DETOUR_FACTOR`, `ZILLOW_ZHVI_ZIP_URL`, `ZILLOW_ZHVI_CITY_URL`, `ZILLOW_ZORI_ZIP_URL` (the public research CSVs `zillow-research` downloads; override only when Zillow moves them), `FRED_API_KEY`, `RENTCAST_API_KEY`, `RENTCAST_MONTHLY_LIMIT`, `SCHOOLDIGGER_APP_ID`, `SCHOOLDIGGER_APP_KEY`, `SCHOOLDIGGER_DAILY_LIMIT`, `CAASPP_YEAR` (California only), `ZILLOW_WRAPPER_ENABLED`, `RAPIDAPI_KEY`, `SAVE_PHOTOS`, `ALERT_CHANNELS` (comma-separated subset of `log,toast,pushover,email`, default `toast,log`), `PUSHOVER_TOKEN`, `PUSHOVER_USER`, `SMTP_HOST`, `SMTP_PORT` (default `587`), `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`, `APP_BASE_URL`, `HB_HTTP_PORT`, `HB_SERVE_SCHEDULER` (default `true`: the hourly catch-up check inside `hb serve`; `false` where OS timers run the jobs, as on the home server). Cities, ZIPs, counties, tax rates, the time zone, map view and price band are **not** env vars — they live in the geography TOML (`02` §3).

Note on photos: any instance reachable beyond the LAN MUST be access-protected (Tailscale, §2b / §2c) — downloaded photos must never be publicly exposed (`03-data-sources.md` §5.4).
