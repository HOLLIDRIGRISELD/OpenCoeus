import tempfile
import unittest
from pathlib import Path

from opencoeus.database import AuditStore
from opencoeus.hashing import sha256_file
from opencoeus.journal import (
    BatchSummary,
    get_batch_summary,
    prepare_execution,
    run_execution,
    undo_last_batch,
)


class PrepareExecutionTests(unittest.TestCase):
    def test_creates_batch_and_entries(self):
        # VERIFIES THAT A BATCH AND ENTRIES ARE CREATED FROM APPROVED ACTIONS.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{db_path.as_posix()}")
            profile = store.create_profile("Prepare Test")
            # CREATE TEST FILES.
            src1 = Path(tmp) / "file1.txt"
            src2 = Path(tmp) / "file2.txt"
            src1.write_text("content1")
            src2.write_text("content2")
            store.save_proposed_actions(profile.id, [
                {"original_path": str(src1), "proposed_path": "/dest/file1.txt", "action_type": "move"},
                {"original_path": str(src2), "proposed_path": "/dest/file2.txt", "action_type": "move"},
            ])
            actions = store.get_proposed_actions(profile.id)
            for a in actions:
                store.approve_action(a.id)
            batch_id, count = prepare_execution(store, profile.id, "Test batch")
            self.assertGreater(batch_id, 0)
            self.assertEqual(count, 2)
            entries = store.get_entries_by_batch(batch_id)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].source_hash, sha256_file(src1))
            store.close()

    def test_returns_zero_for_no_approved(self):
        # VERIFIES THAT (0, 0) IS RETURNED WHEN NO ACTIONS ARE APPROVED.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{db_path.as_posix()}")
            profile = store.create_profile("No Approved")
            store.save_proposed_actions(profile.id, [
                {"original_path": "/a.txt", "proposed_path": "/new_a.txt", "action_type": "move"},
            ])
            batch_id, count = prepare_execution(store, profile.id, "")
            self.assertEqual(batch_id, 0)
            self.assertEqual(count, 0)
            store.close()


class GetBatchSummaryTests(unittest.TestCase):
    def test_summary_counts(self):
        # VERIFIES THAT THE SUMMARY CORRECTLY COUNTS ENTRIES BY STATUS.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{db_path.as_posix()}")
            profile = store.create_profile("Summary Test")
            batch = store.create_batch(profile.id)
            e1 = store.add_entry(batch.id, None, "move", "/a.txt", "/new_a.txt")
            e2 = store.add_entry(batch.id, None, "move", "/b.txt", "/new_b.txt")
            e3 = store.add_entry(batch.id, None, "move", "/c.txt", "/new_c.txt")
            store.update_entry(e1.id, status="completed")
            store.update_entry(e2.id, status="completed")
            summary = get_batch_summary(store, batch.id)
            self.assertEqual(summary.total, 3)
            self.assertEqual(summary.completed, 2)
            self.assertEqual(summary.failed, 0)
            self.assertEqual(summary.pending, 1)
            store.close()

    def test_summary_all_completed(self):
        # VERIFIES THAT STATUS IS COMPLETED WHEN ALL ENTRIES ARE COMPLETED.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{db_path.as_posix()}")
            profile = store.create_profile("All Done")
            batch = store.create_batch(profile.id)
            e1 = store.add_entry(batch.id, None, "move", "/a.txt", "/new_a.txt")
            e2 = store.add_entry(batch.id, None, "move", "/b.txt", "/new_b.txt")
            store.update_entry(e1.id, status="completed")
            store.update_entry(e2.id, status="completed")
            summary = get_batch_summary(store, batch.id)
            self.assertEqual(summary.status, "completed")
            store.close()


class UndoLastBatchTests(unittest.TestCase):
    def test_returns_none_when_no_batches(self):
        # VERIFIES THAT (NONE, [ERROR]) IS RETURNED WHEN NO BATCHES EXIST.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{db_path.as_posix()}")
            profile = store.create_profile("No Batches")
            batch_id, errors = undo_last_batch(store, profile.id)
            self.assertIsNone(batch_id)
            self.assertEqual(len(errors), 1)
            store.close()


if __name__ == "__main__":
    unittest.main()
