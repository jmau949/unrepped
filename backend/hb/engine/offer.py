"""Offer back-solver — docs/06-algorithms.md §6.

The buyer profile carries a fixed **dollar** down payment, so three limits
apply, and the lowest one wins: **cash** (below), the **20%-down lender floor**
(price ≤ down ÷ 20%), and — once an income is entered — the **payment limit**
(PITI ≤ the lender's debt-to-income ceiling, `affordability.max_housing_payment`).
The cash limit is the largest bid
whose `down_payment + closing + appraisal gap` fits ``cash_available``, where
the lender funds only appraised value × LTV and the buyer covers the gap in
cash, up to ``appraisal_gap_tolerance_pct`` of the appraisal proxy E. Beyond
that tolerated gap the bid is infeasible outright (``gap_capped``), not merely
expensive — with a healthy cash pile the ceiling is therefore usually
``(1+g)·E``, which is exactly the disciplined-bid message. Solved by bisection
on [0.5E, 1.5E] per the doc — immune to the kinks in the piecewise-linear cash
curve and to a future non-linear closing estimate.

The cash-constrained ``max_defensible_bid`` answers "what CAN I pay"; the
posture-driven ``ceiling`` answers "what SHOULD I pay at most" and is what the
escalation clause carries — for a market-rejected price the ceiling never
exceeds list, no matter how much cash the profile holds. Profile-only mode (no
listing, the Affordability page's inverse readout) has no appraisal anchor, so
it answers the one cash question that is still well-posed: the largest price
where cash covers down + closing **and still leaves 6 months of PITI in
reserve** (the reserves rule from §8).

The verdict generator turns the numbers into plain language (docs/06 §6
templates); ``verdict_template`` identifies the chosen template so tests
assert the selection matrix, not prose.
"""

import logging
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from hb.db.models import BuyerProfile, Listing, Property
from hb.engine import affordability, posture, valuation

log = logging.getLogger(__name__)

BISECT_TOL = 500          # dollars — well below offer granularity
MIN_DOWN_PCT = 0.20        # jumbo-lender floor: price ≤ down/0.20.
                           # (The affordability *calculator* still models PMI below
                           # 20% for what-if scenarios; the max-bid solver stays
                           # conservative.)
# opening-bid bands as fractions of list, keyed by recommendation (docs/06 §6)
UNDERBID_OPEN = (0.93, 0.97)  # lingering homes clear at a median ~0.975 of asking; open just under
AT_LIST_OPEN = (0.97, 1.00)
OVERBID_OPEN = (1.00, 1.02)
AT_LIST_CEIL_PCT = 1.02       # ceiling: just above the model value (list-capped when lingering)


@dataclass
class OfferSolution:
    max_defensible_bid: int
    cma_estimate: int | None
    predicted: dict | None   # {low, point, high, basis, unadjusted_point, rejection_weight} | None
    verdict: str
    verdict_template: str
    escalation_cap: int      # = ceiling — the value-justified number, not the cash max
    gap_capped: bool
    ltv_capped: bool         # the 20%-down lender floor was the binding constraint
    payment_capped: bool     # the income-based payment limit was the binding constraint
    limits: dict             # {cash, down_payment, payment|None}: each limit's price
    e_basis: str             # 'adjusted_blend' | 'cma' | 'list' | 'none'
    recommendation: str | None = None   # 'underbid' | 'at_list' | 'overbid' | None
    opening_range: dict | None = None   # {low, high} suggested opening bid
    ceiling: int = 0                    # min(cash max, value-justified cap)
    posture: dict | None = None         # PostureResult payload for the UI
    confidence: str | None = None       # recommendation confidence


def cash_needed(bid: float, e: float, down_payment: int, gap_tol_pct: float) -> float:
    gap = min(max(0.0, bid - e), gap_tol_pct * e)
    return down_payment + affordability.CLOSING_PCT * bid + gap


def solve_p_cash(cash_available: int, e: int, down_payment: int, gap_tol_pct: float,
                 tol: int = BISECT_TOL) -> tuple[float, bool]:
    """Largest bid with cash_needed(bid) ≤ cash_available. Returns
    (p_cash, gap_capped); gap_capped means the buyer had cash left but the
    appraisal-gap tolerance made higher bids infeasible."""
    if cash_available <= down_payment:
        return 0.0, False
    lo, hi = 0.5 * e, 1.5 * e
    if cash_available < cash_needed(lo, e, down_payment, gap_tol_pct):
        # below the doc's bracket the gap is zero and the curve inverts exactly
        return (cash_available - down_payment) / affordability.CLOSING_PCT, False
    if cash_available >= cash_needed(hi, e, down_payment, gap_tol_pct):
        p = hi
    else:
        while hi - lo > tol:
            mid = (lo + hi) / 2
            if cash_needed(mid, e, down_payment, gap_tol_pct) <= cash_available:
                lo = mid
            else:
                hi = mid
        p = lo
    cap = (1 + gap_tol_pct) * e
    if p > cap:
        return cap, True
    return p, False


def solve_reserves_price(cash_available: int, down_payment: int, rate_pct: float,
                         tax_rate: float, insurance_monthly: int, hoa_monthly: int,
                         earthquake_monthly: int) -> float:
    """Profile-only ceiling: largest P where
    cash = down + closing(P) + RESERVES_MONTHS·PITI(P). Linear in P per PMI
    branch (loan = P − down); solve without PMI first, re-solve with it if the
    no-PMI answer lands below 20% down."""
    months = affordability.RESERVES_MONTHS
    flat = insurance_monthly + hoa_monthly + earthquake_monthly
    budget = cash_available - down_payment - months * flat
    if budget <= 0:
        return 0.0
    f = affordability.monthly_pi(1, rate_pct)

    def _solve(with_pmi: bool) -> float:
        loan_rate = f + (affordability.PMI_ANNUAL_RATE / 12 if with_pmi else 0)
        coef = affordability.CLOSING_PCT + months * (loan_rate + tax_rate / 12)
        return (budget + months * down_payment * loan_rate) / coef

    p = _solve(with_pmi=False)
    if down_payment < 0.20 * p:  # PMI territory — redo with the PMI coefficient
        p = max(_solve(with_pmi=True), down_payment / 0.20)
    return p


def solve_payment_price(max_payment: float, down_payment: int, rate_pct: float,
                        tax_rate: float, flat_monthly: int) -> float:
    """Largest P whose PITI fits the payment limit: PI(P − down) + tax(P) +
    insurance/HOA/rider ≤ max_payment. Linear in P; no PMI, because the 20%-down
    floor already keeps every answer at or above 20% down."""
    f = affordability.monthly_pi(1, rate_pct)
    p = (max_payment - flat_monthly + down_payment * f) / (f + tax_rate / 12)
    return max(p, 0.0)


def _fmt(x: float | int) -> str:
    return f"${round(x):,}"


def _pct_of_list(value: float, list_price: int | None) -> str:
    return f"{value / list_price:.0%}" if list_price else "n/a"


def recommend(post: posture.PostureResult | None, predicted: dict | None,
              list_price: int | None, max_bid: int) -> tuple[str | None, dict | None, int]:
    """(recommendation, opening_range, ceiling) from the pricing posture.

    The ceiling is the value-justified cap, never above the cash-constrained
    ``max_bid``. For a lingering home it is the near-market rule (just above
    the market-adjusted value) capped at list: weeks of no-takers is not the
    moment to pay a CMA premium. The opening never exceeds the value cap."""
    if list_price is None or list_price <= 0:
        return None, None, max_bid
    p = post.posture if post else "unknown"
    if p == "overpriced":
        band = UNDERBID_OPEN
        cap = (min(list_price, round(predicted["point"] * AT_LIST_CEIL_PCT)) if predicted
               else list_price)
        rec, ceiling = "underbid", min(max_bid, cap)
    elif p == "underpriced":
        band = OVERBID_OPEN
        cap = predicted["high"] if predicted else round(list_price * AT_LIST_CEIL_PCT)
        rec, ceiling = "overbid", min(max_bid, cap)
    else:  # near_market | unknown — pay list-ish, anchored to the model value
        band = AT_LIST_OPEN
        cap = (round(predicted["point"] * AT_LIST_CEIL_PCT) if predicted
               else list_price)
        rec, ceiling = "at_list", min(max_bid, cap)
    # the opening never exceeds the value cap; when the cap sits below the whole
    # band the band slides down with it, keeping its width, so the buyer is never
    # told to open at the walk-away number
    opening = {"low": min(round(list_price * band[0]), round(cap * band[0] / band[1])),
               "high": min(round(list_price * band[1]), cap)}
    return rec, opening, ceiling


def _exposure_clause(post: posture.PostureResult | None) -> str:
    """'On market 87 days (area median 18), 2 price cut(s)' — the evidence line
    of the underbid verdict, read off the posture result."""
    ex = (post.exposure if post else None) or {}
    med = f"{ex['median_dom']:.0f}" if ex.get("median_dom") is not None else "n/a"
    days = ex.get("days") if ex.get("days") is not None else "?"
    episodes = ex.get("episode_count") or 1
    if episodes > 1:
        text = (f"On market {ex.get('episode_days', '?')} days this episode "
                f"({days} cumulative over {episodes} episodes; area median {med})")
    else:
        text = f"On market {days} days (area median {med})"
    cuts = ex.get("cuts") or 0
    source = ex.get("cut_source")
    cut = (f"{cuts} price cut(s)" if cuts else
           "price reduced per Realtor history" if source == "history" else
           "relisted below the previous ask" if source == "relist_lower" else
           "no price cut")
    return f"{text}, {cut}"


def select_verdict(max_bid: int, predicted: dict | None, list_price: int | None,
                   cma_estimate: int | None,
                   gap_capped: bool, gap_cap: int | None,
                   down_payment: int, cash_available: int,
                   ltv_capped: bool = False,
                   payment_capped: bool = False,
                   payment_limit: float | None = None,
                   profile_only: bool = False,
                   recommendation: str | None = None,
                   opening: dict | None = None,
                   ceiling: int | None = None,
                   post: posture.PostureResult | None = None) -> tuple[str, str]:
    """Docs/06 §6 template set, keyed on the posture recommendation. First
    matching row wins; independent modifier clauses are appended in fixed
    order. Returns (template_id, text)."""
    dti = f"{affordability.DTI_MAX:.0%}"
    if ltv_capped:
        limit_clause = (
            f" The binding limit is the {MIN_DOWN_PCT:.0%}-minimum-down lender floor "
            f"({_fmt(down_payment)} down ÷ {MIN_DOWN_PCT:.0%}) — raising the down payment "
            f"raises the ceiling.")
    elif payment_capped and payment_limit is not None:
        limit_clause = (
            f" The binding limit is the monthly payment: about {_fmt(payment_limit)}/mo, "
            f"{dti} of your gross income less your other debts, which is about where "
            f"lenders stop.")
    else:
        limit_clause = ""
    if profile_only:
        if ltv_capped:
            why = (f"That is where your {_fmt(down_payment)} down payment is "
                   f"{MIN_DOWN_PCT:.0%} of the price, the minimum most lenders here "
                   f"require. A bigger down payment raises it.")
        elif payment_capped and payment_limit is not None:
            why = (f"That is where the monthly payment reaches about "
                   f"{_fmt(payment_limit)}/mo: {dti} of your gross income, minus your "
                   f"other debts, which is about where lenders stop.")
        else:
            why = (f"That is where your savings still cover the {_fmt(down_payment)} down "
                   f"payment, closing costs and {affordability.RESERVES_MONTHS} months of "
                   f"payments in reserve. More savings beyond the down payment raise it.")
        nudge = ("" if payment_limit is not None else
                 " Add your income to include the monthly-payment limit lenders apply.")
        return ("profile_only", f"You can afford up to {_fmt(max_bid)}. {why}{nudge}")

    cap = ceiling if ceiling is not None else max_bid
    open_str = (f"{_fmt(opening['low'])}–{_fmt(opening['high'])}" if opening else "n/a")

    if predicted is None:
        template, text = "no_model", (
            f"Not enough recent comps to model a likely sale range. On cash alone "
            f"({_fmt(down_payment)} down out of {_fmt(cash_available)}) your max "
            f"defensible bid is {_fmt(max_bid)}."
        )
        if recommendation == "underbid":
            text += (" Market behaviour alone (exposure, cuts) says this asking price is "
                     "more likely than not to come down — open below list even without "
                     "a model.")
    elif opening and max_bid < opening["low"]:
        template, text = "out_of_reach", (
            f"Likely sale {_fmt(predicted['low'])}–{_fmt(predicted['high'])} (median "
            f"{_pct_of_list(predicted['point'], list_price)} of list). Your max defensible "
            f"bid {_fmt(max_bid)} is below even the suggested opening {open_str}. "
            f"Passing is reasonable; a preemptive knockout is not available to you."
        )
    elif recommendation == "underbid":
        offer_note = (", offer date passed with no pending"
                      if post and any(s["id"] == "offer_passed" for s in post.signals)
                      else "")
        chase_note = (f" — do not chase the CMA ({_fmt(cma_estimate)})"
                      if cma_estimate and list_price and cma_estimate > list_price else "")
        p = post.p_below_list if post else None
        share = f"About {int(p * 10 + 0.5)} in 10" if p is not None else "Most"
        typical = post.typical_sold_to_list if post else None
        under = (f", typically ~{(1 - typical) * 100:.1f}% under"
                 if typical is not None and typical < 1 else "")
        template, text = "underbid_lingering", (
            f"{_exposure_clause(post)}{offer_note}. {share} homes with this history sell "
            f"below asking{under} — likely sale {_fmt(predicted['low'])}–"
            f"{_fmt(predicted['high'])} (median {_pct_of_list(predicted['point'], list_price)} "
            f"of list). Open at {open_str} with comps attached; your ceiling is "
            f"{_fmt(cap)}{chase_note}."
        )
    elif recommendation == "at_list":
        template, text = "at_list_disciplined", (
            f"Listed near the model value — likely sale {_fmt(predicted['low'])}–"
            f"{_fmt(predicted['high'])} (median {_pct_of_list(predicted['point'], list_price)} "
            f"of list). Open at {open_str}; escalate only to your ceiling {_fmt(cap)}."
        )
    elif max_bid < predicted["low"]:
        template, text = "out_of_reach", (
            f"Likely sale {_fmt(predicted['low'])}–{_fmt(predicted['high'])} (median "
            f"{_pct_of_list(predicted['point'], list_price)} of list). Your max defensible "
            f"bid {_fmt(max_bid)} is below the likely range floor {_fmt(predicted['low'])}. "
            f"Passing is reasonable; a preemptive knockout is not available to you."
        )
    elif max_bid < predicted["high"]:
        template, text = "overbid_competitive", (
            f"Priced to spur bidding — likely sale {_fmt(predicted['low'])}–"
            f"{_fmt(predicted['high'])} (median {_pct_of_list(predicted['point'], list_price)} "
            f"of list). Your max defensible bid {_fmt(max_bid)} is inside the likely range — "
            f"competitive but disciplined. Open at {open_str}; escalate to {_fmt(cap)}, "
            f"not beyond."
        )
    else:
        template, text = "overbid_strong", (
            f"Priced to spur bidding — likely sale {_fmt(predicted['low'])}–"
            f"{_fmt(predicted['high'])}; your max defensible bid {_fmt(max_bid)} clears the "
            f"top of the range. Budget is not the constraint here — bid discipline is. "
            f"Open at {open_str}; cap your escalation at {_fmt(cap)}."
        )

    if cma_estimate is not None and list_price and cma_estimate < 0.98 * list_price:
        text += (f" The CMA ({_fmt(cma_estimate)}) sits below the list price — "
                 f"the list is a signal, not a floor.")
    if post is not None and post.agreement == "diverge" and post.spread_pct is not None:
        text += (f" Value estimates disagree by {post.spread_pct:.0%} — treat the point "
                 f"estimates as soft; the market-behaviour signals are the more reliable "
                 f"evidence.")
    if gap_capped and gap_cap is not None:
        text += (f" Your appraisal-gap tolerance caps the bid at {_fmt(gap_cap)} — "
                 f"more cash would not raise it.")
    text += limit_clause
    return template, text


def solve(session: Session, listing: Listing | None, prop: Property | None,
          profile: BuyerProfile, overrides: dict | None = None,
          city: str | None = None) -> OfferSolution:
    """Full back-solve for one listing (or profile-only when ``listing`` is
    None — the Affordability page's inverse readout, reserves-based)."""
    ov = overrides or {}

    def pick(name):
        v = ov.get(name)
        return v if v is not None else getattr(profile, name)

    cash = pick("cash_available")
    down = pick("down_payment")
    gap_tol = pick("appraisal_gap_tolerance_pct")
    insurance = pick("insurance_monthly_est")
    include_eq = pick("include_earthquake_ins")
    payment_limit = affordability.max_housing_payment(
        pick("annual_income"), pick("monthly_debts"))
    rate = ov.get("rate_assumption")
    if rate is None:
        rate = profile.rate_assumption
    if rate is None:
        rate = affordability.latest_rate(session) or 6.5
    hoa = ov.get("hoa_monthly")
    if hoa is None:
        hoa = int((listing.raw or {}).get("hoa_fee") or 0) if listing is not None else 0
    earthquake = affordability.optional_insurance_monthly() if include_eq else 0
    tax_rate = affordability.tax_rate_for_city(prop.city if prop else city)

    if listing is None:
        p_cash = solve_reserves_price(cash, down, rate, tax_rate,
                                      insurance, hoa, earthquake)
        gap_capped, gap_cap = False, None
        cma_estimate, predicted, e_basis = None, None, "none"
        post = None
        profile_only = True
    else:
        cma_estimate = valuation.latest_cma_estimate(session, prop.id)
        predicted = valuation.predicted_sale(session, listing, prop)
        post = posture.classify(session, listing, prop, predicted, cma_estimate)
        # appraisal proxy E: the market-adjusted blend — the model value AFTER
        # prolonged-exposure evidence — then the CMA, then list as last resort
        if predicted is not None:
            e, e_basis = predicted["point"], "adjusted_blend"
        elif cma_estimate is not None:
            e, e_basis = cma_estimate, "cma"
        else:
            e, e_basis = listing.list_price or 0, "list"
        if e > 0:
            p_cash, gap_capped = solve_p_cash(cash, e, down, gap_tol)
        else:  # no appraisal proxy at all — degrade to the gap-free closed form
            p_cash = max(cash - down, 0) / affordability.CLOSING_PCT
            gap_capped = False
        gap_cap = round((1 + gap_tol) * e) if gap_capped else None
        profile_only = False

    # Three limits, the lowest wins. Lender floor: price ≤ down / MIN_DOWN_PCT
    # (down = 0 ⇒ ceiling 0 — the profile isn't filled in yet, and a $0 answer says
    # so louder than $12M). Payment limit: only once an income is entered.
    ltv_cap = down / MIN_DOWN_PCT
    p_pay = (solve_payment_price(payment_limit, down, rate, tax_rate,
                                 insurance + hoa + earthquake)
             if payment_limit is not None else None)
    limits = {"cash": round(p_cash), "down_payment": round(ltv_cap),
              "payment": round(p_pay) if p_pay is not None else None}
    ltv_capped = payment_capped = False
    if ltv_cap < p_cash and (p_pay is None or ltv_cap <= p_pay):
        p_cash, ltv_capped = ltv_cap, True
    elif p_pay is not None and p_pay < p_cash:
        p_cash, payment_capped = p_pay, True
    if ltv_capped or payment_capped:
        gap_capped, gap_cap = False, None  # a lender-side limit binds first

    max_bid = round(p_cash)
    recommendation, opening, ceiling = (
        recommend(post, predicted, listing.list_price or listing.original_list_price, max_bid)
        if listing is not None else (None, None, max_bid))
    template, verdict = select_verdict(
        max_bid, predicted, listing.list_price if listing else None, cma_estimate,
        gap_capped, gap_cap, down, cash,
        ltv_capped=ltv_capped, payment_capped=payment_capped,
        payment_limit=payment_limit, profile_only=profile_only,
        recommendation=recommendation, opening=opening, ceiling=ceiling, post=post,
    )
    confidence = None
    if post is not None:
        confidence = post.confidence
        if post.agreement == "diverge" and confidence == "high":
            confidence = "medium"  # disagreeing estimates never carry full conviction
    return OfferSolution(
        max_defensible_bid=max_bid,
        cma_estimate=cma_estimate,
        predicted=predicted,
        verdict=verdict,
        verdict_template=template,
        escalation_cap=ceiling,
        gap_capped=gap_capped,
        ltv_capped=ltv_capped,
        payment_capped=payment_capped,
        limits=limits,
        e_basis=e_basis,
        recommendation=recommendation,
        opening_range=opening,
        ceiling=ceiling,
        posture={k: v for k, v in asdict(post).items()
                 if k not in ("adjusted", "unadjusted_point")} if post is not None else None,
        confidence=confidence,
    )
