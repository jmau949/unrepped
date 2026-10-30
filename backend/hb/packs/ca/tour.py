"""Tour checklist content for the `ca` pack — docs/13 in data form: the base
checklist plus the seismic items (retrofit hardware, strapped water heater),
California hints, and the age notes that assume an unbolted pre-1980 foundation.
"""

from hb.packs import compose
from hb.packs.types import AgeNote, CostBand, CostBook
from hb.packs.types import TourItem as I
from hb.packs.us import tour as us
from hb.packs.us.tour import YES_NO

COST_BANDS = CostBook(
    year=us.COST_BANDS.year,
    label="California contractor ranges (rough)",
    bands={
        **us.COST_BANDS.bands,
        "foundation_bolting": CostBand("foundation_bolting",
                                       "Foundation bolting + cripple wall", 5_000, 15_000),
    },
)

_SECTIONS = compose.override_items(us.SECTIONS, {
    "noise_train": {
        "hint": "Commuter and freight corridors (Caltrain, Metrolink, Amtrak, BNSF/UP) sound "
                "the horn at every grade crossing.",
    },
    "grading_slopes_away": {
        "hint": "Clay soils — drainage is the root cause behind most foundation findings.",
    },
    "sewer_lateral_cert": {
        "label": "Sewer lateral compliance certificate",
        "hint": "Many Bay Area and coastal cities require one at sale. Clay lateral plus tree "
                "roots is a five-figure line item — ask for the video.",
    },
})
_SECTIONS = compose.add_items(
    _SECTIONS, "exterior",
    I("retrofit_visible", "Seismic retrofit visible", "choice",
      choices=["anchor bolts + shear plywood visible", "none visible", "unsure"],
      hint="Pre-1980 raised foundations are often unbolted. Affects "
           "earthquake insurance as well as safety.",
      photo="Through a crawlspace vent with the flash on",
      applies_when={"year_built_before": 1980},
      flag_when={"in": ["none visible"]}, cost="foundation_bolting"),
    after="foundation_cracks",
)
_SECTIONS = compose.add_items(
    _SECTIONS, "systems",
    I("water_heater_strapped", "Double-strapped", "choice", choices=YES_NO,
      hint="Two straps is the California seismic requirement.",
      flag_when={"in": ["no"]}),
    after="water_heater_year",
)
SECTIONS = tuple(_SECTIONS)

AGENT_QUESTIONS: tuple[str, ...] = tuple(
    "Which disclosures are available now — TDS/SPQ, pest, NHD, home inspection, "
    "roof cert, sewer lateral video, permit history?"
    if q.startswith("Which disclosures are available now") else q
    for q in us.AGENT_QUESTIONS
)

AGE_NOTES: tuple[AgeNote, ...] = (
    AgeNote(1980, "Built {year}. Assume the foundation is unbolted and the cripple wall "
                  "unbraced until you see hardware — pre-1980 is the cutoff."),
    AgeNote(1975, "Built {year}. Clay sewer lateral is likely; ask for a video inspection "
                  "and a compliance certificate."),
    AgeNote(1970, "Built {year}. Check for galvanized supply piping under every sink, and "
                  "for cloth or knob-and-tube wiring in the garage."),
)
