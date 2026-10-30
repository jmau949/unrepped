"""Tour checklist engine — pruning, flagging and the cost roll-up behind docs/13.

The checklist content (sections, items, agent questions, cost bands, age notes)
is pack data (`hb/packs/<key>/tour.py`, docs/packs/README.md); this module is
the pure functions over it. One definition, three renderers: the in-app tour
panel (docs/08 §3 item 6c), the Field page (frontend /field, docs/08 §11), and
the AI deep-dive brief (hb/brief.py). Nothing here touches the DB or the
network, so `/field-data` can seed the phone with a spec that raises the same
flags with no round trip.

Two ideas carry the weight:

- `flag_when` turns an observation into a **red flag** deterministically. The
  buyer is a first-timer; "Federal Pacific" has to mean something without them
  knowing why. See the playbook §4 for the reasoning behind each condition.
- A flagged item may name a `cost` band, so observations roll up into a
  deferred-maintenance range and a condition-adjusted value (docs/06 has the
  valuation; this is the deduction). Bands are deliberately wide, labelled with
  their year and region, and shown as estimates everywhere they surface.

Cost bands are keyed and **deduped on roll-up**: `panel_brand` and `panel_fuses`
both point at `panel_replace`, and a house with both does not pay twice.
"""

from datetime import datetime

from hb import packs
from hb.packs.types import CostBook, Pack, TourItem

# Item value types. `rating` is 1-5; `choice` uses `TourItem.choices`.
ITEM_TYPES = ("bool", "number", "text", "choice", "rating")


def _pack(pack: Pack | None) -> Pack:
    return pack or packs.current()


def all_items(pack: Pack | None = None) -> list[TourItem]:
    """Every checklist item, in spec order."""
    return [i for s in _pack(pack).tour.sections for i in s.items]


def items_by_key(pack: Pack | None = None) -> dict[str, TourItem]:
    return {i.key: i for i in all_items(pack)}


def _applies(item: TourItem, facts: dict) -> bool:
    """Unknown facts keep the item — if we don't know the year, still ask."""
    before = item.applies_when.get("year_built_before")
    if before is not None:
        year_built = facts.get("year_built")
        if year_built is not None and year_built >= before:
            return False
    return True


def items_for(facts: dict, pack: Pack | None = None) -> list[TourItem]:
    """The checklist items that apply to one home, in spec order."""
    return [i for i in all_items(pack) if _applies(i, facts)]


def spec_for(facts: dict, pack: Pack | None = None) -> dict:
    """Prune the checklist to one home and attach what the app already knows.

    `facts` is the property context the caller has on hand: year_built, sqft,
    assessor_sqft, sqft_mismatch, hazards. Everything is optional.
    """
    pack = _pack(pack)
    costs = pack.tour.cost_bands
    sections = []
    for section in pack.tour.sections:
        live = [i for i in section.items if _applies(i, facts)]
        if not live:
            continue
        sections.append({
            "key": section.key,
            "title": section.title,
            "blurb": section.blurb,
            "items": [
                {
                    "key": i.key, "label": i.label, "type": i.type,
                    "choices": i.choices, "hint": i.hint, "photo": i.photo,
                    # `flag_when` ships to the client so the tour panel and the
                    # Field page raise the same red flags with no round trip. The
                    # rules stay data; only a ~15-line interpreter is mirrored in
                    # JS (frontend/src/lib/tourFlags.ts).
                    "flag_when": i.flag_when,
                    "cost": i.cost,
                    "cost_band": _band_out(i.cost, costs),
                }
                for i in live
            ],
        })
    return {
        "sections": sections,
        "agent_questions": list(pack.tour.agent_questions),
        "context_notes": _context_notes(facts, pack),
        "costs": {"year": costs.year, "label": costs.label},
        "photo_shot_list": [
            {"key": i.key, "label": i.label, "shot": i.photo}
            for section in pack.tour.sections for i in section.items
            if i.photo and _applies(i, facts)
        ],
    }


def _band_out(key: str, costs: CostBook) -> dict | None:
    band = costs.get(key)
    return {"key": band.key, "label": band.label, "low": band.low, "high": band.high} \
        if band else None


def _context_notes(facts: dict, pack: Pack) -> list[str]:
    """What this specific home means for what you should look at."""
    notes: list[str] = []
    year_built = facts.get("year_built")
    if year_built:
        for note in pack.tour.age_notes:
            if year_built < note.year_before:
                notes.append(note.text.format(year=year_built))
    if facts.get("sqft_mismatch"):
        notes.append(
            "Listed square footage exceeds the assessor's by more than 15%. Ask what was "
            "added and whether it was permitted — this affects appraisal and insurance."
        )
    labels = {layer.key: layer.label for layer in pack.hazards}
    for hazard in facts.get("hazards") or []:
        notes.append(f"Hazard flag on file: {labels.get(hazard, hazard)}. "
                     "Ask how it affects insurance cost.")
    return notes


def _is_flagged(item: TourItem, value, year: int) -> bool:
    if not item.flag_when or value is None or value == "":
        return False
    cond = item.flag_when
    if "in" in cond:
        return value in cond["in"]
    if "is_true" in cond:
        return bool(value) is cond["is_true"]
    if "older_than" in cond:
        try:
            observed = int(value)
        except (TypeError, ValueError):
            return False
        return observed > 1800 and (year - observed) >= cond["older_than"]
    if "gte" in cond:
        try:
            return float(value) >= cond["gte"]
        except (TypeError, ValueError):
            return False
    return False


def evaluate(checklist: dict, *, items: list[TourItem] | None = None,
             year: int | None = None, pack: Pack | None = None) -> dict:
    """Roll a filled checklist up into flags, costs, and what is still unknown.

    Deterministic and pure — the API, the offline kit and the brief all call this
    so none of them reimplement the rules. Cost bands are deduped by key, so a
    house with both a Federal Pacific panel and fuses pays for one panel.
    """
    pack = _pack(pack)
    costs = pack.tour.cost_bands
    checklist = checklist or {}
    live = items if items is not None else all_items(pack)
    year = year or datetime.now().year

    flags: list[dict] = []
    bands: dict[str, object] = {}
    unanswered: list[dict] = []

    section_of = {i.key: s.key for s in pack.tour.sections for i in s.items}

    for item in live:
        value = checklist.get(item.key)
        # A bool left unchecked means "not observed", not "observed false" — only
        # the choice items carry an explicit "no".
        if value is None or value == "" or (item.type == "bool" and value is False):
            if item.type != "text":
                unanswered.append({"key": item.key, "label": item.label,
                                   "section": section_of.get(item.key, "")})
            continue
        if _is_flagged(item, value, year):
            band = costs.get(item.cost)
            flags.append({
                "key": item.key, "label": item.label, "value": value,
                "section": section_of.get(item.key, ""),
                "cost": band.key if band else None,
            })
            if band:
                bands[band.key] = band

    ordered = sorted(bands.values(), key=lambda b: b.low, reverse=True)
    return {
        "flags": flags,
        "costs": {
            "year": costs.year,
            "label": costs.label,
            "low": sum(b.low for b in ordered),
            "high": sum(b.high for b in ordered),
            "items": [{"key": b.key, "label": b.label, "low": b.low, "high": b.high}
                      for b in ordered],
        },
        "unanswered": unanswered,
    }
