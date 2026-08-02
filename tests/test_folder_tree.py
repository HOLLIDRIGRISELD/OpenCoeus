import tempfile
import unittest
from pathlib import Path

from opencoeus.core.folder_tree import (
    FolderNode,
    build_folder_tree,
    flatten_tree,
)
from opencoeus.config import default_protected_patterns


class BuildFolderTreeTests(unittest.TestCase):
    def test_empty_directory_returns_node_with_no_children(self):
        # VERIFIES THAT SCANNING AN EMPTY DIRECTORY RETURNS A ROOT NODE WITH ZERO CHILDREN.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tree = build_folder_tree(root, default_protected_patterns())
            self.assertEqual(tree.file_count, 0)
            self.assertEqual(len(tree.children), 0)

    def test_flat_directory_returns_children(self):
        # VERIFIES THAT SUBDIRECTORIES IN A FLAT STRUCTURE ARE FOUND AS DIRECT CHILDREN.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "alpha").mkdir()
            (root / "beta").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            child_names = {c.name for c in tree.children}
            self.assertEqual(child_names, {"alpha", "beta"})

    def test_nested_directories_have_correct_depth(self):
        # VERIFIES THAT DEEPLY NESTED DIRECTORIES ARE ASSIGNED THE CORRECT DEPTH VALUE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "a" / "b" / "c").mkdir(parents=True)
            tree = build_folder_tree(root, default_protected_patterns())
            flat = {entry["path"]: entry for entry in flatten_tree(tree)}
            deepest = flat.get((root / "a" / "b" / "c").as_posix())
            self.assertIsNotNone(deepest)
            self.assertEqual(deepest["depth"], 3)

    def test_max_depth_limits_recursion(self):
        # VERIFIES THAT FOLDERS BEYOND max_depth ARE NOT INCLUDED IN THE TREE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "a" / "b" / "c" / "d").mkdir(parents=True)
            tree = build_folder_tree(root, default_protected_patterns(), max_depth=2)
            flat = {entry["path"]: entry for entry in flatten_tree(tree)}
            self.assertIsNone(flat.get((root / "a" / "b" / "c" / "d").as_posix()))

    def test_file_counts_include_direct_files(self):
        # VERIFIES THAT FILE COUNTS ON A NODE REFLECT ITS DIRECT FILE CHILDREN.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "child").mkdir()
            (root / "file_a.txt").write_text("hello")
            (root / "file_b.txt").write_text("world")
            tree = build_folder_tree(root, default_protected_patterns())
            self.assertEqual(tree.file_count, 2)

    def test_file_counts_aggregate_through_children(self):
        # VERIFIES THAT A PARENT NODE FILE COUNT INCLUDES FILES FROM ALL DESCENDANTS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sub").mkdir()
            (root / "top.txt").write_text("a")
            (root / "sub" / "deep.txt").write_text("b")
            tree = build_folder_tree(root, default_protected_patterns())
            self.assertEqual(tree.file_count, 2)

    def test_total_size_aggregates_through_children(self):
        # VERIFIES THAT TOTAL_SIZE ON THE ROOT INCLUDES BYTES FROM ALL DESCENDANT FILES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sub").mkdir()
            (root / "a.txt").write_text("AB")
            (root / "sub" / "b.txt").write_text("CDE")
            tree = build_folder_tree(root, default_protected_patterns())
            self.assertEqual(tree.total_size, 5)

    def test_protected_folders_are_flagged(self):
        # VERIFIES THAT FOLDERS MATCHING PROTECTED PATTERNS HAVE is_protected SET TO TRUE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / ".opencoeus").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            flat = {entry["path"]: entry for entry in flatten_tree(tree)}
            node = flat.get((root / ".opencoeus").as_posix())
            self.assertIsNotNone(node)
            self.assertTrue(node["is_protected"])

    def test_symlinks_are_excluded(self):
        # VERIFIES THAT SYMBOLIC LINKS TO DIRECTORIES ARE NOT INCLUDED IN THE TREE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            real_dir = root / "real"
            real_dir.mkdir()
            link_dir = root / "link"
            link_dir.symlink_to(real_dir)
            tree = build_folder_tree(root, default_protected_patterns())
            flat = {entry["path"]: entry for entry in flatten_tree(tree)}
            self.assertIsNone(flat.get(link_dir.as_posix()))

    def test_progress_callback_is_invoked(self):
        # VERIFIES THAT THE PROGRESS CALLBACK IS CALLED FOR DISCOVERED SUBDIRECTORIES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for i in range(10):
                (root / f"folder_{i}").mkdir()
            discovered_paths = []
            build_folder_tree(root, default_protected_patterns(), progress_callback=discovered_paths.append)
            self.assertGreater(len(discovered_paths), 0)

    def test_children_are_sorted_alphabetically(self):
        # VERIFIES THAT CHILD NODES ARE SORTED BY NAME IN ASCENDING ORDER.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name in ["zebra", "alpha", "mango"]:
                (root / name).mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            child_names = [c.name for c in tree.children]
            self.assertEqual(child_names, ["alpha", "mango", "zebra"])


class FlattenTreeTests(unittest.TestCase):
    def test_flat_list_contains_all_nodes(self):
        # VERIFIES THAT FLATTEN_TREE RETURNS EVERY NODE IN THE TREE AS A DICTIONARY.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "c").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            flat = flatten_tree(tree)
            self.assertEqual(len(flat), 4)

    def test_flat_list_entries_have_depth_key(self):
        # VERIFIES THAT EACH ENTRY IN THE FLAT LIST INCLUDES A depth INTEGER KEY.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "child").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            flat = flatten_tree(tree)
            for entry in flat:
                self.assertIn("depth", entry)
                self.assertIsInstance(entry["depth"], int)

    def test_flat_list_root_is_first_entry(self):
        # VERIFIES THAT THE ROOT NODE APPEARS AS THE FIRST ENTRY IN THE FLAT LIST.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "child").mkdir()
            tree = build_folder_tree(root, default_protected_patterns())
            flat = flatten_tree(tree)
            self.assertEqual(flat[0]["path"], root.as_posix())


if __name__ == "__main__":
    unittest.main()
