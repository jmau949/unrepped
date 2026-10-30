import sqlite3
from datetime import date, timedelta

from hb.db.backup import backup_db
from hb.db.models import Base
from hb.db.engine import make_engine


def _make_db(tmp_path):
    db = tmp_path / "hb.sqlite3"
    eng = make_engine(db)
    Base.metadata.create_all(eng)
    eng.dispose()
    return db


def test_backup_creates_valid_copy(tmp_path):
    db = _make_db(tmp_path)
    out = backup_db(db_path=db, backups_dir=tmp_path / "backups")

    assert out.exists()
    conn = sqlite3.connect(out)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "properties" in tables and "market_metrics" in tables


def test_same_day_rerun_overwrites(tmp_path):
    db = _make_db(tmp_path)
    backups = tmp_path / "backups"
    backup_db(db_path=db, backups_dir=backups)
    backup_db(db_path=db, backups_dir=backups)
    assert len(list(backups.glob("hb-*.sqlite3"))) == 1


def test_prune_removes_old_keeps_recent(tmp_path):
    db = _make_db(tmp_path)
    backups = tmp_path / "backups"
    backups.mkdir()
    old = backups / f"hb-{(date.today() - timedelta(days=20)).isoformat()}.sqlite3"
    recent = backups / f"hb-{(date.today() - timedelta(days=3)).isoformat()}.sqlite3"
    old.touch()
    recent.touch()
    unrelated = backups / "keep-me.sqlite3"
    unrelated.touch()

    backup_db(db_path=db, backups_dir=backups, keep_days=14)

    assert not old.exists()
    assert recent.exists()
    assert unrelated.exists()  # non-matching names never pruned
