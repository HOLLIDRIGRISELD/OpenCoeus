import unittest
import tempfile
from pathlib import Path

from opencoeus.content_extractor import extract_all, _get_category, FileSignals


class GetCategoryTests(unittest.TestCase):
    def test_installer_category(self):
        self.assertEqual(_get_category(".exe"), "installer")
        self.assertEqual(_get_category(".msi"), "installer")
        self.assertEqual(_get_category(".dmg"), "installer")

    def test_system_category(self):
        self.assertEqual(_get_category(".dll"), "system")
        self.assertEqual(_get_category(".sys"), "system")

    def test_temp_category(self):
        self.assertEqual(_get_category(".tmp"), "temp")
        self.assertEqual(_get_category(".bak"), "temp")

    def test_document_category(self):
        self.assertEqual(_get_category(".pdf"), "document")
        self.assertEqual(_get_category(".docx"), "document")
        self.assertEqual(_get_category(".txt"), "document")
        self.assertEqual(_get_category(".md"), "document")

    def test_image_category(self):
        self.assertEqual(_get_category(".jpg"), "image")
        self.assertEqual(_get_category(".png"), "image")

    def test_audio_category(self):
        self.assertEqual(_get_category(".mp3"), "audio")
        self.assertEqual(_get_category(".flac"), "audio")

    def test_video_category(self):
        self.assertEqual(_get_category(".mp4"), "video")

    def test_spreadsheet_category(self):
        self.assertEqual(_get_category(".xlsx"), "spreadsheet")
        self.assertEqual(_get_category(".csv"), "spreadsheet")

    def test_archive_category(self):
        self.assertEqual(_get_category(".zip"), "archive")
        self.assertEqual(_get_category(".tar"), "archive")

    def test_code_category(self):
        self.assertEqual(_get_category(".py"), "code")
        self.assertEqual(_get_category(".js"), "code")

    def test_unknown_category(self):
        self.assertEqual(_get_category(".xyz"), "unknown")


class ExtractAllTests(unittest.TestCase):
    def test_installer_returns_minimal(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            f.write(b"MZ\x90\x00")
            path = Path(f.name)
        try:
            result = extract_all(path)
            self.assertEqual(result.file_type, "installer")
            self.assertEqual(result.confidence_hint, 0.1)
        finally:
            path.unlink(missing_ok=True)

    def test_text_file_extracts_full_content(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("Hello world\nThis is a test file\n" * 50)
            path = Path(f.name)
        try:
            result = extract_all(path)
            self.assertIn("Hello world", result.text)
            self.assertGreater(len(result.text), 500)
            self.assertEqual(result.file_type, "document")
            self.assertGreaterEqual(result.confidence_hint, 0.9)
        finally:
            path.unlink(missing_ok=True)

    def test_code_file_extracts_imports(self):
        content = "#!/usr/bin/env python\nimport os\nimport sys\n\ndef main():\n    pass\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            path = Path(f.name)
        try:
            result = extract_all(path)
            self.assertEqual(result.file_type, "code")
            self.assertIn("import", result.text)
            self.assertGreaterEqual(result.confidence_hint, 0.6)
        finally:
            path.unlink(missing_ok=True)

    def test_csv_file_extracts_content(self):
        content = "Name,Age,City\nAlice,30,NYC\nBob,25,LA\n"
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            path = Path(f.name)
        try:
            result = extract_all(path)
            self.assertIn("Alice", result.text)
            self.assertIn("Name", result.text)
            self.assertEqual(result.file_type, "spreadsheet")
        finally:
            path.unlink(missing_ok=True)

    def test_unknown_extension_falls_back(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz", mode="w", delete=False, encoding="utf-8") as f:
            f.write("Some random content")
            path = Path(f.name)
        try:
            result = extract_all(path)
            self.assertEqual(result.file_type, "unknown")
            self.assertIn("Some random content", result.text)
        finally:
            path.unlink(missing_ok=True)

    def test_empty_file_returns_empty_signals(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = Path(f.name)
        try:
            result = extract_all(path)
            self.assertEqual(result.text, "")
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
