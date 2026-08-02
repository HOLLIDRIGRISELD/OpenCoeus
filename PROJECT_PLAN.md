# OpenCoeus product and development plan

## Product purpose

OpenCoeus is a highly specialized, locally hosted Data Lifecycle Management (DLM) desktop application and intelligent file manager. Its core purpose is to parse, deduplicate, rename, and reorganize massive volumes of congested server data completely offline, ensuring maximum data privacy and system optimization.

### Core capabilities

- **Cryptographic Deduplication**: Scans entire server directories at the byte level using SHA-256 hashing to identify and eliminate exact file duplicates across folders, drastically reducing unnecessary storage bloat.
- **Intelligent Document Parsing**: Uses local text extraction tools to open and read the contents of PDF, Word, TXT, and Markdown documents without any external internet connection or cloud APIs.
- **AI-Powered Renaming**: Uses local Natural Language Processing (NLP) to analyze extracted text, understand document context, and automatically generate standardized, highly accurate filenames. An optional local LLM refines suggested names in batches.
- **Persistent Memory and Safeguards**: Relies on a local SQLite database to log every generated title and summary, ensuring the system never assigns identical names to different files. Uses strict safe zones to bypass chronological or reporting folders, preserving vital directory structures.
- **Spreadsheet Consolidation**: Dives into complex, macro-enabled spreadsheets to extract embedded tables or metadata, converting and merging them into lightweight master sheets for rapid, global searching.

## Technology stack

| Area | Technology | Role |
| --- | --- | --- |
| Desktop interface | PyQt6 | Native cross-platform window, background scan thread, progress, and audit log. |
| Core engine | Python 3.11+ | Safe traversal, policy checks, hashing, manifests, and action orchestration. |
| Exact duplicates | `hashlib` SHA-256 | Byte-level duplicate detection after size-based filtering. |
| Documents | `pypdf`, `python-docx`, `Pillow`, `mutagen` | Offline PDF, DOCX, image, and audio metadata extraction. |
| NLP and renaming | `spaCy` | Local title extraction, entity detection, keyword scoring, document classification, and context-aware filename generation. |
| Local LLM | `llama-cpp-python` (phi3 / Qwen2.5 GGUF) | Optional offline refinement of suggested filenames in batches. |
| Spreadsheets | `openpyxl` | Read-only analysis and explicitly approved consolidation of spreadsheet data. |
| Local memory | SQLite and SQLAlchemy | Audit history, title history, proposed actions, and transaction journal. |
| Distribution | PyInstaller | Per-platform desktop packages built on Windows, macOS, or Linux. |

## Safety policy

- Default mode is scan and preview only: no rename, move, merge, or deletion.
- System and OpenCoeus application-data folders are protected with platform-aware rules.
- Folder scans present a selectable folder tree with recommended exclusions.
- Application, game, dependency, and source-code folders are excluded by default when recognised.
- Organisation retains each selected folder's structure unless the user explicitly approves a destination rule.
- Server, code, config, installer, and system files are never renamed (bypass list).
- Every file change requires a preview, explicit approval, persistent audit record, and undo journal.
- Safe zones use strict regex patterns to bypass chronological, reporting, and system folders, preserving vital directory structures.

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
- [x] Results interface with filters, duplicate groups, protected files, document title suggestions, unique files, unreadable files, and a search-by-name feature.
- [x] Action approval workflow with approve selected, approve all, reject, and database persistence.
- [x] Rules management UI with add, edit, enable/disable, and delete controls.
- [x] Two-phase scan workflow: Phase 1 classifies folders, Phase 2 scans files with exclusions.
- [x] 18 default organisation rules (documents, photos, music, video, compressed, code, installers, spreadsheets, duplicates, uncategorized, and rename rules).
- [x] Error display section for scan warnings and unreadable files.
- [x] Async CSV manifest export via background thread.
- [x] Modern dark theme with sidebar-based navigation (7 pages).
- [x] CLI subcommands: scan, profile, classify, organize.
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

- [x] Add `{title}`, `{title_sanitized}`, `{date}`, `{date_month}` template variables to rules engine.
- [x] Add "rename" and "move+rename" action types alongside existing "move".
- [x] Create safe rename function in the executor for same-directory renames.
- [x] Build smart filename constructor: title + metadata into clean filesystem name.
- [x] Handle rename collisions, length limits, and special character sanitisation.
- [x] Add proposed rename preview to the results table.
- [x] Add "Has suggested title" filter to results page.
- [x] Add approve/reject workflow for renames in actions page.
- [x] Add default smart-rename rules for documents, spreadsheets, screenshots, and filename normalisation.
- [x] Extend transaction journal to support rename entries with rollback.
- [x] CLI subcommand: rename (--dry-run).
- [x] Tests: rename collision resolution, title extraction, template rendering, undo round-trip.

### Stage 5 - AI-powered renaming with NLP (implemented)

- [x] Add spaCy as a runtime dependency for local NLP processing.
- [x] Build NLP title extractor: keyword extraction, sentence importance scoring, and entity detection (people, organisations, projects, locations, dates).
- [x] Build document classifier: 26 document types (invoice, report, contract, letter, manual, specification, budget, etc.).
- [x] Build smart title generator: document type + keywords + metadata into a standardized filename.
- [x] Add naming strategy selector to profile settings (`nlp_enhanced` vs `rule_based`).
- [x] Add NLP confidence score to each suggested title for user review.
- [x] Content-based batch grouping: related documents co-located into one shared content folder per batch (no per-file deep folders).
- [x] Date-free filenames: generated names never include dates; year subfolders are still used for non-batch destinations (e.g. `Photos/2024/`).
- [x] Optional local LLM refinement (llama.cpp, phi3 / Qwen2.5 GGUF) during the organize pass.
- [x] Fallback chain: NLP to rule-based to original filename.
- [x] Tests: NLP extraction accuracy, classifier precision, confidence scoring, batch grouping, fallback behaviour, locked-refinement handling.
- [ ] Learn naming conventions from existing files in target folder (pattern detection).
- [ ] Add "AI Suggested" column to results table with confidence indicator.
- [ ] Batch rename mode: apply NLP titles to all matching documents with one-click approval.

#### Maintenance & refactor (post-Stage 5)

- [x] Consolidated the low-level scanning modules into a `core/` package (`file_scan`, `folder_tree`, `folder_classifier`, `hashing`, `safety`), resolving a duplicate `scanner.py` naming clash.
- [x] Made folder-name patterns single-sourced in `config.py` (shared constants used by both the safety rules and the folder classifier).
- [x] Extracted `get_data_directory()` shared by the database path and UI settings, and added persisted `settings.json` (theme + behavior toggles).
- [x] Optimised the folder-tree build to a single-pass `os.scandir` traversal with cached stats.
- [x] Removed dead code and redundant imports (folder-tree lookup helpers, batch summary, unreachable profile-update branch).
- [x] 415 automated tests across 21 test files.

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
