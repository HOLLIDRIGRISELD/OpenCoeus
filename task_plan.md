# Task Plan: Accurate content-based naming, then speed

## Goal

Make OpenCoeus rename and organise documents accurately with clean, content-derived names, then make analysis substantially faster without changing pinned naming/organisation output.

## Current Phase

Phase 5: Delivery — complete.

## Source of truth

`docs/intent/opencoeus-naming-and-speed.md` — confirmed intent. Re-read it before major decisions.

## Phases

### Phase 1: Naming baseline and acceptance rules
- [x] Capture current golden suggestions vs. the meaningful originals they replaced
- [x] Define concrete "clean name" rules (length, allowed characters, no generic category label)
- [x] Write failing tests that pin the intended names
- **Status:** complete

### Phase 2: Fix content-based naming
- [x] Preserve meaningful originals when grouped name is only a generic type/entity label
- [x] Fix `_extract_subtype` matching ordinary prose
- [x] Fix `_extract_entity` shortening real names via shortest-candidate `min()`
- [x] Strip disallowed symbol soup from generated names
- [x] Regenerate golden only after intended names are confirmed
- **Status:** complete

### Phase 3: Speed without output drift
- [x] Skip extraction for known byte-identical duplicates in the same batch
- [x] Keep rehash-on-change safety; never trust stale size/mtime
- [x] Keep grouped duplicate lookup for existing analysed files
- **Status:** complete

### Phase 4: Verification and measurement
- [x] Full pytest, ruff, compileall green
- [x] Assert golden output unchanged by Phase 3
- [x] Measure analysis throughput on a synthetic corpus; record before/after in `progress.md`
- **Status:** complete

### Phase 5: Delivery
- [x] Update intent/plan/progress files with final state
- [x] Report results and remaining risks
- **Status:** complete

## Key Questions

1. Clean name: letters/digits/spaces/hyphens only; ≤ 60 chars stem; no `/`, `_`, `=`, or symbol runs.
2. Original wins when it is meaningful and the generated stem is only a generic type/entity label or `Unclassified`.
3. Speed target: 10 GB ≈ 30 min baseline; measured improvement recorded, no invented promise.

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Naming before speed | User explicitly requires speed not to worsen naming; golden is the guardrail |
| Keep golden suggestion pin | It exposed the regression; removing it hides it again |
| No staged-batch UI / LIFO undo this round | Out of scope in confirmed intent |
| Preserve originals over generic labels | `agreement.docx` is more accurate than `Contract.docx` |
| Revert entity “prefer longest” change | It produced `HLFHelicopterManual.pdf`, `MetaPlatformsInvoice.PDF` |
| Skip prefetch only for repeated recorded hashes in a batch | Rehash in analysis remains authoritative; stale hash falls back to extraction |
| Live single duplicate lookup only for skipped candidates | Keeps grouped lookup test and transaction budget intact |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| Golden mismatch after re-pinning suggestions | 1 | Inspected diff; fixed naming code, then re-pinned |
| Flaky concurrent SQLite bootstrap | 2 | Retry `PRAGMA journal_mode=WAL` on lock |
| Test setup made c.txt a real file | 1 | Removed it so chain target is free |
| `test_duplicate_lookup_is_grouped...` and DB-batching regression | 1 | Scoped live lookup to `duplicate_candidates` |
| `duplicate_candidates` not passed from batch loop | 1 | Added kwarg to `process()` call |

## Notes

- Re-read this file before major decisions.
- Baseline copy (no git): `C:\Users\seldi\AppData\Local\Temp\opencode\opencoeus-audit20-baseline`.
- Graphify outputs in `graphify-out/` are a separate codebase map, not part of this task.
