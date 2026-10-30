"""Overbid model — the SP/LP sale-price *distribution* for a listing (docs/06 §5).

Bay Area list prices are frequently set as bid floors — posture.py decides per
listing whether that framing actually applies. This model predicts where a home
sells as a ratio of list. It always uses `sp_lp` measured against the ORIGINAL
list price, splits the comp sample fresh/stale (a price cut changes SP/LP
behaviour entirely), takes recency-weighted quantiles, and shrinks a thin ZIP
sample toward the city distribution.

Worked example 06 §5.5 is a literal gate: `shrink(1.12, 1.09, 9.1, 8) == 1.106`.
`as_of` (backtest) caps the comp window and drives the recency weight.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.models import Listing, ListingGroup, Property, Sale
from hb.engine import exposure, stats

# --- tunable knobs (recorded by the backtest report) -------------------------
WEIGHT_HALF_LIFE_DAYS = 60
SHRINK_K = 8
BASE_WINDOW_DAYS = 90
EXTENDED_WINDOW_DAYS = 180
MIN_SAMPLE = 8
LIST_TOLERANCE = 0.30
ATYPICAL_PCT = 0.07
STALE_DOM_MULTIPLIER = 1.5
# Calibration: the raw weighted p25–p75 covered only ~47% of actual sales in the
# backtest (too narrow — partly because backfilled comps carry no price-cut
# history, so the fresh distribution is artificially tight). Widen the band by
# this fraction so the stated range honestly reflects realized uncertainty.
RANGE_WIDEN = 0.03


@dataclass
class OverbidResult:
    list_price: int | None
    basis: str            # fresh | stale
    basis_reason: str
    n_comps: int
    n_eff: float
    window_days: int
    p25: float | None
    p50: float | None
    p75: float | None
    predicted: dict | None  # {low, point, high}
    atypical_pricing: bool
    histogram: list[dict] = field(default_factory=list)
    comps: list[dict] = field(default_factory=list)


def shrink(p_zip: float, p_city: float | None, n_eff: float, k: int = SHRINK_K) -> float:
    """Shrink a ZIP quantile toward the city quantile (docs/06 §5.3).

    `p_city=None` (no city data) ⇒ return the ZIP quantile unchanged.
    """
    if p_city is None:
        return p_zip
    return (n_eff * p_zip + k * p_city) / (n_eff + k)


def _same_city_zips(zip5: str) -> list[str]:
    return settings.geo.sibling_zips(zip5)


def _load(session: Session, zips: tuple[str, ...], window_days: int, upper: str,
          today: date) -> list[dict]:
    """Raw comp sales in `zips` within the window (unfiltered by list/beds so the
    per-listing filter can reuse a cached load). Each: sp_lp, fresh, days_ago…"""
    min_date = (today - timedelta(days=window_days)).isoformat()
    rows = session.execute(
        select(Sale, Property, ListingGroup.episode_count)
        .join(Property, Sale.property_id == Property.id)
        .outerjoin(Listing, Sale.listing_id == Listing.id)
        .outerjoin(ListingGroup, Listing.listing_group_id == ListingGroup.id)
        .where(
            Property.zip.in_(list(zips)),
            Property.property_type == "single_family",
            Sale.sp_lp.is_not(None),
            Sale.sale_date >= min_date,
            Sale.sale_date < upper,
        )
    ).all()
    out = []
    for sale, prop, episodes in rows:
        relisted = bool(episodes and episodes > 1)
        out.append({
            "sale_id": sale.id, "address": prop.address_norm.title(), "zip": prop.zip,
            "beds": prop.beds, "sqft": prop.sqft, "sale_date": sale.sale_date,
            "sale_price": sale.sale_price, "original_list_price": sale.original_list_price,
            "sp_lp": sale.sp_lp, "days_ago": max(0, (today - date.fromisoformat(sale.sale_date[:10])).days),
            "fresh": (not sale.had_price_cut) and not relisted,
        })
    return out


def _filter(rows: list[dict], anchor: int, beds: int | None) -> list[dict]:
    lo, hi = anchor * (1 - LIST_TOLERANCE), anchor * (1 + LIST_TOLERANCE)
    out = []
    for r in rows:
        olp = r["original_list_price"]
        if olp is None or not (lo <= olp <= hi):
            continue
        if beds is not None and r["beds"] is not None and abs(r["beds"] - beds) > 1:
            continue
        out.append(r)
    return out


def _quantiles(comps: list[dict]) -> tuple[list[float], float]:
    """Weighted p25/p50/p75 of sp_lp + n_eff. Empty ⇒ ([], 0)."""
    if not comps:
        return [], 0.0
    values = [c["sp_lp"] for c in comps]
    weights = [0.5 ** (c["days_ago"] / WEIGHT_HALF_LIFE_DAYS) for c in comps]
    q = stats.weighted_quantile(values, weights, [0.25, 0.50, 0.75])
    sw = sum(weights)
    sw2 = sum(w * w for w in weights)
    n_eff = (sw * sw) / sw2 if sw2 else 0.0
    return q, n_eff


def predict(session: Session, listing: Listing, prop: Property,
            cma_estimate: int | None = None, as_of: str | None = None,
            cache: dict | None = None) -> OverbidResult:
    today = date.fromisoformat(as_of[:10]) if as_of else date.today()
    # sales through "today" inclusive — today = as_of in backtest mode, matching
    # cma._gather so live and as-of runs on the same day see the same sample
    upper = (today + timedelta(days=1)).isoformat()
    anchor = listing.original_list_price or listing.list_price

    if anchor is None:
        return OverbidResult(None, "fresh", "no list price", 0, 0.0, BASE_WINDOW_DAYS,
                             None, None, None, None, False)

    def load(zips, window):
        key = (frozenset(zips), window)
        if cache is not None and key in cache:
            return cache[key]
        rows = _load(session, tuple(zips), window, upper, today)
        if cache is not None:
            cache[key] = rows
        return rows

    # --- sample with ZIP → same-city expansion, then window extension --------
    zips = [prop.zip]
    window = BASE_WINDOW_DAYS
    sample = _filter(load(zips, window), anchor, prop.beds)
    if len(sample) < MIN_SAMPLE:
        zips = _same_city_zips(prop.zip)
        sample = _filter(load(zips, window), anchor, prop.beds)
    if len(sample) < MIN_SAMPLE:
        window = EXTENDED_WINDOW_DAYS
        sample = _filter(load(zips, window), anchor, prop.beds)

    # --- subject routing to fresh/stale (as-of aware: no look-ahead) --------
    # Routing picks a comp DISTRIBUTION on the subject's cumulative history (a
    # cut, or cumulative DOM past the stale threshold). The posture layer asks a
    # different question — whether THIS asking price has been tested — and runs
    # on the episode clock; a fresh relist therefore reads "bait" there while
    # its cumulative days usually route it stale here.
    ex = exposure.inputs(session, listing, prop, as_of, cache)
    stale_by_dom = bool(ex.days and ex.median_dom
                        and ex.days > STALE_DOM_MULTIPLIER * ex.median_dom)
    basis = "stale" if (ex.had_cut or stale_by_dom) else "fresh"
    basis_reason = (
        "price cut" if ex.had_cut else
        f"cumulative DOM {ex.days} > {STALE_DOM_MULTIPLIER}× area median {ex.median_dom}"
        if stale_by_dom else
        "fresh listing, no cut"
    )

    chosen = [c for c in sample if c["fresh"]] if basis == "fresh" else [c for c in sample if not c["fresh"]]
    if not chosen:
        chosen = sample  # bucket empty ⇒ fall back to the whole sample

    if not chosen:
        return OverbidResult(anchor, basis, basis_reason, 0, 0.0, window,
                             None, None, None, None, False)

    (p_zip, n_eff) = _quantiles(chosen)

    # --- city distribution for shrinkage ------------------------------------
    city_zips = _same_city_zips(prop.zip)
    city_sample = _filter(load(city_zips, window), anchor, prop.beds)
    city_chosen = ([c for c in city_sample if c["fresh"]] if basis == "fresh"
                   else [c for c in city_sample if not c["fresh"]]) or city_sample
    (p_city, _) = _quantiles(city_chosen)

    p25, p50, p75 = (
        shrink(p_zip[i], p_city[i] if p_city else None, n_eff) for i in range(3)
    )

    predicted = {"low": round(anchor * p25 * (1 - RANGE_WIDEN)),
                 "point": round(anchor * p50),
                 "high": round(anchor * p75 * (1 + RANGE_WIDEN))}
    atypical = bool(cma_estimate and abs(predicted["point"] - cma_estimate) / cma_estimate > ATYPICAL_PCT)

    weights = [0.5 ** (c["days_ago"] / WEIGHT_HALF_LIFE_DAYS) for c in chosen]
    histogram = [
        {"bucket_low": round(lo, 4), "bucket_high": round(hi, 4), "weight": round(w, 4)}
        for lo, hi, w in stats.weighted_histogram([c["sp_lp"] for c in chosen], weights, bins=8)
    ]
    comps = [
        {"address": c["address"], "sale_date": c["sale_date"], "sp_lp": c["sp_lp"],
         "original_list_price": c["original_list_price"], "sale_price": c["sale_price"]}
        for c in sorted(chosen, key=lambda c: c["sale_date"], reverse=True)
    ]

    return OverbidResult(
        list_price=anchor, basis=basis, basis_reason=basis_reason, n_comps=len(chosen),
        n_eff=round(n_eff, 2), window_days=window, p25=round(p25, 4), p50=round(p50, 4),
        p75=round(p75, 4), predicted=predicted, atypical_pricing=atypical,
        histogram=histogram, comps=comps,
    )
