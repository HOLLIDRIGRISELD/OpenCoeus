# Audit fixes — 2026-11-24

Scope: the 20 numbered findings in the repo audit. The 12 smaller findings left out stay out.

## Groups (disjoint file ownership)

- [x] A — Data layer: findings 1, 6, 8, 11, 12.
  Files: `app/infrastructure/**`, `app/services/settings_service.py`, `app/search/**`, related tests.
- [x] B — Organisation: findings 3, 4, 5, 9, 10, 19.
  Files: `app/organisation/**`, `app/services/organisation_service.py`, `app/services/context.py`, `app/services/recovery_service.py`, `app/cli.py`, related tests.
- [x] C — Analysis and LLM: findings 2, 7, 13, 14, 20.
  Files: `app/services/analysis_service.py`, `app/intelligence/llm.py`, `app/intelligence/prompts/document_analysis.txt`, related tests.
- [x] D — UI and processing: findings 15, 16, 17, 18.
  Files: `app/ui/**`, `app/processing/extractors/text.py`, `app/processing/chunking.py`, related tests.

## Rules

- TDD per finding: write one focused failing test, watch it fail, apply the smallest fix, watch it pass.
- Use `.\.venv\Scripts\python.exe -m pytest <target>` and `.\.venv\Scripts\python.exe -m ruff check <changed files>`.
- Do not commit. Coordinator runs the full suite after all groups land.
- No new dependencies. No unrelated cleanup.
