# 00 — Product Requirements (PRD)

## 0. Feature tour

It replicates — and in one key way surpasses — what paid consumer tools (PropStream, Reventure, DealCheck, TopHap, Homebot) charge for:

- **Transparent buyer-side CMA**: auto-selected, swappable closed comps with a visible, editable adjustment grid. No consumer product does this transparently today.
- **Overbid model + pricing posture**: in some markets (the Bay Area the tool was built in) homes are intentionally listed 10–40% under expected sale value to spur bidding wars — but not all: some are listed at market and some above it. **List price is a signal, not a floor.** The platform predicts the *sale* price from closed comps and the hyper-local sale-to-list ratio distribution, then classifies each listing's pricing posture (underpriced / near-market / overpriced) from market evidence — exposure vs area-median DOM, price cuts, relists, a passed offer date — and discounts its own estimates when the market has visibly rejected the price. The output is an explicit **UNDERBID / BID AT LIST / OVERBID** recommendation; "bid floor" framing appears only when the classifier actually says the list is bait.
- **Listing radar**: twice-daily scraping of active/pending/sold listings with price-cut, relist, and new-comp alerts, and true cumulative days-on-market (stitched across delist/relist cycles that game the public number).
- **Offer tooling**: max-defensible-bid back-solver, posture-driven opening range and value-justified ceiling, plain-language verdicts, affordability with your geography's effective tax rates and the pack's reassessment warning.
- **Open houses**: every scheduled open house on the homes the scan tracks, grouped by day with distance from your home address, a saved schedule of the ones you plan to go to (flagged if one is cancelled), and a per-day planner that orders the scheduled stops by their time windows and drive time, then hands you a multi-stop Google Maps route. Sources, geocoder and drive-time estimator are pluggable (`backend/hb/open_houses/`, docs/05 §4c).
- **Market dashboards**: ZIP-level trends (median $/sqft, inventory, DOM, sale-to-list, months of supply).
- **Tour capture**: a per-visit checklist pruned to the home's age (pre-1978 adds lead paint, pre-1975 the sewer lateral; the California pack adds foundation bolting pre-1980), with `flag_when` rules that raise the red flags a first-time buyer wouldn't recognise. Flagged defects carry regional cost bands that roll up — deduped by trade — into a deferred-maintenance total and a condition-adjusted value against the CMA.
- **AI deep-dive brief**: one button emits everything known *and* observed about a home as markdown — including, explicitly, what could not be verified — for handing a serious candidate to an AI alongside the disclosure packet.
- **Get Ready checklist**: what to have in place *before* touring, ordered by **lead time** rather than by date, because the only ordering that matters is which items are gated by calendar time you cannot compress (a credit dispute is 30–60 days by law; gift funds need 60 days of seasoning).
- **Field** (`/field`): the tour checklist laid out to be held in one hand while you walk a house. Pick the day's homes from your Tracker and open-house schedule (or search), then walk each through four big-button screens — Outside, Systems, Inside, Agent & verdict — with red flags and the deferred-maintenance total updating as you tap. Answers save as you go and show on the listing's Tour log and the Tracker; a print sheet is the paper fallback.
- **Closing tracker**: for a buyer with no agent, five numbers off the accepted contract derive every dated task through to keys — the pack's contingency clocks (the C.A.R. RPA's 17/17/21 under the California pack), escrow, disclosures, inspections, loan/appraisal, title, walkthrough, signing. A NULL day-count means *waived*, which prunes that anchor and everything depending on it. Deadline alerts fire from a daily job, so a missed date never depends on opening the page. The pack's playbook (`docs/14` for California) renders on the page.
- **Watchlist**: every home you watch, track or tour stays watched whatever you decided — pass, lose, or pause the search — and the page tells you what it did next in one plain sentence per home: price cuts, pending, sold and for how much against the original ask *and against the max bid you had set*. Alerts keep firing for those homes at any price, and their public sale history is re-checked weekly so a sale after the home left the market still shows up.
- **Contact the listing side without a buyer's agent**: every listing's agent, office and MLS id are already in the scrape — the detail page turns them into direct call and email links, so first contact never runs through a portal "Contact agent" form that assigns you an agent and a fee. Owner-of-record lookups point at your counties' free assessor rolls; no paid data.

## 1. User & context

- Single user: a self-represented first-time home buyer purchasing a **single-family home** in one configured metro area, on their own timeline. Each user runs their own instance.
- Target geography: a configured set of cities, their ZIP codes and counties, declared in one `geography.toml` (`02-architecture.md` §3). The packaged example is the SF Peninsula — Santa Clara, Sunnyvale, Mountain View, Redwood City, Menlo Park, Palo Alto, San Mateo, Burlingame, San Carlos, Belmont, Millbrae, San Bruno (27 ZIP codes across San Mateo and Santa Clara counties). The lists live in config, not code; the geography also selects a **state pack** of transaction content (`docs/packs/README.md`).
- Target price band: configured per geography (`[price_band]` in `geography.toml`; the packaged example is $2,000,000–$3,000,000). The band drives new-listing alert matching and default UI listing filters, and is shown on the Dashboard. It is **never an ingestion filter** — all prices are scraped so comps and overbid distributions stay statistically correct (`05-pipelines.md` §4).
- The user's core fear: **overpaying** in a market where list prices are intentionally misleading (see `01-domain-primer.md`).
- Two jobs for the product: (a) *teach* the user their target market over months of passive observation, (b) *arm* them per-listing during the active hunt: what will this sell for, what's my max bid, what leverage do I have.

## 2. Goals

1. Answer, for any active listing in the target area, in under one minute: **"What will this home actually sell for, and what should I bid?"** — with the reasoning fully visible (comps, adjustments, distributions), not a black-box number.
2. Detect leverage: overpriced/stale listings (true cumulative DOM, price cuts, relists) where negotiating below ask is realistic.
3. Track the user's pipeline of candidate homes through the offer process (disclosures → offer date → offer).
4. Keep total cost ≤ ~$105/mo at peak (active hunt), $0/mo otherwise.
5. Run locally on a home machine (Windows, macOS or Linux).

## 3. Feature scope

| # | Feature | Summary | Spec |
|---|---|---|---|
| F1 | Market dashboards | ZIP/city trend tiles + charts: median sale price, $/sqft, sale-to-list ratio, DOM, inventory, new listings, months of supply, % price cuts; mortgage-rate chart | 08 §1 |
| F2 | Listing radar | Twice-daily scrape (`SCAN_TIMES`, default 05:00 and 15:00) of for-sale/pending/sold in target cities; filterable list + map; per-listing badges (price cut, relist, cumulative DOM, predicted-sale chip) | 05 §4, 08 §2 |
| F3 | Transparent CMA engine | Auto-select 3–6 closed comps (bracketed), market-derived adjustment grid with per-ZIP time adjustment, swappable comps, live re-estimate, saved runs | 06 §2–4 |
| F4 | Overbid model | Hyper-local sale-to-list distribution → predicted sale price range for any list price; fresh vs stale segmentation | 06 §5 |
| F5 | Multi-AVM spread | Own CMA vs Realtor.com estimate vs RentCast AVM (optional Zestimate) on one axis; spread width = uncertainty signal | 06 §7, 08 §4 |
| F6 | Listing tracker | Kanban pipeline (saved → toured → disclosures → offer prep → offered → won → closing / lost / passed) with disclosure checklist and offer-date deadlines | 08 §5 |
| F7 | Alerts | Price cut, relist/back-on-market, new listing matching saved criteria, new comp sold near tracked home, offer date approaching, watched home went pending / sold / off market, closing deadline due soon / overdue, scan failure; channels: server log, desktop toast, Pushover push, email | 09 |
| F8 | Offer strategy helper | Max-defensible-bid back-solver (payment + cash/appraisal-gap constraints), escalation cap, plain-language verdict | 06 §6 |
| F9 | Affordability calculator | PITI with the geography's effective tax rate (city override → county), the pack's reassessment warning (California's supplemental bill under the `ca` pack), PMI, HOA, insurance (+ the pack's optional-peril toggle — earthquake in California), closing costs, post-close reserves check | 06 §8 |
| F10 | Condition tagging | Manual renovated/dated/fixer tags on properties; feeds CMA condition adjustment | 04 §properties |
| F11 | Hazard & permit context | FEMA flood zone for every geography, plus the state pack's hazard layers (the `ca` pack adds CAL FIRE wildfire severity and CGS liquefaction/fault zones) per property; assessor-sqft mismatch flag (unpermitted additions) — blank unless `properties.assessor_sqft` is filled in by hand, since no job writes it | 03 §1.4, 05 §8 |
| F12 | Tour capture | Per-visit checklist pruned to the home's age, with `flag_when` rules that raise red flags a first-time buyer wouldn't recognise; flagged defects carry the pack's regional cost bands (re-labelled per geography) that roll up (deduped by trade) into deferred maintenance and a condition-adjusted value. Recorded per visit from the listing detail page's tour panel or from **Field** (`/field`), the same checklist laid out to be held in one hand — pick the day's homes from the Tracker and open-house schedule, then four big-button screens per home, saved as you tap — with multiple visits per home, a printable paper fallback, and `POST /api/tours/import` gap-filling from Field's Copy answers without ever reverting an in-app edit | 13, 04 §property_tours, 08 §3.6c, §11 |
| F13 | AI deep-dive brief | One-click markdown of everything known about a home plus everything observed — and, explicitly, **what could not be verified** — for handing a viable candidate to an AI alongside the disclosure packet | 13 §9, 07 §Listings |
| F15 | Prep checklist | The front half the product was missing: what to have in place **before** touring and bidding — credit and the loan document pack, a genuinely underwritten pre-approval, the team a buyer with no agent must assemble themselves (attorney, inspector, sewer scope, insurance broker), market study, and the bidding rules decided while calm. Ordered by **`lead_time`** rather than by date, because the only ordering that matters is which items are gated by calendar time you cannot compress (a credit dispute is 30–60 days by law; gift funds need 60 days of seasoning). One global checklist in the `settings` row `prep_checklist` — no new table, because you get pre-approved once, not once per house | 15, 08 §13 |
| F14 | Closing tracker | The half of the process after acceptance, for a buyer with **no agent**: a `deals` row holding the five numbers off the contract, from which `hb/closing_spec.py` derives every dated task (escrow, disclosures, inspections, loan/appraisal, title/insurance, contingency removal, walkthrough, signing, post-close). Contingency clocks default to the pack's (the C.A.R. RPA's 17/17/21 under the `ca` pack) and a **NULL day-count means waived**, which prunes that anchor and every task depending on it. Each task carries the *why* a first-timer needs, the pack's form reference where one applies, and a cost band; deadline alerts fire from a daily job so a missed date never depends on opening the page | 14, 04 §deals, 08 §12 |
| F16 | Listing-side contact | Every listing's agent, office, broker and MLS id are already in the scrape (`listings.raw`); the detail page turns them into direct call and email links, so first contact never runs through a portal lead form that assigns a buyer's agent and a fee. Contacts can be saved on the listing by hand (owner of record from the free county assessor rolls, a second agent) and carry into the deal team | 08 §3 1c, 07 §Listings, 14 §2.3 |
| F18 | Watchlist | Every home the buyer watched (a Watch button on the listing), tracked or toured, whatever they decided, and what it did next: price cuts, pending, sold and for how much against the original ask and the buyer's own max bid. Tracking or touring a home watches it, and untracking or pausing the search never un-watches it; watched homes stay in alert scope at any price, and their Realtor history is refreshed weekly so a sale after the home left the market still shows up | 08 §5b, 07 §Watchlist, 09 §2 |
| F17 | Open houses | Every scheduled open house on the homes the scan tracks, grouped by day with straight-line distance from the user's home address; schedule the ones to go to (saved, with cancellations flagged) and the planner orders each day's stops by their time windows and estimated drive time into a multi-stop Google Maps route; `Open Sat 1–4 PM` chips on Listings, Listing detail and Tracker; log a visit straight into the tour record. Sources, geocoder and drive-time estimator are pluggable Protocols | 05 §4c, 04 §open_houses, 07 §Open houses, 08 §14 |

## 4. Non-goals

- **Not multi-user.** No auth, no accounts. Access control is network-level (your LAN or Tailscale).
- **Not a listing search engine.** Zillow/Redfin remain the browsing UX; this tool analyzes and tracks.
- **No rental/investment analysis** (cap rates, cash flow). Primary residence only.
- **No MLS/IDX integration** — unavailable to consumers; data comes from public datasets, libraries, and consumer APIs.
- **No redistribution** of any scraped content. Listing photos ARE downloaded and stored locally for personal reference (`03-data-sources.md` §5.4), but never republished or exposed on an unprotected deployment. Personal use only.
- **No ML beyond robust regression.** The value is transparent methodology, not model sophistication.
- **No mobile app.** Responsive web UI is sufficient.

## 5. Success criteria

1. **Golden backtest**: on ≥ 20 recently sold target-area homes, the **blended predicted value** (`valuation.CMA_WEIGHT`·CMA + rest·overbid point — the headline number the product shows, computed using only pre-sale data) has median absolute error ≤ 8% vs actual sale price, and the overbid model's **calibrated predicted range** contains the actual sale price ≥ 50% of the time. CMA-only MdAPE is reported alongside as a diagnostic with no threshold (the transparent comp CMA is the *explanation*; the blend is the *prediction*). See `10-testing-strategy.md` §4 and `06-algorithms.md` §5.4.
2. **Freshness**: new listings in target cities appear in the tool within 24h; price cuts alert within 24h.
3. **Idempotency**: any pipeline run twice back-to-back yields zero new rows / zero duplicate events (see `05-pipelines.md` §1).
4. **Dashboard parity**: ZIP metrics match Redfin Data Center published values for spot-checked ZIP/week combinations.
5. **Cost**: $0/mo on the free tiers; the RentCast paid tier is the only recurring cost, and optional (§2 goal 4).

## 6. Constraints & assumptions

- Windows 11 dev machine; Python 3.12 and Node 20+ available.
- Single SQLite database file (< 5 GB); downloaded photos add roughly 100–300 KB per image under `data/photos/` — budget ~10–20 GB disk overall.
- RentCast free tier = 50 requests/mo → per-property enrichment is budgeted and user-triggered until the paid tier is on.
- Zillow research CSV history is restated every release → those pipelines truncate-and-replace, never diff.
- All scraping: logged out, ~1 req/sec with jitter, aggressive caching (`03-data-sources.md` §5).
- The target price band (`[price_band]` in `geography.toml`) filters alerts and UI defaults only, never ingestion.
