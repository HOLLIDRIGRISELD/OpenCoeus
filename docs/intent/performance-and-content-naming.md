# Intent: performance and content-aware naming

Status: confirmed by user on 2026-11-22

## Outcome

Make OpenCoeus faster across startup, scan, analyse, and UI, and change naming so suggested files and folders read like a human organised them.

## User

The person organising a large local document library (~11.4GB, ~5286 files) directly in the desktop app.

## Why now

Current names are generic or mechanical, for example `0001text.json.json → 001text.json`, and do not reveal what a file contains. The app is also slower than it needs to be at startup, analysis, and page refresh.

## Success

- Startup reaches an interactive window quickly; local-model runtime startup no longer blocks before the event loop.
- Scan and analyse are measurably faster while extracted text, chunking, embeddings, classifier output, LLM gating, FTS content, duplicate reuse, cache keys, and move/undo safety stay unchanged.
- Page navigation and library-change refreshes do not rebuild many unrelated pages or run unbounded duplicate queries.
- A single manual gets a content-based name: `gferlhlf.pdf → HLFManual.pdf`.
- A single invoice gets a content-based name: `123825ofsaolkd.incoive → MetaInvoice.PDF`.
- Several files from the same company and type go into folders such as `Meta → Invoices →`. Inside a grouped folder, the strongest content-derived type/subtype wins as the filename; the document date is only the fallback when no better descriptor exists.
- Names stay short and readable. Dates, amounts, hashes, long numbers, and doubled extensions are not used as clutter in single-file names.

## Constraint

- No new dependencies and no cloud processing.
- No unsafe file moves, silent overwrites, or data loss.
- No changes to extractor text, chunking or the 96-chunk cap, embeddings or precision, classifier weights/formula/evidence, LLM gates/caps, FTS content, duplicate reuse source selection, or model-name cache keys.
- The golden fixture may change only for the intentional naming/folder behavior. All other golden fields stay byte-identical.
- Every behavior change goes RED → GREEN with the full suite, ruff, compileall, and quality gate before completion.

## Out of scope

- No UI visual redesign or new visual identity.
- No LLM quality changes, model swaps, or remote services.
- No dependency additions.
- No new destructive database operations without confirmation.
