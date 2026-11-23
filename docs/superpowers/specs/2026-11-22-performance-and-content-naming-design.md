# Spec: Performance and content-aware naming — V1

Status: proposed  
Date: 2026-11-22  
Intent: `docs/intent/performance-and-content-naming.md`

## Objective

Make OpenCoeus faster across startup, scan, analyse, and UI, and replace generic/counter-style names with short content-derived names and folders.

The user organises a large local document library (~11.4GB, ~5286 files). Current names such as `0001text.json.json → 001text.json` do not reveal content. Target behavior:

- `gferlhlf.pdf → HLFManual.pdf`
- `123825ofsaolkd.incoive → MetaInvoice.PDF`
- repeated Meta invoices → `Meta → Invoices → <document date>.pdf`

Speed gains must not weaken extraction, chunking, embeddings, classification, LLM gating, FTS content, duplicate reuse, cache keys, or move/undo safety.

## Tech stack

- Python 3.11+, PySide6, SQLAlchemy, SQLite/FTS5, NumPy
- Existing local extractors, hashing embeddings, classifier, naming validator, planner, PathGuard
- No new dependencies and no cloud/remote calls

## Commands

Verification after every slice:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check app tests main.py
.venv\Scripts\python.exe -m compileall -q app tests main.py
$env:OPENCOEUS_WRITE_GOLDEN=$null; .venv\Scripts\python.exe -m pytest tests/test_quality_gate.py
```

Performance measurement uses the existing `time.perf_counter()` hooks in scan/analyse plus SQLAlchemy event counters in tests. A change is kept only if it beats run-to-run variance and leaves the suite green.

## Project structure

- `app/ui/` — startup timing, refresh policies, table building
- `app/services/` — scan/analyse orchestration, batching, settings hoisting
- `app/infrastructure/` — repositories, SQL shape, indexes, batch writes
- `app/intelligence/` — content entity/type/date extraction, naming policy
- `app/organisation/` — planner and PathGuard integration
- `tests/` — RED/GREEN regression tests, perf assertions, golden gate
- `docs/intent/` — confirmed user intent
- `docs/superpowers/specs/` — this design

## Code style

No prose comments. Docstrings only where the module already uses them. Prefer pure functions for naming decisions. Example test style:

```python
def test_single_manual_gets_entity_type_name() -> None:
    name = suggest_content_name(
        original="gferlhlf.pdf",
        text="HLF Helicopter flight manual ...",
        entities=("HLF",),
        document_type="manual",
    )
    assert name == "HLFManual.pdf"
```

## Testing strategy

- TDD for every behavior change: RED, confirm intended failure, GREEN, full suite.
- Unit tests for pure naming/folder decisions.
- Repository tests for statement counts and output identity: `list_summaries(1000)` must issue O(1) queries; batched writes must produce identical rows.
- UI tests for deferred runtime, dirty refresh, lazy duplicate loading, and busy guards.
- Pipeline tests for stage overlap and batched writes; compare outputs against pre-change fixtures.
- Golden gate: for speed modules, golden diff must be empty. For `content-naming`, golden diff must list only intentional `suggested_name` / `relative_folder` changes; all extracted text, chunk, embedding, score, category, confidence, evidence, FTS, and cache-key fields stay byte-identical.
- Full suite, ruff, compileall, and quality gate after every module.

## Boundaries

- Always: TDD, full verification, no overwrites, no user-file deletion, no silent test weakening.
- Ask first: new DB columns/tables, dependency additions, LLM calls, changes to locked pipeline fields beyond the intentional naming/folder fields, golden fixture updates beyond those fields.
- Never: cloud processing, deleting user files, caching LLM results, changing extractor text/chunking/embedding precision/classifier math/FTS raw content/duplicate source selection/model-name cache keys, keeping neutral optimizations.

## Capability map

| Module id | Responsibility | Depends on |
|---|---|---|
| `startup-speed` | Defer local runtime startup; avoid needless VACUUM | — |
| `db-access` | Batch summaries/fingerprints/FTS; measure query plans | — |
| `ui-speed` | Dirty refresh, lazy duplicates, batched repo reads | `db-access` |
| `analysis-throughput` | Stage overlap, hoist settings, batch per-file writes | `db-access` |
| `content-naming` | Entity/type/date extraction, natural names, folders | `analysis-throughput` |

Build order: `startup-speed` → `db-access` → `ui-speed` + `analysis-throughput` → `content-naming`.

## Approaches

- **A — Safety-gated layered pass (chosen).** Each module is its own RED→GREEN slice with full verification. Speed modules land first with an unchanged golden. Naming lands last with a reviewed, intentional golden diff. Best attribution and rollback in a non-git workspace.
- **B — Single large rewrite (rejected).** Faster to write but impossible to attribute regressions or preserve the golden boundary cleanly.
- **C — UI-only plus heuristic naming (rejected).** Leaves scan/analyse slow and risks inconsistent names between pages and CLI.

## Detailed requirements

### startup-speed

- Move `LocalRuntime.start()` off the pre-event-loop path in `app/ui/app.py`.
- Keep `runtime.stop()` and `context.close()` in cleanup.
- Skip `purge_session_data()` VACUUM when the purge deleted zero rows, preserving existing cleanup semantics.
- Add tests that fail if runtime startup is called before `app.exec()` and if VACUUM runs on an empty purge.

### db-access

- Replace per-row `list_summaries()` queries with grouped/batched reads that preserve the exact DTO shape.
- Replace per-path fingerprint `get()` loop with a batched upsert preserving cache values.
- Batch FTS rebuild writes while preserving exact raw FTS columns and tag order.
- Measure `EXPLAIN QUERY PLAN` for hot shapes; add indexes only with before/after plans and write-cost notes. `create_all()` will not add indexes to existing tables, so any new index needs explicit `CREATE INDEX IF NOT EXISTS`.
- Add SQL statement-count tests for the hot read paths.

### ui-speed

- Mark pages dirty on library/settings changes; refresh only the current page, refresh others on next navigation. Ctrl+R remains a forced refresh.
- Guard `navigate()` against re-refreshing the same page.
- Load the duplicate table lazily on tab selection instead of every Recommendations refresh.
- Reuse already-loaded plan items for plan summary; remove duplicate `plan_items()` reads.
- Cache detail-panel renders by selected id; invalidate on refresh.
- Table filling may set row count once and suppress redundant updates, but pinned column-width and role tests must remain green.

### analysis-throughput

- Reuse `extraction.text` for FTS indexing rather than reloading full text.
- Hoist repeated settings reads (`naming_template`, `organisation_root`, `use_conventions`, thresholds) to batch start when no concurrent writes occur.
- Batch chunk/blob/tag inserts while preserving order, bytes, and chunk indices.
- Overlap extraction with embed/classify in ordered stages; per-file computation and output order remain identical.
- Cache `_existing_names` per destination folder and include reserved names; dedupe sequence must stay identical.
- Never parallelise LLM calls or cache LLM responses.

### content-naming

- Add a pure local naming resolver after classification and before suggestion persistence, also used by the duplicate-reuse path.
- Inputs available: original filename, extension, extracted text, keywords, category, confidence, evidence, profile fields (title/type/org/date/language/summary), existing folder names, existing filenames, reserved names.
- When organisation root is configured and contains the file, the file's relative parent is a low-confidence hint only. Generic parents (`Downloads`, `Documents`, `Inbox`) are ignored; content evidence, manual edits, and enabled rules still win. With no configured root the scanned parent is the root itself and is not durable entity context.
- Extract a confident company/subject entity and document type from content plus filename. No new LLM calls.
- Single file: `<Entity><Type><ext>`, title-cased, no separator, extension preserved. Example: `HLFManual.pdf`, `MetaInvoice.PDF`.
- Repeated company+type: relative folder `<Entity>/<TypePlural>/`. Inside that folder, prefer the strongest content-derived type/subtype as the filename; use the document date only when no better descriptor exists. Example: `Meta/Invoices/Statement.pdf` beats `Meta/Invoices/2026-03-14.pdf`; the date form remains the fallback.
- If neither a better subtype nor a date is available in a grouped file, use the smallest readable suffix, e.g. `Invoice 2.pdf`; never dates guessed from file mtime, hashes, amounts, long numbers, or doubled extensions.
- If no confident entity/type exists, keep the existing validator-cleaned suggestion rather than inventing a fake one.
- Preserve the original extension case from the filename; the scanner's lowercase extension stays unchanged for cache keys and metadata.
- Every result still passes `FilenameValidator`, duplicate-target claiming, `PathGuard`, and planner safety checks.
- Rules and existing-folder conventions stay opt-in and separate; new content naming is default on because the user explicitly requested it.

## Success criteria

- Interactive startup no longer waits on Ollama; runtime probe happens after the event loop starts.
- Cold startup time and analyse wall-clock are measured before/after on the same corpus; only measured wins beyond variance are kept.
- `list_summaries(1000)` issues O(1) SQL statements; Recommendations refresh never calls `list_summaries(100_000)`.
- One library change refreshes at most the current page immediately; other pages refresh on next navigation.
- Full suite `275+ passed`, ruff/compileall clean, quality gate green after every module.
- Golden diff empty for all speed modules.
- Golden diff for `content-naming` contains only intentional changes to `suggestions.filename` and `suggestions.destination`; every other golden field stays byte-identical.
- User examples produce `HLFManual.pdf` and `MetaInvoice.PDF`; repeated Meta invoices produce `Meta/Invoices/<strongest-subtype>.pdf`, falling back to `Meta/Invoices/<date>.pdf` only when no stronger subtype exists.

## Out of scope (deferred)

- OCR for scanned/manual images — needs new dependency or model, deferred.
- LLM-based naming — would change quality and gating, deferred.
- User-editable naming grammar UI — new visual/UI scope, deferred until naming behavior settles.
- Folder tree UI — previously rejected.
- New dependencies, cloud services, schema column changes.

## Open questions

- Exact entity/type confidence threshold for vague documents; default to conservative fallback in V1.
- Which date format to use in grouped folders; default `YYYY-MM-DD` unless user corrects.
- Whether to preserve original extension case; default yes because the user wrote `MetaInvoice.PDF`.

## Approval gate

Approve this spec before Phase 2 planning. No implementation code has been written.
