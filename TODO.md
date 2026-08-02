# OpenCoeus engineering backlog

`PROJECT_PLAN.md` is the source of truth for product scope. This file tracks the next actionable work needed to deliver it.

## Current baseline - complete

### Stage 1: safe audit foundation
- [x] Cross-platform scan-only desktop application for Windows, macOS, and Linux.
- [x] Safe traversal, exact SHA-256 duplicate detection, local SQLite audit history, and CSV export.
- [x] Offline PDF/DOCX text extraction and filename suggestions.
- [x] Platform-aware protected folders and non-destructive default policy.

### Stage 2: selective review and organisation
- [x] Folder tree with tri-state checkboxes for including or excluding individual folders.
- [x] Automatic folder classification into 7 categories (system, virtual environment, package dependencies, version control, game library, application, source code) with user override support.
- [x] Reusable scan profiles storing root path, included/excluded folders, custom protected patterns, and document extraction settings.
- [x] Deterministic rules engine with extension, pattern, date, size, folder, status, and always rule types.
- [x] 18 default organisation rules (documents, photos, music, video, compressed, code, installers, spreadsheets, duplicates, uncategorized, and rename rules).
- [x] Results interface with filters and search-by-name across path and title fields.
- [x] Action approval workflow: approve selected, approve all, reject, with database persistence.
- [x] Rules management UI: add, edit, enable/disable, delete.
- [x] Two-phase scan: Phase 1 classifies folders, Phase 2 scans files with exclusions.
- [x] Error display section for scan warnings and unreadable files.
- [x] Async CSV manifest export via background thread.
- [x] Modern dark theme with sidebar navigation (7 pages: Home, Folders, Results, Actions, Rules, Log, Settings).
- [x] CLI subcommands: scan, profile, classify, organize.
- [x] Performance: throttled progress, batch DB recording, compiled regex, sorted table updates, pre-parsed rule configs, bulk classification save, log buffer with QTimer, log capped at 5000 lines.
- [x] Bug fixes: extended metadata persisted, profile wired to CLI, dynamic profile_id, action approvals saved, folder exclusions persisted to profile, sync index alignment fixed.
- [x] 188 automated tests across 13 test files.

### Stage 3: approved changes and recovery
- [x] TransactionBatch and TransactionEntry database models with index optimisation.
- [x] Pre-Stage 3 fixes: reason column on ProposedAction, reject_action persistence, protected file skip in rules engine.
- [x] Executor package: atomic file moves with collision detection, holding area management, pre-flight hash verification, rollback on failure, thread-safe execution lock, crash recovery.
- [x] Journal: batch orchestration, undo orchestration, batch summary.
- [x] UI: Execute Approved and Undo buttons, batch history table, ExecutionWorker and UndoWorker background threads.
- [x] CLI: execute (--dry-run) and undo subcommands.
- [x] Refactor: BatchStatus/EntryStatus enums, DEFAULT_RULES single source, absolute holding path, mutual exclusion guards, N+1 query fix, regex pre-compilation, profile cascade delete, date safety guard, cache eviction.
- [x] Comprehensive codebase audit: 48 issues fixed across critical, high, medium, and low severity levels.
- [x] Runtime bug fixes: profile creation FK, QColor crashes, stale DB, broken update_profile, status_badge column width.
- [x] UI rewrite: modular package architecture, CardTable, CardTree, unified button styling, modern card-based design across all pages.
- [x] 312 automated tests across 16 test files including end-to-end round-trip, partial rollback, pre-flight hash mismatch, and full DB state verification tests.

### Stage 4: smart renaming
- [x] 25+ template variables ({title}, {title_sanitized}, {doc_type}, {date_iso}, {stem_nospace}, etc.) in rules engine.
- [x] "rename" and "move+rename" action types alongside existing "move".
- [x] Smart filename constructor in `_render_rename()` with `_substitute_variables()`.
- [x] Content-type detection (26 types: Invoice, Meeting-Notes, Specification, Report, Budget, Contract, Presentation, Readme, Backup, Spreadsheet, etc.).
- [x] Title extraction from PDF/DOCX/TXT/MD with scoring.
- [x] Rename collision resolution in executor.
- [x] OS-level filename validation in safety checks.
- [x] Rename audit trail (original_filename/new_filename on ProposedAction and TransactionEntry).
- [x] Approve/reject workflow for renames in actions page.
- [x] Normalization pass for rules with priority >= 25.
- [x] "Has Suggested Title" filter on results page.
- [x] Action type filter (All/Move/Rename/Move+Rename) in actions UI.
- [x] CLI rename subcommand with --dry-run.
- [x] CLI --rename-template uses full 25+ variable engine.

### Stage 5: AI-powered renaming with NLP (implemented)
- [x] spaCy runtime dependency for local NLP processing.
- [x] NLP title extractor: keyword extraction, sentence importance scoring, entity detection (people, organisations, projects, locations, dates).
- [x] Document classifier: 26 document types (invoice, report, contract, letter, manual, specification, budget, etc.).
- [x] Smart title generator: document type + keywords + metadata into a standardized filename.
- [x] Naming strategy selector on profiles (`nlp_enhanced` default, `rule_based`).
- [x] NLP confidence score on every suggested title.
- [x] Content-based batch grouping: related documents share one content folder per batch (e.g. `Documents/specification/e2-lifeboat-and-rescue-boat/`).
- [x] Date-free filenames; year subfolders retained only for non-batch destinations (Photos, Spreadsheets).
- [x] Local LLM refinement (llama-cpp-python, phi3 / Qwen2.5 GGUF) during organize; enabled per profile.
- [x] Fallback chain: NLP to rule-based to original filename.
- [x] 415 automated tests across 21 test files (batch grouping, locked refinement, no-date naming, fallback, classifier precision).
- [x] Dead-code pass: removed unused NLP/DB/fixture helpers and dead write statements.

### Codebase maintenance (post-Stage 5)
- [x] New `core/` package consolidates `file_scan`, `folder_tree`, `folder_classifier`, `hashing`, and `safety`; resolves the duplicate `scanner.py` module naming clash.
- [x] Folder-name patterns single-sourced in `config.py` (version-control / virtual-environment / dependency / cache constants shared with the classifier).
- [x] `config.get_data_directory()` shared by the database path and UI settings; `settings.json` persistence with data-dir fallback.
- [x] Single-pass `os.scandir` folder-tree build (one directory scan per folder, cached stats).
- [x] Dead code removed: `find_node`, `set_folder_exclusion`, `get_batch_summary`/`BatchSummary`, unreachable `update_profile` branch, redundant local imports, CLI `__main__` guard.
- [x] Settings overhaul: persisted theme + behavior toggles, working dark/light switch, sidebar minimize button removed.
- [x] 415 automated tests across 21 test files (settings round-trip added; dead-code tests pruned).
- [ ] Learn naming conventions from existing files in target folder (pattern detection).
- [ ] Add "AI Suggested" column to results table with confidence indicator.
- [ ] Batch rename mode: apply NLP titles to all matching documents with one-click approval.

## Future: spreadsheet consolidation (Stage 6)

- [ ] Define supported .xlsx and .xlsm data schemas with representative files.
- [ ] Add read-only spreadsheet inspection before any conversion or consolidation.
- [ ] Add approved master-workbook generation with source links and validation reports.
- [ ] Add "spreadsheet" action type for merge/consolidate operations.
- [ ] Tests: schema validation, master-workbook integrity, source traceability.

## Future: packaging and release quality (Stage 7)

- [ ] Build and test signed PyInstaller packages on clean Windows, macOS, and Linux systems.
- [ ] Add auto-update check mechanism (offline-compatible version file).
- [ ] Add first-run welcome wizard with profile setup.
- [ ] Performance profiling and optimisation for large directories (100k+ files).
- [ ] Accessibility audit: keyboard navigation, screen reader labels, high-contrast mode.
- [ ] End-to-end smoke tests on clean machines.
