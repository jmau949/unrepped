"""`GET /api/config` — the configured geography and pack, for the UI (docs/07 §Config).

Everything the frontend used to hard-code about the Peninsula lives here: the
city list, map centre, assessor links, contingency defaults, hazard and
school-rating labels, the tracker checklist. It is static for
the life of the process (`staleTime: Infinity` client-side) and separate from
the 60-second health poll on purpose.
"""

from fastapi import APIRouter

from hb import packs
from hb.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


def config_out() -> dict:
    geo = settings.geo
    pack = packs.current()
    c = pack.closing.contingency
    costs = pack.closing.costs
    return {
        "geography": {
            "name": geo.name,
            "state": geo.state,
            "timezone": geo.timezone,
            "cities": [
                {"name": city.name, "county": city.county, "zips": list(city.zips),
                 "flags": list(city.flags)}
                for city in geo.cities
            ],
            "zips": list(geo.zips),
            "counties": [
                {"name": county.name, "assessor_label": county.assessor_label,
                 "assessor_url": county.assessor_url,
                 "effective_tax_rate": county.effective_tax_rate}
                for county in geo.counties
            ],
            "map": {"center": list(geo.map.center), "zoom": geo.map.zoom},
            "price_band": {"min": geo.price_band.min, "max": geo.price_band.max},
        },
        "pack": {
            "key": pack.key,
            "label": pack.label,
            "contingency": {
                "investigation_days": c.investigation_days,
                "appraisal_days": c.appraisal_days,
                "loan_days": c.loan_days,
                "emd_business_days": c.emd_business_days,
                "label": c.label,
            },
            "costs": {"year": costs.year, "label": costs.label},
            "hazards": [{"key": h.key, "label": h.label, "tone": h.tone} for h in pack.hazards],
            "rating_sources": [{"key": r.key, "label": r.label, "blurb": r.blurb}
                               for r in pack.rating_sources],
            "tracker_checklist": [{"key": f.key, "label": f.label, "kind": f.kind}
                                  for f in pack.content.tracker_checklist],
            "affordability": {
                "earthquake_monthly_default": pack.affordability.earthquake_monthly_default,
                "optional_insurance_label": pack.affordability.optional_insurance_label,
            },
            "attorney_phrase": pack.content.attorney_phrase,
            "guide": {"available": pack.guide is not None},
        },
    }


@router.get("")
def get_config() -> dict:
    return config_out()
