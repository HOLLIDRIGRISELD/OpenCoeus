"""Command-line interface for OpenCoeus.

The CLI exposes the same services as the desktop application, which makes the
pipeline scriptable for evaluation and reproducible demos::

    opencoeus scan ~/Documents --recursive
    opencoeus analyse --no-llm
    opencoeus plan --save
    opencoeus execute 3 --yes
    opencoeus search "invoice from March" --mode hybrid

Every destructive command requires confirmation unless ``--yes`` is supplied.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import dataclasses
import json
import sys
from datetime import date, datetime
from pathlib import Path

from app.core.config import AppConfig
from app.core.constants import APP_NAME, APP_VERSION
from app.core.exceptions import (
    DatabaseError,
    InvalidRecommendationError,
    OpenCoeusError,
)
from app.core.progress import ProgressEvent
from app.demo import create_sample_library
from app.services.context import AppContext


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=_json_default, ensure_ascii=False))


def _progress(event: ProgressEvent) -> None:
    total = f"/{event.total}" if event.total else ""
    message = event.message or event.phase
    print(f"  [{event.phase}] {event.current}{total} {message}")


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def cmd_scan(args: argparse.Namespace, ctx: AppContext) -> int:
    override = ctx.profiles.get_by_name(args.profile) if args.profile else None
    selected = override or ctx.profiles.active()
    root_arg = args.path or (selected.root_path if selected else None)
    if not root_arg:
        print("No scan path supplied and no active profile is set.", file=sys.stderr)
        return 2
    root = Path(root_arg).expanduser()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2
    report = ctx.scanning.scan(
        root,
        recursive=args.recursive,
        include_unsupported=args.include_unsupported,
        max_files=args.max_files,
        compute_hashes=not args.no_hash,
        progress=_progress,
        profile=override,
    )
    print(
        f"Scanned {report.total} files: {report.created} new, {report.updated} refreshed, "
        f"{report.unsupported} unsupported, {report.failed} failed in "
        f"{report.duration_seconds:.1f}s"
    )
    if report.errors:
        for path, message in report.errors[:10]:
            print(f"  ! {path}: {message}", file=sys.stderr)
    print(f"Organisation root: {ctx.organisation.organisation_root()}")
    print("Next: opencoeus analyse")
    return 0


def cmd_analyse(args: argparse.Namespace, ctx: AppContext) -> int:
    report = ctx.analysis.analyse_pending(
        limit=args.limit,
        use_llm=not args.no_llm,
        force=args.force,
        progress=_progress,
    )
    print(report.summary())
    print(f"  {report.pending_review} file(s) need human review; {report.llm_used} used the local model.")
    if report.errors:
        for file_id, message in report.errors[:10]:
            print(f"  ! file {file_id}: {message}", file=sys.stderr)
    return 0


def cmd_search(args: argparse.Namespace, ctx: AppContext) -> int:
    response = ctx.search.search(args.query, mode=args.mode, limit=args.limit)
    if args.json:
        _print_json(dataclasses.asdict(response))
        return 0
    print(f'Search "{response.query}" ({response.mode}) in {response.took_ms:.1f} ms')
    if not response.hits:
        print("  No matches.")
    for index, hit in enumerate(response.hits, start=1):
        print(f"  {index:>2}. {hit.filename}  [{hit.mode}, {hit.match_percent}%]")
        print(f"      {hit.path}")
        if hit.category:
            print(f"      category: {hit.category}")
        if hit.snippet:
            print(f"      … {hit.snippet[:220]}")
    for note in response.notes:
        print(f"  note: {note}")
    return 0


def cmd_stats(args: argparse.Namespace, ctx: AppContext) -> int:
    stats = ctx.stats()
    if args.json:
        _print_json(dataclasses.asdict(stats))
        return 0
    print(f"{APP_NAME} {APP_VERSION}")
    print(f"  Files:           {stats.total_files}")
    print(f"  Size:            {_human_bytes(stats.total_bytes)}")
    print(f"  Analysed:        {stats.analysed}")
    print(f"  Pending review:  {stats.pending_review}")
    print(f"  Organised:       {stats.organised}")
    print(f"  Failed:          {stats.failed}")
    print(f"  Duplicate sets:  {stats.duplicates}")
    if stats.categories:
        print("  Categories:")
        for category, count in sorted(stats.categories.items(), key=lambda item: -item[1]):
            print(f"    {category:<20} {count}")
    if stats.recent_operations:
        print("  Recent operations:")
        for operation in stats.recent_operations[:5]:
            print(f"    #{operation.id} {operation.status:<10} {operation.filename}")
    return 0


def cmd_duplicates(args: argparse.Namespace, ctx: AppContext) -> int:
    groups = ctx.duplicates()
    if args.json:
        _print_json(
            [
                {"sha256": group.sha256, "files": group.files, "wasted_bytes": group.wasted_bytes}
                for group in groups
            ]
        )
        return 0
    if not groups:
        print("No duplicate files found.")
        return 0
    print(f"{len(groups)} duplicate group(s):")
    for index, group in enumerate(groups, start=1):
        print(f"  {index}. {group.sha256[:16]}… ({group.count} copies, "
              f"{_human_bytes(group.wasted_bytes)} redundant)")
        for item in group.files:
            print(f"      {item['path']}")
    return 0


def cmd_plan(args: argparse.Namespace, ctx: AppContext) -> int:
    previews = ctx.organisation.build_preview(
        limit=args.limit, accepted_only=args.accepted_only
    )
    draft = previews.draft
    summary = draft.summary
    if args.json:
        payload = {
            "root": str(draft.root),
            "summary": dataclasses.asdict(summary),
            "actions": [
                {
                    "file_id": action.file_id,
                    "action": action.action.value,
                    "source": str(action.source_path),
                    "destination": str(action.destination_path),
                    "confidence": action.confidence,
                    "conflict": action.conflict,
                    "notes": action.notes,
                }
                for action in draft.actions
            ],
            "unchanged": draft.unchanged,
            "skipped": draft.skipped,
            "notes": previews.notes,
        }
        if args.save:
            payload["plan_id"] = ctx.organisation.create_plan(
                limit=args.limit, accepted_only=args.accepted_only
            )
        _print_json(payload)
        return 0

    print(f"Plan preview for {draft.root}")
    print(
        f"  {summary.total} action(s): {summary.renames} rename(s), {summary.moves} move(s), "
        f"{summary.new_folders} new folder(s), {summary.conflicts} conflict(s), "
        f"{summary.needs_review} below review threshold"
    )
    for action in draft.actions:
        marker = "!" if action.conflict else "✓"
        print(f"  {marker} {action.action.value:<16} {action.destination_path}")
        if action.conflict:
            print(f"      blocked: {action.conflict}")
    if draft.unchanged:
        print(f"  {len(draft.unchanged)} file(s) already in the right place.")
    for note in dict.fromkeys(previews.notes):
        print(f"  note: {note}")
    if not args.save:
        print("Preview only; pass --save to create an approvable plan.")
        return 0
    if not draft.actions:
        print("Nothing to save.", file=sys.stderr)
        return 1
    plan_id = ctx.organisation.create_plan(limit=args.limit, accepted_only=args.accepted_only)
    print(f"Saved plan #{plan_id}. Next: opencoeus execute {plan_id} --yes")
    return 0


def cmd_revalidate(args: argparse.Namespace, ctx: AppContext) -> int:
    """Return an interrupted plan to draft so it can be approved and retried."""

    try:
        summary = ctx.organisation.revalidate(args.plan_id)
    except InvalidRecommendationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"Plan #{args.plan_id} is a draft again: {summary.total} action(s), "
        f"{summary.conflicts} conflict(s). Approve it before executing."
    )
    return 0


def cmd_plans(args: argparse.Namespace, ctx: AppContext) -> int:
    plans = ctx.organisation.list_plans(limit=args.limit)
    if args.json:
        _print_json(plans)
        return 0
    if not plans:
        print("No plans yet.")
        return 0
    print(f"{'ID':>4}  {'STATUS':<22} {'ITEMS':>5}  ROOT")
    for plan in plans:
        print(
            f"{plan['id']:>4}  {str(plan['status']):<22} {plan['item_count']:>5}  "
            f"{plan['root_path']}"
        )
    return 0


def cmd_execute(args: argparse.Namespace, ctx: AppContext) -> int:
    plan = ctx.organisation.plan(args.plan_id)
    if plan is None:
        print(f"Plan {args.plan_id} was not found.", file=sys.stderr)
        return 2
    items = ctx.organisation.items(args.plan_id)
    summary = ctx.organisation.summary(args.plan_id)
    print(
        f"Plan #{args.plan_id}: {len(items)} item(s), {summary.conflicts} conflict(s), "
        f"status {plan['status']}"
    )
    if not args.yes and not _confirm("Apply this plan to the filesystem?"):
        print("Aborted; nothing changed.")
        return 1
    if getattr(args, "staged", False):
        if plan["status"] == "draft":
            ctx.organisation.approve(args.plan_id)
        result = ctx.organisation.execute_batch(args.plan_id, progress=_progress)
        print(
            f"Staged batch finished: {result.state} "
            f"({len(result.completed)} completed, {len(result.failed)} failed)"
        )
        return 0 if result.state == "COMPLETED" else 1
    report = ctx.organisation.approve_and_execute(args.plan_id, progress=_progress)
    print(f"Execution finished: {report.summary} in {report.duration_seconds:.1f}s")
    for result in report.failed:
        print(f"  ! {result.source_path}: {result.message}", file=sys.stderr)
    for result in report.skipped:
        print(f"  - {result.source_path}: {result.message}")
    return 0 if not report.failed else 1


def cmd_history(args: argparse.Namespace, ctx: AppContext) -> int:
    operations = ctx.recovery.history(limit=args.limit, status=args.status)
    if args.json:
        _print_json([dataclasses.asdict(operation) for operation in operations])
        return 0
    if not operations:
        print("No operations yet.")
        return 0
    print(f"{'ID':>4}  {'STATUS':<12} {'TYPE':<16} {'UNDO':<5} FILE")
    for operation in operations:
        print(
            f"{operation.id:>4}  {operation.status:<12} {operation.operation_type:<16} "
            f"{'yes' if operation.undoable else 'no':<5} {operation.filename}"
        )
    return 0


def cmd_undo(args: argparse.Namespace, ctx: AppContext) -> int:
    if args.list or args.operation_id is None:
        operations = ctx.recovery.undoable()
        if not operations:
            print("Nothing can be undone.")
            return 0
        print("Undoable operations:")
        for operation in operations:
            print(
                f"  #{operation.id} {operation.filename} "
                f"({operation.source_path} → {operation.destination_path})"
            )
        if args.operation_id is None:
            print("Pass an operation id to undo it.")
        return 0
    if not getattr(args, "yes", False) and not _confirm("Undo this operation?"):
        print("Aborted; nothing changed.")
        return 1
    try:
        result = ctx.recovery.undo(args.operation_id)
    except OpenCoeusError as exc:
        print(exc.user_message, file=sys.stderr)
        return 1
    print(result.message or "Operation undone.")
    return 0


def cmd_backup(args: argparse.Namespace, ctx: AppContext) -> int:
    if args.list:
        backups = ctx.recovery.list_backups()
        if not backups:
            print("No backups yet.")
            return 0
        for backup in backups:
            print(f"  {backup.path}  ({_human_bytes(backup.size)})")
        return 0
    destination = Path(args.destination).expanduser() if args.destination else None
    path = ctx.recovery.backup(destination)
    print(f"Backup written to {path}")
    return 0


def cmd_restore(args: argparse.Namespace, ctx: AppContext) -> int:
    backup = Path(args.backup).expanduser()
    if not backup.is_file():
        print(f"Backup not found: {backup}", file=sys.stderr)
        return 2
    if not args.yes and not _confirm("Replace the live database with this backup?"):
        print("Aborted; nothing changed.")
        return 1
    try:
        ctx.recovery.restore(backup)
    except DatabaseError as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    print("Database restored. Restart OpenCoeus before using it again.")
    return 0


def cmd_doctor(_args: argparse.Namespace, ctx: AppContext) -> int:
    print(f"{APP_NAME} {APP_VERSION}")
    print(f"  Data directory: {ctx.config.data_dir}")
    print(f"  Database:       {ctx.config.db_path}")
    print(f"  Integrity:      {'ok' if ctx.recovery.integrity_check() else 'FAILED'}")
    print(f"  Files indexed:  {ctx.stats().total_files}")
    print("  Capabilities:")
    for capability in ctx.capabilities(probe=True):
        status = "yes" if capability.available else ("required" if capability.required else "no")
        print(f"    {capability.label:<22} {status:<8} {capability.detail}")
    print("  Fallbacks:")
    for key, description in ctx.models.fallbacks.items():
        print(f"    {key:<22} {description}")
    return 0


def cmd_capabilities(_args: argparse.Namespace, ctx: AppContext) -> int:
    for capability in ctx.capabilities(probe=True):
        print(
            f"{capability.label}: "
            f"{'available' if capability.available else 'unavailable'} — {capability.detail}"
        )
    return 0


def cmd_root(args: argparse.Namespace, ctx: AppContext) -> int:
    if args.path:
        root = Path(args.path).expanduser().resolve()
        if not root.is_dir():
            print(f"Not a directory: {root}", file=sys.stderr)
            return 2
        problems = ctx.set_organisation_root(root)
        if problems:
            print(problems[0], file=sys.stderr)
            return 1
        print(f"Organisation root set to {root}")
        return 0
    print(ctx.organisation.organisation_root())
    return 0


def cmd_demo(args: argparse.Namespace, ctx: AppContext) -> int:
    destination = Path(args.path).expanduser()
    created = create_sample_library(destination)
    print(f"Created {len(created)} sample file(s) in {destination}")
    if args.scan:
        report = ctx.scanning.scan(destination, include_unsupported=True)
        print(f"Scanned: {report.summary()}")
        analysis = ctx.analysis.analyse_pending(use_llm=False)
        print(f"Analysed: {analysis.summary()}")
        print("Next: opencoeus plan")
    return 0


def cmd_profile(args: argparse.Namespace, ctx: AppContext) -> int:
    command = args.profile_command
    if command == "list":
        profiles = ctx.profiles.list()
        if not profiles:
            print("No scan profiles yet.")
            return 0
        for profile in profiles:
            print(
                f"{profile.name}\t{profile.root_path}\t"
                f"include={','.join(profile.included_folders) or 'all'}\t"
                f"exclude={','.join(profile.excluded_folders) or 'none'}\t"
                f"patterns={','.join(profile.custom_patterns) or 'none'}"
            )
        return 0

    if command == "add":
        profile_id = ctx.profiles.add(
            args.name,
            str(Path(args.root).expanduser()),
            args.included,
            args.excluded,
            args.patterns,
        )
        print(f"Profile {args.name} added as #{profile_id}.")
        return 0

    profile = ctx.profiles.get_by_name(args.name)
    if profile is None:
        print(f"Profile {args.name} was not found.", file=sys.stderr)
        return 2
    if command == "apply":
        ctx.profiles.set_active(profile.id)
        print(f"Active profile: {profile.name}")
        return 0
    if not getattr(args, "yes", False) and not _confirm(f"Delete profile {profile.name}?"):
        print("Aborted; nothing changed.")
        return 1
    ctx.profiles.delete(profile.id)
    print(f"Profile {profile.name} deleted.")
    return 0


MANIFEST_FIELDS = (
    "path",
    "name",
    "size_bytes",
    "sha256",
    "status",
    "category",
    "modified_at",
    "last_planned_action",
    "last_operation_status",
)


def cmd_manifest(args: argparse.Namespace, ctx: AppContext) -> int:
    output = Path(args.output).expanduser()
    yes = getattr(args, "yes", False)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = ctx.files.manifest_rows()
    try:
        handle = output.open("w" if yes else "x", encoding="utf-8", newline="")
    except FileExistsError:
        print(f"Manifest already exists: {output}. Pass --yes to overwrite.", file=sys.stderr)
        return 1
    with handle:
        writer = csv.DictWriter(handle, fieldnames=list(MANIFEST_FIELDS))
        writer.writeheader()
        writer.writerows(dataclasses.asdict(row) for row in rows)
    print(f"Wrote {len(rows)} row(s) to {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opencoeus",
        description="Local-first hybrid AI file organisation and document retrieval.",
    )
    parser.add_argument("--data-dir", type=Path, help="Override the application data directory.")
    parser.add_argument("--log-level", default=None, help="Logging level (DEBUG, INFO, WARNING).")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")

    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Register files from a folder.")
    scan.add_argument("path", nargs="?")
    scan.add_argument("--profile", help="Use this profile for this scan only.")
    scan.add_argument("--no-recursive", dest="recursive", action="store_false")
    scan.add_argument("--include-unsupported", action="store_true")
    scan.add_argument("--max-files", type=int, default=0)
    scan.add_argument("--no-hash", action="store_true")
    scan.set_defaults(handler=cmd_scan)

    analyse = sub.add_parser("analyse", help="Extract, classify and recommend.")
    analyse.add_argument("--limit", type=int, default=None)
    analyse.add_argument(
        "--force", action="store_true", help="Re-analyse files already analysed or awaiting review."
    )
    analyse.add_argument("--no-llm", action="store_true", help="Do not contact the local LLM.")
    analyse.set_defaults(handler=cmd_analyse)

    search = sub.add_parser("search", help="Search indexed documents.")
    search.add_argument("query")
    search.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="hybrid")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=cmd_search)

    stats = sub.add_parser("stats", help="Show library statistics.")
    stats.add_argument("--json", action="store_true")
    stats.set_defaults(handler=cmd_stats)

    manifest = sub.add_parser(
        "manifest",
        help="Export a read-only CSV audit manifest; write the output outside the scanned library.",
    )
    manifest.add_argument("--output", required=True, type=Path, help="CSV destination path.")
    manifest.add_argument("--yes", action="store_true", help="Overwrite an existing manifest.")
    manifest.set_defaults(handler=cmd_manifest)

    duplicates = sub.add_parser("duplicates", help="Find identical files by SHA-256.")
    duplicates.add_argument("--json", action="store_true")
    duplicates.set_defaults(handler=cmd_duplicates)

    profile = sub.add_parser("profile", help="Manage named scan profiles.")
    profile.set_defaults(handler=cmd_profile)
    profile_actions = profile.add_subparsers(dest="profile_command", required=True)
    profile_actions.add_parser("list", help="List saved profiles.")
    profile_add = profile_actions.add_parser("add", help="Save a profile.")
    profile_add.add_argument("name")
    profile_add.add_argument("root")
    profile_add.add_argument("--include", dest="included", action="append", default=[])
    profile_add.add_argument("--exclude", dest="excluded", action="append", default=[])
    profile_add.add_argument("--pattern", dest="patterns", action="append", default=[])
    profile_apply = profile_actions.add_parser("apply", help="Set the active profile.")
    profile_apply.add_argument("name")
    profile_delete = profile_actions.add_parser("delete", help="Delete a profile.")
    profile_delete.add_argument("name")
    profile_delete.add_argument("--yes", action="store_true")

    plan = sub.add_parser("plan", help="Preview (and optionally save) an organisation plan.")
    plan.add_argument("--limit", type=int, default=500)
    plan.add_argument("--accepted-only", action="store_true")
    plan.add_argument("--save", action="store_true")
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(handler=cmd_plan)

    plans = sub.add_parser("plans", help="List saved plans.")
    plans.add_argument("--limit", type=int, default=50)
    plans.add_argument("--json", action="store_true")
    plans.set_defaults(handler=cmd_plans)

    revalidate = sub.add_parser(
        "revalidate", help="Recheck an interrupted plan so it can be approved again."
    )
    revalidate.add_argument("plan_id", type=int)
    revalidate.set_defaults(handler=cmd_revalidate)

    execute = sub.add_parser("execute", help="Approve and apply a saved plan.")
    execute.add_argument("plan_id", type=int)
    execute.add_argument("--yes", action="store_true")
    execute.add_argument("--staged", action="store_true", help="Move through a holding area.")
    execute.set_defaults(handler=cmd_execute)

    history = sub.add_parser("history", help="Show the operation history.")
    history.add_argument("--limit", type=int, default=100)
    history.add_argument("--status")
    history.add_argument("--json", action="store_true")
    history.set_defaults(handler=cmd_history)

    undo = sub.add_parser("undo", help="Undo a completed operation.")
    undo.add_argument("operation_id", type=int, nargs="?")
    undo.add_argument("--list", action="store_true")
    undo.add_argument("--yes", action="store_true")
    undo.set_defaults(handler=cmd_undo)

    backup = sub.add_parser("backup", help="Create or list database backups.")
    backup.add_argument("destination", nargs="?")
    backup.add_argument("--list", action="store_true")
    backup.set_defaults(handler=cmd_backup)

    restore = sub.add_parser("restore", help="Restore the database from a backup.")
    restore.add_argument("backup")
    restore.add_argument("--yes", action="store_true")
    restore.set_defaults(handler=cmd_restore)

    doctor = sub.add_parser("doctor", help="Diagnose configuration, models and integrity.")
    doctor.set_defaults(handler=cmd_doctor)

    capabilities = sub.add_parser("capabilities", help="List local AI capabilities.")
    capabilities.set_defaults(handler=cmd_capabilities)

    root = sub.add_parser("root", help="Show or set the organisation root.")
    root.add_argument("path", nargs="?")
    root.set_defaults(handler=cmd_root)

    demo = sub.add_parser("demo", help="Create a sample library for demos.")
    demo.add_argument("path", nargs="?", default="OpenCoeus-Demo")
    demo.add_argument("--scan", action="store_true", help="Scan and analyse immediately.")
    demo.set_defaults(handler=cmd_demo)

    return parser


def _configure_console() -> None:
    """Use UTF-8 for CLI output, including on legacy Windows consoles.

    Windows terminals default to a regional code page (for example cp1252) that
    cannot encode the check marks and ellipses used in CLI output. Without this,
    printing a plan would raise ``UnicodeEncodeError`` halfway through.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):  # pragma: no cover - exotic streams
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = AppConfig.load(args.data_dir)
        if args.log_level:
            config.log_level = args.log_level
        with AppContext.create(config, purge=False) as ctx:
            return int(args.handler(args, ctx))
    except OpenCoeusError as exc:
        print(f"{exc.user_message}\n{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
