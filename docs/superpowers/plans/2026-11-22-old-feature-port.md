# OpenCoeusOLD Feature Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port seven selected behaviours from OpenCoeusOLD into current OpenCoeus without weakening the locked analysis quality or speed work.

**Architecture:** New old-project ideas land as fresh `app/` modules and new SQLAlchemy tables on the existing `Base`; no upstream code is imported, no existing column is altered. Features are added one at a time in dependency order (7, 3, 1, 4, 5, 6, 8), each with its own failing test and full verification before the next.

**Tech Stack:** Python 3.11+, PySide6, SQLAlchemy 2.0, pytest, ruff, standard-library `csv`/`fnmatch`/`threading`.

**Spec:** `docs/superpowers/specs/2026-11-22-old-feature-port-design.md`

## Global Constraints

- Quality lock: no changes to extractor text, chunking/96-chunk cap, embeddings/precision, classifier weights/formula/evidence, LLM gating/caps, FTS content, duplicate reuse, or model-name cache keys.
- No new dependencies; all processing stays local.
- New DB tables only; `Base.metadata.create_all()` creates them; never alter an existing column.
- New tables are either persistent (omit from `purge_session_data()`) or session data (add to the explicit delete list).
- No prose comments in code; docstrings only where the project already uses them.
- No git repo. Instead of commits, each task ends with a checkpoint copy of changed files to `C:\Users\seldi\AppData\Local\Temp\opencode\checkpoints\task-N\`.
- Before Task 1, copy `app/`, `tests/`, `main.py`, `pyproject.toml`, `docs/` to `C:\Users\seldi\AppData\Local\Temp\opencode\pre-port-snapshot\`.
- Verify after every task:
  - `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest`
  - `.venv\Scripts\python.exe -m ruff check app tests main.py`
  - `.venv\Scripts\python.exe -m compileall -q app tests main.py`
- `OPENCOEUS_WRITE_GOLDEN=1` must never be set during verification.
- GUI restarts are pre-approved.

## Review Focus

- Golden analysis drift: new scan skips, profiles, rules or conventions must not change `tests/fixtures/quality_golden.json` — pinned by `tests/test_quality_gate.py` in every task's full-suite run.
- Data loss in staged batches: a mid-batch failure must restore every already-held file — pinned by `test_batch_failure_restores_all_files` in Task 6.
- Name collisions from user rules: rule-generated names must still be blocked by `PathGuard` — pinned by `test_rule_name_collision_is_blocked` in Task 4.
- Cache-key drift from new settings or profiles — pinned by `test_profile_and_rule_settings_do_not_change_cache_prefix` in Task 3.
- Destructive CLI defaults: export/read-only paths must not trigger `purge_session_data()` — pinned by `test_manifest_does_not_mutate_db` in Task 7 and the existing `purge=False` CLI test.

---

## File Structure

- `app/core/config.py` — data-dir precedence, protected-directory defaults.
- `app/processing/scanner.py` — junk names, custom patterns, include allowlist.
- `app/infrastructure/models.py` — all new mapped tables.
- `app/infrastructure/repositories/profiles.py`, `organisation_rules.py`, `batches.py` — one repository per new table, following `RuleRepository`.
- `app/services/profile_service.py` — active-profile state.
- `app/organisation/rules.py` — pure rule evaluator.
- `app/intelligence/conventions.py` — pure naming-convention detector.
- `app/ui/pages/rules.py` — rule editor page; Files page gets a read-only profile summary.
- `tests/test_config_paths.py`, `tests/test_scan_filtering.py`, `tests/test_profiles.py`, `tests/test_rules.py`, `tests/test_rules_ui.py`, `tests/test_conventions.py`, `tests/test_batch.py`, `tests/test_manifest.py`.

---

### Task 1: Data-dir override and read-only fallback

**Files:**
- Modify: `app/core/config.py:24-33,57-58,93-96,119-173`
- Modify: `app/cli.py:528-548`
- Test: `tests/test_config_paths.py` (new)

**Interfaces:**
- Consumes: `AppConfig.load(data_dir)` at `app/core/config.py:125-173`, `default_data_dir()` at `:24-33`, `ConfigurationError` from `app/core/exceptions.py`.
- Produces: `AppConfig.load(data_dir: str | Path | None = None) -> AppConfig`; precedence explicit argument → `OPENCOEUS_DATA_DIR` → `config.json` `data_dir` → `default_data_dir()`; `db_url` recomputed after merge when not explicitly supplied; unwritable chosen dir falls back to `default_data_dir()` with one warning; doubly-unwritable raises `ConfigurationError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_env_data_dir_overrides_default(monkeypatch, tmp_path):
    target = tmp_path / "env"
    monkeypatch.setenv("OPENCOEUS_DATA_DIR", str(target))
    assert AppConfig.load().data_dir == target

def test_explicit_data_dir_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCOEUS_DATA_DIR", str(tmp_path / "env"))
    explicit = tmp_path / "explicit"
    assert AppConfig.load(explicit).data_dir == explicit

def test_json_data_dir_recomputes_db_url(tmp_path):
    (tmp_path / "config.json").write_text('{"data_dir": "%s"}' % (tmp_path / "from_json"))
    config = AppConfig.load(tmp_path)
    assert config.data_dir == tmp_path / "from_json"
    assert config.db_path == (tmp_path / "from_json" / "opencoeus.db")

def test_env_beats_json_data_dir(tmp_path, monkeypatch):
    env = tmp_path / "env"
    (tmp_path / "config.json").write_text('{"data_dir": "%s"}' % (tmp_path / "from_json"))
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: tmp_path)
    monkeypatch.setenv("OPENCOEUS_DATA_DIR", str(env))
    assert AppConfig.load().data_dir == env

def test_unwritable_dir_falls_back(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.delenv("OPENCOEUS_DATA_DIR", raising=False)
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: tmp_path / "fallback")
    assert AppConfig.load(blocker / "child").data_dir == tmp_path / "fallback"

def test_all_unwritable_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: blocker / "child")
    with pytest.raises(ConfigurationError):
        AppConfig.load(blocker / "child")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config_paths.py -v`
Expected: FAIL — env var ignored, `db_url` stale, no fallback, no `ConfigurationError`.

- [ ] **Step 3: Implement resolution and fallback in `app/core/config.py`**

Add a private `_resolve_data_dir(explicit: Path | None) -> Path`, use it in `load()`, drop a caller-supplied `data_dir` key from the JSON merge when env or argument supplied it, recompute `db_url` after merge if the JSON did not explicitly set `db_url`, and wrap both the `config.json` read and `ensure_directories()` `OSError` with a writability probe that falls back once. Catch `ConfigurationError` in `app/cli.py:main()` and print the message before returning `2`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config_paths.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Verify the project**

Run the three global verification commands. Expected: full suite green, ruff clean, compileall exit `0`, golden gate unchanged.

- [ ] **Step 6: Checkpoint**

Copy modified files to `...\checkpoints\task-1\`.

---

### Task 2: Richer protected-folder and OS junk skip rules

**Files:**
- Modify: `app/core/config.py:71-79`
- Modify: `app/processing/scanner.py:23-37,40-68,87-99,121-190`
- Test: `tests/test_scan_filtering.py`

**Interfaces:**
- Consumes: `ScanOptions` at `app/processing/scanner.py:40-68`, `_EXCLUDED_FILE_NAMES` / `_EXCLUDED_NAME_SUFFIXES` at `:31-37`, pre-`describe_file()` skip block at `:173-175`, `write_text` from `tests/conftest.py:42-47`.
- Produces: `ScanOptions.custom_patterns: tuple[str, ...] = ()`, `ScanOptions.included_folders: tuple[str, ...] = ()`; `FileScanner` skips `thumbs.db`, `desktop.ini`, `.DS_Store`, `._*`; directory/file basenames matching an `fnmatch` pattern in `custom_patterns` are skipped; when `included_folders` is non-empty, only directories whose basename is in it are descended (root always scanned). `AppConfig.excluded_directories` gains exactly `.svn`, `.hg`, `.idea`, `.vscode`, `.tox`, `.mypy_cache`, `.pytest_cache`, `venv`, `env`, `site-packages` on top of the current seven names — no ordinary document folder name is added.

- [ ] **Step 1: Write the failing tests**

```python
from app.processing.scanner import FileScanner, ScanOptions
from tests.conftest import write_text


def test_os_junk_names_never_reach_describe_file(context, tmp_path, monkeypatch):
    root = tmp_path / "lib"
    for name in ("thumbs.db", "desktop.ini", ".DS_Store"):
        write_text(root / name, "junk")
    spy = []
    monkeypatch.setattr("app.processing.scanner.describe_file", lambda *a: spy.append(a))
    context.scanning.scan(root, include_unsupported=False)
    assert spy == []


def test_appledouble_prefix_is_skipped(context, tmp_path):
    root = tmp_path / "lib"
    path = write_text(root / "._report.pdf", "resource fork")
    context.scanning.scan(root, include_unsupported=False)
    assert context.files.find_by_path(path) is None


def test_custom_pattern_excludes_file_and_directory(tmp_path):
    root = tmp_path / "lib"
    write_text(root / "secret.tmp", "x")
    write_text(root / "private" / "keep.txt", "x")
    found = FileScanner(ScanOptions(custom_patterns=("*.tmp", "private"))).scan(root)
    assert all("secret.tmp" not in str(f.path) and "private" not in str(f.path) for f in found)


def test_included_folders_allowlist(tmp_path):
    root = tmp_path / "lib"
    write_text(root / "notes.txt", "x")
    write_text(root / "keep" / "keep.txt", "x")
    write_text(root / "drop" / "drop.txt", "x")
    found = FileScanner(ScanOptions(included_folders=("keep",))).scan(root)
    assert any("keep.txt" in str(f.path) for f in found)
    assert not any("drop.txt" in str(f.path) for f in found)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scan_filtering.py -v`
Expected: FAIL on new assertions; existing `test_supported_pdf_named_dat_is_detected` still passes.

- [ ] **Step 3: Implement the skip rules**

Add the protected names to `AppConfig.excluded_directories`, add `_EXCLUDED_FILE_PREFIXES = ("._",)` and the junk names, extend `ScanOptions`, apply `fnmatch` patterns case-insensitively on Windows in the existing skip block, and apply `included_folders` in the directory-descend decision at `app/processing/scanner.py:164-166`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_scan_filtering.py -v`
Expected: PASS including the existing `.dat` PDF test.

- [ ] **Step 5: Verify the project**

Run the three global verification commands. Expected: full suite green, ruff clean, compileall exit `0`, golden gate unchanged.

- [ ] **Step 6: Checkpoint**

Copy modified files to `...\checkpoints\task-2\`.

---

### Task 3: Named scan profiles

**Files:**
- Modify: `app/infrastructure/models.py` (add `ScanProfile` near `Rule` at `:480-497`)
- Create: `app/infrastructure/repositories/profiles.py`, `app/services/profile_service.py`
- Modify: `app/services/context.py:77-96`, `app/services/scanning_service.py:42-83`, `app/cli.py:420-426,443-449`, `app/ui/pages/files.py`
- Test: `tests/test_profiles.py` (new)

**Interfaces:**
- Consumes: `RuleRepository` pattern at `app/infrastructure/repositories/settings.py:80-138`; `ScanOptions` fields from Task 2; `ScanningService.scan()` at `app/services/scanning_service.py:61-71` (signature unchanged).
- Produces: `ProfileService.list() -> list[ScanProfileView]`, `add(name: str, root: str, included: Sequence[str], excluded: Sequence[str], patterns: Sequence[str]) -> int`, `delete(profile_id: int) -> None`, `set_active(profile_id: int | None) -> None`, `active() -> ScanProfileView | None`; `ScanProfileView` has `id`, `name`, `root_path`, `included_folders`, `excluded_folders`, `custom_patterns`. `ScanningService.__init__` gains keyword `profiles: ProfileService | None = None`; `scan()` merges active-profile fields into `ScanOptions`. CLI adds `profile list|add|apply|delete` and makes `scan` positional `path` optional (`nargs="?"`) so an active profile supplies the root.

- [ ] **Step 1: Write the failing tests**

```python
from tests.conftest import write_text


def test_profile_crud_and_active(context):
    profile_id = context.profiles.add("Docs", "/docs", ("Invoices",), ("Temp",), ("*.tmp",))
    assert [p.name for p in context.profiles.list()] == ["Docs"]
    context.profiles.set_active(profile_id)
    assert context.profiles.active().name == "Docs"
    context.profiles.delete(profile_id)
    assert context.profiles.active() is None


def test_active_profile_survives_purge(context):
    profile_id = context.profiles.add("Docs", "/docs", (), (), ())
    context.profiles.set_active(profile_id)
    context.db.purge_session_data()
    assert context.profiles.active().name == "Docs"


def test_profile_filters_are_applied_to_scan(context, tmp_path):
    root = tmp_path / "lib"
    write_text(root / "skip.tmp", "x")
    write_text(root / "keep" / "keep.txt", "x")
    context.profiles.add("P", str(root), ("keep",), (), ("*.tmp",))
    context.profiles.set_active(1)
    context.scanning.scan(root)
    names = [f.name for f in context.files.list_summaries()]
    assert "skip.tmp" not in names and "keep.txt" in names


def test_profile_settings_do_not_change_cache_prefix(context):
    before = context.analysis._cache_signature(use_llm=False)
    context.profiles.add("P", "/docs", (), (), ())
    context.profiles.set_active(1)
    assert context.analysis._cache_signature(use_llm=False) == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_profiles.py -v`
Expected: FAIL — `context.profiles` missing, CLI commands absent.

- [ ] **Step 3: Implement table, repository, service and wiring**

Add `ScanProfile` with JSON columns and a unique `name`; persist across purge by leaving it out of `purge_session_data()`. Wire `ctx.profiles`. In `ScanningService.scan()`, read `self._profiles.active()` when present, set `included_folders`, extend `excluded_directory_names`, and set `custom_patterns`. Add CLI handlers using `AppContext(..., purge=False)` already used by `main()`. Show active profile name and effective filters as read-only labels in the Files page.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_profiles.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Verify the project**

Run the three global verification commands plus `tests/test_quality_gate.py`. Expected: full suite green, ruff clean, compileall exit `0`, golden unchanged.

- [ ] **Step 6: Checkpoint**

Copy modified files to `...\checkpoints\task-3\`.

---

### Task 4: User-defined organisation rules and rule editor

**Files:**
- Modify: `app/infrastructure/models.py` (add `OrganisationRule` after `Rule` at `:497`)
- Create: `app/infrastructure/repositories/organisation_rules.py`, `app/organisation/rules.py`, `app/ui/pages/rules.py`
- Modify: `app/organisation/planner.py:82-99,99-186`, `app/services/organisation_service.py:147-149`, `app/services/context.py:77-96`, `app/ui/pages/__init__.py:3-20`, `app/ui/main_window.py:40-49,141-150`
- Test: `tests/test_rules.py`, `tests/test_rules_ui.py` (new)

**Interfaces:**
- Consumes: `PlanEntry` at `app/organisation/planner.py:21-43`, `OrganisationPlanner.plan()` at `:99`, `PathGuard` checks at `:134-153`, `OrganisationPreviews` build at `app/services/organisation_service.py:89-155`.
- Produces: `OrganisationRule` fields `id`, `name`, `priority`, `enabled`, `match_field`, `match_op`, `match_value`, `action`, `folder_template`, `name_template`; `RuleDecision` dataclass with `relative_folder: str`, `new_name: str`, `action: str` (one of `MOVE`, `RENAME`, `RENAME_AND_MOVE`); `RuleEvaluator.evaluate(record: dict[str, object], rules: Sequence[OrganisationRule]) -> RuleDecision | None`; `OrganisationPlanner.__init__(..., rule_resolver: Callable[[int], RuleDecision | None] | None = None)`; `context.organisation_rules` with `add(name, match_field, match_op, match_value, folder_template, *, action="MOVE", name_template="", priority=100, enabled=True)`, `enabled()`, `list()`, `set_enabled(rule_id, enabled)`, `delete(rule_id)`, `seed_disabled_examples()`; `RulesPage` following `BasePage` with `add_rule(...)`, `row_count()`, `set_enabled(row, enabled)`, `rule_at(row)`, `delete_rule(row)`.

- [ ] **Step 1: Write the failing tests**

```python
from app.organisation.rules import RuleEvaluator
from app.infrastructure.models import OrganisationRule


def test_rule_evaluator_priority_and_fields():
    rules = [
        OrganisationRule(name="pdf", priority=10, match_field="extension",
                         match_op="equals", match_value=".pdf", action="MOVE",
                         folder_template="PDFs", name_template=""),
        OrganisationRule(name="all", priority=100, match_field="always",
                         match_op="equals", match_value="", action="MOVE",
                         folder_template="Misc", name_template=""),
    ]
    decision = RuleEvaluator().evaluate({"extension": ".pdf", "size": 10}, rules)
    assert decision.relative_folder == "PDFs"


def test_no_enabled_rules_leaves_preview_unchanged(context, analysed_library):
    before = context.organisation.build_preview()
    after = context.organisation.build_preview()
    assert before.draft.actions == after.draft.actions


def test_rule_name_collision_is_blocked(context, analysed_library):
    context.organisation_rules.add("all", "always", "equals", "", "OneName", enabled=True)
    draft = context.organisation.build_preview().draft
    assert len(draft.actions) > 1
    assert any(a.conflict for a in draft.actions)


def test_rules_page_add_toggle_delete(qtbot, context):
    page = RulesPage(context)
    page.add_rule("pdf", "extension", "equals", ".pdf", "PDFs")
    assert page.row_count() == 1
    page.set_enabled(0, False)
    assert page.rule_at(0).enabled is False
    page.delete_rule(0)
    assert page.row_count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rules.py tests/test_rules_ui.py -v`
Expected: FAIL — modules absent.

- [ ] **Step 3: Implement evaluator, table, repository, planner hook and UI**

Evaluate `extension`, `name`, `size`, `category`, `status`, `folder`, `always`; validate template tokens to `{title}`, `{category}`, `{original}`, `{date}`, `{year}`, `{extension}`. In `OrganisationPlanner.plan()`, call `rule_resolver(entry.file_id)` before validation, override `new_name`/`relative_folder`, append a note, then go through the unchanged `PathGuard` checks. Seed disabled examples only when the table is empty. Register `RulesPage` in the nav.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rules.py tests/test_rules_ui.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the project**

Run the three global verification commands. Expected: full suite green, ruff clean, compileall exit `0`, golden unchanged.

- [ ] **Step 6: Checkpoint**

Copy modified files to `...\checkpoints\task-4\`.

---

### Task 5: Optional naming-convention detection

**Files:**
- Create: `app/intelligence/conventions.py`
- Modify: `app/services/settings_service.py:13-28`, `app/services/analysis_service.py:421-444,499-519`
- Test: `tests/test_conventions.py` (new)

**Interfaces:**
- Consumes: `NamingEngine.suggest()` at `app/intelligence/naming_engine.py:96-170`, `FilenameValidator` at `:41-93`, `save_suggestions()` seam at `app/services/analysis_service.py:436-445`.
- Produces: `Convention` dataclass (`case_style`, `separator`, `prefix`, `date_style`, `numeric_suffix`, `next_sequence`); `detect_convention(names: Sequence[str]) -> Convention | None`; `apply_convention(name: str, convention: Convention) -> str`; setting `naming.use_conventions`, default `False`; `AnalysisService._apply_naming_conventions(suggestion: NamingSuggestion, existing_names: Sequence[str]) -> NamingSuggestion` — returns the suggestion unchanged when the setting is off, otherwise rewrites via `apply_convention`, revalidates via `FilenameValidator`, and appends `"naming convention: ..."` to `evidence`.

- [ ] **Step 1: Write the failing tests**

```python
from app.domain.models import NamingSuggestion
from app.intelligence.conventions import apply_convention, detect_convention


def test_detect_convention_from_existing_names():
    convention = detect_convention(["2026-Report-01", "2026-Report-02", "2026-Report-03"])
    assert convention.separator == "-"
    assert convention.numeric_suffix == 2
    assert convention.next_sequence == 4


def test_default_off_keeps_golden(context, sample_library):
    context.scanning.scan(sample_library)
    context.analysis.analyse_pending(use_llm=False)
    assert context.settings.snapshot()["naming.use_conventions"] is False


def test_opt_on_rewrites_name_and_records_evidence(context):
    suggestion = NamingSuggestion(
        original_name="report.txt", suggested_name="Report-01.txt",
        confidence=0.7, explanation="template", template="{title}",
    )
    assert context.analysis._apply_naming_conventions(suggestion, []) is suggestion
    context.settings.update({"naming.use_conventions": True})
    rewritten = context.analysis._apply_naming_conventions(
        suggestion, ["2026-Report-01", "2026-Report-02"]
    )
    assert "convention" in " ".join(rewritten.evidence).lower()


def test_convention_rewrite_never_collides(context):
    suggestion = NamingSuggestion(
        original_name="report.txt", suggested_name="Report-03.txt",
        confidence=0.7, explanation="template", template="{title}",
    )
    names = ["2026-Report-01", "2026-Report-02", "2026-Report-03", "Report-03.txt"]
    rewritten = context.analysis._apply_naming_conventions(suggestion, names)
    assert rewritten.suggested_name not in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conventions.py -v`
Expected: FAIL — module/setting absent.

- [ ] **Step 3: Implement detector and opt-in post-pass**

Pure string/regex logic only; `re` is in the standard library. Add `_apply_naming_conventions` to `AnalysisService`. Call it in both the normal and duplicate-reuse suggestion paths immediately after `self._naming.suggest(...)` and before `save_suggestions()`. It re-runs `FilenameValidator`, rechecks existing names and planned targets, and appends evidence. Never touch classification, LLM, FTS or cache key.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_conventions.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the project**

Run the three global verification commands. Expected: full suite green, ruff clean, compileall exit `0`, golden unchanged with default off.

- [ ] **Step 6: Checkpoint**

Copy modified files to `...\checkpoints\task-5\`.

---

### Task 6: Staged batch execution with holding area and batch lock

**Files:**
- Modify: `app/infrastructure/models.py` (add `BatchExecution`, `BatchExecutionItem`)
- Create: `app/infrastructure/repositories/batches.py`
- Modify: `app/services/organisation_service.py:191-352`, `app/services/context.py:68-89`, `app/cli.py:469-472`
- Test: `tests/test_batch.py` (new)

**Interfaces:**
- Consumes: `move_no_overwrite`, `verify_destination` at `app/organisation/fsops.py:30-42,86-157`; `PathGuard` at `app/organisation/validator.py:66-235`; `OperationRepository` transitions at `app/infrastructure/repositories/operations.py:157-241`; existing undo at `app/organisation/recovery.py:51-136`.
- Produces: `context.batches` with `create(plan_id: int, holding_dir: Path) -> int`, `set_state(batch_id: int, state: str) -> None`, `record_item(batch_id: int, file_id: int, original_path: Path, holding_path: Path, final_path: Path) -> None`, `set_item_state(batch_id: int, file_id: int, state: str) -> None`, `get(batch_id: int) -> BatchExecution`, `unfinished() -> list[BatchExecution]`; `BatchResult(state: str, completed: list[int], failed: list[int], operation_ids: list[int])`; `OrganisationService.execute_batch(plan_id: int, *, progress=None, cancel=None) -> BatchResult` with states `PENDING`, `HELD`, `COMPLETED`, `FAILED`, `ROLLED_BACK`; module-level `_BATCH_LOCK = threading.Lock()` acquired with `acquire(blocking=False)`; `cleanup_stale_batches()` invoked at `AppContext.__init__` after schema creation; CLI `execute <plan_id> --staged`. `move_no_overwrite` is imported into `app/services/organisation_service.py` so tests can monkeypatch that exact name.

- [ ] **Step 1: Write the failing tests**

```python
import threading
from pathlib import Path

import pytest

from app.core.exceptions import OperationConflictError
from app.domain.enums import PlanStatus
from app.services import organisation_service as org_service
from tests.conftest import file_id_for


def _approved_plan(context, analysed_library) -> int:
    plan_id = context.organisation.create_plan()
    context.organisation.approve(plan_id)
    return plan_id


def test_batch_failure_restores_all_files(context, analysed_library, monkeypatch):
    plan_id = _approved_plan(context, analysed_library)
    originals = [p for p in analysed_library.rglob("*") if p.is_file()]
    real_move = org_service.move_no_overwrite
    calls = []

    def failing_move(source, destination, *args, **kwargs):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("injected second-hop failure")
        return real_move(source, destination, *args, **kwargs)

    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", failing_move)
    result = context.organisation.execute_batch(plan_id)
    assert result.state == "FAILED"
    assert all(path.exists() for path in originals)
    batch = context.batches.unfinished()[0]
    assert not list(batch.holding_dir.iterdir())


def test_concurrent_execute_is_refused(context, analysed_library, monkeypatch):
    plan_id = _approved_plan(context, analysed_library)
    lock = threading.Lock()
    assert lock.acquire(blocking=False)
    monkeypatch.setattr("app.services.organisation_service._BATCH_LOCK", lock)
    with pytest.raises(OperationConflictError, match="already running"):
        context.organisation.execute_batch(plan_id)


def test_revalidate_held_item_uses_holding_path(context, analysed_library, tmp_path):
    plan_id = _approved_plan(context, analysed_library)
    holding = tmp_path / "holding"
    holding.mkdir()
    file_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")
    batch_id = context.batches.create(plan_id, holding)
    held = holding / "held.txt"
    held.write_text("moved")
    context.batches.record_item(batch_id, file_id, Path("original"), held, Path("final"))
    context.batches.set_item_state(batch_id, file_id, "HELD")
    context.operations.update_plan_status(plan_id, PlanStatus.FAILED)
    context.organisation.revalidate(plan_id)
    assert all(item.conflict is None for item in context.operations.plan_items(plan_id))


def test_undo_still_works_after_completed_batch(context, analysed_library):
    plan_id = _approved_plan(context, analysed_library)
    result = context.organisation.execute_batch(plan_id)
    assert result.state == "COMPLETED"
    assert context.recovery.undo(result.operation_ids[0]).success is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_batch.py -v`
Expected: FAIL — method/repository absent.

- [ ] **Step 3: Implement batch tables, repository and flow**

Preflight existence, size and full SHA-256 against the stored fingerprint for every item; fail the whole batch before moving anything if any source is stale. Move source→holding then holding→final using only `move_no_overwrite`/`verify_destination`; on failure restore held files to originals. Record one `Operation` per item with original source and final destination so existing undo works. Store original/holding/final paths in `BatchExecutionItem`; never mutate `PlanItem.source_path`. `revalidate()` resolves `HELD` items via the batch table. Cleanup restores `PENDING`/`HELD` files whose original path is free and logs a warning otherwise; never deletes user files. Add `threading.Lock` plus DB state check.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_batch.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the project**

Run the three global verification commands. Expected: full suite green, ruff clean, compileall exit `0`, golden unchanged; existing `tests/test_organisation.py` still passes.

- [ ] **Step 6: Checkpoint**

Copy modified files to `...\checkpoints\task-6\`.

---

### Task 7: CSV audit manifest export

**Files:**
- Modify: `app/infrastructure/repositories/files.py:108-205` (add `manifest_rows`)
- Modify: `app/cli.py:443-449` and add `cmd_manifest`
- Test: `tests/test_manifest.py` (new)

**Interfaces:**
- Consumes: `FileRepository.list_summaries()` at `app/infrastructure/repositories/files.py:108-171`, `light_records()` at `:173-205`, `OperationRepository.plan_items()` at `app/infrastructure/repositories/operations.py:99-122`, CLI handler pattern at `app/cli.py:528-548`.
- Produces: `ManifestRow` dataclass (`path`, `name`, `size_bytes`, `sha256`, `status`, `category`, `modified_at`, `last_planned_action`, `last_operation_status`); `FileRepository.manifest_rows() -> list[ManifestRow]` (one row per file, newest plan/operation only); `cmd_manifest(args, ctx) -> int` writing exact header `path,name,size_bytes,sha256,status,category,modified_at,last_planned_action,last_operation_status`.

- [ ] **Step 1: Write the failing tests**

```python
def test_manifest_header_and_rows(context, analysed_library, tmp_path):
    output = tmp_path / "manifest.csv"
    assert main(["--data-dir", str(context.config.data_dir), "manifest", "--output", str(output)]) == 0
    lines = output.read_text().splitlines()
    assert lines[0] == "path,name,size_bytes,sha256,status,category,modified_at,last_planned_action,last_operation_status"
    assert len(lines) == 1 + len(context.files.list_summaries())

def test_manifest_does_not_mutate_db(context, analysed_library, tmp_path):
    before = context.files.stats()
    main(["--data-dir", str(context.config.data_dir), "manifest", "--output", str(tmp_path / "m.csv")])
    assert context.files.stats() == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_manifest.py -v`
Expected: FAIL — unrecognised `manifest` command.

- [ ] **Step 3: Implement read-only query and CLI command**

Add one bulk SELECT or a combination of the cited repository methods avoiding N+1 calls; resolve output with `.expanduser()`; use `csv.DictWriter` with `newline=""`; do not call analysis, indexing, recommendation mutators or `purge_session_data()`. Mention in `--help` that the output should be outside the scanned library.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the project**

Run the three global verification commands. Expected: full suite green, ruff clean, compileall exit `0`, golden unchanged.

- [ ] **Step 6: Checkpoint and finish**

Copy modified files to `...\checkpoints\task-7\`. Run the full suite once more, then report the seven one-line feature summaries and anything dropped.

---

## Self-Review

- Spec coverage: item 7 → Task 1, item 3 → Task 2, item 1 → Task 3, item 4 → Task 4, item 5 → Task 5, item 6 → Task 6, item 8 → Task 7. Item 2 (folder tree) intentionally absent per user choice.
- Builder-check decisions 1–10 are carried into Tasks 6, 4, 3 and 7.
- Type consistency: `RuleDecision`, `ScanProfileView`, `ManifestRow`, `ProfileService`, `OrganisationRuleRepository`, `BatchRepository` names are used consistently across producing and consuming tasks.
- Review Focus items are pinned by the named tests in Tasks 2–7.
