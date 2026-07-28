# OpenCoeus

OpenCoeus is an offline-first Data Lifecycle Management desktop application and intelligent file manager for Windows, macOS, and Linux. It is designed to safely analyse, deduplicate, rename, and reorganise large local folders, drives, and server shares without cloud services.

The current release proposes file actions and executes approved changes with a reversible transaction journal. It scans folders, detects exact duplicates, honours protected system folders, classifies folders into categories, applies rules-based organisation, and stores an audit trail locally. Approved changes are executed atomically with collision detection, holding area rollback, and undo capability.

For the complete product scope, implemented capabilities, safety policy, and staged roadmap, see [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Included now

### Core scanning and deduplication
- Memory-safe traversal with per-file error handling and symbolic-link avoidance.
- SHA-256 duplicate detection using size grouping to avoid unnecessary hashing.
- Platform-aware protected-folder safety rules for Windows, macOS, and Linux.
- Local SQLite/SQLAlchemy audit history with batch recording.
- PDF and DOCX first-page text extraction and offline filename suggestions.

### Folder tree and classification
- Recursive folder tree builder with file counts, total size, and depth tracking.
- Automatic folder classification into 7 categories: system, virtual environment, package dependencies, version control, game library, application, and source code.
- Tri-state checkbox interface for including or excluding individual folders.
- Protected system folders are always excluded by default.
- User override support for every classification recommendation.

### Scan profiles
- Reusable scan profiles that store root path, included folders, excluded folders, custom protected patterns, and document extraction settings.
- Full CRUD: create, list, load by ID or name, update, and delete profiles.
- Profiles are persisted to the local database and shared across sessions.

### Rules-based organisation
- Deterministic rules engine that evaluates files against user-defined or default rules.
- Rule types: extension, filename pattern, date (older/newer than N days), size range, folder path, status, and always-match.
- 11 default rules: Documents, Photos, Music, Video, Compressed, Code, Installers, Old files archive, Duplicate consolidation, Uncategorized, and Spreadsheets.
- Priority-based first-match-wins evaluation with pre-parsed configurations and compiled regex.
- Destination templates with {filename}, {stem}, {extension}, {folder}, {root}, and {date_year} placeholders.
- Rename action type alongside move/move+rename with full template engine.
- 25+ template variables including {title}, {title_sanitized}, {date_iso}, {doc_type}, {stem_nospace}.

### Results and action management
- Results table with 7 columns: Path, Size, Status, Duplicate of, Title, Extension, Folder.
- Filterable results: All, Duplicates, Duplicate Groups, Protected, Unique, Unreadable, With Title.
- Search-by-name filtering across path and title fields.
- Actions table with proposed file moves and rule-matched reasons.
- Approve selected, Approve all, and Reject controls with database persistence.
- Error display section for scan warnings and unreadable files.

### Two-phase scan workflow
- Phase 1: Discover folder tree, classify folders, save classifications to database.
- Phase 2: Scan files within selected exclusions, detect duplicates, apply rules, propose actions.
- Background QThread workers for non-blocking UI.
- Throttled progress callbacks and buffered log output.

### Execution engine
- Execute approved file moves with atomic collision detection and resolution.
- Two-phase transaction: source to holding area, then holding area to destination.
- Pre-flight hash and size verification before execution.
- Crash recovery for batches stuck in executing status.
- Thread-safe execution with module-level lock preventing concurrent batches.
- Partial rollback: if one file fails, remaining holding-area files are restored to source.
- Full undo: reverse all completed entries in a batch, restoring files to original locations.
- Batch history table with entry counts and status indicators.

### Desktop interface
- Modern dark theme with sidebar-based navigation (6 pages: Home, Folders, Results, Actions, Rules, Log).
- Home dashboard with stat cards (Folders, Files, Duplicates, Actions) and profile management.
- Profile editor dialog for creating and editing scan profiles.
- Rule management UI with Add, Edit, Enable/Disable, and Delete controls.
- Real-time audit log with buffered output (capped at 5000 lines).
- Async CSV manifest export via background thread.
- Table sorting with clickable column headers.

### Command-line interface
- scan - single-phase scan with CSV manifest export.
- profile - create, list, show, and delete scan profiles.
- classify - build folder tree and classify folders with optional JSON export.
- organize - full two-phase pipeline: classify, scan, apply rules, export proposed actions.
- rename - propose content-aware renames using title extraction and template engine with dry-run support.
- execute - execute approved file actions with optional dry-run mode.
- undo - reverse the last executed batch of file moves.

## Quick start

### Install

Windows PowerShell:

`powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
`

macOS or Linux:

`ash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
`

### Launch the desktop application

`ash
python -m opencoeus.ui
`

### CLI examples

Scan a folder and export a CSV manifest:

`ash
python -m opencoeus.cli scan "D:\YourFolder" --output scan-manifest.csv
`

Classify folders in a directory:

`ash
python -m opencoeus.cli classify "D:\YourFolder" --output classifications.json
`

Manage scan profiles:

`ash
python -m opencoeus.cli profile create "My Drive" --root "D:\"
python -m opencoeus.cli profile list
python -m opencoeus.cli profile show "My Drive"
python -m opencoeus.cli profile delete "My Drive"
`

Run the full two-phase organise pipeline with proposed actions:

`ash
python -m opencoeus.cli organize "D:\YourFolder" --output actions.csv --profile "My Drive"
`

The organize command runs Phase 1 (classify folders), Phase 2 (scan files with exclusions), applies the rules engine, and exports proposed file actions. It never moves or removes files - every action requires explicit approval in the UI.

Preview content-aware renames:

`ash
python -m opencoeus.cli rename "D:\YourFolder" --dry-run
`

Execute approved file actions (after approving in the UI):

`ash
python -m opencoeus.cli execute --profile "My Drive"
`

Dry run (show what would be done without executing):

`ash
python -m opencoeus.cli execute --profile "My Drive" --dry-run
`

Undo the last executed batch:

`ash
python -m opencoeus.cli undo --profile "My Drive"
`

## Package the desktop application

Build on the operating system you intend to distribute to. PyInstaller packages are platform-specific.

Windows:

`powershell
python -m PyInstaller --noconfirm --windowed --name OpenCoeus --collect-all pypdf --collect-all docx --collect-all sklearn -m opencoeus.ui
`

macOS and Linux:

`ash
python -m PyInstaller --noconfirm --windowed --name OpenCoeus --collect-all pypdf --collect-all docx --collect-all sklearn -m opencoeus.ui
`

## Database location

The local database is created in the platform's normal per-user data location:

- **Windows:** `%LOCALAPPDATA%\OpenCoeus`
- **macOS:** `~/Library/Application Support/OpenCoeus`
- **Linux:** `~/.local/state/OpenCoeus`

If that location is read-only, it falls back to `.opencoeus` in the working folder. Set `OPENCOEUS_DATA_DIR` to choose an explicit location. No network connection is used by this application.

## Current development focus

Stages 1-4 (safe audit, selective organisation, approved changes, smart renaming) are complete. The next release focuses on AI-powered renaming with local NLP:

1. Add spaCy as a runtime dependency for local NLP processing.
2. Build NLP title extractor with keyword scoring and sentence importance ranking.
3. Build document classifier for automatic type detection (invoice, report, contract, letter, manual, etc.).
4. Create NamingStrategy interface with RuleBased and NLP implementations.

The complete product scope and delivery stages are in [PROJECT_PLAN.md](PROJECT_PLAN.md). The actionable engineering backlog is in [TODO.md](TODO.md).
