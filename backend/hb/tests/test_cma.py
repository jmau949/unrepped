import pytest
from sqlalchemy import func, select

from hb.db.models import AvmSnapshot, CmaComp, CmaRun, MarketMetric, PriceIndex, Property, Sale
from hb.engine import cma

AS_OF = "2026-07-14"
SUBJ_LAT, SUBJ_LON = 37.350, -122.030


@pytest.fixture
def market(session):
    """Flat index (factor≈1.0) + $/sqft so m = 0.45*1400 = 630."""
    for mo in ("2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"):
        session.add(PriceIndex(geo_type="zip", geo_id="94087", month=mo,
                               index_value=1.0, source="blend"))
    for ps in ("2026-05-01", "2026-06-01", "2026-07-01"):
        session.add(MarketMetric(geo_type="zip", geo_id="94087", period_start=ps,
                                 period="monthly", metric="median_ppsf", value=1400, source="redfin"))
    session.commit()
    return session


def _subject(session, **over):
    fields = dict(address_norm="100 SUBJECT ST", zip="94087", city="Sunnyvale",
                  lat=SUBJ_LAT, lon=SUBJ_LON, beds=3, baths=2.0, sqft=1600,
                  lot_sqft=5000, year_built=1975, condition_tag="dated",
                  property_type="single_family")
    fields.update(over)
    p = Property(**fields)
    session.add(p)
    session.flush()
    return p


def _comp(session, sqft, price, *, sale_date="2026-06-01", dlat=0.001, dlon=0.001,
          beds=3, baths=2.0, lot=5000, cond="dated", n=[0]):
    n[0] += 1
    p = Property(address_norm=f"{n[0]} COMP AVE", zip="94087", city="Sunnyvale",
                 lat=SUBJ_LAT + dlat, lon=SUBJ_LON + dlon, beds=beds, baths=baths,
                 sqft=sqft, lot_sqft=lot, year_built=1975, condition_tag=cond,
                 property_type="single_family")
    session.add(p)
    session.flush()
    s = Sale(property_id=p.id, sale_date=sale_date, sale_price=price,
             original_list_price=price, sp_lp=1.0, source="realtor_sold_scan")
    session.add(s)
    session.flush()
    return p, s


def test_end_to_end_estimate_and_persistence(market):
    subj = _subject(market)
    _comp(market, 1500, 2_150_000)
    _comp(market, 1700, 2_300_000, dlat=0.0012)
    _comp(market, 1600, 2_200_000, dlat=-0.001)
    _comp(market, 1550, 2_180_000, dlon=-0.001)
    _comp(market, 1650, 2_250_000, dlat=0.0015)
    _comp(market, 1620, 2_210_000, dlon=0.0012)
    market.commit()

    result = cma.run(market, subj.id, as_of=AS_OF)
    assert len(result.comps) == 6
    assert 2_100_000 < result.estimate < 2_300_000
    assert result.low <= result.estimate <= result.high
    assert result.confidence in ("low", "medium", "high")
    assert result.index_source.startswith("blend@")

    # persisted: one run, six comps, one own_cma snapshot dated as_of
    assert market.execute(select(func.count()).select_from(CmaRun)).scalar_one() == 1
    assert market.execute(select(func.count()).select_from(CmaComp)).scalar_one() == 6
    snap = market.execute(select(AvmSnapshot)).scalar_one()
    assert snap.source == "own_cma" and snap.as_of == AS_OF and snap.value == result.estimate


def test_rerun_creates_new_run_history_preserved(market):
    subj = _subject(market)
    for i in range(5):
        _comp(market, 1600 + (i - 2) * 40, 2_200_000 + (i - 2) * 20_000, dlat=0.001 * (i + 1))
    market.commit()

    r1 = cma.run(market, subj.id, as_of=AS_OF)
    r2 = cma.run(market, subj.id, as_of=AS_OF)
    assert market.execute(select(func.count()).select_from(CmaRun)).scalar_one() == 2
    assert r1.params["cma_run_id"] != r2.params["cma_run_id"]
    # only one own_cma snapshot per (property, source, as_of)
    assert market.execute(
        select(func.count()).select_from(AvmSnapshot).where(AvmSnapshot.source == "own_cma")
    ).scalar_one() == 1


def test_no_persist_path(market):
    subj = _subject(market)
    for i in range(5):
        _comp(market, 1600, 2_200_000, dlat=0.001 * (i + 1))
    market.commit()
    cma.run(market, subj.id, as_of=AS_OF, persist=False)
    assert market.execute(select(func.count()).select_from(CmaRun)).scalar_one() == 0
    assert market.execute(select(func.count()).select_from(AvmSnapshot)).scalar_one() == 0


def test_relaxation_when_starved(market):
    subj = _subject(market)
    # all comps ~0.8 mi away -> base 0.5mi finds none, must relax distance
    for i in range(5):
        _comp(market, 1600, 2_200_000, dlat=0.011 + 0.0005 * i, dlon=0.0)
    market.commit()
    result = cma.run(market, subj.id, as_of=AS_OF)
    assert "distance" in result.params["relaxations"]
    assert len(result.comps) == 5


def test_bracketing_swaps_in_smaller_comp(market):
    subj = _subject(market)  # 1600 sqft
    # six highest-scoring comps are all BIGGER than the subject...
    for i in range(6):
        _comp(market, 1700 + i * 10, 2_300_000, dlat=0.0005 * (i + 1))
    # ...one clearly smaller comp exists, slightly farther (lower score)
    small, _ = _comp(market, 1450, 2_050_000, dlat=0.004)
    market.commit()
    result = cma.run(market, subj.id, as_of=AS_OF)
    assert any(c.sqft < 1600 for c in result.comps), "smaller comp must be bracketed in"
    assert any(c.property_id == small.id for c in result.comps)


def test_confidence_low_when_thin(market):
    subj = _subject(market)
    _comp(market, 1600, 2_200_000)
    _comp(market, 1620, 2_210_000, dlat=0.0012)
    market.commit()
    result = cma.run(market, subj.id, as_of=AS_OF)
    assert result.confidence == "low"
    assert "n<3" in result.confidence_reasons


def test_no_coordinates_returns_low(market):
    subj = _subject(market, lat=None, lon=None)
    market.commit()
    result = cma.run(market, subj.id, as_of=AS_OF)
    assert result.confidence == "low"
    assert result.estimate is None
    assert "no coordinates" in result.confidence_reasons
