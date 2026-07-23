import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opencoeus.cli import main


class CliTests(unittest.TestCase):
    def test_scan_command_creates_manifest_file(self):
        # VERIFIES THAT THE CLI SCAN COMMAND CREATES A CSV MANIFEST FILE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            (test_root / "file.txt").write_text("test content")
            output_path = test_root / "output.csv"
            with patch("sys.argv", ["opencoeus", "scan", str(test_root), "--output", str(output_path)]):
                exit_code = main()
            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())

    def test_scan_command_returns_zero(self):
        # VERIFIES THAT THE CLI RETURNS EXIT CODE 0 ON SUCCESS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            output_path = test_root / "manifest.csv"
            with patch("sys.argv", ["opencoeus", "scan", str(test_root), "--output", str(output_path)]):
                exit_code = main()
            self.assertEqual(exit_code, 0)

    def test_scan_with_no_document_text_flag(self):
        # VERIFIES THAT THE --no-document-text FLAG IS ACCEPTED AND WORKS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            (test_root / "file.txt").write_text("content")
            output_path = test_root / "output.csv"
            with patch("sys.argv", ["opencoeus", "scan", str(test_root), "--output", str(output_path), "--no-document-text"]):
                exit_code = main()
            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())

    def test_scan_empty_directory_creates_empty_manifest(self):
        # VERIFIES THAT SCANNING AN EMPTY DIRECTORY CREATES A MANIFEST WITH ONLY HEADERS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            output_path = test_root / "empty_manifest.csv"
            with patch("sys.argv", ["opencoeus", "scan", str(test_root), "--output", str(output_path)]):
                exit_code = main()
            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            with output_path.open(encoding="utf-8-sig") as csv_file:
                lines = csv_file.readlines()
            # ONLY THE HEADER LINE SHOULD BE PRESENT.
            self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
