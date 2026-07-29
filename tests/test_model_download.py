from __future__ import annotations

import unittest
from pathlib import Path

from opencoeus.model_download import (
    MODELS_DIR,
    BIN_DIR,
    PHI3_GGUF_FILENAME,
    Qwen25_GGUF_FILENAME,
    is_model_downloaded,
    is_llama_cli_downloaded,
    model_path,
    llama_cli_path,
)


class ModelDownloadTests(unittest.TestCase):

    def test_models_dir_is_under_home(self):
        self.assertTrue(str(MODELS_DIR).startswith(str(Path.home())))

    def test_bin_dir_is_under_home(self):
        self.assertTrue(str(BIN_DIR).startswith(str(Path.home())))

    def test_phi3_filename_nonempty(self):
        self.assertTrue(len(PHI3_GGUF_FILENAME) > 0)
        self.assertTrue(PHI3_GGUF_FILENAME.endswith(".gguf"))

    def test_qwen_filename_nonempty(self):
        self.assertTrue(len(Qwen25_GGUF_FILENAME) > 0)
        self.assertTrue(Qwen25_GGUF_FILENAME.endswith(".gguf"))

    def test_is_model_downloaded_returns_false_for_missing(self):
        self.assertFalse(is_model_downloaded("nonexistent-model.gguf"))

    def test_is_llama_cli_downloaded_returns_false_by_default(self):
        self.assertFalse(is_llama_cli_downloaded())

    def test_model_path_returns_models_dir_join(self):
        path = model_path("test.gguf")
        self.assertEqual(path, MODELS_DIR / "test.gguf")

    def test_llama_cli_path_returns_none_when_missing(self):
        self.assertIsNone(llama_cli_path())

    def test_filenames_are_distinct(self):
        self.assertNotEqual(PHI3_GGUF_FILENAME, Qwen25_GGUF_FILENAME)
