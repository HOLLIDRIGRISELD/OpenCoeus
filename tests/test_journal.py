import tempfile
import unittest
from pathlib import Path

from opencoeus.db import AuditStore
from opencoeus.core.hashing import sha256_file
from opencoeus.journal import (
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
