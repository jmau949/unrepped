"""Feature adjustments — the transparent, line-item heart of the CMA (docs/06 §4).

Direction is always *adjust the comp toward the subject* (comp superior ⇒
subtract). Time adjustment is applied first (via ``price_index``) and every
subsequent line item is persisted so the workbench can render them — the
transparency is the product.

Worked example 06 §4.3 is a literal test (`test_adjustments.py`): the sum must
be $2,198,766. The exactness traps, all locked here:
- condition % is taken on the **time-adjusted** price (``adj_price0``), not the
  raw sale price;
- the lot coefficient is ``0.15 × m`` (dollars per lot-sqft), not ``0.15``;
- each line item is rounded to integer dollars.

Pure math (``adjust`` and the ``*_adjustment`` helpers) takes no session; the
marginal-$/sqft resolution reads ``market_metrics``/``sales`` and lives in the
session-taking helpers used by ``engine/cma.py``.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.db.models import MarketMetric
from hb.engine.price_index import _geo_candidates

# --- tunable knobs (recorded by the backtest report) -------------------------
M_FACTOR = 0.45              # default marginal $/sqft = M_FACTOR × median_ppsf
M_FACTOR_MIN, M_FACTOR_MAX = 0.30, 0.60  # configurable band (docs/01 §2.2)
FULL_BATH = 15_000
HALF_BATH = 8_000
LOT_COEF = 0.15              # × m × Δlot_sqft
LOT_CAP_PCT = 0.10           # cap lot adjustment at ±10% of comp price
COND_FACTOR = {"renovated": 0.07, "dated": 0.0, "fixer": -0.15}  # relative to 'dated'
MIN_REGRESSION_SALES = 40
SQFT_COEF_BAND = (0.25, 0.70)  # accept RLM sqft coef only within this × avg $/sqft


@dataclass
class CompAdjustment:
    line_items: dict[str, int]  # time, sqft, baths, lot, condition
    adjusted_price: int
    notes: list[str] = field(default_factory=list)

    @property
    def gross_feature(self) -> int:
        """Σ|feature line items| (excludes time — a market-level correction, not
        a comp-dissimilarity signal). Drives the §4.4 confidence check."""
        return sum(abs(self.line_items[k]) for k in ("sqft", "baths", "lot", "condition"))


@dataclass
class RegressionFit:
    accepted: bool
    n: int
    sqft_coef: float
    bath_coef: float
    reason: str


def bath_adjustment(subj_baths: float | None, comp_baths: float | None,
                    bath_coef: float | None = None) -> int:
    """Grid: full bath ±$15k, half ±$8k (comp superior ⇒ negative). When a
    regression bath coefficient is accepted it replaces the grid linearly."""
    if subj_baths is None or comp_baths is None:
        return 0
    diff = subj_baths - comp_baths
    if bath_coef is not None:
        return round(bath_coef * diff)
    sign = 1 if diff >= 0 else -1
    mag = abs(diff)
    full = int(mag + 1e-9)
    half = 1 if (mag - full) >= 0.25 else 0
    return sign * (full * FULL_BATH + half * HALF_BATH)


def lot_adjustment(subj_lot: int | None, comp_lot: int | None, m: float,
                   comp_price: int) -> tuple[int, str]:
    """``Δlot_sqft × 0.15 × m`` capped at ±10% of comp price."""
    if subj_lot is None or comp_lot is None:
        return 0, "lot unknown"
    raw = round((subj_lot - comp_lot) * LOT_COEF * m)
    cap = round(LOT_CAP_PCT * comp_price)
    clamped = max(-cap, min(cap, raw))
    return clamped, ("lot capped" if clamped != raw else "")


def condition_adjustment(subj_tag: str | None, comp_tag: str | None,
                         adj_price0: int) -> tuple[int, str]:
    """Relative-to-'dated' baseline: renovated +7%, dated 0, fixer −15% of the
    time-adjusted price. Either tag unknown ⇒ 0 with a note."""
    if subj_tag not in COND_FACTOR or comp_tag not in COND_FACTOR:
        return 0, "condition unknown"
    delta = COND_FACTOR[subj_tag] - COND_FACTOR[comp_tag]
    return round(delta * adj_price0), ""


def adjust(subject: dict, comp: dict, m: float, time_adj_factor: float,
           bath_coef: float | None = None) -> CompAdjustment:
    """One comp's full line-item adjustment toward the subject.

    ``subject``/``comp`` dicts carry sqft, baths, lot_sqft, condition_tag;
    ``comp`` also carries sale_price. ``time_adj_factor`` from
    ``price_index.time_adj_factor``.
    """
    sale_price = int(comp["sale_price"])
    adj_price0 = round(sale_price * time_adj_factor)
    time_li = adj_price0 - sale_price

    if subject.get("sqft") and comp.get("sqft"):
        sqft_li = round(m * (subject["sqft"] - comp["sqft"]))
    else:
        sqft_li = 0
    baths_li = bath_adjustment(subject.get("baths"), comp.get("baths"), bath_coef)
    lot_li, lot_note = lot_adjustment(subject.get("lot_sqft"), comp.get("lot_sqft"), m, sale_price)
    cond_li, cond_note = condition_adjustment(
        subject.get("condition_tag"), comp.get("condition_tag"), adj_price0
    )

    adjusted = adj_price0 + sqft_li + baths_li + lot_li + cond_li
    notes = [n for n in (lot_note, cond_note) if n]
    return CompAdjustment(
        line_items={"time": time_li, "sqft": sqft_li, "baths": baths_li,
                    "lot": lot_li, "condition": cond_li},
        adjusted_price=int(adjusted),
        notes=notes,
    )


# --- marginal $/sqft resolution (session-taking) -----------------------------

def median_ppsf(session: Session, zip5: str, as_of: str | None = None) -> float | None:
    """Trailing-~90-day median $/sqft for the geo (ZIP→city→county fallback),
    truncated to ``as_of``. Uses the last 3 monthly ``median_ppsf`` rows."""
    for geo_type, geo_id in _geo_candidates(zip5):
        stmt = (
            select(MarketMetric.value)
            .where(
                MarketMetric.geo_type == geo_type,
                MarketMetric.geo_id == geo_id,
                MarketMetric.metric == "median_ppsf",
                MarketMetric.source == "redfin",
            )
            .order_by(MarketMetric.period_start.desc())
            .limit(3)
        )
        if as_of:
            stmt = stmt.where(MarketMetric.period_start <= as_of)
        rows = sorted(float(v) for v in session.execute(stmt).scalars().all())
        if rows:
            return rows[len(rows) // 2]
    return None


def default_m(session: Session, zip5: str, as_of: str | None = None) -> tuple[float | None, float | None]:
    """(m, avg_ppsf) from the heuristic ``M_FACTOR × median_ppsf``. Both None if
    no $/sqft data (the caller then skips sqft/lot adjustment)."""
    ppsf = median_ppsf(session, zip5, as_of)
    if ppsf is None:
        return None, None
    return M_FACTOR * ppsf, ppsf


def regression_override(rows: list[dict], avg_ppsf: float) -> RegressionFit | None:
    """Robust regression ``detrended_price ~ sqft + baths + lot_sqft + age`` on
    pre-time-adjusted ``rows`` (each: detrended_price, sqft, baths, lot_sqft,
    age). ``None`` when < 40 usable rows or the fit fails. Otherwise a
    ``RegressionFit`` whose ``accepted`` says whether the sqft coef sits within
    25–70% of ``avg_ppsf`` (else the heuristic ``m`` is kept)."""
    usable = [
        r for r in rows
        if all(r.get(k) is not None for k in ("detrended_price", "sqft", "baths", "lot_sqft", "age"))
    ]
    if len(usable) < MIN_REGRESSION_SALES:
        return None
    try:
        import numpy as np
        import statsmodels.api as sm

        y = np.array([r["detrended_price"] for r in usable], dtype=float)
        X = np.column_stack([
            [r["sqft"] for r in usable],
            [r["baths"] for r in usable],
            [r["lot_sqft"] for r in usable],
            [r["age"] for r in usable],
        ]).astype(float)
        X = sm.add_constant(X)
        fit = sm.RLM(y, X, M=sm.robust.norms.HuberT()).fit()
        sqft_coef = float(fit.params[1])
        bath_coef = float(fit.params[2])
    except Exception as exc:  # noqa: BLE001 — any numerical failure ⇒ keep heuristic
        return RegressionFit(False, len(usable), 0.0, 0.0, f"fit failed: {exc}")

    lo, hi = SQFT_COEF_BAND[0] * avg_ppsf, SQFT_COEF_BAND[1] * avg_ppsf
    accepted = lo <= sqft_coef <= hi
    reason = "accepted" if accepted else f"sqft coef {sqft_coef:.0f} outside [{lo:.0f},{hi:.0f}]"
    return RegressionFit(accepted, len(usable), sqft_coef, bath_coef, reason)
