import base64
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import config
import cloud_backup


class CloudBackupUnitTests(unittest.TestCase):
    def setUp(self):
        self.key = base64.urlsafe_b64encode(b"biri-go-test-key-32-bytes-long!!").decode("ascii")
        self.env = patch.dict(os.environ, {"CLOUD_BACKUP_ENCRYPTION_KEY": self.key}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def sample_snapshot(self):
        return {
            "format_version": cloud_backup.FORMAT_VERSION,
            "database": config.DB_NAME,
            "created_at": "2026-11-13T00:00:00+00:00",
            "table_count": 1,
            "row_count": 1,
            "tables": [{
                "name": "sample_table",
                "create_sql": "CREATE TABLE sample_table (id int NOT NULL)",
                "columns": ["id", "amount", "created_on", "created_at", "clock", "raw"],
                "rows": [{
                    "id": 1,
                    "amount": Decimal("12.34"),
                    "created_on": date(2026, 11, 13),
                    "created_at": datetime(2026, 11, 13, 9, 30, 0),
                    "clock": timedelta(hours=2, minutes=15),
                    "raw": b"\x00\x01\xff",
                }],
            }],
        }

    def test_blob_sdk_sync_interface_is_available(self):
        with patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "test-token"}):
            client = cloud_backup._blob()
        for method in ("put_blob", "get_blob", "query_blobs", "delete_blob", "multipart_upload_blob"):
            self.assertTrue(callable(getattr(client, method, None)), method)

    def test_encrypt_decrypt_round_trip(self):
        plain = b"backup test payload"
        self.assertEqual(cloud_backup._decrypt(cloud_backup._encrypt(plain)), plain)

    def test_archive_round_trip_and_checksum(self):
        snapshot = self.sample_snapshot()
        payload = cloud_backup._archive(snapshot)
        filename = cloud_backup._filename(payload)
        restored = cloud_backup._decode(payload, filename)
        row = restored["tables"][0]["rows"][0]
        self.assertEqual(row["amount"], "12.34")
        self.assertEqual(row["created_on"], date(2026, 11, 13))
        self.assertEqual(row["created_at"], datetime(2026, 11, 13, 9, 30))
        self.assertEqual(row["clock"], timedelta(hours=2, minutes=15))
        self.assertEqual(row["raw"], b"\x00\x01\xff")

    def test_tampered_archive_is_rejected(self):
        payload = cloud_backup._archive(self.sample_snapshot())
        filename = cloud_backup._filename(payload)
        damaged = payload[:-1] + bytes([payload[-1] ^ 1])
        with self.assertRaises(RuntimeError):
            cloud_backup._decode(damaged, filename)

    def test_wrong_key_is_rejected(self):
        payload = cloud_backup._archive(self.sample_snapshot())
        wrong = base64.urlsafe_b64encode(b"another-test-key-32-bytes-long!!").decode("ascii")
        with patch.dict(os.environ, {"CLOUD_BACKUP_ENCRYPTION_KEY": wrong}):
            with self.assertRaises(RuntimeError):
                cloud_backup._decode(payload)

    def test_manifest_mismatch_is_rejected(self):
        snapshot = self.sample_snapshot()
        snapshot["row_count"] = 2
        payload = cloud_backup._archive(snapshot)
        with self.assertRaisesRegex(RuntimeError, "row count"):
            cloud_backup._decode(payload)

    def test_archive_size_limit_is_enforced(self):
        with patch.dict(os.environ, {
            "CLOUD_BACKUP_ENCRYPTION_KEY": self.key,
            "CLOUD_BACKUP_MAX_BYTES": "1",
        }):
            with self.assertRaisesRegex(RuntimeError, "CLOUD_BACKUP_MAX_BYTES"):
                cloud_backup._archive(self.sample_snapshot())

    def test_identifier_rejects_sql_injection(self):
        with self.assertRaises(RuntimeError):
            cloud_backup._ident("employees; DROP TABLE account")

    def test_schema_normalisation_ignores_auto_increment_counter(self):
        left = "CREATE TABLE t (id int) ENGINE=InnoDB AUTO_INCREMENT=12"
        right = "CREATE TABLE t (id int) ENGINE=InnoDB AUTO_INCREMENT=900"
        self.assertEqual(
            cloud_backup._normalise_ddl(left),
            cloud_backup._normalise_ddl(right),
        )


if __name__ == "__main__":
    unittest.main()
