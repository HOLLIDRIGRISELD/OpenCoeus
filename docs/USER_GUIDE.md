# User Guide

OpenCoeus scans a folder, works out what each document is, and proposes a better filename
and a sensible destination. **Nothing is renamed or moved until you approve a plan**, and
completed changes can be undone. Everything — extraction, classification, embeddings,
search — runs on your machine.

This guide is written for the desktop application. A CLI exists for scripting and testing;
see [README](../README.md#cli-pipeline) for its commands.

---

## 1. Install and first run

### Requirements

- Python 3.11 or newer (tested with 3.14)
- A desktop session (the GUI needs a display; the CLI does not)
- Optional: `sentence-transformers` for trained embeddings
- Optional: a local Ollama-compatible runtime for the weak LLM tie-breaker
- Optional: Tesseract for OCR of scanned images

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
pip install -e ".[ocr]"            # pytesseract (install the Tesseract binary separately)
```

### Start

```bash
python main.py
# or, after installation:
opencoeus-gui
```

On first launch OpenCoeus creates its data directory and database:

| OS | Data directory |
| --- | --- |
| Linux | `~/.local/share/OpenCoeus` (or `$XDG_DATA_HOME/OpenCoeus`) |
| macOS | `~/Library/Application Support/OpenCoeus` |
| Windows | `%LOCALAPPDATA%\OpenCoeus` |

It contains `opencoeus.db`, `backups/` and `logs/`. You do not need to create or configure
anything to get started.

> Want sample material? `opencoeus demo ~/OpenCoeus-Demo --scan` creates a realistic messy
> library (19 files including a duplicate and an unsupported archive) and scans it. Then
> continue with step 3 below. Remove the folder when you are done.

---

## 2. The window at a glance

The sidebar has eight pages. The header shows where you are; the status bar shows the most
recent message.

| Page | What it is for |
| --- | --- |
| **Overview** | Counts, category mix, duplicates, recent operations. |
| **Scan & analyse** | Choose a folder; run discovery and the analysis pipeline. |
| **Library** | Browse every indexed file; inspect analysis details. |
| **Review** | Accept, edit or reject each suggestion; inspect duplicates. |
| **Planner** | Preview the effect of accepted suggestions; save, approve, execute. |
| **Search** | Keyword, semantic or hybrid retrieval. |
| **History** | Audit trail, undo, backups, index maintenance. |
| **Settings** | Naming template, thresholds, fusion weights, models, storage. |

Keyboard shortcuts: `Ctrl+1` … `Ctrl+8` switch pages, `Ctrl+R` refreshes the current page,
`Ctrl+F` jumps to the search box.

A typical session is **Scan → Analyse → Review → Planner → Execute → Search**, with
**History** available whenever you want to undo.

---

## 3. Scan a folder

1. Open **Scan & analyse**.
2. Press **Browse…** or type a path. Scanning is read-only.
3. Leave **Include subfolders** on unless you want a shallow scan.
4. Leave **Compute SHA-256 hashes** on. Duplicate detection and post-move verification
   depend on hashes.
5. **Register unsupported formats** records files OpenCoeus cannot read (for example ZIP or
   audio) so they appear in the library instead of being silently ignored.
6. Press **Start scan** and watch the progress bar and activity log. **Cancel** stops cleanly;
   already-registered files remain.

The root of the most recent scan becomes the default **organisation root** — the directory
that proposed folders are relative to. The scan page log prints it after every scan. You can
override it in **Settings** (see §10).

What the scan does and does not do:

- It detects the real format from magic bytes, not just the extension.
- It records size, timestamps, hash and path. It does **not** read document text yet.
- It never modifies, renames or deletes anything.

**Tips**

- Scanning a very large folder is fine; files above the maximum analysis size are registered
  but skipped during extraction (configurable in Settings).
- Excluded directories (`.git`, `.venv`, `node_modules`, caches, recycle bins) are skipped.
- If a file changes after scanning, re-scan before analysing so the hash is current.

---

## 4. Analyse the library

Still on **Scan & analyse**, the second card runs the pipeline:

1. **Extract** text and structure with the format-specific extractor.
2. **Chunk and embed** the text, storing one vector per chunk.
3. **Classify** into a category using keyword evidence, embedding similarity and structural
   hints. The default categories include government reports, expense/spending data, source code,
   web pages and calendar events as well as the original education, finance, business, personal
   and technical groups.
4. **Recommend** a filename (from your template) and a folder, with evidence and warnings.

Files with no extracted text (for example images without OCR) stay **Unclassified** for review
unless their filename contains a clear category keyword (such as "invoice"); in that case the
filename is used as the only available evidence.

Options:

- **Use the local language model when available** — only has an effect if a local runtime is
  reachable and enabled, and the hybrid result is uncertain. Confident documents skip the call;
  the model can suggest a title or break a tie but never touches files. The desktop app opens the
  Ollama tray app when it starts and closes it when it closes; pull the model once with
  `ollama pull qwen2.5:3b-instruct`.
- **Re-analyse processed and review files** — include files already analysed earlier in this
  session. Opening the desktop app starts from an empty library: scanned files, analyses,
  suggestions, plans, scans and operation history are forgotten, and settings and categories are
  kept. Nothing on disk is touched, so scan the folder again after opening. CLI
  commands use the saved library instead.

Press **Analyse pending files**. Only new or unfinished files are processed unless the re-analysis
option is checked. Failures (corrupt PDF, unreadable image, password-protected
document) are recorded per file and do not abort the batch. The activity log names them.

When it finishes, press **Review recommendations →** or open **Review** in the sidebar.

### What "no model installed" means

If `sentence-transformers` is not installed, OpenCoeus uses a deterministic hashing embedder.
Classification and semantic search still work, but they capture lexical overlap rather than
deep meaning. The Settings page shows which backend is active. Install the `ai` extra and
re-analyse to upgrade; cached vectors are discarded on the next launch.

---

## 5. Review suggestions

The **Review** page has two tabs.

### Suggestions tab

Each row is a document with its proposed filename, folder, category, confidence and status.
Select a row to open the detail panel on the right:

- **Evidence** — why this category and name were chosen (matched keywords, closest
  categories, confidence, warnings).
- **Filename** — edit it. The same validator used by the generator rejects empty names,
  illegal characters, reserved Windows names and over-long paths, and normalises spaces to
  underscores.
- **Folder** — edit the relative destination. It must stay inside the organisation root.
- **Category** — override it manually. The change is recorded as `manual`, so future
  analysis does not silently overwrite your judgement.

Buttons:

| Button | Effect |
| --- | --- |
| **Save changes** | Validates your edits, stores them and marks the suggestion accepted. Moves nothing. |
| **Accept** | Accepts the current suggestion as-is. |
| **Reject** | Excludes it from planning. |
| **Reset** | Restores the generated suggestion. |
| **Accept all shown** | Bulk-accepts the current filter. Use with care. |
| **Open file** / **Show in folder** | Inspect the original without changing it. |
| **Go to planner →** | Jumps to the next step. |

Status meanings:

- **pending** — not reviewed yet; included in a plan preview by default.
- **accepted** — will be included in the plan.
- **rejected** — excluded.
- **edited** — accepted with your changes; revalidated.

### Duplicates tab

Identical content (same SHA-256) is grouped with wasted space. OpenCoeus never deletes
automatically. Resolve duplicates yourself (open and compare, then remove or archive the
copy you do not want), or leave them; the planner will refuse to move two files to the same
destination and report the conflict instead of overwriting.

> Low-confidence files appear as **Unclassified** and are worth reviewing first. A wrong
> confident guess is the failure mode the review threshold exists to prevent. When you manually
> choose a category, that decision is remembered as a bounded hint for similar documents; it is
> shown in later evidence and never overwrites a strong result by itself.

---

## 6. Plan and execute

Open **Planner**.

1. **Preview limit** — sets how many suggestions are used for the preview and the saved plan
   (default 500). Raise it for a larger batch; large values take longer to rebuild.
2. **Rebuild preview** — computes every action from accepted/pending suggestions plus your
   edits, and validates it against the organisation root. This is read-only.
3. Check the summary cards: actions, conflicts, skipped. Every conflict is listed with its
   reason (destination exists, two actions target the same path, unsafe name, missing
   source).
4. **Save as draft plan** if you want to inspect it later or execute from the CLI. Saved
   plans are listed with their status.
5. **New plan from pending** — in **Saved plans**, clears the current selection and rebuilds
   the preview from the current pending suggestions, so a blocked plan does not trap the tab.
6. **Approve plan** — approval is a separate, explicit step. A draft cannot execute.
7. **Execute approved plan…** — asks for confirmation, then processes actions one at a time.

During execution each action is re-validated, recorded as pending, moved with an atomic
no-overwrite primitive, hash-verified, re-indexed and marked complete. A failed action does
not abort the rest of the plan; its reason is recorded and the plan ends as
`partially_completed` if anything failed.

**What "no overwrite" means in practice.** The destination is claimed with an exclusive
create before the move. If anything already exists at that path — including a file created
after the preview — the action fails safely and your source file stays where it was. There is
no code path that replaces an existing file.

**Conflicts are normal.** The demo library contains a deliberate duplicate invoice, so two
actions target the same destination. One wins; the other is reported as a conflict. Nothing
is lost.

---

## 7. Search

Open **Search**, type a query and choose a mode:

| Mode | Best for |
| --- | --- |
| **Keyword** | Exact tokens: invoice numbers, surnames, project codes. |
| **Semantic** | Meaning: "the letter about the lease renewal". |
| **Hybrid** (default) | Everything else; fuses both by rank. |

Results show the file, a snippet, the score and an explanation naming the retrievers that
contributed. **Open document** and **Show in folder** open the current location.

Search covers filenames, extracted text and tags. It does not search inside images unless
OCR was installed and produced text. If a document was moved outside OpenCoeus, its stored
path is stale — re-scan the folder.

---

## 8. History and undo

Open **History** for the append-only audit trail. Filter by status, then:

- **Undo selected…** restores a completed operation to its original path. Undo is allowed
  only when:
  1. the file is still at the recorded destination,
  2. its content hash still matches,
  3. the original path is free.

  Otherwise the undo is refused and the reason is shown. This is deliberate: guessing could
  destroy an unrelated file. Undo restores the path only; it cannot reconstruct content you
  deleted or edited.

- **Create backup** writes a timestamped copy of the database to `backups/`.
- **Restore selected…** replaces the current database with a backup. This affects the
  *index and history*, not your files. Close other windows before restoring.
- **Check database integrity**, **Rebuild search index** and **Compact database** are
  maintenance actions for corruption, stale search results or disk reclamation.

Operations are never deleted from history while the app is open. A refused or failed action stays
visible with its reason. The history, plans and scans belong to the current session and are
cleared the next time OpenCoeus starts.

---

## 9. Settings

Open **Settings**. Changes are validated as a whole: if one value is invalid, nothing is
saved and an error explains why. Valid changes apply immediately — no restart.

| Group | Settings |
| --- | --- |
| Organisation | **Root** — the directory proposed folders live under. Empty means "use the most recent scan root". It must exist. |
| Naming | **Filename template** and its available tokens (for example `{title}`, `{date}`, `{organisation}`, `{category}`). |
| Thresholds | **High-confidence threshold** and **Review threshold** (must be ordered). |
| Search | **Keyword weight (alpha)** and **Semantic weight (beta)**, non-negative. |
| Models | **Embedding model**, **Prefer transformer embeddings**, **Enable local LLM**, LLM model and endpoint. |
| Processing | **Maximum analysis size**, **Scan progress batch**. |
| Storage | **Data directory** (read-only display). |

**Probe models** reports what is actually available locally: transformer availability,
the active embedding backend, and whether the LLM endpoint responds. Use it before
concluding that AI features are broken.

Changing the embedding model or naming template affects the next analysis; opening the desktop
app clears the previous derived cache, and **Force** re-analyses files already handled in this
session.

---

## 10. Safety model in one page

| Guarantee | How it is enforced |
| --- | --- |
| Nothing changes during scan, analysis or preview | Those code paths are read-only. |
| Nothing changes without approval | Execution requires an approved plan; drafts are rejected. |
| No destination is ever overwritten | `O_CREAT \| O_EXCL` reservation, then atomic replace or verified copy. Collisions raise. |
| No writes outside the organisation root | `PathGuard` rejects traversal, absolute escapes, reserved names and over-long paths. |
| No silent loss on failure | Cross-device moves verify the hash before removing the source; failed actions are recorded, not hidden. |
| No blind undo | Destination, hash and free original path are all checked. |
| No cloud dependency | No network code path for documents; the LLM client defaults to `127.0.0.1`. |

The application cannot protect you from yourself outside it: if you delete or edit a file in
another program, undo will refuse rather than guess.

---

## 11. Troubleshooting

**The window does not appear, or Qt complains about a platform plugin.**
On a headless machine use the CLI. In CI or a remote session set
`QT_QPA_PLATFORM=offscreen` (tests) or ensure `DISPLAY`/`WAYLAND_DISPLAY` is set correctly.
On Linux, missing XCB/Wayland libraries are an OS package issue, not a Python one.

**"Semantic search is unavailable" or results look keyword-only.**
The embedding backend failed to load. Open **Settings → Probe models**. The deterministic
fallback should still work. If you installed the `ai` extra, check the model name and disk
space, then re-analyse.

**Analysis is slow or a file is skipped.**
Large files above **Maximum analysis size** are skipped by design; raise the limit
deliberately. Scanned PDFs and images need OCR, which is optional. First analysis is slower
because models load lazily.

**Classification is poor.**
English-centric categories, short documents and scans without OCR all reduce quality. Review
and correct low-confidence items; manual category overrides are preserved. Trained embeddings
improve semantic similarity. See [Research & Evaluation](RESEARCH_EVALUATION.md) for what is
and is not claimed.

**A filename looks sparse, e.g. `INVOICE.pdf`.**
Generic headings produce generic titles. Edit the name in Review, or use a richer template
that includes `{date}` or `{organisation}`. Names are generated from the document's top
title-like lines and, for web and XML files, their `<title>` element; code, markup, CSV rows,
greeting lines, licence boilerplate and generic section labels are ignored, and the original
filename is used when no trustworthy title exists. Suggestions belong to the current session, so
every analysis uses the current naming rules.

**The planner reports conflicts.**
A destination already exists, two actions target the same path (often duplicates), or a name
is unsafe. Resolve duplicates in the **Duplicates** tab, edit the suggested folder/name, or
reject one of the suggestions. Conflicted actions never overwrite anything.

**Execute does nothing / "plan must be approved".**
Approval is separate from saving. Press **Approve plan**, then execute. A plan that was saved
as a draft stays a draft.

**Undo is refused.**
The file moved or changed, or the original path is occupied. The History page states which
condition failed. Restore manually if appropriate; do not expect the app to overwrite.

**"Database is locked".**
Another OpenCoeus window, the CLI, or a backup is writing. Close the other process and retry.
WAL mode allows concurrent readers but only one writer.

**Search returns stale paths.**
Files were moved outside OpenCoeus. Re-scan the folder. Completed operations inside OpenCoeus
update the index automatically.

**I want a clean start.**
Just close and reopen the app: each launch forgets the scanned files, analyses, plans and history,
and never touches your documents. Settings and categories are kept.

---

## 12. Where to go next

- [README](../README.md) — overview, CLI, configuration.
- [Architecture](ARCHITECTURE.md) — how the layers fit together.
- [Requirements](REQUIREMENTS.md) — what is specified and how it is verified.
- [Research & Evaluation](RESEARCH_EVALUATION.md) — claims, baselines, metrics, study design.
- [Design Decisions](DECISIONS.md) — why the system is built this way.
- [Packaging](PACKAGING.md) — building a standalone application.
