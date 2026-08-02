import unittest
from pathlib import Path

from opencoeus.extractors import FileSignals
from opencoeus.nlp import NLPEngine, NLPResult


class NLPEngineTests(unittest.TestCase):

    def setUp(self):
        self.engine = NLPEngine(confidence_threshold=0.6)

    def test_analyze_document_text_extracts_entities(self):
        signals = FileSignals(
            text="Acme Corporation reported a 20% increase in revenue for Q3 2024. "
                 "John Smith, the CEO, presented the findings to the board.",
            file_type="document",
            extension=".pdf",
            confidence_hint=0.7,
            signals_present=["text", "metadata"],
        )
        result = self.engine.analyze(Path("/test/report.pdf"), signals, stem="report")
        self.assertIsInstance(result, NLPResult)
        self.assertGreaterEqual(result.confidence, 0.6)
        self.assertIn(result.author, ["John Smith", "John", "Smith"])
        self.assertIn(result.organization, ["Acme Corporation", "Acme"])

    def test_analyze_image_with_metadata(self):
        signals = FileSignals(
            text="",
            file_type="image",
            extension=".jpg",
            confidence_hint=0.3,
            signals_present=["metadata"],
            metadata={
                "camera_model": "iPhone 15 Pro",
                "date_taken": "2024:07:28 14:30:00",
                "width": "4032",
                "height": "3024",
            },
        )
        result = self.engine.analyze(Path("/test/photo.jpg"), signals, stem="IMG_1234")
        self.assertEqual(result.camera_model, "iPhone 15 Pro")
        self.assertIn("2024", result.date)

    def test_analyze_audio_with_tags(self):
        signals = FileSignals(
            text="",
            file_type="audio",
            extension=".mp3",
            confidence_hint=0.4,
            signals_present=["metadata"],
            metadata={
                "artist": "Queen",
                "album": "A Night At The Opera",
                "title": "Bohemian Rhapsody",
                "duration_seconds": "354",
            },
        )
        result = self.engine.analyze(Path("/test/song.mp3"), signals, stem="track01")
        self.assertEqual(result.artist, "Queen")
        self.assertEqual(result.album, "A Night At The Opera")

    def test_analyze_installer_low_confidence(self):
        signals = FileSignals(
            text="",
            file_type="installer",
            extension=".exe",
            confidence_hint=0.1,
            signals_present=["detected_category"],
        )
        result = self.engine.analyze(Path("/test/setup.exe"), signals, stem="setup")
        self.assertLess(result.confidence, 0.6)
        self.assertFalse(result.nlp_generated)

    def test_analyze_empty_text_falls_back_gracefully(self):
        signals = FileSignals(
            text="",
            file_type="document",
            extension=".txt",
            confidence_hint=0.5,
            signals_present=[],
        )
        result = self.engine.analyze(Path("/test/empty.txt"), signals, stem="empty")
        self.assertIsInstance(result, NLPResult)
        self.assertIn("empty", result.smart_filename.lower())

    def test_document_type_classification(self):
        signals = FileSignals(
            text="INVOICE INV-2024-0315\nTotal Amount: $1,234.56\nDue Date: 2024-08-15",
            file_type="document",
            extension=".pdf",
            confidence_hint=0.7,
            signals_present=["text"],
        )
        result = self.engine.analyze(Path("/test/invoice.pdf"), signals, stem="doc")
        self.assertEqual(result.document_type, "Invoice")

    def test_keywords_extracted_from_text(self):
        signals = FileSignals(
            text="Python is a programming language. Python is used for machine learning. "
                 "Data science uses Python extensively.",
            file_type="document",
            extension=".txt",
            confidence_hint=0.7,
            signals_present=["text"],
        )
        result = self.engine.analyze(Path("/test/code.txt"), signals, stem="doc")
        self.assertIn("python", [k.lower() for k in result.keywords])

    def test_smart_filename_generated(self):
        signals = FileSignals(
            text="Report: Q4 2024 Financial Analysis by Jane Doe",
            file_type="document",
            extension=".pdf",
            confidence_hint=0.7,
            signals_present=["text"],
        )
        result = self.engine.analyze(Path("/test/report.pdf"), signals, stem="report")
        self.assertTrue(result.smart_filename.endswith(".pdf"))
        self.assertGreater(len(result.smart_filename), 5)

    def test_smart_destination_generated(self):
        signals = FileSignals(
            text="Report: Q4 2024 Financial Analysis by Acme Corp",
            file_type="document",
            extension=".pdf",
            confidence_hint=0.7,
            signals_present=["text"],
            metadata={"author": "Jane Doe", "created_date": "2024-12-15"},
        )
        result = self.engine.analyze(Path("/test/report.pdf"), signals, stem="report")
        self.assertIsInstance(result.smart_destination, str)
        self.assertGreater(len(result.smart_destination), 0)

    def test_confidence_below_threshold(self):
        self.engine.confidence_threshold = 0.9
        signals = FileSignals(
            text="Short text",
            file_type="document",
            extension=".txt",
            confidence_hint=0.3,
            signals_present=["text"],
        )
        result = self.engine.analyze(Path("/test/short.txt"), signals, stem="short")
        self.assertFalse(result.nlp_generated)

    def test_generate_filename_uses_server_style(self):
        result = NLPResult(
            topic="Q3 Revenue",
            author="John Smith",
            organization="Acme Corp",
            date="2024-03-15",
            document_type="Invoice",
        )
        name = self.engine._generate_filename(result, "scan001", ".pdf")
        self.assertEqual(name, "invoice_q3-revenue_john-smith.pdf")
        self.assertNotIn(" ", name)
        self.assertNotIn("2024", name)
        self.assertEqual(name, name.lower())

    def test_generate_filename_caps_length(self):
        result = NLPResult(
            topic="A very long topic that would otherwise create an extremely long filename",
            author="Jane Doe",
            organization="Some Very Long Organization Name",
            date="2024-03-15",
            document_type="Report",
        )
        name = self.engine._generate_filename(result, "scan001", ".pdf")
        self.assertLessEqual(len(name), 64)
        self.assertTrue(name.endswith(".pdf"))

    def test_generate_filename_keeps_stem_without_signals(self):
        # VERIFIES THAT NO RELIABLE NLP SIGNALS NEVER PRODUCE GARBAGE NAMES
        # FROM FREQUENT TOKENS OR SUMMARY FRAGMENTS (e.g. MANUAL CODES).
        result = NLPResult(
            document_type="Document",
            keywords=["stan", "rev", "c224e"],
            summary="stan rev stamped drawing",
            date="",
            topic="",
            author="",
            organization="",
            project="",
        )
        name = self.engine._generate_filename(result, "D7 EMBARKATION LADDER", ".pdf")
        self.assertEqual(name, "D7 EMBARKATION LADDER.pdf")

    def test_analyze_is_heuristic_only(self):
        engine = NLPEngine()
        signals = FileSignals(
            text="Quarterly Report Summary",
            file_type="document",
            extension=".pdf",
            confidence_hint=0.6,
            signals_present=["text"],
        )
        result = engine.analyze(Path("/test/q.pdf"), signals, stem="q")
        self.assertFalse(result.nlp_generated)


class DocumentTypeClassificationTests(unittest.TestCase):

    def setUp(self):
        self.engine = NLPEngine()

    def _classify_from_text(self, text: str) -> str:
        signals = FileSignals(text=text, file_type="document", extension=".pdf", confidence_hint=0.5)
        return self.engine.analyze(Path("/test/doc.pdf"), signals).document_type

    def test_invoice(self):
        self.assertEqual(self._classify_from_text("INVOICE INV-2024-001"), "Invoice")

    def test_meeting_notes(self):
        self.assertEqual(self._classify_from_text("Meeting Notes - Q4 Review\nAttendees: John, Jane"), "Meeting-Notes")

    def test_report(self):
        self.assertEqual(self._classify_from_text("Quarterly Report Summary"), "Report")

    def test_budget(self):
        self.assertEqual(self._classify_from_text("Budget Forecast 2025"), "Budget")

    def test_contract(self):
        self.assertEqual(self._classify_from_text("Service Agreement Contract"), "Contract")

    def test_resume(self):
        self.assertEqual(self._classify_from_text("Curriculum Vitae - John Smith"), "Resume")

    def test_letter(self):
        self.assertEqual(self._classify_from_text("Dear Mr. Smith,\nSincerely, Jane"), "Letter")

    def test_memo(self):
        self.assertEqual(self._classify_from_text("MEMORANDUM\nTO: All Staff\nFROM: Management"), "Memo")

    def test_manual(self):
        self.assertEqual(self._classify_from_text("User Guide - Installation Manual"), "Manual")

    def test_fallback_document(self):
        self.assertEqual(self._classify_from_text("Some random text content without any specific pattern"), "Document")


if __name__ == "__main__":
    unittest.main()
