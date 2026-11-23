# Intent: Accurate content-based renaming first, then speed

Confirmed 2026-11-23 via `interview-me`. This is the source of truth for the next work sessions.

## Statement of intent

- **Outcome:** Content-based renaming and organisation that is accurate and readable — short names, no generic category labels, no long word-chains, no `/`, `_`, `=`, or symbol soup. Meaningful originals survive when content adds nothing better.
- **User:** The project owner, running OpenCoeus on a real document library.
- **Why now:** The golden test exposed `agreement.docx` → `Contract.docx` and `expenses.csv` → `Report.csv`. That breaks the app's purpose. Analysis of a 10 GB corpus takes ~30 minutes, which is unusable at realistic/server scale.
- **Success:** Names are content-derived and clean; golden pins names/folders so regressions fail the suite; 10 GB analysis time drops substantially with pinned output unchanged.
- **Constraint:** Speed work must never make naming or organising worse. Output stability is the guardrail.
- **Out of scope:** staged-batch UI switch, plan-level undo, new dependencies, LLM/model changes, folder-taxonomy changes.

## Order of work

1. Fix and pin naming quality.
2. Only then reduce analysis time, with golden output as the regression gate.

## User's own words (verbatim, for intent fidelity)

> THE PROPOSED GENERIC RENAMES THAT ARE NOT EVEN ACURATE AND ARE BADLE WRITTEN WITH A LOT OF WORDS - / _ = AND SYMBOLS IN ORDER FOR IT TO BE FUNCTIANLY GOOD FOR ITS PORPOSE WITCH IS CONTECTS BASED ORGANIZATION AND REANMING ANBD TEHN TACKEL SPEED BUT WITOUT MAKING TYHE ABOVE MENTIONED WORSEW

> YES EXACLTRY BUYT5 STILL IF FOR A 10GB FILEBASE IT TAKES 30 MINS TO JUST ANALIZE IMAGINE WHAT IT WOULD DO TO A REAL SERVER
