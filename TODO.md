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
- [x] Comprehensive codebase audit: 48 issues fixed across critical, high, medium, and low severity levels.
- [x] Runtime bug fixes: profile creation FK, QColor crashes, stale DB, broken update_profile, status_badge column width.
- [x] UI rewrite: modular package architecture, CardTable, CardTree, unified button styling, modern card-based design across all pages.
- [x] 290 automated tests across 16 test files including end-to-end round-trip, partial rollback, pre-flight hash mismatch, and full DB state verification tests.

## Next: smart renaming (Stage 4)

- [ ] Add {title}, {title_sanitized}, {date}, {date_month} template variables to rules engine.
- [ ] Add "rename" action type alongside existing "move" action.
- [ ] Create safe_rename() function in executor for same-directory renames.
- [ ] Build smart filename constructor: title + metadata into clean filesystem name.
- [ ] Handle rename collisions, length limits, and special character sanitisation.
- [ ] Add proposed rename preview column to results table.
- [ ] Add "Has suggested title" filter to results page.
- [ ] Add approve/reject workflow for renames in actions page.
- [ ] Add default "Smart rename documents" rule (PDF/DOCX to suggested title).
- [ ] Add default "Photos by date" rule (rename photos to YYYY-MM-DD - name).
- [ ] Extend transaction journal to support rename entries with rollback.
- [ ] CLI subcommand: rename (--dry-run).
- [ ] Tests: rename collision resolution, title extraction, template rendering, undo round-trip.

## Future: AI-powered renaming with NLP (Stage 5)

- [ ] Add spaCy as runtime dependency for local NLP processing.
- [ ] Build NLP title extractor: keyword extraction, sentence importance scoring.
- [ ] Build document classifier: detect document type (invoice, report, contract, letter, manual, etc.).
- [ ] Build smart title generator: combine document type + keywords + metadata into standardised filename.
- [ ] Create NamingStrategy interface with two implementations: RuleBasedStrategy (Stage 4) and NLPStrategy (Stage 5).
- [ ] Add naming strategy selector to profile settings (rule-based vs NLP vs hybrid).
- [ ] Add NLP confidence score to each suggested title for user review.
- [ ] Add "AI Suggested" column to results table with confidence indicator.
- [ ] Batch rename mode: apply NLP titles to all matching documents with one-click approval.
- [ ] Learn naming conventions from existing files in target folder (pattern detection).
- [ ] Fallback chain: NLP fails to rule-based to original filename.
- [ ] Tests: NLP extraction accuracy, classifier precision, naming convention detection, fallback behaviour.

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
