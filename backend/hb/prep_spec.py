"""Preparation checklist engine — the roll-up behind the Get Ready page (docs/15).

The content is pack data (`hb/packs/<key>/prep.py`, docs/packs/README.md); this
module is the pure functions over it. The product had a hole at the front: it
taught the market (docs/01), the walk-through (docs/13), the bid (docs/06) and
the escrow (docs/14) — but nothing about the weeks BEFORE the first open house,
which is where a buyer with no agent either builds a working setup or discovers,
mid-bidding-war, that they don't have one.

Same shape as `tour_spec` and `closing_spec`: pure functions, no DB and no
network. Two differences, both deliberate:

- **No dates.** There is no acceptance date to count from, and inventing a fake
  schedule would be worse than none. Ordering comes from `lead_time` instead — the
  tasks that take weeks of calendar time regardless of effort are flagged so they get
  started first, which is the single most useful thing this list can tell you.
- **One global checklist, not one per property.** State lives in the `settings` table
  under `prep_checklist` (docs/04), because you get pre-approved once, not once per
  house. That is why there is no new table for this.

`needed_by` splits the list into what must be true before you walk a house and what
must be true before you write an offer. In a market that runs offer dates with the
packet up front those are days apart, not weeks, so the second group is not "later",
it is "also now, but with one more week".
"""

from hb import packs
from hb.packs.types import Pack, PrepTask


def _pack(pack: Pack | None) -> Pack:
    return pack or packs.current()


def tasks_for(facts: dict | None = None, pack: Pack | None = None) -> list[PrepTask]:
    """Every task, in spec order. `facts` reserved for future pruning."""
    return list(_pack(pack).prep.tasks)


def _state(checklist: dict, key: str) -> dict:
    """Per-task state, tolerant of a bare truthy value from an older client."""
    raw = (checklist or {}).get(key)
    if isinstance(raw, dict):
        return raw
    if raw:
        return {"done_on": True}
    return {}


def spec_for(checklist: dict | None = None, pack: Pack | None = None) -> dict:
    """The checklist grouped by phase, with saved state attached.

    Mirrors closing_spec.spec_for — and takes the checklist for the same reason:
    the UI renders its checkboxes from this, so building it without state means
    every box comes back empty regardless of what was saved.
    """
    pack = _pack(pack)
    checklist = checklist or {}
    by_phase: dict[str, list[dict]] = {}
    for task in tasks_for(pack=pack):
        state = _state(checklist, task.key)
        by_phase.setdefault(task.phase, []).append({
            "key": task.key,
            "label": task.label,
            "phase": task.phase,
            "owner": task.owner,
            "why": task.why,
            "how": task.how,
            "needed_by": task.needed_by,
            "lead_time": task.lead_time,
            "done_on": state.get("done_on") or None,
            "done": bool(state.get("done_on")),
            "note": state.get("note") or None,
        })
    return {
        "phases": [
            {"key": p.key, "title": p.title, "blurb": p.blurb, "tasks": by_phase[p.key]}
            for p in pack.prep.phases if by_phase.get(p.key)
        ],
    }


def evaluate(checklist: dict | None = None, pack: Pack | None = None) -> dict:
    """Progress, plus what is not started and cannot be hurried later."""
    pack = _pack(pack)
    checklist = checklist or {}
    spec = spec_for(checklist, pack)
    rows = [t for p in spec["phases"] for t in p["tasks"]]
    done = [r for r in rows if r["done"]]
    open_rows = [r for r in rows if not r["done"]]

    return {
        "total": len(rows),
        "done": len(done),
        # The genuinely useful signal: unfinished work with real calendar lead time.
        "long_lead_open": [r for r in open_rows if r["lead_time"]],
        "before_tour_open": [r for r in open_rows if r["needed_by"] == "before you tour"],
        "before_offer_open": [r for r in open_rows if r["needed_by"] == "before you offer"],
        "next_action": open_rows[0] if open_rows else None,
        "phases": [
            {"key": p["key"], "title": p["title"], "total": len(p["tasks"]),
             "done": sum(1 for t in p["tasks"] if t["done"])}
            for p in spec["phases"]
        ],
    }
