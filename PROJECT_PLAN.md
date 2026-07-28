# OpenCoeus product and development plan

## Product purpose

OpenCoeus is a highly specialized, locally hosted Data Lifecycle Management (DLM) desktop application and intelligent file manager. Its core purpose is to parse, deduplicate, rename, and reorganize massive volumes of congested server data completely offline, ensuring maximum data privacy and system optimization.

### Core capabilities

- **Cryptographic Deduplication**: Scans entire server directories at the byte level using SHA-256 hashing to identify and eliminate exact file duplicates across folders, drastically reducing unnecessary storage bloat.
- **Intelligent Document Parsing**: Uses local text extraction tools to open and read the contents of PDF and Word documents without any external internet connection or cloud APIs.
- **AI-Powered Renaming**: Uses local Natural Language Processing (NLP) to analyze extracted text, understand document context, and automatically generate and apply standardized, highly accurate filenames.
- **Persistent Memory and Safeguards**: Relies on a local SQLite database to log every generated title and summary, ensuring the system never assigns identical names to different files. Uses strict regex Safe Zones to bypass chronological or reporting folders, preserving vital directory structures.
- **Spreadsheet Consolidation**: Dives into complex, macro-enabled spreadsheets to extract embedded tables or metadata, converting and merging them into lightweight master sheets for rapid, global searching.

## Technology stack

| Area | Technology | Role |
| --- | --- | --- |
| Desktop interface | PyQt6 | Native cross-platform window, background scan thread, progress, and audit log. |
| Core engine | Python 3.11+ | Safe traversal, policy checks, hashing, manifests, and action orchestration. |
| Exact duplicates | `hashlib` SHA-256 | Byte-level duplicate detection after size-based filtering. |
| Documents | `pypdf`, `python-docx` | Offline PDF and DOCX text extraction. |
| NLP and renaming | `spaCy` | Local title extraction, keyword scoring, document classification, and context-aware filename generation. |
| Local analysis | `scikit-learn` | Document type classification and naming convention detection. |
| Spreadsheets | `pandas`, `openpyxl` | Read-only analysis and explicitly approved consolidation of spreadsheet data. |
| Local memory | SQLite and SQLAlchemy | Audit history, title history, proposed actions, and transaction journal. |
| Distribution | PyInstaller | Per-platform desktop packages built on Windows, macOS, or Linux. |

## Safety policy

- Default mode is scan and preview only: no rename, move, merge, or deletion.
- System and OpenCoeus application-data folders are protected with platform-aware rules.
- Folder scans present a selectable folder tree with recommended exclusions.
- Application, game, dependency, and source-code folders are excluded by default when recognised.
- Organisation retains each selected folder's structure unless the user explicitly approves a destination rule.
- Every file change requires a preview, explicit approval, persistent audit record, and undo journal.
- Safe Zones use strict regex patterns to bypass chronological, reporting, and system folders, preserving vital directory structures.

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
- [x] 312 automated tests across 16 test files including end-to-end round-trip, partial rollback, pre-flight hash mismatch, and full rename round-trip tests.

### Stage 4 - smart renaming (implemented)

- [x] Add {title}, {title_sanitized}, {date}, {date_month} template variables to rules engine.
- [x] Add "rename" action type alongside existing "move" action.
- [x] Create safe_rename() function in executor for same-directory renames.
- [x] Build smart filename constructor: title + metadata into clean filesystem name.
- [x] Handle rename collisions, length limits, and special character sanitisation.
- [x] Add proposed rename preview column to results table.
- [x] Add "Has suggested title" filter to results page.
- [x] Add approve/reject workflow for renames in actions page.
- [x] Add default "Smart rename documents" rule (PDF/DOCX to suggested title).
- [x] Add default "Photos by date" rule (rename photos to YYYY-MM-DD - name).
- [x] Extend transaction journal to support rename entries with rollback.
- [x] CLI subcommand: rename (--dry-run).
- [x] Tests: rename collision resolution, title extraction, template rendering, undo round-trip.

### Stage 5 - AI-powered renaming with NLP (not started)

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

### Stage 6 - spreadsheet consolidation (not started)

- [ ] Define supported .xlsx and .xlsm data schemas with representative files.
- [ ] Add read-only spreadsheet inspection before any conversion or consolidation.
- [ ] Add approved master-workbook generation with source links and validation reports.
- [ ] Add "spreadsheet" action type for merge/consolidate operations.
- [ ] Tests: schema validation, master-workbook integrity, source traceability.

### Stage 7 - packaging and release quality (not started)

- [ ] Build and test signed PyInstaller packages on clean Windows, macOS, and Linux systems.
- [ ] Add auto-update check mechanism (offline-compatible version file).
- [ ] Add first-run welcome wizard with profile setup.
- [ ] Performance profiling and optimisation for large directories (100k+ files).
- [ ] Accessibility audit: keyboard navigation, screen reader labels, high-contrast mode.
- [ ] End-to-end smoke tests on clean machines.

## Explicit non-goals for the current version

The current release proposes file actions and executes approved changes with a reversible transaction journal. Automatic deletion of duplicates is never performed - every action requires explicit user approval. Image OCR is not in scope; the application does not interpret images with visual analysis.
