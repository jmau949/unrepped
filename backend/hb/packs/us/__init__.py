"""The `us` base pack: state-neutral transaction content for any US geography
whose state has no pack of its own. State packs compose on top of it."""

from hb.packs.types import Closing, Pack, Prep, Tour
from hb.packs.us import closing, content, prep, sources, tour

PACK = Pack(
    key="us",
    label="United States (generic)",
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
    guide=None,
)
