"""The `ca` pack: California transaction content, composed on the `us` base.
Selected by `pack = "ca"` (or `state = "CA"`) in geography.toml."""

from hb.packs.ca import closing, content, prep, sources, tour
from hb.packs.types import Closing, Guide, Pack, Prep, Tour

# docs/14 served as the in-app closing guide. `section_ids` are the ids the
# Closing page deep-links to; §15 is written for developers and is hidden.
GUIDE = Guide(
    doc="docs/14-closing-playbook.md",
    section_ids={
        "1": "lost", "2": "forms", "3": "lock_down", "4": "clocks", "5": "disclosures",
        "6": "inspections", "7": "city_rules", "8": "loan", "9": "insurance",
        "10": "repairs", "11": "removal", "12": "final_week", "13": "cash",
        "14": "post_close", "15": "app_model",
    },
    exclude=frozenset({"app_model"}),
    phase_map={
        "lock_down": (("lock_down", "Days 0–3"), ("clocks", "The contingency clock")),
        "disclosures": (("disclosures", "The disclosure packet"),),
        "inspections": (("inspections", "Inspections"),
                        ("city_rules", "City point-of-sale rules")),
        "loan": (("loan", "Loan, appraisal, and the gap"),),
        "title_insurance": (("insurance", "Insurance"), ("disclosures", "Reading the prelim")),
        "negotiate": (("repairs", "Repairs and credits"), ("removal", "Removing contingencies")),
        "final_week": (("final_week", "The final week"), ("cash", "Cash to close")),
        "post_close": (("post_close", "Week one after close"),),
    },
)

PACK = Pack(
    key="ca",
    label="California",
    closing=Closing(
        contingency=closing.CONTINGENCY,
        forms=closing.FORMS,
        phases=closing.PHASES,
        tasks=closing.TASKS,
        costs=closing.COSTS,
    ),
    tour=Tour(
        sections=tour.SECTIONS,
        agent_questions=tour.AGENT_QUESTIONS,
        cost_bands=tour.COST_BANDS,
        age_notes=tour.AGE_NOTES,
    ),
    prep=Prep(
        phases=prep.PHASES,
        tasks=prep.TASKS,
        owners=prep.OWNERS,
        needed_by=prep.NEEDED_BY,
    ),
    content=content.CONTENT,
    affordability=content.AFFORDABILITY,
    hazards=sources.HAZARDS,
    rating_sources=sources.RATING_SOURCES,
    guide=GUIDE,
)
