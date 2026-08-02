from __future__ import annotations

import unittest

from opencoeus.engine import ManifestRow
from opencoeus.llm import LLMConfig
from opencoeus.llm.refine import (
    RefineEngine,
    _sanitize_filename,
    _sanitize_subfolder,
)
from opencoeus.llm.result import LLMGenerationResult
from opencoeus.rules import RuleMatch


def _make_row(path: str, extension: str = ".pdf", **kwargs) -> ManifestRow:
    defaults = dict(
        size=100, sha256="", status="unique",
        relative_path=path.lstrip("/"), extension=extension,
        modified_at="2024-06-15T10:30:00", folder_path=str(path).rsplit("/", 1)[0],
        doc_type="Invoice",
    )
    defaults.update(kwargs)
    return ManifestRow(path=path, **defaults)


def _make_match(original: str, proposed: str, action: str = "move") -> RuleMatch:
    return RuleMatch(
        original_path=original,
        proposed_path=proposed,
        action_type=action,
        rule_id=1,
        reason="Matched rule 'Documents' (extension)",
        original_filename=original.rsplit("/", 1)[-1],
        new_filename=proposed.rsplit("/", 1)[-1],
    )


class _FakeLLM:

    def __init__(self, *responses):
        self.config = LLMConfig(enabled=True)
        self._responses = list(responses)
        self._calls = []

    def complete(self, user_text, max_tokens=None, system_prompt=None):
        self._calls.append((user_text, max_tokens))
        raw = self._responses.pop(0) if self._responses else ""
        return LLMGenerationResult(raw_output=raw, success=bool(raw.strip()))


class SanitizeTests(unittest.TestCase):

    def test_filename_strips_extension_and_invalid_chars(self):
        self.assertEqual(
            _sanitize_filename("2024-03-15/Invoice:Q3", ".pdf"),
            "2024-03-15_invoice_q3.pdf",
        )

    def test_filename_removes_model_extension(self):
        self.assertEqual(
            _sanitize_filename("Acme_Corp_Invoice.PDF", ".pdf"),
            "acme_corp_invoice.pdf",
        )

    def test_filename_is_lowercase(self):
        name = _sanitize_filename("Acme_Corp_Q2_Roadmap_Meeting_Notes", ".pdf")
        self.assertEqual(name, "acme_corp_q2_roadmap_meeting_notes.pdf")

    def test_filename_caps_stem_at_60(self):
        name = _sanitize_filename("A" * 100, ".pdf")
        self.assertTrue(name.endswith(".pdf"))
        self.assertEqual(len(name), 64)

    def test_filename_empty_returns_empty(self):
        self.assertEqual(_sanitize_filename("", ".pdf"), "")
        self.assertEqual(_sanitize_filename("...___", ".pdf"), "")

    def test_subfolder_normalizes_separators_and_traversal(self):
        self.assertEqual(
            _sanitize_subfolder(r"Clients\Acme Corp\\2024\Invoices"),
            "Clients/Acme Corp/2024/Invoices",
        )
        self.assertEqual(_sanitize_subfolder("../Clients/../Acme/"), "Clients/Acme")


class BatchParseTests(unittest.TestCase):

    def test_parses_json_array(self):
        raw = (
            '[{"index":0,"filename":"A_Report","subfolder":"Clients/Acme/2024"},'
            '{"index":1,"filename":"B_Budget","subfolder":"Finance/2024"}]'
        )
        parsed = RefineEngine._parse_batch_output(raw)
        self.assertEqual(parsed[0], ("A_Report", "Clients/Acme/2024"))
        self.assertEqual(parsed[1], ("B_Budget", "Finance/2024"))

    def test_parses_single_object(self):
        raw = '{"filename":"A_Report","subfolder":"Clients/Acme/2024"}'
        parsed = RefineEngine._parse_batch_output(raw)
        self.assertEqual(parsed[0], ("A_Report", "Clients/Acme/2024"))

    def test_garbage_returns_empty(self):
        self.assertEqual(RefineEngine._parse_batch_output("I have no idea"), {})
        self.assertEqual(RefineEngine._parse_batch_output('[{"index":"x"}]'), {})
        self.assertEqual(RefineEngine._parse_batch_output(""), {})


class RefineBatchTests(unittest.TestCase):

    def test_refines_all_matches_in_batch(self):
        fake = _FakeLLM(
            '[{"index":0,"filename":"2024-03-15_Acme_Corp_Invoice","subfolder":"Clients/Acme Corp/2024/Invoices"},'
            '{"index":1,"filename":"Q2_2024_Budget","subfolder":"Finance/Budget/2024"}]'
        )
        engine = RefineEngine(fake, scan_root="/root")
        row0 = _make_row("/root/report.pdf", doc_type="Invoice")
        row1 = _make_row("/root/budget.pdf", doc_type="Budget")
        match0 = _make_match("/root/report.pdf", "/root/Documents/report.pdf")
        match1 = _make_match("/root/budget.pdf", "/root/Documents/budget.pdf")
        engine.refine_matches([(match0, row0), (match1, row1)])

        self.assertEqual(
            match0.proposed_path,
            "/root/Documents/Clients/Acme Corp/2024/Invoices/2024-03-15_acme_corp_invoice.pdf",
        )
        self.assertEqual(match0.new_filename, "2024-03-15_acme_corp_invoice.pdf")
        self.assertEqual(match0.action_type, "move+rename")
        self.assertIn("Refined", match0.reason)
        self.assertEqual(
            match1.proposed_path,
            "/root/Documents/Finance/Budget/2024/q2_2024_budget.pdf",
        )

    def test_strips_base_folder_repeat_from_subfolder(self):
        fake = _FakeLLM(
            '[{"index":0,"filename":"Acme_Report","subfolder":"Documents/Clients/Acme/2024"}]'
        )
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row("/root/report.pdf")
        match = _make_match("/root/report.pdf", "/root/Documents/report.pdf")
        engine.refine_matches([(match, row)])
        self.assertEqual(
            match.proposed_path,
            "/root/Documents/Clients/Acme/2024/acme_report.pdf",
        )

    def test_rename_match_with_subfolder_becomes_move_rename(self):
        fake = _FakeLLM(
            '[{"index":0,"filename":"Acme_Report","subfolder":"Clients/Acme/2024"}]'
        )
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row("/root/inbox/report.pdf")
        match = _make_match(
            "/root/inbox/report.pdf", "/root/inbox/Acme_Report.pdf", action="rename"
        )
        engine.refine_matches([(match, row)])
        self.assertEqual(match.action_type, "move+rename")
        self.assertEqual(
            match.proposed_path,
            "/root/inbox/Clients/Acme/2024/acme_report.pdf",
        )

    def test_rename_match_without_subfolder_stays_rename(self):
        fake = _FakeLLM('[{"index":0,"filename":"Acme_Report","subfolder":""}]')
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row("/root/inbox/report.pdf")
        match = _make_match(
            "/root/inbox/report.pdf", "/root/inbox/Old_Name.pdf", action="rename"
        )
        engine.refine_matches([(match, row)])
        self.assertEqual(match.action_type, "rename")
        self.assertEqual(match.proposed_path, "/root/inbox/acme_report.pdf")

    def test_empty_response_falls_back_to_heuristic(self):
        fake = _FakeLLM("")
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row(
            "/root/report.pdf",
            smart_filename="2024-06-15_Report_Acme.pdf",
            smart_destination="Report/Acme/2024",
        )
        match = _make_match("/root/report.pdf", "/root/Documents/report.pdf")
        engine.refine_matches([(match, row)])
        self.assertEqual(
            match.proposed_path,
            "/root/Documents/Report/Acme/2024/2024-06-15_report_acme.pdf",
        )
        self.assertEqual(match.action_type, "move+rename")

    def test_heuristic_fallback_strips_base_prefix(self):
        fake = _FakeLLM("")
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row(
            "/root/report.pdf",
            smart_filename="2024-06-15_Report.pdf",
            smart_destination="Documents/Acme/2024",
        )
        match = _make_match("/root/report.pdf", "/root/Documents/report.pdf")
        engine.refine_matches([(match, row)])
        self.assertEqual(
            match.proposed_path,
            "/root/Documents/Acme/2024/2024-06-15_report.pdf",
        )

    def test_no_change_keeps_rule_result(self):
        fake = _FakeLLM('[{"index":0,"filename":"report.pdf","subfolder":""}]')
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row("/root/report.pdf")
        match = _make_match("/root/report.pdf", "/root/Documents/report.pdf")
        engine.refine_matches([(match, row)])
        self.assertEqual(match.proposed_path, "/root/Documents/report.pdf")
        self.assertEqual(match.action_type, "move")
        self.assertNotIn("Refined", match.reason)

    def test_batching_respects_batch_size(self):
        fake = _FakeLLM('[{"index":0,"filename":"A.pdf","subfolder":""}]',
                        '[{"index":0,"filename":"B.pdf","subfolder":""}]')
        fake.config.batch_size = 1
        engine = RefineEngine(fake, scan_root="/root")
        row0 = _make_row("/root/a.pdf")
        row1 = _make_row("/root/b.pdf")
        match0 = _make_match("/root/a.pdf", "/root/Documents/a.pdf")
        match1 = _make_match("/root/b.pdf", "/root/Documents/b.pdf")
        engine.refine_matches([(match0, row0), (match1, row1)])
        self.assertEqual(len(fake._calls), 2)
        self.assertEqual(match0.new_filename, "a.pdf")
        self.assertEqual(match1.new_filename, "b.pdf")

    def test_locked_pairs_keep_folder_and_only_refine_filename(self):
        # VERIFIES THAT ALREADY-GROUPED DOCUMENT BATCHES KEEP THEIR SHARED FOLDER;
        # THE LLM MAY REFINE FILENAMES BUT NEVER SCATTERS THE BATCH INTO SUBFOLDERS.
        fake = _FakeLLM(
            '[{"index":0,"filename":"E2_Lifeboat_Manual","subfolder":"Scattered/Other/2024"},'
            '{"index":1,"filename":"E2_Rescue_Plan","subfolder":"Scattered/Other/2024"}]'
        )
        engine = RefineEngine(fake, scan_root="/root")
        row0 = _make_row("/root/E2 LIFEBOAT/E2-1.pdf", doc_type="Specification", smart_filename="e2-1.pdf")
        row1 = _make_row("/root/E2 LIFEBOAT/E2-2.pdf", doc_type="Specification", smart_filename="e2-2.pdf")
        match0 = _make_match(
            "/root/E2 LIFEBOAT/E2-1.pdf",
            "/root/Documents/specification/e2-lifeboat/e2-1.pdf",
            action="move+rename",
        )
        match1 = _make_match(
            "/root/E2 LIFEBOAT/E2-2.pdf",
            "/root/Documents/specification/e2-lifeboat/e2-2.pdf",
            action="move+rename",
        )
        engine.refine_matches([], locked_pairs=[(match0, row0), (match1, row1)])
        self.assertEqual(
            match0.proposed_path,
            "/root/Documents/specification/e2-lifeboat/e2_lifeboat_manual.pdf",
        )
        self.assertEqual(
            match1.proposed_path,
            "/root/Documents/specification/e2-lifeboat/e2_rescue_plan.pdf",
        )

    def test_locked_fallback_keeps_batch_folder(self):
        # VERIFIES THE HEURISTIC FALLBACK DOES NOT RE-APPLY THE PER-FILE SMART
        # DESTINATION ON ALREADY-GROUPED (LOCKED) BATCH MEMBERS.
        fake = _FakeLLM("")
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row(
            "/root/E2 LIFEBOAT/E2-1.pdf", doc_type="Specification",
            smart_filename="e2-1.pdf", smart_destination="Specification/DECK/2024",
        )
        match = _make_match(
            "/root/E2 LIFEBOAT/E2-1.pdf",
            "/root/Documents/specification/e2-lifeboat/e2-1.pdf",
            action="move+rename",
        )
        engine.refine_matches([], locked_pairs=[(match, row)])
        self.assertEqual(
            match.proposed_path,
            "/root/Documents/specification/e2-lifeboat/e2-1.pdf",
        )


class NoRenameTests(unittest.TestCase):

    def test_code_file_skips_llm_and_keeps_name(self):
        fake = _FakeLLM('[{"index":0,"filename":"db_init.py","subfolder":"crm/db"}]')
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row("/root/db_init.py", extension=".py")
        match = _make_match("/root/db_init.py", "/root/Code/db_init.py", action="move")
        engine.refine_matches([(match, row)])
        self.assertEqual(fake._calls, [])
        self.assertEqual(match.proposed_path, "/root/Code/db_init.py")
        self.assertEqual(match.new_filename, "db_init.py")
        self.assertEqual(match.action_type, "move")
        self.assertIn("Preserved server file name", match.reason)

    def test_rename_match_reset_to_original_name(self):
        fake = _FakeLLM("")
        engine = RefineEngine(fake, scan_root="/root")
        row = _make_row("/root/server.yaml", extension=".yaml")
        match = _make_match(
            "/root/server.yaml", "/root/Config/server_config.yaml", action="rename"
        )
        engine.refine_matches([(match, row)])
        self.assertEqual(fake._calls, [])
        self.assertEqual(match.proposed_path, "/root/Config/server.yaml")
        self.assertEqual(match.new_filename, "server.yaml")
        self.assertEqual(match.action_type, "move")
        self.assertIn("Preserved server file name", match.reason)

    def test_mixed_batch_only_keeps_code_file(self):
        fake = _FakeLLM(
            '[{"index":0,"filename":"2024-06-15_acme-invoice","subfolder":"Clients/Acme/2024"}]'
        )
        engine = RefineEngine(fake, scan_root="/root")
        code_row = _make_row("/root/app.py", extension=".py")
        doc_row = _make_row("/root/report.pdf")
        code_match = _make_match("/root/app.py", "/root/Code/app.py", action="rename")
        doc_match = _make_match("/root/report.pdf", "/root/Documents/report.pdf")
        engine.refine_matches([(code_match, code_row), (doc_match, doc_row)])
        self.assertEqual(len(fake._calls), 1)
        self.assertEqual(code_match.proposed_path, "/root/Code/app.py")
        self.assertEqual(
            doc_match.proposed_path,
            "/root/Documents/Clients/Acme/2024/2024-06-15_acme-invoice.pdf",
        )
        self.assertEqual(doc_match.action_type, "move+rename")


if __name__ == "__main__":
    unittest.main()
