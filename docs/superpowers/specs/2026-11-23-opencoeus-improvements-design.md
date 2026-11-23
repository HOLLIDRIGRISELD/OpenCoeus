# Design: collision, LLM and cache improvements

Date: 2026-11-23  
Status: proposed — awaiting approval

## Intent

Improve the last real run without destabilising naming. Measured run: 5,286 files scanned, 4,535 analysed, 500-item plan, 396 completed moves, 104 skipped, 0 failed. All 104 skips were `duplicate_target` collisions. LLM emitted 48 warnings in 17 minutes (31 false “instruction-like text” refusals, 17 truncated JSON). DB reached 1.09 GB, mostly session FTS (~541 MB) plus embedding cache blobs (~105 MB / 35,765 rows).

User approved work items 1 → 2 → 3 and asked to re-plan the 104 skipped files. Earlier intent doc put LLM/model changes out of scope; this request overrides that for this work only.

## Goals

- Turn in-plan name collisions into deterministic distinct names: target 0 `duplicate_target` skips.
- Cut false LLM refusals and malformed JSON without weakening the “LLM output is only a suggestion” rule.
- Bound embedding-cache growth within a run.
- Re-plan the 104 skipped files after the fixes pass verification.

## Non-goals

- No folder-taxonomy changes.
- No new dependencies.
- No staged-batch UI switch or plan-level undo.
- No auto-execution of the new plan; user approval still required.
- No FTS schema or search-ranking changes.

## Anti-goals

- Re-pinning the golden snapshot to hide a naming regression.
- Overwriting an existing file to “solve” a collision.
- Silently accepting malformed or prompt-injected LLM output.

## Constraints

- `tests/fixtures/quality_golden.json` stays the regression gate until a deliberate re-pin.
- No overwrite: `PathGuard.destination_exists` must remain an error.
- Existing undo data for the 396 completed moves stays untouched.
- Each item lands separately with pytest + golden check between items.

## Approaches considered

1. **Collision-first** (chosen): disambiguate in `OrganisationPlanner.plan()` using the existing `deduplicate_filename()` helper. Smallest diff, no LLM/DB risk.
2. **LLM-waste-first** (chosen second): narrow the injection regex, shrink output arrays, add one retry on JSON parse failure. Small wall-time win, mainly a noise/waste fix.
3. **Cache-bound** (chosen third): cap persistent embedding cache rows. Bounds mid-run growth; does not shrink FTS.
4. **Broad parallelism rewrite** (deferred): more workers/queue tuning. No evidence it beats 1–3 and it risks output drift.

## Decisions

### 1. Collision suffix

- Reuse `app.intelligence.naming_engine.deduplicate_filename()`; suffix style is space+number, e.g. `EdinburghNapierUniversityContract 2.pdf`. This matches the existing convention and keeps names readable.
- Apply per destination folder, case-insensitively, only when another action in the same plan already claims the destination.
- Keep `PathGuard` checks unchanged: an existing file on disk is still a hard conflict.
- Add a note to the planned action explaining the suffix.
- Update `tests/test_organisation.py::test_planner_assigns_actions_and_detects_duplicate_targets` to assert two clean actions with `Alpha 2.txt`, not one blocked action.
- Check `tests/test_end_to_end.py` conflict expectations; adjust only if the demo’s remaining conflicts are all duplicate-target cases.

### 2. LLM waste

- Narrow `_INJECTION_PATTERN` to explicit override/exfiltration forms (`ignore/disregard/forget ... instructions`, `you are now`, `system prompt`, `respond with only`, etc.). Drop broad `please/kindly ... include/return/...` and `you should` matches that fire on ordinary documents.
- Keep the `<document>` data wrapper and prompt rule 1; never treat document text as trusted.
- Simplify prompt output: tags ≤ 4, evidence ≤ 3, uncertainties ≤ 2. Cap parsed lists to those limits in `LocalLLMResult`.
- Set `num_predict` to 400 after the smaller schema. On JSON parse failure, retry once with `num_predict=800`; after that, return `None` and log once.
- Add tests: ordinary “Please include the total” is not refused; explicit “Ignore previous instructions” is refused; malformed JSON triggers exactly one retry.

### 3. Embedding cache bound

- Add `prune(max_entries=10000)` to `EmbeddingCacheRepository` and the `EmbeddingCache` protocol. Delete oldest `created_at` rows in both blob and legacy tables when over the cap.
- Delegate via `EmbeddingEngine.prune_cache()` and call once at the end of `analyse_pending()`.
- Cap chosen because 10,000 × 3,072 × 8 bytes ≈ 234 MB raw; practical typical size ~30–40 MB after compression/page layout. Tune only with a before/after measurement.
- Leave FTS untouched. It is purged on a clean startup; shrinking it would reduce search coverage. Expected DB after a full run with the cap: ~600–700 MB, not a few hundred MB.

## Order and verification

1. Collision fix → focused planner tests → full pytest → `ruff check app tests main.py` → `compileall -q app tests main.py` → golden diff.
2. LLM fix → focused LLM tests → same full gate.
3. Cache cap → focused repository/engine test → same full gate → measure cache row count on a synthetic batch.
4. Commit each slice separately (Conventional Commits).
5. After all three are green, build a fresh preview/plan for the 104 skipped files, show summary, and stop before execution.

## Left to builder

- Exact diff hunks and test names.
- Choose the retry prompt shape; prefer reusing the same prompt with a larger token budget.
- If `test_end_to_end.py` still expects conflicts after item 1, inspect the demo library before changing the assertion.
- Record before/after cache row counts in the item-3 commit message.
