"""State packs — the transaction content that differs by state (docs/packs/README.md).

`current()` resolves the pack for the configured geography: `geography.toml`
names one with `pack = "ca"`, otherwise the lower-cased state is tried, and a
state without a pack gets the `us` base. The geography's `[costs]` table is
then layered on (year, label, individual bands), so "2026 SF-Peninsula
contractor ranges" is a geography fact and the pack stays California-wide.

Packs are plain data, so this module holds no state: `current()` is cheap and
always reflects `settings.geo`, which is what lets the tests swap geographies
with a plain assignment.
"""

from __future__ import annotations

from dataclasses import replace

from hb.config import settings
from hb.geography import Geography
from hb.packs import ca, us
from hb.packs.types import CostBand, CostBook, Pack

REGISTRY: dict[str, Pack] = {"us": us.PACK, "ca": ca.PACK}

DEFAULT_KEY = "us"


def key_for(geo: Geography) -> str:
    key = geo.pack_key
    return key if key in REGISTRY else DEFAULT_KEY


def _book(book: CostBook, geo: Geography, bands: dict[str, tuple[int, int]]) -> CostBook:
    merged = dict(book.bands)
    for key, (low, high) in bands.items():
        base = merged.get(key)
        merged[key] = CostBand(key, base.label if base else key.replace("_", " "), low, high)
    return CostBook(
        year=geo.costs.year or book.year,
        label=geo.costs.label or book.label,
        bands=merged,
    )


def for_geography(geo: Geography) -> Pack:
    """The pack for a geography with its `[costs]` overrides applied."""
    pack = REGISTRY[key_for(geo)]
    return replace(
        pack,
        closing=replace(pack.closing, costs=_book(pack.closing.costs, geo, geo.costs.closing)),
        tour=replace(pack.tour, cost_bands=_book(pack.tour.cost_bands, geo, geo.costs.tour)),
    )


def current() -> Pack:
    return for_geography(settings.geo)


def validate(pack: Pack) -> list[str]:
    """Internal-consistency problems in a pack — empty for a well-formed one.
    Run over every registered pack by the test suite."""
    problems: list[str] = []
    c = pack.closing

    def unique(label: str, keys: list[str]) -> None:
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            problems.append(f"{label}: duplicate keys {dupes}")

    unique("closing.tasks", [t.key for t in c.tasks])
    unique("closing.phases", [p.key for p in c.phases])
    phases = {p.key for p in c.phases}
    for t in c.tasks:
        if t.phase not in phases:
            problems.append(f"closing task {t.key}: unknown phase {t.phase!r}")
        if t.form and t.form not in c.forms:
            problems.append(f"closing task {t.key}: unknown form {t.form!r}")
        if t.cost and t.cost not in c.costs.bands:
            problems.append(f"closing task {t.key}: unknown cost band {t.cost!r}")
        if not (t.why and t.how):
            problems.append(f"closing task {t.key}: why/how must both be filled in")
    for code, form in c.forms.items():
        if not (form.name and form.what) or form.name == form.code:
            problems.append(f"form {code}: needs a plain-English name and description")

    items = [i for s in pack.tour.sections for i in s.items]
    unique("tour.items", [i.key for i in items])
    for i in items:
        if i.cost and i.cost not in pack.tour.cost_bands.bands:
            problems.append(f"tour item {i.key}: unknown cost band {i.cost!r}")

    unique("prep.tasks", [t.key for t in pack.prep.tasks])
    prep_phases = {p.key for p in pack.prep.phases}
    for t in pack.prep.tasks:
        if t.phase not in prep_phases:
            problems.append(f"prep task {t.key}: unknown phase {t.phase!r}")
        if t.owner not in pack.prep.owners:
            problems.append(f"prep task {t.key}: unknown owner {t.owner!r}")
        if t.needed_by not in pack.prep.needed_by:
            problems.append(f"prep task {t.key}: unknown needed_by {t.needed_by!r}")
        if not (t.why and t.how):
            problems.append(f"prep task {t.key}: why/how must both be filled in")

    unique("hazards", [h.key for h in pack.hazards])
    unique("rating_sources", [r.key for r in pack.rating_sources])
    unique("tracker_checklist", [f.key for f in pack.content.tracker_checklist])
    if pack.guide:
        ids = set(pack.guide.section_ids.values())
        for phase, links in pack.guide.phase_map.items():
            if phase not in phases:
                problems.append(f"guide.phase_map: unknown closing phase {phase!r}")
            for sid, _label in links:
                if sid not in ids:
                    problems.append(f"guide.phase_map[{phase}]: unknown section id {sid!r}")
    return problems
