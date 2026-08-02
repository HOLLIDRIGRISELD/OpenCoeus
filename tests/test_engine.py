import tempfile
import unittest
from pathlib import Path

from opencoeus.config import ScanSettings
from opencoeus.db import AuditStore
from opencoeus.engine import ScanEngine


class ScanEngineTests(unittest.TestCase):
    def test_detects_duplicates_but_preserves_protected_system_folders(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root_directory = Path(temporary_directory)
            (test_root_directory / "first-copy.bin").write_bytes(b"identical file content")
            (test_root_directory / "second-copy.bin").write_bytes(b"identical file content")
            protected_directory = test_root_directory / ".opencoeus"
            protected_directory.mkdir()
            (protected_directory / "protected-copy.bin").write_bytes(b"identical file content")
            audit_store = AuditStore(f"sqlite:///{(test_root_directory / 'audit.sqlite3').as_posix()}")
            scan_result = ScanEngine(ScanSettings(test_root_directory, extract_documents=False), audit_store).run()
            file_statuses = {Path(manifest_row.path).name: manifest_row.status for manifest_row in scan_result.rows}
            self.assertEqual(file_statuses["first-copy.bin"], "unique")
            self.assertEqual(file_statuses["second-copy.bin"], "duplicate")
            self.assertEqual(file_statuses["protected-copy.bin"], "protected")
            audit_store.close()


if __name__ == "__main__":
    unittest.main()
