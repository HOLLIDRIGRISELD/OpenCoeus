# Findings & Decisions — naming and speed

## Requirements (from confirmed intent)

- Accurate, short, readable filenames from document content.
- No generic category labels as names; no long word-chains; no `/`, `_`, `=`, or symbol soup.
- Preserve meaningful original filename when content gives nothing better.
- Organisation/folders remain content-based.
- Speed work must not change pinned naming/organisation output.
- 10 GB corpus currently ~30 min to analyse — must improve substantially.

## Naming

### Regression evidence (golden)
Before fixes, generated names replaced meaningful originals:

| File | Generated | Correct |
|------|-----------|---------|
| agreement.docx | Contract.docx | agreement.docx |
| balances.xlsx | Statement.xlsx | balances.xlsx |
| chart.png | Unclassified.png | chart.png |
| expenses.csv | Report.csv | expenses.csv |
| service.py | Manual.py | service.py |

### Root causes fixed
- `NamingEngine.suggest()` used the cleaned original filename when the extracted title is unsupported.
- Opaque stems (`123825ofsaolkd`) still fall back to document type; meaningful stems survive.
- `_extract_subtype()` now requires a `subtype:`/`type:` label or standalone hint line.
- `FILENAME_SEPARATOR` changed from `_` to a space; stems reject `/`, `_`, `=` and backslashes.
- Entity “longest candidate” change was reverted: it created `HLFHelicopterManual.pdf`, `MetaPlatformsInvoice.PDF`.
- Golden fixture re-pinned after confirming intended names.

## Speed

### Hotspots found
1. `scanning_service.py` and `analysis_service.py` each hash full files.
2. Duplicates were extracted before duplicate reuse was checked.
3. Only extraction is parallel; embed/classify/profile are serial.
4. Global DB `RLock` held through cache serialization, embedding save and FTS.
5. Semantic search loops over vectors with per-chunk `np.dot`.
6. UI builds/refreshes all pages at startup, then refreshes dashboard again.

### Fixed this round
- `analyse_pending()` tracks hashes already seen in the batch and skips prefetch extraction for repeated hashes.
- `_analyse_file()` still rehashes actual bytes; a stale recorded hash cannot cause wrong reuse.
- Live `find_analysed_duplicate()` runs only for skipped candidates; existing grouped lookup is unchanged.
- Golden output unchanged by the speed change.

### Unsafe optimisations — deliberately avoided
- Trusting stored hash without rehash: breaks stale-content safety.
- Trusting mtime+size only: same-size/same-mtime edits must reanalyse.
- Skipping FTS writes, removing the DB lock blindly, or raising worker counts blindly.

### Measurement (200 files, 20 unique contents × 10 copies)
| Corpus | Baseline extractions | Current extractions | Baseline time | Current time |
|--------|---------------------|---------------------|---------------|--------------|
| Small text | 200 | 20 | 4.349 s | 3.991 s |
| 10× text | 200 | 20 | 5.853 s | 4.452 s |

Per-file extraction dropped 90%; wall time improved ~8–24% on this synthetic corpus because DB clone/suggestion work now dominates. Real 10 GB corpora with expensive extraction should gain more; no exact 10 GB promise made.

## Verification

- Full pytest: green (~475 tests, one `fitz` FutureWarning).
- Ruff: clean. Compileall: clean.
- Golden test remains pinned and green.

## Resources

- Intent: `docs/intent/opencoeus-naming-and-speed.md`
- Plan: `task_plan.md`
- Golden fixture: `tests/fixtures/quality_golden.json`
- Golden test: `tests/test_quality_gate.py`
- Naming core: `app/intelligence/content_naming.py`, `app/intelligence/naming_engine.py`
- Analysis hot path: `app/services/analysis_service.py`
- Baseline copy (no git): `C:\Users\seldi\AppData\Local\Temp\opencode\opencoeus-audit20-baseline`
