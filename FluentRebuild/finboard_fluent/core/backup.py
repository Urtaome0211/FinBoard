"""Automatic database backups, integrity checks and restore helpers."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .. import __version__
from .database import DB_ERROR, Database, SCHEMA_VERSION
from .security import load_config

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
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = folder / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"
    counter = 1
    while target.exists():
        target = folder / f"{BACKUP_PREFIX}{stamp}-{counter}{BACKUP_SUFFIX}"
        counter += 1
    db.backup_to(target)
    rotate_backups(path, keep)
    return target


def quick_check(db: Database) -> tuple[bool, str]:
    """Return ``(ok, detail)`` for the SQLite integrity check."""
    try:
        rows = db.conn.execute("PRAGMA quick_check").fetchall()
    except DB_ERROR as exc:
        return False, str(exc)
    problems = [str(row[0]) for row in rows if str(row[0]).lower() != "ok"]
    if problems:
        return False, "；".join(problems[:3])
    try:
        foreign = db.conn.execute("PRAGMA foreign_key_check").fetchall()
    except DB_ERROR as exc:
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
    except DB_ERROR as exc:
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
    source_conn = db.connect_external(source)
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
        db.checkpoint()
        source_conn.backup(db.conn)
        db.conn.commit()
        db.conn.execute("PRAGMA foreign_keys=ON")
    finally:
        source_conn.close()


# --------------------------------------------------------------- full bundles
BUNDLE_FORMAT = 1
BUNDLE_MAGIC = b"FBK1"


def _bundle_key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )


def _encrypt_bundle(data: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _bundle_key(password, salt)
    return BUNDLE_MAGIC + salt + nonce + AESGCM(key).encrypt(nonce, data, None)


def _decrypt_bundle(data: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not data.startswith(BUNDLE_MAGIC):
        raise ValueError("不是有效的 FinBoard 备份包")
    body = data[len(BUNDLE_MAGIC) :]
    if len(body) < 28:
        raise ValueError("备份包内容不完整")
    salt, nonce, ciphertext = body[:16], body[16:28], body[28:]
    try:
        return AESGCM(_bundle_key(password, salt)).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError("备份包密码不正确或文件已损坏") from exc


def _bundle_bytes(path: Path, password: str | None) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() == ".fbk":
        if not password:
            raise ValueError("该备份包已加密，请输入密码")
        return _decrypt_bundle(data, password)
    return data


def create_full_backup(
    db: Database, *, password: str | None = None, include_attachments: bool = True
) -> Path:
    """Create a complete bundle: database, attachments, security.json and manifest."""
    path = Path(db.path)
    folder = backup_dir(path)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    work = Path(tempfile.mkdtemp(prefix="finboard-bundle-"))
    try:
        db_copy = work / "finboard.db"
        db.backup_to(db_copy)
        files: list[dict[str, object]] = []
        db_hash = hashlib.sha256(db_copy.read_bytes()).hexdigest()
        files.append({"path": "finboard.db", "size": db_copy.stat().st_size, "sha256": db_hash})
        attachments = path.parent / "attachments"
        if include_attachments and attachments.is_dir():
            dest = work / "attachments"
            shutil.copytree(attachments, dest)
            for item in sorted(dest.rglob("*")):
                if item.is_file():
                    files.append(
                        {
                            "path": str(item.relative_to(work)).replace("\\", "/"),
                            "size": item.stat().st_size,
                            "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
                        }
                    )
        config = path.parent / "security.json"
        if config.is_file():
            shutil.copy2(config, work / "security.json")
            files.append(
                {
                    "path": "security.json",
                    "size": (work / "security.json").stat().st_size,
                    "sha256": hashlib.sha256((work / "security.json").read_bytes()).hexdigest(),
                }
            )
        version = int(db.conn.execute("PRAGMA user_version").fetchone()[0])
        manifest = {
            "format": BUNDLE_FORMAT,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "schema": version,
            "app_version": __version__,
            "database_encrypted": db.is_encrypted,
            "attachment_count": sum(1 for f in files if str(f["path"]).startswith("attachments/")),
            "files": files,
        }
        (work / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        zip_path = folder / f"finboard-full-{stamp}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(work.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(work).as_posix())
        if password:
            encrypted = folder / f"finboard-full-{stamp}.fbk"
            encrypted.write_bytes(_encrypt_bundle(zip_path.read_bytes(), password))
            zip_path.unlink()
            return encrypted
        return zip_path
    finally:
        shutil.rmtree(work, ignore_errors=True)


def verify_full_backup(path: str | Path, *, password: str | None = None) -> dict[str, object]:
    """Validate a complete bundle without touching the live database."""
    path = Path(path)
    if not path.is_file():
        raise ValueError("备份包不存在")
    data = _bundle_bytes(path, password)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        if "manifest.json" not in names:
            raise ValueError("备份包缺少 manifest.json")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if int(manifest.get("format", 0)) != BUNDLE_FORMAT:
            raise ValueError("备份包格式不受支持")
        for entry in manifest.get("files", []):
            name = str(entry.get("path"))
            if name not in names:
                raise ValueError(f"备份包缺少文件：{name}")
            payload = archive.read(name)
            if len(payload) != int(entry.get("size", -1)):
                raise ValueError(f"备份文件大小不匹配：{name}")
            if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
                raise ValueError(f"备份文件校验失败：{name}")
        db_name = "finboard.db"
        if "security.json" in names:
            security = json.loads(archive.read("security.json").decode("utf-8"))
        else:
            security = None
        db_bytes = archive.read(db_name)
        encrypted = bool(manifest.get("database_encrypted"))
        if not encrypted:
            handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            try:
                handle.write(db_bytes)
                handle.close()
                check = sqlite3.connect(handle.name)
                try:
                    rows = check.execute("PRAGMA quick_check").fetchall()
                    if [row for row in rows if str(row[0]).lower() != "ok"]:
                        raise ValueError("备份数据库未通过完整性检查")
                finally:
                    check.close()
            finally:
                try:
                    os.unlink(handle.name)
                except OSError:
                    pass
    return {
        "manifest": manifest,
        "encrypted": encrypted,
        "security": security,
        "path": str(path),
    }


def restore_full_backup(
    db: Database, bundle: str | Path, *, password: str | None = None
) -> dict[str, object]:
    """Restore database, attachments and security.json from a bundle."""
    info = verify_full_backup(bundle, password=password)
    data = _bundle_bytes(Path(bundle), password)
    work = Path(tempfile.mkdtemp(prefix="finboard-restore-"))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(work)
        restored_db = work / "finboard.db"
        if db.is_encrypted:
            if not db.encryption_key:
                raise ValueError("当前数据库已加密，缺少解锁密钥")
        else:
            if info["encrypted"]:
                raise ValueError("不能把加密备份恢复到未加密数据库，请先启用加密")
        if not db.is_encrypted and info["encrypted"]:
            raise ValueError("备份包是加密的，当前数据库未加密")
        if db.is_encrypted and not info["encrypted"]:
            raise ValueError("当前数据库已加密，不能恢复未加密备份")
        if db.is_encrypted:
            current = load_config(db.path) or {}
            incoming = info.get("security") or {}
            if current.get("verifier") != incoming.get("verifier"):
                raise ValueError("备份包的加密配置与当前数据库不一致")
        # Keep the current database as a safety copy before swapping.
        create_backup(db, keep=20, reason="before-full-restore")
        db.checkpoint()
        db.restore_from(restored_db)
        attachments = Path(db.path).parent / "attachments"
        incoming = work / "attachments"
        if incoming.is_dir():
            if attachments.exists():
                backup = attachments.with_name("attachments-before-restore")
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                attachments.rename(backup)
            shutil.copytree(incoming, attachments)
        source_config = work / "security.json"
        if source_config.is_file():
            shutil.copy2(source_config, Path(db.path).parent / "security.json")
        return info
    finally:
        shutil.rmtree(work, ignore_errors=True)


def recovery_drill(db: Database, *, password: str | None = None) -> dict[str, object]:
    """Create, verify and open a temporary restore from a fresh bundle."""
    bundle = create_full_backup(db, password=password, include_attachments=False)
    try:
        info = verify_full_backup(bundle, password=password)
        data = _bundle_bytes(bundle, password)
        work = Path(tempfile.mkdtemp(prefix="finboard-drill-"))
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.extract("finboard.db", work)
            temp_db = Database(work / "finboard.db", encryption_key=db.encryption_key)
            try:
                temp_db.conn.execute("SELECT 1").fetchone()
                ok, detail = quick_check(temp_db)
                if not ok:
                    raise ValueError(detail)
                count = int(
                    temp_db.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
                )
            finally:
                temp_db.close()
            info["transactions"] = count
            return info
        finally:
            shutil.rmtree(work, ignore_errors=True)
    finally:
        try:
            bundle.unlink()
        except OSError:
            pass
