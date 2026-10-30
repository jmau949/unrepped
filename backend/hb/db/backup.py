"""Nightly SQLite backup with retention — docs/11-deployment.md §2.

Uses sqlite3's online backup API (safe under WAL, no downtime). One file per
day (same-day re-runs overwrite), pruned after keep_days.
"""

import logging
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from hb.config import settings

log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"hb-(\d{4}-\d{2}-\d{2})\.sqlite3$")


def backup_db(
    db_path: Path | None = None,
    backups_dir: Path | None = None,
    keep_days: int = 14,
) -> Path:
    src_path = db_path or settings.db_path
    out_dir = backups_dir or settings.data_dir / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_path = out_dir / f"hb-{date.today().isoformat()}.sqlite3"

    src = sqlite3.connect(src_path)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()

    cutoff = date.today() - timedelta(days=keep_days)
    for f in out_dir.glob("hb-*.sqlite3"):
        m = _NAME_RE.search(f.name)
        if m and date.fromisoformat(m.group(1)) < cutoff:
            f.unlink()
            log.info("pruned old backup %s", f.name)

    log.info("backup written: %s", dest_path)
    return dest_path
