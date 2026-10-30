"""Shared pipeline job runner — implements the idempotency & bookkeeping
contract of docs/05-pipelines.md §1.

Every job runs inside a JobRunner context manager, which:
- writes one `pipeline_runs` row per invocation (status ok|noop|partial|failed),
- collects per-item errors without aborting the run (partial-failure tolerance),
- provides content-hash bookkeeping for bulk downloads (daily schedule,
  weekly/monthly upstream => hash-unchanged => status noop).

Job-level exceptions are recorded as status=failed and suppressed so a
meta-command (`hb pipeline daily`) can continue with the next job.
"""

import hashlib
import logging
from contextlib import contextmanager
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.engine import Engine

from hb.config import settings
from hb.db.engine import get_engine, make_session
from hb.db.models import PipelineRun, utcnow_iso

log = logging.getLogger(__name__)

PROGRESS_EVERY_BYTES = 512 << 20  # a progress line per 512 MiB of a bulk download


def human_size(n: int) -> str:
    """A byte count the way a person reads it: '5.5 GB', '210 MB', '12 kB'."""
    for unit, size in (("GB", 1 << 30), ("MB", 1 << 20), ("kB", 1 << 10)):
        if n >= size:
            value = n / size
            return f"{value:.1f} {unit}" if value < 10 else f"{value:.0f} {unit}"
    return f"{n} B"


def geo_fingerprint() -> str:
    """The target geography as a string to fold into a bulk job's content hash.

    A job that filters an upstream file to the geography's ZIPs / cities must
    reload that file when the lists change, not only when upstream republishes
    it — otherwise a newly added city stays empty until the next release.
    """
    return ",".join(sorted(settings.target_zips)) + "|" + ",".join(sorted(settings.target_cities))


class JobRunner:
    def __init__(self, job: str, engine: Engine | None = None):
        self.job = job
        self.engine = engine or get_engine()
        self.items_seen = 0
        self.items_upserted = 0
        self.events_emitted = 0
        self.errors: list[str] = []
        self.content_hash: str | None = None
        self.status: str = "running"
        self._noop = False

    def __enter__(self) -> "JobRunner":
        self.session = make_session(self.engine)
        self.run_row = PipelineRun(job=self.job)
        self.session.add(self.run_row)
        self.session.commit()
        return self

    @contextmanager
    def item(self, label: str = ""):
        """Wrap per-item work; an exception is recorded, not raised."""
        self.items_seen += 1
        try:
            yield
        except Exception as exc:  # noqa: BLE001 — deliberate catch-all per docs/05 §1.3
            self.errors.append(f"{label}: {exc}")
            log.warning("job %s item failed (%s): %s", self.job, label, exc)

    def mark_noop(self) -> None:
        """Call when the upstream content hash is unchanged — job did nothing."""
        self._noop = True

    def last_content_hash(self) -> str | None:
        """Hash from this job's most recent successful (ok/noop) run."""
        return self.session.execute(
            select(PipelineRun.content_hash)
            .where(
                PipelineRun.job == self.job,
                PipelineRun.status.in_(["ok", "noop"]),
                PipelineRun.content_hash.is_not(None),
                PipelineRun.id != self.run_row.id,
            )
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def save_raw(self, source: str, name: str, content: bytes) -> tuple[str, bool]:
        """Cache a downloaded file under data/raw/<source>/<date>/ with a .sha256
        sidecar. Returns (path, changed) — changed=False means the bytes are
        identical to the last successful run's and the caller should mark_noop().
        """
        digest = hashlib.sha256(content).hexdigest()
        raw_dir = settings.raw_dir / source / date.today().isoformat()
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / name
        path.write_bytes(content)
        (raw_dir / f"{name}.sha256").write_text(digest)
        changed = digest != self.last_content_hash()
        self.content_hash = digest
        return str(path), changed

    def download_to_raw(self, url: str, source: str, name: str) -> tuple[str, str]:
        """Stream a (possibly 100MB+) download to the raw cache, hashing as it
        goes. Returns (path, sha256). Does NOT touch content-hash bookkeeping —
        multi-file jobs combine their file digests and set self.content_hash.

        Says what it is downloading and how big, and logs progress every
        PROGRESS_EVERY_BYTES: the Redfin files are ~5.5 GB, and a first run
        must not sit silent for the whole download.
        """
        raw_dir = settings.raw_dir / source / date.today().isoformat()
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / name
        digest = hashlib.sha256()
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            log.info("%s: downloading %s (%s)", self.job, name,
                     human_size(total) if total else "size unknown")
            done = reported = 0
            with open(path, "wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if done // PROGRESS_EVERY_BYTES > reported:
                        reported = done // PROGRESS_EVERY_BYTES
                        log.info("%s: %s: %s of %s", self.job, name, human_size(done),
                                 human_size(total) if total else "?")
        log.info("%s: %s downloaded (%s)", self.job, name, human_size(done))
        hexdigest = digest.hexdigest()
        (raw_dir / f"{name}.sha256").write_text(hexdigest)
        return str(path), hexdigest

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if exc is not None:
            self.status = "failed"
            summary = f"{type(exc).__name__}: {exc}"
        elif self._noop:
            self.status = "noop"
            summary = None
        elif self.errors and self.items_seen and len(self.errors) >= self.items_seen:
            self.status = "failed"
            summary = "; ".join(self.errors[:10])
        elif self.errors:
            self.status = "partial"
            summary = "; ".join(self.errors[:10])
        else:
            self.status = "ok"
            summary = None

        self.run_row.finished_at = utcnow_iso()
        self.run_row.status = self.status
        self.run_row.items_seen = self.items_seen
        self.run_row.items_upserted = self.items_upserted
        self.run_row.events_emitted = self.events_emitted
        self.run_row.error_summary = summary
        self.run_row.content_hash = self.content_hash
        self.session.commit()
        self.session.close()
        if exc is not None:
            log.error("job %s failed: %s", self.job, exc)
        return True  # suppress — callers read .status
