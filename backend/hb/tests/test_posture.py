"""Pricing-posture unit tests — docs/06 §5.6 (calibrated curve, probability
tiers, rejection weight, market-evidence adjustment)."""

from datetime import date, timedelta

import pytest

from hb.db.models import AvmSnapshot, Listing, ListingEvent, ListingGroup, MarketMetric, Property
from hb.engine import posture

TODAY = date.today()


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


# --- the calibrated curve ----------------------------------------------------------

def test_exposure_logit_interpolates_between_knots_and_is_flat_outside():
    (x0, y0), (x1, y1), (x2, y2) = posture.EXPOSURE_LOGIT
    assert posture.exposure_logit(x0) == pytest.approx(y0)
    assert posture.exposure_logit(x1) == pytest.approx(y1)
    assert posture.exposure_logit(x2) == pytest.approx(y2)
    assert posture.exposure_logit((x0 + x1) / 2) == pytest.approx((y0 + y1) / 2)
    assert posture.exposure_logit(0.0) == pytest.approx(y0)    # fresher than the first knot
    assert posture.exposure_logit(12.0) == pytest.approx(y2)   # beyond the last knot


def test_features_match_the_curve():
    """The backtest re-fit and the classifier must be the same model: the
    feature row dotted with the knot differences reproduces the curve."""
    (_, y0), (_, y1), (_, y2) = posture.EXPOSURE_LOGIT
    coefs = [y0, y1 - y0, y2 - y1, posture.CUT_LOGIT, posture.RELIST_LOGIT]
    for ratio in (0.2, 0.5, 0.9, 1.25, 2.5, 4.0, 7.0):
        row = posture.features(ratio, had_cut=True, relisted=True)
        assert sum(c * f for c, f in zip(coefs, row)) == pytest.approx(
            posture.exposure_logit(ratio) + posture.CUT_LOGIT + posture.RELIST_LOGIT)
    assert posture.knots_from_coefficients(y0, y1 - y0, y2 - y1) == posture.EXPOSURE_LOGIT


def test_tier_boundaries():
    assert posture.sigmoid(0.0) == 0.5
    assert posture.UNDER_P < 0.5 < posture.OVER_P
    assert posture.MEDIUM_P < posture.HIGH_P


# --- market_adjusted invariants ------------------------------------------------

PRED = {"low": 2_610_000, "point": 2_930_000, "high": 3_230_000}
LIST = 2_650_000


def test_market_adjusted_noop_at_zero_weight():
    assert posture.market_adjusted(PRED, LIST, 0.0) == PRED


def test_market_adjusted_full_weight_pulls_point_to_anchor():
    adj = posture.market_adjusted(PRED, LIST, 1.0)
    assert adj["point"] == round(LIST * posture.NO_SALE_ANCHOR)
    assert adj["low"] <= adj["point"] <= adj["high"]
    # once rejection is half-credible the high end sits just above list
    assert adj["high"] == round(LIST * posture.ADJ_RANGE_HIGH_CAP)


def test_market_adjusted_never_raises_the_estimate():
    # list ABOVE the model point: target = min(point, anchor) = point => no-op
    adj = posture.market_adjusted(PRED, 3_400_000, 1.0)
    assert adj["point"] == PRED["point"]
    for w in (0.0, 0.3, 0.7, 1.0):
        adj = posture.market_adjusted(PRED, LIST, w)
        assert adj["point"] <= PRED["point"]
        assert adj["low"] <= adj["point"] <= adj["high"]


def test_market_adjusted_partial_weight_interpolates():
    adj = posture.market_adjusted(PRED, LIST, 0.5)
    assert adj["point"] == round(0.5 * PRED["point"] + 0.5 * round(LIST * posture.NO_SALE_ANCHOR))


def test_market_adjusted_below_half_weight_keeps_high():
    adj = posture.market_adjusted(PRED, LIST, 0.49)
    assert adj["high"] == PRED["high"]


# --- rejection_weight ------------------------------------------------------------

def test_rejection_weight_ramp():
    assert posture.rejection_weight(0.5) == 0.0            # inside the first offer window
    assert posture.rejection_weight(1.0) == 0.0            # at the median — ramp starts
    assert posture.rejection_weight(1.125) == pytest.approx(0.5)
    assert posture.rejection_weight(1.25) == 1.0           # the curve's step is complete
    assert posture.rejection_weight(4.1) == 1.0            # saturates


def test_rejection_weight_offer_passed_bonus():
    assert posture.rejection_weight(1.0, offer_passed=True) == \
        pytest.approx(posture.OFFER_PASSED_W_BONUS)
    assert posture.rejection_weight(1.25, offer_passed=True) == 1.0  # capped


def test_rejection_weight_missing_data():
    assert posture.rejection_weight(None) == 0.0
    assert posture.rejection_weight(None, offer_passed=True) == \
        pytest.approx(posture.OFFER_PASSED_W_BONUS)


# --- estimate agreement ----------------------------------------------------------

def test_agreement_needs_two_sources():
    assert posture.estimate_agreement([2_900_000]) == ("unknown", None)
    assert posture.estimate_agreement([]) == ("unknown", None)


def test_agreement_bands():
    a, s = posture.estimate_agreement([2_900_000, 2_950_000])
    assert a == "agree" and s < posture.AGREE_PCT
    a, _ = posture.estimate_agreement([2_900_000, 3_200_000])
    assert a == "moderate"
    a, s = posture.estimate_agreement([2_650_000, 3_360_000])
    assert a == "diverge" and s > posture.DIVERGE_PCT


# --- classify (seeded sessions) ---------------------------------------------------

def _median_dom(session, value=10.0, period_start="2026-01-01"):
    session.add(MarketMetric(geo_type="city", geo_id="Sunnyvale", period_start=period_start,
                             period="monthly", metric="median_dom", value=value,
                             source="redfin"))


def _subject(session, *, list_price=LIST, days=None, list_date=None,
             offer_due_at=None, status="active"):
    """One active episode listed `days` ago (or on `list_date`); no list date at
    all when both are None."""
    prop = Property(address_norm="1 SUBJECT WAY", zip="94087", city="Sunnyvale",
                    beds=3, baths=2.0, sqft=1600, property_type="single_family")
    session.add(prop)
    session.flush()
    if list_date is None and days is not None:
        list_date = _iso(days)
    group = None
    if list_date is not None:
        group = ListingGroup(property_id=prop.id, episode_count=1, first_list_date=list_date)
        session.add(group)
        session.flush()
    lst = Listing(property_id=prop.id, listing_group_id=group.id if group else None,
                  source="realtor", source_listing_id="SUBJ1", status=status,
                  list_price=list_price, original_list_price=list_price,
                  list_date=list_date, offer_due_at=offer_due_at)
    session.add(lst)
    session.flush()
    return lst, prop


def _ids(result):
    return {s["id"] for s in result.signals}


def test_classify_market_rejected_shape_is_overpriced_medium(session):
    """The motivating case: CMA far above list, 41 days exposure vs median 10
    and a passed offer date. The market has said no — but only ~3 in 4 such
    homes sell below asking, so the honest call is overpriced at MEDIUM, with
    the served value pulled to 0.98 × list."""
    _median_dom(session)
    lst, prop = _subject(session, days=41, offer_due_at=_iso(30))
    session.commit()

    r = posture.classify(session, lst, prop,
                         predicted={"low": 2_610_000, "point": 2_930_000, "high": 3_230_000},
                         cma_estimate=3_360_000)
    assert r.posture == "overpriced"
    assert r.confidence == "medium"
    assert 0.72 < r.p_below_list < posture.HIGH_P
    assert r.logit == pytest.approx(posture.exposure_logit(4.1) + posture.OFFER_PASSED_LOGIT, abs=1e-3)
    assert r.rejection_weight == 1.0
    assert r.adjusted["point"] == round(LIST * posture.NO_SALE_ANCHOR)
    assert r.adjusted["high"] == round(LIST * posture.ADJ_RANGE_HIGH_CAP)
    assert _ids(r) == {"exposure", "offer_passed"}
    assert r.value_gap_pct == pytest.approx(LIST / 2_930_000 - 1, abs=1e-3)
    assert r.typical_sold_to_list == posture.TYPICAL_SOLD_TO_LIST["overpriced"]
    assert r.withdrawal_share == posture.WITHDRAWAL_SHARE
    assert r.exposure["days"] == 41 and r.exposure["ratio"] == 4.1


def test_classify_fresh_listing_is_underpriced(session):
    """Half the median DOM in, no cut, single episode: ~7 in 10 such homes
    sell at or above asking — the bait convention, stated as a probability
    (and only MEDIUM confidence: 3 in 10 fresh listings still clear below)."""
    _median_dom(session)
    lst, prop = _subject(session, list_price=2_050_000, days=5)
    session.commit()

    r = posture.classify(session, lst, prop,
                         predicted={"low": 2_150_000, "point": 2_270_000, "high": 2_390_000},
                         cma_estimate=2_260_000)
    assert r.posture == "underpriced"
    assert r.confidence == "medium"
    assert 0.20 < r.p_below_list < posture.UNDER_P
    assert _ids(r) == {"exposure"}
    assert r.signals[0]["points"] < 0
    assert r.rejection_weight == 0.0
    assert r.adjusted == {"low": 2_150_000, "point": 2_270_000, "high": 2_390_000}  # untouched
    assert r.withdrawal_share is None


def test_classify_relist_resets_clock(session):
    """A relist is judged on its new episode: 60 days in a withdrawn first
    episode plus 5 days at the new ask reads as 0.5× the median, not 6.5× —
    the failure mode that labelled fresh relists 'overpriced, high'."""
    _median_dom(session)
    lst, prop = _subject(session, list_price=2_800_000, days=5)
    group = session.get(ListingGroup, lst.listing_group_id)
    group.episode_count = 2
    session.add(Listing(property_id=prop.id, listing_group_id=group.id, source="realtor",
                        source_listing_id="SUBJ0", status="delisted", list_price=2_800_000,
                        original_list_price=2_800_000, list_date=_iso(95), delist_date=_iso(35)))
    session.commit()

    r = posture.classify(session, lst, prop, predicted=None)
    assert r.exposure["ratio"] == 0.5
    assert r.exposure["days"] == 65 and r.exposure["episode_days"] == 5
    assert "relist" in _ids(r) and "price_cuts" not in _ids(r)
    assert r.p_below_list < posture.OVER_P
    assert r.posture != "overpriced"
    assert "cumulative across 2 episodes" in next(s for s in r.signals if s["id"] == "exposure")["detail"]


def test_classify_behavior_only_stale_with_cut(session):
    """No CMA, no model — exposure plus a price cut still says overpriced at
    medium confidence; there is just no value to adjust."""
    _median_dom(session)
    lst, prop = _subject(session, days=40)
    session.add(ListingEvent(listing_id=lst.id, event_type="price_change",
                             old_value="2750000", new_value="2650000",
                             observed_at=_iso(20) + "T00:00:00+00:00"))
    session.commit()

    r = posture.classify(session, lst, prop, predicted=None, cma_estimate=None)
    assert r.posture == "overpriced"
    assert r.confidence == "medium"
    assert r.logit == pytest.approx(posture.exposure_logit(4.0) + posture.CUT_LOGIT, abs=1e-3)
    assert r.adjusted is None
    assert r.value_gap_pct is None
    assert next(s for s in r.signals if s["id"] == "price_cuts")["detail"].startswith("1 price cut")


def test_classify_no_data_is_unknown(session):
    lst, prop = _subject(session)  # no list date, no dom_source, no metrics
    session.commit()
    r = posture.classify(session, lst, prop, predicted=None, cma_estimate=None)
    assert r.posture == "unknown"
    assert r.confidence == "low"
    assert r.logit is None and r.p_below_list is None
    assert r.typical_sold_to_list is None


def test_classify_cut_without_median_is_a_fact_not_a_probability(session):
    """A price cut is reported as a signal even when no area median exists —
    but without the exposure base there is no probability to publish."""
    lst, prop = _subject(session, days=30)
    session.add(ListingEvent(listing_id=lst.id, event_type="price_change",
                             old_value="2750000", new_value="2650000",
                             observed_at=_iso(10) + "T00:00:00+00:00"))
    session.commit()
    r = posture.classify(session, lst, prop, predicted=None)
    assert r.posture == "unknown" and r.p_below_list is None
    assert _ids(r) == {"price_cuts"}


def test_classify_value_gap_is_informational(session):
    """A wildly disagreeing AVM changes the agreement label and nothing else:
    list-vs-value is reported, never voted."""
    _median_dom(session)
    lst, prop = _subject(session, list_price=2_200_000, days=10)
    predicted = {"low": 2_400_000, "point": 2_500_000, "high": 2_600_000}
    before = posture.classify(session, lst, prop, predicted=predicted, cma_estimate=2_450_000)
    assert before.agreement == "agree"
    assert before.posture == "near_market"
    assert before.value_gap_pct == pytest.approx(2_200_000 / 2_500_000 - 1, abs=1e-4)

    session.add(AvmSnapshot(property_id=prop.id, source="zestimate",
                            value=3_200_000, as_of="2026-07-01"))
    session.commit()
    after = posture.classify(session, lst, prop, predicted=predicted, cma_estimate=2_450_000)
    assert after.agreement == "diverge"
    assert (after.posture, after.confidence, after.p_below_list, after.signals) == \
        (before.posture, before.confidence, before.p_below_list, before.signals)


def test_classify_echoes_already_adjusted_predicted(session):
    """valuation.predicted_sale hands classify a post-adjustment payload — it
    must be echoed, not re-adjusted."""
    _median_dom(session)
    lst, prop = _subject(session, days=41)
    session.commit()
    adjusted_payload = {"low": 2_610_000, "point": 2_597_000, "high": 2_703_000,
                        "unadjusted_point": 2_930_000, "rejection_weight": 1.0}
    r = posture.classify(session, lst, prop, predicted=adjusted_payload)
    assert r.adjusted == {"low": 2_610_000, "point": 2_597_000, "high": 2_703_000}
    assert r.unadjusted_point == 2_930_000  # the value gap uses the pre-adjustment value


def test_classify_asof_ignores_future_cut_relist_and_offer_date(session):
    """Backtest discipline: a cut observed after as_of must not count, a later
    episode must not make it a relist, and the offer-date signal is live-only."""
    _median_dom(session)
    lst, prop = _subject(session, list_date="2026-06-20", offer_due_at=_iso(30))
    group = session.get(ListingGroup, lst.listing_group_id)
    session.add(ListingEvent(listing_id=lst.id, event_type="price_change",
                             old_value="2750000", new_value="2650000",
                             observed_at="2026-07-10T00:00:00+00:00"))
    session.add(Listing(property_id=prop.id, listing_group_id=group.id, source="realtor",
                        source_listing_id="SUBJ2", status="active", list_price=2_500_000,
                        original_list_price=2_500_000, list_date="2026-08-01"))
    session.commit()

    r = posture.classify(session, lst, prop, predicted=None, cma_estimate=3_000_000,
                         as_of="2026-06-25")
    assert _ids(r) == {"exposure"}
    exposure = next(s for s in r.signals if s["id"] == "exposure")
    assert "5 days vs area median 10" in exposure["detail"]
    assert r.exposure["episode_count"] == 1
