# Packaging and Distribution

OpenCoeus is a Python + PySide6 desktop application. This document describes how to build a
standalone, runnable application for Windows, macOS and Linux with PyInstaller, what must be
bundled, where user data lives, and what to check before calling a build releasable.

The project intentionally ships **build instructions, not binaries**. The deliverable should
be reproducible from source; committing multi-hundred-megabyte artifacts is neither reviewable
nor portable.

---

## 1. What the build must include

| Component | Why it matters |
| --- | --- |
| `main.py` + the `app` package | GUI entry point and all application code |
| PySide6 Qt libraries and **platform plugins** | Missing `platforms/` is the most common "it won't start" failure |
| PyMuPDF (`fitz`) | PDF extraction; needs its native library |
| python-docx, python-pptx, openpyxl | DOCX/PPTX/XLSX extraction |
| Pillow | Image metadata and thumbnails |
| SQLAlchemy + SQLite | Storage; SQLite is part of the Python runtime |
| numpy | Embedding maths |
| `app/demo.py` assets | None — the demo is generated programmatically |
| Optional: Tesseract binary | OCR; **not** bundled by default |
| Optional: sentence-transformers + torch | Trained embeddings; **not** bundled by default (very large) |

The deterministic hashing embedder is pure Python + NumPy, so a lean build is fully
functional: classification, semantic search, planning and execution all work without
PyTorch.

---

## 2. Prepare the environment

Build on the **target OS**. PyInstaller does not cross-compile: a Windows `.exe` must be
built on Windows, a macOS `.app` on macOS, and a Linux binary on a compatible Linux
distribution (glibc is not portable across old/new systems).

```bash
cd opencoeus
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pip install pyinstaller              # packaging only; not a dev extra
python -m pytest                     # do not package a failing tree
```

For a lean build, do **not** install the `ai` extra. If you want trained embeddings bundled,
install it and expect a very large artifact plus platform-specific PyTorch libraries.

---

## 3. Build

### One-folder (recommended)

Faster startup, easier to inspect, and simpler to patch than one-file.

```bash
pyinstaller \
  --name OpenCoeus \
  --windowed \
  --noconfirm \
  --clean \
  --collect-submodules app \
  --collect-data PySide6 \
  main.py
```

Output: `dist/OpenCoeus/` with `OpenCoeus` (or `OpenCoeus.exe`) inside.

- `--windowed` suppresses the console. Keep the console during debugging; remove it for
  release.
- `--collect-data PySide6` is a blunt instrument. If the artifact is too large, rely on
  PyInstaller's Qt hook and instead verify that `platforms/`, `styles/`, `imageformats/` and
  (on Windows) `translations/` are present.
- `--collect-submodules app` guards against lazy/indirect imports being missed. All
  extractors and intelligence modules are imported explicitly, so this is belt-and-braces.

### One-file (optional)

```bash
pyinstaller --name OpenCoeus --onefile --windowed --noconfirm --clean main.py
```

One-file extracts to a temporary directory at every launch: slower cold start, and some
antivirus products are more suspicious of it. Prefer one-folder for a desktop app.

### Icon and version metadata

```bash
# Windows icon + version resource
pyinstaller --name OpenCoeus --windowed --icon assets/opencoeus.ico ^
  --version-file packaging/version_info.txt main.py

# macOS icon + bundle identifier
pyinstaller --name OpenCoeus --windowed --icon assets/opencoeus.icns ^
  --osx-bundle-identifier org.opencoeus.app main.py
```

Provide icons in `assets/` if you add them; none are required for a functional build.

### A minimal `.spec` file

If you prefer a checked-in spec, start from the generated one and make the data collection
explicit:

```python
# OpenCoeus.spec (excerpt)
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "app.processing.extractors.pdf",
        "app.processing.extractors.docx",
        "app.processing.extractors.pptx",
        "app.processing.extractors.xlsx",
        "app.processing.extractors.text",
        "app.processing.extractors.image",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas", "torch", "sentence_transformers"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, exclude_binaries=True, name="OpenCoeus", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="OpenCoeus")
```

`excludes` keeps the artifact small **only if those packages are installed**; excluding torch
is correct for the lean build, but do not exclude it and then expect trained embeddings at
runtime.

---

## 4. Platform notes

### Windows

- Build in a clean VM or CI runner to avoid picking up unrelated DLLs.
- Test on a machine **without** Python and **without** Visual C++ redistributables if you
  target non-developers; ship the redistributable if required by your Qt/PyMuPDF build.
- Unsigned executables trigger SmartScreen. Signing requires a code-signing certificate;
  document the limitation rather than pretending it does not exist.
- Long paths: Windows path limits still apply. OpenCoeus validates names and paths, but the
  organisation root should not sit at the edge of `MAX_PATH`.
- Case-insensitive filesystems: case-only renames are supported via a temporary name, and
  relative folder suggestions use `/` separators so the database stays portable.
- The CLI reconfigures its streams to UTF-8 at startup, so check marks and ellipses print
  correctly even when the console code page is cp1252.

### macOS

- Build on the oldest macOS version you intend to support.
- PyInstaller produces a `.app` bundle in `dist/OpenCoeus.app`.
- Unsigned, un-notarised apps are blocked by Gatekeeper on other machines. For internal use,
  users can right-click → Open. For distribution, sign with a Developer ID and notarise:

  ```bash
  codesign --deep --force --options runtime --sign "Developer ID Application: …" \
    dist/OpenCoeus.app
  xcrun notarytool submit dist/OpenCoeus.zip --keychain-profile … --wait
  xcrun stapler staple dist/OpenCoeus.app
  ```

- Apple silicon and Intel need separate builds (or a universal2 Python + Qt, which is
  possible but easy to get wrong). Do not claim universality without testing both.
- Quantum/torch builds on macOS are especially sensitive to architecture mismatch.

### Linux

- Build on the oldest glibc you support (for example the oldest current LTS). A binary built
  on a rolling distribution often fails elsewhere.
- Test on a session with Wayland **and** X11; Qt chooses the platform plugin at runtime.
- Common missing runtime libraries: `libxcb-cursor0`, `libxkbcommon-x11-0`, `libegl1`,
  `libgl1`. Document them per distribution; do not assume a desktop install has them.
- AppImage or Flatpak are reasonable next steps, but they are packaging projects of their
  own. The PyInstaller folder is the supported baseline.

---

## 5. Runtime behaviour of a packaged build

- The application writes only to the per-user data directory (see below) and to the
  organisation root the user chooses. It does not write next to the executable.
- On first launch it creates the database and seeds categories/settings. A packaged app
  therefore needs **write permission** to the user's data directory.
- Logs go to `<data dir>/logs/`; backups to `<data dir>/backups/`.
- Configuration may be overridden with `config.json` in the data directory, or with CLI flags
  when launching the CLI.

| OS | Data directory |
| --- | --- |
| Linux | `$XDG_DATA_HOME/OpenCoeus` or `~/.local/share/OpenCoeus` |
| macOS | `~/Library/Application Support/OpenCoeus` |
| Windows | `%LOCALAPPDATA%\OpenCoeus` |

A portable/USB build that stores data beside the executable is **not** implemented. Doing it
properly means resolving the data directory at runtime, handling read-only media, and
migrating existing databases. Do not fake it with a relative path.

---

## 6. Optional components

### Trained embeddings

Bundling `sentence-transformers` pulls in PyTorch (hundreds of megabytes) and a model cache.
If you do it:

- Trigger a model download at build time so the weights are present, and set
  `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` at runtime to prevent surprise downloads.
- Verify the packaged app loads the model with no network.
- Expect OS-specific native libraries; test on a clean machine.

The default build deliberately omits this and uses `opencoeus-hash-ngram-384-v2-idf`.

### Local LLM

Never bundle the runtime. Ollama (or any compatible server) is a separate installation the
user opts into. The client defaults to `http://127.0.0.1:11434`; packaging must not introduce
a remote default.

### OCR

Tesseract is a native binary with language data. Either instruct users to install it and put
it on `PATH`, or bundle it explicitly with its licence files. `pytesseract` alone is not
enough.

---

## 7. Licensing and notices

The project source is MIT, but **dependencies have their own licences** and some are
copyleft:

| Dependency | Licence (verify for your version) | Implication |
| --- | --- | --- |
| PySide6 / Qt | LGPL-3.0 (or commercial) | Dynamic linking, provide licence text and allow replacement of Qt libraries |
| PyMuPDF | **AGPL-3.0** (or commercial) | Bundling it in a distributed binary triggers AGPL obligations; a commercial licence removes them |
| SQLAlchemy | MIT | Attribution |
| python-docx, python-pptx, openpyxl | MIT | Attribution |
| Pillow | HPND | Attribution |
| NumPy | BSD-3-Clause | Attribution |
| sentence-transformers, PyTorch | Apache-2.0 / BSD-style | Attribution; model weights have their own terms |

**This matters for a public release.** MIT applies to *this* code; it cannot relicense
PyMuPDF. If you distribute a bundled binary, either comply with the AGPL for PyMuPDF (offer
the corresponding source and licence) or replace it with a permissively licensed PDF library
(for example `pypdf` for text extraction, accepting weaker layout support) before claiming a
fully MIT distribution. The same caution applies to Qt's LGPL: dynamic linking and notices
are required.

Include a `THIRD_PARTY_NOTICES` file with the exact versions and licence texts in any real
release. This document is guidance, not legal advice.

---

## 8. Release checklist

**Before building**

- [ ] `python -m pytest` passes (76 tests at the time of writing).
- [ ] `python -m compileall -q app tests` succeeds.
- [ ] Version bumped in `pyproject.toml` and `app/core/constants.py`; they agree.
- [ ] No development data directory, logs, backups or `.db` files inside the tree.
- [ ] No secrets, API keys or personal paths in tracked files.

**Build**

- [ ] Built on the target OS and oldest supported version.
- [ ] Artifact contains Qt `platforms/` plugins and the native libraries for PyMuPDF.
- [ ] Optional extras are either fully bundled and tested or explicitly absent.

**Smoke test on a clean machine (no Python installed)**

- [ ] App starts and shows the Overview page.
- [ ] `Ctrl+1`…`Ctrl+8` navigate; `Ctrl+R` refreshes.
- [ ] Demo library can be scanned and analysed.
- [ ] Review → Planner → Approve → Execute moves a file; History → Undo restores it.
- [ ] Search works in keyword, semantic and hybrid modes.
- [ ] Settings → Probe models reports the deterministic fallback honestly.
- [ ] Data directory, logs and backups are created in the expected per-user location.
- [ ] No network traffic during scan, analysis, search or execution.
- [ ] Uninstall/removal instructions are accurate and do not imply user documents are deleted.

**Distribute**

- [ ] Licence and third-party notices included.
- [ ] Checksums published next to the artifact.
- [ ] Known limitations documented (unsigned binary, OCR/LLM/model not bundled, English-centric
      categories).

---

## 9. Troubleshooting the build

**`Could not find the Qt platform plugin "xcb"` (Linux)**
Qt plugins were not collected. Rebuild with `--collect-data PySide6`, or copy
`PySide6/Qt/plugins/platforms/` into the bundle's `platforms/` directory. On the target
machine, install `libxcb-cursor0` and related XCB libraries.

**`ModuleNotFoundError: fitz` / missing native PDF library**
PyMuPDF's binary was not collected. Ensure PyMuPDF is installed in the build environment and
that PyInstaller's hook runs; inspect `build/OpenCoeus/warn-OpenCoeus.txt`.

**App starts then exits immediately**
Build once **without** `--windowed` to see the traceback. The most common causes are a
missing hidden import, an unwritable data directory, or a database created by an incompatible
version.

**The artifact is enormous**
Exclude `torch`, `sentence_transformers`, `tkinter`, `matplotlib` and `pandas` if they leaked
in from the environment. Build in a dedicated virtual environment rather than a system Python
with many packages installed.

**Antivirus flags the executable**
Common for unsigned PyInstaller binaries. Signing helps; submitting a false-positive report
to the vendor helps; one-file builds are flagged more often than one-folder.

**It works on the build machine but not another**
Usually a missing system library, an architecture mismatch (Apple silicon vs Intel), or an
older glibc on the target. Build on the oldest target and test on a clean VM.
