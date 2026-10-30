# Documentation index

The `docs/` folder is the authoritative spec: every page, pipeline, table and algorithm is described here, and code changes keep it in sync. Humans can start with the README; AI assistants start with `CLAUDE.md`, which points here.

| File | Contents |
|---|---|
| `00-product-requirements.md` | PRD: the feature tour (§0), user, goals, feature scope, non-goals, success criteria |
| `01-domain-primer.md` | Market dynamics (written for the Bay Area, as a worked example), CMA methodology, leverage signals, first-time-buyer blind spots — the domain knowledge behind every algorithm |
| `02-architecture.md` | Stack + rationale, repo layout, config conventions (geography + packs), portability rules |
| `03-data-sources.md` | Every data source: exact URLs, access method, schedule, cost, legality, failure modes |
| `04-data-model.md` | Full schema: tables, columns, unique/upsert keys, indexes, FK graph |
| `05-pipelines.md` | Per-job specs: steps, idempotency contracts, entity resolution, relist stitching. Most run daily; the registry in `backend/hb/pipelines/__init__.py` is authoritative about which |
| `06-algorithms.md` | CMA, overbid model, offer back-solver, affordability — formulas + worked examples |
| `07-api-spec.md` | REST endpoints with request/response shapes, including `GET /api/config` and `GET /api/guide/closing` |
| `08-ui-spec.md` | Every UI page: layout, components, data needs, states |
| `09-alerts-spec.md` | Alert rules, triggers, dedup, channels |
| `10-testing-strategy.md` | Test strategy incl. duplicate-handling matrix and CMA golden backtest |
| `11-deployment.md` | Run it: quick start, setup notes and every command (§1); Local vs Tailscale; always-on on Windows (§2) or macOS/Linux (§2a); Tailscale on your own computer (§2c); the alternate machine's units and deploy script (§2b); costs |
| `12-api-keys.md` | API-key setup (FRED/RentCast/SchoolDigger/RapidAPI/Realtor.com/CAASPP/Pushover/Email) + the one-time historical comp backfill |
| `13-tour-playbook.md` | What to look at when you walk a house, why each finding matters, and the repair cost bands behind the flags (California pack) |
| `14-closing-playbook.md` | Offer accepted → keys without a buyer's agent: the escrow calendar, contingency clocks, forms, who to hire when (California pack; served in-app) |
| `15-prep-playbook.md` | What to have in place before touring: credit, the loan document pack, a real pre-approval, the team you must assemble yourself (California pack) |
| `16-home-server.md` | Optional extras for the Tailscale setup — a VM (isolation) and/or an alternate machine (always on): host prep and LAN isolation, tailnet policy, install, deploy, moving data, backups, upkeep; the Proxmox reference build as an appendix |
| `packs/README.md` | The geography file, pack anatomy, and how to add a state pack |
| `../CONTRIBUTING.md`, `../SECURITY.md`, `../LICENSE` | How to contribute; the (LAN-only, no-auth) threat model; MIT |
