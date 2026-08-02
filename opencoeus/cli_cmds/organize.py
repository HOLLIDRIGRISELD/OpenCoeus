from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from ..config import ScanSettings
from ..core.folder_classifier import classify_tree
from ..core.folder_tree import build_folder_tree
from ..db import AuditStore
from ..engine import ManifestRow, ScanEngine
from ..llm import build_llm_engine
from ..profiles import ProfileConfig, load_profile_by_name
from ..rules import DEFAULT_RULES, RulesEngine


def run_organize(args) -> int:
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
        excluded_folders = {
            c["folder_path"] for c in classifications
            if c["recommended_action"] == "exclude"
        }
        print(f"  Excluded {len(excluded_folders)} folders automatically.")

        print("Phase 2: Scanning files...")
        scan_engine = ScanEngine(settings, store)
        scan_result = scan_engine.run_phase_two(excluded_folders, print)
        print(f"  Scanned {len(scan_result.rows)} files, found {scan_result.duplicate_count} duplicates.")

        rules_engine = RulesEngine(profile, scan_root=settings.root.as_posix(), llm_engine=build_llm_engine(profile))
        matches = rules_engine.evaluate(scan_result.rows, rules)

        if args.rename_template and matches:
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


def run_rename(args) -> int:
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

        rules_engine = RulesEngine(profile, scan_root=settings.root.as_posix(), llm_engine=build_llm_engine(profile))
        matches = rules_engine.evaluate(scan_result.rows, rules)

        rename_matches = [m for m in matches if m.action_type in {"rename", "move+rename"}]

        if args.rename_template and rename_matches:
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
