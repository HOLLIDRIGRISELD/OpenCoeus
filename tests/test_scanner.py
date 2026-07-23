import tempfile
import unittest
from pathlib import Path

from opencoeus.scanner import FileRecord, iter_files


class ScannerBasicTests(unittest.TestCase):
    def test_finds_regular_files_in_flat_directory(self):
        # SETS UP A SIMPLE DIRECTORY WITH TWO FILES AND VERIFIES BOTH ARE FOUND.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            (test_root / "alpha.txt").write_text("hello")
            (test_root / "beta.bin").write_bytes(b"\x00\x01\x02")
            discovered_files = list(iter_files(test_root))
            discovered_names = {record.path.name for record in discovered_files}
            self.assertEqual(discovered_names, {"alpha.txt", "beta.bin"})

    def test_returns_correct_file_sizes(self):
        # VERIFIES THAT EACH FILE RECORD CONTAINS THE EXACT BYTE SIZE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            (test_root / "small.txt").write_text("ab")
            (test_root / "large.bin").write_bytes(b"\xff" * 1000)
            discovered_files = list(iter_files(test_root))
            size_by_name = {record.path.name: record.size for record in discovered_files}
            self.assertEqual(size_by_name["small.txt"], 2)
            self.assertEqual(size_by_name["large.bin"], 1000)

    def test_recurses_into_subdirectories(self):
        # VERIFIES THAT FILES IN NESTED SUBDIRECTORIES ARE DISCOVERED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            nested_directory = test_root / "level1" / "level2" / "level3"
            nested_directory.mkdir(parents=True)
            (nested_directory / "deep_file.txt").write_text("buried")
            (test_root / "shallow_file.txt").write_text("surface")
            discovered_files = list(iter_files(test_root))
            discovered_names = {record.path.name for record in discovered_files}
            self.assertEqual(discovered_names, {"deep_file.txt", "shallow_file.txt"})

    def test_skips_symbolic_links(self):
        # VERIFIES THAT SYMBOLIC LINKS ARE NOT YIELDED AS FILES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            real_file = test_root / "real.txt"
            real_file.write_text("actual content")
            symlink_path = test_root / "link.txt"
            try:
                symlink_path.symlink_to(real_file)
            except OSError:
                # SOME WINDOWS ENVIRONMENTS REQUIRE ELEVATED PRIVILEGES FOR SYMLINKS.
                self.skipTest("Symlink creation not supported on this system")
            discovered_files = list(iter_files(test_root))
            discovered_names = {record.path.name for record in discovered_files}
            # ONLY THE REAL FILE SHOULD APPEAR, NOT THE SYMLINK.
            self.assertIn("real.txt", discovered_names)
            self.assertNotIn("link.txt", discovered_names)

    def test_empty_directory_yields_nothing(self):
        # VERIFIES THAT AN EMPTY DIRECTORY PRODUCES ZERO FILE RECORDS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            discovered_files = list(iter_files(test_root))
            self.assertEqual(discovered_files, [])

    def test_empty_root_directory_yields_nothing(self):
        # VERIFIES THAT A NONEXISTENT ROOT PRODUCES ZERO RECORDS AND REPORTS AN ERROR.
        non_existent_path = Path("C:\\nonexistent_folder_12345")
        errors = []
        discovered_files = list(iter_files(non_existent_path, errors.append))
        self.assertEqual(discovered_files, [])
        self.assertTrue(len(errors) > 0)

    def test_error_callback_reports_unreadable_directories(self):
        # VERIFIES THAT THE ERROR CALLBACK IS INVOKED WHEN A DIRECTORY CANNOT BE READ.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            readable = test_root / "readable"
            readable.mkdir()
            (readable / "file.txt").write_text("content")
            errors = []
            discovered_files = list(iter_files(test_root, errors.append))
            discovered_names = {record.path.name for record in discovered_files}
            self.assertIn("file.txt", discovered_names)

    def test_skips_broken_symlinks_without_crashing(self):
        # VERIFIES THAT BROKEN SYMBOLIC LINKS ARE SILENTLY SKIPPED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            (test_root / "real.txt").write_text("content")
            broken_link = test_root / "broken_link.txt"
            try:
                broken_link.symlink_to("C:\\nonexistent_target_12345")
            except OSError:
                self.skipTest("Symlink creation not supported on this system")
            errors = []
            discovered_files = list(iter_files(test_root, errors.append))
            # SHOULD FIND THE REAL FILE AND NOT CRASH ON THE BROKEN LINK.
            discovered_names = {record.path.name for record in discovered_files}
            self.assertIn("real.txt", discovered_names)
            self.assertNotIn("broken_link.txt", discovered_names)

    def test_handles_mixed_file_extensions(self):
        # VERIFIES THAT FILES WITH VARIOUS EXTENSIONS ARE ALL DISCOVERED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            (test_root / "report.txt").write_text("text content")
            (test_root / "image.png").write_bytes(b"\x89PNG")
            (test_root / "data.csv").write_text("col1,col2\n1,2")
            sub_directory = test_root / "subfolder"
            sub_directory.mkdir()
            (sub_directory / "nested.txt").write_text("nested content")
            discovered_files = list(iter_files(test_root))
            discovered_names = {record.path.name for record in discovered_files}
            self.assertEqual(discovered_names, {"report.txt", "image.png", "data.csv", "nested.txt"})


if __name__ == "__main__":
    unittest.main()
