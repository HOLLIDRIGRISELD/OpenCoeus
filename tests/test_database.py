import tempfile
import unittest
from pathlib import Path

from opencoeus.database import AuditStore


class AuditStoreRecordTests(unittest.TestCase):
    def test_records_new_file_successfully(self):
        # VERIFIES THAT A NEW FILE CAN BE RECORDED IN THE AUDIT DATABASE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/test/file.txt", 1024, "abc123", "unique")
            # RECORDDING SHOULD NOT RAISE ANY ERRORS.
            store.close()

    def test_updates_existing_file_record(self):
        # VERIFIES THAT RECORDING THE SAME FILE PATH TWICE UPDATES THE EXISTING RECORD.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/test/file.txt", 1024, "hash1", "unique")
            store.record_file("/test/file.txt", 2048, "hash2", "duplicate")
            # THE SECOND RECORD SHOULD UPDATE, NOT CREATE A NEW ROW.
            store.close()

    def test_records_file_with_none_hash(self):
        # VERIFIES THAT A FILE CAN BE RECORDED WITH A NONE HASH VALUE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/test/protected.bin", 512, None, "protected")
            store.close()

    def test_records_multiple_files_independently(self):
        # VERIFIES THAT MULTIPLE DIFFERENT FILES ARE STORED AS SEPARATE RECORDS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/file_a.txt", 100, "hash_a", "unique")
            store.record_file("/file_b.txt", 200, "hash_b", "duplicate")
            store.record_file("/file_c.txt", 300, None, "protected")
            store.close()


class AuditStoreReserveTitleTests(unittest.TestCase):
    def test_reserves_unique_title(self):
        # VERIFIES THAT A TITLE NOT ALREADY IN THE DATABASE IS RESERVED AS-IS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            reserved = store.reserve_title("My Document Title", "/path/to/file.pdf")
            self.assertEqual(reserved, "My Document Title")
            store.close()

    def test_returns_same_title_for_same_source_path(self):
        # VERIFIES THAT REQUESTING THE SAME TITLE FOR THE SAME SOURCE RETURNS THE SAME RESULT.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            first_reservation = store.reserve_title("First Title", "/same/path.pdf")
            second_reservation = store.reserve_title("Different Title", "/same/path.pdf")
            self.assertEqual(first_reservation, second_reservation)
            self.assertEqual(first_reservation, "First Title")
            store.close()

    def test_appends_number_on_duplicate_title(self):
        # VERIFIES THAT A DUPLICATE TITLE GETS A NUMBER SUFFIX LIKE (2).
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            first_reservation = store.reserve_title("Shared Title", "/file_a.pdf")
            second_reservation = store.reserve_title("Shared Title", "/file_b.pdf")
            self.assertEqual(first_reservation, "Shared Title")
            self.assertEqual(second_reservation, "Shared Title (2)")
            store.close()

    def test_appends_incrementing_numbers(self):
        # VERIFIES THAT MULTIPLE DUPLICATE TITLES GET INCREMENTING NUMBERS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            first = store.reserve_title("Collision", "/a.pdf")
            second = store.reserve_title("Collision", "/b.pdf")
            third = store.reserve_title("Collision", "/c.pdf")
            fourth = store.reserve_title("Collision", "/d.pdf")
            self.assertEqual(first, "Collision")
            self.assertEqual(second, "Collision (2)")
            self.assertEqual(third, "Collision (3)")
            self.assertEqual(fourth, "Collision (4)")
            store.close()

    def test_different_titles_for_different_source_paths(self):
        # VERIFIES THAT DIFFERENT SOURCE PATHS CAN HAVE DIFFERENT TITLES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            title_a = store.reserve_title("Alpha Document", "/alpha.pdf")
            title_b = store.reserve_title("Beta Document", "/beta.pdf")
            self.assertEqual(title_a, "Alpha Document")
            self.assertEqual(title_b, "Beta Document")
            store.close()


class AuditStoreCloseTests(unittest.TestCase):
    def test_close_disposes_engine(self):
        # VERIFIES THAT close() DOES NOT RAISE ERRORS AND CAN BE CALLED MULTIPLE TIMES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.close()
            # DOUBLE-CLOSE SHOULD NOT RAISE.
            store.close()


if __name__ == "__main__":
    unittest.main()
