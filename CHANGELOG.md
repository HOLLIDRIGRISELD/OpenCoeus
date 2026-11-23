# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Chunking is capped at 96 chunks per document and IDF fitting samples a bounded corpus (2,000
  texts / ~4M characters), keeping large-library analysis and startup time predictable.
- Accuracy work now reuses one document vector for classification instead of encoding a second
  truncated copy, and identical files reuse the first analysis without re-extracting or
  re-embedding.
- The local LLM is called only for genuinely uncertain documents; confident documents skip it.
- The hashing fallback now uses corpus IDF weights and is identified as
  `opencoeus-hash-ngram-384-v2-idf`, so old vectors are not mixed with the new representation.
- Category descriptions, confidence calibration, the rule vocabulary and the review-feedback
  prior were redesigned together rather than patched individually.
- Filename suggestions now reject code, markup, CSV rows, property lines and generic section
  labels, keep useful numeric filename prefixes, and clean syntax characters from every
  template field. When no trustworthy title exists the original filename is used.
- Titles now come from the HTML/XML `<title>` element, email `Subject` headers and ICS
  `SUMMARY` values; licence boilerplate, greetings and survey export markers are rejected or
  stripped instead of becoming filenames.
- The planner has a **Preview limit** control (default 500) used by both preview and saved
  plans, plus **New plan from pending** in **Saved plans**.
- The window chrome and pages were tightened: labels no longer paint dark rectangles on cards,
  long values open at their start, page introductions use the full content width, progress bars
  stay thin, settings cards keep their fields together, and the decorative sidebar footer (data
  path, version) and header extras (root path, privacy chip) were removed to free space.
- Opening the desktop app now starts from a clean library: scanned files, analyses, suggestions,
  extracted text, chunks, embeddings, plans and operation history are removed, while settings,
  categories and rules are kept. CLI commands keep the saved library. Disk files are untouched,
  so stale names can no longer appear after a code or template change.
- The desktop app opens the Ollama desktop app (tray icon) when it starts and closes it and the
  server it spawns when it closes. A runtime already listening on the endpoint is reused and left
  running, and a missing executable only logs an informational message.

### Fixed

- CLI commands no longer wipe the library, plans or undo history; only the desktop app clears
  session data when it opens.
- Closing the app no longer risks force-killing an unrelated process if Ollama exited and Windows
  reused its PID.
- A failed rollback now reports where the file stayed instead of leaving the database pointing at
  the old path without warning.
- File extensions again contribute structural evidence to classification, as documented.
- Removed unused helpers and prose comments across the source tree.

### Added

- Persistent exact-text embedding cache with bounded in-memory LRU, so analysis after a restart
  does not pay for repeated encodes.
- Confirmed manual category corrections are stored as vectors and add a bounded prior to future
  classifications; the classifier is rebuilt after each new decision.
- `tests/test_accuracy.py` covers calibration, cache reuse, LLM gating, IDF, feedback and
  duplicate reuse.
- Five default categories for document types found in the real library: `Government/Reports`,
  `Finance/Expenses`, `Technical/Source Code`, `Technical/Web Pages` and `Personal/Calendar`.

- The desktop UI is now responsive. The initial window size follows the available screen, the
  sidebar (176–260 px) and header (64–92 px) scale with the window, secondary header details are
  hidden when cramped, splitters use stretch ratios instead of fixed pixels, dashboard stat cards
  wrap 6/3/2/1 columns and the settings grid collapses to one column on narrow screens.
- Fractional display scaling (125%/150%/175%) is preserved instead of being rounded to whole
  integers.

### Fixed

- IDF fitting now excludes `.svg`/`.eps` hex payloads, so vector-image data cannot skew hashing
  feature weights, and documents with no extracted text stay `Unclassified` unless a filename
  keyword provides real evidence.
- Source-code and saved web pages from the real library now match `Technical/Source Code` and
  `Technical/Web Pages` instead of falling into generic personal or government categories.
- EPS and SVG files are now detected as metadata-only `vector-image` files instead of being read as
  multi-megabyte plain text, removing roughly two seconds of wasted encoding per file. Analysis
  also re-checks the current file signature, so previously misdetected rows benefit without a
  manual rescan.
- Generic or syntax-derived titles no longer collapse many files into one destination (for
  example `PowerPoint_Presentation.pptx` or a CSV header row), so the planner no longer reports
  hundreds of avoidable same-destination conflicts.
- Normal analysis no longer reprocesses the whole `pending_review` backlog; the re-analysis option
  now explicitly includes both analysed and review files.
- Classification now normalises semantic similarity using the active embedding backend. The
  hashing fallback uses its actual 0.0–0.25 cosine range, so clear documents reach the review
  threshold without extra inference while contentless files remain `Unclassified`.
- XLSX workbooks containing chart sheets no longer fail extraction; chart sheets are skipped with a
  warning while worksheet data, properties and the 20,000-cell budget are preserved.
- Truncated images now retain their readable PNG/JPEG header metadata and record a warning instead
  of failing extraction entirely. OCR and EXIF are still reported as unavailable when the pixel
  data is incomplete.
- The local LLM-health probe no longer runs for confident documents; availability is checked only
  after the deterministic uncertainty gates pass.
- Windows: case-only renames (`beta.txt` → `Beta.txt`) are now executed through a temporary
  name instead of being skipped as "no change required".
- Windows: root-relative paths such as `/etc` and drive-relative paths such as `C:temp` are
  rejected as manual folder edits instead of being treated as relative destinations.
- Windows: relative folder suggestions are stored with POSIX separators, so the review page
  shows `Finance/Invoices` rather than `Finance\Invoices`.
- Windows: the CLI now configures UTF-8 output, preventing `UnicodeEncodeError` when printing
  check marks or ellipses on regional code pages such as cp1252.
- Packaging: `project.license` now uses the SPDX string form, removing setuptools deprecation
  warnings.

### Added

- GitHub Actions CI matrix covering Windows and Ubuntu on Python 3.11 and 3.14.

## [0.6.0] — 2026-11-12

The first complete, runnable release: desktop application, CLI, pipeline, safety layer,
search, tests and documentation.

### Added

- PySide6 desktop application with eight pages (Overview, Scan & analyse, Library, Review,
  Planner, Search, History, Settings), background workers with progress and cancellation, and
  keyboard navigation.
- Recursive, cancellable scanner with magic-byte format detection, SHA-256 hashing, excluded
  directories and registration of unsupported formats.
- Extractors for PDF, DOCX, PPTX, XLSX, text/Markdown/CSV and images; optional Tesseract OCR.
- Chunking and a pluggable embedding engine: Sentence-Transformers when installed, otherwise
  a deterministic hashing embedder (`opencoeus-hash-ngram-384-v1`).
- Hybrid classifier combining keyword evidence, embedding similarity and structural hints,
  with confidence, margin, abstention and per-document evidence.
- Template-based naming with a shared validator, collision avoidance and a bounded folder
  recommendation hierarchy.
- Review workflow: accept, reject, reset and edit; manual category overrides are preserved.
- Read-only plan preview, persisted draft plans, explicit approval, per-action conflict
  reporting, no-overwrite execution, hash verification and append-only operation history.
- Guarded undo that verifies destination, content hash and a free original path.
- SQLite FTS5 keyword search, chunk-level semantic search and Reciprocal Rank Fusion hybrid
  ranking with configurable weights.
- Duplicate detection by SHA-256 with wasted-space reporting.
- Backup/restore, integrity check, FTS rebuild, VACUUM and local capability diagnostics.
- CLI with feature parity (`scan`, `analyse`, `plan`, `plans`, `execute`, `search`, `stats`,
  `duplicates`, `history`, `undo`, `backup`, `restore`, `doctor`, `capabilities`, `root`,
  `demo`).
- Deterministic 19-file demo library including a duplicate and an unsupported archive.
- 76 pytest tests across every layer, including an end-to-end pipeline and a headless GUI
  smoke test.
- Documentation: architecture, requirements and traceability, research/evaluation design,
  ADR-style decisions, user guide and packaging guide.

### Known limitations

- English-centric category seed; the taxonomy is small and editable only in the database.
- The default hashing embedder is lexical, not a trained semantic model.
- OCR requires a separately installed Tesseract binary.
- One organisation root per library; no filesystem watcher in the GUI yet.
- Classification and retrieval quality have not yet been measured on a labelled corpus; see
  `docs/RESEARCH_EVALUATION.md`.
