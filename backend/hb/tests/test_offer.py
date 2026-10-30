"""Offer back-solver unit tests — docs/06 §6 (cash/gap constraint, verdict matrix)."""

import pytest

from hb.db.models import BuyerProfile
from hb.engine import affordability, offer, posture


@pytest.fixture
def seeded(session):
    session.add(BuyerProfile(id="default"))
    session.commit()
    return session


# --- cash constraint (fixed dollar down payment) -------------------------------

def test_bisection_converges_within_500():
    """Mid-segment (E < bid < (1+g)E) analytic answer:
    cash = D + 0.015·b + (b − E)  =>  b = (cash − D + E)/1.015."""
    e, down, g = 2_000_000, 450_000, 0.05
    target = 2_050_000
    cash = round(down + 1.015 * target - e)
    p, capped = offer.solve_p_cash(cash, e, down, g)
    assert p == pytest.approx(target, abs=500)
    assert capped is False


def test_cash_below_bracket_exact():
    """Below 0.5E the gap is zero: b = (cash − D)/0.015 exactly."""
    p, capped = offer.solve_p_cash(460_000, 2_000_000, 450_000, 0.05)
    assert p == pytest.approx(10_000 / 0.015, abs=1)
    assert capped is False


def test_gap_cap_infeasibility():
    """Plenty of cash, but the tolerated appraisal gap caps the bid at (1+g)·E."""
    p, capped = offer.solve_p_cash(1_000_000, 2_000_000, 450_000, 0.05)
    assert capped is True
    assert p == pytest.approx(1.05 * 2_000_000, abs=1)


def test_down_exceeding_cash_gives_zero():
    p, capped = offer.solve_p_cash(400_000, 2_000_000, 450_000, 0.05)
    assert p == 0.0
    assert capped is False


def test_cash_needed_is_monotone_and_kinked():
    e, down, g = 2_000_000, 450_000, 0.05
    below = offer.cash_needed(e - 1, e, down, g)
    at = offer.cash_needed(e, e, down, g)
    above = offer.cash_needed(e + 100_000, e, down, g)
    capped = offer.cash_needed(e * 1.10, e, down, g)
    assert below < at < above < capped
    # gap saturates at g*E; past it only closing scales with the bid
    assert offer.cash_needed(e * 1.5, e, down, g) - offer.cash_needed(e * 1.4, e, down, g) \
        == pytest.approx(affordability.CLOSING_PCT * 0.1 * e, rel=1e-6)


# --- profile-only reserves ceiling ---------------------------------------------

def test_reserves_price_roundtrip(seeded):
    """The solved P must satisfy cash == down + closing + 6·PITI within $1/mo."""
    cash, down = 800_000, 450_000
    p = offer.solve_reserves_price(cash, down, 6.5, 0.0128,
                                   insurance_monthly=250, hoa_monthly=0,
                                   earthquake_monthly=0)
    assert p > down
    r = affordability.calc(seeded, round(p), "Sunnyvale", down_payment=down,
                           rate=6.5, insurance_monthly=250, cash_available=cash)
    assert r.reserves_after == pytest.approx(6 * r.piti, abs=6)


def test_reserves_price_zero_when_down_eats_cash():
    assert offer.solve_reserves_price(400_000, 450_000, 6.5, 0.0128, 250, 0, 0) == 0.0


def test_solve_profile_only_ltv_capped(seeded):
    """$2M cash / $1M down must give $5M (down ÷ 20%),
    not the ~$16.7M the reserves rule alone would allow."""
    profile = seeded.get(BuyerProfile, "default")
    profile.cash_available = 2_000_000
    profile.down_payment = 1_000_000
    profile.rate_assumption = 6.5
    seeded.commit()
    sol = offer.solve(seeded, None, None, profile, city="Sunnyvale")
    assert sol.verdict_template == "profile_only"
    assert sol.predicted is None
    assert sol.e_basis == "none"
    assert sol.max_defensible_bid == 5_000_000
    assert sol.ltv_capped is True
    assert sol.payment_capped is False
    assert "20% of the price" in sol.verdict
    assert "Add your income" in sol.verdict  # no income entered: the nudge shows
    assert sol.limits["payment"] is None
    assert sol.escalation_cap == sol.max_defensible_bid


def test_solve_profile_only_payment_capped(seeded):
    """The same $2M cash / $1M down with a $300k income: the lender's payment limit
    (43% of gross income) binds far below the $5M the 20%-down floor allows."""
    profile = seeded.get(BuyerProfile, "default")
    profile.cash_available = 2_000_000
    profile.down_payment = 1_000_000
    profile.rate_assumption = 6.5
    profile.annual_income = 300_000
    profile.monthly_debts = 1_000
    seeded.commit()
    sol = offer.solve(seeded, None, None, profile, city="Sunnyvale")
    assert sol.payment_capped is True and sol.ltv_capped is False
    assert sol.limits["down_payment"] == 5_000_000
    assert sol.max_defensible_bid == sol.limits["payment"] < 5_000_000
    assert "monthly payment" in sol.verdict and "Add your income" not in sol.verdict
    # at the answer the payment sits on the limit: 0.43 * 300k / 12 - 1k = $9,750
    r = affordability.calc(seeded, sol.max_defensible_bid, "Sunnyvale",
                           down_payment=1_000_000, rate=6.5, insurance_monthly=250,
                           annual_income=300_000, monthly_debts=1_000)
    assert r.payment_limit == 9_750
    assert r.piti == pytest.approx(9_750, abs=5)
    assert r.payment_ok is True


def test_payment_limit_off_without_income(seeded):
    r = affordability.calc(seeded, 2_000_000, "Sunnyvale", down_payment=400_000, rate=6.5)
    assert r.payment_limit is None and r.payment_ok is None


def test_solve_profile_only_reserves_bound(seeded):
    """Tight cash relative to down: the reserves ceiling binds below the LTV cap."""
    profile = seeded.get(BuyerProfile, "default")
    profile.cash_available = 1_150_000
    profile.down_payment = 1_000_000  # LTV cap 5M, but only 150k left for closing+reserves
    profile.rate_assumption = 6.5
    seeded.commit()
    sol = offer.solve(seeded, None, None, profile, city="Sunnyvale")
    assert sol.ltv_capped is False
    assert 0 < sol.max_defensible_bid < 5_000_000


def test_solve_zero_down_gives_zero_ceiling(seeded):
    profile = seeded.get(BuyerProfile, "default")
    profile.cash_available = 2_000_000
    profile.down_payment = 0
    profile.rate_assumption = 6.5
    seeded.commit()
    sol = offer.solve(seeded, None, None, profile, city="Sunnyvale")
    assert sol.max_defensible_bid == 0
    assert sol.ltv_capped is True


# --- recommendation layer -------------------------------------------------------

PRED_FRESH = {"low": 2_150_000, "point": 2_270_000, "high": 2_390_000, "basis": "fresh"}
PRED_STALE = {"low": 1_990_000, "point": 2_030_000, "high": 2_070_000, "basis": "stale"}
LIST = 2_050_000


EXPOSURE_87 = {"days": 87, "episode_days": 87, "episode_count": 1, "cuts": 2,
               "cut_source": "observed", "median_dom": 18.0, "ratio": 4.83,
               "offer_passed": False}
P_BY_REC = {"underbid": 0.74, "at_list": 0.4, "overbid": 0.13}


def _post(p, p_below=None, agreement="agree", spread=0.02, signals=(), exposure=None):
    return posture.PostureResult(
        posture=p, confidence="medium", logit=None, p_below_list=p_below,
        typical_sold_to_list=posture.TYPICAL_SOLD_TO_LIST.get(p), exposure=exposure,
        value_gap_pct=None, withdrawal_share=None, rejection_weight=0.0,
        adjusted=None, unadjusted_point=None, agreement=agreement,
        spread_pct=spread, signals=list(signals),
    )


def test_recommend_overpriced_caps_ceiling_at_list():
    """Deep cash must NOT raise the ceiling past a lingering home's list price:
    the cap is the near-market rule (1.02 x the adjusted point) capped at list."""
    rec, opening, ceiling = offer.recommend(
        _post("overpriced", 0.74), PRED_STALE, LIST, max_bid=3_500_000)
    assert rec == "underbid"
    assert ceiling == LIST   # min(list, round(2_030_000 * 1.02) = 2_070_600)
    assert opening == {"low": round(LIST * 0.93), "high": round(LIST * 0.97)}


def test_recommend_opening_never_exceeds_ceiling():
    """When the market-adjusted value sits well below list, the value cap binds
    and the opening band slides down under it keeping its width — never 'open
    at X, ceiling < X', and never 'open at your walk-away number'."""
    low_pred = {"low": 1_700_000, "point": 1_800_000, "high": 1_900_000, "basis": "stale"}
    _, opening, ceiling = offer.recommend(
        _post("overpriced", 0.74), low_pred, LIST, max_bid=3_500_000)
    cap = round(1_800_000 * offer.AT_LIST_CEIL_PCT)
    assert ceiling == cap
    assert opening == {"low": round(cap * 0.93 / 0.97), "high": cap}
    assert opening["low"] < opening["high"] <= ceiling


def test_recommend_underpriced_ceiling_is_value_justified():
    rec, opening, ceiling = offer.recommend(
        _post("underpriced", 0.13), PRED_FRESH, LIST, max_bid=3_500_000)
    assert rec == "overbid"
    assert ceiling == PRED_FRESH["high"]        # value cap, not the cash max
    assert opening == {"low": LIST, "high": round(LIST * 1.02)}


def test_recommend_ceiling_never_exceeds_cash():
    _, _, ceiling = offer.recommend(
        _post("underpriced", 0.13), PRED_FRESH, LIST, max_bid=2_200_000)
    assert ceiling == 2_200_000


def test_recommend_near_market_and_unknown():
    rec, opening, ceiling = offer.recommend(
        _post("near_market", 0.4), PRED_FRESH, LIST, max_bid=3_500_000)
    assert rec == "at_list"
    assert ceiling == round(PRED_FRESH["point"] * offer.AT_LIST_CEIL_PCT)
    assert opening == {"low": round(LIST * 0.97), "high": LIST}
    rec, _, ceiling = offer.recommend(None, None, LIST, max_bid=3_500_000)
    assert rec == "at_list" and ceiling == LIST


def test_recommend_no_list_price():
    assert offer.recommend(_post("overpriced", 0.74), PRED_STALE, None, 2_000_000) \
        == (None, None, 2_000_000)


# --- verdict selection matrix -------------------------------------------------

def _verdict(max_bid, predicted, recommendation, *, list_price=LIST, cma=None,
             post=None, opening=None, ceiling=None, gap_capped=False, gap_cap=None):
    if post is None and recommendation is not None:
        post = _post({"underbid": "overpriced", "at_list": "near_market",
                      "overbid": "underpriced"}[recommendation],
                     P_BY_REC[recommendation], exposure=EXPOSURE_87)
    if opening is None and recommendation is not None and list_price:
        _, opening, ceiling = offer.recommend(post, predicted, list_price, max_bid)
    return offer.select_verdict(
        max_bid, predicted, list_price=list_price, cma_estimate=cma,
        gap_capped=gap_capped, gap_cap=gap_cap,
        down_payment=450_000, cash_available=800_000,
        recommendation=recommendation, opening=opening, ceiling=ceiling, post=post,
    )


@pytest.mark.parametrize(
    "max_bid, predicted, recommendation, expected",
    [
        (2_310_000, None, None, "no_model"),
        (2_310_000, None, "underbid", "no_model"),           # behaviour-only underbid note
        (2_050_000, PRED_STALE, "underbid", "underbid_lingering"),
        (3_500_000, PRED_STALE, "underbid", "underbid_lingering"),  # rich ≠ chase CMA
        (1_800_000, PRED_STALE, "underbid", "out_of_reach"),  # below even the opening
        (2_050_000, PRED_FRESH, "at_list", "at_list_disciplined"),
        (2_050_000, PRED_FRESH, "overbid", "out_of_reach"),   # can open, can't compete
        (2_150_000, PRED_FRESH, "overbid", "overbid_competitive"),  # B == low (inclusive)
        (2_310_000, PRED_FRESH, "overbid", "overbid_competitive"),  # inside the range
        (2_390_000, PRED_FRESH, "overbid", "overbid_strong"),  # B == high (inclusive top)
        (2_500_000, PRED_FRESH, "overbid", "overbid_strong"),
    ],
)
def test_verdict_matrix(max_bid, predicted, recommendation, expected):
    template, _text = _verdict(max_bid, predicted, recommendation)
    assert template == expected


def test_verdict_underbid_never_recommends_above_list():
    """The lingering-home failure mode: huge cash + high CMA must still read as
    an underbid with a ceiling at list, not a green light to $3.5M — and the
    verdict states the calibrated share, not an absolute claim."""
    post = _post("overpriced", 0.74, exposure=EXPOSURE_87,
                 signals=[{"id": "offer_passed", "label": "Offer date passed",
                           "points": 0.5, "detail": "offer date passed"}])
    template, text = _verdict(3_500_000, PRED_STALE, "underbid",
                              cma=3_360_000, post=post)
    assert template == "underbid_lingering"
    assert "About 7 in 10 homes with this history sell below asking" in text
    assert "typically ~2.7% under" in text
    assert f"your ceiling is ${LIST:,}" in text
    assert "do not chase the CMA ($3,360,000)" in text
    assert "offer date passed with no pending" in text
    assert "has not accepted" not in text


def test_verdict_signal_not_floor_modifier():
    _, text = _verdict(2_310_000, PRED_FRESH, "at_list",
                       list_price=2_400_000, cma=2_200_000)
    assert "a signal, not a floor" in text


def test_verdict_divergence_hedge():
    post = _post("near_market", 0.4, agreement="diverge", spread=0.21)
    _, text = _verdict(2_310_000, PRED_FRESH, "at_list", post=post)
    assert "Value estimates disagree by 21%" in text
    assert "market-behaviour signals" in text


def test_verdict_gap_capped_modifier():
    _, text = _verdict(2_310_000, PRED_FRESH, "overbid",
                       gap_capped=True, gap_cap=2_310_000)
    assert "appraisal-gap tolerance caps" in text


def test_verdict_underbid_slots():
    template, text = _verdict(2_050_000, PRED_STALE, "underbid")
    assert template == "underbid_lingering"
    assert "On market 87 days (area median 18), 2 price cut(s)" in text
    assert "$1,906,500–$1,988,500" in text  # 93–97% of list


def test_verdict_underbid_relist_reads_the_episode_clock():
    post = _post("overpriced", 0.74, exposure={
        **EXPOSURE_87, "days": 120, "episode_days": 33, "episode_count": 2,
        "cuts": 0, "cut_source": "relist_lower"})
    _, text = _verdict(2_050_000, PRED_STALE, "underbid", post=post)
    assert "On market 33 days this episode (120 cumulative over 2 episodes; area median 18)" in text
    assert "relisted below the previous ask" in text
