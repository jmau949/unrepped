"""Composition helpers for building one pack from another.

A state pack is the `us` base plus field-level overrides and a few additions,
not a second copy of 70 records: checklist JSON (`deals.checklist`,
`tracked_listings.disclosure_checklist`, `settings.prep_checklist`) is keyed on
task keys, so the same key must mean the same task in every pack, and a pack
author should edit three dicts rather than re-type the base.

Every helper is total and loud: overriding or removing a key that does not
exist is a mistake in the pack, so it raises at import time.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import TypeVar

from hb.packs.types import TourItem, TourSection

K = TypeVar("K")


def _keys(records: Iterable) -> list[str]:
    return [r.key for r in records]


def override(records: Sequence[K], overrides: dict[str, dict]) -> list[K]:
    """Replace named fields on the records whose key is in `overrides`."""
    unknown = set(overrides) - set(_keys(records))
    if unknown:
        raise KeyError(f"override targets unknown keys: {sorted(unknown)}")
    return [replace(r, **overrides[r.key]) if r.key in overrides else r for r in records]


def add(records: Sequence[K], *new: K, after: str | None = None) -> list[K]:
    """Append records, or insert them right after the record keyed `after`."""
    dupes = set(_keys(new)) & set(_keys(records))
    if dupes:
        raise KeyError(f"add would duplicate keys: {sorted(dupes)}")
    out = list(records)
    if after is None:
        out.extend(new)
        return out
    idx = next((i for i, r in enumerate(out) if r.key == after), None)
    if idx is None:
        raise KeyError(f"add after unknown key: {after!r}")
    out[idx + 1:idx + 1] = list(new)
    return out


def without(records: Sequence[K], *keys: str) -> list[K]:
    missing = set(keys) - set(_keys(records))
    if missing:
        raise KeyError(f"without targets unknown keys: {sorted(missing)}")
    return [r for r in records if r.key not in keys]


# --- tour sections hold their items, so item edits go through the section ---


def _items(sections: Sequence[TourSection]) -> list[TourItem]:
    return [i for s in sections for i in s.items]


def override_items(sections: Sequence[TourSection],
                   overrides: dict[str, dict]) -> list[TourSection]:
    unknown = set(overrides) - set(_keys(_items(sections)))
    if unknown:
        raise KeyError(f"override_items targets unknown keys: {sorted(unknown)}")
    return [replace(s, items=override(s.items, {k: v for k, v in overrides.items()
                                                 if k in _keys(s.items)}))
            for s in sections]


def without_items(sections: Sequence[TourSection], *keys: str) -> list[TourSection]:
    missing = set(keys) - set(_keys(_items(sections)))
    if missing:
        raise KeyError(f"without_items targets unknown keys: {sorted(missing)}")
    return [replace(s, items=[i for i in s.items if i.key not in keys]) for s in sections]


def add_items(sections: Sequence[TourSection], section_key: str, *new: TourItem,
              after: str | None = None) -> list[TourSection]:
    if section_key not in _keys(sections):
        raise KeyError(f"add_items to unknown section: {section_key!r}")
    dupes = set(_keys(new)) & set(_keys(_items(sections)))
    if dupes:
        raise KeyError(f"add_items would duplicate keys: {sorted(dupes)}")
    return [replace(s, items=add(s.items, *new, after=after)) if s.key == section_key else s
            for s in sections]
