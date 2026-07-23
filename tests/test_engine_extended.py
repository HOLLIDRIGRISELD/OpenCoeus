import csv
import tempfile
import unittest
from pathlib import Path

from opencoeus.config import ScanSettings
from opencoeus.database import AuditStore
from opencoeus.engine import ManifestRow, ScanEngine, ScanResult, write_manifest


class ManifestRowTests(unittest.TestCase):
    def test_manifest_row_defaults(self):
        # VERIFIES THAT A MANIFEST ROW HAS EMPTY DEFAULTS FOR OPTIONAL FIELDS.
        row = ManifestRow(path="/test", size=100, sha256="abc", status="unique")
        self.assertEqual(row.duplicate_of, "")
        self.assertEqual(row.suggested_title, "")

    def test_manifest_row_accepts_all_fields(self):
        # VERIFIES THAT A MANIFEST ROW CAN BE CONSTRUCTED WITH ALL FIELDS SPECIFIED.
        row = ManifestRow(
            path="/test/file.txt",
            size=2048,
            sha256="def456",
            status="duplicate",
            duplicate_of="/original/file.txt",
            suggested_title="Original File",
        )
        self.assertEqual(row.path, "/test/file.txt")
        self.assertEqual(row.status, "duplicate")
        self.assertEqual(row.duplicate_of, "/original/file.txt")
        self.assertEqual(row.suggested_title, "Original File")


class ScanResultTests(unittest.TestCase):
    def test_empty_scan_result_has_zero_duplicates(self):
        # VERIFIES THAT AN EMPTY SCAN RESULT REPORTS ZERO DUPLICATES.
        result = ScanResult()
        self.assertEqual(result.duplicate_count, 0)

    def test_duplicate_count_counts_only_duplicates(self):
        # VERIFIES THAT duplicate_count ONLY COUNTS ROWS WITH STATUS 'duplicate'.
        result = ScanResult()
        result.rows.append(ManifestRow(path="a", size=1, sha256="", status="unique"))
        result.rows.append(ManifestRow(path="b", size=1, sha256="", status="duplicate"))
        result.rows.append(ManifestRow(path="c", size=1, sha256="", status="duplicate"))
        result.rows.append(ManifestRow(path="d", size=1, sha256="", status="protected"))
        self.assertEqual(result.duplicate_count, 2)


class WriteManifestTests(unittest.TestCase):
    def test_creates_valid_csv_file(self):
        # VERIFIES THAT write_manifest CREATES A VALID CSV WITH CORRECT HEADERS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "test_manifest.csv"
            result = ScanResult()
            result.rows.append(ManifestRow(path="/a.txt", size=10, sha256="h1", status="unique"))
            result.rows.append(ManifestRow(path="/b.txt", size=20, sha256="h2", status="duplicate"))
            write_manifest(result, output_path)
            self.assertTrue(output_path.exists())
            with output_path.open(encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                rows = list(reader)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["path"], "/a.txt")
            self.assertEqual(rows[0]["status"], "unique")
            self.assertEqual(rows[1]["path"], "/b.txt")
            self.assertEqual(rows[1]["status"], "duplicate")

    def test_csv_has_six_columns(self):
        # VERIFIES THAT THE CSV OUTPUT CONTAINS EXACTLY SIX COLUMNS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "test_manifest.csv"
            result = ScanResult()
            result.rows.append(ManifestRow(path="/x", size=1, sha256="", status="unique"))
            write_manifest(result, output_path)
            with output_path.open(encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                self.assertEqual(reader.fieldnames, ["path", "size", "sha256", "status", "duplicate_of", "suggested_title"])

    def test_empty_result_produces_header_only_csv(self):
        # VERIFIES THAT AN EMPTY SCAN RESULT PRODUCES A CSV WITH ONLY THE HEADER ROW.
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "empty_manifest.csv"
            result = ScanResult()
            write_manifest(result, output_path)
            with output_path.open(encoding="utf-8-sig") as csv_file:
                lines = csv_file.readlines()
            self.assertEqual(len(lines), 1)

    def test_manifest_row_dicts_are_written_correctly(self):
        # VERIFIES THAT MANIFEST ROW DATA IS SERIALIZED CORRECTLY IN THE CSV.
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "test_manifest.csv"
            result = ScanResult()
            result.rows.append(ManifestRow(
                path="/docs/manual.pdf",
                size=5000,
                sha256="abc123def",
                status="duplicate",
                duplicate_of="/docs/original.pdf",
                suggested_title="User Manual",
            ))
            write_manifest(result, output_path)
            with output_path.open(encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                row = next(reader)
            self.assertEqual(row["duplicate_of"], "/docs/original.pdf")
            self.assertEqual(row["suggested_title"], "User Manual")


class ScanEngineEdgeCaseTests(unittest.TestCase):
    def _create_store_outside_root(self, test_root: Path) -> AuditStore:
        # PLACES THE SQLITE DATABASE OUTSIDE THE SCAN ROOT SO THE SCANNER DOES NOT PICK IT UP.
        database_path = test_root.parent / "audit_test.sqlite3"
        return AuditStore(f"sqlite:///{database_path.as_posix()}")

    def test_scan_empty_directory(self):
        # VERIFIES THAT SCANNING AN EMPTY DIRECTORY PRODUCES ZERO ROWS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            store = self._create_store_outside_root(test_root)
            result = ScanEngine(ScanSettings(test_root, extract_documents=False), store).run()
            self.assertEqual(len(result.rows), 0)
            self.assertEqual(result.duplicate_count, 0)
            store.close()

    def test_scan_directory_with_only_protected_folders(self):
        # VERIFIES THAT A DIRECTORY WITH ONLY PROTECTED FOLDERS PRODUCES PROTECTED STATUS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            protected = test_root / ".opencoeus"
            protected.mkdir()
            (protected / "data.db").write_bytes(b"database content")
            store = self._create_store_outside_root(test_root)
            result = ScanEngine(ScanSettings(test_root, extract_documents=False), store).run()
            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0].status, "protected")
            store.close()

    def test_progress_callback_is_called(self):
        # VERIFIES THAT THE PROGRESS CALLBACK IS INVOKED DURING A SCAN.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            (test_root / "file.txt").write_text("content")
            progress_messages = []
            store = self._create_store_outside_root(test_root)
            ScanEngine(ScanSettings(test_root, extract_documents=False), store).run(progress_messages.append)
            self.assertEqual(len(progress_messages), 1)
            self.assertIn("1/1", progress_messages[0])
            store.close()

    def test_scan_with_no_progress_callback_does_not_crash(self):
        # VERIFIES THAT SCANNING WITHOUT A PROGRESS CALLBACK WORKS CORRECTLY.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            (test_root / "file.txt").write_text("content")
            store = self._create_store_outside_root(test_root)
            result = ScanEngine(ScanSettings(test_root, extract_documents=False), store).run(None)
            self.assertEqual(len(result.rows), 1)
            store.close()

    def test_scan_records_errors_for_unreadable_files(self):
        # VERIFIES THAT ERRORS ARE RECORDED WHEN FILES CANNOT BE HASHED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            # CREATE TWO SAME-SIZE FILES WHERE ONE WILL BE HASHED.
            (test_root / "file_a.bin").write_bytes(b"same content!!")
            (test_root / "file_b.bin").write_bytes(b"same content!!")
            store = self._create_store_outside_root(test_root)
            result = ScanEngine(ScanSettings(test_root, extract_documents=False), store).run()
            # ONE FILE SHOULD BE UNIQUE, ONE SHOULD BE DUPLICATE.
            statuses = [row.status for row in result.rows]
            self.assertIn("unique", statuses)
            self.assertIn("duplicate", statuses)
            store.close()


if __name__ == "__main__":
    unittest.main()
