# Architecture

OpenCoeus is a local-first desktop application for document understanding, organisation and retrieval. This document describes the implemented architecture, the reasoning behind its boundaries and the invariants that keep filesystem operations safe.

---

## 1. Design goals

1. **Local and private.** Documents, extracted text, embeddings and the audit trail stay on the machine. Network access is limited to an optional loopback LLM runtime.
2. **Human authority.** The system proposes; the user decides. No file is renamed or moved without an approved plan.
3. **Safe by construction.** No overwrite, no traversal, no blind undo. Safety is enforced by the lowest layer that touches the filesystem, not by the UI.
4. **Graceful degradation.** Missing AI models, OCR, extractors or an LLM must reduce quality, not crash the pipeline.
5. **Explainability.** Every recommendation carries evidence, warnings and a confidence score derived from inspectable signals.
6. **Testability.** Algorithms are independent of Qt and, where possible, of the database.

---

## 2. Layered structure

```text
┌──────────────────────────────────────────────────────────────┐
│ Presentation      app/ui/*, app/cli.py, main.py              │
│                   widgets, pages, workers, argparse          │
├──────────────────────────────────────────────────────────────┤
│ Services          app/services/*                             │
│                   use-cases, orchestration, composition root │
├──────────────────────────────────────────────────────────────┤
│ Domain logic      app/intelligence/*, app/organisation/*,    │
│                   app/search/*, app/processing/*             │
│                   pure-ish algorithms and filesystem prims   │
├──────────────────────────────────────────────────────────────┤
│ Infrastructure    app/infrastructure/*                       │
│                   SQLAlchemy schema, DB lifecycle, repos     │
├──────────────────────────────────────────────────────────────┤
│ Core              app/core/*                                 │
│                   config, constants, errors, logging, cancel │
└──────────────────────────────────────────────────────────────┘
```

The dependency rule points downward: `ui → services → domain/intelligence/organisation/search/processing → infrastructure → core`. Domain logic does not import PySide6, and the UI never receives ORM entities.

### Package responsibilities

| Package | Responsibility | Key types |
| --- | --- | --- |
| `app/core` | Process configuration, constants, exception hierarchy, logging, progress/cancellation. | `AppConfig`, `OpenCoeusError`, `CancellationToken`, `ProgressEvent` |
| `app/domain` | Framework-independent vocabulary and read models. | `ScannedFile`, `DocumentProfile`, `ClassificationResult`, `NamingSuggestion`, `PlannedAction`, `FileSummary`, `SuggestionView` |
| `app/infrastructure` | Database lifecycle, schema, FTS projection, repositories. | `Database`, `Base`, `FileRepository`, `AnalysisRepository`, `OperationRepository`, `SettingsRepository` |
| `app/processing` | Read-only document input. | `FileScanner`, `inspect_format`, `sha256_file`, `chunk_text`, `ExtractorRegistry` |
| `app/intelligence` | Understanding and recommendation. | `EmbeddingEngine`, `HybridClassifier`, `NamingEngine`, `FilenameValidator`, `FolderRecommender`, `LocalLLMClient` |
| `app/organisation` | Planning and safe mutation. | `OrganisationPlanner`, `PathGuard`, `move_no_overwrite`, `FileOperationExecutor`, `RecoveryManager` |
| `app/search` | Index maintenance and retrieval. | `SearchIndexer`, `KeywordSearch`, `SemanticSearch`, `HybridSearch` |
| `app/services` | Use-cases and wiring. | `AppContext`, `ScanningService`, `AnalysisService`, `RecommendationService`, `OrganisationService`, `RecoveryService`, `SearchService`, `SettingsService` |
| `app/ui` | Desktop presentation. | `MainWindow`, eight `BasePage` subclasses, `Task`, `WorkerSignals` |

---

## 3. Composition root

`app/services/context.py` defines `AppContext`, the single place where the object graph is built.

```python
ctx = AppContext.create()          # loads AppConfig, opens SQLite, creates schema
ctx.scanning.scan(path)
ctx.analysis.analyse_pending(use_llm=False)
ctx.organisation.build_preview()
```

Properties:

- Construction creates the schema and seeds categories/settings; everything else is lazy.
- The classifier is built on first use from the category table, so adding a category changes classification without code changes.
- `apply_settings()` validates an atomic settings update, rebuilds embedding/LLM/model-manager-dependent services, re-wires services and invalidates the classifier.
- `close()` disposes the SQLAlchemy engine.

The CLI and GUI share the same context; there is no second implementation of business logic.

---

## 4. Data model

SQLite is used through SQLAlchemy 2.0 ORM. The schema is created from `Base.metadata`. FTS5 is an explicit projection rather than a trigger-maintained index.

```text
categories ──< document_analyses >── files ──< document_contents
    │                                   │  ├──< file_meta
    │                                   │  ├──< document_chunks ──< embeddings
    │                                   │  ├──< suggestions
    │                                   │  ├──< tags (via file_tags)
    │                                   │  ├──< operations >── operation_events
    │                                   │  └──< plan_items >── organisation_plans
    └──< category_rules (optional user rules)

scan_sessions     settings     file_fts (virtual, rowid = files.id)
```

### Main tables

| Table | Purpose | Notes |
| --- | --- | --- |
| `files` | Identity and current location. | `original_path` preserved; `current_path`/`current_name` updated after moves and undo; SHA-256 used for duplicates. |
| `document_contents` | Extracted text and quality. | One row per file; warnings and extraction method retained. |
| `document_chunks` | Chunk-level text. | Ordered by `chunk_index`; linked to embeddings. |
| `embeddings` | One vector per chunk/model. | Stored as JSON floats; `model_name` prevents mixing representations. |
| `document_analyses` | Versioned analysis result. | New row per analysis; latest row wins. Category, title, dates, evidence, uncertainties, scores, tags in `extra`. |
| `suggestions` | Filename/destination/category proposals. | Status lifecycle: `pending → accepted/rejected → applied/superseded`. |
| `organisation_plans` | Approved/draft plans. | Status lifecycle: `draft → approved → executing → completed/partially_completed/failed`. |
| `plan_items` | One action per file. | Stores source, destination, confidence, conflict text and per-item status. |
| `operations` | Append-only audit of attempted actions. | Original and destination hashes, undo flag, error message. |
| `operation_events` | Event log per operation. | `recorded`, `created_directory`, `verified`, `failed`, `rolled_back`. |
| `categories` | Two-level category tree. | Seeded from `DEFAULT_CATEGORIES` (including `Government`, expense, source-code, web-page and calendar leaves); user-extensible. |
| `settings` | Key/value application settings. | Typed access through `SettingsService`. |
| `scan_sessions` | Scan history and diagnostics. | Counts, status, error, timestamps. |
| `file_fts` | FTS5 virtual table. | `filename`, `content`, `tags`; `porter unicode61` tokenizer. |

### Read models

The UI deliberately never sees a SQLAlchemy entity. Repositories return frozen-in-practice dataclasses such as `FileSummary`, `SuggestionView`, `PlanItemView`, `OperationView`, `DashboardStats`, `SearchHit` and `SearchResponse`. This avoids detached-instance errors, prevents accidental lazy-loading from Qt widgets and makes UI tests possible without SQLAlchemy sessions.

---

## 5. Processing pipeline

### 5.1 Scanning

`ScanningService.scan()`:

1. Resolve the root and create a `ScanSession`.
2. Traverse with `FileScanner` (iterative, cancellable, symlink-safe, excluded directories).
3. Identify format from magic bytes (`inspect_format`), not from the extension alone.
4. Compute SHA-256 for supported files within the size limit.
5. Upsert identity and metadata into `files`.
6. Record the scan root as `organisation.root` after a successful non-cancelled scan.
7. Finish the session with counters.

Scanning never modifies files.

### 5.2 Extraction

`ExtractorRegistry` dispatches on the detected format:

| Format | Extractor | Notes |
| --- | --- | --- |
| `pdf` | PyMuPDF | Page text, metadata, page count. |
| `docx` | python-docx | Paragraphs, tables, core properties. |
| `pptx` | python-pptx | Slide text and notes. |
| `xlsx` | openpyxl | Read-only, data-only, 20k cell budget; chart sheets skipped with a warning. |
| `text` | built-in | UTF-8/UTF-8-SIG/CP1252/Latin-1 fallback. |
| `image` | Pillow | Header metadata and EXIF description; optional Tesseract OCR. Truncated files keep readable header fields with a warning. |
| `vector-image` | Pillow (metadata) | EPS/SVG: metadata-only success (`vector-metadata`), no drawing content or OCR. |

Failures produce an `ExtractionResult(success=False, error=...)`; analysis continues with filename and metadata. Documents are truncated at 2,000,000 characters to bound resource use. Analysis re-runs `inspect_format()` on the current file before dispatch, so a stale stored `detected_format` (for example an older `.eps`/`.svg` row recorded as `text`) cannot route a file to the wrong extractor.

### 5.3 Chunking and embeddings

`chunk_text()` splits on paragraph boundaries, then sentence boundaries for oversized paragraphs, with configurable target/overlap/min sizes and a chunk cap (96 chunks by default, roughly 170k characters). Each chunk becomes a `DocumentChunk`.

`EmbeddingEngine` selects a backend:

- `SentenceTransformerBackend` when `sentence-transformers` is importable and `prefer_transformer=True`;
- `HashingEmbeddingBackend` otherwise (`opencoeus-hash-ngram-384-v2-idf`).

Both return L2-normalised `float32` vectors. Exact texts are cached in a bounded in-memory LRU and in SQLite, keyed by model name, so a restart or re-analysis does not re-encode them. The hashing backend fits corpus IDF once when first selected, so rare n-gram features outweigh boilerplate without a larger model. IDF fitting samples at most 2,000 texts of 2,000 characters each (about 4M characters total), so startup cost stays flat even on a very large library. Files stored as vector-image hex payloads (`.svg`/`.eps`) are excluded from that sample, so encoded drawing data cannot skew feature weights. Different model names are never compared.

### 5.4 Classification

`HybridClassifier` combines:

- **Rule score**: word-boundary matches against domain vocabularies (`_RULES`), normalised by 3 and capped at 1. Top-level hints add 0.25 each.
- **Semantic score**: cosine similarity between the document vector and each category description vector. Transformer similarities are rescaled from a 0.05 baseline to 1.0; the non-semantic hashing fallback uses a 0.0 baseline and 0.25 scale because its raw cosine range is much narrower. The document vector is the mean of the already-computed chunk vectors, so classification adds no second encode.
- **Feedback prior**: cosine similarity to confirmed manual category decisions adds at most `0.32`, is filtered by embedding model, and is shown in evidence.
- **Combined score**: `0.45 × rules + 0.55 × semantics + feedback prior`.
- **Confidence**: `0.08 + 0.52 × top_score + 0.55 × margin + 0.08 × rule_bonus`, capped at `0.98`, where `rule_bonus = min(1, rule_hits / 3)`. Margin is weighted more heavily than the raw score.
- **Insufficient evidence**: if `top_score < 0.22` **or** the document has no extracted text or title, and no rule matched, the result is `Unclassified` with low confidence and `needs_review=True`. This stops no-text files such as images without OCR from being assigned a category purely from a filename-derived vector.

Evidence includes matched terms, semantic similarity, keyword score, the runner-up category and any feedback prior. The classifier never invents a category outside the database descriptions. Byte-identical files reuse the first analysis without re-extracting or re-embedding; filename and folder suggestions are regenerated for the new path.

The default seed taxonomy covers council/government reports, expense/spending datasets, source code, web pages and calendar files alongside the original education, finance, business, personal and technical leaves. Rule vocabularies in `_RULES` mirror the real vocabulary found in those documents; adding new system categories still only requires a seed row plus, optionally, a rule tuple.

### 5.5 Recommendation

1. `extract_title()` prefers document metadata, then a plausible heading, then a cleaned filename. `title_supported` records which case applied.
2. `extract_date()`, `extract_organisation()` and `extract_document_type()` only return values supported by the text; unknown values stay `None`.
3. `NamingEngine` renders the template with available fields. Unavailable tokens are removed cleanly. The result is sanitised by `FilenameValidator`, checked against Windows reserved names and truncated portably, then deduplicated against the destination folder (`_2`, `_3`, …).
4. Confidence favours a supported title: `min(0.98, 0.65 × classification + 0.35)` for supported titles, `0.10` instead of `0.35` for fallback titles.
5. `FolderRecommender` maps the category path to at most `max_depth` components, reuses an existing folder case-insensitively when possible and reports whether the folder is new.
6. Suggestions are persisted with explanation, evidence and warnings; previous pending suggestions are superseded.
7. The file status becomes `analysed` or `pending_review`.

### 5.6 Local LLM (optional)

`LocalLLMClient` speaks the Ollama-compatible HTTP API with the standard library. It is enabled only when configured, has a health probe and expects JSON-only output that is parsed defensively. Its role is bounded:

- it may propose a title only when the document did not provide a supported one, and the uncertainty is recorded;
- it may agree with a category (small confidence bump) or act as a weak tie-breaker only when the hybrid result is uncertain (low confidence, small top-two margin or no supported title) and it is at least 60% confident;
- it can never override a strong hybrid result, execute an operation or write a file. Confident documents skip both the availability probe and the call entirely.

When absent, `AnalysisService` records the lower-quality path in evidence and continues.

---

## 6. Organisation and safety

### 6.1 Planning

`OrganisationService.build_preview()` reads pending/accepted suggestions, resolves the organisation root and builds `PlanEntry` objects. `OrganisationPlanner` is a pure transformation:

- assign `RENAME`, `MOVE` or `RENAME_AND_MOVE` by comparing source and destination;
- mark exact no-ops as `unchanged`;
- validate destinations with `PathGuard`;
- detect duplicate targets within the same plan;
- annotate low-confidence entries;
- return a `PlanDraft` with safe actions, blocked actions, skipped entries and warnings.

`build_preview()` writes nothing. `create_plan()` persists the draft. `approve()` transitions `draft → approved`. `execute()` refuses a draft unless `require_approval=False` is explicitly passed (used only by controlled tooling).

### 6.2 PathGuard

Every destination is checked for:

- `..` path traversal;
- containment inside the resolved organisation root;
- portable filename validity (Windows-invalid characters, trailing dots/spaces, reserved device names, length limits);
- parent components that are files rather than directories;
- existing destinations (never replaceable);
- duplicate destinations claimed by another action in the same plan.

Source checks distinguish errors (missing, not a file) from warnings (source outside root, which is allowed because the move brings it inside).

### 6.3 No-overwrite execution

`move_no_overwrite()` implements the core safety primitive:

```text
reserve destination with O_CREAT | O_EXCL     # atomic claim
        │
        ├── same device: os.replace(source, destination)   # atomic rename over our placeholder
        │
        └── EXDEV: copy2 → flush → fsync → verify hash → unlink source
                    │
                    └── on any failure: remove the partial destination, keep the source
```

Because the destination name is claimed before data is written, a concurrent process cannot win a check-then-move race. `os.replace` is only allowed to replace the empty placeholder created by this process.

After the move, the executor verifies size and, for files below the hash limit, SHA-256. It updates the canonical path, refreshes FTS, records `verified` and marks the operation complete. On failure it attempts to restore the source, records the reason and marks the item failed. An operation is recorded *before* the move, so a crash still leaves an audit row.

### 6.4 Undo

`RecoveryManager.undo()` requires:

- operation status `completed`;
- `undoable = True`;
- the organised file still exists;
- the original path is free;
- the current hash matches the recorded destination hash.

If any condition fails, the operation is invalidated with an explanation and the file is left untouched. Undo itself uses `move_no_overwrite`, updates the DB location, restores the processing status, refreshes FTS and appends a `rolled_back` event.

### 6.5 Plan status semantics

| Status | Meaning |
| --- | --- |
| `draft` | Persisted, not approved, cannot execute. |
| `approved` | Approved, not yet started. |
| `executing` | In progress. |
| `completed` | Every action completed. |
| `partially_completed` | Some actions completed, others failed or were skipped (for example conflicts). |
| `failed` | Nothing completed. |
| `revalidation_required` | Reserved for plans whose inputs changed before execution. |

Blocked actions remain in the plan for transparency; they are reported as skipped and never touch the filesystem.

---

## 7. Search architecture

### Index maintenance

`SearchIndexer.index_file()` is called after analysis, execution and undo. It combines filename, extracted content and tag names into `file_fts`. FTS is rebuilt explicitly (`RecoveryService.rebuild_search_index()`) rather than through triggers, because the indexed text spans three tables and analysis is batched.

### Retrieval

- `KeywordSearch` tokenises the query, removes stopwords, quotes tokens and joins with `OR` to avoid FTS5 syntax errors and absent-term failures. BM25 rank is converted to a bounded score.
- `SemanticSearch` loads all vectors for the active model, computes dot products (vectors are normalised), keeps the best chunk per file, normalises the visible score and returns a query-centred snippet.
- `HybridSearch` fuses ranks with RRF (`k=60`), applies `alpha`/`beta` from settings and prefers the semantic snippet when both retrievers agree.

`SearchService` validates the mode, applies current weights, catches failures (a search error must not crash the UI), annotates hits with categories and returns notes explaining the mode and fallbacks.

---

## 8. Concurrency and UI integration

- Qt runs on the main thread. `BasePage.run_task()` starts a `QThread`-backed `Task`, connects progress signals before starting and marshals results back with signals.
- Services are thread-safe by construction: each repository call opens a short SQLAlchemy session; the database uses `check_same_thread=False`, WAL (on disk), `synchronous=NORMAL`, a 15-second busy timeout and foreign keys enabled per connection.
- Cancellation is cooperative through `CancellationToken`; scanners, analysers and executors check it between units of work.
- The classifier is lazily created behind a lock and invalidated when settings change.
- The UI refreshes cross-page data through signals (`library_changed`, `navigate`) rather than direct page coupling.

---

## 9. Error handling and degradation

| Failure | Behaviour |
| --- | --- |
| Unsupported format | Registered as `unsupported`; analysis skips it with a clear status. |
| Extraction failure | Stored with `success=False`; recommendations fall back to filename/metadata; status becomes pending review. |
| Missing transformer model | Deterministic hashing embedder; search notes explain the fallback. |
| Missing/failed LLM | Analysis continues silently but records lower confidence where relevant. |
| Invalid settings | Atomic rejection with human-readable problems; nothing changes. |
| Database write failure during analysis | File marked `failed`, batch continues. |
| Move conflict | Action skipped with a conflict message; source remains. |
| Move failure | Source restored when possible; operation logged as failed. |
| Undo precondition failure | Operation invalidated with a reason; file untouched. |
| Search failure | Empty result plus an explanatory note; UI remains usable. |

Errors derive from `OpenCoeusError` and carry a `user_message` suitable for dialogs.

---

## 10. Extension points

- **New document format:** implement `BaseExtractor` (`name`, `version`, `formats`, `extract`) and register it in `ExtractorRegistry`. Add the extension to `AppConfig.supported_extensions` if it should be scanned by default.
- **New category vocabulary:** add a row to `categories` (UI/DB) and, optionally, a rule tuple in `HybridClassifier._RULES`. The classifier rebuilds on the next settings change or restart.
- **New naming token:** add the field to `NamingEngine.suggest()` and document it in the template error message/user guide.
- **New search retriever:** implement the `search(query, limit)` shape, then add it to `HybridSearch` or `SearchService`.
- **Scheduled/watched folders:** no watcher is wired in yet; a watcher service would need a filesystem-watch dependency and should enqueue scans through the same pipeline.
- **New UI page:** subclass `BasePage`, add it to `NAVIGATION` and the `pages` dict in `MainWindow`.

---

## 11. Design trade-offs

| Decision | Benefit | Cost |
| --- | --- | --- |
| SQLite + FTS5 | Zero-ops, local, transactional, excellent text search. | Single-writer; very large libraries need batching. |
| ORM + read models | Type safety and UI decoupling. | Two mappings to maintain. |
| Hashed fallback embeddings | Works everywhere, deterministic tests. | Lexical rather than trained semantics. |
| Rules + semantics | Explainable and robust with little data. | Rule vocabulary needs maintenance. |
| Persisted plans | Auditability and re-validation. | More state to manage than an in-memory action list. |
| Sequential execution | Predictable conflict detection and progress. | Slower than parallel moves on network storage. |
| Optional local LLM | Better titles/tie-breaks on capable machines. | Additional runtime and model management. |

See [DECISIONS.md](DECISIONS.md) for the decision records and rejected alternatives.
