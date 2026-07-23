import unittest

from opencoeus.engine import ManifestRow
from opencoeus.profiles import ProfileConfig
from opencoeus.rules_engine import RulesEngine, RuleMatch


def _make_row(path: str, size: int = 100, extension: str = ".txt",
              modified_at: str = "2024-06-15T10:30:00", folder_path: str = "/docs",
              status: str = "unique") -> ManifestRow:
    # HELPER TO CREATE A MANIFEST ROW WITH SENSIBLE DEFAULTS FOR RULE TESTING.
    return ManifestRow(
        path=path, size=size, sha256="", status=status,
        relative_path=path.lstrip("/"), extension=extension,
        modified_at=modified_at, folder_path=folder_path,
    )


def _make_rule(rule_id: int = 1, name: str = "Test Rule", rule_type: str = "extension",
               rule_config: dict | None = None, destination_template: str = "/dest/{filename}",
               priority: int = 0, enabled: bool = True, action_type: str = "move") -> dict:
    # HELPER TO CREATE A RULE DICTIONARY FOR TESTING THE RULES ENGINE.
    import json
    return {
        "id": rule_id,
        "name": name,
        "rule_type": rule_type,
        "rule_config": json.dumps(rule_config or {}),
        "destination_template": destination_template,
        "priority": priority,
        "enabled": enabled,
        "action_type": action_type,
    }


class ExtensionRuleTests(unittest.TestCase):
    def test_extension_rule_matches_file(self):
        # VERIFIES THAT AN EXTENSION RULE MATCHES A FILE WITH THE SPECIFIED EXTENSION.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="extension", rule_config={"extensions": [".pdf", ".docx"]})
        row = _make_row("/doc.pdf", extension=".pdf")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].original_path, "/doc.pdf")

    def test_extension_rule_ignores_non_matching_file(self):
        # VERIFIES THAT AN EXTENSION RULE DOES NOT MATCH A FILE WITH A DIFFERENT EXTENSION.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="extension", rule_config={"extensions": [".pdf"]})
        row = _make_row("/image.png", extension=".png")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)

    def test_extension_rule_is_case_insensitive(self):
        # VERIFIES THAT EXTENSION MATCHING IS CASE INSENSITIVE.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="extension", rule_config={"extensions": [".PDF"]})
        row = _make_row("/doc.pdf", extension=".pdf")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 1)


class PatternRuleTests(unittest.TestCase):
    def test_pattern_rule_matches_filename(self):
        # VERIFIES THAT A PATTERN RULE MATCHES A FILE WHOSE NAME MATCHES THE REGEX.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="pattern", rule_config={"patterns": [r"^report_.*\.csv$"]})
        row = _make_row("/reports/report_2024.csv", extension=".csv")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 1)

    def test_pattern_rule_ignores_non_matching_filename(self):
        # VERIFIES THAT A PATTERN RULE DOES NOT MATCH A FILE WHOSE NAME DOES NOT MATCH.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="pattern", rule_config={"patterns": [r"^report_.*\.csv$"]})
        row = _make_row("/data/summary.csv", extension=".csv")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)


class DateRuleTests(unittest.TestCase):
    def test_date_rule_matches_old_file(self):
        # VERIFIES THAT A DATE RULE MATCHES A FILE OLDER THAN THE SPECIFIED NUMBER OF DAYS.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="date", rule_config={"older_than_days": 30})
        row = _make_row("/old.txt", modified_at="2020-01-01T00:00:00")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 1)

    def test_date_rule_ignores_recent_file(self):
        # VERIFIES THAT A DATE RULE DOES NOT MATCH A FILE MORE RECENT THAN THE THRESHOLD.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="date", rule_config={"older_than_days": 36500})
        row = _make_row("/new.txt", modified_at="2024-06-15T10:00:00")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)

    def test_date_rule_ignores_file_with_no_date(self):
        # VERIFIES THAT A DATE RULE SKIPS FILES WITH EMPTY MODIFIED_AT.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="date", rule_config={"older_than_days": 1})
        row = _make_row("/unknown.txt", modified_at="")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)


class SizeRuleTests(unittest.TestCase):
    def test_size_rule_matches_large_file(self):
        # VERIFIES THAT A SIZE RULE MATCHES A FILE ABOVE THE MINIMUM SIZE THRESHOLD.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="size", rule_config={"min_bytes": 1000000})
        row = _make_row("/large.bin", size=5000000)
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 1)

    def test_size_rule_ignores_small_file(self):
        # VERIFIES THAT A SIZE RULE DOES NOT MATCH A FILE BELOW THE MINIMUM SIZE THRESHOLD.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="size", rule_config={"min_bytes": 1000000})
        row = _make_row("/tiny.txt", size=100)
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)

    def test_size_rule_matches_within_range(self):
        # VERIFIES THAT A SIZE RULE WITH BOTH MIN AND MAX MATCHES FILES WITHIN THE RANGE.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="size", rule_config={"min_bytes": 100, "max_bytes": 500})
        row = _make_row("/mid.bin", size=300)
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 1)


class FolderRuleTests(unittest.TestCase):
    def test_folder_rule_matches_path(self):
        # VERIFIES THAT A FOLDER RULE MATCHES A FILE IN A FOLDER THAT SATISFIES THE PATTERN.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="folder", rule_config={"folders": [r"/downloads$"]})
        row = _make_row("/downloads/file.txt", folder_path="/downloads")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 1)

    def test_folder_rule_ignores_non_matching_path(self):
        # VERIFIES THAT A FOLDER RULE DOES NOT MATCH A FILE IN A FOLDER THAT DOES NOT SATISFY THE PATTERN.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="folder", rule_config={"folders": [r"/downloads$"]})
        row = _make_row("/documents/file.txt", folder_path="/documents")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)


class RulePriorityTests(unittest.TestCase):
    def test_higher_priority_rule_applied_first(self):
        # VERIFIES THAT THE RULE WITH THE LOWEST PRIORITY NUMBER IS APPLIED FIRST.
        engine = RulesEngine(ProfileConfig())
        low_priority = _make_rule(rule_id=1, name="Low", rule_type="extension",
                                  rule_config={"extensions": [".txt"]}, priority=10)
        high_priority = _make_rule(rule_id=2, name="High", rule_type="extension",
                                   rule_config={"extensions": [".txt"]}, priority=1)
        row = _make_row("/doc.txt", extension=".txt")
        matches = engine.evaluate([row], [low_priority, high_priority])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].rule_id, 2)

    def test_disabled_rule_is_ignored(self):
        # VERIFIES THAT A RULE WITH enabled=False IS NOT APPLIED.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="extension", rule_config={"extensions": [".txt"]}, enabled=False)
        row = _make_row("/doc.txt", extension=".txt")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)


class DestinationRenderingTests(unittest.TestCase):
    def test_destination_renders_filename(self):
        # VERIFIES THAT {filename} IN THE DESTINATION TEMPLATE IS REPLACED WITH THE ACTUAL FILENAME.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(destination_template="/dest/{filename}", rule_config={"extensions": [".pdf"]})
        row = _make_row("/src/report.pdf", extension=".pdf")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(matches[0].proposed_path, "/dest/report.pdf")

    def test_destination_renders_extension(self):
        # VERIFIES THAT {extension} IN THE DESTINATION TEMPLATE IS REPLACED WITH THE FILE EXTENSION WITHOUT DOT.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(destination_template="/dest/{extension}/{filename}", rule_config={"extensions": [".jpg"]})
        row = _make_row("/src/photo.jpg", extension=".jpg")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(matches[0].proposed_path, "/dest/jpg/photo.jpg")

    def test_destination_renders_date_year(self):
        # VERIFIES THAT {date_year} IN THE DESTINATION TEMPLATE IS REPLACED WITH THE FILE'S YEAR.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(destination_template="/archive/{date_year}/{filename}", rule_config={"extensions": [".txt"]})
        row = _make_row("/src/old.txt", extension=".txt", modified_at="2022-03-15T08:00:00")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(matches[0].proposed_path, "/archive/2022/old.txt")


class RuleMatchTests(unittest.TestCase):
    def test_rule_match_dataclass_fields(self):
        # VERIFIES THAT RuleMatch HAS ALL EXPECTED FIELDS.
        match = RuleMatch(original_path="/a", proposed_path="/b", action_type="move", rule_id=1, reason="test")
        self.assertEqual(match.original_path, "/a")
        self.assertEqual(match.proposed_path, "/b")
        self.assertEqual(match.action_type, "move")
        self.assertEqual(match.rule_id, 1)
        self.assertEqual(match.reason, "test")


class RulesEngineEdgeCaseTests(unittest.TestCase):
    def test_empty_manifest_returns_no_matches(self):
        # VERIFIES THAT AN EMPTY MANIFEST ROW LIST PRODUCES NO MATCHES.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="extension", rule_config={"extensions": [".txt"]})
        matches = engine.evaluate([], [rule])
        self.assertEqual(matches, [])

    def test_empty_rules_returns_no_matches(self):
        # VERIFIES THAT NO RULES PRODUCES NO MATCHES EVEN WITH MANIFEST ROWS.
        engine = RulesEngine(ProfileConfig())
        row = _make_row("/doc.txt", extension=".txt")
        matches = engine.evaluate([row], [])
        self.assertEqual(matches, [])

    def test_duplicate_files_are_skipped(self):
        # VERIFIES THAT DUPLICATE FILES ARE NOT EVALUATED BY THE RULES ENGINE.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="extension", rule_config={"extensions": [".txt"]})
        row = _make_row("/dup.txt", extension=".txt", status="duplicate")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)

    def test_rule_without_destination_template_produces_no_match(self):
        # VERIFIES THAT A RULE WITH AN EMPTY DESTINATION TEMPLATE PRODUCES NO MATCH.
        engine = RulesEngine(ProfileConfig())
        rule = _make_rule(rule_type="extension", rule_config={"extensions": [".txt"]}, destination_template="")
        row = _make_row("/doc.txt", extension=".txt")
        matches = engine.evaluate([row], [rule])
        self.assertEqual(len(matches), 0)

    def test_only_first_matching_rule_applied_per_file(self):
        # VERIFIES THAT ONLY THE FIRST MATCHING RULE IS APPLIED TO EACH FILE.
        engine = RulesEngine(ProfileConfig())
        rule_a = _make_rule(rule_id=1, name="A", rule_type="extension",
                            rule_config={"extensions": [".txt"]}, priority=1)
        rule_b = _make_rule(rule_id=2, name="B", rule_type="extension",
                            rule_config={"extensions": [".txt"]}, priority=2)
        row = _make_row("/doc.txt", extension=".txt")
        matches = engine.evaluate([row], [rule_a, rule_b])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].rule_id, 1)


if __name__ == "__main__":
    unittest.main()
