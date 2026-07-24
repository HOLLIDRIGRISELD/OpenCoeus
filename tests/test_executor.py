import tempfile
import unittest
from pathlib import Path

from opencoeus.database import AuditStore
from opencoeus.executor import (
    ExecutionResult,
    cleanup_holding_area,
    create_holding_area,
    get_holding_dir,
    pre_execution_check,
    resolve_collision,
    rollback_partial,
    rollback_remaining,
    safe_move,
    verify_file_integrity,
)
from opencoeus.hashing import sha256_file


class ResolveCollisionTests(unittest.TestCase):
    def test_no_conflict(self):
        # VERIFIES THAT ORIGINAL PATH IS RETURNED WHEN NO CONFLICT EXISTS.
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "file.txt"
            result = resolve_collision(dest)
            self.assertEqual(result, dest)

    def test_one_conflict(self):
        # VERIFIES THAT (2) IS APPENDED WHEN ONE CONFLICT EXISTS.
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "file.txt"
            dest.write_text("existing")
            result = resolve_collision(dest)
            self.assertEqual(result.name, "file (2).txt")

    def test_multiple_conflicts(self):
        # VERIFIES THAT (3), (4), ETC. ARE USED FOR MULTIPLE CONFLICTS.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "file.txt").write_text("a")
            (Path(tmp) / "file (2).txt").write_text("b")
            (Path(tmp) / "file (3).txt").write_text("c")
            result = resolve_collision(Path(tmp) / "file.txt")
            self.assertEqual(result.name, "file (4).txt")


class SafeMoveTests(unittest.TestCase):
    def test_move_same_directory(self):
        # VERIFIES THAT A FILE IS MOVED WITHIN THE SAME DIRECTORY.
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.txt"
            src.write_text("hello")
            dst = Path(tmp) / "dest.txt"
            result = safe_move(src, dst)
            self.assertTrue(result.exists())
            self.assertFalse(src.exists())
            self.assertEqual(result.read_text(), "hello")

    def test_move_creates_parent_dirs(self):
        # VERIFIES THAT PARENT DIRECTORIES ARE CREATED IF MISSING.
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.txt"
            src.write_text("data")
            dst = Path(tmp) / "sub" / "dir" / "dest.txt"
            result = safe_move(src, dst)
            self.assertTrue(result.exists())
            self.assertEqual(result.read_text(), "data")

    def test_move_cross_directory(self):
        # VERIFIES THAT A FILE CAN BE MOVED ACROSS DIRECTORIES.
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "src"
            dst_dir = Path(tmp) / "dst"
            src_dir.mkdir()
            dst_dir.mkdir()
            src = src_dir / "file.txt"
            src.write_text("cross")
            result = safe_move(src, dst_dir / "file.txt")
            self.assertTrue(result.exists())
            self.assertFalse(src.exists())


class VerifyFileIntegrityTests(unittest.TestCase):
    def test_match(self):
        # VERIFIES THAT NONE IS RETURNED WHEN HASH AND SIZE MATCH.
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "test.txt"
            f.write_text("verify me")
            h = sha256_file(f)
            s = f.stat().st_size
            result = verify_file_integrity(f, h, s)
            self.assertIsNone(result)

    def test_hash_mismatch(self):
        # VERIFIES THAT AN ERROR IS RETURNED WHEN HASH DOES NOT MATCH.
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "test.txt"
            f.write_text("data")
            result = verify_file_integrity(f, "wrong_hash", f.stat().st_size)
            self.assertIsNotNone(result)
            self.assertIn("Hash mismatch", result)

    def test_size_mismatch(self):
        # VERIFIES THAT AN ERROR IS RETURNED WHEN SIZE DOES NOT MATCH.
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "test.txt"
            f.write_text("data")
            result = verify_file_integrity(f, "", 999999)
            self.assertIsNotNone(result)
            self.assertIn("Size mismatch", result)

    def test_file_missing(self):
        # VERIFIES THAT AN ERROR IS RETURNED WHEN FILE DOES NOT EXIST.
        result = verify_file_integrity(Path("/nonexistent/file.txt"), "", 0)
        self.assertIsNotNone(result)
        self.assertIn("not found", result)


class HoldingAreaTests(unittest.TestCase):
    def test_get_holding_dir(self):
        # VERIFIES THAT THE HOLDING DIR PATH IS CORRECT.
        result = get_holding_dir(42)
        self.assertEqual(result, Path(".opencoeus") / "transactions" / "42")

    def test_create_holding_area(self):
        # VERIFIES THAT THE HOLDING DIRECTORY IS CREATED.
        with tempfile.TemporaryDirectory() as tmp:
            import opencoeus.executor as executor_mod
            original = executor_mod.HOLDING_ROOT
            executor_mod.HOLDING_ROOT = Path(tmp) / "transactions"
            try:
                result = create_holding_area(99)
                self.assertTrue(result.exists())
                self.assertTrue(result.is_dir())
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_cleanup_holding_area(self):
        # VERIFIES THAT THE HOLDING DIRECTORY IS REMOVED.
        with tempfile.TemporaryDirectory() as tmp:
            import opencoeus.executor as executor_mod
            original = executor_mod.HOLDING_ROOT
            executor_mod.HOLDING_ROOT = Path(tmp) / "transactions"
            try:
                create_holding_area(100)
                cleanup_holding_area(100)
                self.assertFalse(get_holding_dir(100).exists())
            finally:
                executor_mod.HOLDING_ROOT = original


class PreExecutionCheckTests(unittest.TestCase):
    def test_all_files_present(self):
        # VERIFIES THAT NO ERRORS ARE RETURNED WHEN ALL SOURCE FILES EXIST.
        with tempfile.TemporaryDirectory() as tmp:
            f1 = Path(tmp) / "a.txt"
            f2 = Path(tmp) / "b.txt"
            f1.write_text("aaa")
            f2.write_text("bbb")
            from opencoeus.models import TransactionEntry
            entries = [
                TransactionEntry(
                    batch_id=1, action_type="move",
                    source_path=str(f1), destination_path="/dest/a.txt",
                    source_hash=sha256_file(f1), source_size=f1.stat().st_size,
                    status="pending",
                ),
                TransactionEntry(
                    batch_id=1, action_type="move",
                    source_path=str(f2), destination_path="/dest/b.txt",
                    source_hash=sha256_file(f2), source_size=f2.stat().st_size,
                    status="pending",
                ),
            ]
            errors = pre_execution_check(entries)
            self.assertEqual(errors, [])

    def test_missing_file_detected(self):
        # VERIFIES THAT AN ERROR IS RETURNED FOR MISSING SOURCE FILES.
        from opencoeus.models import TransactionEntry
        entries = [
            TransactionEntry(
                batch_id=1, action_type="move",
                source_path="/nonexistent/file.txt", destination_path="/dest/file.txt",
                source_hash="", source_size=0,
                status="pending",
            ),
        ]
        errors = pre_execution_check(entries)
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0])

    def test_hash_mismatch_detected(self):
        # VERIFIES THAT AN ERROR IS RETURNED WHEN SOURCE FILE HASH DOES NOT MATCH.
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "changed.txt"
            f.write_text("original")
            from opencoeus.models import TransactionEntry
            entries = [
                TransactionEntry(
                    batch_id=1, action_type="move",
                    source_path=str(f), destination_path="/dest/changed.txt",
                    source_hash="wrong_hash", source_size=f.stat().st_size,
                    status="pending",
                ),
            ]
            errors = pre_execution_check(entries)
            self.assertEqual(len(errors), 1)
            self.assertIn("Hash mismatch", errors[0])


class RollbackTests(unittest.TestCase):
    def test_rollback_partial_restores_files(self):
        # VERIFIES THAT ROLLBACK RESTORES FILES FROM HOLDING TO ORIGINAL SOURCE.
        with tempfile.TemporaryDirectory() as tmp:
            import opencoeus.executor as executor_mod
            original = executor_mod.HOLDING_ROOT
            executor_mod.HOLDING_ROOT = Path(tmp) / "transactions"
            try:
                src = Path(tmp) / "source.txt"
                src.write_text("original")
                holding = create_holding_area(200)
                moved = safe_move(src, holding / "source.txt")
                self.assertFalse(src.exists())
                from opencoeus.models import TransactionEntry
                entry = TransactionEntry(
                    batch_id=200, action_type="move",
                    source_path=str(src), destination_path="/dest/source.txt",
                    source_hash="", source_size=0, status="moved_to_holding",
                )
                rollback_partial([(entry, moved)], None)
                self.assertTrue(src.exists())
                self.assertEqual(src.read_text(), "original")
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_rollback_remaining_restores_uncompleted(self):
        # VERIFIES THAT ONLY UNCOMPLETED ENTRIES ARE ROLLED BACK.
        with tempfile.TemporaryDirectory() as tmp:
            import opencoeus.executor as executor_mod
            original = executor_mod.HOLDING_ROOT
            executor_mod.HOLDING_ROOT = Path(tmp) / "transactions"
            try:
                src1 = Path(tmp) / "file1.txt"
                src2 = Path(tmp) / "file2.txt"
                src1.write_text("first")
                src2.write_text("second")
                holding = create_holding_area(300)
                moved1 = safe_move(src1, holding / "file1.txt")
                moved2 = safe_move(src2, holding / "file2.txt")
                from opencoeus.models import TransactionEntry
                e1 = TransactionEntry(
                    batch_id=300, action_type="move",
                    source_path=str(src1), destination_path="/dest/file1.txt",
                    source_hash="", source_size=0, status="moved_to_holding",
                )
                e1.id = 1
                e2 = TransactionEntry(
                    batch_id=300, action_type="move",
                    source_path=str(src2), destination_path="/dest/file2.txt",
                    source_hash="", source_size=0, status="moved_to_holding",
                )
                e2.id = 2
                # e1 IS COMPLETED, e2 IS NOT.
                rollback_remaining([(e1, moved1), (e2, moved2)], [(e1, moved1)], None)
                self.assertFalse(src1.exists())  # COMPLETED: NOT ROLLED BACK.
                self.assertTrue(src2.exists())    # UNCOMPLETED: ROLLED BACK.
                self.assertEqual(src2.read_text(), "second")
            finally:
                executor_mod.HOLDING_ROOT = original


if __name__ == "__main__":
    unittest.main()
