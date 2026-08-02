from __future__ import annotations

import argparse
from pathlib import Path

from .cli_cmds.execute import run_execute, run_undo
from .cli_cmds.organize import run_organize, run_rename
from .cli_cmds.profile import run_profile
from .cli_cmds.scan import run_classify, run_scan


def main() -> int:
    command_parser = argparse.ArgumentParser(
        description="OpenCoeus offline scan and organization (never modifies files without approval)."
    )
    command_subparsers = command_parser.add_subparsers(dest="command", required=True)

    scan_command = command_subparsers.add_parser("scan", help="Create a non-destructive audit manifest.")
    scan_command.add_argument("folder", type=Path)
    scan_command.add_argument("--output", type=Path, default=Path("opencoeus-manifest.csv"))
    scan_command.add_argument("--no-document-text", action="store_true")
    scan_command.add_argument("--profile", type=str, default=None, help="Scan profile name to apply settings from.")

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

    classify_command = command_subparsers.add_parser("classify", help="Classify folders in a directory tree.")
    classify_command.add_argument("folder", type=Path)
    classify_command.add_argument("--output", type=Path, default=None, help="Save classifications to JSON file.")
    classify_command.add_argument("--max-depth", type=int, default=5, help="Maximum folder tree depth.")

    organize_command = command_subparsers.add_parser("organize", help="Propose file organization actions using rules.")
    organize_command.add_argument("folder", type=Path)
    organize_command.add_argument("--output", type=Path, default=Path("opencoeus-actions.csv"))
    organize_command.add_argument("--no-document-text", action="store_true")
    organize_command.add_argument("--profile", type=str, default=None, help="Profile name to use for rules.")
    organize_command.add_argument("--rules-file", type=Path, default=None, help="JSON file with rule definitions.")
    organize_command.add_argument("--rename-template", type=str, default=None, help="Override rename template for all rules.")

    rename_command = command_subparsers.add_parser("rename", help="Propose file renames using content-aware rules.")
    rename_command.add_argument("folder", type=Path)
    rename_command.add_argument("--output", type=Path, default=Path("opencoeus-renames.csv"))
    rename_command.add_argument("--no-document-text", action="store_true")
    rename_command.add_argument("--profile", type=str, default=None, help="Profile name to use for rules.")
    rename_command.add_argument("--rules-file", type=Path, default=None, help="JSON file with rule definitions.")
    rename_command.add_argument("--rename-template", type=str, default=None, help="Override rename template for all rules.")
    rename_command.add_argument("--dry-run", action="store_true", help="Preview renames without saving to CSV.")

    execute_command = command_subparsers.add_parser("execute", help="Execute approved file organization actions.")
    execute_command.add_argument("--profile", type=str, default=None, help="Profile name to execute actions for.")
    execute_command.add_argument("--dry-run", action="store_true", help="Show what would be done without executing.")

    undo_command = command_subparsers.add_parser("undo", help="Undo the last executed batch of file moves.")
    undo_command.add_argument("--profile", type=str, default=None, help="Profile name to undo actions for.")

    command_arguments = command_parser.parse_args()

    from .executor import cleanup_stale_holding_folders
    cleanup_stale_holding_folders()

    if command_arguments.command == "scan":
        return run_scan(command_arguments)
    if command_arguments.command == "profile":
        return run_profile(command_arguments)
    if command_arguments.command == "classify":
        return run_classify(command_arguments)
    if command_arguments.command == "organize":
        return run_organize(command_arguments)
    if command_arguments.command == "rename":
        return run_rename(command_arguments)
    if command_arguments.command == "execute":
        return run_execute(command_arguments)
    if command_arguments.command == "undo":
        return run_undo(command_arguments)
    return 0
