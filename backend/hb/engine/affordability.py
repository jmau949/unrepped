"""Affordability math — docs/06-algorithms.md §8.

PITI with the geography's effective property-tax rate (city override, then
county), PMI below 20% down, the pack's optional excluded-peril rider
(earthquake in California), ~1.5% buyer-side closing estimate, the pack's
reassessment / supplemental-tax warning, a post-close reserves check, and the
lender's payment limit from income: housing payment + other monthly debts may
take at most DTI_MAX of gross monthly income.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb import packs
from hb.config import settings
from hb.db.models import RateSnapshot

PMI_ANNUAL_RATE = 0.006      # of loan, when down < 20%
CLOSING_PCT = 0.015          # buyer-side estimate (title, escrow, lender)
RESERVES_MONTHS = 6
DEFAULT_TAX_RATE = 0.0125    # fallback when city unknown
DTI_MAX = 0.43               # back-end debt-to-income ceiling (the qualified-mortgage line)


@dataclass
class AffordabilityResult:
    piti: int
    pi: int
    tax: int
    insurance: int
    pmi: int
    hoa: int
    earthquake: int
    closing_est: int
    cash_needed: int
    supplemental_tax_note: str
    reserves_after: int
    reserves_ok: bool
    rate_used: float
    tax_rate_used: float
    payment_limit: int | None  # max housing payment from income; None without income
    payment_ok: bool | None


def max_housing_payment(annual_income: int, monthly_debts: int) -> float | None:
    """The most a lender lets the housing payment (PITI + HOA) be: DTI_MAX of
    gross monthly income, less the other monthly debts. None when no income is
    entered — then the payment limit is simply not applied."""
    if annual_income <= 0:
        return None
    return max(DTI_MAX * annual_income / 12 - monthly_debts, 0.0)


def tax_rate_for_city(city: str | None) -> float:
    """The geography's rate for the city (city override, then county); the
    national fallback for a city outside the configured geography."""
    return settings.geo.tax_rate_for(city) or DEFAULT_TAX_RATE


def optional_insurance_monthly() -> int:
    """The pack's default monthly cost of the optional excluded-peril rider the
    profile toggle adds (earthquake insurance in California)."""
    return packs.current().affordability.earthquake_monthly_default


def latest_rate(session: Session) -> float | None:
    return session.execute(
        select(RateSnapshot.value)
        .where(RateSnapshot.series == "MORTGAGE30US")
        .order_by(RateSnapshot.date.desc())
        .limit(1)
    ).scalar_one_or_none()


def monthly_pi(loan: float, annual_rate_pct: float, years: int = 30) -> float:
    r = annual_rate_pct / 100 / 12
    n = years * 12
    if r == 0:
        return loan / n
    return loan * r / (1 - (1 + r) ** -n)


def calc(
    session: Session,
    price: int,
    city: str | None,
    down_payment: int = 0,
    rate: float | None = None,
    insurance_monthly: int = 250,
    hoa_monthly: int = 0,
    include_earthquake: bool = False,
    cash_available: int = 0,
    annual_income: int = 0,
    monthly_debts: int = 0,
) -> AffordabilityResult:
    """`down_payment` is a dollar amount (the profile stores dollars, not a
    percentage); PMI applies below 20% of price."""
    rate_used = rate if rate is not None else (latest_rate(session) or 6.5)
    tax_rate = tax_rate_for_city(city)

    down = min(max(down_payment, 0), price)
    loan = price - down
    pi = monthly_pi(loan, rate_used)
    tax = price * tax_rate / 12
    pmi = loan * PMI_ANNUAL_RATE / 12 if down < 0.20 * price else 0
    earthquake = optional_insurance_monthly() if include_earthquake else 0
    piti = pi + tax + insurance_monthly + pmi + hoa_monthly + earthquake

    closing = price * CLOSING_PCT
    cash_needed = down + closing
    reserves_after = cash_available - cash_needed
    reserves_ok = reserves_after >= RESERVES_MONTHS * piti

    limit = max_housing_payment(annual_income, monthly_debts)

    supplemental = packs.current().affordability.supplemental_tax_note.format(
        amount=round(price * tax_rate / 2))

    return AffordabilityResult(
        piti=round(piti),
        pi=round(pi),
        tax=round(tax),
        insurance=insurance_monthly,
        pmi=round(pmi),
        hoa=hoa_monthly,
        earthquake=earthquake,
        closing_est=round(closing),
        cash_needed=round(cash_needed),
        supplemental_tax_note=supplemental,
        reserves_after=round(reserves_after),
        reserves_ok=reserves_ok,
        rate_used=rate_used,
        tax_rate_used=tax_rate,
        payment_limit=round(limit) if limit is not None else None,
        # whole dollars, like everything shown: the solver's answer rounds to the dollar
        payment_ok=(round(piti) <= round(limit)) if limit is not None else None,
    )
