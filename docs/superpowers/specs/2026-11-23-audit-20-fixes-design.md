# Audit 20 Fixes Design

**Intent:** Fix every finding in the 2026-11-23 read-only audit without adding layers or dependencies. Keep the local-first, human-approved design.

**Approaches:** (1) One big rewrite — rejected: too risky. (2) Four parallel slices with disjoint file ownership — chosen: findings group naturally into persistence/safety, organisation, analysis, and naming/UX. (3) Sequential single-agent — rejected: slower, no benefit.

**Goals:** All 20 findings fixed with TDD regressions; full pytest, ruff, compileall and quality gate green.

**Non-goals:** New dependencies, new abstractions, GUI redesign, regenerating golden files wholesale.

**Constraints:** Python 3.11+, PySide6/SQLAlchemy/numpy only; no `OPENCOEUS_WRITE_GOLDEN`; do not edit user data or DB/config files; work from baseline copy `C:\Users\seldi\AppData\Local\Temp\opencode\opencoeus-audit20-baseline`.

**Decisions:** GUI stops purging session data by default (`AppContext.create(purge=False)`); stale-batch guard stays. Backup/restore validates required columns. Organisation fixes use stored plan roots and fix rollback/failure state. Analysis fixes restore batch reads and reuse scan hash; IDF cache gets a corpus fingerprint that stays stable for the first corpus so existing golden vectors remain valid. `needs_review` is persisted; golden compare drops suggestions and gains semantic checks. Naming fixes prefer labelled entities and full dates; LLM naming fields are applied. Cancel is non-blocking and reaches the search worker.
