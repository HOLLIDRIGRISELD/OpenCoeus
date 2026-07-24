import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from opencoeus.database import AuditStore
from opencoeus.executor import (
    ExecutionResult,
    cleanup_empty_folders,
    cleanup_holding_area,
    create_holding_area,
    execute_batch,
    get_holding_dir,
    pre_execution_check,
    recover_crashed_batches,
    resolve_collision,
    rollback_partial,
    rollback_remaining,
    safe_move,
    undo_batch,
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
        self.assertEqual(result, Path.home() / ".opencoeus" / "transactions" / "42")

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
    def _make_store(self):
        # CREATES A TEMPORARY AUDITSTORE FOR TESTING.
        import tempfile as _tmp
        tmp_dir = _tmp.mkdtemp()
        url = f"sqlite:///{Path(tmp_dir) / 'test.sqlite3'}"
        return AuditStore(url)

    def test_all_files_present(self):
        # VERIFIES THAT NO ERRORS ARE RETURNED WHEN ALL SOURCE FILES EXIST.
        store = self._make_store()
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
            passing, errors = pre_execution_check(entries, store)
            self.assertEqual(errors, [])
            self.assertEqual(len(passing), 2)

    def test_missing_file_detected(self):
        # VERIFIES THAT AN ERROR IS RETURNED FOR MISSING SOURCE FILES.
        store = self._make_store()
        from opencoeus.models import TransactionEntry
        entries = [
            TransactionEntry(
                batch_id=1, action_type="move",
                source_path="/nonexistent/file.txt", destination_path="/dest/file.txt",
                source_hash="", source_size=0,
                status="pending",
            ),
        ]
        passing, errors = pre_execution_check(entries, store)
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0])
        self.assertEqual(len(passing), 0)

    def test_hash_mismatch_detected(self):
        # VERIFIES THAT AN ERROR IS RETURNED WHEN SOURCE FILE HASH DOES NOT MATCH.
        store = self._make_store()
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
            passing, errors = pre_execution_check(entries, store)
            self.assertEqual(len(errors), 1)
            self.assertIn("Hash mismatch", errors[0])
            self.assertEqual(len(passing), 0)


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


class CleanupEmptyFoldersTests(unittest.TestCase):
    def test_removes_empty_folders(self):
        # VERIFIES THAT EMPTY FOLDERS ARE REMOVED AFTER CLEANUP.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty_dir").mkdir()
            (root / "another_empty").mkdir()
            removed = cleanup_empty_folders(root)
            self.assertEqual(removed, 2)
            self.assertFalse((root / "empty_dir").exists())
            self.assertFalse((root / "another_empty").exists())

    def test_skips_non_empty_folders(self):
        # VERIFIES THAT FOLDERS WITH FILES ARE NOT REMOVED.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "has_files").mkdir()
            (root / "has_files" / "file.txt").write_text("content")
            removed = cleanup_empty_folders(root)
            self.assertEqual(removed, 0)
            self.assertTrue((root / "has_files").exists())

    def test_skips_excluded_folders(self):
        # VERIFIES THAT EXCLUDED FOLDERS ARE NOT REMOVED EVEN IF EMPTY.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "node_modules").mkdir()
            (root / "empty_dir").mkdir()
            removed = cleanup_empty_folders(root, excluded_folders={str(root / "node_modules")})
            self.assertEqual(removed, 1)
            self.assertTrue((root / "node_modules").exists())
            self.assertFalse((root / "empty_dir").exists())

    def test_skips_root_folder(self):
        # VERIFIES THAT THE ROOT FOLDER ITSELF IS NEVER DELETED.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            removed = cleanup_empty_folders(root)
            self.assertEqual(removed, 0)
            self.assertTrue(root.exists())

    def test_skips_opencoeus_folder(self):
        # VERIFIES THAT .opencoeus FOLDER IS NOT REMOVED.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".opencoeus").mkdir()
            removed = cleanup_empty_folders(root)
            self.assertEqual(removed, 0)
            self.assertTrue((root / ".opencoeus").exists())

    def test_cleans_nested_empty_folders_bottom_up(self):
        # VERIFIES THAT NESTED EMPTY FOLDERS ARE CLEANED BOTTOM-UP (CHILDREN BEFORE PARENTS).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "parent"
            child = parent / "child"
            child.mkdir(parents=True)
            removed = cleanup_empty_folders(root)
            self.assertEqual(removed, 2)
            self.assertFalse(child.exists())
            self.assertFalse(parent.exists())


class ExecuteBatchTests(unittest.TestCase):
    def _make_store(self):
        import tempfile as _tmp
        tmp_dir = _tmp.mkdtemp()
        url = f"sqlite:///{Path(tmp_dir) / 'test.sqlite3'}"
        return AuditStore(url)

    def test_execute_batch_single_file(self):
        # VERIFIES FULL EXECUTION FLOW: SINGLE FILE MOVED FROM SOURCE TO DESTINATION.
        import opencoeus.executor as executor_mod
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("Exec Single")
                src = Path(tmp) / "source.txt"
                src.write_text("hello world")
                dest = Path(tmp) / "dest_dir" / "source.txt"
                batch = store.create_batch(profile.id, "single test")
                store.add_entry(batch.id, None, "move", str(src), str(dest),
                                source_hash=sha256_file(src), source_size=src.stat().st_size)
                result = execute_batch(batch.id, store)
                self.assertEqual(result.completed, 1)
                self.assertEqual(result.failed, 0)
                self.assertTrue(dest.exists())
                self.assertFalse(src.exists())
                self.assertEqual(dest.read_text(), "hello world")
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_execute_batch_multiple_files(self):
        # VERIFIES FULL EXECUTION FLOW: MULTIPLE FILES MOVED SUCCESSFULLY.
        import opencoeus.executor as executor_mod
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("Exec Multi")
                src1 = Path(tmp) / "a.txt"
                src2 = Path(tmp) / "b.txt"
                src3 = Path(tmp) / "c.txt"
                src1.write_text("aaa")
                src2.write_text("bbb")
                src3.write_text("ccc")
                dest_dir = Path(tmp) / "output"
                batch = store.create_batch(profile.id, "multi test")
                for src in (src1, src2, src3):
                    store.add_entry(batch.id, None, "move", str(src),
                                    str(dest_dir / src.name),
                                    source_hash=sha256_file(src), source_size=src.stat().st_size)
                result = execute_batch(batch.id, store)
                self.assertEqual(result.completed, 3)
                self.assertEqual(result.failed, 0)
                self.assertTrue((dest_dir / "a.txt").exists())
                self.assertTrue((dest_dir / "b.txt").exists())
                self.assertTrue((dest_dir / "c.txt").exists())
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_execute_batch_missing_source(self):
        # VERIFIES PRE-FLIGHT DETECTS MISSING SOURCE FILE AND MARKS ENTRY FAILED.
        import opencoeus.executor as executor_mod
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("Exec Missing")
                missing = Path(tmp) / "nonexistent.txt"
                dest = Path(tmp) / "dest.txt"
                batch = store.create_batch(profile.id, "missing test")
                store.add_entry(batch.id, None, "move", str(missing), str(dest))
                result = execute_batch(batch.id, store)
                self.assertEqual(result.failed, 1)
                self.assertEqual(result.completed, 0)
                entries = store.get_entries_by_batch(batch.id)
                self.assertEqual(entries[0].status, "failed")
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_execute_batch_concurrent_guard(self):
        # VERIFIES SECOND CONCURRENT EXECUTE_BATCH RETURNS ERROR IMMEDIATELY.
        import opencoeus.executor as executor_mod
        import threading
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("Concurrent")
                batch = store.create_batch(profile.id, "concurrent test")
                # ACQUIRE THE LOCK MANUALLY TO SIMULATE CONCURRENT EXECUTION.
                executor_mod._batch_lock.acquire()
                try:
                    result = execute_batch(batch.id, store)
                    self.assertEqual(len(result.errors), 1)
                    self.assertIn("already executing", result.errors[0])
                finally:
                    executor_mod._batch_lock.release()
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_execute_batch_no_pending(self):
        # VERIFIES BATCH WITH NO PENDING ENTRIES RETURNS SKIPPED.
        import opencoeus.executor as executor_mod
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("No Pending")
                batch = store.create_batch(profile.id)
                entry = store.add_entry(batch.id, None, "move", "/a.txt", "/b.txt")
                store.update_entry(entry.id, status="completed")
                result = execute_batch(batch.id, store)
                self.assertEqual(result.skipped, 1)
                self.assertEqual(result.completed, 0)
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_execute_batch_empty_batch(self):
        # VERIFIES BATCH WITH ZERO ENTRIES RETURNS IMMEDIATELY.
        import opencoeus.executor as executor_mod
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("Empty")
                batch = store.create_batch(profile.id)
                result = execute_batch(batch.id, store)
                self.assertEqual(result.total, 0)
                self.assertEqual(result.skipped, 0)
            finally:
                executor_mod.HOLDING_ROOT = original


class UndoBatchTests(unittest.TestCase):
    def _make_store(self):
        import tempfile as _tmp
        tmp_dir = _tmp.mkdtemp()
        url = f"sqlite:///{Path(tmp_dir) / 'test.sqlite3'}"
        return AuditStore(url)

    def test_undo_restores_files(self):
        # VERIFIES UNDO MOVES FILES FROM DESTINATION BACK TO SOURCE.
        import opencoeus.executor as executor_mod
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("Undo Test")
                src = Path(tmp) / "original.txt"
                src.write_text("content")
                dest = Path(tmp) / "moved.txt"
                batch = store.create_batch(profile.id)
                entry = store.add_entry(batch.id, None, "move", str(src), str(dest))
                # SIMULATE COMPLETED STATE.
                store.update_entry(entry.id, status="completed", destination_path=str(dest),
                                   executed_at=datetime.now(UTC).replace(tzinfo=None))
                store.mark_batch(batch.id, "completed", completed_at=datetime.now(UTC).replace(tzinfo=None))
                dest.write_text("content")
                errors = undo_batch(batch.id, store)
                self.assertEqual(len(errors), 0)
                self.assertTrue(src.exists())
                self.assertFalse(dest.exists())
                self.assertEqual(src.read_text(), "content")
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_undo_missing_destination(self):
        # VERIFIES UNDO HANDLES MISSING DESTINATION FILES GRACEFULLY.
        import opencoeus.executor as executor_mod
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("Undo Missing")
                src = Path(tmp) / "original.txt"
                dest = Path(tmp) / "deleted.txt"
                batch = store.create_batch(profile.id)
                entry = store.add_entry(batch.id, None, "move", str(src), str(dest))
                store.update_entry(entry.id, status="completed", destination_path=str(dest),
                                   executed_at=datetime.now(UTC).replace(tzinfo=None))
                store.mark_batch(batch.id, "completed", completed_at=datetime.now(UTC).replace(tzinfo=None))
                errors = undo_batch(batch.id, store)
                self.assertEqual(len(errors), 1)
                self.assertIn("missing", errors[0])
            finally:
                executor_mod.HOLDING_ROOT = original

    def test_undo_empty_batch(self):
        # VERIFIES UNDO ON BATCH WITH NO COMPLETED ENTRIES RETURNS ERROR.
        import opencoeus.executor as executor_mod
        original = executor_mod.HOLDING_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            holding_tmp = Path(tmp) / "holding"
            executor_mod.HOLDING_ROOT = holding_tmp
            try:
                store = self._make_store()
                profile = store.create_profile("Undo Empty")
                batch = store.create_batch(profile.id)
                errors = undo_batch(batch.id, store)
                self.assertEqual(len(errors), 1)
                self.assertIn("No completed entries", errors[0])
            finally:
                executor_mod.HOLDING_ROOT = original


class RecoverCrashedBatchesTests(unittest.TestCase):
    def _make_store(self):
        import tempfile as _tmp
        tmp_dir = _tmp.mkdtemp()
        url = f"sqlite:///{Path(tmp_dir) / 'test.sqlite3'}"
        return AuditStore(url)

    def test_recover_executing_batch(self):
        # VERIFIES BATCH STUCK IN EXECUTING IS MARKED FAILED.
        store = self._make_store()
        profile = store.create_profile("Crash Test")
        batch = store.create_batch(profile.id)
        entry = store.add_entry(batch.id, None, "move", "/a.txt", "/b.txt")
        # SET BATCH TO EXECUTING AND ENTRY TO MOVED_TO_HOLDING.
        store.mark_batch(batch.id, "executing")
        store.update_entry(entry.id, status="moved_to_holding", holding_path="/holding/b.txt")
        recovered = recover_crashed_batches(store)
        self.assertEqual(recovered, 1)
        # VERIFY STATUS WAS UPDATED.
        from opencoeus.models import TransactionBatch, TransactionEntry
        from sqlalchemy import select
        with store.session_factory() as session:
            batch_obj = session.scalar(select(TransactionBatch).where(TransactionBatch.id == batch.id))
            self.assertEqual(batch_obj.status, "failed")
            entry_obj = session.scalar(select(TransactionEntry).where(TransactionEntry.id == entry.id))
            self.assertEqual(entry_obj.status, "failed")

    def test_recover_nothing_to_recover(self):
        # VERIFIES NO RECOVERY NEEDED WHEN NO EXECUTING BATCHES EXIST.
        store = self._make_store()
        profile = store.create_profile("No Crash")
        batch = store.create_batch(profile.id)
        store.mark_batch(batch.id, "completed")
        recovered = recover_crashed_batches(store)
        self.assertEqual(recovered, 0)


class BatchStatusEnumTests(unittest.TestCase):
    def test_batch_status_values(self):
        # VERIFIES BATCHSTATUS ENUM HAS CORRECT STRING VALUES.
        from opencoeus.models import BatchStatus
        self.assertEqual(BatchStatus.PENDING, "pending")
        self.assertEqual(BatchStatus.EXECUTING, "executing")
        self.assertEqual(BatchStatus.COMPLETED, "completed")
        self.assertEqual(BatchStatus.FAILED, "failed")
        self.assertEqual(BatchStatus.UNDONE, "undone")

    def test_entry_status_values(self):
        # VERIFIES ENTRYSTATUS ENUM HAS CORRECT STRING VALUES.
        from opencoeus.models import EntryStatus
        self.assertEqual(EntryStatus.PENDING, "pending")
        self.assertEqual(EntryStatus.MOVED_TO_HOLDING, "moved_to_holding")
        self.assertEqual(EntryStatus.COMPLETED, "completed")
        self.assertEqual(EntryStatus.FAILED, "failed")
        self.assertEqual(EntryStatus.UNDONE, "undone")


if __name__ == "__main__":
    unittest.main()
