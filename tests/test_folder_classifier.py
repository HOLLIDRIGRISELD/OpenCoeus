import tempfile
import unittest
from pathlib import Path

from opencoeus.folder_tree import FolderNode, build_folder_tree
from opencoeus.folder_classifier import classify_folder, classify_tree
from opencoeus.config import default_protected_patterns


def _make_node(name: str, is_protected: bool = False) -> FolderNode:
    # HELPER TO CREATE A STANDALONE FOLDER NODE FOR UNIT TESTING CLASSIFY_FOLDER.
    return FolderNode(name=name, path=Path(f"/{name}"), depth=0, is_protected=is_protected)


class ClassifyFolderTests(unittest.TestCase):
    def test_classifies_node_modules_as_package_dependencies(self):
        # VERIFIES THAT A FOLDER NAMED node_modules IS CLASSIFIED AS package_dependencies.
        node = _make_node("node_modules")
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "package_dependencies")
        self.assertEqual(action, "exclude")
        self.assertIn("node_modules", reason)

    def test_classifies_venv_as_virtual_environment(self):
        # VERIFIES THAT A FOLDER NAMED venv IS CLASSIFIED AS virtual_environment.
        node = _make_node("venv")
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "virtual_environment")
        self.assertEqual(action, "exclude")
        self.assertIn("venv", reason)

    def test_classifies_git_as_version_control(self):
        # VERIFIES THAT A FOLDER NAMED .git IS CLASSIFIED AS version_control.
        node = _make_node(".git")
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "version_control")
        self.assertEqual(action, "exclude")

    def test_classifies_steam_as_game_library(self):
        # VERIFIES THAT A FOLDER NAMED Steam IS CLASSIFIED AS game_library.
        node = _make_node("Steam")
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "game_library")
        self.assertEqual(action, "exclude")

    def test_classifies_windows_as_system(self):
        # VERIFIES THAT A FOLDER NAMED Windows IS CLASSIFIED AS system.
        node = _make_node("Windows")
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "system")
        self.assertEqual(action, "exclude")

    def test_classifies_src_as_source_code(self):
        # VERIFIES THAT A FOLDER NAMED src IS CLASSIFIED AS source_code WITH ask_user ACTION.
        node = _make_node("src")
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "source_code")
        self.assertEqual(action, "ask_user")

    def test_classifies_unknown_folder_as_unknown(self):
        # VERIFIES THAT AN UNRECOGNIZED FOLDER NAME IS CLASSIFIED AS unknown WITH ask_user ACTION.
        node = _make_node("MyRandomFolder")
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "unknown")
        self.assertEqual(action, "ask_user")

    def test_protected_folder_defaults_to_system_exclude(self):
        # VERIFIES THAT A PROTECTED FOLDER WITH NO SPECIFIC MATCH DEFAULTS TO system EXCLUDE.
        node = _make_node("SystemVolumeInfo", is_protected=True)
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "system")
        self.assertEqual(action, "exclude")
        self.assertIn("protected", reason)

    def test_custom_patterns_are_applied(self):
        # VERIFIES THAT USER-PROVIDED CUSTOM PATTERNS ARE USED FOR CLASSIFICATION.
        node = _make_node("my_special_dir")
        classification, action, reason = classify_folder(node, custom_patterns=[r"^my_special_dir$"])
        self.assertEqual(classification, "custom")
        self.assertEqual(action, "ask_user")

    def test_case_insensitive_matching(self):
        # VERIFIES THAT PATTERN MATCHING IS CASE INSENSITIVE.
        node = _make_node("NODE_MODULES")
        classification, action, reason = classify_folder(node)
        self.assertEqual(classification, "package_dependencies")

    def test_classify_folder_returns_three_values(self):
        # VERIFIES THAT classify_folder ALWAYS RETURNS A TUPLE OF EXACTLY THREE STRINGS.
        node = _make_node("anything")
        result = classify_folder(node)
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], str)
        self.assertIsInstance(result[1], str)
        self.assertIsInstance(result[2], str)


class ClassifyTreeTests(unittest.TestCase):
    def test_classifies_every_folder_in_tree(self):
        # VERIFIES THAT classify_tree RETURNS A CLASSIFICATION ENTRY FOR EVERY NODE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "alpha").mkdir()
            (root / "beta").mkdir()
            (root / "alpha" / "gamma").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            classifications = classify_tree(tree)
            self.assertEqual(len(classifications), 4)

    def test_classifications_include_required_keys(self):
        # VERIFIES THAT EACH CLASSIFICATION DICT CONTAINS folder_path, classification, recommended_action, AND reason.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sub").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            classifications = classify_tree(tree)
            for entry in classifications:
                self.assertIn("folder_path", entry)
                self.assertIn("classification", entry)
                self.assertIn("recommended_action", entry)
                self.assertIn("reason", entry)
                self.assertIn("user_override", entry)
                self.assertIsNone(entry["user_override"])

    def test_classifications_propagate_to_tree_nodes(self):
        # VERIFIES THAT classify_tree SETS classification AND recommended_action ON EACH FolderNode.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "node_modules").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            classify_tree(tree)
            child = tree.children[0]
            self.assertEqual(child.classification, "package_dependencies")
            self.assertEqual(child.recommended_action, "exclude")

    def test_classify_tree_with_custom_patterns(self):
        # VERIFIES THAT CUSTOM PATTERNS PASSED TO classify_tree ARE APPLIED TO EVERY NODE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "my_custom").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            classifications = classify_tree(tree, custom_patterns=[r"^my_custom$"])
            custom_entries = [c for c in classifications if c["classification"] == "custom"]
            self.assertEqual(len(custom_entries), 1)


if __name__ == "__main__":
    unittest.main()
