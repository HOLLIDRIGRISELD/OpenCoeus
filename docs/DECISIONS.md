# Design Decisions

Architecture Decision Records for OpenCoeus. Each record states the context, the decision,
the alternatives that were rejected, and the consequences — including the costs. Records are
append-only in spirit: if a decision changes, add a new record that supersedes the old one
rather than rewriting history.

| ADR | Decision | Status |
| --- | --- | --- |
| 001 | Local-first, no network dependency for documents | Accepted |
| 002 | SQLite + SQLAlchemy 2.0 as the single store | Accepted |
| 003 | FTS5 for keyword search, embeddings for semantic search | Accepted |
| 004 | Reciprocal Rank Fusion for hybrid ranking | Accepted |
| 005 | Deterministic hashing embedder as the fallback | Accepted |
| 006 | Hybrid rule + embedding classifier with abstention | Accepted |
| 007 | Human approval before any filesystem mutation | Accepted |
| 008 | Reserve-then-move for no-overwrite execution | Accepted |
| 009 | Undo only under verifiable preconditions | Accepted |
| 010 | UI consumes read models, never ORM entities | Accepted |
| 011 | Optional local LLM as a bounded tie-breaker | Accepted |
| 012 | PySide6 for the desktop shell | Accepted |
| 013 | Atomic, validated settings updates | Accepted |
| 014 | Layered package structure with a composition root | Accepted |
| 015 | Ship a CLI with feature parity | Accepted |
| 016 | Packaging with PyInstaller, not an installer framework | Accepted |

---

## ADR-001 — Local-first, no network dependency for documents

**Context.** Competing tools upload documents to a hosted service to run extraction,
classification and embeddings. For personal documents (contracts, invoices, medical records)
that is a privacy and compliance problem, and it makes the application unusable offline.

**Decision.** Every document-bearing operation — extraction, embedding, classification,
indexing, search — runs in-process or against a local runtime. The only network code path is
the optional LLM client, which defaults to `http://127.0.0.1:11434` and is disabled unless
explicitly enabled. There is no telemetry, analytics or crash-upload code.

**Alternatives rejected.**
- *Cloud inference for quality.* Rejected: violates the core premise, adds keys, cost, latency
  and an availability dependency.
- *Local-only but requiring a GPU.* Rejected: excludes most users; see ADR-005.

**Consequences.** Quality is bounded by what runs on a laptop CPU. Model downloads (if the
`ai` extra is installed) are the user's explicit action. Documentation must be honest that the
default embedder is lexical, not a trained language model.

---

## ADR-002 — SQLite + SQLAlchemy 2.0 as the single store

**Context.** The application needs files, extracted content, chunks, embeddings, analyses,
suggestions, plans, operations and settings. Options ranged from flat JSON to a client/server
database.

**Decision.** One SQLite database (`opencoeus.db`) in the per-user data directory, accessed
through SQLAlchemy 2.0 typed ORM models. WAL mode, foreign keys enabled per connection, and
short-lived sessions. Backups copy the database plus FTS state via the backup API.

**Alternatives rejected.**
- *JSON/CSV files.* Rejected: no transactions, no indexes, no concurrent readers, painful
  migrations.
- *PostgreSQL.* Rejected: requires a server; contradicts single-user local-first deployment.
- *Embedded key-value store (LMDB, RocksDB).* Rejected: loses ad-hoc SQL for reporting and
  makes the audit trail harder to inspect.

**Consequences.** SQLite is a single-writer store; long analyses must commit in batches rather
than holding a write transaction. Schema evolution is handled by idempotent `create_all` plus
explicit repair helpers, not Alembic (see ADR-014 consequences). Very large libraries
(> 10⁵ files) will need pagination and possibly a different vector index.

---

## ADR-003 — FTS5 for keyword search, embeddings for semantic search

**Context.** Users search both by exact tokens (invoice number, surname) and by meaning
("the letter about the lease renewal").

**Decision.** Maintain two independent indexes:
1. An FTS5 virtual table over filename, extracted text and tags (BM25 ranking).
2. Chunk-level vectors stored as JSON in `embeddings`, namespaced by model name, compared by
   cosine similarity in NumPy.

**Alternatives rejected.**
- *Keyword only.* Rejected: misses paraphrase and synonym queries.
- *Semantic only.* Rejected: unreliable for identifiers, numbers and rare proper nouns.
- *A dedicated vector database (FAISS, Chroma, Qdrant).* Rejected for the default install:
  another dependency and process for a personal-scale corpus. The `SearchIndexer` boundary
  keeps this replaceable.

**Consequences.** Two indexes must be kept consistent; the indexer writes both. FTS5 is
compiled into CPython's bundled SQLite on all tier-one platforms, but a rebuild command exists
because tokenizer changes and corruption happen. Brute-force cosine is O(chunks) per query;
acceptable at personal scale, and the first thing to replace at larger scale.

---

## ADR-004 — Reciprocal Rank Fusion for hybrid ranking

**Context.** BM25 scores and cosine similarities are not comparable: BM25 is unbounded and
corpus-dependent, cosine is bounded but compressed near 1.0. A weighted sum of raw scores
requires per-corpus normalisation and is fragile.

**Decision.** Fuse by rank:
`score = α / (k + rank_keyword) + β / (k + rank_semantic)`, with `k = 60`, defaults
`α = 0.4`, `β = 0.6`. Weights are configurable in Settings; the fused score is normalised to
`[0, 1]` for display and the explanation names the retrievers that contributed.

**Alternatives rejected.**
- *Weighted raw-score sum.* Rejected: scale mismatch; needs calibration per corpus.
- *Learning-to-rank.* Rejected: no labelled click data, and unexplainable to the user.
- *Cascade (keyword then semantic re-rank).* Rejected: hides semantic-only matches when the
  keyword stage returns nothing.

**Consequences.** RRF ignores score magnitudes, so a very strong keyword match can rank below
a mediocre match found by both retrievers. That is usually desirable (agreement is evidence)
but must be stated in the evaluation. α/β are a product decision exposed to the user rather
than a hidden constant.

---

## ADR-005 — Deterministic hashing embedder as the fallback

**Context.** `sentence-transformers` pulls in PyTorch (~2 GB) and may fail to install on
constrained or offline machines. An application that only works after a multi-gigabyte
download is a fragile demo.

**Decision.** An `EmbeddingEngine` selects a backend at runtime. If
`sentence-transformers` is importable and the model loads, use it. Otherwise use a
deterministic feature-hashing embedder (`opencoeus-hash-ngram-384-v2-idf`): character/word n-grams
hashed into a fixed 384-dimensional space and weighted by corpus IDF, then L2-normalised. Exact
text vectors are cached in memory and SQLite across runs. Vector rows record the model name so
representations from different backends or weighting schemes are never compared.

**Alternatives rejected.**
- *Hard dependency on transformers.* Rejected: installation friction, offline failure.
- *No fallback (disable semantic features).* Rejected: search and classification would
  silently degrade to keyword-only, and the UI would have nothing to explain.
- *A tiny bundled neural model.* Rejected for now: licensing, binary size and CPU latency.

**Consequences.** The fallback captures lexical overlap, not deep semantics. It makes the
system *functional*, not *equivalent*. Docs and evaluation must separate results by backend.
Changing backends requires re-embedding; the namespacing makes this explicit instead of
producing nonsense similarities.

---

## ADR-006 — Hybrid rule + embedding classifier with abstention

**Context.** Pure LLM classification is unexplainable and non-deterministic; pure keyword
rules are brittle. Users need a reason they can inspect, and a way to say "I don't know".

**Decision.** Combine:
- keyword evidence over extracted text (weight 0.45),
- cosine similarity between document and category descriptions (weight 0.55),
- structural hints from filename and extension as bounded adjustments.

Confidence is `0.08 + 0.52 × top_score + 0.55 × margin + 0.08 × rule_bonus` (capped at 0.98),
so a clear margin is rewarded more than a high but contested score. Confirmed manual category
decisions add a bounded nearest-vector prior (at most 0.32) to the same ranking; they are data,
not a rule patch, and are filtered by embedding model. Below the low-confidence threshold the
result is `Unclassified` and routed to review. Every result stores its evidence (matched
keywords, closest categories, scores, feedback) so the UI can show it.

**Alternatives rejected.**
- *Fine-tuned supervised classifier.* Rejected for v1: needs a labelled corpus that does not
  yet exist, and would not be explainable per document.
- *LLM-first classification.* Rejected: slow, non-deterministic, unverifiable, and a privacy
  surface if misconfigured.
- *Always answer (no abstention).* Rejected: confident wrong folders are worse than asking.

**Consequences.** Accuracy depends on category descriptions; users can edit categories and
rules in the database (a rules UI is planned). The 0.45/0.55 weights are a starting point to
be tuned by the evaluation in `RESEARCH_EVALUATION.md`, not a measured optimum.

---

## ADR-007 — Human approval before any filesystem mutation

**Context.** Automated organisers can destroy context or data. A wrong move is recoverable; a
wrong overwrite is not. Trust is the limiting factor for adoption.

**Decision.** Three distinct phases:
1. **Recommend** — suggestions are stored, never applied.
2. **Plan** — a read-only preview persisted as a draft.
3. **Execute** — only an explicitly approved plan mutates the filesystem, one action at a
   time, each re-validated immediately before the move.

Accepting a suggestion does not move a file. A draft plan cannot execute. There is no
"auto-organise" mode.

**Alternatives rejected.**
- *One-click auto-organise with undo.* Rejected: undo cannot restore a clobbered file or a
  decision the user never saw.
- *Watch-folder automation.* Deferred: same risk profile, needs a quarantine area and a
  notification design first.

**Consequences.** More clicks. Batch accept/reject mitigates this in the Review page. The
audit trail becomes meaningful because every mutation has a corresponding approval.

---

## ADR-008 — Reserve-then-move for no-overwrite execution

**Context.** `os.replace` overwrites silently. `if not exists: move()` is racy: another
process (or another action in the same plan) can create the destination between the check and
the move.

**Decision.** `reserve_path()` atomically claims the destination with
`os.open(..., O_CREAT | O_EXCL)`. On the same filesystem, `os.replace` moves the source onto
our own placeholder. Across filesystems (`EXDEV`), copy → `fsync` → hash-verify → unlink
source; on any failure the reservation is released and the source is preserved. A collision
raises `OperationConflictError` and is recorded on the plan item instead of aborting the batch.

**Alternatives rejected.**
- *Check-then-move.* Rejected: time-of-check/time-of-use race.
- *`shutil.move`.* Rejected: overwrites on POSIX and does not verify content.
- *Rename into a temp name then rename again.* Rejected: two renames do not remove the race
  on the final name; the exclusive create does.

**Consequences.** A zero-byte placeholder exists briefly; a crash between reserve and replace
can leave it behind, which the executor treats as a failed action (never as success). The
cross-device path costs a full copy and a second hash, which is the price of verified safety.

---

## ADR-009 — Undo only under verifiable preconditions

**Context.** "Undo" is dangerous if the world changed: the destination may be gone, the
original path may now hold a different file, or the content may have been edited.

**Decision.** Undo requires all of:
1. the operation exists and is completed,
2. the current file is still at the recorded destination,
3. the content hash still matches the recorded hash,
4. the original path is free.

If any condition fails, undo is refused and the history entry is annotated with the reason.
Undo restores only the path; it does not attempt to reconstruct deleted content.

**Alternatives rejected.**
- *Best-effort undo that overwrites the old path.* Rejected: destroys an unrelated file.
- *Move-to-trash instead of in-place moves.* Attractive, but out of scope for v1 and changes
  the meaning of "organise"; noted as future work.

**Consequences.** Some undos are impossible after the user edits or moves the file elsewhere.
That is correct: the application refuses rather than guesses. The operation history is
append-only, so the refusal itself is auditable.

---

## ADR-010 — UI consumes read models, never ORM entities

**Context.** Passing SQLAlchemy objects into Qt widgets keeps sessions alive, triggers lazy
loads during paint, and couples the interface to the schema.

**Decision.** Repositories return framework-independent dataclasses (`FileRecord`,
`AnalysisRecord`, `PlanRecord`, `OperationRecord`, search hits, …). The UI and CLI consume
only these. ORM objects do not cross the repository boundary.

**Alternatives rejected.**
- *Pass ORM rows with `expire_on_commit=False`.* Rejected: subtle staleness, accidental
  relationship loads, harder testing.
- *A separate DTO layer per screen.* Rejected: duplication without benefit at this size.

**Consequences.** Mapping code in repositories, and some fields must be fetched eagerly. In
exchange, the UI is testable without a database session and schema changes stay local.

---

## ADR-011 — Optional local LLM as a bounded tie-breaker

**Context.** Local instruct models are good at summarising and plausible titles, but
non-deterministic and prone to invented facts. Letting one drive file operations would be
reckless.

**Decision.** An Ollama-compatible client, disabled unless enabled, with a hard timeout. Its
only jobs are (a) proposing a title when extraction is weak and (b) breaking ties when hybrid
evidence is inconclusive. A document must actually be uncertain — low confidence, a small
top-two margin or no supported title — before the client is called; confident documents skip
the request entirely. Output must be JSON, is schema-validated, and is recorded as evidence with
the model name. It never receives a path it can act on and never writes to the filesystem.
Failure or absence is non-fatal.

**Alternatives rejected.**
- *No LLM at all.* Kept as the default in tests; the client remains optional so RQ6 can be
  measured rather than assumed.
- *LLM as the primary classifier.* Rejected: unexplainable, slow, and a privacy risk if the
  endpoint is misconfigured.
- *Bundling a model.* Rejected: size and licensing; the runtime is the user's choice.

**Consequences.** An extra moving part that must be tested for graceful absence. Prompt and
response schemas live in `app/intelligence/llm_prompts.py`; the evaluation treats LLM-on as an
ablation, not the baseline.

---

## ADR-012 — PySide6 for the desktop shell

**Context.** The project needs a native desktop application with background work, tables,
split views and file dialogs, on Windows, macOS and Linux.

**Decision.** PySide6 (Qt 6, LGPL). A single `QMainWindow` with a fixed sidebar, a
`QStackedWidget` of eight pages, and `QThread`-based workers via `BasePage.run_task()`.
Styling is a small QSS theme, not a component framework.

**Alternatives rejected.**
- *Electron/Tauri.* Rejected: duplicates the Python backend across a JS bridge, larger
  footprint.
- *Tkinter.* Rejected: weaker table/view widgets and high-DPI behaviour.
- *Web app.* Rejected: local-first desktop is the premise; a browser adds a server surface.

**Consequences.** Qt is a large dependency and LGPL compliance matters for distribution
(dynamic linking, licence notice). Threading must respect Qt's rule that widgets are touched
only on the GUI thread; the worker helper enforces that pattern.

---

## ADR-013 — Atomic, validated settings updates

**Context.** Settings interact: thresholds must be ordered, fusion weights must be
non-negative, the organisation root must exist, template placeholders must be known. Applying
half a change leaves the app in an inconsistent state.

**Decision.** `SettingsService.update_many()` validates the complete prospective state first,
then writes in one transaction. `AppContext.apply_settings()` rebuilds model-dependent
services and invalidates the lazy classifier so changes take effect immediately without a
restart. Invalid input changes nothing and returns an actionable error.

**Alternatives rejected.**
- *Write-then-validate.* Rejected: leaves corrupt state on failure.
- *Require restart.* Rejected: poor UX and hides which settings actually took effect.

**Consequences.** The settings page must send all typed values together, not field-by-field.
Rebuilding services is cheap because models are lazy, but a long-running task started before
the change keeps its snapshot — documented behaviour.

---

## ADR-014 — Layered package structure with a composition root

**Context.** The codebase must be navigable for assessment and extensible without a rewrite.

**Decision.** Layers: `core` (config, errors, logging, progress), `domain` (enums, read
models), `infrastructure` (ORM, database, repositories), `processing` (scan, extract, chunk,
hash), `intelligence` (embeddings, rules, classifier, naming, folders, LLM), `organisation`
(guard, planner, fsops, executor, recovery), `search` (keyword, semantic, hybrid, indexer),
`services` (use cases), `ui` (Qt). Dependencies point inward; `services` is the only place
that wires concrete implementations (`AppContext`).

**Alternatives rejected.**
- *Flat `models.py` / `views.py` layout.* Rejected: becomes unnavigable past a few thousand
  lines and hides coupling.
- *Full dependency-injection framework.* Rejected: disproportionate for a single composition
  root.
- *Alembic migrations in v1.* Deferred: schema is created idempotently and the app is
  pre-1.0; a migration story is required before a stable release.

**Consequences.** More files and some mapping boilerplate. In return, each layer is testable
in isolation, and replacing the embedder or vector store touches one module.

---

## ADR-015 — Ship a CLI with feature parity

**Context.** A GUI is hard to test in CI and impossible on a headless server. Demonstrating
the pipeline should not require clicking.

**Decision.** `app/cli.py` exposes scan, analyse, plan, plans, execute, search, history, undo,
demo, backup, restore, integrity, rebuild-index and capabilities. It uses the same services as
the GUI; there is no second implementation.

**Alternatives rejected.**
- *GUI only.* Rejected: untestable end-to-end in CI, poor for reproducible evaluation.
- *A separate CLI codebase.* Rejected: divergence and duplicated bugs.

**Consequences.** Service APIs must stay UI-agnostic (already required by ADR-010). CLI output
is text/JSON and therefore part of the public surface for scripts.

---

## ADR-016 — Packaging with PyInstaller, not an installer framework

**Context.** The deliverable is a source project, not a signed commercial product. Time
spent on MSI/DMG/AppImage plumbing is time not spent on correctness.

**Decision.** Document PyInstaller one-folder builds for Windows, macOS and Linux, with Qt
plugins and optional model data handled explicitly. Ship instructions and a build checklist;
do not commit binaries.

**Alternatives rejected.**
- *Briefcase / cx_Freeze / Nuitka.* Viable, but PyInstaller has the widest Qt recipe coverage.
- *Installer frameworks (Inno Setup, WiX, pkgbuild).* Deferred: signing, notarisation and
  update channels are out of scope.
- *Docker for the GUI.* Rejected: defeats the desktop use case.

**Consequences.** One-folder builds are large (Qt) and not signed; users may see OS warnings.
`docs/PACKAGING.md` records the flags, data directories and the Qt platform-plugin pitfalls so
the build is reproducible.
