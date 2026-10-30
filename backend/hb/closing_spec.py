"""Closing task engine — the date math and pruning behind the closing tracker.

The content (tasks, phases, forms, cost bands, contingency defaults) is pack
data (`hb/packs/<key>/closing.py`, docs/packs/README.md); this module is the
pure functions that turn it into dated rows for one deal. One definition, two
renderers: the closing tracker (`/closing`, docs/08 §12) and the
`deal-deadlines` alert job (docs/05, docs/09). Nothing here touches the DB or
the network, so the same dates come out wherever they are computed.

Three ideas carry the weight:

- **Every date is derived, never stored.** A deal holds five numbers from the contract
  (acceptance, price, COE, and the three contingency day-counts); every task date is
  arithmetic on those. Correcting `accepted_on` re-dates the whole transaction.
- **A waived contingency erases its anchor**, and with it every task that hangs off
  that anchor. `loan_days = None` does not merely grey out the loan-removal task, it
  removes the appraisal-gap decision, the clear-to-close gate, and the rest of the
  chain — because none of them are protecting anything any more.
- **`blocking` means the deal does not proceed without it**, not "important". Missing a
  blocking task is how a first-time buyer loses an earnest-money deposit, so it is the
  one flag the UI is allowed to shout about.

`applies_when` prunes the list to one home the way `tour_spec` does — off `year_built`
(lead paint, foundation, chimney), off a city flag from geography.toml (`city_flag`,
e.g. the point-of-sale sewer ordinances the `ca` pack keys on `sewer_lateral_pos`),
and off whether the purchase is financed. Unknown facts keep the task: if we don't
know the year, still ask.

Cost bands are keyed and **deduped on roll-up**, exactly as in the tour spec, and
are labelled as estimates everywhere they surface.

**Not legal advice, and not authority on your deadlines.** These dates are arithmetic on
numbers the user typed in off their own contract; the contract governs.
"""

from datetime import date, timedelta

from hb import packs
from hb.config import settings
from hb.packs.types import ClosingTask, CostBook, Pack

# Who actually performs the task. The buyer has no agent, so `you` is most of them —
# which is the point the playbook opens with.
OWNERS = ("you", "lender", "escrow", "title", "seller", "inspector", "insurer", "attorney")

# Every task hangs off one of these. `acceptance` and `coe` come straight off the deal;
# `emd` is business days out; the three removals are calendar days and are `None`
# when that contingency was waived.
ANCHORS = (
    "acceptance",
    "emd",
    "investigation_removal",
    "appraisal_removal",
    "loan_removal",
    "coe",
)


def _pack(pack: Pack | None) -> Pack:
    return pack or packs.current()


# --------------------------------------------------------------------- date math


def parse_date(value) -> date | None:
    """Accept a date, an ISO YYYY-MM-DD string, or nothing."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def add_business_days(start: date, days: int) -> date:
    """Weekdays only.

    Deliberately ignores federal and state holidays: a holiday inside the window
    pushes a real EMD deadline out by a day, so treat this as the EARLIEST the
    deposit could be due and confirm the date against the contract.
    """
    out = start
    remaining = days
    while remaining > 0:
        out += timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


def anchors(deal: dict, pack: Pack | None = None) -> dict[str, date | None]:
    """Resolve the six anchors from a deal's five contract numbers.

    A contingency whose day-count is None was WAIVED — its anchor resolves to None,
    which prunes it and every task hanging off it out of the schedule entirely.
    """
    accepted = parse_date(deal.get("accepted_on"))
    coe = parse_date(deal.get("close_of_escrow_on"))
    emd_days = deal.get("emd_business_days")
    if emd_days is None:
        emd_days = _pack(pack).closing.contingency.emd_business_days

    def removal(key: str) -> date | None:
        days = deal.get(key)
        if accepted is None or days is None:
            return None
        return accepted + timedelta(days=int(days))

    return {
        "acceptance": accepted,
        "emd": add_business_days(accepted, int(emd_days)) if accepted else None,
        "investigation_removal": removal("investigation_days"),
        "appraisal_removal": removal("appraisal_days"),
        "loan_removal": removal("loan_days"),
        "coe": coe,
    }


# ------------------------------------------------------------------- pruning


def _applies(task: ClosingTask, facts: dict, deal: dict) -> bool:
    """Unknown facts keep the task — same rule as tour_spec: if we don't know, still ask."""
    cond = task.applies_when
    if not cond:
        return True

    before = cond.get("year_built_before")
    if before is not None:
        year_built = facts.get("year_built")
        if year_built is not None and int(year_built) >= before:
            return False

    flag = cond.get("city_flag")
    if flag is not None:
        city = (facts.get("city") or "").strip().casefold()
        # An unknown city keeps the task — a missed point-of-sale ordinance is a
        # five-figure surprise, so this one fails loud rather than quiet.
        flagged = {c.casefold() for c in settings.geo.cities_with_flag(flag)}
        if city and city not in flagged:
            return False

    if cond.get("financed") is True:
        # Absent means financed: the default purchase in this product carries a loan.
        if deal.get("financed") is False:
            return False

    for extra in ("hoa", "pool"):
        if cond.get(extra) is True and facts.get(extra) is not True:
            return False

    return True


def tasks_for(deal: dict, facts: dict | None = None,
              pack: Pack | None = None) -> list[ClosingTask]:
    """The tasks that apply to one deal, in spec order, with waived chains removed."""
    pack = _pack(pack)
    facts = facts or {}
    live = anchors(deal, pack)
    return [
        t for t in pack.closing.tasks
        if _applies(t, facts, deal) and live.get(t.due.anchor) is not None
    ]


def _band_out(key: str, costs: CostBook) -> dict | None:
    band = costs.get(key)
    return {"key": band.key, "label": band.label, "low": band.low, "high": band.high} \
        if band else None


def _state(checklist: dict, key: str) -> dict:
    """Per-task state, tolerant of a bare truthy value from an older client."""
    raw = (checklist or {}).get(key)
    if isinstance(raw, dict):
        return raw
    if raw:
        return {"done_on": True}
    return {}


def schedule(deal: dict, facts: dict | None = None, checklist: dict | None = None,
             pack: Pack | None = None) -> list[dict]:
    """Concrete dated tasks for one deal.

    Pure: the same deal, facts and pack always produce the same dates, which is
    what lets the API, the alert job and the tests agree without sharing state.
    """
    pack = _pack(pack)
    forms = pack.closing.forms
    facts = facts or {}
    checklist = checklist or {}
    live = anchors(deal, pack)
    out: list[dict] = []
    for task in tasks_for(deal, facts, pack):
        anchor_date = live[task.due.anchor]
        state = _state(checklist, task.key)
        override = parse_date(state.get("due_override"))
        due_on = override or (anchor_date + timedelta(days=task.due.offset))
        out.append({
            "key": task.key,
            "label": task.label,
            "phase": task.phase,
            "owner": task.owner,
            "why": task.why,
            "how": task.how,
            "form": task.form,
            # Ship the plain-English name with the code. A badge reading "BNA" is
            # noise to the first-time buyer this whole spec is written for.
            "form_name": forms[task.form].name if task.form in forms else "",
            "form_what": forms[task.form].what if task.form in forms else "",
            "blocking": task.blocking,
            "anchor": task.due.anchor,
            "offset": task.due.offset,
            "due_on": due_on.isoformat(),
            "due_overridden": override is not None,
            "cost": task.cost,
            "cost_band": _band_out(task.cost, pack.closing.costs),
            "done_on": state.get("done_on") or None,
            "done": bool(state.get("done_on")),
            "waived": bool(state.get("waived")),
            "note": state.get("note") or None,
        })
    out.sort(key=lambda t: (t["due_on"], t["key"]))
    return out


def evaluate(deal: dict, checklist: dict | None = None, facts: dict | None = None,
             today: date | None = None, soon_days: int = 3,
             pack: Pack | None = None) -> dict:
    """Roll a deal up into what is overdue, what is next, and what it all costs.

    Recomputed on read and never stored (docs/04), so correcting a date or a cost band
    immediately reprices an open deal.
    """
    pack = _pack(pack)
    costs = pack.closing.costs
    today = today or date.today()
    rows = schedule(deal, facts, checklist, pack)

    overdue, due_soon, open_blocking = [], [], []
    done_count = 0
    phase_counts: dict[str, dict] = {p.key: {"key": p.key, "title": p.title,
                                             "total": 0, "done": 0}
                                     for p in pack.closing.phases}
    bands: dict[str, object] = {}

    for row in rows:
        bucket = phase_counts.setdefault(
            row["phase"], {"key": row["phase"], "title": row["phase"], "total": 0, "done": 0})
        bucket["total"] += 1
        band = costs.get(row["cost"])
        if band:
            bands[band.key] = band
        if row["done"] or row["waived"]:
            bucket["done"] += 1
            done_count += 1
            continue
        due = date.fromisoformat(row["due_on"])
        delta = (due - today).days
        if delta < 0:
            overdue.append(row)
        elif delta <= soon_days:
            due_soon.append(row)
        if row["blocking"]:
            open_blocking.append(row)

    remaining = [r for r in rows if not r["done"] and not r["waived"]]
    ordered = sorted(bands.values(), key=lambda b: b.low, reverse=True)

    live = anchors(deal, pack)
    coe = live.get("coe")
    return {
        "anchors": {k: (v.isoformat() if v else None) for k, v in live.items()},
        "waived": [k for k in ("investigation_removal", "appraisal_removal", "loan_removal")
                   if live.get(k) is None],
        "total": len(rows),
        "done": done_count,
        "overdue": overdue,
        "due_soon": due_soon,
        "blocking_open": open_blocking,
        "next_action": remaining[0] if remaining else None,
        "phases": [phase_counts[p.key] for p in pack.closing.phases
                   if phase_counts[p.key]["total"]],
        "days_to_close": (coe - today).days if coe else None,
        "costs": {
            "year": costs.year,
            "label": costs.label,
            "low": sum(b.low for b in ordered),
            "high": sum(b.high for b in ordered),
            "items": [{"key": b.key, "label": b.label, "low": b.low, "high": b.high}
                      for b in ordered],
        },
    }


def spec_for(deal: dict, facts: dict | None = None, checklist: dict | None = None,
             pack: Pack | None = None) -> dict:
    """The task spec pruned to one deal, grouped by phase — mirrors tour_spec.spec_for.

    `checklist` is not optional in practice: this is what the UI renders its
    checkboxes and notes from, so omitting it hands back rows that all claim
    `done: False` while `evaluate()` reports the true count. Default it to empty
    only for the no-deal preview, where there is genuinely nothing ticked.
    """
    pack = _pack(pack)
    rows = schedule(deal, facts, checklist, pack)
    by_phase: dict[str, list[dict]] = {}
    for row in rows:
        by_phase.setdefault(row["phase"], []).append(row)
    c = pack.closing.contingency
    return {
        "phases": [
            {"key": p.key, "title": p.title, "blurb": p.blurb, "tasks": by_phase[p.key]}
            for p in pack.closing.phases if by_phase.get(p.key)
        ],
        "anchors": {k: (v.isoformat() if v else None) for k, v in anchors(deal, pack).items()},
        "contingency": {
            "investigation_days": c.investigation_days,
            "appraisal_days": c.appraisal_days,
            "loan_days": c.loan_days,
            "emd_business_days": c.emd_business_days,
            "label": c.label,
        },
    }
