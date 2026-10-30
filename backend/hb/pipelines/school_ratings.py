"""school-ratings pipeline — CAASPP test-score ratings (docs/05-pipelines.md §10).

Derives a 1-10 rating for each CA public school from the state's CAASPP Smarter
Balanced results (% of students meeting/exceeding standard, ELA + Math, all
students, all grades) and joins it onto the NCES `schools` table by (zip, name),
setting `schools.rating`. The rating is a **decile** of average %-met across CA
schools — a real, defensible test-performance percentile, not the proprietary
GreatSchools number.

Standalone job (`hb pipeline school-ratings`), NOT in the daily sequence: CAASPP
updates once a year and the results file is ~157 MB. Rerun after each annual
release, with CAASPP_YEAR bumped. Pack-gated: it runs only where the current
pack declares the `caaspp` rating source (the `ca` pack); under any other pack
the job records a noop and leaves ratings to the other sources. Unmatched
schools keep rating=NULL (badge "—").
"""

import csv
import hashlib
import logging
import os
import re
import zipfile

import duckdb
import pandas as pd
from sqlalchemy import select

from hb import packs
from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import School, SchoolRatingSnapshot
from hb.db.upsert import upsert
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)

_BASE = "https://caaspp-elpac.ets.org/caaspp/researchfiles"


def _year() -> int:
    return settings.caaspp_year  # bump CAASPP_YEAR after each annual release


def results_url() -> str:
    return f"{_BASE}/sb_ca{_year()}_all_csv_v1.zip"


def entities_url() -> str:
    return f"{_BASE}/sb_ca{_year()}entities_csv.zip"


def _norm(name: str | None) -> str:
    """Collapse a school name to a comparison key (lowercase alphanumerics)."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _extract(zip_path: str) -> str:
    """Extract the single member of a CAASPP zip alongside it; return its path."""
    with zipfile.ZipFile(zip_path) as z:
        member = z.namelist()[0]
        dest_dir = os.path.dirname(zip_path)
        dest = os.path.join(dest_dir, member)
        if not os.path.exists(dest):
            z.extract(member, dest_dir)
        return dest


def _aggregate_pct(results_csv: str) -> pd.DataFrame:
    """Per-school average % Standard Met and Above across ELA (Test ID 1) and
    Math (Test ID 2), All Students (Student Group ID 1), All Grades (Grade 13).
    Returns columns cc, dc, scode, sch_name, pct. Caret-delimited, Latin-1."""
    con = duckdb.connect()
    try:
        return con.execute(
            """
            SELECT "County Code" AS cc, "District Code" AS dc, "School Code" AS scode,
                   any_value("School Name") AS sch_name,
                   avg(TRY_CAST("Percentage Standard Met and Above" AS DOUBLE)) AS pct
            FROM read_csv(?, delim='^', header=true, all_varchar=true, encoding='latin-1')
            WHERE "School Code" <> '0000000' AND "Student Group ID" = '1'
                  AND "Grade" = '13' AND "Test ID" IN ('1', '2')
                  AND TRY_CAST("Percentage Standard Met and Above" AS DOUBLE) IS NOT NULL
            GROUP BY 1, 2, 3
            """,
            [results_csv],
        ).df()
    finally:
        con.close()


def _zip_by_cds(entities_csv: str) -> dict:
    """(County Code, District Code, School Code) -> 5-digit zip, from the CAASPP
    entities file (caret-delimited; Zip Code is column 9)."""
    out: dict = {}
    with open(entities_csv, encoding="latin-1", newline="") as fh:
        reader = csv.reader(fh, delimiter="^")
        next(reader, None)  # header
        for row in reader:
            if len(row) >= 10 and row[0].isdigit():
                out[(row[0], row[1], row[2])] = ((row[9] or "").strip()[:5]) or None
    return out


def _build_rating_lookup(pct_df: pd.DataFrame, zip_by_cds: dict) -> dict:
    """(zip, normalized name) -> (rating, pct_met). Rating is the decile of
    average %-met across all rated CA schools (percentile rank scaled to 1-10);
    pct_met is the raw average % met/exceeded (kept so the UI can show it)."""
    if pct_df.empty:
        return {}
    df = pct_df.copy()
    df["rating"] = (df["pct"].rank(pct=True) * 9 + 1).round().clip(1, 10).astype(int)
    lookup: dict = {}
    for r in df.itertuples(index=False):
        z5 = zip_by_cds.get((r.cc, r.dc, r.scode))
        if z5:
            lookup[(z5, _norm(r.sch_name))] = (int(r.rating), round(float(r.pct), 1))
    return lookup


def fetch_caaspp(runner: JobRunner) -> tuple[pd.DataFrame, dict, str]:
    """Download + extract the CAASPP results and entities files; return the
    per-school %-met frame, the (cds -> zip) map, and a combined content hash.
    Network seam — tests monkeypatch this. The ~1 GB extracted results CSV is
    removed after aggregation (the zips stay in the raw cache)."""
    year = _year()
    results_zip, d1 = runner.download_to_raw(results_url(), "caaspp", f"sb_ca{year}_all.zip")
    entities_zip, d2 = runner.download_to_raw(entities_url(), "caaspp",
                                              f"sb_ca{year}entities.zip")
    results_csv = _extract(results_zip)
    entities_csv = _extract(entities_zip)
    try:
        pct_df = _aggregate_pct(results_csv)
        zip_by_cds = _zip_by_cds(entities_csv)
    finally:
        if results_csv != results_zip and os.path.exists(results_csv):
            os.remove(results_csv)  # ~1 GB; don't keep the extracted copy
    digest = hashlib.sha256(f"{d1}|{d2}".encode()).hexdigest()
    return pct_df, zip_by_cds, digest


def _backfill_snapshots(runner: JobRunner) -> int:
    """Write `source='caaspp'` snapshot rows for already-rated schools that
    lack one (the snapshot table postdates the rating columns; an unchanged
    annual file must still converge). Returns how many were missing."""
    session = make_session(runner.engine)
    try:
        have = select(SchoolRatingSnapshot.school_id).where(
            SchoolRatingSnapshot.source == "caaspp")
        missing = session.execute(
            select(School).where(School.rating.is_not(None), School.id.not_in(have))
        ).scalars().all()
        for sc in missing:
            upsert(session, SchoolRatingSnapshot, {
                "school_id": sc.id, "source": "caaspp",
                "rating_10": float(sc.rating),
                "label": (f"{sc.pct_met:.0f}% met standard"
                          if sc.pct_met is not None else None),
                "detail": {"pct_met": sc.pct_met},
                "as_of": str(_year()),
            }, ["school_id", "source"])
        session.commit()
        if missing:
            runner.items_upserted += len(missing)
            log.info("school-ratings: backfilled %d caaspp snapshots", len(missing))
        return len(missing)
    finally:
        session.close()


def _pack_declares_caaspp() -> bool:
    """CAASPP is a California test, so the source belongs to the `ca` pack's
    `rating_sources` (docs/packs/README.md); no state literal lives here."""
    return any(src.key == "caaspp" for src in packs.current().rating_sources)


def run(engine=None) -> str:
    with JobRunner("school-ratings", engine) as runner:
        if not _pack_declares_caaspp():
            log.info("school-ratings: the %s pack declares no CAASPP source; geography is %s "
                     "— skipping", packs.current().key, settings.geo.state)
            runner.mark_noop()  # status finalized by __exit__
        else:
            _run_caaspp(runner)
    return runner.status


def _run_caaspp(runner: JobRunner) -> None:
    pct_df, zip_by_cds, digest = fetch_caaspp(runner)
    runner.content_hash = digest
    if digest == runner.last_content_hash():
        if _backfill_snapshots(runner) == 0:
            runner.mark_noop()  # status finalized by __exit__; return AFTER the with-block
    else:
        lookup = _build_rating_lookup(pct_df, zip_by_cds)
        session = make_session(runner.engine)
        try:
            with runner.item("caaspp"):
                schools = session.execute(select(School)).scalars().all()
                matched = 0
                for sc in schools:
                    hit = lookup.get((sc.zip, _norm(sc.name)))
                    if hit is not None:
                        sc.rating, sc.pct_met = hit
                        # multi-source snapshot row so the API serves all
                        # ratings uniformly (docs/04 school_rating_snapshots)
                        upsert(session, SchoolRatingSnapshot, {
                            "school_id": sc.id, "source": "caaspp",
                            "rating_10": float(sc.rating),
                            "label": f"{sc.pct_met:.0f}% met standard",
                            "detail": {"pct_met": sc.pct_met},
                            "as_of": str(_year()),
                        }, ["school_id", "source"])
                        matched += 1
                session.commit()
                runner.items_upserted = matched
                log.info("school-ratings: rated %d / %d schools", matched, len(schools))
        finally:
            session.close()
