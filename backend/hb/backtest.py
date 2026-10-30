"""Golden backtest — the CMA credibility gate (docs/10 §4).

For each recent sale, re-run the CMA and overbid model **as of the day before it
was listed** — every input strictly date-filtered so there is no leakage — and
compare the predictions to what actually happened:
- blended predicted value (valuation.CMA_WEIGHT·CMA + rest·overbid, the number
  the product shows): median absolute % error vs the real sale price (pass ≤ 8%);
- CMA-only MdAPE reported as a diagnostic (no threshold);
- overbid: share of real sale prices inside the calibrated predicted range
  (pass ≥ 50%).

Pass B replays the posture layer (docs/06 §5.6) on every sale whose pending
transition the scan observed, two ways:
- **Survival replay** — each sale re-scored as-of every ``SURVIVAL_RATIOS``
  exposure point it passed through before going pending. That is the population
  a live chip faces (a lingering home shows up at every point, a hot one at the
  first few), so it is what the calibration table, the per-tier precision and
  the knob re-fit are computed on. Posture-only: no valuation is needed.
- **Decision-point replay** — as-of ``MIDFLIGHT_LAG_DAYS`` (7) before pending,
  with the CMA + overbid blend, to score the market-adjusted value against the
  unadjusted blend and against list-as-of. (Scoring posture only there samples
  homes about to sell and halves the below-asking odds of fresh listings — the
  survival replay exists because of that.)

`calibration_ok` is a soft gate — a reported line, not an exit code — until a
few runs confirm it is stable. The re-fit uses the classifier's own
``posture.features`` so the suggested knobs and the shipped ones are the same
model.

Runs against real ingested `sales` only — no synthetic data. If the DB lacks ≥ n
qualifying sales the report says so and the gate stays unmet. Output goes to
`data/backtests/<date>.md` with the tuning-knob values so a failing run can be
tuned and re-run.
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.models import Listing, ListingGroup, Property, Sale
from hb.engine import adjustments, cma, exposure, overbid, posture, valuation

log = logging.getLogger(__name__)

WINDOW_DAYS = 60
MDAPE_THRESHOLD = 0.08
COVERAGE_THRESHOLD = 0.50
MIN_PRIOR_COMPS = 3  # "sufficient prior data" (docs/10 §4): skip sales the model
                     # can't fairly value as-of because too few comps had closed
# pass B — posture calibration
MIDFLIGHT_LAG_DAYS = 7          # decision point: a week before the home went pending
MIDFLIGHT_WINDOW_DAYS = 365
SURVIVAL_RATIOS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0)
CALIBRATION_EDGES = (0.0, 0.20, 0.35, 0.40, 0.60, 0.65, 0.80, 1.0001)  # the posture tier boundaries
CALIBRATION_MIN_N = 50          # a bucket is judged only with this many rows (below it the
                                # binomial noise alone exceeds the tolerance; still reported)
CALIBRATION_TOL = 0.10          # |realized − mean predicted| per judged bucket
MEDIUM_PRECISION_MIN = 0.60     # overpriced medium+high: share that sold below asking
PRECISION_MIN_N = 30
FIT_MIN_N = 100                 # re-fit the knobs only with this many scored rows


def _knobs() -> dict:
    return {
        "valuation.cma_weight (blend: cma vs overbid)": valuation.CMA_WEIGHT,
        "overbid.range_widen": overbid.RANGE_WIDEN,
        "cma.m_factor": adjustments.M_FACTOR,
        "cma.f_time_half_life_days": cma.F_TIME_HALF_LIFE_DAYS,
        "cma.range_floor_pct": cma.RANGE_FLOOR_PCT,
        "cma.base_radius_mi": cma.BASE_RADIUS_MI,
        "cma.base_months": cma.BASE_MONTHS,
        "overbid.weight_half_life_days": overbid.WEIGHT_HALF_LIFE_DAYS,
        "overbid.shrink_k": overbid.SHRINK_K,
        "overbid.list_tolerance": overbid.LIST_TOLERANCE,
        "overbid.stale_dom_multiplier": overbid.STALE_DOM_MULTIPLIER,
        "posture.exposure_logit": posture.EXPOSURE_LOGIT,
        "posture.cut_logit": posture.CUT_LOGIT,
        "posture.relist_logit": posture.RELIST_LOGIT,
        "posture.offer_passed_logit": posture.OFFER_PASSED_LOGIT,
        "posture.over_p": posture.OVER_P,
        "posture.under_p": posture.UNDER_P,
        "posture.high_p": posture.HIGH_P,
        "posture.medium_p": posture.MEDIUM_P,
        "posture.typical_sold_to_list": posture.TYPICAL_SOLD_TO_LIST,
        "posture.withdrawal_ratio": posture.WITHDRAWAL_RATIO,
        "posture.withdrawal_share": posture.WITHDRAWAL_SHARE,
        "posture.w_ramp_start": posture.W_RAMP_START,
        "posture.w_ramp_full": posture.W_RAMP_FULL,
        "posture.no_sale_anchor": posture.NO_SALE_ANCHOR,
        "posture.adj_range_high_cap": posture.ADJ_RANGE_HIGH_CAP,
        "backtest.midflight_lag_days": MIDFLIGHT_LAG_DAYS,
        "backtest.survival_ratios": SURVIVAL_RATIOS,
        "backtest.calibration_tol": CALIBRATION_TOL,
        "backtest.medium_precision_min": MEDIUM_PRECISION_MIN,
    }


@dataclass
class BacktestReport:
    n_candidates: int
    n_used: int
    mdape: float | None
    coverage: float | None
    passed: bool
    knobs: dict
    rows: list[dict] = field(default_factory=list)
    note: str = ""
    n_thin: int = 0            # candidates dropped for < MIN_PRIOR_COMPS as-of comps
    history_span: str = ""     # earliest..latest sale_date in the DB
    cma_mdape: float | None = None  # diagnostic: pure-CMA error, no threshold
    midflight: dict | None = None   # pass B: posture calibration + market-adjustment diagnostics


def run_backtest(session: Session, n: int = 20, today: date | None = None) -> BacktestReport:
    today = today or date.today()
    min_date = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    candidates = session.execute(
        select(Sale, Listing, Property)
        .join(Property, Sale.property_id == Property.id)
        .join(Listing, Sale.listing_id == Listing.id)
        .where(
            Property.zip.in_(settings.target_zips),
            Property.property_type == "single_family",
            Sale.sale_date >= min_date,
            Listing.list_date.is_not(None),
        )
        .order_by(Sale.sale_date.desc())
    ).all()

    log.info("backtest: evaluating %d candidate sales as-of their list date…", len(candidates))
    rows: list[dict] = []
    n_thin = 0
    for i, (sale, listing, prop) in enumerate(candidates, 1):
        if i % 25 == 0:
            log.info("backtest: %d/%d candidates (%d usable so far)", i, len(candidates), len(rows))
        as_of = (date.fromisoformat(listing.list_date[:10]) - timedelta(days=1)).isoformat()
        if as_of >= sale.sale_date[:10]:
            continue
        actual = sale.sale_price
        cma_result = cma.run(session, prop.id, as_of=as_of, persist=False)
        included = [c for c in cma_result.comps if c.included]
        if cma_result.estimate is None or len(included) < MIN_PRIOR_COMPS:
            n_thin += 1  # insufficient prior data to value this sale fairly
            continue
        ob = overbid.predict(session, listing, prop, cma_estimate=cma_result.estimate, as_of=as_of)
        ob_point = ob.predicted["point"] if ob.predicted else None
        predicted = valuation.blended_value(cma_result.estimate, ob_point)
        ape = abs(predicted - actual) / actual
        cma_ape = abs(cma_result.estimate - actual) / actual
        covered = bool(ob.predicted and ob.predicted["low"] <= actual <= ob.predicted["high"])
        rows.append({
            "address": prop.address_norm.title(), "as_of": as_of, "actual": actual,
            "cma_estimate": cma_result.estimate, "predicted": predicted,
            "n_comps": len(included), "ape": round(ape, 4), "cma_ape": round(cma_ape, 4),
            "overbid_low": ob.predicted["low"] if ob.predicted else None,
            "overbid_high": ob.predicted["high"] if ob.predicted else None,
            "covered": covered,
        })

    n_used = len(rows)
    mdape = statistics.median(r["ape"] for r in rows) if rows else None
    cma_mdape = statistics.median(r["cma_ape"] for r in rows) if rows else None
    coverage = (sum(r["covered"] for r in rows) / n_used) if n_used else None
    passed = bool(
        n_used >= n and mdape is not None and mdape <= MDAPE_THRESHOLD
        and coverage is not None and coverage >= COVERAGE_THRESHOLD
    )
    span = session.execute(select(func.min(Sale.sale_date), func.max(Sale.sale_date))).one()
    history_span = f"{span[0]}..{span[1]}" if span[0] else "(no sales)"
    note = "" if n_used >= n else (
        f"INSUFFICIENT PRIOR DATA: only {n_used} of {len(candidates)} recent sales had "
        f"≥ {MIN_PRIOR_COMPS} comps closed as-of their list date (need ≥ {n}); "
        f"{n_thin} were skipped as comp-starved. The sales history spans {history_span} — "
        f"as-of backtesting needs several months of prior sales, so run `hb pipeline "
        f"listing-scan` daily to accumulate depth, then re-run. The valuation math itself is "
        f"verified by the §4.3/§5.5 unit gates."
    )

    # pass B — independent of pass-A usability: a long-listed home is often
    # comp-starved at its list date yet perfectly evaluable mid-flight
    mid_candidates = _midflight_candidates(session, today)
    log.info("backtest: pass B over %d scan-observed pendings…", len(mid_candidates))
    survival = _survival_rows(session, mid_candidates)
    decision: list[dict] = []
    for i, (sale, listing, prop) in enumerate(mid_candidates, 1):
        if i % 50 == 0:
            log.info("backtest: pass B decision-point %d/%d", i, len(mid_candidates))
        row = _midflight_row(session, sale, listing, prop)
        if row is not None:
            decision.append(row)

    return BacktestReport(len(candidates), n_used, mdape, coverage, passed, _knobs(), rows,
                          note, n_thin, history_span, cma_mdape=cma_mdape,
                          midflight=_midflight_summary(decision, survival,
                                                       _withdrawal_share(session)))


# --- pass B -----------------------------------------------------------------------

def _midflight_candidates(session: Session, today: date) -> list:
    """Sales whose pending transition the scan observed — `pending_date − lag`
    is then a moment the listing was really still active (sale_date − lag can
    land inside escrow)."""
    min_date = (today - timedelta(days=MIDFLIGHT_WINDOW_DAYS)).isoformat()
    return session.execute(
        select(Sale, Listing, Property)
        .join(Property, Sale.property_id == Property.id)
        .join(Listing, Sale.listing_id == Listing.id)
        .where(
            Property.zip.in_(settings.target_zips),
            Property.property_type == "single_family",
            Sale.sale_date >= min_date,
            Listing.list_date.is_not(None),
            Listing.pending_date.is_not(None),
        )
        .order_by(Sale.sale_date.desc())
    ).all()


def _posture_row(session: Session, sale: Sale, listing: Listing, prop: Property,
                 as_of: str, with_value: bool) -> dict | None:
    """Replay the posture layer as-of `as_of`. `with_value` also runs the CMA +
    overbid blend so the market-adjusted value can be scored. All inputs
    as-of-disciplined; the offer-date signal is live-only and therefore absent."""
    predicted = None
    cma_est = None
    unadj = None
    if with_value:
        cma_mid = cma.run(session, prop.id, as_of=as_of, persist=False)
        cma_est = cma_mid.estimate
        ob = overbid.predict(session, listing, prop, cma_estimate=cma_est, as_of=as_of)
        if ob.predicted:
            unadj = valuation.blended_value(cma_est, ob.predicted["point"])
            predicted = {"low": min(ob.predicted["low"], unadj), "point": unadj,
                         "high": max(ob.predicted["high"], unadj)}
    post = posture.classify(session, listing, prop, predicted, cma_estimate=cma_est, as_of=as_of)
    list_asof = posture.list_price_as_of(session, listing, as_of)
    actual = sale.sale_price
    ex = post.exposure or {}
    adjusted = post.adjusted["point"] if post.adjusted else None

    def _ape(value):
        return round(abs(value - actual) / actual, 4) if value else None

    return {
        "address": prop.address_norm.title(), "as_of": as_of, "actual": actual,
        "list_asof": list_asof, "p_below_list": post.p_below_list,
        "posture": post.posture, "confidence": post.confidence,
        "w": post.rejection_weight, "ratio": ex.get("ratio"),
        "had_cut": ex.get("cut_source") is not None,
        "relisted": (ex.get("episode_count") or 1) > 1,
        "below": (actual < list_asof) if list_asof else None,
        "sold_to_list": round(actual / list_asof, 4) if list_asof else None,
        "unadjusted": unadj, "adjusted": adjusted,
        "ape_unadjusted": _ape(unadj), "ape_adjusted": _ape(adjusted),
        "ape_list": _ape(list_asof),
    }


def _midflight_row(session: Session, sale: Sale, listing: Listing,
                   prop: Property) -> dict | None:
    """Decision-point replay: MIDFLIGHT_LAG_DAYS before the listing went pending,
    with the valuation, so the market-adjusted value can be scored."""
    mid = (date.fromisoformat(listing.pending_date[:10])
           - timedelta(days=MIDFLIGHT_LAG_DAYS)).isoformat()
    if mid <= listing.list_date[:10]:
        return None  # too young at that lag to have an exposure story
    return _posture_row(session, sale, listing, prop, mid, with_value=True)


def _survival_rows(session: Session, candidates: list) -> list[dict]:
    """Posture-only replay of every sale at each SURVIVAL_RATIOS exposure point
    it passed through before going pending. The grid is laid with the area
    median as-of the pending date; each row's own ratio comes from
    `exposure.inputs` as-of that point (and a point with no median yet is
    skipped by the classifier)."""
    rows: list[dict] = []
    for sale, listing, prop in candidates:
        median = exposure.area_median_dom(session, listing.pending_date[:10])
        if not median:
            continue
        start = date.fromisoformat(listing.list_date[:10])
        pend = date.fromisoformat(listing.pending_date[:10])
        for ratio in SURVIVAL_RATIOS:
            as_of = start + timedelta(days=round(ratio * median))
            if as_of <= start or as_of >= pend:
                continue
            row = _posture_row(session, sale, listing, prop, as_of.isoformat(), with_value=False)
            if row is not None and row["p_below_list"] is not None and row["below"] is not None:
                row["grid"] = ratio
                rows.append(row)
    return rows


def _share(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "n": n,
        "below": sum(1 for r in rows if r["below"]),
        "below_share": round(sum(1 for r in rows if r["below"]) / n, 3) if n else None,
        "median_sold_to_list": (round(statistics.median(r["sold_to_list"] for r in rows), 3)
                                if n else None),
    }


def _tier_table(rows: list[dict]) -> dict:
    tiers: dict[str, list[dict]] = {}
    for r in rows:
        tiers.setdefault(f"{r['posture']}/{r['confidence']}", []).append(r)
    return {k: _share(v) for k, v in sorted(tiers.items())}


def _calibration_table(rows: list[dict]) -> list[dict]:
    out = []
    for lo, hi in zip(CALIBRATION_EDGES, CALIBRATION_EDGES[1:]):
        g = [r for r in rows if lo <= r["p_below_list"] < hi]
        entry = {"lo": lo, "hi": min(hi, 1.0), **_share(g), "mean_p": None, "ok": None}
        if g:
            mean_p = statistics.mean(r["p_below_list"] for r in g)
            entry["mean_p"] = round(mean_p, 3)
            if len(g) >= CALIBRATION_MIN_N:
                # a bucket is off only beyond the tolerance AND beyond two
                # binomial standard errors — thin buckets are noisy, not wrong
                tol = max(CALIBRATION_TOL, 2 * (mean_p * (1 - mean_p) / len(g)) ** 0.5)
                entry["ok"] = abs(entry["below_share"] - mean_p) <= tol
        out.append(entry)
    return out


def _fit_posture_logit(rows: list[dict]) -> dict | None:
    """Ridge-stabilised IRLS logistic fit of `below` on `posture.features` —
    the same design the shipped knobs came from — so each run can say what the
    knobs *would* be on its own rows. None below FIT_MIN_N."""
    scored = [r for r in rows if r["ratio"] is not None]
    if len(scored) < FIT_MIN_N:
        return None
    x = np.array([posture.features(r["ratio"], r["had_cut"], r["relisted"]) for r in scored])
    y = np.array([1.0 if r["below"] else 0.0 for r in scored])
    beta = np.zeros(x.shape[1])
    for _ in range(30):
        p = 1.0 / (1.0 + np.exp(-x @ beta))
        w = p * (1 - p)
        hess = x.T @ (x * w[:, None]) + 1e-3 * np.eye(x.shape[1])
        grad = x.T @ (p - y)
        step = np.linalg.solve(hess, grad)
        beta -= step
        if np.max(np.abs(step)) < 1e-6:
            break
    b0, b1, b2, b_cut, b_relist = (float(b) for b in beta)
    return {
        "n": len(scored),
        "exposure_logit": posture.knots_from_coefficients(b0, b1, b2),
        "cut_logit": round(b_cut, 2),
        "relist_logit": round(b_relist, 2),
        "n_relisted": int(sum(r["relisted"] for r in scored)),
        "n_cut": int(sum(r["had_cut"] for r in scored)),
    }


def _withdrawal_share(session: Session) -> dict | None:
    """Among scan-observed campaigns (listing groups) exposed past
    `posture.WITHDRAWAL_RATIO` × the area median, the share whose LAST episode
    ended withdrawn rather than pending or sold — the fact the UI quotes beside
    `p_below_list` (which is conditional on a sale). Counted per campaign, not
    per episode: a withdrawn first attempt that relisted and sold is a sale."""
    median = exposure.area_median_dom(session, None)
    if not median:
        return None
    rows = session.execute(
        select(ListingGroup.id, Listing.list_date, Listing.pending_date,
               Listing.delist_date, Listing.status)
        .join(Listing, Listing.listing_group_id == ListingGroup.id)
        .join(Property, Listing.property_id == Property.id)
        .where(Property.zip.in_(settings.target_zips),
               Property.property_type == "single_family",
               Listing.list_date.is_not(None))
        .order_by(ListingGroup.id, Listing.list_date)
    ).all()
    campaigns: dict[str, list[tuple]] = {}
    for gid, *episode in rows:
        campaigns.setdefault(gid, []).append(tuple(episode))
    n = withdrawn = 0
    for episodes in campaigns.values():
        # exposure runs to pending or delisting — never to the sale (escrow is
        # not market time) — and every episode must have an observed end
        days = 0
        for list_date, pending_date, delist_date, status in episodes:
            end = pending_date if status in ("sold", "pending") else delist_date
            if not end:
                days = None
                break
            days += max(0, (date.fromisoformat(end[:10])
                            - date.fromisoformat(list_date[:10])).days)
        if days is None or days <= posture.WITHDRAWAL_RATIO * median:
            continue
        n += 1
        withdrawn += episodes[-1][3] == "delisted"
    return {"n": n, "share": round(withdrawn / n, 3) if n else None,
            "ratio": posture.WITHDRAWAL_RATIO}


def _midflight_summary(decision: list[dict], survival: list[dict],
                       withdrawal: dict | None) -> dict | None:
    if not decision and not survival:
        return None
    calibration = _calibration_table(survival)
    over = [r for r in survival if r["posture"] == "overpriced"
            and r["confidence"] in ("medium", "high")]
    precision = {
        "n": len(over),
        "precision": round(sum(1 for r in over if r["below"]) / len(over), 3) if over else None,
        "ok": None,
    }
    if len(over) >= PRECISION_MIN_N:
        precision["ok"] = precision["precision"] >= MEDIUM_PRECISION_MIN
    checks = [b["ok"] for b in calibration if b["ok"] is not None]
    if precision["ok"] is not None:
        checks.append(precision["ok"])
    calibration_ok = all(checks) if checks else None

    over_all = [r for r in survival if r["posture"] == "overpriced"]
    split = {
        "relisted": _share([r for r in over_all if r["relisted"]]),
        "with_cut": _share([r for r in over_all if r["had_cut"]]),
        "no_cut_single_episode": _share([r for r in over_all
                                         if not r["had_cut"] and not r["relisted"]]),
    }

    def _mdape(rows, key):
        vals = [r[key] for r in rows if r[key] is not None]
        return statistics.median(vals) if vals else None

    valued = [r for r in decision if r["unadjusted"] is not None and r["adjusted"] is not None]
    stale = [r for r in valued if r["w"] > 0]
    return {
        "n": len(decision),
        "n_survival": len(survival),
        "curve": [{"ratio": ratio, **_share([r for r in survival if r["grid"] == ratio])}
                  for ratio in SURVIVAL_RATIOS],
        "tiers": _tier_table(survival),
        "calibration": calibration,
        "overpriced_precision": precision,
        "overpriced_split": split,
        "calibration_ok": calibration_ok,
        "fit": _fit_posture_logit(survival),
        "decision_tiers": _tier_table([r for r in decision if r["below"] is not None]),
        "n_valued": len(valued),
        "mdape_unadjusted": _mdape(valued, "ape_unadjusted"),
        "mdape_adjusted": _mdape(valued, "ape_adjusted"),
        "mdape_list": _mdape(valued, "ape_list"),
        "n_stale": len(stale),
        "mdape_unadjusted_stale": _mdape(stale, "ape_unadjusted"),
        "mdape_adjusted_stale": _mdape(stale, "ape_adjusted"),
        "mdape_list_stale": _mdape(stale, "ape_list"),
        "withdrawal": withdrawal,
        "rows": decision,
    }


# --- report ------------------------------------------------------------------------

def _p(x) -> str:
    return f"{x:.2%}" if x is not None else "n/a"


def _tier_lines(tiers: dict) -> list[str]:
    lines = ["", "| tier | n | sold below asking | median sold/list |", "|---|---|---|---|"]
    for k, v in tiers.items():
        lines.append(f"| {k} | {v['n']} | {_p(v['below_share'])} | {v['median_sold_to_list']} |")
    return lines


def _render_midflight(mf: dict) -> list[str]:
    ok = mf["calibration_ok"]
    gate = "PASS ✅" if ok else "FAIL ❌" if ok is False else "n/a (too few rows to judge)"
    prec = mf["overpriced_precision"]
    lines = [
        "", "## Mid-flight / posture calibration (pass B — soft gate)", "",
        f"- Survival replay: **{mf['n_survival']}** (sale, exposure point) rows over "
        f"{len(SURVIVAL_RATIOS)} grid ratios of the area median, each sale re-scored as-of "
        f"every point it passed through before pending (offer-date signal is live-only)",
        f"- **Calibration: {gate}** — every p bucket with n ≥ {CALIBRATION_MIN_N} within "
        f"±{CALIBRATION_TOL:.0%} of its realized below-asking share, and overpriced "
        f"medium+high precision ≥ {MEDIUM_PRECISION_MIN:.0%} at n ≥ {PRECISION_MIN_N}",
        f"- Overpriced (medium+high) sold below asking: "
        f"**{_p(prec['precision'])}** (n={prec['n']})",
    ]
    wd = mf.get("withdrawal")
    if wd and wd["share"] is not None:
        lines.append(f"- Withdrawn rather than sold, episodes past {wd['ratio']:.0f}× the area "
                     f"median: **{wd['share']:.0%}** (n={wd['n']}; shipped knob "
                     f"`posture.withdrawal_share` = {posture.WITHDRAWAL_SHARE})")
    lines += ["", "| exposure (× median) | n | sold below asking | median sold/list |",
              "|---|---|---|---|"]
    for c in mf["curve"]:
        if c["n"]:
            lines.append(f"| {c['ratio']} | {c['n']} | {_p(c['below_share'])} "
                         f"| {c['median_sold_to_list']} |")
    lines += ["", "| p bucket | n | mean p | sold below asking | median sold/list | ok |",
              "|---|---|---|---|---|---|"]
    for b in mf["calibration"]:
        okc = "✅" if b["ok"] else "❌" if b["ok"] is False else "—"
        lines.append(f"| {b['lo']:.2f}–{b['hi']:.2f} | {b['n']} | "
                     f"{b['mean_p'] if b['mean_p'] is not None else 'n/a'} | "
                     f"{_p(b['below_share'])} | {b['median_sold_to_list'] or 'n/a'} | {okc} |")
    lines += _tier_lines(mf["tiers"])
    sp = mf["overpriced_split"]
    lines += ["", "Overpriced-classified by evidence: "
              + "; ".join(f"{k.replace('_', ' ')} {v['below']}/{v['n']} below asking"
                          for k, v in sp.items())]
    fit = mf.get("fit")
    if fit:
        lines += ["", f"Re-fit on this run's rows (n={fit['n']}, {fit['n_cut']} with a cut, "
                  f"{fit['n_relisted']} relisted) vs shipped: `exposure_logit` "
                  f"{fit['exposure_logit']} vs {posture.EXPOSURE_LOGIT}; `cut_logit` "
                  f"{fit['cut_logit']} vs {posture.CUT_LOGIT}; `relist_logit` "
                  f"{fit['relist_logit']} vs {posture.RELIST_LOGIT}"]
    else:
        lines += ["", f"Re-fit skipped (needs ≥ {FIT_MIN_N} scored rows)."]
    lines += [
        "", f"### Decision point — as-of {MIDFLIGHT_LAG_DAYS} days before pending (n={mf['n']})", "",
        f"- MdAPE, valued rows (n={mf['n_valued']}): unadjusted **{_p(mf['mdape_unadjusted'])}** "
        f"vs market-adjusted **{_p(mf['mdape_adjusted'])}** vs list-as-of "
        f"**{_p(mf['mdape_list'])}**",
        f"- MdAPE, rejection-weight > 0 subset (n={mf['n_stale']}): unadjusted "
        f"**{_p(mf['mdape_unadjusted_stale'])}** vs adjusted **{_p(mf['mdape_adjusted_stale'])}** "
        f"vs list-as-of **{_p(mf['mdape_list_stale'])}** — adjusted must not be worse here",
        "- Posture tiers at the decision point (samples homes about to sell — fresh buckets "
        "read optimistic here; the survival table above is the calibrated one):",
    ]
    lines += _tier_lines(mf["decision_tiers"])
    lines += ["", "| address | as-of | actual | list as-of | p below | posture | below | "
              "unadjusted | adjusted | w |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in mf["rows"]:
        lines.append(
            f"| {r['address']} | {r['as_of']} | {r['actual']:,} "
            f"| {f'{r['list_asof']:,}' if r['list_asof'] else 'n/a'} "
            f"| {r['p_below_list'] if r['p_below_list'] is not None else 'n/a'} "
            f"| {r['posture']}/{r['confidence']} "
            f"| {'yes' if r['below'] else 'no' if r['below'] is False else 'n/a'} "
            f"| {f'{r['unadjusted']:,}' if r['unadjusted'] else 'n/a'} "
            f"| {f'{r['adjusted']:,}' if r['adjusted'] else 'n/a'} | {r['w']:.2f} |"
        )
    return lines


def render_markdown(report: BacktestReport, today: date | None = None) -> str:
    today = today or date.today()
    lines = [
        f"# Golden backtest — {today.isoformat()}",
        "",
        f"- Candidate sales (last {WINDOW_DAYS} days, target ZIPs): **{report.n_candidates}**",
        f"- Sales history in DB: **{report.history_span}**",
        f"- Usable (≥ {MIN_PRIOR_COMPS} comps closed as-of the list date): **{report.n_used}** "
        f"({report.n_thin} skipped as comp-starved)",
        f"- Predicted-value MdAPE ({valuation.CMA_WEIGHT:.1f}·CMA + "
        f"{1 - valuation.CMA_WEIGHT:.1f}·overbid blend): "
        f"**{f'{report.mdape:.2%}' if report.mdape is not None else 'n/a'}** "
        f"(pass ≤ {MDAPE_THRESHOLD:.0%})",
        f"- CMA-only MdAPE (diagnostic, no threshold): "
        f"**{f'{report.cma_mdape:.2%}' if report.cma_mdape is not None else 'n/a'}**",
        f"- Calibrated-range coverage (p25–p75 widened ±{overbid.RANGE_WIDEN:.0%}, "
        f"docs/06 §5.4): **{f'{report.coverage:.0%}' if report.coverage is not None else 'n/a'}** "
        f"(pass ≥ {COVERAGE_THRESHOLD:.0%})",
        f"- **Gate: {'PASS ✅' if report.passed else 'FAIL ❌'}**",
    ]
    if report.note:
        lines += ["", f"> {report.note}"]
    if report.midflight:
        lines += _render_midflight(report.midflight)
    lines += ["", "## Tuning knobs", ""]
    lines += [f"- `{k}` = {v}" for k, v in report.knobs.items()]
    lines += ["", "## Per-sale results", "",
              "| address | as-of | actual | CMA est | predicted | comps | APE | overbid range | covered |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in report.rows:
        rng = (f"{r['overbid_low']:,}–{r['overbid_high']:,}"
               if r["overbid_low"] is not None else "n/a")
        lines.append(
            f"| {r['address']} | {r['as_of']} | {r['actual']:,} | {r['cma_estimate']:,} "
            f"| {r['predicted']:,} | {r['n_comps']} | {r['ape']:.2%} | {rng} "
            f"| {'yes' if r['covered'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def write_report(report: BacktestReport, today: date | None = None) -> str:
    today = today or date.today()
    out_dir = settings.data_dir / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{today.isoformat()}.md"
    path.write_text(render_markdown(report, today), encoding="utf-8")
    return str(path)
