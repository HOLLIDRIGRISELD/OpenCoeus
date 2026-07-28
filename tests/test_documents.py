import unittest

from opencoeus.documents import suggest_title, extract_metadata, detect_document_type


class DetectDocumentTypeTests(unittest.TestCase):
    def test_detects_invoice_from_text(self):
        # VERIFIES THAT TEXT CONTAINING INVOICE KEYWORDS IS DETECTED AS INVOICE.
        text = "Invoice #INV-2024-0315\nAmount: $1,250.00\nPayment terms: Net 30"
        self.assertEqual(detect_document_type(text), "Invoice")

    def test_detects_meeting_notes(self):
        # VERIFIES THAT TEXT CONTAINING MEETING KEYWORDS IS DETECTED AS MEETING NOTES.
        text = "Meeting Notes - March 2024\nAttendees: Alice, Bob\nAgenda: Review progress"
        self.assertEqual(detect_document_type(text), "Meeting-Notes")

    def test_detects_specification(self):
        # VERIFIES THAT TEXT CONTAINING SPECIFICATION KEYWORDS IS DETECTED.
        text = "Technical Specification\nArchitecture Overview\nRequirements"
        self.assertEqual(detect_document_type(text), "Specification")

    def test_detects_report(self):
        # VERIFIES THAT TEXT CONTAINING REPORT KEYWORDS IS DETECTED.
        text = "Executive Summary\nThis report covers the quarterly analysis."
        self.assertEqual(detect_document_type(text), "Report")

    def test_detects_budget(self):
        # VERIFIES THAT TEXT CONTAINING BUDGET KEYWORDS IS DETECTED.
        text = "Budget 2024\nRevenue: $100,000\nExpenses: $75,000"
        self.assertEqual(detect_document_type(text), "Budget")

    def test_returns_document_fallback(self):
        # VERIFIES THAT TEXT WITH NO MATCHING KEYWORDS RETURNS "Document".
        text = "Random text with no specific document type keywords at all"
        self.assertEqual(detect_document_type(text), "Document")

    def test_empty_text_returns_document(self):
        # VERIFIES THAT EMPTY TEXT RETURNS THE FALLBACK "Document".
        self.assertEqual(detect_document_type(""), "Document")

    def test_metadata_also_checked(self):
        # VERIFIES THAT METADATA IS ALSO CHECKED FOR TYPE DETECTION.
        text = "Some random page content"
        metadata = {"title": "Invoice for Services", "author": "Acme Corp"}
        self.assertEqual(detect_document_type(text, metadata), "Invoice")

    def test_title_candidate_checked_first(self):
        # VERIFIES THAT THE TITLE CANDIDATE STRING IS CHECKED.
        text = "Some random body text with no keywords at all"
        title_candidate = "Meeting Minutes - Q2 Review"
        self.assertEqual(detect_document_type(text, None, title_candidate), "Meeting-Notes")


class SuggestTitleTests(unittest.TestCase):
    def test_selects_best_scored_candidate(self):
        # VERIFIES THAT THE BEST SCORED CANDIDATE IS CHOSEN BY THE SCORING ALGORITHM.
        # THE LINE CONTAINING A TITLE INDICATOR WORD SCORES HIGHEST.
        document_text = "Short\nThis is a proper document title with enough characters\nAnother line"
        result = suggest_title(document_text, "fallback")
        self.assertEqual(result, "This is a proper document title with enough characters")

    def test_prefers_mixed_case_over_all_caps(self):
        # VERIFIES THAT MIXED CASE LINES SCORE HIGHER THAN ALL CAPS LINES.
        document_text = "ALL CAPS HEADER LINE\nMixed Case Title Line"
        result = suggest_title(document_text, "fallback")
        self.assertEqual(result, "Mixed Case Title Line")

    def test_uses_fallback_when_no_candidates_found(self):
        # VERIFIES THAT THE FALLBACK TITLE IS USED WHEN NO LINE MEETS THE CRITERIA.
        document_text = "ab\n12\nx"
        result = suggest_title(document_text, "My Fallback Title")
        self.assertEqual(result, "My Fallback Title")

    def test_returns_untitled_when_no_candidates_and_no_fallback(self):
        # VERIFIES THAT 'Untitled document' IS RETURNED WHEN BOTH TEXT AND FALLBACK FAIL.
        result = suggest_title("", "")
        self.assertEqual(result, "Untitled document")

    def test_strips_unsafe_filename_characters(self):
        # VERIFIES THAT CHARACTERS UNSAFE FOR FILENAMES ARE REPLACED WITH HYPHENS.
        document_text = "Title with <special> chars: and | pipes"
        result = suggest_title(document_text, "fallback")
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)
        self.assertNotIn(":", result)
        self.assertNotIn("|", result)

    def test_truncates_long_titles_to_120_characters(self):
        # VERIFIES THAT A TITLE LONGER THAN 120 CHARACTERS IS TRUNCATED.
        long_line = "A" * 150
        result = suggest_title(long_line, "fallback")
        self.assertLessEqual(len(result), 120)

    def test_strips_leading_and_trailing_dots_and_hyphens(self):
        # VERIFIES THAT LEADING AND TRAILING DOTS AND HYPHENS ARE STRIPPED.
        document_text = "  . - Title with dots and dashes - .  "
        result = suggest_title(document_text, "fallback")
        self.assertFalse(result.startswith("."))
        self.assertFalse(result.startswith("-"))
        self.assertFalse(result.endswith("."))
        self.assertFalse(result.endswith("-"))

    def test_collapses_whitespace_in_lines(self):
        # VERIFIES THAT MULTIPLE WHITESPACE CHARACTERS ARE COLLAPSED TO SINGLE SPACES.
        document_text = "Title   with    lots    of     spaces"
        result = suggest_title(document_text, "fallback")
        self.assertNotIn("   ", result)

    def test_skips_lines_without_alpha_characters(self):
        # VERIFIES THAT LINES CONTAINING ONLY NUMBERS OR SYMBOLS ARE SKIPPED.
        document_text = "12345678\n98765432\n!!!@@@###\nThis Has Letters And Is Long Enough"
        result = suggest_title(document_text, "fallback")
        self.assertEqual(result, "This Has Letters And Is Long Enough")

    def test_skips_too_short_lines(self):
        # VERIFIES THAT LINES SHORTER THAN 8 CHARACTERS ARE NOT SELECTED.
        document_text = "ab\ncdefgh\nThis line is long enough to qualify"
        result = suggest_title(document_text, "fallback")
        self.assertEqual(result, "This line is long enough to qualify")

    def test_skips_too_long_lines(self):
        # VERIFIES THAT LINES LONGER THAN 120 CHARACTERS ARE NOT SELECTED.
        long_line = "X" * 121
        document_text = f"{long_line}\nThis is a reasonable title line"
        result = suggest_title(document_text, "fallback")
        self.assertEqual(result, "This is a reasonable title line")

    def test_empty_lines_are_ignored(self):
        # VERIFIES THAT EMPTY OR BLANK LINES DO NOT INTERFERE WITH TITLE SELECTION.
        document_text = "\n\n\n\nThis is the actual title with enough length\n\n"
        result = suggest_title(document_text, "fallback")
        self.assertEqual(result, "This is the actual title with enough length")

    def test_fallback_is_used_when_text_is_only_whitespace(self):
        # VERIFIES THAT FALLBACK IS USED WHEN DOCUMENT TEXT IS ALL WHITESPACE.
        result = suggest_title("   \n  \n  ", "My Fallback")
        self.assertEqual(result, "My Fallback")


if __name__ == "__main__":
    unittest.main()
