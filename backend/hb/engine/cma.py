"""CMA engine — comp selection, scoring, bracketing, estimate (docs/06 §2 & §4).

`run()` returns a `CmaResult` (never writes when `persist=False`, the backtest
path). The API/pipeline caller persists `CmaRun` + `CmaComp` + an own_cma
`AvmSnapshot`. Every candidate is scored by a product-of-penalties similarity,
the top set is bracketed (swap to guarantee the subject is straddled on size
and price), and the estimate is a similarity-weighted median with a
transparent confidence rule.

`as_of` (backtest) means "today" everywhere: it caps the comp window, the
price index, `median_ppsf`, and the recency weight `f_time` — no leakage.
"""

import calendar
import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.models import AvmSnapshot, CmaComp, CmaRun, Property, Sale
from hb.engine import adjustments, stats
from hb.engine.price_index import time_adj_factor
from hb.geo import bbox, haversine_miles

log = logging.getLogger(__name__)

CONDITIONS = set(adjustments.COND_FACTOR)  # renovated | dated | fixer
BASE_MONTHS = 6
BASE_RADIUS_MI = 0.5
RELAX_MONTHS = 9
RELAX_RADIUS_MI = 1.0
BASE_SQFT_TOL = 0.20
RELAX_SQFT_TOL = 0.30
MIN_SURVIVORS = 5
DEFAULT_MAX_COMPS = 6
RANGE_FLOOR_PCT = 0.03
F_TIME_HALF_LIFE_DAYS = 90  # similarity recency half-life (docs/06 §2.2); a
                            # backtest-tunable knob — _knobs() reports this name


@dataclass
class CompRow:
    sale_id: str
    property_id: str
    address: str
    sale_date: str
    sale_price: int
    distance_mi: float
    lat: float | None
    lon: float | None
    beds: int | None
    baths: float | None
    sqft: int | None
    lot_sqft: int | None
    condition_tag: str | None
    similarity_score: float
    time_adj_factor: float
    index_source: str
    adjustments: dict
    adjusted_price: int
    auto_selected: bool = True
    included: bool = True
    overrides: dict = field(default_factory=dict)


@dataclass
class CmaResult:
    property_id: str
    as_of: str
    estimate: int | None
    low: int | None
    high: int | None
    confidence: str
    confidence_reasons: list[str]
    index_source: str | None
    comps: list[CompRow]
    params: dict = field(default_factory=dict)


# --- date helpers ------------------------------------------------------------

def _months_ago(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) - n
    y, m = divmod(total, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _street_name(prop: Property) -> str:
    s = (prop.street or prop.address_norm or "").upper().strip()
    parts = s.split()
    if parts and parts[0].replace("-", "").isdigit():
        parts = parts[1:]
    return " ".join(parts)


# --- similarity (docs/06 §2.2) ----------------------------------------------

def _f_cond(subj_tag: str | None, comp_tag: str | None) -> float:
    if subj_tag not in CONDITIONS or comp_tag not in CONDITIONS:
        return 0.9  # unknown
    if subj_tag == comp_tag:
        return 1.0
    if {subj_tag, comp_tag} == {"renovated", "fixer"}:
        return 0.6  # opposite
    return 0.8  # adjacent


def similarity(subject: dict, comp: dict, distance_mi: float, days_ago: float,
               same_street: bool) -> float:
    f_dist = math.exp(-((distance_mi / 0.4) ** 2))
    f_time = 0.5 ** (days_ago / F_TIME_HALF_LIFE_DAYS)
    subj_sqft, comp_sqft = subject.get("sqft"), comp.get("sqft")
    f_sqft = (
        math.exp(-(((abs(comp_sqft - subj_sqft) / subj_sqft) / 0.15) ** 2))
        if subj_sqft and comp_sqft else 1.0
    )
    subj_beds, comp_beds = subject.get("beds"), comp.get("beds")
    f_beds = 0.85 ** abs(subj_beds - comp_beds) if subj_beds is not None and comp_beds is not None else 1.0
    subj_baths, comp_baths = subject.get("baths"), comp.get("baths")
    if subj_baths is not None and comp_baths is not None:
        f_baths = 0.90 ** abs(round(subj_baths * 2) / 2 - round(comp_baths * 2) / 2)
    else:
        f_baths = 1.0
    subj_lot, comp_lot = subject.get("lot_sqft"), comp.get("lot_sqft")
    f_lot = (
        math.exp(-(((abs(comp_lot - subj_lot) / subj_lot) / 0.5) ** 2))
        if subj_lot and comp_lot else 1.0
    )
    f_cond = _f_cond(subject.get("condition_tag"), comp.get("condition_tag"))
    score = f_dist * f_time * f_sqft * f_beds * f_baths * f_lot * f_cond
    if same_street:
        score = min(score * 1.1, 1.0)
    return score


# --- candidate gathering -----------------------------------------------------

def _gather(session: Session, subject: Property, subj: dict, months: int,
            radius: float, sqft_tol: float, min_date: str, as_of_date: str) -> list[tuple]:
    """(Sale, Property, distance_mi) candidates passing the hard filters."""
    lat_min, lat_max, lon_min, lon_max = bbox(subject.lat, subject.lon, radius)
    stmt = (
        select(Sale, Property)
        .join(Property, Sale.property_id == Property.id)
        .where(
            Property.property_type == "single_family",
            Property.id != subject.id,
            Property.lat.is_not(None), Property.lon.is_not(None),
            Property.lat >= lat_min, Property.lat <= lat_max,
            Property.lon >= lon_min, Property.lon <= lon_max,
            Sale.sale_date >= min_date,
            Sale.sale_date < as_of_date,
        )
    )
    out = []
    for sale, prop in session.execute(stmt).all():
        d = haversine_miles(subject.lat, subject.lon, prop.lat, prop.lon)
        if d > radius:
            continue
        if subj.get("beds") is not None and prop.beds is not None and abs(prop.beds - subj["beds"]) > 1:
            continue
        if subj.get("sqft"):
            if prop.sqft is None or abs(prop.sqft - subj["sqft"]) / subj["sqft"] > sqft_tol:
                continue
        out.append((sale, prop, d))
    return out


def _regression_rows(session: Session, subject: Property, as_of: str | None,
                     today_month: str, today_date: date, cache=None) -> list[dict]:
    """Time-adjusted sales in the subject's ZIP + same-city ZIPs over 12 months,
    detrended for the RLM marginal-$/sqft override."""
    zips = settings.geo.sibling_zips(subject.zip)
    min_date = _months_ago(today_date, 12).isoformat()
    stmt = (
        select(Sale, Property)
        .join(Property, Sale.property_id == Property.id)
        .where(Property.zip.in_(zips), Sale.sale_date >= min_date,
               Sale.sale_date < (today_date + timedelta(days=1)).isoformat())
    )
    rows = []
    for sale, prop in session.execute(stmt).all():
        if not (prop.sqft and prop.lot_sqft is not None and prop.baths is not None and prop.year_built):
            continue
        factor, _ = time_adj_factor(session, prop.zip, sale.sale_date[:7], today_month, as_of, cache)
        rows.append({
            "detrended_price": sale.sale_price * factor,
            "sqft": prop.sqft, "baths": prop.baths, "lot_sqft": prop.lot_sqft,
            "age": max(0, today_date.year - prop.year_built),
        })
    return rows


# --- bracketing (docs/06 §2.3) ----------------------------------------------

def _prelim(selected: list[CompRow]) -> float:
    return stats.weighted_median(
        [c.adjusted_price for c in selected], [c.similarity_score for c in selected]
    )


def _swap_in(selected: list[CompRow], remaining: list[CompRow], predicate) -> bool:
    """Replace the lowest-scored selected comp with the best-scoring remaining
    comp satisfying `predicate`. Returns True if a swap happened."""
    if any(predicate(c) for c in selected):
        return False
    candidate = next((c for c in remaining if predicate(c)), None)  # remaining is score-desc
    if candidate is None:
        return False
    victim = min(selected, key=lambda c: c.similarity_score)
    selected.remove(victim)
    remaining.remove(candidate)
    remaining.append(victim)
    remaining.sort(key=lambda c: c.similarity_score, reverse=True)
    selected.append(candidate)
    return True


def _bracket(selected: list[CompRow], remaining: list[CompRow], subj_sqft: int | None
             ) -> list[str]:
    """Swap to straddle the subject on size then on price. Returns reasons if a
    bracket cannot be filled."""
    if subj_sqft:
        _swap_in(selected, remaining, lambda c: c.sqft is not None and c.sqft > subj_sqft)
        _swap_in(selected, remaining, lambda c: c.sqft is not None and c.sqft < subj_sqft)
    prelim = _prelim(selected)
    _swap_in(selected, remaining, lambda c: c.adjusted_price > prelim)
    _swap_in(selected, remaining, lambda c: c.adjusted_price < prelim)

    reasons = []
    if subj_sqft and not (any(c.sqft and c.sqft > subj_sqft for c in selected)
                          and any(c.sqft and c.sqft < subj_sqft for c in selected)):
        reasons.append("unbracketed")
    prelim = _prelim(selected)
    if not (any(c.adjusted_price > prelim for c in selected)
            and any(c.adjusted_price < prelim for c in selected)):
        if "unbracketed" not in reasons:
            reasons.append("unbracketed")
    return reasons


# --- confidence (docs/06 §4.4) ----------------------------------------------

def _confidence(included: list[CompRow], estimate: float, spread_ratio: float,
                unbracketed: bool) -> tuple[str, list[str]]:
    n = len(included)
    reasons: list[str] = []
    gross_ratios = [
        abs(c.adjustments["sqft"]) + abs(c.adjustments["baths"])
        + abs(c.adjustments["lot"]) + abs(c.adjustments["condition"])
        for c in included
    ]
    gross_pct = [g / c.sale_price for g, c in zip(gross_ratios, included)] if included else [0]
    max_gross = max(gross_pct) if gross_pct else 0.0

    low = n < 3 or spread_ratio > 0.10 or max_gross > 0.20 or unbracketed
    if low:
        if n < 3:
            reasons.append("n<3")
        if spread_ratio > 0.10:
            reasons.append("spread>10%")
        if max_gross > 0.20:
            reasons.append("gross adjustment>20%")
        if unbracketed:
            reasons.append("unbracketed")
        return "low", reasons
    if n >= 5 and spread_ratio <= 0.06 and max_gross <= 0.15:
        return "high", ["n>=5", "spread<=6%", "adjustments<=15%"]
    return "medium", ["medium spread/coverage"]


def _resolve_m(session: Session, subject: Property, as_of: str | None,
               today_month: str, today_date: date, cache=None) -> tuple[float, float | None, str]:
    """Marginal $/sqft: heuristic ``0.45×median_ppsf``, RLM override when thick.
    Returns (m_eff, bath_coef, source). m_eff falls back to 0 (disables
    sqft/lot adjustment) when no $/sqft data exists."""
    m, avg_ppsf = adjustments.default_m(session, subject.zip, as_of)
    m_source = "heuristic"
    bath_coef = None
    if m is not None and avg_ppsf:
        fit = adjustments.regression_override(
            _regression_rows(session, subject, as_of, today_month, today_date, cache), avg_ppsf
        )
        if fit and fit.accepted:
            m, bath_coef, m_source = fit.sqft_coef, fit.bath_coef, "regression"
    return (m if m is not None else 0.0), bath_coef, m_source


def _build_comprow(session, subject, subj, subj_street, sale, prop, dist, m_eff,
                   bath_coef, today_date, today_month, as_of, overrides=None,
                   cache=None) -> CompRow:
    days_ago = max(0, (today_date - date.fromisoformat(sale.sale_date[:10])).days)
    comp = {
        "sqft": prop.sqft, "beds": prop.beds, "baths": prop.baths,
        "lot_sqft": prop.lot_sqft, "condition_tag": prop.condition_tag,
        "sale_price": sale.sale_price,
    }
    same_street = bool(subj_street) and _street_name(prop) == subj_street
    score = similarity(subj, comp, dist, days_ago, same_street)
    factor, src = time_adj_factor(session, prop.zip, sale.sale_date[:7], today_month, as_of, cache)
    adj = adjustments.adjust(subj, comp, m_eff, factor, bath_coef)
    line_items = dict(adj.line_items)
    overrides = {k: int(v) for k, v in (overrides or {}).items() if k in line_items}
    line_items.update(overrides)
    adjusted = sale.sale_price + sum(line_items.values())  # = adj_price0 + feature items
    addr = f"{prop.address_norm.title()}{' #' + prop.unit if prop.unit else ''}"
    return CompRow(
        sale_id=sale.id, property_id=prop.id, address=addr, sale_date=sale.sale_date,
        sale_price=sale.sale_price, distance_mi=round(dist, 3), lat=prop.lat, lon=prop.lon,
        beds=prop.beds, baths=prop.baths, sqft=prop.sqft, lot_sqft=prop.lot_sqft,
        condition_tag=prop.condition_tag, similarity_score=round(score, 6),
        time_adj_factor=round(factor, 6), index_source=src, adjustments=line_items,
        adjusted_price=int(adjusted), overrides=overrides,
    )


# --- main entry --------------------------------------------------------------

def run(session: Session, property_id: str, params: dict | None = None,
        as_of: str | None = None, persist: bool = True) -> CmaResult:
    params = dict(params or {})
    subject = session.get(Property, property_id)
    if subject is None:
        raise ValueError(f"unknown property: {property_id}")

    today_date = date.fromisoformat(as_of[:10]) if as_of else date.today()
    today_month = today_date.strftime("%Y-%m")
    # comp window upper bound: sales through "today" inclusive, where today is
    # as_of in backtest mode (docs/10 §4: as_of = list_date − 1, so comps sold
    # the day before listing count — same inclusivity as the live path). Or
    # through today when live (today + 1 day, since sale_date is date-only).
    upper = (today_date + timedelta(days=1)).isoformat()

    subj = {
        "sqft": subject.sqft, "beds": subject.beds, "baths": subject.baths,
        "lot_sqft": subject.lot_sqft, "condition_tag": subject.condition_tag,
        "zip": subject.zip,
    }
    subj_street = _street_name(subject)

    if subject.lat is None or subject.lon is None:
        return CmaResult(property_id, today_date.isoformat(), None, None, None,
                         "low", ["no coordinates"], None, [], params)

    # --- candidate pool with relaxation ladder (months -> distance -> sqft) ---
    months, radius, sqft_tol = (
        params.get("months", BASE_MONTHS),
        params.get("radius_mi", BASE_RADIUS_MI),
        BASE_SQFT_TOL,
    )
    relaxations: list[str] = []

    def gather(mo, rad, tol):
        return _gather(session, subject, subj, mo, rad, tol,
                       _months_ago(today_date, mo).isoformat(), upper)

    cands = gather(months, radius, sqft_tol)
    if len(cands) < MIN_SURVIVORS:
        months = max(months, RELAX_MONTHS)
        relaxations.append("months")
        cands = gather(months, radius, sqft_tol)
    if len(cands) < MIN_SURVIVORS:
        radius = max(radius, RELAX_RADIUS_MI)
        relaxations.append("distance")
        cands = gather(months, radius, sqft_tol)
    if len(cands) < MIN_SURVIVORS:
        sqft_tol = RELAX_SQFT_TOL
        relaxations.append("sqft")
        cands = gather(months, radius, sqft_tol)

    # --- marginal $/sqft: heuristic, RLM override when data is thick ----------
    idx_cache: dict = {}  # memoize price-index series across this run's comps
    m_eff, bath_coef, m_source = _resolve_m(session, subject, as_of, today_month, today_date, idx_cache)

    # --- score + adjust every candidate --------------------------------------
    index_source = "none"
    scored: list[CompRow] = []
    for sale, prop, dist in cands:
        row = _build_comprow(session, subject, subj, subj_street, sale, prop, dist,
                             m_eff, bath_coef, today_date, today_month, as_of, cache=idx_cache)
        if row.index_source != "none":
            index_source = row.index_source
        scored.append(row)

    scored.sort(key=lambda c: c.similarity_score, reverse=True)
    max_comps = params.get("max_comps", DEFAULT_MAX_COMPS)
    selected = scored[:max_comps]
    remaining = scored[max_comps:]
    bracket_reasons = _bracket(selected, remaining, subject.sqft) if selected else ["no comps"]

    # keep a few next-best candidates (excluded) so the workbench drawer can
    # one-click swap them in without a fresh selection pass
    drawer = remaining[:DEFAULT_MAX_COMPS]
    for c in drawer:
        c.included = False
        c.auto_selected = False
    comps = selected + drawer

    return _finalize(session, subject, comps, index_source, m_source, relaxations,
                     bracket_reasons, today_date, params, persist)


def _finalize(session, subject, selected, index_source, m_source, relaxations,
              bracket_reasons, today_date, params, persist) -> CmaResult:
    included = [c for c in selected if c.included]
    if not included:
        reasons = bracket_reasons or ["no included comps"]
        result = CmaResult(subject.id, today_date.isoformat(), None, None, None, "low",
                           reasons, index_source, selected,
                           {**params, "confidence_reasons": reasons})
        # persist even the empty run: the workbench needs a real run id to keep
        # accepting toggles (id=null dead-ended all further PATCHes)
        if persist:
            _persist(session, result)
        return result

    prices = [c.adjusted_price for c in included]
    weights = [c.similarity_score for c in included]
    estimate = stats.weighted_median(prices, weights)
    p25, p75 = stats.weighted_quantile(prices, weights, [0.25, 0.75])
    spread_ratio = (p75 - p25) / estimate if estimate else 1.0
    low = min(p25, estimate * (1 - RANGE_FLOOR_PCT))
    high = max(p75, estimate * (1 + RANGE_FLOOR_PCT))

    confidence, reasons = _confidence(included, estimate, spread_ratio,
                                      "unbracketed" in bracket_reasons)

    result = CmaResult(
        property_id=subject.id, as_of=today_date.isoformat(),
        estimate=round(estimate), low=round(low), high=round(high),
        confidence=confidence, confidence_reasons=reasons, index_source=index_source,
        comps=selected,
        params={**params, "relaxations": relaxations, "m_source": m_source,
                "confidence_reasons": reasons},
    )
    if persist:
        _persist(session, result)
    return result


def _persist(session: Session, result: CmaResult) -> str:
    run_row = CmaRun(
        property_id=result.property_id, params=result.params, estimate=result.estimate,
        low=result.low, high=result.high, confidence=result.confidence,
        index_source=result.index_source,
    )
    session.add(run_row)
    session.flush()
    for c in result.comps:
        stored = {**c.adjustments, "_overrides": c.overrides} if c.overrides else c.adjustments
        session.add(CmaComp(
            cma_run_id=run_row.id, sale_id=c.sale_id, similarity_score=c.similarity_score,
            auto_selected=c.auto_selected, included=c.included, time_adj_factor=c.time_adj_factor,
            adjustments=stored, adjusted_price=c.adjusted_price,
        ))
    if result.estimate is not None:
        snap = session.execute(
            select(AvmSnapshot).where(
                AvmSnapshot.property_id == result.property_id,
                AvmSnapshot.source == "own_cma", AvmSnapshot.as_of == result.as_of,
            )
        ).scalar_one_or_none()
        if snap is None:
            session.add(AvmSnapshot(
                property_id=result.property_id, source="own_cma", value=result.estimate,
                low=result.low, high=result.high, as_of=result.as_of,
            ))
        else:
            snap.value, snap.low, snap.high = result.estimate, result.low, result.high
    session.commit()
    result.params["cma_run_id"] = run_row.id
    return run_row.id


def recompute(session: Session, property_id: str, comp_specs: list[dict],
              params: dict | None = None, as_of: str | None = None,
              persist: bool = True) -> CmaResult:
    """Re-run the estimate over a fixed, user-curated comp set (workbench comp
    toggles and adjustment overrides). ``comp_specs`` = ``[{sale_id, included,
    overrides}]``. No candidate re-selection or swap — the curation is honoured;
    bracketing is only checked (for the ``unbracketed`` confidence reason).
    Persists a brand-new run; the source run is never mutated (history)."""
    params = dict(params or {})
    subject = session.get(Property, property_id)
    if subject is None:
        raise ValueError(f"unknown property: {property_id}")
    today_date = date.fromisoformat(as_of[:10]) if as_of else date.today()
    today_month = today_date.strftime("%Y-%m")
    subj = {
        "sqft": subject.sqft, "beds": subject.beds, "baths": subject.baths,
        "lot_sqft": subject.lot_sqft, "condition_tag": subject.condition_tag,
    }
    subj_street = _street_name(subject)
    idx_cache: dict = {}
    m_eff, bath_coef, m_source = _resolve_m(session, subject, as_of, today_month, today_date, idx_cache)

    index_source = "none"
    selected: list[CompRow] = []
    for spec in comp_specs:
        sale = session.get(Sale, spec["sale_id"])
        if sale is None:
            continue
        prop = session.get(Property, sale.property_id)
        dist = (haversine_miles(subject.lat, subject.lon, prop.lat, prop.lon)
                if subject.lat and prop.lat else 0.0)
        row = _build_comprow(session, subject, subj, subj_street, sale, prop, dist,
                             m_eff, bath_coef, today_date, today_month, as_of,
                             overrides=spec.get("overrides"), cache=idx_cache)
        row.included = spec.get("included", True)
        row.auto_selected = spec.get("auto_selected", False)
        if row.index_source != "none":
            index_source = row.index_source
        selected.append(row)

    included = [c for c in selected if c.included]
    straddles = bool(subject.sqft and included
                     and any(c.sqft and c.sqft > subject.sqft for c in included)
                     and any(c.sqft and c.sqft < subject.sqft for c in included))
    bracket_reasons = [] if straddles else ["unbracketed"]
    return _finalize(session, subject, selected, index_source, m_source, [],
                     bracket_reasons, today_date, params, persist)
