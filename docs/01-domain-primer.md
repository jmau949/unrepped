# 01 — Domain Primer: Bay Area Dynamics, CMA Methodology, Buyer Blind Spots

This document is the domain knowledge behind every algorithm in `06-algorithms.md`. Read it before implementing anything in `hb/engine/`.

> Written for the **San Francisco Bay Area** — the market the product was built in and the one its `ca` pack encodes. The mechanics (closed-sale CMA, sale-to-list distributions, pricing posture, cumulative DOM) are market-agnostic; the magnitudes and conventions below are not. Read them as a worked example of the knowledge to gather for your own market, then configure your geography (`02` §3).

## 1. Bay Area pricing dynamics (why list price ≠ value)

- **Intentional underpricing is the regional convention — common, not universal.** SF/Peninsula/South Bay single-family homes are routinely listed **10–40% below expected sale value** to manufacture bidding wars, with a published **offer date** ~7–14 days after listing. Agents openly describe list prices as invitations to compete, not valuations. But plenty of listings are priced at market, and some *above* it (aspirational sellers, mispriced condition problems, agents who lost the pricing argument). A buyer tool that assumes bait pricing everywhere tells its user to chase a CMA the market has already refused — the posture classifier (docs/06 §5.6) decides per listing which regime applies.
- Magnitude (2024–2026): ~61% of five-county Bay Area homes sold over asking in 2024; SF single-family homes averaged ~25% over asking by May 2026; overbids of 10–30% are normal on the Peninsula/South Bay; trophy properties go 50%+ over.
- **Process quirks the product must model:**
  - **Disclosure packets** (seller-paid inspections, pest report, NHD, TDS/SPQ) are provided *up front*; buyers are expected to review before offering.
  - Offers are expected **non-contingent or nearly so** in competitive segments; ~19% of hot-market CA buyers waived appraisal contingency (Oct 2025); **appraisal-gap coverage of 5–10%** is a common offer term.
  - **Preemptive offers** (before the offer date) must be knockout price + clean terms.
- **Consequences for the product:**
  - The Zestimate on an *active* listing anchors toward the (often fake-low) list price — display it but never trust it on-market.
  - Value must come from **closed sales**, adjusted to today; the expected *sale* price comes from the CMA cross-checked against `list_price × local overbid distribution` — and then discounted by **market evidence**: prolonged exposure at a price with no takers is evidence value ≤ that price, however confident the comp math is (docs/06 §5.6).
  - **List price is a signal, not a floor.** The UI labels each list price with its *inferred pricing posture* as a calibrated share — "~7 in 10 such homes sell below asking (typ. 2.7% under)" — and the "bid floor" framing appears only when the classifier says the listing is underpriced bait. Estimates (ours included) are soft — when the CMA, the ratio model, and external AVMs disagree, the UI says so and leans on market behaviour instead of any point number.

## 2. CMA methodology (what appraisers/agents actually do)

Source of truth: Fannie Mae Selling Guide B4-1.3-08 (Comparable Sales) and B4-1.3-09 (Adjustments), plus standard agent CMA practice.

### 2.1 Comp selection
- **Closed sales only** for the value estimate; actives/pendings bracket current conditions but don't set value.
- **Distance**: same neighborhood; < 0.5 mi ideal, 1.0 mi acceptable suburban. Never cross a "boundary of value" (school-district line, highway, flight path) without an explicit adjustment.
- **Recency**: sold < 6 months, strongly weighted to < 90 days; pendings are the freshest directional signal.
- **Similarity**: ±20% gross living area (GLA/sqft); same property type; beds ±1; similar era/lot.
- **Count**: 3–6 solid comps.
- **Bracketing**: include at least one comp *superior* and one *inferior* to the subject (in size and adjusted price) so the subject's value interpolates rather than extrapolates.

### 2.2 Adjustments
- Adjust the **comp's** price toward the subject: comp has a feature the subject lacks → subtract; comp lacks it → add.
- Adjustments must be **market-derived** (paired sales / regression), not rules of thumb. Fannie Mae explicitly rejects habitual "$X/sqft" figures unsupported by local data.
- **Marginal $/sqft ≠ average $/sqft**: the market pays roughly **30–60% of the average $/sqft** for each *additional* square foot (the land and the kitchen come with the first square foot). Using full average $/sqft to adjust size differences is the most common amateur CMA error.
- **Time/market-conditions adjustment is mandatory** (Fannie Mae policy since late 2024): adjust each comp for market movement between its sale month and today using a local price index. In a market moving 1%+/month, a 5-month-old comp needs a ~5% adjustment — larger than most feature adjustments, and the one most people skip.
- **$/sqft is a screening/sanity metric, not the valuation.** Small homes always show higher $/sqft.

### 2.3 Paired-sales intuition
Two sales identical except one feature → the price difference *is* the market's adjustment for that feature. With enough local sales, a robust regression approximates paired-sales analysis; with few, use conservative fallback values and show them as assumptions.

## 3. Leverage signals (when a buyer can negotiate)

- **Sale-to-list ratio (SP/LP)** — the single best "how much over/under ask" calibration. Must be computed **hyper-locally** (ZIP + property similarity + trailing 60–90 days) and **against the original list price** (post-cut ratios hide the underpricing strategy). >100% median → expect to bid over; ~96% + rising inventory → a below-ask opener is normal.
- **Days on market** — rough framework: <14 DOM: no discount, expect competition; 30–60 DOM: ~5% below ask with comps attached; 60–120+ DOM: 5–15% below plus concessions.
- **Cumulative DOM (CDOM)** — sellers game public DOM by delisting and relisting (public counters reset). MLSs track CDOM internally; this product reconstructs it by stitching listing episodes per property (`05-pipelines.md` §6). **A listing showing 9 DOM that is really on day 87 is a leverage gift.**
- **Price-cut history** — 3+ reductions ≈ motivated seller; negotiate below the *reduced* price. A price cut also moves a listing from the "fresh" to the "stale" overbid distribution (`06-algorithms.md` §5).
- **Months of supply / pending-to-active ratio** — direction of the local market decides whether to be aggressive or patient. Computed per ZIP by `market-supply` (`05-pipelines.md` §3.5), interpreted against peninsula-calibrated bands and the ZIP's own three-year range (`06-algorithms.md` §9), surfaced on the Supply page (`08-ui-spec.md` §9). Note the whole target market runs 0.2–2.5 months — national "6 months = balanced" framing is useless here, so read the *percentile*, not the absolute.

## 4. First-time-buyer blind spots (must be productized)

| Blind spot | What it is | Where handled |
|---|---|---|
| Disclosure-packet workflow | Packets arrive before offers; must be read fast (pest report **Section 1 total** = active damage cost; TDS/SPQ seller disclosures; NHD natural-hazard report; HOA docs if any) | Tracker checklist |
| Offer dates | Typically ~7 days post-list; missing one means a preemptive-or-nothing situation | A date input on the listing detail page (`listings.offer_due_at`, also parsed from the remarks when they state one), `offer_date_soon` deadline alerts |
| Appraisal gap | Winning bids often exceed what an appraiser will support; lender funds only appraised value × LTV — the gap is extra cash. Offers commonly include 5–10% gap coverage | Offer back-solver cash constraint, 06 §6 |
| Prop 13 + supplemental tax | Property tax ≈ 1.1–1.3% of *purchase price* (varies by city due to local parcel taxes/bonds). First year brings a **supplemental bill** back-dated to close because the seller's old assessed value applied until then | Affordability engine, 06 §8 |
| Unpermitted additions | Endemic in the Bay Area. Listing sqft > assessor sqft by >15% is a red flag (appraisal/insurance/permit risk) | The sqft-mismatch flag reads `properties.assessor_sqft`, which no job populates (there is no assessor feed) — it fires only when the value is filled in by hand |
| Hazards | Flood (FEMA NFHL), wildfire (CAL FIRE FHSZ — matters in Redwood City/San Mateo hills), liquefaction and Alquist-Priolo fault zones (SF, bayfront fill) — all raise insurance cost or lending friction; earthquake insurance is separate and expensive | Hazard overlays |
| Rate locks | Locks run 30–60 days; pre-approvals expire (usually 60–90 days) | The contacts panel on the listing page and the deal team (08 §3 1c, `backend/hb/api/contacts.py`) hold the lender; the closing `deal_deadline_*` alerts cover the loan contingency clock. There is no rate-move alert |
| Escalation clauses | "Beat highest offer by $X up to cap Y" — cap must equal the max defensible bid, not a hopeful number | Offer helper, 06 §6 |
| Post-close reserves | Winning with $0 left is losing; warn if reserves < 6 months PITI | Affordability, 06 §8 |
| Seismic retrofit / foundation | Pre-1980 homes may need bolting/cripple-wall work ($5–25k+); check disclosures | Manual note field on tracked listings |
| Contingencies are removed **actively** | A California contingency does not expire on its own — it stays in force until you sign a Contingency Removal (Form CR). Passing the date neither waives your protection nor cancels the deal; it puts you in breach of a timeline the seller can act on | Closing tracker, 14 §4, 11 |
| The 48-hour NBP | Once a contingency date has passed, the seller serves a **Notice to Buyer to Perform** and you have **2 days** before they may cancel and contest the deposit. Two days is not enough time to learn what an NBP is | `deal_deadline_*` alerts, 14 §4 |
| Insurance is now a closing gate | CA 2026: carrier exits and non-renewals mean placement can take weeks, FAIR Plan + DIC is a common outcome, and the lender will not fund without a bound policy. First-timers schedule it last | Closing tracker day-1 blocking task, 14 §9 |
| Prelim title **exceptions** | The preliminary report is a list of what title will *not* insure — easements, shared-driveway agreements, deed restrictions, encroachments. They survive the sale | Blocking task + attorney prompt, 14 §5 |
| Point-of-sale city ordinances | Seven San Mateo County cities (incl. **San Mateo, Burlingame, Millbrae**) require a sewer-lateral compliance certificate before title transfers; San Carlos/Belmont trigger on remodel only. A lateral is $12–30k | `Task.applies_when` city rule, 14 §7 |
| CD vs LE comparison | The Closing Disclosure arrives 3 business days before closing and nobody checks it against your Loan Estimate for you | Blocking task, 14 §12 |

## 5. Competitive landscape (why build this)

- Free AVMs (Zestimate, Redfin Estimate, Realtor.com's three-AVM display) give numbers without comp transparency; on-market Zestimates anchor to list price.
- Investor tools with real comps engines (PropStream $99–699/mo) are flip/rental-framed.
- Useful patterns copied: DealCheck's offer back-solver (~$10/mo), Homebot's plain-language "buy score" verdict, Reventure's ZIP dashboards ($39/mo), TopHap's parcel heatmaps ($15–55/mo), Realtor.com's AVM-spread-as-uncertainty display.
- **The gap: no consumer-priced product does a transparent buyer-side CMA with a visible adjustment grid and a local overbid model.** That is this product's core.
