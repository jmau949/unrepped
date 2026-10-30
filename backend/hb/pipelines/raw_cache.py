"""Raw-cache retention — docs/05-pipelines.md §2.

Every bulk download lands in a new dated folder under data/raw/<source>/
(JobRunner.save_raw / download_to_raw) and nothing else ever removes one, so
the cache would grow by every release forever. Upstream restates its history
in each release and the loaded rows live in the database, so a dated folder
older than RAW_KEEP_DAYS has nothing left to offer and is deleted at the tail
of `hb pipeline daily` (and by `hb prune-raw`). Only folders named as an ISO
date directly under a source are candidates: undated reference data such as
data/raw/hazards/ is never touched.
"""

import logging
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from hb.config import settings

log = logging.getLogger(__name__)

_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def prune_raw(
    raw_dir: Path | None = None,
    keep_days: int | None = None,
    today: date | None = None,
) -> list[Path]:
    """Delete dated raw-cache folders older than `keep_days`; returns what went.
    A folder exactly `keep_days` old is kept. `keep_days` <= 0 keeps everything."""
    raw_dir = raw_dir or settings.raw_dir
    keep_days = settings.raw_keep_days if keep_days is None else keep_days
    if keep_days <= 0 or not raw_dir.is_dir():
        return []
    cutoff = (today or date.today()) - timedelta(days=keep_days)

    removed: list[Path] = []
    for source in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        for folder in sorted(p for p in source.iterdir() if p.is_dir()):
            if not _DATED.match(folder.name):
                continue
            try:
                downloaded = date.fromisoformat(folder.name)
            except ValueError:
                continue
            if downloaded >= cutoff:
                continue
            try:
                shutil.rmtree(folder)
            except OSError as exc:  # a locked file must not stop the rest of the sweep
                log.warning("raw cache: could not prune %s/%s: %s", source.name, folder.name, exc)
                continue
            removed.append(folder)
            log.info("raw cache: pruned %s/%s", source.name, folder.name)
    return removed
