"""Pack types — the records a state pack is made of (docs/packs/README.md).

A pack is data: the transaction content that differs by state — contingency
defaults, named forms, the closing / tour / prep prose, hazard layers, school
rating sources — bundled as frozen dataclasses. The engines
(`hb.closing_spec`, `hb.tour_spec`, `hb.prep_spec`, `hb.brief`) stay generic and
read whichever pack `hb.packs.current()` resolves for the configured geography.

Nothing here imports `hb.*` at runtime, so a pack module can be imported on its
own and tests can validate every pack without settings.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from hb.geography import Geography


# ----------------------------------------------------------------- closing


@dataclass(frozen=True)
class Contingency:
    """Default contingency clocks for a NEW deal, calendar days after acceptance
    (EMD in business days). Once a deal exists its own negotiated numbers govern."""

    investigation_days: int
    appraisal_days: int
    loan_days: int
    emd_business_days: int
    label: str  # shown next to the numbers, e.g. "C.A.R. RPA defaults"


@dataclass(frozen=True)
class Form:
    """A contract form, named in plain English. Referenced only — form text is
    never reproduced; the point is that "sign the BNA" is a useless instruction
    to the person this product is written for."""

    code: str
    name: str
    what: str


@dataclass(frozen=True)
class Due:
    """An anchor plus a calendar-day offset. Negative counts backward."""

    anchor: str
    offset: int = 0


@dataclass(frozen=True)
class ClosingTask:
    key: str
    label: str
    phase: str
    owner: str
    # `why` is the whole reason the spec exists: a bare label ("remove loan
    # contingency") carries none of the stakes for a first-time buyer.
    why: str
    how: str
    due: Due
    blocking: bool = False
    form: str = ""  # code into Closing.forms
    cost: str = ""  # key into Closing.costs
    applies_when: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Phase:
    key: str
    title: str
    blurb: str


@dataclass(frozen=True)
class CostBand:
    """A repair / settlement cost range, integer dollars (docs/04 money convention)."""

    key: str
    label: str
    low: int
    high: int


@dataclass(frozen=True)
class CostBook:
    """A labelled set of cost bands. `year` and `label` are what the UI prints
    next to any total ("2026 SF-Peninsula contractor ranges"); a geography can
    override both plus individual bands (`[costs]` in geography.toml)."""

    year: int
    label: str
    bands: dict[str, CostBand]

    def get(self, key: str | None) -> CostBand | None:
        return self.bands.get(key) if key else None


@dataclass(frozen=True)
class Closing:
    contingency: Contingency
    forms: dict[str, Form]
    phases: tuple[Phase, ...]
    tasks: tuple[ClosingTask, ...]
    costs: CostBook


# -------------------------------------------------------------------- tour


@dataclass(frozen=True)
class TourItem:
    key: str
    label: str
    type: str  # one of hb.tour_spec.ITEM_TYPES
    choices: list[str] = field(default_factory=list)
    hint: str = ""
    # The exact shot to take — the shot-list IS the point (docs/13 §9).
    photo: str = ""
    applies_when: dict = field(default_factory=dict)
    flag_when: dict = field(default_factory=dict)
    cost: str = ""  # key into Tour.cost_bands


@dataclass(frozen=True)
class TourSection:
    key: str
    title: str
    blurb: str
    items: list[TourItem]


@dataclass(frozen=True)
class AgeNote:
    """A context note shown for homes built before `year_before`; `text` may use
    `{year}` for the home's actual year built."""

    year_before: int
    text: str


@dataclass(frozen=True)
class Tour:
    sections: tuple[TourSection, ...]
    agent_questions: tuple[str, ...]
    cost_bands: CostBook
    age_notes: tuple[AgeNote, ...]


# -------------------------------------------------------------------- prep


@dataclass(frozen=True)
class PrepTask:
    key: str
    label: str
    phase: str
    why: str
    how: str
    owner: str = "you"
    needed_by: str = "before you tour"
    # Calendar time this takes no matter how motivated you are — the whole
    # ordering logic of the Get Ready page.
    lead_time: str = ""
    applies_when: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Prep:
    phases: tuple[Phase, ...]
    tasks: tuple[PrepTask, ...]
    owners: tuple[str, ...]
    needed_by: tuple[str, ...]


# ----------------------------------------------------------------- content


@dataclass(frozen=True)
class ChecklistField:
    """One field of the Tracker's per-listing disclosure checklist. Keys are
    the storage contract for `tracked_listings.disclosure_checklist`."""

    key: str
    label: str
    kind: str  # "bool" | "number" | "text"


@dataclass(frozen=True)
class Affordability:
    earthquake_monthly_default: int  # the optional-peril rider the profile toggle adds
    optional_insurance_label: str  # label of that toggle on /affordability
    supplemental_tax_note: str  # `{amount}` = the estimated first-year catch-up bill
    # `hb setup` estimates each county's effective tax rate from what current
    # owners pay (Census ACS). Where the assessment resets to the price at sale
    # and is capped afterwards, owners pay far less than a buyer will, so the
    # pack names the buyer's rate instead, with the one-line reason shown.
    purchase_tax_rate: float | None = None
    purchase_tax_note: str = ""


@dataclass(frozen=True)
class Content:
    disclosure_packet: tuple[str, ...]  # what the AI brief tells the reader is attached
    brief_tax_note: str  # the one-line post-close tax warning in the brief
    attorney_phrase: str  # "a California real estate attorney"
    tracker_checklist: tuple[ChecklistField, ...]


# --------------------------------------------------------------- registries


@dataclass(frozen=True)
class HazardLayer:
    """One hazard polygon layer: where to fetch it (an ArcGIS REST query
    endpoint), how to scope the query to the geography, and how to turn a
    feature's properties into the stored `zone_value`."""

    key: str
    label: str
    tone: str  # UI colour family: sky | orange | amber | purple | rose | slate
    url: str
    query: Callable[[Geography], dict]
    zone_value: Callable[[dict], str]


@dataclass(frozen=True)
class RatingSource:
    """A school-rating source. The first one listed is the primary: it sorts
    first on the listing page and in the brief."""

    key: str
    label: str
    blurb: str


@dataclass(frozen=True)
class Guide:
    """A closing playbook served from a markdown doc (`GET /api/guide/closing`).

    `section_ids` maps the doc's `## N.` section numbers to stable ids the UI
    deep-links to; `exclude` hides sections written for developers;
    `phase_map` lists, per closing phase, the guide sections worth reading.
    """

    doc: str  # repo-relative path
    section_ids: dict[str, str]
    exclude: frozenset[str]
    phase_map: dict[str, tuple[tuple[str, str], ...]]  # phase -> ((id, label), ...)


@dataclass(frozen=True)
class Pack:
    key: str
    label: str
    closing: Closing
    tour: Tour
    prep: Prep
    content: Content
    affordability: Affordability
    hazards: tuple[HazardLayer, ...]
    rating_sources: tuple[RatingSource, ...]
    guide: Guide | None = None
