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
- [x] 11 default organisation rules (Documents, Photos, Music, Video, Compressed, Code, Installers, Old files archive, Duplicate consolidation, Uncategorized, Spreadsheets).
- [x] Results interface with filters: All, Duplicates, Duplicate Groups, Protected, Unique, Unreadable, With Title, and search-by-name.
- [x] Action approval workflow: approve selected, approve all, reject, with database persistence.
- [x] Rules management UI: add, edit, enable/disable, delete.
- [x] Two-phase scan: Phase 1 classifies folders, Phase 2 scans files with exclusions.
- [x] Error display section for scan warnings and unreadable files.
- [x] Async CSV manifest export via background thread.
- [x] Modern dark theme with sidebar navigation (6 pages: Home, Folders, Results, Actions, Rules, Log).
- [x] CLI subcommands: scan, profile, classify, organise.
- [x] Performance: throttled progress, batch DB recording, compiled regex, sorted table updates, pre-parsed rule configs, bulk classification save, log buffer with QTimer, log capped at 5000 lines.
- [x] Bug fixes: extended metadata persisted, profile wired to CLI, dynamic profile_id, action approvals saved, folder exclusions persisted to profile, sync index alignment fixed.
- [x] 188 automated tests across 13 test files.

### Stage 3: approved changes and recovery
- [x] TransactionBatch and TransactionEntry database models with index optimisation.
- [x] Pre-Stage 3 fixes: reason column on ProposedAction, reject_action persistence, protected file skip in rules engine.
- [x] executor.py: atomic file moves with collision detection, holding area management, pre-flight hash verification, rollback on failure, thread-safe execution lock, crash recovery.
- [x] journal.py: batch orchestration, undo orchestration, batch summary.
- [x] UI: Execute Approved and Undo buttons, batch history table, ExecutionWorker and UndoWorker background threads.
- [x] CLI: execute (--dry-run) and undo subcommands.
- [x] Refactor: BatchStatus/EntryStatus enums, DEFAULT_RULES single source in rules_engine.py, absolute holding path, mutual exclusion guards, N+1 query fix, regex pre-compilation, profile cascade delete, date safety guard, cache eviction.
- [x] 278 automated tests across 16 test files including end-to-end round-trip, partial rollback, pre-flight hash mismatch, and full DB state verification tests.

## Next: spreadsheet workflows and release (Stage 4)

- [ ] Define supported spreadsheet schemas before enabling .xlsx or .xlsm consolidation.
- [ ] Implement read-only spreadsheet inspection, followed by an approved master-workbook workflow.
- [ ] Build, package, and test on clean offline Windows, macOS, and Linux machines.
