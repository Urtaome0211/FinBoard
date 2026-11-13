from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard_fluent.core.backup import (
    create_backup,
    create_full_backup,
    quick_check,
    recovery_drill,
    restore_full_backup,
    verify_full_backup,
)
from finboard_fluent.core.database import Database
from finboard_fluent.core.security import (
    DatabaseLocked,
    decrypt_database,
    encrypt_database,
    is_encrypted_file,
    load_config,
    unlock_key,
    verify_config,
)


class SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.path = self.folder / "finboard.db"
        self.db = Database(self.path)
        self.account = self.db.conn.execute(
            "INSERT INTO accounts(name,type,opening_balance,note,created_at)"
            " VALUES('工资卡','debit',100000,'',datetime('now'))"
        ).lastrowid
        self.category = self.db.conn.execute("SELECT id FROM categories LIMIT 1").fetchone()[0]
        self.db.conn.execute(
            "INSERT INTO transactions(date,kind,amount,category_id,account_id,payee,created_at,updated_at)"
            " VALUES('2026-11-01','expense',1234,?,?,'午餐',datetime('now'),datetime('now'))",
            (self.category, self.account),
        )
        self.db.conn.commit()
        self.db.close()

    def tearDown(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
        self.temp.cleanup()

    def test_encrypt_decrypt_roundtrip(self) -> None:
        config = encrypt_database(self.path, "pw123456")
        self.assertTrue(is_encrypted_file(self.path))
        self.assertTrue(verify_config(config, "pw123456"))
        self.assertFalse(verify_config(config, "wrong"))
        key = unlock_key(config, "pw123456")
        db = Database(self.path, encryption_key=key)
        try:
            self.assertEqual(db.conn.execute("PRAGMA user_version").fetchone()[0], 19)
            self.assertEqual(
                db.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1
            )
            self.assertTrue(quick_check(db)[0])
            self.assertTrue(create_backup(db, reason="test").is_file())
        finally:
            db.close()
        decrypt_database(self.path, "pw123456")
        self.assertFalse(is_encrypted_file(self.path))
        self.assertFalse(load_config(self.path))
        plain = Database(self.path)
        try:
            self.assertEqual(
                plain.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1
            )
        finally:
            plain.close()

    def test_wrong_key_is_locked(self) -> None:
        config = encrypt_database(self.path, "pw123456")
        self.assertTrue(config["encrypted"])
        with self.assertRaises(DatabaseLocked):
            Database(self.path, encryption_key="00" * 32).conn
        with self.assertRaises(Exception):
            decrypt_database(self.path, "bad-password")

    def test_full_bundle_verify_restore_and_drill(self) -> None:
        attachments = self.folder / "attachments"
        attachments.mkdir()
        (attachments / "receipt.txt").write_text("hello", encoding="utf-8")
        db = Database(self.path)
        try:
            bundle = create_full_backup(db)
            self.assertEqual(bundle.suffix, ".zip")
            info = verify_full_backup(bundle)
            self.assertEqual(info["manifest"]["attachment_count"], 1)
            self.assertEqual(len(info["manifest"]["files"]), 2)
            encrypted_bundle = create_full_backup(db, password="bundle-pw")
            self.assertEqual(encrypted_bundle.suffix, ".fbk")
            with self.assertRaises(ValueError):
                verify_full_backup(encrypted_bundle, password="bad")
            self.assertTrue(verify_full_backup(encrypted_bundle, password="bundle-pw"))
            drill = recovery_drill(db)
            self.assertEqual(drill["transactions"], 1)
            db.conn.execute("DELETE FROM transactions")
            db.conn.commit()
            (attachments / "receipt.txt").unlink()
            self.db = db
            restore_full_backup(db, bundle)
            self.assertEqual(
                db.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1
            )
            self.assertTrue((attachments / "receipt.txt").is_file())
        finally:
            db.close()

    def test_full_bundle_encrypted_database(self) -> None:
        config = encrypt_database(self.path, "pw123456")
        key = unlock_key(config, "pw123456")
        db = Database(self.path, encryption_key=key)
        try:
            bundle = create_full_backup(db)
            info = verify_full_backup(bundle)
            self.assertTrue(info["encrypted"])
            self.assertIsNotNone(info["security"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
