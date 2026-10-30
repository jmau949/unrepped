# Thin wrappers around uv/npm (docs/11-deployment.md §1). Run from repo root.
# Every target is portable (Windows Git Bash, macOS, Linux) except deploy-windows;
# deploy-server needs a POSIX shell with tar/ssh/curl and Tailscale SSH to the home server.

# Per-checkout settings (gitignored; template config.mk.example): DEPLOY picks what
# `make deploy` runs - `local` (the always-on machine this checkout runs on) or
# `server` (the home server over Tailscale SSH). HB_SSH, if set there, is the
# server's SSH target for ops/deploy-server.sh (default hb@hb).
-include config.mk
ifdef HB_SSH
export HB_SSH
endif

.PHONY: install setup start load schedule schedule-remove serve dev-api dev-ui daily scan alerts \
        test lint migrate build backfill build-index enrich backtest deploy deploy-local \
        deploy-windows deploy-server

# First-time setup: backend env + frontend deps.
install:
	cd backend && uv sync
	cd frontend && npm install

# Choose your area: asks for state, cities and price range and writes
# geography.toml (+ .env on a first run) from Census data (docs/packs/README.md s.1).
setup:
	cd backend && uv run hb setup

# Everything after `make setup`, in one go: build the SPA (seconds, needs no
# data — first, so `make serve` in a second terminal works while the load runs),
# load the data for your area, make the operating system run the scans on its
# own from now on, serve. Safe to run again any time (a refresh, then serve);
# `make serve` alone skips the refresh. Steps are chained explicitly rather than
# as prerequisites so `make -j` cannot reorder them; a schedule failure is
# reported but still lets the app come up.
start:
	$(MAKE) build
	$(MAKE) load
	-$(MAKE) schedule
	$(MAKE) serve

# The per-user OS schedule for the scans (hb schedule install): hourly Task
# Scheduler jobs on Windows, launchd agents on macOS, systemd --user timers or a
# crontab block on Linux. No administrator needed; idempotent, and it re-points
# the jobs at this checkout. `make schedule-remove` undoes it.
schedule:
	cd backend && uv run hb schedule install

schedule-remove:
	cd backend && uv run hb schedule remove

# The data load: the pack's hazard polygons when they are not on disk yet (the
# daily `hazards` job reads them, so they come first), the daily bulk sources
# (first run ~5.5 GB of Redfin CSVs), then a listing scan — whose photo tail is
# the slow part of a first run (four at a time, a pause each; a city can have 15,000).
# Each step reports its own failures and the next one still runs (the leading
# `-`), so one bad source leaves the rest of the app populated.
load:
	@echo "Loading your area's data. The first run takes an hour or more: leave this window open."
	@echo "Steps: hazard maps, market data (about 5.5 GB), then every home for sale and its photos."
	@echo "Each step prints its progress. Meanwhile, 'make serve' in a second terminal opens the app."
	-cd backend && uv run hb pipeline hazards-fetch --if-missing
	-cd backend && uv run hb pipeline daily
	-cd backend && uv run hb pipeline listing-scan

# The run command. Applies migrations (seeding an empty DB), then serves the API
# + the built SPA as plain HTTP on 18800 (HB_HTTP_PORT in .env), bound on
# 0.0.0.0. Builds the SPA first when it has never been built; after a frontend
# change run `make build` yourself (serve never rebuilds an existing one).
serve:
	@test -d frontend/dist || $(MAKE) build
	cd backend && uv run hb serve

dev-api:
	cd backend && uv run uvicorn hb.main:app --reload --port 8000

dev-ui:
	cd frontend && npm run dev

daily:
	cd backend && uv run hb pipeline daily

scan:
	cd backend && uv run hb pipeline listing-scan

alerts:
	cd backend && uv run hb alerts send

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check .

migrate:
	cd backend && uv run hb db upgrade

build:
	cd frontend && npm run build

# --- Valuation data + gate ---
# One-time historical comp backfill so the backtest has prior comps (docs/12).
# Override the window with:  make backfill MONTHS=36
MONTHS ?= 24
backfill:
	cd backend && uv run hb pipeline backfill-sales --months $(MONTHS)

# Rebuild the price index after a backfill.
build-index:
	cd backend && uv run hb pipeline build-index

# Enrich all tracked listings with Realtor.com/RentCast/Zestimate AVMs.
enrich:
	cd backend && uv run hb pipeline enrich --all-tracked

# Golden backtest gate (docs/10 §4).
backtest:
	cd backend && uv run hb backtest --n 20

# --- Windows always-on deployment (ops/windows-lan.ps1) ---
# Rebuild the SPA, then restart the always-on LAN server - the "HB API Server"
# scheduled task from ops/windows-lan.ps1, which runs ops/serve.ps1 -> `hb serve`.
# Neither half refreshes on its own: the task never reloads Python, and the SPA
# is served from disk, so deploying is always both. The health poll on 18800 is
# the gate: if nothing answers within 20 s the target fails. Windows Firewall
# scopes the port to the local subnet and 18800 is outside the common dev range
# so 3000/5173/8000/8081 stay free. On macOS/Linux there is no equivalent
# target: run `make build` and keep `make serve` running under launchd/systemd
# (docs/11 §2a).
# The venv is synced HERE, while the server is stopped: the server holds
# .venv\Scripts\hb.exe open, and the scheduled tasks run `uv run --no-sync` so
# they never try to rewrite it (ops/windows-tasks.ps1).
deploy-windows: build
	powershell -NoProfile -Command '$$ErrorActionPreference = "Stop"; Stop-ScheduledTask -TaskName "HB API Server" -ErrorAction SilentlyContinue; Get-NetTCPConnection -LocalPort 18800 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $$_.OwningProcess -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 1; Push-Location backend; uv sync; $$synced = $$LASTEXITCODE; Pop-Location; if ($$synced -ne 0) { Start-ScheduledTask -TaskName "HB API Server"; throw "deploy failed: uv sync could not update backend/.venv - a running pipeline (HB Listing Scan / HB Daily Pipelines) holds hb.exe; rerun once it finishes" }; Start-ScheduledTask -TaskName "HB API Server"; $$up = $$false; foreach ($$i in 1..20) { Start-Sleep -Seconds 1; try { Invoke-RestMethod -Uri "http://localhost:18800/api/ops/health" -TimeoutSec 5 | Out-Null; $$up = $$true; break } catch { } }; if (-not $$up) { throw "deploy failed: nothing healthy on http://localhost:18800 - check the HB API Server task" }; Write-Host "deployed: http://localhost:18800"'

# --- Home-server deployment (ops/deploy-server.sh, docs/11 §2b, docs/16) ---
# Build the SPA, stream the working tree to the home server (HB_SSH, default hb@hb)
# over Tailscale SSH, swap it into place keeping the server's own .env and venv,
# uv sync, restart hb.service, then poll the health endpoint through
# `tailscale serve` for up to 20 s.
deploy-server:
	bash ops/deploy-server.sh

# --- Local always-on deployment ---
# `DEPLOY = local`: on Windows the "HB API Server" task above; elsewhere there is no
# service the Makefile can restart, so rebuild the SPA and say what is left (docs/11 §2a).
ifeq ($(OS),Windows_NT)
deploy-local: deploy-windows
else
deploy-local: build
	@echo "SPA rebuilt. A backend change needs a restart of whatever runs 'hb serve' (docs/11 §2a)."
endif

# `make deploy` runs the target named by DEPLOY in config.mk (docs/11 §1), so the
# same command ships to whichever setup this checkout serves. Unset, it fails rather
# than guessing: deploy-windows stops whatever is listening on 18800.
ifeq ($(DEPLOY),)
deploy:
	@echo "make deploy: set DEPLOY in config.mk (copy config.mk.example) to local or server," >&2
	@echo "or run make deploy-local / make deploy-server directly (docs/11-deployment.md, section 1)." >&2
	@exit 1
else ifneq ($(DEPLOY),$(filter local server,$(DEPLOY)))
deploy:
	@echo "make deploy: DEPLOY must be local or server (config.mk), not '$(DEPLOY)'" >&2
	@exit 1
else
deploy: deploy-$(DEPLOY)
endif
