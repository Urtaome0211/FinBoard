"""Automatic database backups, integrity checks and restore helpers."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .database import Database, SCHEMA_VERSION

BACKUP_PREFIX = "finboard-"
BACKUP_SUFFIX = ".db"
_INDEX_MARKERS = ("index", "索引")


def backup_dir(db_path: str | Path) -> Path:
    path = Path(db_path)
    if str(path) == ":memory:":
        raise ValueError("内存数据库不支持备份")
    return path.parent / "backups"


def list_backups(db_path: str | Path) -> list[Path]:
    folder = backup_dir(db_path)
    if not folder.exists():
        return []
    return sorted(folder.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))


def latest_backup(db_path: str | Path) -> Path | None:
    backups = list_backups(db_path)
    return backups[-1] if backups else None


def rotate_backups(db_path: str | Path, keep: int = 10) -> None:
    keep = max(1, int(keep))
    backups = list_backups(db_path)
    for old in backups[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass


def create_backup(
    db: Database, *, keep: int = 10, reason: str = "auto"
) -> Path:
    """Copy the live database into ``<data>/backups`` and rotate old copies."""
    path = Path(db.path)
    if str(path) == ":memory:":
        raise ValueError("内存数据库不支持备份")
    folder = backup_dir(path)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"
    counter = 1
    while target.exists():
        target = folder / f"{BACKUP_PREFIX}{stamp}-{counter}{BACKUP_SUFFIX}"
        counter += 1
    try:
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    destination = sqlite3.connect(target)
    try:
        db.conn.backup(destination)
    finally:
        destination.close()
    rotate_backups(path, keep)
    return target


def quick_check(db: Database) -> tuple[bool, str]:
    """Return ``(ok, detail)`` for the SQLite integrity check."""
    try:
        rows = db.conn.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error as exc:
        return False, str(exc)
    problems = [str(row[0]) for row in rows if str(row[0]).lower() != "ok"]
    if problems:
        return False, "；".join(problems[:3])
    try:
        foreign = db.conn.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.Error as exc:
        return False, str(exc)
    if foreign:
        return False, f"发现 {len(foreign)} 处外键异常"
    return True, ""


def looks_like_index_problem(detail: str) -> bool:
    """Return True when quick_check reports a broken index b-tree."""
    text = str(detail).lower()
    return any(marker in text for marker in _INDEX_MARKERS)


def repair_indexes(db: Database) -> tuple[bool, str]:
    """Rebuild all indexes after an index-only integrity failure.

    The function is deliberately conservative: a database that is damaged
    outside its indexes is returned untouched, so the caller can offer a
    backup restore instead of hiding real corruption.
    """
    ok, detail = quick_check(db)
    if ok:
        return True, ""
    if not looks_like_index_problem(detail):
        return False, detail
    try:
        create_backup(db, keep=20, reason="before-reindex")
    except Exception:
        pass
    try:
        db.conn.execute("REINDEX")
        db.conn.commit()
    except sqlite3.Error as exc:
        return False, str(exc)
    ok, detail = quick_check(db)
    if not ok:
        return False, detail
    return True, "已重建索引"


def restore_backup(db: Database, source: str | Path) -> None:
    """Replace the live database with a verified backup."""
    source = Path(source)
    if not source.is_file():
        raise ValueError("备份文件不存在")
    source_conn = sqlite3.connect(source)
    try:
        version = int(
            source_conn.execute("PRAGMA user_version").fetchone()[0]
        )
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"备份版本为 {version}，当前版本为 {SCHEMA_VERSION}，无法直接恢复"
            )
        problems = [
            str(row[0])
            for row in source_conn.execute("PRAGMA quick_check").fetchall()
            if str(row[0]).lower() != "ok"
        ]
        if problems:
            raise ValueError("备份文件未通过完整性检查")
        create_backup(db, keep=20, reason="before-restore")
        try:
            db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        source_conn.backup(db.conn)
        db.conn.commit()
        db.conn.execute("PRAGMA foreign_keys=ON")
    finally:
        source_conn.close()
