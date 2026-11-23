# Port selected features from OpenCoeusOLD into current OpenCoeus

Date: 2026-11-22
Status: awaiting approval

## Intent

The user kept an older OpenCoeus implementation on `D:\OpenCoeusOLD` (HEAD `b5cdbad0fecdb48f001ae96e2188a06a178e3fec`, dirty working tree, 58 changed files). A read-only `pullstack` dissection compared that snapshot with the current project. The user chose to take items **1, 3, 4, 5, 6, 7, 8** and to leave item **2 (folder tree UI)** out.

Goal: bring over the behaviour that is genuinely missing here, rewritten in current `app/` idioms, without weakening the measured speed work or the locked analysis quality.

## Goals

- Add: named scan profiles (1), richer protected/junk skip rules (3), user-defined organisation rules + editor (4), optional existing-folder naming conventions (5), staged batch execution with a batch lock (6), `OPENCOEUS_DATA_DIR` with read-only fallback (7), CSV audit manifest (8).
- Keep every change testable in isolation, TDD red → green.
- Keep the app launchable after every single item.

## Non-goals

- No folder-tree classification/exclusion UI (item 2, explicitly dropped).
- No old PyQt6 UI, DB schema, packaging, CLI, or extractor code copied over.
- No old GGUF/llama.cpp backend, PDF OCR, audio/video/archive extractors, or prefix-hash duplicate prefilter.
- No migration to Alembic; no changes to existing table columns.

## Anti-goals (what would make this a failure)

- Any change to extractor text for normal files, chunking or the 96-chunk cap, embeddings or precision, classifier weights/formula/evidence, LLM gating or caps, FTS content, duplicate reuse, or model-name cache keys.
- Any new dependency; any processing that leaves the local machine.
- Data loss, silent overwrites, or a deleted user folder.
- A single large diff that cannot be reverted cleanly.

## Constraints

- Quality lock is enforced by `tests/test_quality_gate.py:19,70-127` with `tests/fixtures/quality_golden.json`. `OPENCOEUS_WRITE_GOLDEN=1` must not remain set.
- Cache key is `sha256_text(f"{content_hash}|{extractor_version}|{prefix}")` at `app/services/analysis_service.py:337-353,588-605`; prefix is `CHUNKER_VERSION|embedding_model|prefer_transformer|CLASSIFIER_VERSION|low_confidence|high_confidence`. Profile names, rules, conventions, and CSV exports must never enter it.
- New tables are created by `Base.metadata.create_all()` at `app/infrastructure/database.py:114-123`; `create_all()` does not alter existing tables (`docs/DECISIONS.md:68-70`). All ORM models live in `app/infrastructure/models.py:35-37`.
- `purge_session_data()` deletes an explicit list of session tables at `app/infrastructure/database.py:125-163`; new tables must be deliberately classified as persistent or session-scoped.
- No-overwrite guarantees live in `app/organisation/fsops.py:30-42,86-157` and `app/organisation/validator.py:66-235`; every moved file must keep using them.
- Verification after each item:
  - `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest`
  - `.venv\Scripts\python.exe -m ruff check app tests main.py`
  - `.venv\Scripts\python.exe -m compileall -q app tests main.py`
- No git repo in this workspace. No worktree/branch isolation is possible; before the first edit, copy `app/`, `tests/`, `main.py`, `pyproject.toml`, `docs/` to `C:\Users\seldi\AppData\Local\Temp\opencode\pre-port-snapshot\`. Restore from that snapshot only on explicit user approval.
- Code comments: no prose comments; docstrings only where the project already uses them.

## Licence

Old `pyproject.toml:10,18` declares MIT; no `LICENSE` file in the old tree. Current `LICENSE:1-21` is MIT. Route: code may be copied with notice, but the chosen route is **reimplement** — fresh code against current helpers, no upstream text, no upstream imports. Not legal advice.

## Approaches

**A — Sequential per feature (chosen).** Order 7 → 3 → 1 → 4 → 5 → 6 → 8, smallest dependency first. Each item gets one failing test set, one implementation slice, full verification, then a review before the next item. Smallest blast radius, clearest rollback, suits a non-git workspace.

**B — Three layer groups (rejected).** Config/data (7,3,1), organisation (4,6), naming/export (5,8). Fewer integration rounds but large diffs that hide which change broke the golden gate.

**C — Parallel agents (rejected).** Features touch shared `models.py`, settings, UI registry, and tests; concurrent edits would conflict and weaken review.

## Design by item

### 7. `OPENCOEUS_DATA_DIR` override + read-only fallback

- `AppConfig.load(data_dir)` at `app/core/config.py:125-173` currently resolves base dir from the explicit argument or `default_data_dir()` (`app/core/config.py:24-33`), then reads `<base>/config.json`. Resolution becomes: explicit `data_dir` argument → `OPENCOEUS_DATA_DIR` → `config.json` `data_dir` → `default_data_dir()`. When the caller or env supplied the dir, that value wins over `config.json`; otherwise the JSON value still applies.
- Fix the existing derivation bug: `db_url` is computed at `app/core/config.py:132-133` before the JSON merge, so a JSON `data_dir` override leaves `db_url` pointing at the old dir. Recompute `db_url` after merging when it was not explicitly supplied.
- Read-only fallback: if the chosen directory cannot be created or written, fall back to `default_data_dir()` and emit one warning through `logging` after config resolution. If the fallback is also unwritable, raise `ConfigurationError`. `AppConfig.load()` currently lets raw `OSError` escape; wrap it.
- Keep the CLI `--data-dir` flag (`app/cli.py:414`) and `AppContext.create(data_dir=...)` (`app/services/context.py:119-130`) working unchanged. GUI keeps calling `AppContext.create()` with no override and therefore picks up the env var.
- Do not add a true no-write runtime mode: `ensure_directories()` (`app/core/config.py:119-123`), logging (`app/core/logging_config.py:35-58`), WAL pragmas and `create_all()` (`app/infrastructure/database.py:55-67,114-123`) all require write access. Falling back to a writable dir is the whole feature.
- Tests: env override, precedence over `config.json`, fallback on unwritable dir, unchanged derived `db_url`, clear error on doubly-unwritable config. No analysis paths touched.

### 3. Richer protected-folder and OS junk skip rules

- Extend `AppConfig.excluded_directories` (`app/core/config.py:71-79`) with the OS/common protected names identified in the old config, keeping the current seven. Keep `PathGuard` and no-overwrite semantics untouched.
- Extend `app/processing/scanner.py:31-37` junk rules with `thumbs.db`, `desktop.ini`, `.DS_Store` and a `._` filename prefix. Add a `_EXCLUDED_NAME_PREFIXES` tuple next to the existing suffix tuple; apply it in the same pre-`describe_file()` block at `app/processing/scanner.py:173-175`, so bloat still never reaches extraction (`tests/test_scan_filtering.py:16-36`).
- Add `ScanOptions.custom_patterns` (`app/processing/scanner.py:40-68`) as `fnmatch` patterns for directory basenames and filenames. Match case-insensitively on Windows. Keep directory exclude path resolution at `app/processing/scanner.py:161-163` and file exclude at `:170-172` unchanged.
- Profile custom patterns from item 1 feed this field; no production caller means an empty tuple today.
- Tests: each new junk name skipped with `include_unsupported=False`, a real document with a `._` prefix skipped, custom pattern excludes a directory and a file, a supported PDF-named `.dat` is still detected (`tests/test_scan_filtering.py:52-62`), golden output unchanged.

### 1. Named scan profiles

- New `ScanProfile` table in `app/infrastructure/models.py`: `id`, unique `name`, `root_path`, `included_folders` JSON, `excluded_folders` JSON, `custom_patterns` JSON, timestamps. No LLM fields and no naming-strategy field — the report's `llm_enabled`/`llm_model`/`llm_temperature` and naming strategy would collide with the global LLM client and the locked cache/suggestion behaviour. Existing global naming template stays authoritative.
- New repository following `RuleRepository` (`app/infrastructure/repositories/settings.py:80-138`) and a `ProfileService` wired as `ctx.profiles` in `app/services/context.py:77-96`. Persist across `purge_session_data()` by omitting the table from the delete list at `app/infrastructure/database.py:125-163`.
- `include_folders` becomes an allowlist of directory basenames passed through a new `ScanOptions.included_folders`; empty means today's behaviour. `excluded_folders` merges into `excluded_directory_names`. `custom_patterns` feeds item 3.
- `ScanningService.scan()` (`app/services/scanning_service.py:61-83`) gains an optional `profile` argument; CLI keeps working without one. Keep the current single global organisation root update at `app/services/scanning_service.py:212-213`.
- CLI: `profile list|add|apply|delete` registered next to `stats`/`duplicates` at `app/cli.py:443-449`, using `set_defaults(handler=...)` and `AppContext(..., purge=False)` as `main()` already does at `app/cli.py:537-539`.
- GUI: a small profile selector in the existing Files/scan page using `app/ui/widgets.py:53-95,297-400`; no new navigation entry. Applying a profile sets the scan root plus include/exclude/pattern inputs for the next scan.
- Tests: CRUD, CLI add/apply/delete, scan with include allowlist and custom pattern, profile survives purge, cache key unchanged.

### 4. User-defined organisation rules + editor

- A `Rule` table already exists at `app/infrastructure/models.py:480-497` with `match_field`, `match_op`, `match_value`, `target_folder`, `priority`, `enabled`, and `RuleRepository` CRUD at `app/infrastructure/repositories/settings.py:80-138`, but no evaluator or UI consumer. Do **not** alter its columns; `create_all()` cannot migrate them.
- Add a new `OrganisationRule` table for richer rules: `id`, `name`, `priority`, `enabled`, `match_field`, `match_op`, `match_value`, `action`, `folder_template`, `name_template`, timestamps. Leave the old `Rule` table and repository in place untouched (no deletion without the user's approval).
- Pure evaluator in `app/organisation/rules.py`: consumes current `File` fields (path, extension, size, category, status, modified_at) and returns a `(relative_folder, new_name, action)` decision or `None`. `fnmatch`, `datetime` and string operations only; no new deps. Match fields: extension, name pattern, size, category, status, folder, always.
- Inject the evaluator into `OrganisationPlanner` (`app/organisation/planner.py:99-186`) as an optional resolver used only to propose `new_name`/`relative_folder`. Every result still goes through `PathGuard.check_destination`/`check_source` and duplicate-target claiming at `app/organisation/planner.py:134-153`; no direct filesystem call.
- Seed a small default set only when the new table is empty, using the same "insert if absent" pattern as `Database.seed_defaults()` at `app/infrastructure/database.py:215-223`. User edits survive restarts and purge.
- Rule editor: new `app/ui/pages/rules.py` registered in `app/ui/pages/__init__.py:3-20` and `MainWindow._build()` at `app/ui/main_window.py:141-150`; `BasePage`/`Task` from `app/ui/base.py:15-75`, table/form widgets from `app/ui/widgets.py`, save flow mirroring `app/ui/pages/settings.py:306-345`. Add validation before save and surface problems in the status label.
- Tests: evaluator match/no-match and priority, planner integration with collision, CRUD + defaults seeding, offscreen UI add/edit/toggle/delete, golden output unchanged (rules only change plan rows).

### 5. Optional naming-convention detection

- New pure module `app/intelligence/conventions.py`: `detect_convention(existing_names)` detects case style, separator, prefix, date style, numeric suffix and next sequence; `apply_convention(name, convention)` rewrites a generated name. Written fresh from the behaviour described in the old code, not copied.
- Attach as an **opt-in post-pass** after `_folders.recommend()` and `_naming.suggest()` and before `save_suggestions()` in `app/services/analysis_service.py:388-444` and the duplicate-reuse path at `:499-519`. Add setting `naming.use_conventions` default `False` in `SettingsService._DEFAULTS` (`app/services/settings_service.py:13-28`); default off keeps the golden snapshot byte-for-byte identical.
- After rewriting, always re-run `FilenameValidator` (`app/intelligence/naming_engine.py:41-93`) and recheck the destination against existing names and planned targets; never reintroduce a collision (`app/intelligence/naming_engine.py:137-147`, `app/organisation/planner.py:134-138`).
- Populate `Suggestion.evidence`/`explanation` with the detected rule so the UI stays honest (`app/infrastructure/models.py:362-387`).
- Tests: detector on a fixture folder family, default-off golden unchanged, opt-on rewrite with collision fallback, no classifier/LLM/FTS/cache-key change.

### 6. Staged batch execution with holding area and batch lock

- Add `BatchExecution` table: `id`, `plan_id`, `state`, `holding_dir`, timestamps. No changes to `OrganisationPlan`, `PlanItem`, `Operation`, or their columns (`app/infrastructure/models.py:390-477`). Reuse `PlanItem.status` strings for per-item state if they already cover it; otherwise keep per-item state in a second new `BatchExecutionItem` table rather than altering columns. Classify both as session data for `purge_session_data()` at `app/infrastructure/database.py:125-163`.
- Holding dir lives under `data_dir/holding/<batch_id>`, never inside the scanned library. Execution: preflight every entry through `PathGuard` and hash/source checks; move each file to holding with `move_no_overwrite` + `verify_destination` (`app/organisation/fsops.py:30-42,86-157`), record `MOVED_TO_HOLDING`; then move from holding to final destination. On any failure, restore already-held files to their originals with the same primitives and mark `FAILED`. Keep the existing per-operation undo at `app/organisation/recovery.py:51-136` unchanged.
- Store original, holding and final paths in the new table. Do not mutate `PlanEntry.source_path`; executor resolves it through batch state so revalidation still works (`app/organisation/planner.py:125-141`, `app/services/organisation_service.py:295-338`).
- Batch lock: one process-wide `threading.Lock` in `OrganisationService` around `execute()`, plus a DB check for an unfinished `BatchExecution` for the plan. Refuse a second execution instead of interleaving (`app/services/organisation_service.py:218-238,258-288`).
- Stale holding cleanup: on CLI start and `AppContext` startup, list unfinished batches; restore files whose original path is free. If an original is occupied, leave the file in holding and log a warning. Never delete a user file automatically.
- Honest limit: this is best-effort two-phase rollback, not a filesystem transaction. A crash between the two phases is recoverable from persisted state; a crash during a single `move_no_overwrite` is handled by the existing primitive.
- Tests: two-file batch where the second fails → both originals restored, no file loss, state `FAILED`; concurrent execute refused; crash simulation resumes from holding; existing undo still passes.

### 8. CSV audit manifest

- Add `manifest --output <path>` to `app/cli.py` near `stats`/`duplicates` (`app/cli.py:443-449`) using `csv.DictWriter` from the standard library. Resolve output with `.expanduser()` like backup/restore (`app/cli.py:339-349`). Make it clear in `--help` that the output should be outside the scanned library (`.csv` is an accepted input extension at `app/core/config.py:80-91`).
- Read-only query: combine `FileRepository.list_summaries()` (`app/infrastructure/repositories/files.py:108-171`) for path/size/status/category with `light_records()` (`:173-205`) for hash, plus `OperationRepository.plan_items()` (`app/infrastructure/repositories/operations.py:99-122`) for planned action. A single new SELECT is acceptable if it avoids N+1 calls.
- No GUI button in this pass; CLI output is enough and keeps the change small.
- Tests: header + row contents, explicit path outside library, DB unchanged before/after, full suite and golden gate unchanged.

## Decisions made during builder check

1. **Batch execution wraps, not replaces, the current executor.** Add `OrganisationService.execute_batch()` as a separate path used only when staging is requested. It records one `Operation` per item with the original source and final destination, so existing undo at `app/organisation/recovery.py:51-136` still resolves a completed batch. The holding hop is recorded only in the new batch tables. Normal `execute()` stays untouched.
2. **Single instance per `data_dir` is assumed**, matching the current app. The batch lock is process-wide plus a DB state check; stale-holding cleanup runs only at startup where no live batch exists. No PID lease or file lock in this pass. Consequence: running two GUI instances against one DB can defeat the lock — called out as a risk, not solved.
3. **Recoverable states are `PENDING` and `HELD`.** `COMPLETED` is terminal, `FAILED` is terminal with rollback attempted, `ROLLED_BACK` is terminal. Startup cleanup restores only `PENDING`/`HELD`; a `FAILED` batch with a partly completed rollback is logged for manual review, never auto-retried.
4. **Preflight checks existence, size, and full SHA-256 against the stored fingerprint** for every source before any file moves. A stale source fails the whole batch, not just that item; no partial staging starts.
5. **`revalidate()` resolves a `HELD` item through the batch table** to its holding path and uses the stored original hash. A missing holding file becomes a conflict. `PlanItem.source_path` is never mutated.
6. **Organisation rules are opt-in.** Seed no enabled defaults; at most insert disabled example rules when the table is empty. The evaluator is a no-op until the user enables a rule, so existing plan rows and golden analysis stay unchanged.
7. **Rule actions are limited to `MOVE`, `RENAME`, `RENAME_AND_MOVE`** — exactly the action types the planner already derives at `app/organisation/planner.py:155-161`. No `SKIP` action. Template tokens are limited to `{title}`, `{category}`, `{original}`, `{date}`, `{year}`, `{extension}` and validated in the editor.
8. **`profile apply <name>` persists an active-profile setting.** `scan` reads it automatically; `scan --profile <name>` overrides. A profile's `root_path` is used only when `scan` is called without a positional root. Include/exclude/patterns always come from the active profile.
9. **Manifest rows are one per file** with columns `path`, `name`, `size_bytes`, `sha256`, `status`, `category`, `modified_at`, `last_planned_action`, `last_operation_status`. The plan/operation columns come from the newest plan for that file; blank when absent. No multi-plan row explosion.
10. **The Files page gets a read-only active-profile summary**, not new editable include/exclude inputs. Profile editing stays in the CLI. Applying a profile changes the next `ScanOptions`; it does not open an editor in the GUI.

## What is left to the builder

- Exact widget placement for the profile summary and rules page, following the cited page/widget patterns.
- Whether `BatchExecutionItem` is needed after reading `PlanItem.status` at implementation time; prefer reusing existing status strings.
- The precise protected-name list, taken from the old config behaviour, still must not exclude a supported document extension.
- Every item is its own TDD slice with the three verification commands above; no implementation starts before this design is approved.
