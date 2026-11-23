# OpenCoeus

**Local-first, hybrid AI for organising and finding your documents.**

OpenCoeus is a desktop application that scans a folder, understands what each document is, proposes a better filename and a sensible destination folder, and lets you approve every change before anything moves. It combines deterministic rules, local embeddings and optional local-LLM assistance. Document text, embeddings, search indexes and the audit trail never leave the machine.

> The repository contains a runnable PySide6 application, a CLI with feature parity, a test suite, architecture and research documentation.

---

## Why it exists

Personal document folders decay into `Downloads`, `final_final_v2`, duplicate invoices and files whose names say nothing about their content. Cloud "AI" organisers solve this by uploading private documents to somebody else's server. OpenCoeus takes the opposite position:

- **Local by default.** No API keys, no telemetry, no document upload. Optional AI models run through a local runtime.
- **Human in control.** Suggestions are explainable and editable. Files move only after a plan is explicitly approved.
- **Safe by construction.** Destinations are never overwritten, traversal outside the organisation root is rejected, and completed operations can be undone.
- **Useful without a GPU.** A deterministic hashing embedder keeps classification, search and recommendations working when transformer models are not installed.

---

## Features

| Area | What you get |
| --- | --- |
| Discovery | Recursive, cancellable scanning of PDF, DOCX, PPTX, XLSX, TXT/MD/CSV and images; SHA-256 hashing; unsupported formats are registered instead of crashing the scan. |
| Extraction | PyMuPDF, python-docx, python-pptx, openpyxl, text decoders and image metadata; optional Tesseract OCR. |
| Understanding | Format detection by magic bytes, title/date/organisation/document-type extraction, keyword tags, extractive summaries. |
| Classification | Hybrid of deterministic domain rules, embedding similarity and structural filename/extension hints; calibrated confidence and review threshold. |
| Recommendations | Portable filename generation from a template (`{title}`, `{date}`, `{organisation}`, `{category}`, …), collision avoidance, bounded folder hierarchy, evidence and warnings for every proposal. |
| Review | Accept, reject, reset, edit filename/folder/category; the same validator is used for generated and typed names. |
| Organisation | Read-only preview, persisted draft plan, explicit approval, per-action conflict detection, no-overwrite execution, hash verification, undo, append-only operation history. |
| Search | SQLite FTS5 keyword search, chunk-level semantic search, and Reciprocal Rank Fusion (RRF) hybrid ranking with configurable weights. |
| Duplicates | Identical-content detection by SHA-256 with wasted-space reporting. |
| Operations | Backup/restore, integrity check, FTS rebuild, VACUUM, local capability diagnostics. |
| Interface | PySide6 desktop shell (8 pages), background workers with progress/cancel, keyboard navigation, and a full CLI. |

---

## Screens at a glance

The desktop application has eight pages:

1. **Overview** – library counts, category mix, duplicates, recent operations.
2. **Scan & analyse** – choose a folder, scan, then run extraction/classification.
3. **Library** – browse indexed files, filter, inspect analysis details, open/reveal.
4. **Review** – inspect evidence, edit names/folders, accept or reject, review duplicates.
5. **Planner** – preview the effect of all accepted suggestions, save a draft plan, approve and execute.
6. **Search** – keyword, semantic or hybrid retrieval with scores and explanations.
7. **History** – audit trail, undo, backups/restore, index maintenance.
8. **Settings** – naming template, thresholds, fusion weights, local model options, capability probe.

Keyboard: `Ctrl+1` … `Ctrl+8` switch pages, `Ctrl+R` refreshes, `Ctrl+F` jumps to search.

---

## Quick start

### Requirements

- Python **3.11+** (tested with 3.14)
- A desktop environment for the GUI (the CLI works headlessly)
- Optional: `sentence-transformers` + PyTorch for trained embeddings
- Optional: an Ollama-compatible local runtime for the weak LLM tie-breaker
- Optional: Tesseract for image OCR

### Install

```bash
git clone <repository-url> opencoeus
cd opencoeus

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Optional extras:

```bash
pip install -e ".[ai]"             # sentence-transformers + torch
pip install -e ".[ocr]"            # pytesseract (Tesseract binary still required)
```

### Run the desktop app

```bash
python main.py
# or, after installation:
opencoeus-gui
```

### Try the demo library

The deterministic demo generator creates a realistic messy folder, including a duplicate and an unsupported archive:

```bash
opencoeus demo ~/OpenCoeus-Demo --scan
```

Then open the GUI, go to **Review**, accept a few suggestions, open **Planner**, preview, save, load, approve and execute.

### CLI pipeline

```bash
opencoeus scan ~/Documents
opencoeus analyse
opencoeus plan                 # read-only preview
opencoeus plan --save          # persist a draft plan
opencoeus plans
opencoeus execute 1            # approve + execute (asks for confirmation)
opencoeus search "invoice amount due" --mode hybrid
opencoeus history
opencoeus undo 3
```

Use `opencoeus --help` or `opencoeus <command> --help` for every option.

---

## How it works

```text
                    ┌──────────────────────────────────────────────┐
                    │                PySide6 UI / CLI              │
                    └───────────────────────┬──────────────────────┘
                                            │ services
        ┌───────────────────────────────────┼───────────────────────────────────┐
        │                                   │                                   │
┌───────▼────────┐                 ┌────────▼────────┐                 ┌────────▼────────┐
│   Scanning     │                 │    Analysis     │                 │   Organisation   │
│ discover+hash  │                 │ extract→classify│                 │ plan→approve→move│
└───────┬────────┘                 └────────┬────────┘                 └────────┬────────┘
        │                                   │                                   │
        │        ┌──────────────────────────┼──────────────────────────┐        │
        │        │                          │                          │        │
┌───────▼────────▼───────┐      ┌───────────▼──────────┐    ┌──────────▼────────▼──────┐
│  Processing            │      │  Intelligence        │    │  Organisation            │
│  scanner, extractors,  │      │  embeddings, rules,  │    │  planner, PathGuard,     │
│  chunking, hashing     │      │  classifier, naming, │    │  no-overwrite fsops,     │
│                        │      │  folders, local LLM  │    │  executor, recovery      │
└───────────┬────────────┘      └───────────┬──────────┘    └──────────┬───────────────┘
            │                               │                          │
            └───────────────────────────────┼──────────────────────────┘
                                            │
                              ┌─────────────▼─────────────┐
                              │  Infrastructure           │
                              │  SQLite + SQLAlchemy 2.0  │
                              │  FTS5, repositories       │
                              └───────────────────────────┘
```

### Pipeline

1. **Scan** – discover supported files, detect the real format from magic bytes, compute SHA-256, register paths and metadata. Scanning is read-only.
2. **Extract** – read text/page structure with the matching extractor. Failures are recorded and do not abort the batch.
3. **Chunk + embed** – split text on paragraph/sentence boundaries, store chunks and one vector per chunk. Embeddings are namespaced by model name so representations are never mixed.
4. **Classify** – combine keyword evidence (weight 0.45), semantic similarity to category descriptions (weight 0.55), filename/extension hints and a bounded prior from confirmed manual category decisions. Confidence is calibrated from the winning score and its margin over the runner-up. Weak evidence becomes `Unclassified` and requires review. Identical content reuses the first analysis.
5. **Recommend** – derive a portable filename from the naming template and the extracted fields, deduplicate against the destination folder, and map the category to a bounded folder hierarchy. Every suggestion carries evidence and warnings.
6. **Review** – a person accepts, rejects or edits. Edits are re-validated with the same `FilenameValidator` used by the generator.
7. **Plan** – accepted/pending suggestions are validated against the organisation root. Conflicts (existing file, duplicate target, traversal, missing source) are attached to the plan instead of being silently skipped.
8. **Approve + execute** – a draft plan cannot execute. After approval, each action is re-validated, recorded as pending, moved with an atomic no-overwrite primitive, hash-verified, indexed and marked complete.
9. **Undo** – restores the previous path only if it is free and the file has not changed since it was organised. Otherwise the history entry is flagged instead of guessing.

### Search ranking

- **Keyword:** FTS5 BM25 over filename, extracted content and AI tags.
- **Semantic:** cosine similarity against chunk embeddings; the best chunk represents the file.
- **Hybrid:** Reciprocal Rank Fusion, `score = α / (k + rank_keyword) + β / (k + rank_semantic)`, with `k = 60` and configurable α/β (defaults 0.4/0.6).

Fusion happens over ranks rather than raw scores because BM25 and cosine similarity are not on the same scale.

---

## Safety guarantees

These are invariants implemented and tested, not aspirations:

- **No overwrite.** `move_no_overwrite()` reserves the destination with `O_CREAT | O_EXCL`. Same-device moves use `os.replace` on the reservation; cross-device moves copy → fsync → hash-verify → unlink source. A collision raises `OperationConflictError`.
- **No escapes.** `PathGuard` rejects `..`, absolute destinations outside the root, non-portable filename characters, reserved Windows device names, over-long names and paths.
- **No unapproved writes.** The planner is read-only; execution requires an approved plan. Accepting a recommendation does not move anything.
- **No silent data loss.** Failed moves are recovered when possible, recorded with their reason, and never overwrite an unknown path.
- **No blind undo.** Undo checks the destination still exists, the original path is free, and the content hash still matches.
- **No cloud dependency.** There is no network code path for documents. The optional LLM client only talks to `127.0.0.1` by default.

---

## Configuration

Process configuration lives in a JSON file in the per-user data directory:

| OS | Data directory |
| --- | --- |
| Linux | `~/.local/share/OpenCoeus` (or `$XDG_DATA_HOME/OpenCoeus`) |
| macOS | `~/Library/Application Support/OpenCoeus` |
| Windows | `%LOCALAPPDATA%\OpenCoeus` |

Contents: `opencoeus.db`, `backups/`, `logs/`, optional `config.json`.

Most behaviour is stored in the database and editable in **Settings**:

- naming template and review/high-confidence thresholds
- search fusion weights
- local LLM model, endpoint and enable flag
- embedding model
- maximum analysis file size and scan batch size
- organisation root

Settings updates are validated atomically: an invalid combination changes nothing.

### Local LLM (optional)

OpenCoeus expects an Ollama-compatible HTTP API. Install Ollama once and pull the model:

```bash
ollama pull qwen2.5:3b-instruct
```

The desktop app opens the Ollama desktop app (tray icon) when it starts and closes it, along
with the server it spawns, when it closes, so no background service lingers. A runtime that is
already listening on the endpoint is reused and left running. Enable the feature in **Settings** or `config.json`. The model is deliberately constrained: it may propose a title or act as a **weak tie-breaker** only when hybrid evidence is inconclusive. It never touches the filesystem, and its output is validated. If the runtime is absent, the application continues without it.

### Embeddings (optional)

Without `sentence-transformers`, OpenCoeus uses a deterministic hashed n-gram embedder with corpus IDF weights (`opencoeus-hash-ngram-384-v2-idf`). It is a real feature-hashing technique and keeps the system functional, but it is not a trained language model. Install the `ai` extra for `all-MiniLM-L6-v2`-class embeddings.

---

## Project structure

```text
app/
  core/            configuration, constants, errors, logging, progress/cancel
  domain/          enums and framework-independent dataclasses/read models
  infrastructure/  SQLAlchemy schema, database lifecycle, FTS, repositories
  processing/      scanner, format signature, hashing, chunking, extractors
  intelligence/    embeddings, keywords, entities, classifier, naming,
                   folder recommender, local LLM, capability manager
  organisation/    PathGuard, planner, no-overwrite fsops, executor, recovery
  search/          keyword, semantic, hybrid RRF, indexer
  services/        scanning, analysis, recommendation, organisation,
                   recovery, search, settings, composition root
  ui/              PySide6 theme, widgets, workers, pages, main window
  cli.py           argparse CLI with feature parity
  demo.py          deterministic sample library
tests/             367 pytest tests across every layer
docs/              architecture, requirements, research/evaluation, ADRs, guides
main.py            GUI entry point
```

---

## Testing

```bash
python -m pytest
```

The suite uses temporary data directories, the deterministic embedder and no LLM. It covers configuration, database/FTS, scanner, chunking, extractors, hashing, classifier, naming, folder recommendation, review/edit flows, planner conflicts, no-overwrite execution, cross-device fallback, undo refusal, search modes, settings validation, an end-to-end demo pipeline and a headless GUI smoke test.

Useful commands:

```bash
python -m pytest -q
python -m pytest tests/test_end_to_end.py -v
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_smoke.py -v
```

Static checks:

```bash
python -m compileall -q app tests
ruff check app tests          # if installed
```

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md) – layers, data model, flows, failure handling, extension points.
- [Requirements](docs/REQUIREMENTS.md) – functional/non-functional requirements and acceptance criteria.
- [Research & Evaluation](docs/RESEARCH_EVALUATION.md) – research questions, baselines, metrics, planned experiments, threats to validity.
- [Design Decisions](docs/DECISIONS.md) – ADR-style record of the important trade-offs.
- [User Guide](docs/USER_GUIDE.md) – GUI-first walkthrough, safety model, troubleshooting.
- [Packaging](docs/PACKAGING.md) – PyInstaller notes for Windows/macOS/Linux.

---

## Limitations and roadmap

- Classification vocabularies are English-centric; the category seed is intentionally small and editable in the database.
- The hashing fallback is lexical, not semantic in the trained-model sense. Quality improves substantially with the `ai` extra.
- OCR is optional and not bundled with a Tesseract binary.
- The organisation root is a single directory; multiple independent libraries would need a root selector per library.
- No filesystem watcher is wired into the GUI yet.
- Planned work: labelled evaluation corpus, calibration plots, user study, incremental scan queue, duplicate-resolution actions, plugin rules UI.

---

## License

The project source is MIT. See [LICENSE](LICENSE).

Dependencies keep their own licences. In particular, **PyMuPDF is AGPL-3.0** (or commercial)
and **PySide6/Qt is LGPL-3.0** (or commercial). Distributing a bundled binary therefore has
obligations beyond the MIT text above; see [Packaging → Licensing](docs/PACKAGING.md#7-licensing-and-notices)
before publishing a build.
