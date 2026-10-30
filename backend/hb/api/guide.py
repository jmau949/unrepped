"""`GET /api/guide/closing` — the pack's closing playbook, served from its markdown
doc (docs/07 §Guide).

The `ca` pack's guide is `docs/14-closing-playbook.md`: the doc the Closing page
renders is the same file the repo maintains, split on its `## N.` headings into
sections the UI can deep-link to. A pack without a guide (the `us` base) gets a
404, and the page says so instead of showing another state's rules.
"""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from hb import packs
from hb.packs.types import Guide

router = APIRouter(prefix="/api/guide", tags=["guide"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HEADING = re.compile(r"^## (\d+)\. (.+?)\s*$", re.MULTILINE)


def split_sections(text: str, guide: Guide) -> tuple[str, str, list[dict]]:
    """(title, intro markdown, sections) from a doc with `## N. Title` headings.
    The intro is everything between the H1 and the first numbered heading."""
    lines = text.splitlines()
    title = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), "")
    matches = list(_HEADING.finditer(text))
    intro_start = text.find("\n", text.find("# ")) + 1 if title else 0
    intro = text[intro_start:matches[0].start()].strip() if matches else text[intro_start:].strip()
    sections: list[dict] = []
    for idx, m in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        n = m.group(1)
        sid = guide.section_ids.get(n, f"s{n}")
        if sid in guide.exclude:
            continue
        sections.append({
            "id": sid,
            "n": int(n),
            "title": m.group(2).strip(),
            "markdown": text[m.end():end].strip(),
        })
    return title, intro, sections


@router.get("/closing")
def closing_guide() -> dict:
    pack = packs.current()
    if pack.guide is None:
        raise HTTPException(404, f"the '{pack.key}' pack ships no closing guide")
    path = _REPO_ROOT / pack.guide.doc
    if not path.is_file():
        raise HTTPException(404, f"guide document not found: {pack.guide.doc}")
    title, intro, sections = split_sections(path.read_text(encoding="utf-8"), pack.guide)
    return {
        "pack": pack.key,
        "pack_label": pack.label,
        "doc": pack.guide.doc,
        "title": title,
        "intro_md": intro,
        "sections": sections,
        "phase_map": {
            phase: [{"id": sid, "label": label} for sid, label in links]
            for phase, links in pack.guide.phase_map.items()
        },
    }
