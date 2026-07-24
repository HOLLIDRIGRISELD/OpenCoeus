# OpenCoeus product and development plan

## Product purpose

OpenCoeus is an offline-first Data Lifecycle Management desktop application and intelligent file manager for large, mixed local folders, external drives, and server shares. It is designed for Windows, macOS, and Linux, with privacy, auditability, and preserving working folder structures as first principles.

It must never reorganise an entire drive as one flat collection. Applications, games, source-code projects, operating-system folders, and user-excluded locations remain in place by default.

## Technology stack

| Area | Technology | Role |
| --- | --- | --- |
| Desktop interface | PyQt6 | Native cross-platform window, background scan thread, progress, and audit log. |
| Core engine | Python 3.11+ | Safe traversal, policy checks, hashing, manifests, and action orchestration. |
| Exact duplicates | `hashlib` SHA-256 | Byte-level duplicate detection after size-based filtering. |
| Documents | `pypdf`, `python-docx` | Offline PDF and DOCX text extraction. |
| Local analysis | scikit-learn; spaCy optional in a later release | Local title and category suggestions; no cloud API is required. |
| Spreadsheets | pandas, openpyxl | Future read-only analysis and explicitly approved consolidation of spreadsheet data. |
| Local memory | SQLite and SQLAlchemy | Audit history, title history, proposed actions, and transaction journal. |
| Distribution | PyInstaller | Per-platform desktop packages built on Windows, macOS, or Linux. |

## Safety policy

- Default mode is scan and preview only: no rename, move, merge, or deletion.
- System and OpenCoeus application-data folders are protected with platform-aware rules.
- Folder scans present a selectable folder tree with recommended exclusions.
- Application, game, dependency, and source-code folders are excluded by default when recognised.
- Organisation retains each selected folder's structure unless the user explicitly approves a destination rule.
- Every file change requires a preview, explicit approval, persistent audit record, and undo journal.

## Delivery roadmap

### Stage 1 - safe audit foundation (implemented)

- [x] Cross-platform PyQt6 desktop shell with background scanning.
- [x] Safe recursive regular-file traversal with error reporting and symbolic-link avoidance.
- [x] Exact SHA-256 duplicate detection, using size grouping to avoid unnecessary hashing.
- [x] SQLite audit history and CSV manifest export.
- [x] Platform-aware protected-folder rules for Windows, macOS, and Linux.
- [x] PDF and DOCX text extraction with local filename suggestions and title history.
- [x] Command-line entry point, automated tests, and packaging instructions.

### Stage 2 - selective review and organisation (implemented)

- [x] Folder tree that allows the user to include or exclude locations after choosing a drive.
- [x] Automatic folder classification into 7 categories (system, virtual environment, package dependencies, version control, game library, application, source code) with user override support.
- [x] Reusable scan profiles storing root path, included/excluded folders, custom protected patterns, and document extraction settings.
- [x] Deterministic rules engine with extension, pattern, date, size, folder, status, and always rule types; priority-based first-match-wins evaluation.
- [x] Results interface with filters for duplicate groups, protected files, document title suggestions, unique files, unreadable files, and a search-by-name feature.
- [x] Action approval workflow with approve selected, approve all, reject, and database persistence.
- [x] Rules management UI with add, edit, enable/disable, and delete controls.
- [x] Two-phase scan workflow: Phase 1 classifies folders, Phase 2 scans files with exclusions.
- [x] 11 default organisation rules (Documents, Photos, Music, Video, Compressed, Code, Installers, Old files archive, Duplicate consolidation, Uncategorized, Spreadsheets).
- [x] Error display section for scan warnings and unreadable files.
- [x] Async CSV manifest export via background thread.
- [x] Modern dark theme with sidebar-based navigation (6 pages).
- [x] CLI subcommands: scan, profile, classify, organise.
- [x] Performance: throttled progress, batch DB recording, compiled regex, sorted table updates, pre-parsed rule configs, bulk classification save, log buffer with QTimer, log capped at 5000 lines.
- [x] 188 automated tests across 13 test files.

### Stage 3 - approved changes and recovery (implemented)

- [x] Execute approved renames and moves with collision detection.
- [x] Persistent, reversible transaction journal for all file changes.
- [x] Duplicate resolution with explicit retained-copy selection; never auto-delete.
- [x] Re-scan and integrity verification immediately before changes are applied.
- [x] Undo capability for recently applied changes.
- [x] TransactionBatch and TransactionEntry database models with index optimisation.
- [x] Atomic file moves with holding area for rollback.
- [x] Pre-flight hash verification before execution.
- [x] Crash recovery for batches stuck in executing status.
- [x] Thread-safe execution with module-level lock preventing concurrent batches.
- [x] Batch history table in the UI with entry counts via single query.
- [x] Background worker threads for execution and undo (non-blocking UI).
- [x] Mutual exclusion guards preventing double-activation of execute/undo.
- [x] CLI subcommands: execute (--dry-run), undo.
- [x] 278 automated tests across 16 test files including end-to-end round-trip, partial rollback, and pre-flight hash mismatch tests.

### Stage 4 - spreadsheet workflows and release quality

- [ ] Define supported .xlsx and .xlsm data schemas with representative files.
- [ ] Add read-only spreadsheet inspection before any conversion or consolidation.
- [ ] Add approved master-workbook generation with source links and validation reports.
- [ ] Build and test signed packages on clean Windows, macOS, and Linux systems.

## Explicit non-goals for the current version

The current release proposes file actions and executes approved changes with a reversible transaction journal. It does not interpret images with OCR, analyse .xlsm data, merge spreadsheets, or use a spaCy/scikit-learn model. Automatic deletion of duplicates is never performed - every action requires explicit user approval.
