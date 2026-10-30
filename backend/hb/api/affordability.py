"""Profile + affordability endpoints — docs/07-api-spec.md."""

from fastapi import APIRouter
from pydantic import BaseModel

from hb.db.engine import make_session
from hb.db.models import BuyerProfile, utcnow_iso
from hb.engine import affordability

router = APIRouter(prefix="/api", tags=["affordability"])


class Profile(BaseModel):
    cash_available: int
    down_payment: int  # dollars
    rate_assumption: float | None
    appraisal_gap_tolerance_pct: float
    insurance_monthly_est: int
    include_earthquake_ins: bool
    target_zips: list[str]
    annual_income: int  # gross, dollars per year; 0 = not entered
    monthly_debts: int  # other monthly debt payments (car, student loans, cards)


class CalcRequest(BaseModel):
    price: int
    city: str | None = None
    down_payment: int | None = None  # dollars
    rate: float | None = None
    hoa_monthly: int = 0
    include_earthquake_ins: bool | None = None


class CalcResponse(BaseModel):
    piti: int
    breakdown: dict[str, int]
    closing_est: int
    cash_needed: int
    supplemental_tax_note: str
    reserves_after: int
    reserves_ok: bool
    rate_used: float
    tax_rate_used: float
    payment_limit: int | None  # max housing payment from income; None without income
    payment_ok: bool | None


@router.get("/profile", response_model=Profile)
def get_profile() -> Profile:
    with make_session() as session:
        row = session.get(BuyerProfile, "default")
        return Profile.model_validate(row, from_attributes=True)


@router.put("/profile", response_model=Profile)
def put_profile(profile: Profile) -> Profile:
    with make_session() as session:
        row = session.get(BuyerProfile, "default")
        for field, value in profile.model_dump().items():
            setattr(row, field, value)
        row.updated_at = utcnow_iso()
        session.commit()
        return Profile.model_validate(row, from_attributes=True)


@router.post("/affordability/calc", response_model=CalcResponse)
def calc(req: CalcRequest) -> CalcResponse:
    with make_session() as session:
        profile = session.get(BuyerProfile, "default")
        result = affordability.calc(
            session,
            price=req.price,
            city=req.city,
            down_payment=(
                req.down_payment if req.down_payment is not None
                else profile.down_payment
            ),
            rate=req.rate if req.rate is not None else profile.rate_assumption,
            insurance_monthly=profile.insurance_monthly_est,
            hoa_monthly=req.hoa_monthly,
            include_earthquake=(
                req.include_earthquake_ins if req.include_earthquake_ins is not None
                else profile.include_earthquake_ins
            ),
            cash_available=profile.cash_available,
            annual_income=profile.annual_income,
            monthly_debts=profile.monthly_debts,
        )
    return CalcResponse(
        piti=result.piti,
        breakdown={
            "pi": result.pi, "tax": result.tax, "insurance": result.insurance,
            "pmi": result.pmi, "hoa": result.hoa, "earthquake": result.earthquake,
        },
        closing_est=result.closing_est,
        cash_needed=result.cash_needed,
        supplemental_tax_note=result.supplemental_tax_note,
        reserves_after=result.reserves_after,
        reserves_ok=result.reserves_ok,
        rate_used=result.rate_used,
        tax_rate_used=result.tax_rate_used,
        payment_limit=result.payment_limit,
        payment_ok=result.payment_ok,
    )
