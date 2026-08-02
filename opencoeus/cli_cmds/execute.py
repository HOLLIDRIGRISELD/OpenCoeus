from __future__ import annotations

import sys

from ..db import AuditStore
from ..journal import prepare_execution, run_execution, undo_last_batch
from ..profiles import load_profile_by_name


def run_execute(args) -> int:
    store = AuditStore()
    try:
        profile_id = None
        if args.profile:
            loaded = load_profile_by_name(store, args.profile)
            if loaded is None:
                print(f"Error: Profile '{args.profile}' not found.", file=sys.stderr)
                return 1
            profile_id = loaded.profile_id
        actions = store.get_proposed_actions(profile_id or 1)
        approved = [a for a in actions if a.approved]
        if not approved:
            print("No approved actions to execute.", file=sys.stderr)
            return 1
        print(f"Found {len(approved)} approved actions.")
        if args.dry_run:
            for action in approved:
                print(f"  {action.action_type:6s}  {action.original_path}")
                print(f"         -> {action.proposed_path}")
            print("\nDry run complete. No files were moved.")
            return 0
        batch_id, count = prepare_execution(store, profile_id or 1, f"{len(approved)} file moves via CLI")
        if batch_id == 0:
            print("Failed to create execution batch.", file=sys.stderr)
            return 1
        print(f"Executing batch {batch_id} ({count} files)...")
        def progress(msg):
            print(f"  {msg}")
        result = run_execution(batch_id, store, progress)
        print(f"\nExecution complete: {result.completed} completed, {result.failed} failed.")
        if result.errors:
            for error in result.errors:
                print(f"  ERROR: {error}", file=sys.stderr)
        return 0 if result.failed == 0 else 1
    finally:
        store.close()


def run_undo(args) -> int:
    store = AuditStore()
    try:
        profile_id = None
        if args.profile:
            loaded = load_profile_by_name(store, args.profile)
            if loaded is None:
                print(f"Error: Profile '{args.profile}' not found.", file=sys.stderr)
                return 1
            profile_id = loaded.profile_id
        batch_id, errors = undo_last_batch(store, profile_id)
        if batch_id is None:
            print("No completed batches to undo.", file=sys.stderr)
            return 1
        print(f"Undone batch {batch_id}.")
        if errors:
            for error in errors:
                print(f"  WARNING: {error}", file=sys.stderr)
        return 0
    finally:
        store.close()
