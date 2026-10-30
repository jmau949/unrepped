import pytest

from hb.engine import affordability


@pytest.fixture
def seeded(session):
    # Sunnyvale's 1.28% comes from the pinned sf_peninsula geography (conftest)
    return session


def test_worked_example_docs06(seeded):
    """docs/06 §8: P=$2.2M, $440k down (20%), 6.5%, Sunnyvale 1.28%, ins $250 -> PITI $13,721."""
    r = affordability.calc(
        seeded, price=2_200_000, city="Sunnyvale",
        down_payment=440_000, rate=6.5, insurance_monthly=250,
    )
    assert r.pi == pytest.approx(11_124, abs=1)
    assert r.tax == pytest.approx(2_347, abs=1)
    assert r.pmi == 0
    assert r.piti == pytest.approx(13_721, abs=1)
    assert r.closing_est == pytest.approx(33_000, abs=1)
    assert r.cash_needed == pytest.approx(473_000, abs=1)


def test_pmi_boundary_at_20pct(seeded):
    with_pmi = affordability.calc(seeded, 2_200_000, "Sunnyvale",
                                  down_payment=418_000, rate=6.5)  # 19%
    without = affordability.calc(seeded, 2_200_000, "Sunnyvale",
                                 down_payment=440_000, rate=6.5)   # 20%
    assert with_pmi.pmi > 0
    assert without.pmi == 0


def test_earthquake_toggle(seeded):
    base = affordability.calc(seeded, 2_200_000, "Sunnyvale", rate=6.5)
    eq = affordability.calc(seeded, 2_200_000, "Sunnyvale", rate=6.5,
                            include_earthquake=True)
    assert eq.piti - base.piti == affordability.optional_insurance_monthly()


def test_reserves_boundary(seeded):
    r = affordability.calc(seeded, 2_200_000, "Sunnyvale", down_payment=440_000,
                           rate=6.5, cash_available=473_000 + 6 * 13_721 + 100)
    assert r.reserves_ok is True
    r2 = affordability.calc(seeded, 2_200_000, "Sunnyvale", down_payment=440_000,
                            rate=6.5, cash_available=473_000 + 6 * 13_721 - 200)
    assert r2.reserves_ok is False


def test_unknown_city_uses_fallback_rate(seeded):
    r = affordability.calc(seeded, 2_000_000, "Nowhere", rate=6.5)
    assert r.tax_rate_used == affordability.DEFAULT_TAX_RATE
