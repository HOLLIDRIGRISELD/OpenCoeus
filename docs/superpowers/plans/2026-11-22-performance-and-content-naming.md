# Performance and Content-Aware Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make startup, scan, analyse, and UI faster while replacing generic names with short content-derived names and `Entity/Type/` folders that prefer a stronger subtype over the document date.

**Architecture:** Five layered slices land in dependency order: startup, shared database reads/writes, UI, analysis throughput, then content naming. Speed slices keep the golden fixture byte-identical; only the final naming slice changes the intentional name/folder fields.

**Tech Stack:** Python 3.11+, PySide6, SQLAlchemy, SQLite/FTS5, NumPy. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-22-performance-and-content-naming-design.md`

## Global Constraints

- TDD for every behavior change: write test, confirm intended RED, implement minimal GREEN, run full verification.
- Baseline already measured on the 11.4GB corpus: `scan=105.48s hashed=5286`, `analyse=453.36s analysed=4535 failed=751`, `total=558.84s`. 40-file baseline: `scan=0.14s`, `analyse=1.80s`, `total=1.94s`. Keep only wins beyond run-to-run variance.
- Verification after every task:
  - `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest`
  - `.venv\Scripts\python.exe -m ruff check app tests main.py`
  - `.venv\Scripts\python.exe -m compileall -q app tests main.py`
  - `$env:OPENCOEUS_WRITE_GOLDEN=$null; .venv\Scripts\python.exe -m pytest tests/test_quality_gate.py -q`
- `OPENCOEUS_WRITE_GOLDEN=1` only during the controlled golden regeneration in Task 5; unset for all verification.
- No changes to extractor text, `MAX_TEXT_CHARS`, chunk config or the 96-chunk cap, embedding backend/model/precision/cache keys, classifier weights/formula/evidence, LLM gates/prompt/caps, FTS content, duplicate-reuse source selection, or model-name cache keys.
- No new dependencies, no cloud calls, no LLM naming calls.
- No unsafe moves, silent overwrites, or user-file deletion. `FilenameValidator`, duplicate-target claiming, `PathGuard`, planner, and undo stay authoritative.
- New DB tables only; no existing schema column changes. Schema bootstrap stays in `Base.metadata.create_all()`. Any new index requires explicit `CREATE INDEX IF NOT EXISTS` plus a written before/after `EXPLAIN QUERY PLAN` note.
- No prose comments. Docstrings only where the file already uses them.
- Workspace is not a git repo. Replace commit steps with a checkpoint copy under `C:\Users\seldi\AppData\Local\Temp\opencode\perf-naming-checkpoints\<task-id>\`.
- All processing stays local.

## Review Focus

- **File already inside a meaningful folder** → keep/use that folder as the entity instead of inventing a new one. Test in Task 5: `test_existing_folder_becomes_entity`.
- **No confident entity/type in content** → keep the existing validator-cleaned suggestion, never fabricate a name. Test in Task 5: `test_low_confidence_keeps_original_suggestion`.
- **Two files derive the same name** → smallest readable suffix, no doubled extension. Test in Task 5: `test_collision_suffix_has_no_doubled_extension`.
- **Grouped folder has a stronger subtype than a date** → subtype filename wins; date is fallback only. Test in Task 5: `test_grouped_subtype_beats_date`.
- **File changes on disk during analysis** → preserve the existing `exists()` / `stat()` checks. Test in Task 4: `test_metadata_recheck_still_runs`.

---

### Task 1: Startup speed

**Files:**
- Modify: `app/ui/app.py:46-54`
- Modify: `app/infrastructure/database.py:125-165`
- Modify: `tests/test_embedding_blobs.py:96-102`
- Test: `tests/test_startup_speed.py` (create)

**Interfaces:**
- Consumes: `LocalRuntime.start()`, `Database.vacuum()`.
- Produces: `LocalRuntime.start()` scheduled on the Qt event loop via `QTimer.singleShot(0, runtime.start)`; `Database.purge_session_data() -> int` returning deleted row count and calling `vacuum()` only when the count is positive.

- [ ] **Step 1: Write the failing startup test**

Create `tests/test_startup_speed.py` with `test_runtime_start_is_deferred_until_event_loop`. Assert that calling `run()` records a `QTimer.singleShot(0, <start>)` call and does not call `LocalRuntime.start()` before `QApplication.exec()` is entered.

- [ ] **Step 2: Write the failing VACUUM test**

In `tests/test_embedding_blobs.py`, change `test_purge_compacts_the_database` to first insert one `File` row, then assert `context.db.purge_session_data()` returns `1` and `vacuum()` was called once. Add `test_empty_purge_skips_vacuum` asserting an empty DB returns `0` and `vacuum()` was not called.

- [ ] **Step 3: Run RED**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_startup_speed.py tests/test_embedding_blobs.py -q`

Expected: FAIL because `QTimer.singleShot` is not used and `purge_session_data()` returns `None`.

- [ ] **Step 4: Implement startup defer**

In `app/ui/app.py`, import `QTimer`, create `runtime = LocalRuntime(context.settings.llm_base_url)` before `window.show()`, replace the direct `runtime.start()` with `QTimer.singleShot(0, runtime.start)`, and keep `runtime.stop()` / `context.close()` in the existing `finally`.

- [ ] **Step 5: Implement conditional VACUUM**

In `app/infrastructure/database.py`, change `purge_session_data() -> int`, sum `result.rowcount` over each DELETE, return the total, and call `self.vacuum()` only when the total is greater than zero. Keep the existing warning on `DatabaseError`.

- [ ] **Step 6: Run targeted GREEN**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_startup_speed.py tests/test_embedding_blobs.py tests/test_startup_cache.py -q`

Expected: PASS.

- [ ] **Step 7: Full verification and checkpoint**

Run all four Global Constraints commands. Copy changed files to `...\checkpoints\task-1\`.

---

### Task 2: Database access batching

**Files:**
- Modify: `app/infrastructure/repositories/files.py:109-172,208-231,371-387`
- Modify: `app/infrastructure/repositories/caches.py:33-46`
- Modify: `app/search/indexer.py:25-49`
- Modify: `app/infrastructure/database.py:114-123,227-249`
- Test: `tests/test_db_access.py` (create)

**Interfaces:**
- Consumes: `Database.batch()`, `Database.session()`, `Database.upsert_fts()`.
- Produces:
  - `FileRepository.list_summaries(limit: int) -> list[FileSummary]` with unchanged DTO shape and O(1) SQL statements.
  - `FileFingerprintRepository.set_many(rows: Iterable[Any]) -> None` using one batched upsert.
  - `SearchIndexer.rebuild(context: Any) -> int` with identical raw FTS columns and tag order.
  - `Database.ensure_performance_indexes() -> None` calling `CREATE INDEX IF NOT EXISTS` only for measured indexes.

- [ ] **Step 1: Write statement-count tests**

In `tests/test_db_access.py`, add:
  - `test_list_summaries_uses_bounded_statements`: seed 200 files, attach a SQLAlchemy `before_cursor_execute` counter, call `list_summaries(1000)`, assert statement count is independent of row count.
  - `test_fingerprint_set_many_uses_one_statement`: assert one upsert statement for 50 rows.
  - `test_fts_rebuild_preserves_raw_columns`: seed analysis + tags, rebuild, assert `filename`, `content`, `tags` exactly match pre-change expectations.

- [ ] **Step 2: Run RED**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_db_access.py -q`

Expected: FAIL on statement-count assertions.

- [ ] **Step 3: Batch summary reads**

In `app/infrastructure/repositories/files.py`, replace the per-row latest-analysis, category-path, and tag queries in `_to_summary` with three batched maps built once per `list_summaries()` call. Preserve field order and values in `FileSummary`.

- [ ] **Step 4: Batch fingerprint writes**

In `app/infrastructure/repositories/caches.py`, replace the `session.get()` loop in `set_many()` with one `INSERT ... ON CONFLICT DO UPDATE` statement built from the input rows. Preserve path, hash, size, and mtime values.

- [ ] **Step 5: Batch FTS rebuild**

In `app/search/indexer.py`, replace the per-file `index_file()` loop in `rebuild()` with one joined query and one batched `upsert_fts()` call. In `app/infrastructure/database.py`, extend `upsert_fts()` to accept a sequence of `(rowid, filename, content, tags)` rows while keeping the same DELETE+INSERT semantics and tag join order.

- [ ] **Step 6: Add measured indexes only**

Capture `EXPLAIN QUERY PLAN` before and after for `document_analyses(file_id, id DESC)`, `files(processing_status, current_path)`, and `file_fingerprints.path LIKE` scans. Add `CREATE INDEX IF NOT EXISTS` calls in `Database.ensure_performance_indexes()` only where the plan changes from SCAN to SEARCH and write-down cost is low. Record the before/after plans in the checkpoint README.

- [ ] **Step 7: Run targeted GREEN**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_db_access.py tests/test_db_batching.py tests/test_quality_gate.py -q`

Expected: PASS with unchanged golden.

- [ ] **Step 8: Full verification and checkpoint**

Run all four Global Constraints commands. Copy changed files and the index-plan README to `...\checkpoints\task-2\`.

---

### Task 3: UI responsiveness

**Files:**
- Modify: `app/ui/main_window.py:246-288`
- Modify: `app/ui/pages/recommendations.py:82-85,224-227,274-300`
- Modify: `app/ui/pages/planner.py:351-355,483-486`
- Modify: `app/ui/pages/files.py:228-239,241-311`
- Modify: `app/ui/pages/search.py:236-272`
- Modify: `app/ui/widgets.py:297-362`
- Test: `tests/test_ui_speed.py` (create)

**Interfaces:**
- Consumes: Task 2 `FileRepository.list_summaries()`.
- Produces: `MainWindow.navigate(key: str) -> None` with same-key guard and dirty flags; `RecommendationsPage.load_duplicates() -> None` for lazy tab population; detail-cache invalidation on refresh.

- [ ] **Step 1: Write UI speed tests**

In `tests/test_ui_speed.py`, add:
  - `test_same_page_navigate_does_not_refresh_twice`
  - `test_library_change_marks_pages_dirty_instead_of_refreshing_all`
  - `test_duplicates_tab_loads_only_when_selected`
  - `test_plan_summary_reuses_loaded_items`
  - `test_unchanged_selection_skips_detail_reload`

- [ ] **Step 2: Run RED**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_ui_speed.py -q`

Expected: FAIL because navigation always refreshes and duplicates load eagerly.

- [ ] **Step 3: Implement dirty refresh**

In `app/ui/main_window.py`, add a per-key dirty set. `navigate()` returns early if `key == self._current_key` unless called from the forced-refresh shortcut. `_library_changed()` and `_settings_changed()` mark pages dirty and refresh only the current page; other pages refresh on next navigation. Keep Ctrl+R as forced refresh.

- [ ] **Step 4: Implement lazy duplicates**

In `app/ui/pages/recommendations.py`, remove `_refresh_duplicates()` from `refresh()`, connect `tabs.currentChanged` to `load_duplicates()`, and guard `load_duplicates()` so it runs once until invalidated by refresh.

- [ ] **Step 5: Reuse plan items**

In `app/ui/pages/planner.py`, pass already-loaded `items` into the summary builder instead of calling `plan_items()` again. Keep the same `PlanDraft` fields.

- [ ] **Step 6: Cache detail renders**

In `files.py`, `recommendations.py`, and `search.py`, store the last rendered `file_id`; skip `_show_detail()` / `_load_detail()` when unchanged. Invalidate the cache in each page's `refresh()`. Do not put the guard inside `_show_detail()` because pinned tests call it directly.

- [ ] **Step 7: Reduce table fill churn**

In `app/ui/widgets.py`, set row count once before filling and reuse one bold `QFont` per table. Keep `ResizeToContents` behavior and pinned column-width assertions unchanged.

- [ ] **Step 8: Run targeted GREEN**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_ui_speed.py tests/test_ui_unification.py tests/test_ui_polish.py tests/test_ui_responsive.py -q`

Expected: PASS.

- [ ] **Step 9: Full verification and checkpoint**

Run all four Global Constraints commands. Copy changed files to `...\checkpoints\task-3\`.

---

### Task 4: Analysis throughput

**Files:**
- Modify: `app/services/analysis_service.py:191-207,238-260,272-296,298-483,558-584,607-621,840-924`
- Modify: `app/infrastructure/repositories/analysis.py:71-95,130-173,615-638,644-679`
- Modify: `app/search/indexer.py:25-39`
- Test: `tests/test_analysis_throughput.py` (create)

**Interfaces:**
- Consumes: Task 2 batch writes, unchanged extraction future from `_preparation_job`.
- Produces: `AnalysisService.analyse_pending(use_llm: bool) -> AnalysisReport` with identical report values; in-memory `extraction.text` passed to FTS; a batch-scoped settings snapshot used by all per-file naming/folder decisions.

- [ ] **Step 1: Write throughput tests**

In `tests/test_analysis_throughput.py`, add:
  - `test_extracted_text_reused_for_fts`: monkeypatch `SearchIndexer.index_file` and assert the in-memory text is passed, while the DB text row is not reloaded.
  - `test_settings_read_once_per_batch`: count settings repository reads for a 20-file batch and assert the naming/folder settings are read once.
  - `test_chunk_and_blob_writes_are_batched`: assert one insert statement for all chunk rows and one for all embedding blobs per file.
  - `test_metadata_recheck_still_runs`: delete a file after extraction starts and assert the existing failure path runs.

- [ ] **Step 2: Run RED**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_analysis_throughput.py -q`

Expected: FAIL on statement counts and settings-read count.

- [ ] **Step 3: Hoist settings reads**

At the start of `analyse_pending()`, read `naming_template`, `organisation_root`, `use_conventions`, and thresholds once into a local snapshot. Pass the snapshot through `analyse_file()` and `_apply_llm()` instead of re-reading per file. Keep cache-signature values identical.

- [ ] **Step 4: Reuse in-memory text for FTS**

Change `SearchIndexer.index_file()` to accept optional `text` and `tags` and use them when provided. In `analysis_service.py`, pass the extraction text and already-computed tags instead of letting the indexer reload `DocumentContent.text`. Raw FTS columns stay byte-identical.

- [ ] **Step 5: Batch per-file writes**

In `app/infrastructure/repositories/analysis.py`, replace per-chunk `add()`/flush loops with bulk inserts that preserve chunk order and index values. Replace per-embedding blob inserts with one executemany call preserving `<f8` bytes. Replace per-tag SELECT/DELETE/INSERT loops with one batched tag reconciliation preserving tag order. Keep `ensure_category()` behavior unchanged.

- [ ] **Step 6: Overlap stages**

Extend the existing extraction executor with a second ordered stage for embed/classify/profile work. Extraction futures remain ordered; each file's computation, kwargs, and result order stay unchanged. Never parallelise LLM calls and never cache LLM responses.

- [ ] **Step 7: Cache destination names**

In `analysis_service.py`, replace per-file `is_dir()` + `iterdir()` with a per-destination-folder cache seeded once and updated by `reserved_names`. Preserve the current dedupe sequence exactly.

- [ ] **Step 8: Run targeted GREEN**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_analysis_throughput.py tests/test_accuracy.py tests/test_duplicate_work.py tests/test_incremental_cache.py tests/test_parallel_extraction.py tests/test_quality_gate.py -q`

Expected: PASS with unchanged golden.

- [ ] **Step 9: Full verification and checkpoint**

Run all four Global Constraints commands. Copy changed files to `...\checkpoints\task-4\`.

---

### Task 5: Content-aware naming and grouping

**Files:**
- Create: `app/intelligence/content_naming.py`
- Modify: `app/services/analysis_service.py:405,435-450,678-738,840-924`
- Modify: `app/infrastructure/repositories/analysis.py:681-823`
- Modify: `tests/test_quality_gate.py`
- Modify: `tests/fixtures/quality_golden.json`
- Test: `tests/test_content_naming.py` (create)

**Interfaces:**
- Consumes: Task 4 settings snapshot, extracted text, profile fields, keywords, category, confidence, evidence, existing folders, reserved names, and the file's relative parent when an organisation root contains it.
- Produces:
  - `suggest_content_name(original_name: str, text: str, profile: Mapping[str, object], keywords: Sequence[str], existing_names: Sequence[str], reserved_names: Sequence[str], relative_parent: str | None = None) -> str`
  - `suggest_grouped_name(entity: str, type_label: str, subtype: str | None, document_date: str | None, extension: str, collision_index: int) -> str`
  - `grouping_relative_folder(entity: str, type_label: str, existing_folders: Sequence[str]) -> str | None`
  - `resolve_suggestion(...)` used by both the normal analysis path and `clone_analysis()` duplicate reuse path.

- [ ] **Step 1: Write pure naming tests**

In `tests/test_content_naming.py`, add:
  - `test_manual_gets_entity_type_name` asserting `gferlhlf.pdf` + HLF helicopter manual text → `HLFManual.pdf`.
  - `test_invoice_gets_entity_type_name` asserting `123825ofsaolkd.incoive` + Meta invoice text → `MetaInvoice.PDF`.
  - `test_grouped_subtype_beats_date` asserting a grouped Meta invoice containing `Statement` yields `Statement.pdf`, not `2026-03-14.pdf`.
  - `test_grouped_date_fallback` asserting no subtype but a date yields `2026-03-14.pdf`.
  - `test_existing_folder_becomes_entity` asserting a file already in `HLF/` uses `HLF` rather than inventing an entity.
  - `test_existing_parent_folder_preserved_with_date_name` asserting `library/Meta/Invoices/foo.pdf` with content date yields destination `Meta/Invoices` and name `2026-03-14.pdf`.
  - `test_generic_parent_is_ignored` asserting `Downloads` does not become an entity.
  - `test_no_organisation_root_parent_not_entity` asserting parent is ignored when no root contains the file.
  - `test_original_extension_case_preserved` asserting `.PDF` survives while scanner metadata stays lowercase.
  - `test_low_confidence_keeps_original_suggestion` asserting weak content returns the validator-cleaned original name.
  - `test_collision_suffix_has_no_doubled_extension` asserting a second `MetaInvoice.pdf` becomes `MetaInvoice 2.pdf`.
  - `test_no_hash_amount_or_long_number_in_name` asserting invoice numbers and amounts never appear in single-file names.

- [ ] **Step 2: Run RED**

Run: `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_content_naming.py -q`

Expected: FAIL because `app.intelligence.content_naming` does not exist.

- [ ] **Step 3: Implement pure naming resolver**

Create `app/intelligence/content_naming.py` with the three functions above. Rules:
  - Prefer content profile/org field, then filename token; use `relative_parent` only as a low-confidence hint and ignore generic parents (`Downloads`, `Documents`, `Inbox`). With no root, `relative_parent` is `None`.
  - Prefer a document type from profile `type`, then strong content keyword, then filename token.
  - Single file: `<Entity><Type><original extension>` using `Path(original_name).suffix` verbatim, title-cased without separators. Scanner metadata stays lowercase.
  - Grouped: `grouping_relative_folder()` returns `<Entity>/<TypePlural>/`; `suggest_grouped_name()` prefers subtype, then date, then readable collision suffix.
  - Never append hash, amount, invoice number, mtime date, or doubled extension.
  - Fall back to the existing validator-cleaned suggestion on low confidence.
  - Every result must pass `FilenameValidator`; callers still claim targets and run `PathGuard`.

- [ ] **Step 4: Integrate into analysis path**

In `analysis_service.py`, call `resolve_suggestion()` after `_build_profile()` and before `save_suggestions()`. Compute `relative_parent` from `_root_for(path)` only when the configured root contains the file; pass the Task 4 settings snapshot, extracted text, keywords, profile, relative parent, existing folder names, and reserved names. Store `rule decision = content-naming` in notes without changing classifier evidence.

- [ ] **Step 5: Integrate into duplicate reuse path**

In `app/infrastructure/repositories/analysis.py:clone_analysis()`, call the same resolver so a reused duplicate gets the same naming policy. Preserve all cloned analysis fields except `suggested_name` and `relative_folder`.

- [ ] **Step 6: Regenerate golden under controlled flag**

Back up `tests/fixtures/quality_golden.json` to the checkpoint directory. Run `$env:OPENCOEUS_WRITE_GOLDEN=1; .venv\Scripts\python.exe -m pytest tests/test_quality_gate.py -q`, then immediately unset the variable. Inspect the diff and keep only `suggestions.filename` / `suggestions.destination` changes. Restore any other field from the backup.

- [ ] **Step 7: Run targeted GREEN**

Run: `$env:OPENCOEUS_WRITE_GOLDEN=$null; $env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest tests/test_content_naming.py tests/test_quality_gate.py tests/test_accuracy.py tests/test_duplicate_work.py tests/test_conventions.py tests/test_organisation.py tests/test_ui_smoke.py -q`

Expected: PASS. Golden diff limited to `suggestions.filename` / `suggestions.destination`.

- [ ] **Step 8: Full verification and checkpoint**

Run all four Global Constraints commands. Record the intentional golden field list in `...\checkpoints\task-5\golden-diff.md` and copy all changed files.

---

## Final acceptance

- Cold-start timing no longer includes Ollama startup delay.
- 40-file and full-corpus timings are recorded before/after for scan and analyse; only measured wins beyond variance remain.
- Full suite passes with `275+` tests, ruff clean, compileall exit 0, quality gate green.
- Golden diff for Tasks 1–4 is empty; Task 5 diff is limited to `suggestions.filename` / `suggestions.destination`.
- User examples produce `HLFManual.pdf`, `MetaInvoice.PDF`, and grouped `Meta/Invoices/<strongest-subtype>.pdf` with date fallback.
