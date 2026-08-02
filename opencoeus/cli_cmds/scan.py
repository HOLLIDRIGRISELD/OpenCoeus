from __future__ import annotations

import json
import sys

from ..config import ScanSettings
from ..core.folder_classifier import classify_tree
from ..core.folder_tree import build_folder_tree
from ..db import AuditStore
from ..engine import ScanEngine, write_manifest
from ..profiles import ProfileConfig, load_profile_by_name


def run_scan(args) -> int:
    if not args.folder.is_dir():
        print(f"Error: Not a readable folder: {args.folder}", file=sys.stderr)
        return 1
    extract_documents = not args.no_document_text
    store = AuditStore()
    try:
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


def run_classify(args) -> int:
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
