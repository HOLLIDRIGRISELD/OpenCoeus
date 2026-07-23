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
    load_profile,
    load_profile_by_name,
    update_profile,
)
from .rules_engine import RulesEngine


def main() -> int:
    command_parser = argparse.ArgumentParser(description="OpenCoeus offline scan and organization (never modifies files without approval).")
    command_subparsers = command_parser.add_subparsers(dest="command", required=True)

    # SCAN COMMAND: THE ORIGINAL STAGE 1 NON-DESTRUCTIVE AUDIT.
    scan_command = command_subparsers.add_parser("scan", help="Create a non-destructive audit manifest.")
    scan_command.add_argument("folder", type=Path)
    scan_command.add_argument("--output", type=Path, default=Path("opencoeus-manifest.csv"))
    scan_command.add_argument("--no-document-text", action="store_true")
    scan_command.add_argument("--profile", type=str, default=None, help="Scan profile name to apply settings from.")

    # PROFILE COMMAND: MANAGE SCAN PROFILES.
    profile_command = command_subparsers.add_parser("profile", help="Manage scan profiles.")
    profile_subparsers = profile_command.add_subparsers(dest="profile_action", required=True)
    profile_list_cmd = profile_subparsers.add_parser("list", help="List all saved profiles.")
    profile_create_cmd = profile_subparsers.add_parser("create", help="Create a new scan profile.")
    profile_create_cmd.add_argument("name", type=str, help="Profile name.")
    profile_create_cmd.add_argument("--root", type=str, default="", help="Default root folder path.")
    profile_delete_cmd = profile_subparsers.add_parser("delete", help="Delete a scan profile.")
    profile_delete_cmd.add_argument("name", type=str, help="Profile name to delete.")
    profile_show_cmd = profile_subparsers.add_parser("show", help="Show profile details.")
    profile_show_cmd.add_argument("name", type=str, help="Profile name to show.")

    # CLASSIFY COMMAND: RUN PHASE ONE FOLDER CLASSIFICATION.
    classify_command = command_subparsers.add_parser("classify", help="Classify folders in a directory tree.")
    classify_command.add_argument("folder", type=Path)
    classify_command.add_argument("--output", type=Path, default=None, help="Save classifications to JSON file.")
    classify_command.add_argument("--max-depth", type=int, default=5, help="Maximum folder tree depth.")

    # ORGANIZE COMMAND: RUN RULES ENGINE AND PROPOSE FILE ACTIONS.
    organize_command = command_subparsers.add_parser("organize", help="Propose file organization actions using rules.")
    organize_command.add_argument("folder", type=Path)
    organize_command.add_argument("--output", type=Path, default=Path("opencoeus-actions.csv"))
    organize_command.add_argument("--no-document-text", action="store_true")
    organize_command.add_argument("--profile", type=str, default=None, help="Profile name to use for rules.")
    organize_command.add_argument("--rules-file", type=Path, default=None, help="JSON file with rule definitions.")

    command_arguments = command_parser.parse_args()

    if command_arguments.command == "scan":
        return _run_scan(command_arguments)
    if command_arguments.command == "profile":
        return _run_profile(command_arguments)
    if command_arguments.command == "classify":
        return _run_classify(command_arguments)
    if command_arguments.command == "organize":
        return _run_organize(command_arguments)
    return 0


def _run_scan(args) -> int:
    if not args.folder.is_dir():
        print(f"Error: Not a readable folder: {args.folder}", file=sys.stderr)
        return 1
    extract_documents = not args.no_document_text
    settings = ScanSettings(args.folder, extract_documents=extract_documents)
    scan_engine = ScanEngine(settings)
    scan_result = scan_engine.run(print)
    write_manifest(scan_result, args.output)
    print(f"Scanned {len(scan_result.rows)} files; found {scan_result.duplicate_count} duplicates. Manifest: {args.output}")
    for scan_error in scan_result.errors:
        print(f"WARNING: {scan_error}")
    return 0


def _run_profile(args) -> int:
    store = AuditStore()
    if args.profile_action == "list":
        profiles = list_profiles(store)
        if not profiles:
            print("No profiles saved.")
        for profile in profiles:
            print(f"  {profile.name}  root={profile.root_path}  extract_docs={profile.document_extraction}")
        store.close()
        return 0
    if args.profile_action == "create":
        created = create_profile(store, args.name, root_path=args.root)
        print(f"Created profile '{created.name}' (id={created.profile_id}).")
        store.close()
        return 0
    if args.profile_action == "delete":
        profile = load_profile_by_name(store, args.name)
        if profile is None:
            print(f"Error: Profile '{args.name}' not found.", file=sys.stderr)
            store.close()
            return 1
        delete_profile(store, profile.profile_id)
        print(f"Deleted profile '{args.name}'.")
        store.close()
        return 0
    if args.profile_action == "show":
        profile = load_profile_by_name(store, args.name)
        if profile is None:
            print(f"Error: Profile '{args.name}' not found.", file=sys.stderr)
            store.close()
            return 1
        print(f"Name: {profile.name}")
        print(f"Root: {profile.root_path}")
        print(f"Included: {profile.included_folders}")
        print(f"Excluded: {profile.excluded_folders}")
        print(f"Custom patterns: {profile.custom_protected_patterns}")
        print(f"Document extraction: {profile.document_extraction}")
        store.close()
        return 0
    return 0


def _run_classify(args) -> int:
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
    if not args.folder.is_dir():
        print(f"Error: Not a readable folder: {args.folder}", file=sys.stderr)
        return 1
    extract_documents = not args.no_document_text
    settings = ScanSettings(args.folder, extract_documents=extract_documents)
    scan_engine = ScanEngine(settings)
    scan_result = scan_engine.run(print)
    rules = []
    if args.rules_file and args.rules_file.is_file():
        with args.rules_file.open(encoding="utf-8") as rules_json:
            rules = json.load(rules_json)
    profile = ProfileConfig()
    if args.profile:
        store = AuditStore()
        loaded = load_profile_by_name(store, args.profile)
        if loaded is None:
            print(f"Warning: Profile '{args.profile}' not found. Using defaults.", file=sys.stderr)
        else:
            profile = loaded
        store.close()
    rules_engine = RulesEngine(profile)
    matches = rules_engine.evaluate(scan_result.rows, rules)
    if matches:
        import csv
        with args.output.open("w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["original_path", "proposed_path", "action_type", "rule_id", "reason"])
            writer.writeheader()
            for match in matches:
                writer.writerow({
                    "original_path": match.original_path,
                    "proposed_path": match.proposed_path,
                    "action_type": match.action_type,
                    "rule_id": match.rule_id or "",
                    "reason": match.reason,
                })
        print(f"Proposed {len(matches)} actions. Saved to {args.output}")
    else:
        print("No actions proposed. Add rules via --rules-file to organize files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
