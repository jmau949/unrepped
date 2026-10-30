from datetime import date

import pytest

from hb import backtest
from hb.db.models import Listing, ListingEvent, MarketMetric, PriceIndex, Property, Sale
from hb.engine import cma, posture

AS_OF = "2026-06-19"
LIST_DATE = "2026-06-20"
SALE_DATE = "2026-07-10"
TODAY = date(2026, 7, 14)
SUBJ_LAT, SUBJ_LON = 37.350, -122.030


@pytest.fixture
def market(session):
    for mo in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"):
        session.add(PriceIndex(geo_type="zip", geo_id="94087", month=mo,
                               index_value=1.0, source="blend"))
    for ps in ("2026-04-01", "2026-05-01", "2026-06-01"):
        session.add(MarketMetric(geo_type="zip", geo_id="94087", period_start=ps,
                                 period="monthly", metric="median_ppsf", value=1400, source="redfin"))
    session.commit()
    return session


def _prop(session, addr, sqft, *, dlat=0.001, dlon=0.001):
    p = Property(address_norm=addr, zip="94087", city="Sunnyvale",
                 lat=SUBJ_LAT + dlat, lon=SUBJ_LON + dlon, beds=3, baths=2.0, sqft=sqft,
                 lot_sqft=5000, year_built=1975, condition_tag="dated",
                 property_type="single_family")
    session.add(p)
    session.flush()
    return p


def _sale(session, prop, sale_date, price, *, listing_id=None, sp_lp=1.0):
    s = Sale(property_id=prop.id, listing_id=listing_id, sale_date=sale_date, sale_price=price,
             original_list_price=round(price / sp_lp), sp_lp=sp_lp, source="realtor_sold_scan")
    session.add(s)
    session.flush()
    return s


def test_leakage_post_asof_comp_excluded(market):
    subj = _prop(market, "100 SUBJECT ST", 1600, dlat=0.0, dlon=0.0)
    pre = [_sale(market, _prop(market, f"{i} PRE AVE", 1600 + (i - 2) * 30),
                 "2026-05-05", 2_200_000 + i * 10_000) for i in range(5)]
    post = _sale(market, _prop(market, "9 POST AVE", 1600), "2026-06-25", 2_500_000)
    market.commit()

    result = cma.run(market, subj.id, as_of=AS_OF, persist=False)
    ids = {c.sale_id for c in result.comps}
    assert post.id not in ids, "a comp sold after the as-of date must be excluded"
    assert any(s.id in ids for s in pre), "pre-as-of comps must be eligible"


def test_run_backtest_end_to_end(market, tmp_path, monkeypatch):
    from hb import config
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)

    subj = _prop(market, "100 SUBJECT ST", 1600, dlat=0.0, dlon=0.0)
    lst = Listing(property_id=subj.id, source="realtor", source_listing_id="SUBJ",
                  status="sold", list_price=2_050_000, original_list_price=2_050_000,
                  list_date=LIST_DATE)
    market.add(lst)
    market.flush()
    # the subject's actual sale (after listing) — the thing we score against
    _sale(market, subj, SALE_DATE, 2_270_000, listing_id=lst.id, sp_lp=1.107)
    # comps sold BEFORE the as-of date, feeding both CMA and overbid
    for i, r in enumerate((1.08, 1.10, 1.12, 1.12, 1.14, 1.11)):
        p = _prop(market, f"{i} COMP AVE", 1580 + i * 20, dlat=0.001 * (i + 1))
        _sale(market, p, "2026-05-10", round(2_050_000 * r), sp_lp=r)
    # a stale subject for pass B: listed 2026-05-01 at 2.6M, cut to 2.46M, sold
    # near the cut list after 70 days — mid-flight (06-19) it has a real
    # exposure story and the market-adjusted value must beat the raw blend
    market.add(MarketMetric(geo_type="city", geo_id="Sunnyvale", period_start="2026-06-01",
                            period="monthly", metric="median_dom", value=12.0,
                            source="redfin"))
    stale_prop = _prop(market, "200 STALE ST", 1620, dlat=0.002, dlon=0.002)
    stale_lst = Listing(property_id=stale_prop.id, source="realtor",
                        source_listing_id="STALE", status="sold",
                        list_price=2_460_000, original_list_price=2_600_000,
                        list_date="2026-05-01", pending_date="2026-07-01",
                        sold_date="2026-07-10")
    market.add(stale_lst)
    market.flush()
    market.add(ListingEvent(listing_id=stale_lst.id, event_type="price_change",
                            old_value="2600000", new_value="2460000",
                            observed_at="2026-06-01T00:00:00+00:00"))
    _sale(market, stale_prop, SALE_DATE, 2_450_000, listing_id=stale_lst.id,
          sp_lp=round(2_450_000 / 2_600_000, 4))
    market.commit()

    report = backtest.run_backtest(market, n=1, today=TODAY)
    assert report.n_used >= 1
    assert report.mdape is not None and report.coverage is not None
    row = next(r for r in report.rows if r["address"] == "100 Subject St")
    assert row["as_of"] == AS_OF  # day before list date
    assert row["actual"] == 2_270_000 and row["cma_estimate"] > 0

    # pass B: the fresh subject never had an observed pending date, so only the
    # stale one is replayed — at the decision point (7 days before pending) with
    # a discounted value, and on the survival grid at every exposure point it
    # passed through once an area median existed (06-01 on: the 3x, 4x and 5x
    # points at 06-06, 06-18 and 06-30; 6x = 07-12 is past pending)
    assert report.midflight is not None and report.midflight["n"] == 1
    mid = report.midflight["rows"][0]
    assert mid["address"] == "200 Stale St"
    assert mid["as_of"] == "2026-06-24"
    assert mid["w"] > 0
    assert (mid["posture"], mid["confidence"]) == ("overpriced", "medium")
    assert mid["p_below_list"] > posture.OVER_P
    assert mid["had_cut"] is True and mid["relisted"] is False
    assert mid["list_asof"] == 2_460_000            # the cut price, not the original
    assert mid["below"] is True                     # sold 2.45M against a 2.46M ask
    assert mid["adjusted"] <= mid["unadjusted"]
    assert mid["ape_adjusted"] <= mid["ape_unadjusted"]  # sold near list: adjustment wins
    assert report.midflight["n_survival"] == 3
    curve = {c["ratio"]: c["n"] for c in report.midflight["curve"]}
    assert curve[3.0] == curve[4.0] == curve[5.0] == 1 and curve[6.0] == 0
    tiers = report.midflight["tiers"]
    assert tiers == {"overpriced/medium": {"n": 3, "below": 3, "below_share": 1.0,
                                           "median_sold_to_list": round(mid["sold_to_list"], 3)}}
    assert report.midflight["decision_tiers"]["overpriced/medium"]["n"] == 1
    assert report.midflight["calibration_ok"] is None   # three rows: nothing to judge
    assert report.midflight["fit"] is None

    path = backtest.write_report(report, today=TODAY)
    assert path.endswith("2026-07-14.md")
    text = (tmp_path / "backtests" / "2026-07-14.md").read_text(encoding="utf-8")
    assert "Tuning knobs" in text and "cma.m_factor" in text
    assert "posture calibration" in text and "posture.exposure_logit" in text
    assert "posture.w_ramp_start" in text


def test_withdrawal_share_counts_campaigns_to_pending_not_sale(market):
    """Per campaign, exposure to pending/delisting: a sold campaign's escrow is
    not market time, and a withdrawn first attempt that relisted and sold is a
    sale, not a withdrawal."""
    from hb.db.models import ListingGroup

    market.add(MarketMetric(geo_type="city", geo_id="Sunnyvale", period_start="2026-06-01",
                            period="monthly", metric="median_dom", value=10.0,
                            source="redfin"))

    def campaign(addr, episodes):
        prop = _prop(market, addr, 1600)
        group = ListingGroup(property_id=prop.id, episode_count=len(episodes))
        market.add(group)
        market.flush()
        for i, (list_date, pending_date, delist_date, status) in enumerate(episodes):
            market.add(Listing(property_id=prop.id, listing_group_id=group.id, source="realtor",
                               source_listing_id=f"{addr}-{i}", status=status, list_price=2_000_000,
                               original_list_price=2_000_000, list_date=list_date,
                               pending_date=pending_date, delist_date=delist_date,
                               sold_date="2026-08-30" if status == "sold" else None))

    # sold after 40 days to pending (escrow to 08-30 must not count) -> past 2x, a sale
    campaign("1 SOLD ST", [("2026-06-01", "2026-07-11", None, "sold")])
    # withdrawn after 40 days -> past 2x, withdrawn
    campaign("2 GONE ST", [("2026-06-01", None, "2026-07-11", "delisted")])
    # withdrawn after 30 days, relisted, pending 10 days later -> past 2x, a sale
    campaign("3 BACK ST", [("2026-05-01", None, "2026-05-31", "delisted"),
                           ("2026-06-10", "2026-06-20", None, "pending")])
    # pending in 8 days -> not past 2x, excluded
    campaign("4 HOT ST", [("2026-06-01", "2026-06-09", None, "pending")])
    # open-ended (no observed end) -> excluded
    campaign("5 OPEN ST", [("2026-05-01", None, None, "active")])
    market.commit()

    assert backtest._withdrawal_share(market) == {"n": 3, "share": round(1 / 3, 3), "ratio": 2.0}


def test_backtest_insufficient_data_note(market):
    # no qualifying sales -> gate unmet, honest note, no crash
    report = backtest.run_backtest(market, n=20, today=TODAY)
    assert report.passed is False
    assert "INSUFFICIENT PRIOR DATA" in report.note
