# Progress Log

## Session: 2026-11-23

### Phase 1: Naming baseline and acceptance rules
- **Status:** complete
- Actions:
  - Ran read-only detective subagents: organisation flow, performance bottlenecks, review triage.
  - Fixed remaining review findings with red→green regressions.
  - Interviewed user; confirmed intent: naming accuracy first, speed second, no output regression.
  - Saved intent + file-based plan (`task_plan.md`, `findings.md`, `progress.md`).
  - Added clean-name acceptance tests in `tests/test_quality_gate.py`.

### Phase 2: Fix content-based naming
- **Status:** complete
- Actions:
  - `NamingEngine.suggest()` keeps meaningful originals when title is unsupported.
  - Opaque stems still get document-type names; meaningful stems survive.
  - `_extract_subtype()` requires explicit label or standalone hint.
  - `FILENAME_SEPARATOR` switched from `_` to a space; symbol soup rejected.
  - Reverted entity longest-candidate change (worse long names).
  - Updated separator expectations across tests; re-pinned golden fixture.

### Phase 3: Speed without output drift
- **Status:** complete
- Actions:
  - `analyse_pending()` skips prefetch extraction for repeated hashes in the same batch.
  - Root fix: prefetched duplicate map no longer blocks live rehash-based duplicate lookup.
  - Live lookup scoped to `duplicate_candidates` so grouped lookup/transaction tests stay green.
  - Added regressions: in-batch duplicate extracted once; stale hash with changed bytes still extracted.

### Interruption
- Graphify full pipeline ran on `.` between phases; outputs in `graphify-out/`. No naming/speed code changed by it.

### Phase 4: Verification and measurement
- **Status:** complete
- Actions:
  - Full pytest, ruff, compileall green.
  - Golden output unchanged by speed work.
  - Synthetic 200-file benchmark: extractions 200 → 20; wall time 4.349 s → 3.991 s (small text), 5.853 s → 4.452 s (10× text).

### Phase 5: Delivery
- **Status:** complete
- Actions: updated `task_plan.md`, `findings.md`, `progress.md`; reported remaining risks.

## Test Results

| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| Full pytest | `pytest -q --tb=line -rf -p no:cacheprovider` | all pass | all pass (~475 tests, 1 fitz FutureWarning) | ✓ |
| Ruff | `ruff check app tests` | clean | All checks passed | ✓ |
| Compileall | `compileall -q app tests main.py` | exit 0 | exit 0 | ✓ |
| Golden snapshot | `test_analysis_outputs_match_the_golden_snapshot` | pinned names | pass | ✓ |
| Clean names | `test_generated_names_are_accurate_readable_and_symbol_free` | no generic/symbol names | pass | ✓ |
| In-batch duplicate | `test_known_duplicate_is_not_extracted_twice` | one extraction | pass | ✓ |
| Stale hash safety | `test_stale_duplicate_hash_still_extracts_changed_bytes` | changed file extracted | pass | ✓ |
| Grouped lookup budget | `test_duplicate_lookup_is_grouped_and_skips_empty_hashes` | no single lookups | pass | ✓ |

## Error Log

| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-11-23 | `c.txt` conflict in revalidate test | 1 | Removed real file; chain target free |
| 2026-11-23 | Golden suggestion mismatch | 1 | Fixed naming code, then re-pinned |
| 2026-11-23 | Concurrent bootstrap `database is locked` | 2 | Retry WAL pragma; busy_timeout first |
| 2026-11-23 | Duplicate test still extracted both files | 1 | Prefetch map was treated as authoritative; added live rehash lookup |
| 2026-11-23 | DB batching + grouped lookup regressions | 1 | Scoped live lookup to `duplicate_candidates` |
| 2026-11-23 | Candidates arrived as `None` | 1 | Passed kwarg from batch `process()` |

## 5-Question Reboot Check

| Question | Answer |
|----------|--------|
| Where am I? | Phase 5 complete |
| Where am I going? | New task; this naming/speed task is delivered |
| What's the goal? | Accurate readable names; faster analysis without output drift |
| What have I learned? | See `findings.md` |
| What have I done? | See session log and test results above |
