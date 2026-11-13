"""Database encryption and local unlock helpers.

SQLCipher is optional at runtime.  When it is unavailable the rest of the
application still opens ordinary SQLite databases; only the security actions
are disabled.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # pragma: no cover - availability depends on the installed wheel
    import sqlcipher3
except Exception:  # pragma: no cover
    sqlcipher3 = None  # type: ignore[assignment]

CONFIG_NAME = "security.json"
CONFIG_VERSION = 1
KDF_N = 2**14
KDF_R = 8
KDF_P = 1
_VERIFY_LABEL = b"finboard-verify-v1"
_SQLITE_HEADER = b"SQLite format 3\x00"


class SecurityError(ValueError):
    """Raised when an encryption/backup operation cannot be completed."""


class DatabaseLocked(SecurityError):
    """Raised when an encrypted database is opened without its key."""


def sqlcipher_available() -> bool:
    return sqlcipher3 is not None


def config_path(db_path: str | Path) -> Path:
    path = Path(db_path)
    return path.parent / CONFIG_NAME


def is_encrypted_file(path: str | Path) -> bool:
    """Return True for a non-SQLite file, i.e. a SQLCipher container."""
    path = Path(path)
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return False
    return bool(head) and head != _SQLITE_HEADER


def load_config(db_path: str | Path) -> dict[str, Any] | None:
    path = config_path(db_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_config(db_path: str | Path, data: dict[str, Any]) -> None:
    path = config_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def update_config(db_path: str | Path, **changes: Any) -> dict[str, Any]:
    config = load_config(db_path)
    if not config:
        raise SecurityError("数据库尚未启用加密")
    config.update(changes)
    _write_config(db_path, config)
    return config


def _remove_config(db_path: str | Path) -> None:
    try:
        config_path(db_path).unlink()
    except FileNotFoundError:
        pass


def new_salt() -> bytes:
    return os.urandom(16)


def derive_master(password: str, salt: bytes) -> bytes:
    password = str(password)
    if not password:
        raise SecurityError("密码不能为空")
    try:
        return hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=KDF_N, r=KDF_R, p=KDF_P, dklen=32
        )
    except (ValueError, MemoryError) as exc:  # pragma: no cover
        raise SecurityError("无法派生加密密钥") from exc


def _verifier(master: bytes) -> str:
    return hmac.new(master, _VERIFY_LABEL, hashlib.sha256).hexdigest()


def verifier_for(password: str, salt: bytes) -> str:
    return _verifier(derive_master(password, salt))


def verify_config(config: dict[str, Any] | None, password: str) -> bool:
    if not config or not config.get("encrypted"):
        return False
    try:
        salt = base64.b64decode(str(config["salt"]))
        expected = str(config["verifier"])
        return hmac.compare_digest(verifier_for(password, salt), expected)
    except (KeyError, ValueError, TypeError):
        return False


def unlock_key(config: dict[str, Any], password: str) -> str:
    if not verify_config(config, password):
        raise SecurityError("密码不正确")
    salt = base64.b64decode(str(config["salt"]))
    return derive_master(password, salt).hex()


def make_config(password: str, *, auto_lock_minutes: int = 10) -> dict[str, Any]:
    salt = new_salt()
    master = derive_master(password, salt)
    return {
        "version": CONFIG_VERSION,
        "encrypted": True,
        "salt": base64.b64encode(salt).decode("ascii"),
        "verifier": _verifier(master),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "auto_lock_minutes": max(0, int(auto_lock_minutes)),
        "lock_enabled": True,
    }


def pragma_key(key_hex: str) -> str:
    value = str(key_hex).strip()
    if len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise SecurityError("加密密钥格式不正确")
    return f"x'{value}'"


def _open_raw(path: Path):
    if sqlcipher3 is None:
        raise SecurityError("当前安装缺少 SQLCipher，无法使用数据库加密")
    conn = sqlcipher3.connect(str(path), timeout=15)
    conn.row_factory = sqlcipher3.Row
    return conn


def _quick_check_conn(conn) -> None:
    rows = conn.execute("PRAGMA quick_check").fetchall()
    problems = [str(row[0]) for row in rows if str(row[0]).lower() != "ok"]
    if problems:
        raise SecurityError("加密数据库未通过完整性检查")


def _safety_copy(path: Path, tag: str) -> Path:
    folder = path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"finboard-{stamp}-{tag}.db"
    shutil.copy2(path, target)
    return target


def encrypt_database(
    path: str | Path, password: str, *, auto_lock_minutes: int = 10
) -> dict[str, Any]:
    """Convert an ordinary SQLite database to an encrypted SQLCipher file.

    The caller must close its live ``Database`` first.  The original file is
    left untouched until the encrypted copy has been verified.
    """
    if sqlcipher3 is None:
        raise SecurityError("当前安装缺少 SQLCipher，无法启用数据库加密")
    path = Path(path).expanduser()
    if not path.is_file():
        raise SecurityError("数据库文件不存在")
    if is_encrypted_file(path):
        raise SecurityError("数据库已经加密")
    config = make_config(password, auto_lock_minutes=auto_lock_minutes)
    key = unlock_key(config, password)
    salt = base64.b64decode(str(config["salt"]))
    master = derive_master(password, salt)
    # The verifier already proves the key; use the same raw key for SQLCipher.
    key = master.hex()

    _safety_copy(path, "pre-encrypt")
    temp = path.with_name(path.name + ".encrypting")
    plain = path.with_name(path.name + ".plaincopy")
    try:
        shutil.copy2(path, plain)
        source = _open_raw(plain)
        target = path.with_name(path.name + ".encrypted")
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        source.execute(
            "ATTACH DATABASE ? AS encrypted KEY ?", (str(target), pragma_key(key))
        )
        version = int(source.execute("PRAGMA user_version").fetchone()[0])
        source.execute(f"PRAGMA encrypted.user_version = {version}")
        source.execute("SELECT sqlcipher_export('encrypted')")
        source.commit()
        source.execute("DETACH DATABASE encrypted")
        source.close()
        check = _open_raw(target)
        try:
            check.execute(f"PRAGMA key = \"{pragma_key(key)}\"")
            _quick_check_conn(check)
        finally:
            check.close()
        # Close the old connection's WAL files before swapping the main file.
        for suffix in ("-wal", "-shm"):
            try:
                path.with_name(path.name + suffix).unlink()
            except FileNotFoundError:
                pass
        os.replace(target, path)
        _write_config(path, config)
        return config
    finally:
        for candidate in (plain, temp):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


def decrypt_database(path: str | Path, password: str) -> None:
    """Convert an encrypted database back to ordinary SQLite."""
    if sqlcipher3 is None:
        raise SecurityError("当前安装缺少 SQLCipher，无法关闭数据库加密")
    path = Path(path).expanduser()
    config = load_config(path)
    key = unlock_key(config or {}, password)
    _safety_copy(path, "pre-decrypt")
    target = path.with_name(path.name + ".decrypted")
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    source = _open_raw(path)
    try:
        source.execute(f"PRAGMA key = \"{pragma_key(key)}\"")
        _quick_check_conn(source)
        source.execute("ATTACH DATABASE ? AS plain KEY ''", (str(target),))
        version = int(source.execute("PRAGMA user_version").fetchone()[0])
        source.execute(f"PRAGMA plain.user_version = {version}")
        source.execute("SELECT sqlcipher_export('plain')")
        source.commit()
        source.execute("DETACH DATABASE plain")
    finally:
        source.close()
    check = sqlite3.connect(target)
    try:
        rows = check.execute("PRAGMA quick_check").fetchall()
        if [row for row in rows if str(row[0]).lower() != "ok"]:
            raise SecurityError("解密后的数据库未通过完整性检查")
    finally:
        check.close()
    for suffix in ("-wal", "-shm"):
        try:
            path.with_name(path.name + suffix).unlink()
        except FileNotFoundError:
            pass
    os.replace(target, path)
    _remove_config(path)


def change_password(
    path: str | Path, old_password: str, new_password: str
) -> dict[str, Any]:
    """Re-encrypt a database under a new password."""
    if sqlcipher3 is None:
        raise SecurityError("当前安装缺少 SQLCipher")
    path = Path(path).expanduser()
    old_config = load_config(path)
    old_key = unlock_key(old_config or {}, old_password)
    new_config = make_config(new_password)
    new_key = derive_master(
        new_password, base64.b64decode(str(new_config["salt"]))
    ).hex()
    _safety_copy(path, "pre-rekey")
    target = path.with_name(path.name + ".rekey")
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    source = _open_raw(path)
    try:
        source.execute(f"PRAGMA key = \"{pragma_key(old_key)}\"")
        source.execute(
            "ATTACH DATABASE ? AS rekeyed KEY ?",
            (str(target), pragma_key(new_key)),
        )
        version = int(source.execute("PRAGMA user_version").fetchone()[0])
        source.execute(f"PRAGMA rekeyed.user_version = {version}")
        source.execute("SELECT sqlcipher_export('rekeyed')")
        source.commit()
        source.execute("DETACH DATABASE rekeyed")
    finally:
        source.close()
    check = _open_raw(target)
    try:
        check.execute(f"PRAGMA key = \"{pragma_key(new_key)}\"")
        _quick_check_conn(check)
    finally:
        check.close()
    os.replace(target, path)
    _write_config(path, new_config)
    return new_config
