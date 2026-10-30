# Contributing

Thanks for looking at this. It is a single-user tool that each person runs on their own
machine, so the most valuable contributions are **state packs**, **data-source fixes** when an
upstream format drifts, and **tests**.

## Setup

Prerequisites: Git, Python ≥ 3.12 with [`uv`](https://docs.astral.sh/uv/), Node 20+, `make`.
On Windows run the targets in Git Bash; most are one-liners you can also run by hand, but
`make deploy-windows` and the `start` / `load` sequences are easiest through `make`.

```
make install          # uv sync + npm install
make setup            # your area -> geography.toml + .env (tests don't need it: they pin the example)
make test             # backend pytest (network-free, ~30 s)
make lint             # ruff
make build            # tsc -b && vite build
make serve            # migrate + serve on http://localhost:18800
```

Hot reload while editing: `make dev-api` (uvicorn on :8000) and `make dev-ui` (Vite on :5173,
proxies `/api` and `/photos`).

## Ground rules

- **The docs are the spec.** `docs/` describes the current state of the system in depth
  (data model in `04`, pipelines in `05`, API in `07`, UI in `08`). A change that makes part of
  a doc stale corrects that part in the same change; do not leave the docs describing a system
  that no longer exists, and do not condense them to make them shorter.
- **Idempotency** (`docs/05` §1): every pipeline job can run twice in a row and produce zero
  new rows and zero duplicate events. Pipeline writes go through `hb/db/upsert.py` keyed on
  each table's natural unique key.
- **No network in tests.** Every pipeline exposes a `fetch_*` seam that tests monkeypatch.
  Follow the existing style in `backend/hb/tests/`; the suite pins the packaged `sf_peninsula`
  geography and uses `tests/fixtures/geography_tx_minimal.toml` for the `us` pack.
- **Scraping etiquette** (`docs/03` §5): logged-out, ~1 req/s jittered, cache raw responses,
  never redistribute downloaded photos or listing data.
- **No geography or state literals in code.** Cities, ZIPs, counties, rates and the state live
  in `geography.toml`; everything that differs by state lives in `hb/packs/<key>/`. If you
  find yourself typing a city name or `"CA"` outside those places, stop (`docs/packs/README.md`).
- **Migrations stack.** The schema is the five migrations in `migrations/versions/`
  (`0001_initial` through `0005_profile_income`); a model change edits `models.py` and adds a
  hand-reviewed migration on top, and `test_migrations.py` fails on drift.
- **Secrets** stay in `.env` (gitignored). Never commit a `.sqlite3`, a cert or a key; the
  `.gitignore` covers `backend/data/`.

## Adding a state pack

Read `docs/packs/README.md` §3. Short version: copy `backend/hb/packs/ca/`, compose on the
`us` base with field-level overrides (same task keys — checklist JSON is keyed on them),
register it in `hb/packs/__init__.py`, run `make test`. A playbook is optional; without one the
Closing page hides its guide links and `MarkdownGuide` shows the one-line note "This pack ships
no closing guide — the tracker below still applies."

## Pull requests

- Target `main`, the only branch. The local and home-server setups are configuration, not
  branches (README → Two ways to run it), so a change lands once for both.
- Keep a PR to one concern. Run `make lint`, `make test` and `make build` before opening it;
  CI (`.github/workflows/ci.yml`) runs the same on Ubuntu.
- Describe what changed and which doc sections you updated.
- Personal data never belongs in fixtures: use `example.com` addresses, `555-01xx` phone
  numbers and invented names and streets, as the existing tests do.

## Security

See `SECURITY.md`. The app has no authentication by design and must stay on a trusted LAN or
your own tailnet (`docs/16`).
