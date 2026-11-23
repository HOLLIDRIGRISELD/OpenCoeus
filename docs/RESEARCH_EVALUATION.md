# Research and Evaluation Design

This document states what the project claims, how those claims could be tested, and what
would count as evidence for or against them. It is an evaluation **design**, not a results
report. No numbers are reported here because the labelled corpus and user study described
below have not been run. Where the implementation makes a measurable guarantee (for example,
"no destination is ever overwritten"), the guarantee is backed by automated tests in
`tests/`, and those tests are cited instead of unpublished measurements.

> **Status:** design + protocol + implemented mechanical checks.
> Human-facing quality claims (classification accuracy, search relevance, naming acceptance)
> remain **hypotheses** until the corpus and study in §6 are completed.

---

## 1. Problem statement

Personal and small-team document collections degrade because filing is manual, inconsistent
and postponed. The result is opaque filenames (`scan_0043.pdf`), duplicated content,
flat directories that grow without structure, and retrieval that depends on remembering
where something was put.

OpenCoeus investigates a narrow question:

> Can a fully local, hybrid system — deterministic rules plus lightweight semantic models
> plus optional local-LLM assistance — produce **useful, explainable and safe** file
> organisation and retrieval for a personal document collection, without sending any
> document content off the device and without taking irreversible action without consent?

The interesting tension is not "can an LLM rename files". It is whether **hybrid, inspectable
automation** can be good enough to trust while remaining cheap, private and reversible.

---

## 2. Research questions

| ID | Question | Why it matters |
| --- | --- | --- |
| **RQ1** | Does hybrid classification (rules + embeddings + filename hints) outperform single-signal baselines on a personal-document corpus? | Justifies the added complexity of fusion. |
| **RQ2** | Does hybrid retrieval (BM25 + semantic via RRF) outperform keyword-only and semantic-only retrieval? | Justifies maintaining two indexes. |
| **RQ3** | Are generated filenames accepted by users, and how much editing do they need? | Naming quality is the most visible output. |
| **RQ4** | Do the safety mechanisms hold under adversarial and failure conditions? | Trust is a prerequisite for adoption. |
| **RQ5** | Is the system usable without a GPU or trained embeddings installed? | Determines the real minimum hardware. |
| **RQ6** | Does a local LLM add measurable value over the non-LLM hybrid pipeline? | Justifies an optional heavy dependency. |

### Hypotheses

- **H1 (RQ1):** Hybrid macro-F1 exceeds the best single-signal baseline by a practically
  meaningful margin (target: ≥ 5 absolute points) on documents with extractable text.
- **H2 (RQ2):** Hybrid nDCG@10 exceeds both keyword-only and semantic-only ranking on
  natural-language queries, and is never materially worse on exact-token queries.
- **H3 (RQ3):** At least 70% of generated filenames are accepted with no edit or a
  single-field edit, and median normalised edit distance is below 0.25.
- **H4 (RQ4):** Under the adversarial suite in §5, zero destination files are overwritten
  and zero writes occur outside the organisation root.
- **H5 (RQ5):** With the deterministic hashing embedder, classification and search remain
  above a usable floor (macro-F1 ≥ 0.55, Recall@10 ≥ 0.60) and complete a 1 000-file scan
  and analysis within a documented time budget on CPU-only hardware.
- **H6 (RQ6):** LLM assistance changes the final decision on fewer than 10% of documents
  and improves accuracy by less than 3 points, i.e. it is a convenience, not a requirement.

H6 is deliberately framed as a *falsifiable cost*: if a local LLM does not clear that bar, the
default configuration is correctly non-LLM.

---

## 3. System under test

| Component | Implementation | Notes for evaluation |
| --- | --- | --- |
| Classification | `app/intelligence/classifier.py` — keyword evidence (0.45), semantic similarity (0.55), structural hints and a bounded confirmed-review prior; margin-weighted confidence | Deterministic seed categories; feedback starts empty and is filtered by model |
| Embeddings | `SentenceTransformerBackend` if installed, else `HashingEmbeddingBackend` (`opencoeus-hash-ngram-384-v2-idf`) | Backend name is stored per vector; never mixed |
| Retrieval | FTS5 BM25, chunk cosine, RRF (`k = 60`, α = 0.4, β = 0.6) | Weights configurable at runtime |
| Naming | Template-driven with `FilenameValidator` and collision avoidance | Same validator for generated and hand-edited names |
| Folders | Category → bounded hierarchy mapping | Max depth and segment limits enforced |
| LLM | Optional Ollama-compatible client, JSON-only output, validated | Never writes to the filesystem |

Evaluation must record which embedding backend, whether an LLM was enabled, and the fusion
weights, because results are not comparable across those settings.

---

## 4. Baselines and ablations

### Classification baselines

| Baseline | Description | Purpose |
| --- | --- | --- |
| **B0 — Majority** | Always predict the most frequent category | Floor |
| **B1 — Extension only** | Map file extension to a category | Tests whether content adds anything |
| **B2 — Filename keywords** | Rules over the original filename only | Cheap, explainable baseline |
| **B3 — Keyword-only** | Keyword evidence over extracted text (weight 1.0) | Isolates text rules |
| **B4 — Semantic-only** | Embedding similarity to category descriptions (weight 1.0) | Isolates the model |
| **B5 — Hybrid (system)** | 0.45 / 0.55 fusion + structural hints + confirmed-review prior | The proposal |

### Retrieval baselines

| Baseline | Description |
| --- | --- |
| **R0 — Filename substring** | Case-insensitive match on filename |
| **R1 — Keyword-only** | FTS5 BM25 |
| **R2 — Semantic-only** | Chunk cosine, best chunk per file |
| **R3 — Hybrid (system)** | RRF over R1 and R2 |

### Ablations

1. Remove structural hints from B5.
2. Shift fusion weights to 0.7/0.3 and 0.3/0.7 to test sensitivity.
3. Swap the trained embedder for the hashing embedder (H5).
4. Enable the local LLM as a tie-breaker (H6).
5. Vary chunk size / overlap and measure retrieval effect.
6. Remove collision avoidance from naming and count resulting conflicts (should be non-zero).

Each ablation is reported alongside its effect on **explainability** and **latency**, not just
the headline metric, because those are design constraints rather than free variables.

---

## 5. Metrics

### 5.1 Classification

- **Accuracy** and **macro-F1** (macro-F1 is primary; the category distribution is skewed).
- **Per-category precision / recall**, reported in a confusion matrix.
- **Coverage at threshold:** fraction of documents whose confidence clears the review
  threshold. Accuracy alone can be gamed by abstaining; report coverage and selective
  accuracy together.
- **Calibration:** reliability diagram and Expected Calibration Error (ECE) with 10 bins.
  Confidence is only useful if it tracks correctness.
- **Abstention quality:** among `Unclassified` outputs, what fraction were genuinely
  ambiguous versus confidently classifiable?
- **Runtime:** milliseconds per document, split into extraction and classification.

### 5.2 Retrieval

- **nDCG@10** (primary; graded relevance), **MRR@10**, **Recall@10**, **Precision@5**.
- Separate reporting for **natural-language queries** (semantic advantage expected) and
  **exact-token queries** such as invoice numbers (keyword advantage expected).
- **Rank stability** when fusion weights change.
- **Latency:** p50/p95 per query at 1 000 / 10 000 / 50 000 chunks.

### 5.3 Naming

- **Exact acceptance rate** (no edit), **minor-edit rate** (one field), **rewrite rate**.
- **Normalised Levenshtein distance** between proposed and final filename.
- **Field-level edit frequency:** title, date, organisation, category.
- **Collision and validation-failure rate** before human editing.
- **Portability violations** caught by `PathGuard` (target: all caught).

### 5.4 Safety

Measured as pass/fail over a scripted adversarial suite (see §5.5), plus:

- number of destination overwrites (target: **0**),
- number of writes outside the root (target: **0**),
- number of executions without an approved plan (target: **0**),
- undo attempts refused because preconditions failed (expected: > 0, and correct),
- recovery success rate after injected mid-move failures.

### 5.5 Adversarial and failure suite

| Case | Expected behaviour |
| --- | --- |
| Destination file already exists | `OperationConflictError`; source untouched |
| Two actions target the same path | Second action flagged as conflict |
| Destination contains `..` or is absolute outside root | `PathGuard` rejects the action |
| Reserved Windows name (`CON`, `NUL`, `LPT1`) | Rejected or sanitised |
| Filename exceeds length / path limit | Rejected with an actionable reason |
| Source deleted between plan and execute | Action fails cleanly, plan continues |
| Destination directory removed mid-run | Recreated or failed cleanly, never silently lost |
| Process interrupted after copy, before unlink | Destination verified by hash; source recoverable |
| Cross-device move | Copy → fsync → hash verify → unlink |
| Symlink in the destination path | Resolved and checked against the root |
| Content changes after organisation | Undo refused, history annotated |
| Source path reused by an unrelated file | Undo refused |
| Unsupported / corrupt file during scan | Registered, scan continues |
| Extraction raises | Recorded, analysis continues for other files |
| Embedding model missing | Deterministic fallback, no crash |

### 5.6 Performance

- Scan throughput (files/minute) and analysis throughput at a fixed file-size cap.
- Peak RSS during analysis; database growth per 1 000 files.
- Cold-start time of the GUI and of the model stack.
- Index rebuild time for FTS and embeddings.

### 5.7 Usability

- **System Usability Scale (SUS)** after a scripted task list.
- **Trust rating** (5-point) for "I understood why this was suggested".
- **Task completion** for: find a known document, rename a batch, undo a mistake.
- **Perceived safety** before and after using undo.
- Think-aloud notes on the explanation text ("evidence" panel).

---

## 6. Corpus and procedure

### 6.1 Corpus

The evaluation needs a labelled, ethically usable document set. Plan:

1. **Synthetic core (shippable).** Extend `app/demo.py` into a parameterised generator that
   produces documents with known ground-truth category, title, date, organisation and a
   set of plausible queries. Advantages: distributable, no privacy issues, exact labels.
   Limitation: generated text is cleaner than reality — treat as a sanity check, not proof.
2. **Public benchmark subset.** Use openly licensed documents (e.g. government open-data
   PDFs, arXiv papers, public-domain books) with a documented labelling guide.
3. **Consented personal collection.** Volunteers contribute documents under written consent,
   processed on their own machines; only aggregate metrics leave the device. This is the
   only source that supports claims about real personal folders.

Target size: **≥ 600 documents**, **≥ 12 categories**, at least 30 documents in the four
largest categories. At least 30% scanned/image documents to exercise OCR paths, and at least
15% duplicates or near-duplicates.

### 6.2 Labelling

- Two annotators label category, title, date, organisation independently.
- Report Cohen's κ; adjudicate disagreements; keep the adjudicated set as ground truth.
- Queries: 60 natural-language + 40 exact-token, with graded relevance (0/1/2) from at
  least two assessors.

### 6.3 Protocol

1. Freeze the corpus hash and the configuration (embedder, weights, thresholds).
2. Run baselines and system on identical inputs; record per-document predictions.
3. Compute metrics with bootstrap 95% confidence intervals (1 000 resamples).
4. Run significance testing (paired bootstrap or Wilcoxon) for H1/H2.
5. Run ablations.
6. Run the adversarial suite and the failure-injection tests.
7. Run the usability study with 12–20 participants on the demo library plus their own
   (consented) folder, counterbalancing baseline and system conditions.
8. Publish the protocol, configuration, aggregate metrics and limitations. Do **not**
   publish participant documents.

### 6.4 Reproducibility

The repository already supports deterministic runs: the hashing embedder is seeded, the demo
generator is fixed, tests use temporary data directories, and the CLI exposes every pipeline
stage. A `scripts/evaluate.py` helper (planned) would emit a machine-readable JSON report per
configuration; until then, the same effect is reached by driving `app/cli.py` and the service
layer directly.

---

## 7. What is already verified (mechanical claims)

These are checked by the automated suite (`python -m pytest`, 76 tests), not by a study:

| Claim | Where |
| --- | --- |
| Destination collisions raise and preserve the source | `tests/test_organisation.py` |
| Cross-device moves verify content before deleting the source | `tests/test_organisation.py` |
| Draft plans cannot execute without approval | `tests/test_organisation.py` |
| Unsafe destinations are rejected by `PathGuard` | `tests/test_organisation.py` |
| Undo refuses when the destination changed or the old path is occupied | `tests/test_organisation.py` |
| The full demo pipeline scans, analyses, plans, executes, searches and undoes | `tests/test_end_to_end.py` |
| Search returns results in all three modes and hybrid fuses ranks | `tests/test_search.py` |
| Settings validation is atomic | `tests/test_settings.py` |
| The GUI constructs every page headlessly | `tests/test_ui_smoke.py` |
| Generated and edited names share one validator | `tests/test_naming_and_folders.py` |

These support **RQ4** and part of **RQ5**. They say nothing about classification or retrieval
quality on real documents.

---

## 8. Threats to validity

**Internal validity**

- Category seed descriptions are part of the system; tuning them on the test corpus would
  leak. Freeze them before evaluation or use a held-out split.
- The hashing embedder is lexical, so "semantic" comparisons partly measure token overlap.
  Report backend-specific results separately.
- Confidence thresholds interact with coverage; never report accuracy without coverage.
- Demo documents are generated by the same author as the classifier and may be unrealistically
  easy to separate.

**External validity**

- Personal collections vary enormously by domain, language and scan quality. An English,
  text-heavy corpus will overstate performance for scanned or non-English folders.
- Labelling categories imposes a taxonomy users may not share; acceptance of the *proposed*
  folder may differ from agreement with the label.
- A usability study with 12–20 participants is directional, not conclusive.

**Construct validity**

- Macro-F1 assumes the label set is the right target. A user might prefer a different but
  reasonable folder; acceptance/edit distance captures this better than exact match.
- nDCG depends on assessor judgements of relevance for personal documents.
- SUS measures perceived usability, not organisation quality over months.

**Conclusion validity**

- Multiple comparisons across categories and ablations need correction or pre-registration.
- Small per-category counts make per-category conclusions unstable.

**Privacy and ethics**

- No document content or embedding leaves the device in normal operation. Evaluation must
  preserve that property: aggregate metrics only, no raw text in reports or logs.
- Consent must be explicit and revocable; participants must be able to delete their derived
  data (database and backups) at any time.
- The optional LLM defaults to `127.0.0.1`; any non-local endpoint is an explicit,
  documented deviation and should be excluded from "local-first" claims.
- Automated renaming can destroy context that only the owner understands. This is why the
  design forbids unattended execution and provides undo; the study should measure whether
  users actually use review, not just whether they *can*.

---

## 9. Success criteria

The project is defensible if, on the consented corpus:

- H1 and H2 hold with confidence intervals excluding zero effect, **or** the hybrid is shown
  to be equal-quality but better-explained and cheaper than a single large model.
- H3 acceptance clears 70% with median edit distance < 0.25.
- H4 holds with zero safety violations in the adversarial suite.
- H5 shows the deterministic fallback is usable, with latency recorded honestly.
- H6 is reported either way; a negative result ("LLM adds little") is a valid and useful
  finding for a local-first design.

If H1/H2 fail, the honest conclusions are still valuable: hybrid fusion may not be worth its
complexity at this scale, and the documentation should say so. The architecture keeps the
signals separable precisely so that this can be measured rather than assumed.
