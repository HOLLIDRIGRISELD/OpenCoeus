from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ScanSettings
from .database import AuditStore
from .engine import ScanEngine, write_manifest
from .folder_classifier import classify_tree
from .folder_tree import build_folder_tree
from .profiles import (
    ProfileConfig,
    create_profile,
    delete_profile,
    list_profiles,
    load_profile_by_name,
)
from .rules_engine import DEFAULT_RULES, RulesEngine

def main() -> int:
    command_parser = argparse.ArgumentParser(
        description="OpenCoeus offline scan and organization (never modifies files without approval)."
    )
    command_subparsers = command_parser.add_subparsers(dest="command", required=True)

    # SCAN COMMAND: THE ORIGINAL STAGE 1 NON DESTRUCTIVE AUDIT
    scan_command = command_subparsers.add_parser("scan", help="Create a non-destructive audit manifest.")
    scan_command.add_argument("folder", type=Path)
    scan_command.add_argument("--output", type=Path, default=Path("opencoeus-manifest.csv"))
    scan_command.add_argument("--no-document-text", action="store_true")
    scan_command.add_argument("--profile", type=str, default=None, help="Scan profile name to apply settings from.")

    # PROFILE COMMAND: MANAGE SCAN PROFILES
    profile_command = command_subparsers.add_parser("profile", help="Manage scan profiles.")
    profile_subparsers = profile_command.add_subparsers(dest="profile_action", required=True)
    profile_subparsers.add_parser("list", help="List all saved profiles.")
    profile_create_cmd = profile_subparsers.add_parser("create", help="Create a new scan profile.")
    profile_create_cmd.add_argument("name", type=str, help="Profile name.")
    profile_create_cmd.add_argument("--root", type=str, default="", help="Default root folder path.")
    profile_delete_cmd = profile_subparsers.add_parser("delete", help="Delete a scan profile.")
    profile_delete_cmd.add_argument("name", type=str, help="Profile name to delete.")
    profile_show_cmd = profile_subparsers.add_parser("show", help="Show profile details.")
    profile_show_cmd.add_argument("name", type=str, help="Profile name to show.")

    # CLASSIFY COMMAND: RUN PHASE ONE FOLDER CLASSIFICATION
    classify_command = command_subparsers.add_parser("classify", help="Classify folders in a directory tree.")
    classify_command.add_argument("folder", type=Path)
    classify_command.add_argument("--output", type=Path, default=None, help="Save classifications to JSON file.")
    classify_command.add_argument("--max-depth", type=int, default=5, help="Maximum folder tree depth.")

    # ORGANIZE COMMAND: RUN RULES ENGINE AND PROPOSE FILE ACTIONS
    organize_command = command_subparsers.add_parser("organize", help="Propose file organization actions using rules.")
    organize_command.add_argument("folder", type=Path)
    organize_command.add_argument("--output", type=Path, default=Path("opencoeus-actions.csv"))
    organize_command.add_argument("--no-document-text", action="store_true")
    organize_command.add_argument("--profile", type=str, default=None, help="Profile name to use for rules.")
    organize_command.add_argument("--rules-file", type=Path, default=None, help="JSON file with rule definitions.")
    organize_command.add_argument("--rename-template", type=str, default=None, help="Override rename template for all rules.")

    # RENAME COMMAND: PROPOSE RENAME ACTIONS
    rename_command = command_subparsers.add_parser("rename", help="Propose file renames using content-aware rules.")
    rename_command.add_argument("folder", type=Path)
    rename_command.add_argument("--output", type=Path, default=Path("opencoeus-renames.csv"))
    rename_command.add_argument("--no-document-text", action="store_true")
    rename_command.add_argument("--profile", type=str, default=None, help="Profile name to use for rules.")
    rename_command.add_argument("--rules-file", type=Path, default=None, help="JSON file with rule definitions.")
    rename_command.add_argument("--rename-template", type=str, default=None, help="Override rename template for all rules.")
    rename_command.add_argument("--dry-run", action="store_true", help="Preview renames without saving to CSV.")

    # EXECUTE COMMAND: EXECUTE APPROVED FILE ACTIONS
    execute_command = command_subparsers.add_parser("execute", help="Execute approved file organization actions.")
    execute_command.add_argument("--profile", type=str, default=None, help="Profile name to execute actions for.")
    execute_command.add_argument("--dry-run", action="store_true", help="Show what would be done without executing.")

    # UNDO COMMAND: UNDO THE LAST EXECUTED BATCH
    undo_command = command_subparsers.add_parser("undo", help="Undo the last executed batch of file moves.")
    undo_command.add_argument("--profile", type=str, default=None, help="Profile name to undo actions for.")

    command_arguments = command_parser.parse_args()

    if command_arguments.command == "scan":
        return _run_scan(command_arguments)
    if command_arguments.command == "profile":
        return _run_profile(command_arguments)
    if command_arguments.command == "classify":
        return _run_classify(command_arguments)
    if command_arguments.command == "organize":
        return _run_organize(command_arguments)
    if command_arguments.command == "rename":
        return _run_rename(command_arguments)
    if command_arguments.command == "execute":
        return _run_execute(command_arguments)
    if command_arguments.command == "undo":
        return _run_undo(command_arguments)
    return 0


def _run_scan(args) -> int:
    """Execute scan command: manifest files with optional document text extraction."""
    if not args.folder.is_dir():
        print(f"Error: Not a readable folder: {args.folder}", file=sys.stderr)
        return 1
    extract_documents = not args.no_document_text
    store = AuditStore()
    try:
        # LOAD PROFILE IF SPECIFIED AND APPLY ITS SETTINGS
        profile = ProfileConfig()
        if args.profile:
            loaded = load_profile_by_name(store, args.profile)
            if loaded is None:
                print(f"Warning: Profile '{args.profile}' not found. Using defaults.", file=sys.stderr)
            else:
                profile = loaded
                if loaded.excluded_folders:
                    print(f"Profile '{args.profile}': excluding {len(loaded.excluded_folders)} folders.")
                if loaded.custom_protected_patterns:
                    print(f"Profile '{args.profile}': using {len(loaded.custom_protected_patterns)} custom patterns.")
                if not loaded.document_extraction:
                    extract_documents = False
        settings = ScanSettings(args.folder, extract_documents=extract_documents)
        # USE PHASE TWO PIPELINE IF PROFILE HAS EXCLUSIONS, OTHERWISE SINGLE PHASE SCAN
        excluded_folders = set(profile.excluded_folders) if profile.excluded_folders else None
        if excluded_folders:
            scan_engine = ScanEngine(settings, store)
            scan_result = scan_engine.run_phase_two(excluded_folders, print)
        else:
            scan_engine = ScanEngine(settings, store)
            scan_result = scan_engine.run(print)
        write_manifest(scan_result, args.output)
        print(f"Scanned {len(scan_result.rows)} files; found {scan_result.duplicate_count} duplicates. Manifest: {args.output}")
        for scan_error in scan_result.errors:
            print(f"WARNING: {scan_error}")
    finally:
        store.close()
    return 0


def _run_profile(args) -> int:
    """Execute profile subcommand: list, create, delete, or show profiles."""
    store = AuditStore()
    try:
        if args.profile_action == "list":
            profiles = list_profiles(store)
            if not profiles:
                print("No profiles saved.")
            for profile in profiles:
                print(f"  {profile.name}  root={profile.root_path}  extract_docs={profile.document_extraction}")
            return 0
        if args.profile_action == "create":
            created = create_profile(store, args.name, root_path=args.root)
            print(f"Created profile '{created.name}' (id={created.profile_id}).")
            return 0
        if args.profile_action == "delete":
            profile = load_profile_by_name(store, args.name)
            if profile is None:
                print(f"Error: Profile '{args.name}' not found.", file=sys.stderr)
                return 1
            delete_profile(store, profile.profile_id)
            print(f"Deleted profile '{args.name}'.")
            return 0
        if args.profile_action == "show":
            profile = load_profile_by_name(store, args.name)
            if profile is None:
                print(f"Error: Profile '{args.name}' not found.", file=sys.stderr)
                return 1
            print(f"Name: {profile.name}")
            print(f"Root: {profile.root_path}")
            print(f"Included: {profile.included_folders}")
            print(f"Excluded: {profile.excluded_folders}")
            print(f"Custom patterns: {profile.custom_protected_patterns}")
            print(f"Document extraction: {profile.document_extraction}")
            return 0
        return 0
    finally:
        store.close()


def _run_classify(args) -> int:
    """Execute classify command: classify folders in a directory tree."""
    if not args.folder.is_dir():
        print(f"Error: Not a readable folder: {args.folder}", file=sys.stderr)
        return 1
    settings = ScanSettings(args.folder)
    tree = build_folder_tree(args.folder, settings.protected_patterns, max_depth=args.max_depth)
    classifications = classify_tree(tree)
    for classification in classifications:
        action_badge = f"[{classification['recommended_action'].upper()}]"
        print(f"  {action_badge:12s} {classification['classification']:25s} {classification['folder_path']}")
        if classification["reason"]:
            print(f"               {classification['reason']}")
    if args.output is not None:
        with args.output.open("w", encoding="utf-8") as json_file:
            json.dump(classifications, json_file, indent=2)
        print(f"\nClassifications saved to {args.output}")
    print(f"\nTotal: {len(classifications)} folders classified.")
    return 0


def _run_organize(args) -> int:
    """Execute organize command: propose file actions using rules engine."""
    if not args.folder.is_dir():
        print(f"Error: Not a readable folder: {args.folder}", file=sys.stderr)
        return 1
    extract_documents = not args.no_document_text
    settings = ScanSettings(args.folder, extract_documents=extract_documents)
    store = AuditStore()
    try:
        # LOAD PROFILE IF SPECIFIED
        profile = ProfileConfig()
        if args.profile:
            loaded = load_profile_by_name(store, args.profile)
            if loaded is None:
                print(f"Warning: Profile '{args.profile}' not found. Using defaults.", file=sys.stderr)
            else:
                profile = loaded

        # LOAD RULES FROM FILE OR USE DEFAULTS
        rules = list(DEFAULT_RULES)
        if args.rules_file and args.rules_file.is_file():
            with args.rules_file.open(encoding="utf-8") as rules_json:
                rules = json.load(rules_json)
            print(f"Loaded {len(rules)} rules from {args.rules_file}")

        # PHASE 1: CLASSIFY FOLDERS
        print("Phase 1: Classifying folders...")
        tree = build_folder_tree(args.folder, settings.protected_patterns)
        classifications = classify_tree(tree, profile.custom_protected_patterns or None)
        excluded_folders = {
            c["folder_path"] for c in classifications
            if c["recommended_action"] == "exclude"
        }
        print(f"  Excluded {len(excluded_folders)} folders automatically.")

        # PHASE 2: SCAN FILES WITH EXCLUSIONS AND APPLY RULES
        print("Phase 2: Scanning files...")
        scan_engine = ScanEngine(settings, store)
        scan_result = scan_engine.run_phase_two(excluded_folders, print)
        print(f"  Scanned {len(scan_result.rows)} files, found {scan_result.duplicate_count} duplicates.")

        # APPLY RULES ENGINE
        rules_engine = RulesEngine(profile, scan_root=settings.root.as_posix())
        matches = rules_engine.evaluate(scan_result.rows, rules)

        # APPLY RENAME TEMPLATE OVERRIDE IF SPECIFIED (USES FULL 25+ VARIABLE ENGINE)
        if args.rename_template and matches:
            from .engine import ManifestRow
            for match in matches:
                if match.action_type in {"rename", "move+rename"}:
                    source = Path(match.original_path)
                    row = ManifestRow(
                        path=match.original_path,
                        size=0, sha256="", status="",
                        relative_path=match.original_path,
                        folder_path=str(source.parent).replace("\\", "/"),
                        extension=source.suffix,
                        suggested_title=match.original_filename or source.stem,
                        modified_at="", size_kb=0, size_mb=0,
                        date_iso="unknown", date_month="", date_day="", date_full="",
                        doc_type="Document",
                    )
                    new_name = rules_engine._render_rename(row, args.rename_template)
                    if new_name:
                        match.new_filename = new_name
                        if match.action_type == "rename":
                            match.proposed_path = str(Path(match.original_path).parent / new_name)
                        else:
                            match.proposed_path = str(Path(match.proposed_path).parent / new_name)

        if matches:
            import csv
            with args.output.open("w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=[
                    "original_path", "proposed_path", "action_type", "rule_id", "reason",
                    "original_filename", "new_filename",
                ])
                writer.writeheader()
                for match in matches:
                    writer.writerow({
                        "original_path": match.original_path,
                        "proposed_path": match.proposed_path,
                        "action_type": match.action_type,
                        "rule_id": match.rule_id or "",
                        "reason": match.reason,
                        "original_filename": match.original_filename,
                        "new_filename": match.new_filename,
                    })
            # COUNT MOVES AND RENAMES FOR SUMMARY
            move_count = sum(1 for m in matches if m.action_type == "move")
            rename_count = sum(1 for m in matches if m.action_type in {"rename", "move+rename"})
            parts = []
            if move_count:
                parts.append(f"{move_count} moves")
            if rename_count:
                parts.append(f"{rename_count} renames")
            summary = ", ".join(parts) if parts else f"{len(matches)} actions"
            print(f"\nProposed {summary}. Saved to {args.output}")
            print("\nPreview (first 10):")
            for match in matches[:10]:
                if match.action_type == "rename":
                    print(f"  RENAME  {match.original_path}")
                    print(f"          -> {match.new_filename}")
                elif match.action_type == "move+rename":
                    print(f"  MOVE+REN  {match.original_path}")
                    print(f"          -> {match.proposed_path}")
                    print(f"          renamed to {match.new_filename}")
                else:
                    print(f"  MOVE    {match.original_path}")
                    print(f"          -> {match.proposed_path}")
                print(f"          {match.reason}")
            if len(matches) > 10:
                print(f"  ... and {len(matches) - 10} more.")
        else:
            print("\nNo actions proposed. Files are already organized or no rules matched.")
    finally:
        store.close()
    return 0


def _run_rename(args) -> int:
    """Execute rename command: propose content-aware renames."""
    if not args.folder.is_dir():
        print(f"Error: Not a readable folder: {args.folder}", file=sys.stderr)
        return 1
    extract_documents = not args.no_document_text
    settings = ScanSettings(args.folder, extract_documents=extract_documents)
    store = AuditStore()
    try:
        profile = ProfileConfig()
        if args.profile:
            loaded = load_profile_by_name(store, args.profile)
            if loaded is None:
                print(f"Warning: Profile '{args.profile}' not found. Using defaults.", file=sys.stderr)
            else:
                profile = loaded

        rules = list(DEFAULT_RULES)
        if args.rules_file and args.rules_file.is_file():
            with args.rules_file.open(encoding="utf-8") as rules_json:
                rules = json.load(rules_json)
            print(f"Loaded {len(rules)} rules from {args.rules_file}")

        print("Phase 1: Classifying folders...")
        tree = build_folder_tree(args.folder, settings.protected_patterns)
        classifications = classify_tree(tree, profile.custom_protected_patterns or None)
        excluded_folders = {c["folder_path"] for c in classifications if c["recommended_action"] == "exclude"}
        print(f"  Excluded {len(excluded_folders)} folders automatically.")

        print("Phase 2: Scanning files...")
        scan_engine = ScanEngine(settings, store)
        scan_result = scan_engine.run_phase_two(excluded_folders, print)
        print(f"  Scanned {len(scan_result.rows)} files, found {scan_result.duplicate_count} duplicates.")

        rules_engine = RulesEngine(profile, scan_root=settings.root.as_posix())
        matches = rules_engine.evaluate(scan_result.rows, rules)

        # FILTER TO ONLY RENAME AND MOVE+RENAME ACTIONS
        rename_matches = [m for m in matches if m.action_type in {"rename", "move+rename"}]

        # APPLY RENAME TEMPLATE OVERRIDE IF SPECIFIED
        if args.rename_template and rename_matches:
            from .engine import ManifestRow
            for match in rename_matches:
                source = Path(match.original_path)
                row = ManifestRow(
                    path=match.original_path, size=0, sha256="", status="",
                    relative_path=match.original_path,
                    folder_path=str(source.parent).replace("\\", "/"),
                    extension=source.suffix,
                    suggested_title=match.original_filename or source.stem,
                    modified_at="", size_kb=0, size_mb=0,
                    date_iso="unknown", date_month="", date_day="", date_full="",
                    doc_type="Document",
                )
                new_name = rules_engine._render_rename(row, args.rename_template)
                if new_name:
                    match.new_filename = new_name
                    if match.action_type == "rename":
                        match.proposed_path = str(Path(match.original_path).parent / new_name)
                    else:
                        match.proposed_path = str(Path(match.proposed_path).parent / new_name)

        if not args.dry_run and rename_matches:
            import csv
            with args.output.open("w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=[
                    "original_path", "proposed_path", "action_type", "rule_id", "reason",
                    "original_filename", "new_filename",
                ])
                writer.writeheader()
                for match in rename_matches:
                    writer.writerow({
                        "original_path": match.original_path,
                        "proposed_path": match.proposed_path,
                        "action_type": match.action_type,
                        "rule_id": match.rule_id or "",
                        "reason": match.reason,
                        "original_filename": match.original_filename,
                        "new_filename": match.new_filename,
                    })
            print(f"\nProposed {len(rename_matches)} renames. Saved to {args.output}")

        # PREVIEW
        print("\nRename preview:")
        if rename_matches:
            for match in rename_matches[:10]:
                if match.action_type == "rename":
                    print(f"  RENAME  {match.original_path}")
                    print(f"          -> {match.new_filename}")
                else:
                    print(f"  MOVE+REN  {match.original_path}")
                    print(f"          -> {match.proposed_path}")
                print(f"          {match.reason}")
            if len(rename_matches) > 10:
                print(f"  ... and {len(rename_matches) - 10} more.")
        else:
            print("  No renames proposed.")
    finally:
        store.close()
    return 0


def _run_execute(args) -> int:
    """Execute approved file moves and renames."""
    store = AuditStore()
    try:
        # DETERMINE PROFILE ID
        profile_id = None
        if args.profile:
            loaded = load_profile_by_name(store, args.profile)
            if loaded is None:
                print(f"Error: Profile '{args.profile}' not found.", file=sys.stderr)
                return 1
            profile_id = loaded.profile_id
        # CHECK FOR APPROVED ACTIONS
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
        # PREPARE AND EXECUTE
        from .journal import prepare_execution, run_execution
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


def _run_undo(args) -> int:
    """Undo the last executed batch of file moves."""
    store = AuditStore()
    try:
        # DETERMINE PROFILE ID
        profile_id = None
        if args.profile:
            loaded = load_profile_by_name(store, args.profile)
            if loaded is None:
                print(f"Error: Profile '{args.profile}' not found.", file=sys.stderr)
                return 1
            profile_id = loaded.profile_id
        # FIND LATEST COMPLETED BATCH
        from .journal import undo_last_batch
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


if __name__ == "__main__":
    raise SystemExit(main())
