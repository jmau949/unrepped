"""Pricing posture — a calibrated probability that a listing sells below its
current asking price (docs/06 §5.6).

The overbid model treats list price as the anchor of a bidding war, the common
Bay Area convention — but not a law. Some homes are listed at value and some
above it, and a tool that assumes bait pricing everywhere tells the buyer to
chase a CMA the market has already refused. The question a buyer actually has
is "will this sell below asking, and by how much?" — and the evidence that
answers it is market behaviour, not another value estimate:

- **Exposure** at the current price relative to the area's median time to
  pending. The empirical curve is a step, not a ramp: a listing in its first
  days sells below asking ~27% of the time, one still active at the median
  ~54%, past the first offer window (1.25–3×) 63–69%, and only beyond ~4×
  does it climb to 72–80%.
- **Price cuts** (the seller conceding a higher ask), **relists** (a withdrawn
  attempt — with the clock reset to the new episode, because a new price is a
  new test) and, live only, a published **offer date that passed** unanswered.
  Once exposure is known these add little: the current asking price is judged
  on how long it has gone untaken, not on how it got there.

Every signal is a log-odds contribution to one logit; `p_below_list` is its
sigmoid. The knobs were fitted on the backtest's survival replay (docs/10 §4:
every scan-observed sale, re-scored as-of each exposure point it passed through
before going pending — the population a live chip actually faces) and every
backtest run re-fits them so the calibration table can be checked against the
shipped values. List-vs-value is NOT a vote: once exposure is known, neither
the CMA nor the list-anchored blend predicts whether a home clears asking
(lingering homes sold below list 62–67% of the time whatever the CMA said), so
it is reported as an informational `value_gap_pct` only.

The second mechanism, the **market-evidence adjustment**, pulls the served
value toward `NO_SALE_ANCHOR × list` as exposure passes the median
(`rejection_weight` ramps 0→1 over 1×–1.25×): list-as-of is a better
predictor than the model for a lingering home, and the pull never raises an
estimate.
"""

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.db.models import AvmSnapshot, Listing, ListingEvent, Property
from hb.engine import exposure as exposure_mod

# --- tunable knobs (recorded and re-fitted by the backtest) -------------------
# log-odds of "sells below the current asking price" by exposure ratio
# (episode-aware exposure days / area median DOM); linear between knots, flat
# outside. Fitted on the survival replay (docs/10 §4); the backtest prints the
# re-fit next to these on every run.
EXPOSURE_LOGIT = ((0.5, -0.98), (1.25, 0.66), (4.0, 1.01))
CUT_LOGIT = 0.14            # any price cut — small once exposure is known (count/depth carry nothing extra)
RELIST_LOGIT = 0.20         # fitted on ~40 relist rows, nearly all early in their new episode
OFFER_PASSED_LOGIT = 0.25   # live-only prior — not measurable as-of, mostly duplicates exposure
OVER_P = 0.60               # p_below_list >= this => overpriced (3 in 5 sell below asking)
UNDER_P = 0.40              # p_below_list <= this => underpriced (3 in 5 sell at or above)
HIGH_P = 0.80               # confidence tiers on max(p, 1 - p)
MEDIUM_P = 0.65
# realized median sold/list per posture (backtest-measured; the magnitude the
# chip and verdict quote next to the probability)
TYPICAL_SOLD_TO_LIST = {"overpriced": 0.973, "near_market": 1.000, "underpriced": 1.055}
# past this exposure ratio about a quarter of scan-observed campaigns end
# withdrawn rather than pending (counted per campaign — a withdrawn attempt
# that relists and sells is a sale) — shown as a separate fact, never folded
# into p (p is conditional on a sale)
WITHDRAWAL_RATIO = 2.0
WITHDRAWAL_SHARE = 0.24
AGREE_PCT = 0.07            # mirror frontend AvmSpreadBar thresholds
DIVERGE_PCT = 0.15
# market-evidence value adjustment
W_RAMP_START = 1.0          # the first offer window is the test…
W_RAMP_FULL = 1.25          # …and by 1.25x the median the survival curve's step is complete:
                            # the rejection is fully credible (decision-point MdAPE on the
                            # w > 0 rows matches list-as-of itself at this setting)
OFFER_PASSED_W_BONUS = 0.25
NO_SALE_ANCHOR = 0.98       # rejection pulls the point toward list x this
ADJ_RANGE_HIGH_CAP = 1.02   # adjusted high <= list x this once w >= 0.5

OFFER_PASSED_GRACE_DAYS = exposure_mod.OFFER_PASSED_GRACE_DAYS


@dataclass
class PostureResult:
    posture: str                        # underpriced | near_market | overpriced | unknown
    confidence: str                     # low | medium | high — tiers on p
    logit: float | None                 # Σ signal points; None without exposure data
    p_below_list: float | None          # sigmoid(logit)
    typical_sold_to_list: float | None  # TYPICAL_SOLD_TO_LIST[posture]
    exposure: dict | None               # {days, episode_days, episode_count, cuts, cut_source, median_dom, ratio, offer_passed}
    value_gap_pct: float | None         # list / unadjusted value − 1; informational, never a vote
    withdrawal_share: float | None      # WITHDRAWAL_SHARE once ratio >= WITHDRAWAL_RATIO
    rejection_weight: float             # w in [0,1] — credibility of "market says value <= list"
    adjusted: dict | None               # {low, point, high} market-evidence-adjusted value
    unadjusted_point: int | None        # blended model value before adjustment
    agreement: str                      # agree | moderate | diverge | unknown
    spread_pct: float | None            # (max - min) / median across estimate sources
    signals: list[dict] = field(default_factory=list)  # [{id, label, points, detail}]


# --- the calibrated curve ------------------------------------------------------

def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def exposure_logit(ratio: float) -> float:
    xs, ys = zip(*EXPOSURE_LOGIT)
    return float(np.interp(ratio, xs, ys))


def features(ratio: float, had_cut: bool, relisted: bool) -> list[float]:
    """The design row the knobs were fitted on — shared with the backtest's
    re-fit so the shipped curve and the suggested one are the same model:
    [1, ramp over the first offer window, slide to 4x, had_cut, relisted]."""
    (x0, _), (x1, _), (x2, _) = EXPOSURE_LOGIT
    ramp = min(1.0, max(0.0, (ratio - x0) / (x1 - x0)))
    slide = min(1.0, max(0.0, (ratio - x1) / (x2 - x1)))
    return [1.0, ramp, slide, 1.0 if had_cut else 0.0, 1.0 if relisted else 0.0]


def knots_from_coefficients(b0: float, b1: float, b2: float) -> tuple:
    """Inverse of `features` for the exposure part: fitted coefficients back to
    the EXPOSURE_LOGIT knot form."""
    (x0, _), (x1, _), (x2, _) = EXPOSURE_LOGIT
    return ((x0, round(b0, 2)), (x1, round(b0 + b1, 2)), (x2, round(b0 + b1 + b2, 2)))


def rejection_weight(ratio: float | None, offer_passed: bool = False) -> float:
    """Credibility of "the market has rejected this price", 0..1. Ramps with the
    episode-aware exposure ratio; a passed offer date adds a bonus (someone named
    a date and nobody showed up)."""
    if ratio is not None:
        w = min(max((ratio - W_RAMP_START) / (W_RAMP_FULL - W_RAMP_START), 0.0), 1.0)
    else:
        w = 0.0
    if offer_passed:
        w = min(1.0, w + OFFER_PASSED_W_BONUS)
    return w


def market_adjusted(predicted: dict, list_price: int, w: float) -> dict:
    """Blend the model point toward min(point, NO_SALE_ANCHOR × list) by w. Never
    raises the estimate; the served range always contains its own point; once
    rejection is at least half-credible the high end is capped just above list."""
    target = min(predicted["point"], round(list_price * NO_SALE_ANCHOR))
    point = round((1 - w) * predicted["point"] + w * target)
    high = predicted["high"]
    if w >= 0.5:
        high = min(high, round(list_price * ADJ_RANGE_HIGH_CAP))
    return {"low": min(predicted["low"], point), "point": point, "high": max(high, point)}


def list_price_as_of(session: Session, listing: Listing, as_of: str | None = None) -> int | None:
    """Current list price as observed by `as_of`: original list plus any cuts
    observed before it. Live mode returns the stored price — the served number
    and the as-of reconstruction must agree on a quiet listing."""
    if not as_of:
        return listing.list_price or listing.original_list_price
    upper = (date.fromisoformat(as_of[:10]) + timedelta(days=1)).isoformat()
    last = session.execute(
        select(ListingEvent)
        .where(ListingEvent.listing_id == listing.id,
               ListingEvent.event_type == "price_change",
               ListingEvent.observed_at < upper)
        .order_by(ListingEvent.observed_at.desc())
        .limit(1)
    ).scalars().first()
    if last and last.new_value:
        return int(last.new_value)
    return listing.original_list_price or listing.list_price


def _estimate_values(session: Session, property_id: str, cma_estimate: int | None,
                     model_point: int | None, as_of: str | None = None) -> list[int]:
    """One value per estimate source on a single axis: latest external AVM
    snapshots + our CMA + the (unadjusted) model point."""
    stmt = (select(AvmSnapshot)
            .where(AvmSnapshot.property_id == property_id)
            .order_by(AvmSnapshot.as_of.desc()))
    if as_of:
        stmt = stmt.where(AvmSnapshot.as_of <= as_of)
    latest: dict[str, int] = {}
    for snap in session.execute(stmt).scalars():
        latest.setdefault(snap.source, snap.value)
    if cma_estimate is not None:
        latest["own_cma"] = cma_estimate  # param wins over a stale snapshot
    if model_point is not None:
        latest["model"] = model_point
    return [v for v in latest.values() if v]


def estimate_agreement(values: list[int]) -> tuple[str, float | None]:
    """(agreement, spread_pct) across estimate sources — thresholds mirrored by
    the frontend AvmSpreadBar. Informational: it caps the offer recommendation's
    confidence and labels the UI; it does not move the posture."""
    if len(values) < 2:
        return "unknown", None
    med = statistics.median(values)
    if not med:
        return "unknown", None
    spread = (max(values) - min(values)) / med
    if spread > DIVERGE_PCT:
        return "diverge", spread
    if spread < AGREE_PCT:
        return "agree", spread
    return "moderate", spread


def _cut_detail(ex: exposure_mod.Exposure) -> str:
    if ex.cut_source == "observed":
        return f"{ex.cuts} price cut(s) observed — the seller conceded a higher ask"
    if ex.cut_source == "history":
        return "price reduced this episode per Realtor's history (before our first scan)"
    return "relisted below the previous episode's final asking price"


def classify(session: Session, listing: Listing, prop: Property,
             predicted: dict | None, cma_estimate: int | None = None,
             as_of: str | None = None, cache: dict | None = None) -> PostureResult:
    """Score the market-behaviour evidence about this listing's asking price.
    `predicted` is the valuation.predicted_sale payload (post-adjustment,
    carrying `unadjusted_point`); a raw overbid/blend dict without that key
    also works — the adjustment is then applied here."""
    ex = exposure_mod.inputs(session, listing, prop, as_of, cache)
    list_price = list_price_as_of(session, listing, as_of)

    unadj_point = None
    if predicted:
        unadj_point = predicted.get("unadjusted_point") or predicted.get("point")
    agreement, spread = estimate_agreement(
        _estimate_values(session, prop.id, cma_estimate, unadj_point, as_of))

    signals: list[dict] = []
    logit: float | None = None
    if ex.ratio is not None:
        clock = ex.episode_days if ex.relisted else ex.days
        pts = exposure_logit(ex.ratio)
        detail = (f"{clock} days this episode vs area median {ex.median_dom:.0f} "
                  f"({ex.days} cumulative across {ex.episode_count} episodes)"
                  if ex.relisted else
                  f"{clock} days vs area median {ex.median_dom:.0f}")
        signals.append({"id": "exposure", "label": "Market exposure",
                        "points": round(pts, 2), "detail": detail})
        logit = pts
    if ex.had_cut:
        signals.append({"id": "price_cuts", "label": "Price cut", "points": CUT_LOGIT,
                        "detail": _cut_detail(ex)})
        if logit is not None:
            logit += CUT_LOGIT
    if ex.relisted:
        signals.append({"id": "relist", "label": "Relisted", "points": RELIST_LOGIT,
                        "detail": f"episode {ex.episode_count} of this campaign — the clock "
                                  f"restarted with the new asking price"})
        if logit is not None:
            logit += RELIST_LOGIT
    if ex.offer_passed:
        signals.append({"id": "offer_passed", "label": "Offer date passed",
                        "points": OFFER_PASSED_LOGIT,
                        "detail": f"offer date {listing.offer_due_at[:10]} passed, still active"})
        if logit is not None:
            logit += OFFER_PASSED_LOGIT

    if logit is None:
        posture, confidence, p = "unknown", "low", None
    else:
        p = round(sigmoid(logit), 3)  # the published number is the classified one
        posture = ("overpriced" if p >= OVER_P else
                   "underpriced" if p <= UNDER_P else "near_market")
        strength = max(p, 1 - p)
        confidence = ("high" if strength >= HIGH_P else
                      "medium" if strength >= MEDIUM_P else "low")

    value_gap = (list_price / unadj_point - 1) if (list_price and unadj_point) else None

    w = rejection_weight(ex.ratio, ex.offer_passed)
    adjusted = None
    if predicted:
        if "unadjusted_point" in predicted:
            adjusted = {k: predicted[k] for k in ("low", "point", "high")}
        elif list_price:
            adjusted = market_adjusted(predicted, list_price, w)
        else:
            adjusted = {k: predicted[k] for k in ("low", "point", "high")}

    return PostureResult(
        posture=posture, confidence=confidence,
        logit=round(logit, 3) if logit is not None else None,
        p_below_list=p,
        typical_sold_to_list=TYPICAL_SOLD_TO_LIST.get(posture),
        exposure={"days": ex.days, "episode_days": ex.episode_days,
                  "episode_count": ex.episode_count, "cuts": ex.cuts,
                  "cut_source": ex.cut_source, "median_dom": ex.median_dom,
                  "ratio": round(ex.ratio, 3) if ex.ratio is not None else None,
                  "offer_passed": ex.offer_passed},
        value_gap_pct=round(value_gap, 4) if value_gap is not None else None,
        withdrawal_share=(WITHDRAWAL_SHARE if ex.ratio is not None
                          and ex.ratio >= WITHDRAWAL_RATIO else None),
        rejection_weight=round(w, 3), adjusted=adjusted, unadjusted_point=unadj_point,
        agreement=agreement, spread_pct=round(spread, 4) if spread is not None else None,
        signals=signals,
    )
