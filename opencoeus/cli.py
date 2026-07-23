from __future__ import annotations

import argparse
from pathlib import Path

from .config import ScanSettings
from .engine import ScanEngine, write_manifest


def main() -> int:
    command_parser = argparse.ArgumentParser(description="OpenCoeus offline scan (never modifies source files).")
    command_subparsers = command_parser.add_subparsers(dest="command", required=True)
    scan_command = command_subparsers.add_parser("scan", help="Create a non-destructive audit manifest.")
    scan_command.add_argument("folder", type=Path)
    scan_command.add_argument("--output", type=Path, default=Path("opencoeus-manifest.csv"))
    scan_command.add_argument("--no-document-text", action="store_true")
    command_arguments = command_parser.parse_args()
    if not command_arguments.folder.is_dir():
        command_parser.error(f"Not a readable folder: {command_arguments.folder}")

    # CREATES A REVIEW-ONLY MANIFEST WITHOUT MODIFYING THE SELECTED FOLDER.
    scan_engine = ScanEngine(
        ScanSettings(command_arguments.folder, extract_documents=not command_arguments.no_document_text)
    )
    scan_result = scan_engine.run(print)
    write_manifest(scan_result, command_arguments.output)
    print(f"Scanned {len(scan_result.rows)} files; found {scan_result.duplicate_count} duplicates. Manifest: {command_arguments.output}")
    for scan_error in scan_result.errors:
        print(f"WARNING: {scan_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
