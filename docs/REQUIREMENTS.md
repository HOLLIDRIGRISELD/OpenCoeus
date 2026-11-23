# Requirements

This document defines the implemented scope of OpenCoeus and the acceptance criteria used to verify it. Requirements are written in an EARS-style form (`When … the system shall …`) so they can be traced to tests and demonstrations.

---

## 1. Scope

### In scope

- A local desktop application for Windows, macOS and Linux.
- Scanning a chosen directory tree and registering supported documents.
- Extracting text and metadata from PDF, DOCX, PPTX, XLSX, plain text/Markdown/CSV and images.
- Hybrid classification into a two-level category tree.
- Filename and destination-folder recommendations with explanations.
- Human review, editing, acceptance and rejection of recommendations.
- Previewing, approving and executing organisation plans.
- Safe rename/move operations with undo and an audit trail.
- Keyword, semantic and hybrid search over extracted content.
- Duplicate detection by content hash.
- A command-line interface with feature parity for scripting and headless environments.
- Database backup, restore and integrity maintenance.

### Out of scope (for this release)

- Cloud synchronisation, accounts, multi-user collaboration or remote APIs for documents.
- Mobile applications.
- Editing document contents.
- Automatic deletion of duplicate files.
- A trained proprietary classification model or a fine-tuned LLM.
- Real-time folder watching in the GUI (the dependency is reserved, but no watcher page ships).
- Multi-root libraries managed simultaneously.

---

## 2. Actors and personas

| Actor | Goal |
| --- | --- |
| **Owner** (primary) | Regain control of a messy personal or study folder without uploading private documents. |
| **Reviewer** | Inspect and correct AI proposals before any file changes. |
| **Power user / developer** | Automate scanning, analysis and search through the CLI; extend formats and categories. |
| **Evaluator / researcher** | Reproduce the pipeline on a labelled corpus and measure classification, retrieval and safety. |

---

## 3. Functional requirements

### 3.1 Scan and discovery

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-01 | When the user selects a readable directory, the system shall recursively discover files in supported formats. | Nested supported files appear once; excluded directories (`.git`, `.venv`, `node_modules`, `__pycache__`, …) are skipped. |
| FR-02 | When scanning, the system shall identify the real format from file content, not only the extension. | A PDF named `.dat` is detected as `pdf`; a ZIP renamed `.docx` is `unknown`. |
| FR-03 | When scanning supported files, the system shall compute a SHA-256 digest. | Every supported registered file has a 64-character hash unless hashing is explicitly disabled or fails. |
| FR-04 | When a file cannot be read, the system shall record the error and continue scanning. | The scan report contains the path/message; other files are still registered. |
| FR-05 | When the user requests it, the system shall register unsupported files with status `unsupported` without analysing them. | Counts and statuses reflect the unsupported file; no extractor error aborts the scan. |
| FR-06 | When the user cancels a scan, the system shall stop traversal promptly and mark the session cancelled. | No partial file is modified; session status is `cancelled`. |
| FR-07 | When a scan completes successfully, the system shall remember its root as the organisation root. | The configured root equals the resolved scan root. |
| FR-08 | When the same root is scanned again, the system shall update existing records instead of duplicating them. | File count is stable; `updated` increases and `created` is zero. |

### 3.2 Extraction and understanding

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-09 | When analysing a supported document, the system shall extract readable text with the format-specific extractor. | Text, method, page count where available, warnings and quality are stored. |
| FR-10 | When extraction fails, the system shall continue with filename/metadata evidence and record the reason. | The file reaches review with an uncertainty; the batch does not abort. |
| FR-11 | When text is long, the system shall split it into overlapping chunks on paragraph/sentence boundaries. | Chunks are ordered, bounded and capped; embeddings match chunk count. |
| FR-12 | When the user has not installed a transformer model, the system shall use the deterministic hashing embedder. | Analysis and semantic search still work; the model name is recorded and search explains the fallback. |
| FR-13 | When a document is analysed, the system shall derive a title, date, organisation and document type only from supported evidence. | Unknown values remain empty; fallback titles are marked unsupported. |
| FR-14 | When a document is analysed, the system shall store tags, a short summary, extracted evidence, inferred evidence and uncertainties. | These fields are visible in the review detail pane and persisted in the analysis row. |
| FR-15 | When images are analysed without OCR, the system shall index filename and available EXIF metadata. | The file is usable for organisation/search; missing content is reported. |

### 3.3 Classification

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-16 | When a document is classified, the system shall combine deterministic keyword evidence and embedding similarity. | The result exposes component scores and a method string. |
| FR-17 | When evidence is weak, the system shall route the document to `Unclassified`/review rather than guessing. | Low evidence produces `needs_review=True` and a low confidence. |
| FR-18 | When a category is added to the database, the system shall use its description on the next classifier build. | No code change is required; the classifier is invalidated/rebuilt. |
| FR-19 | When a document is classified, the system shall provide human-readable evidence. | Evidence names matched terms, semantic similarity and/or the runner-up category. |
| FR-20 | When a local LLM is available, the system shall use it only as a bounded title/tie-break aid. | Strong hybrid results are retained; LLM disagreement is recorded; no filesystem action is delegated. |
| FR-21 | When no local LLM is available, the system shall proceed without error. | `report.llm_used` is zero; no connection errors escape. |

### 3.4 Recommendations

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-22 | When generating a filename, the system shall render the configured template and remove unavailable fields cleanly. | No `None`, empty separators or unresolved tokens appear. |
| FR-23 | When generating a filename, the system shall produce a portable, bounded name. | Invalid characters, reserved device names, trailing dots/spaces and over-length names are handled with warnings. |
| FR-24 | When a generated name collides in the destination, the system shall choose a free variant. | `_2`, `_3`, … are used and a warning is attached. |
| FR-25 | When recommending a folder, the system shall stay within the configured depth and reuse existing folders case-insensitively. | Relative path contains at most `max_depth` components. |
| FR-26 | When producing any recommendation, the system shall include a confidence, explanation, evidence and warnings. | All fields are present in the review detail and database rows. |
| FR-27 | When a recommendation is regenerated, previous pending suggestions shall be superseded. | The pending list contains one filename/destination/category set per file. |

### 3.5 Human review

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-28 | When a suggestion is pending, the user shall be able to accept, reject or reset it. | Status changes are persisted and reflected in the pending list. |
| FR-29 | When the user edits a filename, the system shall validate it with the same validator as generated names. | Empty/invalid names are rejected; valid names are accepted with confidence 1.0. |
| FR-30 | When the user edits a folder, the system shall reject absolute paths and `..` escapes. | Invalid edits return problems and leave the suggestion unchanged. |
| FR-31 | When the user changes a category, the system shall update the analysis, the destination suggestion and mark the method `manual`. | Review detail shows the new category, confidence 1.0 and an audit note. |
| FR-32 | When a file is accepted, the system shall not move or rename it. | The filesystem is unchanged until an approved plan is executed. |
| FR-33 | When duplicate content exists, the system shall group files by SHA-256 and report wasted bytes. | Groups contain all matching files; counts and sizes are correct. |

### 3.6 Planning

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-34 | When the user previews a plan, the system shall build it without writing to the database or filesystem. | Repeated previews leave file mtimes and plan tables unchanged. |
| FR-35 | When a destination is invalid, occupied, duplicated in the plan or escapes the root, the system shall mark the action as blocked with a reason. | Blocked actions remain visible; safe actions are separated. |
| FR-36 | When a file's proposed location equals its current location, the system shall mark it unchanged. | No action is emitted for that file. |
| FR-37 | When the user saves a plan, the system shall persist a draft plan and its items. | Plan status is `draft`; item count and paths match the preview. |
| FR-38 | When a plan has no effective actions, the system shall refuse to create it. | `InvalidRecommendationError` is raised with an explanatory message. |
| FR-39 | When the user approves a plan, the system shall transition it from `draft` to `approved` only. | Executing a draft is refused. |
| FR-40 | When a plan has already completed or failed, the system shall refuse to execute it again. | A clear error is returned. |

### 3.7 Execution and recovery

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-41 | When executing an action, the system shall re-validate source and destination immediately before moving. | A file that disappeared or a destination that appeared is handled safely. |
| FR-42 | When a destination exists, the system shall never overwrite it. | The source remains; the destination content is unchanged; the action is skipped/failed with a reason. |
| FR-43 | When moving across filesystems, the system shall copy, flush, verify and only then remove the source. | A failed copy leaves the source intact and removes the partial destination. |
| FR-44 | When a move completes, the system shall verify size/hash, update the file location, refresh search and log a completed undoable operation. | Database path, FTS result and operation history agree. |
| FR-45 | When a move fails, the system shall attempt to restore the source and log the failure. | No silent loss; history contains the error. |
| FR-46 | When the user undoes a completed operation, the system shall restore the original path only if it is free and the content is unchanged. | Otherwise the operation is invalidated with a reason and the file stays put. |
| FR-47 | When an operation is undone, the system shall update the file location/status, refresh search and append a rolled-back event. | History status is `rolled_back`; the file is discoverable at the restored path. |
| FR-48 | When an operation is blocked or failed, it shall not be reported as undoable. | `undoable` is false. |

### 3.8 Search and retrieval

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-49 | When the user searches by keyword, the system shall query FTS5 without exposing raw FTS syntax errors. | Punctuation-only queries return no results; normal queries return ranked hits. |
| FR-50 | When the user searches semantically, the system shall rank files by best chunk similarity. | Results include score, snippet and the embedding model name. |
| FR-51 | When the user searches in hybrid mode, the system shall fuse keyword and semantic ranks with RRF using configured weights. | Weights from settings are used; explanations name the retrievers. |
| FR-52 | When a search returns results, the system shall annotate them with their category and an explanation. | The UI shows category, score and snippet. |
| FR-53 | When a search fails or is empty, the system shall return a usable response with notes rather than raising. | The UI remains responsive. |
| FR-54 | When files move or are undone, the system shall refresh the full-text index. | Search finds the file at its current location. |

### 3.9 Settings, maintenance and diagnostics

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-55 | When settings are saved, the system shall validate all values atomically. | Any problem returns messages; no value is partially written. |
| FR-56 | When settings change, the system shall rebuild model-dependent services immediately. | New thresholds/weights/models apply without restart. |
| FR-57 | When the naming template lacks `{title}` or `{original}`, the system shall reject it. | A clear validation problem is returned. |
| FR-58 | When the user requests a backup, the system shall create a consistent SQLite copy. | The file opens and contains the same data. |
| FR-59 | When the user requests restore, the system shall warn that a restart is required. | The CLI refuses without confirmation; the UI explains the restart. |
| FR-60 | When maintenance is requested, the system shall support integrity check, FTS rebuild and VACUUM. | Each returns success/failure without corrupting data. |
| FR-61 | When diagnosing capabilities, the system shall report embedding, LLM, OCR and optional-library status and fallbacks. | `opencoeus doctor` and the Settings page show the same information. |

### 3.10 Interfaces

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| FR-62 | When the GUI is used, all long-running work shall run off the UI thread with progress and cancellation. | The window remains responsive; Cancel stops scan/analysis. |
| FR-63 | When the CLI is used, it shall expose scan, analyse, search, stats, duplicates, plan, plans, execute, history, undo, backup, restore, doctor, capabilities, root and demo. | Commands and `--help` operate without Qt. |
| FR-64 | When a page is opened, it shall display current data and handle an empty database gracefully. | All eight pages render with zero files. |
| FR-65 | When the user presses the documented shortcuts, navigation shall work. | `Ctrl+1…8`, `Ctrl+R`, `Ctrl+F` behave as documented. |

---

## 4. Non-functional requirements

### 4.1 Privacy and security

| ID | Requirement |
| --- | --- |
| NFR-01 | Document content, embeddings, metadata and history shall remain on the local machine. |
| NFR-02 | The only permitted network target shall be the configured loopback LLM endpoint; no document upload path shall exist. |
| NFR-03 | The application shall not require an account, API key or telemetry consent. |
| NFR-04 | Filenames and destinations shall be validated against traversal, reserved names and portable-character rules. |
| NFR-05 | Execution shall be gated by explicit human approval and shall never overwrite an existing path. |
| NFR-06 | The audit trail shall record every attempted operation and its outcome. |

### 4.2 Reliability and data integrity

| ID | Requirement |
| --- | --- |
| NFR-07 | A single unreadable or unsupported file shall not abort a scan or analysis batch. |
| NFR-08 | A failed move shall leave the source recoverable and the destination unmodified. |
| NFR-09 | Undo shall refuse unsafe restores rather than guess. |
| NFR-10 | Database writes shall be transactional; schema creation and seeding shall be idempotent. |
| NFR-11 | Backups shall use SQLite's online backup API so they are consistent while the app is running. |
| NFR-12 | The system shall verify content hashes after moves and before undo when a hash is available. |

### 4.3 Performance and scalability

| ID | Requirement |
| --- | --- |
| NFR-13 | Scanning and analysis shall be incremental and cancellable, with progress feedback. |
| NFR-14 | Exact-text embedding vectors shall be cached in memory and SQLite and reused across runs; model names shall separate vector spaces. |
| NFR-15 | FTS queries shall be indexed and bounded by a configurable result limit. |
| NFR-16 | The database shall use WAL, a busy timeout and foreign-key enforcement for concurrent UI/worker access. |
| NFR-17 | Chunking and extraction shall enforce size/chunk/cell budgets to avoid pathological memory use. |
| NFR-18 | Target: a 1,000-file, text-based library should remain usable on a modern laptop; large PDFs and OCR dominate runtime. (To be measured on the evaluation corpus.) |

### 4.4 Usability and accessibility

| ID | Requirement |
| --- | --- |
| NFR-19 | Every recommendation shall be explainable in plain language with evidence and warnings. |
| NFR-20 | Confidence shall be shown as a percentage and grouped into high/medium/low bands. |
| NFR-21 | Destructive or irreversible actions shall require confirmation and explain their consequence. |
| NFR-22 | The UI shall use a consistent visual language, readable contrast and keyboard navigation. |
| NFR-23 | Errors shown to users shall be actionable and avoid raw tracebacks. |
| NFR-24 | The interface shall remain usable at 1080×720 and scale to larger windows. |

### 4.5 Portability and maintainability

| ID | Requirement |
| --- | --- |
| NFR-25 | The application shall run on Python 3.11+ on Windows, macOS and Linux. |
| NFR-26 | Core algorithms shall be testable without Qt, network access or optional AI packages. |
| NFR-27 | Optional capabilities shall be detected at runtime and degrade explicitly. |
| NFR-28 | The codebase shall follow a documented layer structure with no UI imports in domain logic. |
| NFR-29 | Public modules shall carry docstrings explaining intent, inputs and failure behaviour. |
| NFR-30 | The test suite shall run headlessly and use isolated temporary data directories. |

---

## 5. Acceptance scenarios

These scenarios are exercised by the automated suite and can be demonstrated manually.

### A. Safe first run

1. Start with an empty database.
2. All eight pages render without errors.
3. A scan of a folder registers files and sets the organisation root.
4. Analysis produces suggestions but no file is modified.

### B. Human correction

1. Open a pending suggestion and read the evidence.
2. Edit the filename to an invalid value; the edit is rejected.
3. Edit it to a valid value; the suggestion is accepted at confidence 1.0.
4. Change the category; the destination follows and the method becomes `manual`.

### C. Conflict safety

1. Create two files that would receive the same destination.
2. Preview a plan; one action is blocked with a conflict reason.
3. Execute the plan; the safe action completes, the blocked file stays in place.

### D. No-overwrite

1. Create a destination file before execution.
2. Attempt execution; the existing file is unchanged and the source is preserved.
3. History explains why the action was skipped.

### E. Undo

1. Execute a rename/move.
2. Undo it; the original path is restored and the history entry is `rolled_back`.
3. Recreate a file at the original path and attempt another undo; the operation is refused and invalidated.

### F. Search continuity

1. Search for a document before and after a move.
2. The same document is found with its updated path.
3. Keyword, semantic and hybrid modes all return explainable results.

### G. Degraded environment

1. Run without `sentence-transformers` and without an LLM.
2. Scanning, analysis, review, planning, execution, search and undo still work.
3. The UI/CLI explain the fallbacks.

---

## 6. Traceability

| Area | Primary implementation | Primary tests |
| --- | --- | --- |
| Scanner/discovery | `app/processing/scanner.py`, `app/services/scanning_service.py` | `tests/test_scanner.py` |
| Extraction/chunking/hashing | `app/processing/*` | `tests/test_processing.py` |
| Database/FTS/repositories | `app/infrastructure/*` | `tests/test_database.py` |
| Classification | `app/intelligence/classifier.py` | `tests/test_classifier.py` |
| Naming/folders | `app/intelligence/naming_engine.py`, `folder_recommender.py` | `tests/test_naming_and_folders.py` |
| Review/edit | `app/services/recommendation_service.py` | `tests/test_recommendations.py` |
| Planning/safety/undo | `app/organisation/*` | `tests/test_organisation.py` |
| Search | `app/search/*`, `app/services/search_service.py` | `tests/test_search.py` |
| Settings | `app/services/settings_service.py`, `app/services/context.py` | `tests/test_settings.py` |
| End-to-end pipeline | all of the above | `tests/test_end_to_end.py` |
| GUI shell | `app/ui/*` | `tests/test_ui_smoke.py` |

---

## 7. Assumptions and constraints

- The user has read access to the selected folder and write access to the organisation root.
- The filesystem is case-sensitive or case-insensitive; conflict detection resolves paths and compares lower-cased destination keys within a plan.
- A single organisation root is configured at a time.
- The local LLM, when used, is an untrusted advisory component.
- Evaluation results depend on the corpus, language and installed embedding model; the repository reports the configuration alongside any measurement.
