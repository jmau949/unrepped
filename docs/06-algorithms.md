# 06 — Algorithms

Formulas and worked examples for the analytical core (`backend/hb/engine/`). Domain rationale lives in `01-domain-primer.md`.

## 1. Notation
Subject = the home being valued. Comp = a closed sale from `sales` joined to `properties`. All prices integer dollars. `today` = run date.

## 2. CMA comp selection (`engine/cma.py`)

### 2.1 Candidate pool (SQL prefilter + Python exact filter)
- Same `property_type='single_family'`.
- `sale_date` within 6 months (relax to 9 if < 5 candidates survive the other filters).
- Distance ≤ 0.5 mi (relax to 1.0 mi if < 5): SQL bounding box on indexed `(lat, lon)` (±Δlat = miles/69, ±Δlon = miles/(69·cos lat)) then exact haversine in Python.
- Sqft within ±20% of subject (relax ±30% if < 5).
- Beds within ±1.
- Relaxation order when starved: months → distance → sqft (never relax beds).

### 2.2 Similarity score (0–1, product of penalties)
```
f_dist  = exp(−(miles / 0.4)²)
f_time  = 0.5 ^ (days_ago / 90)          # 90-day half-life ⇒ "weighted to <90 days"
f_sqft  = exp(−((|Δsqft| / subj_sqft) / 0.15)²)
f_beds  = 0.85 ^ |Δbeds|
f_baths = 0.90 ^ |Δbaths|                # baths rounded to nearest 0.5
f_lot   = exp(−((|Δlot| / subj_lot) / 0.5)²)   # wide tolerance; skip if either lot NULL
f_cond  = 1.0 same tag | 0.9 unknown | 0.8 adjacent (renovated↔dated, dated↔fixer) | 0.6 opposite (renovated↔fixer)
score   = f_dist · f_time · f_sqft · f_beds · f_baths · f_lot · f_cond
bonus: score ×= 1.1 if same normalized street name (cap score at 1.0)
```

### 2.3 Selection with bracketing
Take the top 6 by score, then enforce: ≥1 comp with sqft > subject and ≥1 with sqft < subject; ≥1 adjusted price above and ≥1 below the preliminary estimate. If a bracket is missing, swap the lowest-scored pick for the best-scoring candidate that fills it. If the pool can't bracket, proceed but set confidence=low with reason `unbracketed`.
User can toggle `included` per comp in the workbench; estimate recomputes over included comps only.

## 3. Time adjustment (`engine/price_index.py`)
For comp c in geo g (ZIP; fall back city→county per `build-index` coverage):
```
time_adj_factor(c) = index(g, month(today)) / index(g, month(c.sale_date))
adj_price₀(c) = c.sale_price × time_adj_factor(c)
```
Missing months: linear interpolation; beyond series end: carry last value and flag. **Always applied first, before feature adjustments.**

## 4. Feature adjustments (`engine/adjustments.py`)
Direction: adjust the **comp toward the subject** (comp superior ⇒ subtract).

### 4.1 Marginal $/sqft
Default: `m = 0.45 × median_ppsf`, where `median_ppsf` is the median of the last 3 Redfin `median_ppsf` rows (≈ trailing 90 days) for the subject's ZIP, falling back to its city, then county (`adjustments.median_ppsf`; the factor is configurable 0.30–0.60; see 01 §2.2).
Regression override when the subject's same-city ZIPs (`settings.geo.sibling_zips`) hold **≥ 40 time-adjusted sales in 12 months** that carry sqft, baths, lot and year built (a sale missing any of them is dropped): robust regression (statsmodels `RLM`, Huber):
`detrended_price ~ sqft + baths + lot_sqft + age` (detrended = time-adjusted). Accept the sqft coefficient only if within **25–70% of average $/sqft**; else keep the 0.45 heuristic. Beds deliberately excluded — collinear with sqft; bed differences flow through sqft.
`adj_sqft = m × (subj_sqft − comp_sqft)`

### 4.2 Fallback grid (when regression rejected/unavailable)
- Bath: full ±$15,000; half ±$8,000 (regression coefficient replaces when accepted).
- Lot: `Δlot_sqft × 0.15 × m`, capped at ±10% of comp price.
- Condition (tags): renovated↔dated ±7% of comp adjusted price (midpoint of 5–10%); fixer −15% relative to dated; unknown ⇒ 0 with a "condition unknown" note.
```
adjusted_price(c) = adj_price₀ + adj_sqft + adj_baths + adj_lot + adj_condition
```
Every line item is persisted in `cma_comps.adjustments` and rendered in the workbench grid — transparency is the product.

### 4.3 Worked example
Subject: 1,600 sqft, 3/2, 5,000 lot, tag `dated`, ZIP 94087. Comp: sold 2026-02-10 for $2,400,000; 1,750 sqft, 3/2.5, 5,200 lot, `renovated`. Today 2026-07-14. Index: 94087 2026-02 = 0.962, 2026-07 = 1.000. Area median $/sqft = $1,400 ⇒ m = $630.
```
time:      2,400,000 × (1.000/0.962) = 2,494,802            (+94,802)
sqft:      630 × (1600 − 1750)       = −94,500
half-bath: −8,000
lot:       (5000−5200) × 0.15 × 630  = −18,900
condition: comp renovated vs subject dated ⇒ −7% × 2,494,802 ≈ −174,636
adjusted_price ≈ 2,494,802 − 94,500 − 8,000 − 18,900 − 174,636 = 2,198,766 → $2,198,800
```

### 4.4 Estimate & uncertainty
Over included comps with weights = similarity scores:
- estimate = weighted **median** of adjusted prices
- range = weighted p25–p75, floored at ±3% of estimate
- confidence: **low** if n < 3, or (p75−p25)/estimate > 10%, or any comp's gross adjustments (Σ|feature line items| — sqft, baths, lot, condition; the time adjustment is a market-level correction, not a dissimilarity, and is excluded) > 20% of its sale price, or unbracketed; **high** if n ≥ 5 and spread ≤ 6% and all gross adjustments ≤ 15%; else **medium**.
Persist `cma_runs` + `avm_snapshots (source='own_cma')`.

## 5. Overbid model (`engine/overbid.py`)
Predicts the sale price *distribution* for a list price (01 §1). Always uses `sp_lp` computed against **original** list price.

### 5.1 Sample
`sales` in subject's ZIP (widened to its same-city ZIPs, `settings.geo.sibling_zips`, if n < 8), trailing 90 days (extend 180 if still n < 8), single-family, original list within ±30% of the subject's original list price (current list when no original is stored — the same anchor the output is scaled from), beds ±1, `sp_lp` NOT NULL.

### 5.2 Fresh/stale split
- **fresh** = comps with `had_price_cut = false` and no relist in their group
- **stale** = the rest (SP/LP behaves completely differently after a cut)
- an empty bucket falls back to the whole sample (for the ZIP quantiles and, separately, for the city distribution in §5.3)
Model the subject with the fresh distribution unless it `had_cut` (an observed downward `price_change`, a dated Realtor `price_history` cut in the current episode, or a relist below the previous ask — `engine/exposure.py`) OR its **cumulative** DOM > 1.5 × area median DOM ⇒ use stale, and say so in the output. Routing deliberately stays on cumulative history: it picks a comp *distribution* whose `fresh` flag was set on the same cumulative facts. The §5.6 posture layer asks a different question — whether *this* asking price has been tested — and runs on the current episode's clock, so a fresh relist reads as bait there while its cumulative days usually route it stale here.

### 5.3 Weighted distribution + shrinkage
Weights `w = 0.5^(days_since_sale/60)`. Weighted quantiles p25/p50/p75 of sp_lp. Shrink toward the city-level distribution for thin samples:
```
p_final(q) = (n_eff·p_zip(q) + k·p_city(q)) / (n_eff + k),   k = 8,  n_eff = (Σw)²/Σw²
```

### 5.4 Output
```
point = list × p50
predicted_range = [list × p25 × (1 − RANGE_WIDEN), list × p75 × (1 + RANGE_WIDEN)]
"Predicted sale: $2.18M – $2.41M (median 112% of $2.05M list; n=14 fresh comps, 90 days)"
```
`RANGE_WIDEN` (currently 0.03) is a **calibration knob**: the raw weighted p25–p75 understates realized uncertainty (backfilled comps carry no price-cut history, tightening the fresh distribution artificially), so the served range is widened until backtest coverage is honest. The UI/API label this the "calibrated range", never "p25–p75"; the raw quantiles are still returned as `p25`/`p75` fields. Tuned values are recorded in each backtest report (docs/10 §4).
**Cross-check**: if `list × p50` diverges from the CMA estimate by > 7%, flag `atypical_pricing`: "List price is atypical for this home — anchor on the CMA, not the ratio." (Catches both extreme teaser prices and genuinely overpriced listings — for the latter the stale path + CMA carry the story.)

### 5.5 Worked example
List $2,050,000 in 94087; 14 fresh comps, weighted p25/50/75 = 1.06/1.12/1.18; city p = 1.04/1.09/1.15, n_eff = 9.1, k = 8:
`p50_final = (9.1·1.12 + 8·1.09)/17.1 = 1.106` ⇒ point ≈ $2.27M, range ≈ [2050k×1.051, 2050k×1.166] = **$2.15M – $2.39M**. CMA estimate $2.20M is within 7% of $2.27M ⇒ no flag.

### 5.6 Pricing posture & market-evidence adjustment (`engine/posture.py`, `engine/exposure.py`)
List price is a signal, not a floor (01 §1): bait pricing is the convention, not a law. The buyer's question is "will this sell below asking, and by how much?", and the evidence that answers it is market behaviour — not another value estimate. Two mechanisms, kept separate:

**A. Posture = a calibrated probability.** Every signal is a log-odds contribution to one logit; `p_below_list = sigmoid(logit)` is P(sells below the current asking price | it sells). Signals (knobs in `posture.py`, recorded and re-fitted by every backtest run — docs/10 §4):

| signal | points (log-odds; + = sells below asking) | when |
|---|---|---|
| exposure | `EXPOSURE_LOGIT` knots `(0.5, −0.98) (1.25, +0.66) (4.0, +1.01)` over `ratio`, linear between, flat outside | always, when an area median exists |
| price cut | `+0.14` once | `had_cut`: an observed downward `price_change`, a dated Realtor `price_history` cut in the current episode, or a relist below the previous ask |
| relist | `+0.20` | `episode_count > 1` — and the exposure clock **restarts** with the new episode |
| offer date passed | `+0.25` | `offer_due_at` + 2d grace elapsed, still active (live-only; an unfitted prior, not reconstructible as-of) |

`ratio` = exposure days / area median DOM (the median of the latest 24 Redfin city-level `median_dom` rows, pooled across every city in the geography — `exposure.area_median_dom`, one value for the whole area), where exposure days = days into the **current episode** for a relist and cumulative DOM otherwise. `engine/exposure.py` is the one extractor every consumer uses, live and as-of alike: spans come from the group's episode rows with `list_date ≤ as_of`, so a replay and the served page agree on a quiet listing and a later episode can never leak into an earlier as-of. The curve is the shape the data has — P(sells below asking | still active at x × median), every scan-observed sale re-scored at every exposure point it passed through (the backtest's survival replay, docs/10 §4; scoring only at the moment a home is about to sell samples the winners and halves the odds for fresh listings):

| x × median | 0.25 | 0.5 | 0.75 | 1 | 1.25 | 1.5 | 2 | 2.5 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sold below asking | 26% | 28% | 44% | 54% | 63% | 67% | 69% | 68% | 70% | 75% | 77% | 80% |
| median sold/list | 1.057 | 1.052 | 1.000 | 0.989 | 0.978 | 0.975 | 0.973 | 0.972 | 0.973 | 0.971 | 0.971 | 0.966 |

A step through the first offer window (0.5× → 1.25×), a long plateau, and a slow climb past 4×. Weeks 3–8 add almost no evidence; a price cut or a relist adds almost none once exposure is known (at the same exposure, cut and never-cut homes clear below asking at the same rate — the current ask is judged on how long it has gone untaken, not on how it got there); and nothing reaches 85%, so the chip states the number instead of a confidence adjective.

Posture: `p ≥ 0.60` ⇒ **overpriced** (3 in 5 sell below asking); `p ≤ 0.40` ⇒ **underpriced** (bait — 3 in 5 sell at or above); else **near_market**; **unknown** without exposure data (no list date/DOM or no area median) — cuts and relists are still listed as facts, with no probability. Confidence on `max(p, 1−p)`: ≥ 0.80 high, ≥ 0.65 medium, else low. Worked values: fresh listing at 0.5× the median, no cut, p 0.27 (underpriced/medium); at the median 0.53 (near_market/low); 1.5× no cut 0.67 (overpriced/medium); 4× with a cut 0.76 (overpriced/medium); 6× with a cut and a passed offer date 0.80 (overpriced/high). Beside p the result carries `typical_sold_to_list` (`TYPICAL_SOLD_TO_LIST`: overpriced 0.973, near_market 1.000, underpriced 1.055 — the backtest-measured median clear per posture), `withdrawal_share` (0.24 once `ratio ≥ 2` — about a quarter of scan-observed campaigns that far past the median end withdrawn rather than pending, counted per campaign so a withdrawn attempt that relists and sells is a sale; a separate fact because p is conditional on a sale), `exposure` (days, episode_days, episode_count, cuts, cut_source, median_dom, ratio, offer_passed) and `value_gap_pct` = list / unadjusted blend − 1.

**List-vs-value is not a vote.** The blended point is 80% `list × p50`, so "list vs model value" mostly echoed the fresh/stale routing; and once exposure is known even the independent CMA carries no information about clearing asking (lingering homes sold below list 67% / 62% / 63% of the time with the CMA below / near / above list). It is shown, not scored. Estimate agreement = `(max−min)/median` over {unadjusted blend, own CMA, external AVMs} with the §7 thresholds — informational: it labels the UI and caps the offer recommendation's confidence at medium.

**B. Market-evidence adjustment** — exposure past the median at price P with no pending is evidence value ≤ P:
```
w = clip((ratio − 1.0) / (1.25 − 1.0), 0, 1)  (+0.25 if offer date passed; cap 1)
adjusted_point = (1−w) · blended_point + w · min(blended_point, 0.98 × list)
adjusted_high ≤ list × 1.02 once w ≥ 0.5;  low = min(low, point)
```
The ramp starts at the median because the first offer window is the test (listings still active past it clear below asking more often than not) and is fully credible by 1.25× — where the survival curve's step is complete — uses the same episode clock as the posture (a relist is a new test), never raises an estimate, and applies inside `valuation.predicted_sale` — every surface serves the adjusted number, with `unadjusted_point`/`rejection_weight` exposed alongside. Grid-searched on the backtest's decision-point replay (docs/10 §4): on the w > 0 rows the adjusted value's MdAPE (3.48%) edges list-as-of alone (3.57%) against 6.08% for the unadjusted blend, and over all rows 5.21% vs 6.19%; the 0.98 anchor sits on the realized median clear.

**Worked example (the motivating case — a literal gate in `test_posture.py`):** list $2.65M, blended value $2.93M, CMA $3.36M, 41 days vs median 10 (ratio 4.1), offer date passed, 0 cuts. logit = +1.01 (exposure) + 0.25 (offer passed) = **+1.26 ⇒ p 0.78 ⇒ overpriced, medium** — about 8 in 10 such homes sell below asking, typically ~2.7% under. w = 1.0 ⇒ adjusted point $2,597,000, high $2,703,000; value gap −9.6% (shown, not scored). The offer solver then recommends **underbid**, opening $2.46M–$2.57M, ceiling $2.65M — not the $3.53M that `1.05 × CMA` would have blessed. **The relist case:** 60 days in a withdrawn first episode, 5 days at the same ask in the new one (ratio 0.5), no cut ⇒ logit −0.98 + 0.20 = −0.78 ⇒ p 0.31 ⇒ **underpriced** — relists that fresh into their new episode sold below list only 17% of the time (median 1.16 of list), which is what a cumulative-DOM tally gets exactly backwards.

## 6. Offer back-solver (`engine/offer.py`)
Inputs: `buyer_profile` (+ per-listing overrides), appraisal proxy **E = market-adjusted blended value** (fallback: CMA, then list — `e_basis`), city tax rate. The profile carries a fixed **dollar** down payment and no monthly-payment ceiling, so the solver has one constraint:
- **Cash constraint with appraisal gap**: cash_needed(bid) = down_payment + closing(bid) + gap(bid), where `gap = min(max(0, bid − E), gap_tolerance_pct × E)` (lender funds only appraised value × LTV; overage beyond tolerated gap is treated as infeasible, not free — with a healthy cash pile the effective ceiling is `(1+g)·E`). Solve cash_needed(bid) = cash_available by bisection on [0.5·E, 1.5·E].
- `max_defensible_bid = min(P_cash, down_payment / 0.20)` — the second term is the jumbo-lender floor (≥20% down in the $2–3M band); without a payment ceiling in the profile it is the only lender-side brake, and with a healthy cash pile it is usually what binds (`ltv_capped`). This is the **cash ceiling** — what the buyer *can* pay.
- **Recommendation layer** (`recommend()`) — what the buyer *should* do, keyed on posture (§5.6):

| posture | recommendation | opening (× list) | ceiling |
|---|---|---|---|
| overpriced | **underbid** | 0.93–0.97 (lingering homes clear at a median ~0.973 of asking) | `min(max_bid, list, 1.02 × adjusted point)` — the near-market rule capped at list: weeks of no-takers is not the moment to pay a CMA premium |
| near_market / unknown | **at_list** | 0.97–1.00 | `min(max_bid, 1.02 × adjusted point)` |
| underpriced | **overbid** | 1.00–1.02 | `min(max_bid, adjusted high)` — value-justified even in a bidding war |

  **Escalation-clause cap = the ceiling**, not the cash max. The opening band is clamped to the value cap, so the verdict never says "open at X, ceiling below X".
- **Three limits, the lowest wins** (`limits` in the response, each as a price): **cash** (above for a listing; for the profile-only readout the largest P where `cash_available = down_payment + closing(P) + 6·PITI(P)`, the §8 reserves rule turned into a ceiling — linear per PMI branch; solve without PMI, re-solve with it if the answer lands below 20% down), the **20%-down lender floor** `down_payment / 0.20` (`ltv_capped`), and — once `annual_income` is entered — the **payment limit**: the largest P with `PITI(P) ≤ max_housing_payment` (§8), linear in P and PMI-free because the floor keeps every answer at ≥20% down (`payment_capped`). Without an income the payment limit is off and the verdict says so.
- **Profile-only inverse readout** (Affordability page, no listing so no E): the lowest of the three limits, verdict `profile_only` in plain words: "You can afford up to $X. That is where …" naming the binding limit.
- **Verdict generator** (Homebot-style plain language), first-match on recommendation: `profile_only`, `no_model`, `out_of_reach` (max bid below even the suggested opening), `underbid_lingering`, `at_list_disciplined`, `overbid_competitive`, `overbid_strong`. Modifier clauses appended in fixed order: CMA-below-list (CMA < 0.98 × list: "the list is a signal, not a floor"), estimate-divergence hedge ("value estimates disagree by N% — treat the point estimates as soft; the market-behaviour signals are the more reliable evidence", also caps confidence at medium), gap-capped, then the binding lender-side limit (LTV floor or payment limit). E.g.:
  - overbid_competitive: "Priced to spur bidding — likely sale $2.15–2.39M (median 111% of list). Your max defensible bid $2.31M is inside the likely range — competitive but disciplined. Open at $2.05M–$2.09M; escalate to $2.31M, not beyond."
  - out of reach: "…max defensible bid $2.05M is below the likely range floor $2.15M. Passing is reasonable; a preemptive knockout is not available to you."
  - underbid_lingering: "On market 87 days (area median 18), 2 price cut(s). About 7 in 10 homes with this history sell below asking, typically ~2.7% under — likely sale $1.99M–$2.07M (median 99% of list). Open at $1.91M–$1.99M with comps attached; your ceiling is $2,050,000 — do not chase the CMA ($3,360,000)." A relist reads "On market 33 days this episode (120 cumulative over 2 episodes; area median 18), relisted below the previous ask…"; the evidence line comes off the `PostureResult.exposure` payload, so the verdict and the posture panel can never disagree.

## 7. Multi-AVM spread
Latest `avm_snapshots` per source rendered on one horizontal axis. `spread = (max−min)/median`. spread > 15% ⇒ "high uncertainty — comp quality matters more than any single number"; < 7% ⇒ "estimates agree". Own-CMA is visually distinguished. The same thresholds drive the §5.6 agreement level (which caps the offer recommendation's confidence at medium; it does not move the posture — list-vs-value is reported there, never scored).

## 8. Affordability (`engine/affordability.py`)
```
loan = P − down_payment (dollars, from buyer_profile);  r = rate/12;  n = 360
P&I = loan·r/(1−(1+r)^−n)
tax_monthly = P · effective_rate(city) / 12          # geography: city override → county rate → DEFAULT_TAX_RATE 0.0125 for a city outside the geography
PMI = 0.006·loan/12 if down_payment < 0.20·P else 0
PITI = P&I + tax_monthly + insurance + PMI + HOA (+ the pack's optional-peril rider if toggled — earthquake under the `ca` pack, default $150/mo est)
closing(P) ≈ 1.5% of P (buyer-side: title, escrow, recording, lender fees; local transfer taxes vary — the geography's county `transfer_tax_note` says who customarily pays; keep 1.5% flat estimate, note in UI)
```
- **Reassessment / supplemental-tax warning** (always shown; wording from the pack's `affordability.supplemental_tax_note` — the `ca` pack describes California's supplemental bill, the `us` base tells the buyer to confirm reassessment timing with the assessor): supplemental ≈ `(P − seller_assessed_value) × rate`; the seller's assessed value is unknown, so the note is formatted with the heuristic amount `P × rate / 2` — a fixed six months to the next roll (`calc()` passes `amount=round(price × tax_rate / 2)` into the pack's note).
- **Reserves check** (`calc()`): `reserves_after = cash_available − down − closing`, `reserves_ok` when `reserves_after ≥ 6 × PITI`, else warn. There is no appraisal-gap term here — the gap tolerance applies inside the offer solver's cash constraint (§6), not the calculator.
- **Payment limit** (`max_housing_payment`): `DTI_MAX × annual_income / 12 − monthly_debts`, with `DTI_MAX = 0.43` (the back-end debt-to-income ceiling of a qualified mortgage; jumbo lenders often sit lower, so it is a ceiling, not a promise). `annual_income = 0` means not entered: no limit, `payment_limit`/`payment_ok` null. The calculator reports whether a price's PITI fits it (whole dollars).
- Worked example: P = $2.2M, $440k down (20%), 6.5%, Sunnyvale 1.28%, ins $250, HOA 0:
  loan $1.76M → P&I $11,124; tax $2,347; PITI ≈ **$13,721/mo**; closing ≈ $33k; cash needed ≈ $473k.

## 9. Months of supply (`engine/supply.py`)

Months of supply (MOS) = active inventory ÷ monthly closed-sale rate: how long it would take to clear every listed home at the current pace. Computation lives in the `market-supply` pipeline (05 §3.5); this module holds only the two interpretation helpers, because the raw number is half the signal.

**Bands** (`classify_band`) — `very_tight <1.0 | tight 1.0–2.0 | balancing 2.0–4.0 | soft ≥4.0`. Deliberately **not** the national NAR convention (<3 seller's / 3–6 balanced / >6 buyer's): every target ZIP sits under 3 months, so national bands would paint the whole peninsula one colour and teach the buyer nothing. Calibrated to the observed 2012–2026 Redfin distribution for the target geos.

**Historical percentile** (`pct_rank`) — fraction of the geo's own trailing-3-year distribution at or below the current value. This is the signal the absolute band cannot give: 1.1 months is tight in absolute terms but *loose* for a ZIP whose own three-year range is 0.3–1.2. Returns `None` below `MIN_HISTORY_POINTS` (12) observations — a percentile over a handful of points is noise dressed as precision.

**Window helpers** (`window_months`, `window_end`) — Redfin ZIP and city rows span 3 calendar months and `market_metrics.period_start` stores the window *start* (03 §1.1), so the UI's as-of label needs the covered months to show the window's end.

**Live windows** (`LIVE_WINDOWS`, `live_period`, `months_ago`) — the now-cast (05 §3.5) is computed for 3, 6, 9 and 12 trailing calendar months and stored as `period='3m'|'6m'|'9m'|'12m'`. `months_ago` walks calendar months rather than 30-day multiples, clamping the 31st to a shorter month, so a 12-month window is exactly a year and never double-counts a season.

- Worked example: ZIP 94402, window `2026-06-01`–`2026-08-31`, Redfin publishes inventory 12, homes_sold 67 (a 3-month total) and months of supply **0.5** (= `3 × 12 / 67` = 0.54, which Redfin rounds to 0.1) → `classify_band` → `very_tight`; the same ratio over the ZIP's own 3-year history sits in the bottom of its range. The live figure for the same ZIP on 2026-09-26 differs — a different window, no lag, and only homes the scanner has seen.
