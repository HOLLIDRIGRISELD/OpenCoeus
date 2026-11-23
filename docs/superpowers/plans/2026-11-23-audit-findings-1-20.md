# OpenCoeus audit findings 1-20 fix plan

Goal: fix the 20 findings from the delivered read-only audit. Original review findings 1-18 are already fixed and verified; do not redo them.

## Constraints

- TDD: write and watch a failing test before production code; one small regression per risky branch.
- No `OPENCOEUS_WRITE_GOLDEN`; no golden regeneration; no DB/config/user file edits.
- No new dependencies. Minimal diffs. Preserve existing comments unless logic changes.
- Strict file ownership per slice; agents must not touch files owned by another slice.
- Each slice: focused pytest + `ruff check` on touched files. Main session: full pytest, ruff, compileall, quality gate.

## Slice 1 - data safety / CLI / GUI block (findings 1, 5, 6, 7, 8)

Owner files:
- `app/services/context.py`
- `app/infrastructure/database.py`
- `app/cli.py`
- `app/ui/pages/history.py`
- `tests/test_startup_speed.py`, `tests/test_restore_safety.py`, `tests/test_cli.py`, `tests/test_db_access.py`

Tasks:
1. Startup purge must remove only stale/orphaned state and must not swallow failures.
5. Destructive CLI commands require explicit confirmation unless `--yes` is supplied.
6. Restore / integrity / vacuum run on a worker; GUI stays responsive and result is marshalled back.
7. Bootstrap is atomic under concurrent starts; no duplicate seed rows or partial schema.
8. Backup never overwrites an existing backup silently; generate a unique path or fail safely.

## Slice 2 - organisation races / recovery / planner (findings 2, 3, 14, 16)

Owner files:
- `app/services/organisation_service.py`
- `app/organisation/executor.py`
- `app/organisation/recovery.py`
- `app/organisation/planner.py`
- `tests/test_organisation.py`, `tests/test_organisation_safety.py`, `tests/test_planner_ui.py`

Tasks:
2. Interrupted plan recovery restores executable state without replaying completed items or losing held files.
3. Move/undo operations serialise per source/destination; no lost updates or double-move under concurrency.
14. Paths from plans are validated against the configured root before any filesystem action.
16. Planner does not report conflicts for identical source/destination or already-completed items.

## Slice 3 - analysis / LLM / intelligence (findings 4, 17, 19, 20)

Owner files:
- `app/services/analysis_service.py`
- `app/intelligence/llm.py`
- `app/intelligence/content_naming.py`
- `app/services/settings_service.py` (only if runtime settings application is required here)
- `tests/test_analysis_safety.py`, `tests/test_content_naming.py`, `tests/test_llm.py`, `tests/test_settings.py`

Tasks:
4. Duplicate reuse preserves the generated display name / title instead of falling back to the raw filename.
17. LLM probe result is not sticky after settings changes; failed probes retry.
19. Runtime LLM settings apply without process restart.
20. File-derived text is filtered for prompt-injection instructions before inclusion in LLM prompts.

## Slice 4 - search / performance / UI (findings 9, 10, 11, 12, 13, 15, 18)

Owner files:
- `app/search/indexer.py`
- `app/intelligence/embeddings.py`
- `app/infrastructure/repositories/analysis.py`
- `app/processing/extractors/*`
- `app/ui/pages/search.py`
- `app/ui/pages/dashboard.py`
- `app/core/progress.py`
- `tests/test_search.py`, `tests/test_embedding_safety.py`, `tests/test_ui_speed.py`, `tests/test_startup_speed.py`, `tests/test_ui_polish.py`

Tasks:
9. Semantic search does not load the full embedding table into memory.
10. IDF calculation does not load all document text into memory.
11. Cold scan uses stored hash/size/mtime metadata instead of rehashing unchanged files.
12. Cancel waits for the worker to finish before reporting completion.
13. Archive expansion enforces entry-count and total-size limits.
15. Dashboard counts reflect only active, non-deleted records.
18. Search page exposes a working Cancel action for long-running searches.

## Verification gates

- Focused pytest + ruff per slice.
- Main session integration: full pytest, ruff check, compileall, quality gate, `OPENCOEUS_WRITE_GOLDEN` empty.

## Progress

- [x] Plan written
- [x] Slice 1 dispatched
- [x] Slice 2 dispatched
- [x] Slice 3 dispatched
- [x] Slice 4 dispatched
- [x] Slice 3 agent completed and reviewed (4, 17, 19, 20)
- [x] Slice 2 agent completed and reviewed (2, 3, 14, 16)
- [x] Slice 4 agent completed and reviewed (9, 10, 11, 12, 13, 15, 18)
- [x] Slice 1 agent completed and reviewed (1, 5, 6, 7, 8)
- [x] All slices reviewed and integrated
- [x] Full verification passed: 410 tests, ruff/compileall/quality gate exit 0, golden env empty
