# OpenCoeus

OpenCoeus is an offline-first Data Lifecycle Management desktop application and intelligent file manager for Windows, macOS, and Linux. It is intended to safely analyse, deduplicate, rename, and reorganise large local folders, drives, and server shares without cloud services.

The current release is deliberately **non-destructive**: it scans folders, detects exact duplicates, honours protected system folders, stores an audit trail locally, and produces CSV manifests for review. It does not yet rename, move, merge, or delete files.

For the complete product scope, implemented capabilities, safety policy, and staged roadmap, see [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Included now

- Memory-safe traversal with per-file error handling.
- SHA-256 duplicate detection (size grouping before hashing for speed).
- Platform-aware protected-folder safety rules for Windows, macOS, and Linux. You can add your own patterns in the application settings code.
- Local SQLite/SQLAlchemy audit history.
- PDF and DOCX first-page text extraction and offline filename suggestions.
- Command-line workflow and a PyQt6 desktop interface that runs scans off the UI thread.

## Quick start

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m opencoeus.cli scan "D:\YourFolder" --output scan-manifest.csv
python -m opencoeus.ui
```

macOS or Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m opencoeus.cli scan "/path/to/your-folder" --output scan-manifest.csv
python -m opencoeus.ui
```

`scan` never moves or removes files. Future file-changing workflows will require a preview, explicit approval, and an undo journal.

## Package the desktop application

Build on the operating system you intend to distribute to. PyInstaller packages are platform-specific.

Windows:

```powershell
python -m PyInstaller --noconfirm --windowed --name OpenCoeus --collect-all pypdf --collect-all docx --collect-all sklearn -m opencoeus.ui
```

macOS and Linux:

```bash
python -m PyInstaller --noconfirm --windowed --name OpenCoeus --collect-all pypdf --collect-all docx --collect-all sklearn -m opencoeus.ui
```

The local database is created in the platform's normal per-user data location: `%LOCALAPPDATA%\OpenCoeus` on Windows, `~/Library/Application Support/OpenCoeus` on macOS, and `$XDG_STATE_HOME/OpenCoeus` (or `~/.local/state/OpenCoeus`) on Linux. If that location is read-only, it falls back to `.opencoeus` in the working folder; set `OPENCOEUS_DATA_DIR` to choose an explicit location. No network connection is used by this application.

## Current development focus

The next release focuses on safe, selective organisation:

1. Let users select or exclude individual folders after choosing a drive.
2. Recommend excluding operating-system, application, game, and source-code folders.
3. Add a rules-based organizer that works without AI.
4. Add an action preview and undo journal before enabling any file change.

The complete product scope and delivery stages are in [PROJECT_PLAN.md](PROJECT_PLAN.md). The actionable engineering backlog is in [TODO.md](TODO.md).
