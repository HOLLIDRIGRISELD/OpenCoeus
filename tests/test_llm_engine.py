from __future__ import annotations

import unittest
from pathlib import Path

from opencoeus.content_extractor import FileSignals
from opencoeus.llm_engine import (
    LLMConfig,
    LLMEngine,
    LLMGenerationResult,
    USER_TEMPLATE,
)


class LLMEngineTests(unittest.TestCase):

    def setUp(self):
        self.engine = LLMEngine(LLMConfig(enabled=False))
        self.signals = FileSignals(
            text="Acme Corp Q3 2024 revenue report shows 20% growth.",
            file_type="document",
            extension=".pdf",
            confidence_hint=0.7,
            signals_present=["text", "metadata"],
        )

    def make_nlp_result(self, **kwargs):
        from opencoeus.nlp_engine import NLPResult
        defaults = dict(topic="", author="", organization="", project="",
                        location="", document_type="", summary="", keywords=[],
                        date="", confidence=0.0, smart_filename="", smart_destination="",
                        camera_model="", artist="", album="", nlp_generated=False, file_type="")
        defaults.update(kwargs)
        return NLPResult(**defaults)

    def test_disabled_engine_returns_noop(self):
        result = self.engine.generate(self.make_nlp_result(), self.signals)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "LLM disabled")

    def test_build_prompt_contains_signals(self):
        nlp_result = self.make_nlp_result(
            topic="Q3 Revenue",
            author="John Smith",
            organization="Acme Corp",
            date="2024-Q3",
            document_type="Report",
            keywords=["revenue", "growth", "Q3"],
        )
        prompt = self.engine._build_prompt(nlp_result, self.signals)
        self.assertIn("Acme Corp", prompt)
        self.assertIn("Q3 Revenue", prompt)
        self.assertIn("John Smith", prompt)
        self.assertIn("report", prompt)

    def test_build_prompt_contains_system_instruction(self):
        nlp_result = self.make_nlp_result()
        prompt = self.engine._build_prompt(nlp_result, self.signals)
        self.assertIn("file naming assistant", prompt)
        self.assertIn("filename", prompt)
        self.assertIn("destination", prompt)

    def test_build_prompt_truncates_long_text(self):
        long_text = "word " * 2000
        sigs = FileSignals(
            text=long_text,
            file_type="document",
            extension=".txt",
        )
        nlp_result = self.make_nlp_result()
        prompt = self.engine._build_prompt(nlp_result, sigs)
        self.assertLess(len(prompt), 10000)

    def test_parse_output_valid(self):
        raw = "FILENAME: Q3_2024_Revenue_Report\nDESTINATION: Finance/Acme_Corp/2024\n"
        result = self.engine._parse_output(raw)
        self.assertTrue(isinstance(result, LLMGenerationResult))
        self.assertEqual(result.filename, "Q3_2024_Revenue_Report")
        self.assertEqual(result.destination, "Finance/Acme_Corp/2024")

    def test_parse_output_missing_filename(self):
        raw = "DESTINATION: Some/Path\n"
        result = self.engine._parse_output(raw)
        self.assertEqual(result.filename, "")
        self.assertEqual(result.destination, "Some/Path")

    def test_parse_output_empty(self):
        result = self.engine._parse_output("")
        self.assertEqual(result.filename, "")
        self.assertEqual(result.destination, "")

    def test_parse_output_case_insensitive(self):
        raw = "filename: my_report.pdf\ndestination: docs/2024\n"
        result = self.engine._parse_output(raw)
        self.assertEqual(result.filename, "my_report.pdf")
        self.assertEqual(result.destination, "docs/2024")

    def test_parse_output_extra_text(self):
        raw = "Here is the result:\nFILENAME: Q2_Summary\nSome extra text\nDESTINATION: Reports/2024\nDone"
        result = self.engine._parse_output(raw)
        self.assertEqual(result.filename, "Q2_Summary")
        self.assertEqual(result.destination, "Reports/2024")

    def test_build_prompt_includes_metadata(self):
        sigs = FileSignals(
            text="song lyrics here",
            file_type="audio",
            extension=".mp3",
            metadata={"artist": "Queen", "album": "A Night At The Opera"},
        )
        nlp_result = self.make_nlp_result(
            artist="Queen",
            album="A Night At The Opera",
            document_type="Music",
        )
        prompt = self.engine._build_prompt(nlp_result, sigs)
        self.assertIn("Queen", prompt)
        self.assertIn("A Night At The Opera", prompt)
        self.assertIn("mp3", prompt)
        self.assertIn("audio", prompt)

    def test_build_prompt_sparse_input(self):
        sigs = FileSignals(
            text="",
            file_type="unknown",
            extension=".tmp",
        )
        nlp_result = self.make_nlp_result()
        prompt = self.engine._build_prompt(nlp_result, sigs)
        self.assertIn("unknown", prompt)
        self.assertIn("tmp", prompt)

    def test_generate_no_backend_returns_error(self):
        engine = LLMEngine(LLMConfig(enabled=True))
        result = engine.generate(self.make_nlp_result(), self.signals)
        self.assertFalse(result.success)
        self.assertIn("No LLM backend", result.error)

    def test_generate_no_model_file_returns_error(self):
        config = LLMConfig(enabled=True, model="phi3")
        engine = LLMEngine(config)
        result = engine.generate(self.make_nlp_result(), self.signals)
        self.assertFalse(result.success)

    def test_resolve_model_filename_phi3(self):
        config = LLMConfig(model="phi3")
        engine = LLMEngine(config)
        self.assertEqual(engine._resolve_model_filename(), "Phi-3-mini-4k-instruct-q4.gguf")

    def test_resolve_model_filename_qwen(self):
        config = LLMConfig(model="qwen2.5")
        engine = LLMEngine(config)
        self.assertEqual(engine._resolve_model_filename(), "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")

    def test_resolve_model_filename_custom(self):
        config = LLMConfig(model="custom-model.gguf")
        engine = LLMEngine(config)
        self.assertEqual(engine._resolve_model_filename(), "custom-model.gguf")

    def test_enabled_but_no_model_graceful(self):
        config = LLMConfig(enabled=True, model="nonexistent.gguf")
        engine = LLMEngine(config)
        result = engine.generate(self.make_nlp_result(), self.signals)
        self.assertFalse(result.success)

    def test_user_template_format_keys(self):
        keys = [
            "{file_type}", "{ext}", "{doc_type}", "{topic}", "{author}",
            "{org}", "{date}", "{keywords}", "{summary}", "{project}",
            "{location}", "{camera}", "{artist}", "{album}", "{text}",
        ]
        for key in keys:
            self.assertIn(key, USER_TEMPLATE, f"Missing key: {key}")
