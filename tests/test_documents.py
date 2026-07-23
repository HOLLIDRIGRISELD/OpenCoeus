import unittest

from opencoeus.documents import suggest_title


class SuggestTitleTests(unittest.TestCase):
    def test_selects_first_candidate_line(self):
        # VERIFIES THAT THE FIRST LINE MEETING LENGTH AND ALPHA REQUIREMENTS IS CHOSEN.
        document_text = "Short\nThis is a proper document title with enough characters\nAnother line"
        result = suggest_title(document_text, "fallback")
        self.assertEqual(result, "This is a proper document title with enough characters")

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
        # VERIFIES THAT LINES LONGER THAN 100 CHARACTERS ARE NOT SELECTED.
        long_line = "X" * 101
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
