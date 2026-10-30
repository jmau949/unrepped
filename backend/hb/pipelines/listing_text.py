"""listing_text — structured signals parsed out of the listing description.

HomeHarvest returns the public remarks as `text` (utils.ordered_properties), and
the scan used to discard them. Two fields the product depends on are sitting in
that prose and nowhere else in any free source:

1. **condition** (`properties.condition_tag`) — the CMA's condition adjustment
   (06 §4.2: renovated↔dated ±7%, fixer −15%) and the `f_cond` similarity factor
   are no-ops while every tag is NULL, which is the single largest contributor to
   CMA-only error. Agents describe condition in the remarks because it is what
   they are selling.
2. **offer date** (`listings.offer_due_at`) — the Bay Area process fact (01 §4):
   offers are reviewed on a published date ~7-14 days after listing. It drives a
   posture signal (06 §5.6), the `offer_date_soon` alert, and whether a
   preemptive offer is even possible.

**Both parsers are deliberately conservative — silence beats a wrong answer.**
A mis-tagged condition moves a comp by ±7% and a wrong deadline is worse than no
deadline, so ambiguous evidence returns None rather than a guess: condition
requires a strict winner across keyword classes (a tie is "unknown"), and an
offer date must parse cleanly AND land in a plausible window around the list
date. Every inferred tag records the phrases that triggered it, so the call is
auditable in the UI and overridable by hand.
"""

import re
from datetime import date, timedelta

# Notes written by this module are prefixed so a hand-entered note is never
# clobbered — provenance without a schema change (04 §properties).
AUTO_PREFIX = "auto: "


# --- condition ---------------------------------------------------------------

_CONDITION_PATTERNS: dict[str, tuple[str, ...]] = {
    # Verifiable claims ONLY. Measured against live peninsula inventory, the
    # promotional vocabulary every listing uses — "beautifully updated",
    # "tastefully updated", "updated kitchen", "designer", "modernized" — tagged
    # 57% of all homes renovated. Those are copywriter filler, not evidence, and
    # a +7% condition adjustment on half the comp pool is worse than no tag.
    "renovated": (
        r"remodel(?:ed|led)", r"renovat(?:ed|ion)", r"rebuilt",
        r"new construction", r"newly (?:built|constructed)",
        r"turn[\s-]?key", r"gut(?:ted)?[\s-]?renovat",
        r"(?:down to the |to the )?studs?[\s-]?out", r"down to the studs",
        r"permitted addition",
        r"(?:brand )?new kitchen",
        r"new (?:roof|hvac|furnace|electrical|plumbing|windows|foundation)",
    ),
    "fixer": (
        r"fixer(?:[\s-]?upper)?", r"contractor'?s? special", r"handyman'?s? special",
        r"needs? (?:work|tlc|updating|renovation|repair)", r"\btlc\b",
        r"deferred maintenance", r"(?:sold )?(?:strictly )?as[\s-]is(?: condition)?",
        r"bring your (?:contractor|imagination|vision|architect)",
        r"opportunity to (?:remodel|rebuild|renovate)", r"sweat equity",
        r"value[\s-]add", r"uninhabitable", r"not habitable", r"tear[\s-]?down",
    ),
    "dated": (
        r"original condition", r"original owner", r"same (?:family|owner)",
        r"(?:long[\s-]?time|longtime) owner", r"estate sale", r"trust sale",
        r"first time on (?:the )?market in \d+", r"cosmetic (?:updating|updates|work)",
        r"needs? cosmetic", r"ready for your (?:personal )?touch",
        r"your personal touches", r"well[\s-]maintained but dated", r"\bdated\b",
    ),
}

# Minimum merged signals before a class may win. Asymmetric on purpose: no agent
# writes "fixer" or "estate sale" casually, but "remodeled" shows up in prose
# about a kitchen redone in 1998, so the renovated claim has to clear a higher
# bar to outvote the marketing noise floor.
_MIN_SIGNALS = {"renovated": 2, "fixer": 1, "dated": 1}

_CONDITION_RE = {
    tag: [re.compile(p, re.I) for p in patterns]
    for tag, patterns in _CONDITION_PATTERNS.items()
}


def classify_condition(text: str | None) -> tuple[str | None, str | None]:
    """Remarks -> (condition_tag, evidence) or (None, None).

    Scores each class by how many distinct phrases matched and requires a strict
    winner: "remodeled kitchen, bathrooms need work" scores 1-1 and stays
    unknown, because a coin-flip tag is worse for the CMA than no tag at all.
    """
    if not text:
        return None, None

    hits: dict[str, list[str]] = {}
    for tag, patterns in _CONDITION_RE.items():
        spans: list[tuple[int, int, str]] = []
        for pattern in patterns:
            for found in pattern.finditer(text):
                spans.append((found.start(), found.end(), found.group(0).strip().lower()))
        # Patterns deliberately overlap ("remodeled" and "remodeled kitchen"), so
        # score merged spans, not raw matches — otherwise one phrase counts twice
        # and outvotes a genuinely competing signal.
        spans.sort()
        merged: list[tuple[int, int, str]] = []
        for start, end, phrase in spans:
            if merged and start < merged[-1][1]:
                prev_start, prev_end, prev_phrase = merged[-1]
                keep = prev_phrase if len(prev_phrase) >= len(phrase) else phrase
                merged[-1] = (prev_start, max(prev_end, end), keep)
            else:
                merged.append((start, end, phrase))
        # Count DISTINCT claims: prose that says "remodeled" twice makes one
        # claim, not two, and must not clear the renovated threshold on repetition.
        distinct = sorted({phrase for _, _, phrase in merged})
        if distinct:
            hits[tag] = distinct

    if not hits:
        return None, None
    ranked = sorted(hits.items(), key=lambda kv: len(kv[1]), reverse=True)
    if len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1]):
        return None, None  # tie -> unknown
    tag, evidence = ranked[0]
    if len(evidence) < _MIN_SIGNALS[tag]:
        return None, None
    return tag, ", ".join(evidence[:4])


# --- offer date --------------------------------------------------------------

_NO_OFFER_DATE = re.compile(
    r"no\s+(?:set\s+|specific\s+|formal\s+)?offer\s+date"
    r"|offers?\s+as\s+they\s+(?:come|are\s+received)"
    r"|reviewing\s+offers?\s+as\s+(?:they\s+come|received)",
    re.I,
)

_TRIGGER = re.compile(
    r"offers?\s+(?:are\s+|will\s+be\s+)?(?:due|deadline|reviewed?)"
    r"|offer\s+(?:date|deadline)"
    r"|(?:submit|present)\s+(?:all\s+)?offers?\s+by"
    r"|reviewing\s+offers?\s+on",
    re.I,
)

_NUMERIC = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\b")

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

_MONTHNAME = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?",
    re.I,
)

# how far either side of the list date a parsed offer date may plausibly land
_WINDOW_BEFORE = timedelta(days=7)
_WINDOW_AFTER = timedelta(days=120)


def _anchor(month: int, day: int, year: int | None, list_dt: date) -> date | None:
    if year is not None:
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    # no year in the text: take the list year, rolling forward for a listing that
    # straddles New Year (listed in December, offers reviewed in January)
    for candidate_year in (list_dt.year, list_dt.year + 1):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if candidate >= list_dt - _WINDOW_BEFORE:
            return candidate
    return None


def parse_offer_due(text: str | None, list_date: str | None) -> str | None:
    """Remarks + list date -> ISO offer date, or None.

    `list_date` is required: it anchors a bare "7/21" to a year and bounds the
    result. Without an anchor there is no safe way to tell an offer deadline from
    any other date in the prose, so the parser declines.
    """
    if not text or not list_date:
        return None
    try:
        list_dt = date.fromisoformat(str(list_date)[:10])
    except ValueError:
        return None
    if _NO_OFFER_DATE.search(text):
        return None

    trigger = _TRIGGER.search(text)
    if not trigger:
        return None
    tail = text[trigger.end(): trigger.end() + 90]

    parsed: date | None = None
    numeric = _NUMERIC.search(tail)
    if numeric:
        month, day, year = numeric.groups()
        parsed = _anchor(int(month), int(day), int(year) if year else None, list_dt)
    if parsed is None:
        named = _MONTHNAME.search(tail)
        if named:
            name, day, year = named.groups()
            parsed = _anchor(_MONTHS[name.lower()[:3]], int(day),
                             int(year) if year else None, list_dt)
    if parsed is None:
        return None
    if not (list_dt - _WINDOW_BEFORE <= parsed <= list_dt + _WINDOW_AFTER):
        return None  # parsed something, but not plausibly this listing's deadline
    return parsed.isoformat()


# --- application -------------------------------------------------------------

def apply_condition(prop, text: str | None) -> bool:
    """Write an inferred condition tag onto a property unless a human owns it.

    Hands off when the tag was set by hand — that is any existing tag whose note
    does not carry AUTO_PREFIX (including a tag with no note at all). Returns
    True if the property changed.
    """
    tag, evidence = classify_condition(text)
    if tag is None:
        return False
    notes = prop.condition_notes or ""
    if prop.condition_tag and not notes.startswith(AUTO_PREFIX):
        return False  # hand-entered: never overwrite
    note = f"{AUTO_PREFIX}{evidence}"
    if prop.condition_tag == tag and prop.condition_notes == note:
        return False
    prop.condition_tag = tag
    prop.condition_notes = note
    return True
