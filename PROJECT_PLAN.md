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
| Local memory | SQLite and SQLAlchemy | Audit history, title history, proposed actions, and future undo journal. |
| Distribution | PyInstaller | Per-platform desktop packages built on Windows, macOS, or Linux. |

## Safety policy

- Default mode is scan and preview only: no rename, move, merge, or deletion.
- System and OpenCoeus application-data folders are protected with platform-aware rules.
- Future drive scans will present a selectable folder tree and recommended exclusions.
- Application, game, dependency, and source-code folders will be excluded by default when recognised.
- Organisation will retain each selected folder's structure unless the user explicitly approves a destination rule.
- Every future file change requires a preview, explicit approval, persistent audit record, and undo journal.

## Delivery roadmap

### Stage 1 — safe audit foundation (implemented)

- [x] Cross-platform PyQt6 desktop shell with background scanning.
- [x] Safe recursive regular-file traversal with error reporting and symbolic-link avoidance.
- [x] Exact SHA-256 duplicate detection, using size grouping to avoid unnecessary hashing.
- [x] SQLite audit history and CSV manifest export.
- [x] Platform-aware protected-folder rules for Windows, macOS, and Linux.
- [x] PDF and DOCX text extraction with local filename suggestions and title history.
- [x] Command-line entry point, automated tests, and packaging instructions.

### Stage 2 — selective review and organisation (next)

- [ ] Folder tree that allows the user to include or exclude locations after choosing a drive.
- [ ] Rules and recommendations for protecting applications, games, source-code repositories, dependencies, and user-designated safe zones.
- [ ] Results interface with filters for duplicate groups, protected files, document title suggestions, and warnings.
- [ ] Rules-based organiser using extensions, patterns, dates, and user profiles; it must work without AI.
- [ ] Optional local NLP categorisation, kept separate from file-changing actions.

### Stage 3 — approved changes and recovery

- [ ] Rename and move preview with original and proposed paths.
- [ ] Explicit action approval, collision handling, and a reversible transaction journal.
- [ ] Duplicate resolution that selects a retained copy but never deletes without explicit approval.
- [ ] Re-scan and integrity verification immediately before changes are applied.

### Stage 4 — spreadsheet workflows and release quality

- [ ] Define supported `.xlsx` and `.xlsm` data schemas with representative files.
- [ ] Add read-only spreadsheet inspection before any conversion or consolidation.
- [ ] Add approved master-workbook generation with source links and validation reports.
- [ ] Build and test signed packages on clean Windows, macOS, and Linux systems.

## Explicit non-goals for the current version

The current release does not delete duplicates, rename files, move files, reorganise folders, interpret images with OCR, analyse `.xlsm` data, merge spreadsheets, or use a spaCy/scikit-learn model. Those capabilities remain planned until their review and rollback safeguards exist.
