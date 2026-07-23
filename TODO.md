# OpenCoeus engineering backlog

`PROJECT_PLAN.md` is the source of truth for product scope. This file tracks the next actionable work needed to deliver it.

## Current baseline — complete

### Stage 1: safe audit foundation
- [x] Cross-platform scan-only desktop application for Windows, macOS, and Linux.
- [x] Safe traversal, exact SHA-256 duplicate detection, local SQLite audit history, and CSV export.
- [x] Offline PDF/DOCX text extraction and filename suggestions.
- [x] Platform-aware protected folders and non-destructive default policy.

### Stage 2: selective review and organisation
- [x] Folder tree with tri-state checkboxes for including or excluding individual folders.
- [x] Automatic folder classification into 7 categories (system, virtual environment, package dependencies, version control, game library, application, source code) with user override support.
- [x] Reusable scan profiles storing root path, included/excluded folders, custom protected patterns, and document extraction settings.
- [x] Deterministic rules engine with extension, pattern, date, size, and folder rule types.
- [x] 8 default organisation rules (Documents, Images, Audio, Video, Archives, Code, Installers, Old files archive).
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

## Next: execute approved changes (Stage 3)

- [ ] Execute approved renames and moves with collision detection.
- [ ] Persistent, reversible transaction journal for all file changes.
- [ ] Duplicate resolution with explicit retained-copy selection; never auto-delete.
- [ ] Re-scan and integrity verification immediately before changes are applied.
- [ ] Undo capability for recently applied changes.

## Later: advanced data workflows and release (Stage 4)

- [ ] Define supported spreadsheet schemas before enabling `.xlsx` or `.xlsm` consolidation.
- [ ] Implement read-only spreadsheet inspection, followed by an approved master-workbook workflow.
- [ ] Evaluate optional local NLP categorisation after the deterministic workflow is reliable.
- [ ] Build, package, and test on clean offline Windows, macOS, and Linux machines.
