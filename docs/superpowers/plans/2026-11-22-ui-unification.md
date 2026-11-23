# UI Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the nine-page PySide6 UI around its existing dark token system and shared widgets, with a thin slice of flow guidance (next-action empty states and busy/disabled guards).

**Architecture:** All visual values stay in `app/ui/theme.py`; pages consume QSS roles and exported tokens instead of inline styles. `app/ui/widgets.py` gains one action-row helper and uses `EmptyState`/`Badge` roles consistently. Page modules keep their existing widget attributes, signals, texts and responsive logic. No service, repository, model, CLI or analysis code changes.

**Tech Stack:** Python 3.11+, PySide6 (Fusion + global QSS), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-22-ui-unification-design.md`

## Global Constraints

- Quality lock unchanged: no extractor, chunking, embedding, classifier, LLM, FTS, planner or execution logic changes.
- No new dependency; no new palette values, typeface or icon set; no focus or press outline of any kind.
- `tests/test_ui_polish.py` pins `outline: none`, forbids other `outline:` declarations and QSS focus selectors, and pins token contrast values and button texts (`Cancel`, “save”).
- `tests/test_ui_smoke.py` pins exactly 9 pages and their keys; `tests/test_ui_responsive.py` pins sidebar 176–260 px, header ≥64 px, stat-card height, `_stat_columns` 2/3/6, `_settings_columns` 1/2, and table widths under an enlarged font.
- `tests/test_rules_ui.py` pins row counts and direct delete calls; `tests/test_profiles.py` pins profile label text.
- TDD for every behaviour change: RED → confirm failure → GREEN → full suite. No prose comments; docstrings only where the file already uses them.
- Verification after every task and before completion:
  `$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest`; `.venv\Scripts\python.exe -m ruff check app tests main.py`; `.venv\Scripts\python.exe -m compileall -q app tests main.py`; `.venv\Scripts\python.exe -m pytest tests/test_quality_gate.py -q`.
- Workspace is not a git repo. Checkpoint changed files to `C:\Users\seldi\AppData\Local\Temp\opencode\ui-checkpoints\task-N\` instead of committing. `OPENCOEUS_WRITE_GOLDEN` must stay unset.

## Review Focus

- **Narrow window with enlarged font** must not introduce horizontal scrolling or clip buttons — pinned by the existing responsive table-width and stat-card assertions, re-run in Task 5.
- **Empty database on first run** must show a next action, not a blank table — `test_empty_states_name_next_action` in Task 5.
- **Background task running** must disable refresh/rebuild/maintenance controls — `test_busy_controls_disabled_while_task_runs` in Task 5.
- **No rule selected** must not silently no-op — `test_rule_delete_disabled_without_selection` in Task 5.
- **Rich text with special characters** must stay escaped and use tokens, not hardcoded colours — `test_rich_text_uses_tokens_and_escapes` in Task 2.

---

### Task 1: Theme roles and shared action row

**Files:**
- Modify: `app/ui/theme.py:79-386`
- Modify: `app/ui/widgets.py:403-428`
- Test: `tests/test_ui_unification.py` (new)

**Interfaces:**
- Consumes: existing `SLATE_800`, `TEXT`, `MUTED`, `FAINT`, `BLUE`, `BLUE`, `STYLESHEET` from `app/ui/theme.py`; `EmptyState`, `separator`, `scrollable_page` from `app/ui/widgets.py`.
- Produces: `add_actions(layout: QVBoxLayout, *widgets: QWidget) -> QHBoxLayout` — inserts a left-stretch row at index 0 of `layout`; `STYLESHEET` contains global `QTextBrowser` rules and `QLabel[role="detail"]`, `QLabel[role="surface"]`, `QLabel[role="code"]`; `separator()` imports `SLATE_800` instead of hardcoding `#1a2742`; `EmptyState` uses role properties instead of inline colours.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout


def test_theme_roles_and_rich_text_rules():
    from app.ui.theme import STYLESHEET
    assert "QTextBrowser {" in STYLESHEET
    assert "QTextBrowser a {" in STYLESHEET
    assert 'QLabel[role="detail"]' in STYLESHEET
    assert 'QLabel[role="surface"]' in STYLESHEET
    assert 'QLabel[role="code"]' in STYLESHEET


def test_shared_widgets_have_no_inline_hex():
    source = Path("app/ui/widgets.py").read_text(encoding="utf-8")
    assert "#1a2742" not in source
    assert "setStyleSheet(f\"color:" not in source


def test_add_actions_inserts_right_aligned_row():
    app = QApplication.instance() or QApplication([])
    layout = QVBoxLayout()
    button = QPushButton("Go")
    row = add_actions(layout, button)
    assert isinstance(row, QHBoxLayout)
    assert layout.itemAt(0) is row
    assert row.itemAt(0).spacerItem() is not None
    assert row.itemAt(1).widget() is button
```

- [ ] **Step 2: Run to confirm RED**

`pytest tests/test_ui_unification.py -q` → 3 failed (`add_actions` import error, missing QSS rules, inline hex present).

- [ ] **Step 3: Implement**

Add the three QSS role blocks and one `QTextBrowser` block to `STYLESHEET` using existing tokens; keep every existing rule including `outline: none`. Replace `EmptyState` inline styles and `separator()`'s literal with role properties and `SLATE_800`. Add `add_actions` to `widgets.py` and export it in `__all__`.

- [ ] **Step 4: Run to confirm GREEN**

`pytest tests/test_ui_unification.py -q` → 3 passed.

- [ ] **Step 5: Verify and checkpoint**

Run all four verification commands from Global Constraints; checkpoint the three changed files.

---

### Task 2: Pages stop styling themselves

**Files:**
- Modify: `app/ui/pages/dashboard.py`, `files.py`, `history.py`, `planner.py`, `recommendations.py`, `search.py`, `settings.py`
- Test: `tests/test_ui_unification.py`

**Interfaces:**
- Consumes: `STYLESHEET` roles and tokens from Task 1; `status_color(status) -> str` and `confidence_color(value) -> str` from `app/ui/theme.py`.
- Produces: page modules with no inline hex colour literals and no per-widget rich-text `setStyleSheet`; HTML colour values come from imported theme constants.

- [ ] **Step 1: Write the failing tests**

```python
PAGE_MODULES = (
    "dashboard", "files", "history", "planner", "recommendations", "search", "settings",
)


def test_pages_have_no_inline_hex_colours():
    for name in PAGE_MODULES:
        source = Path(f"app/ui/pages/{name}.py").read_text(encoding="utf-8")
        assert '"#' not in source and "'#" not in source, name


def test_pages_have_no_local_richtext_stylesheet():
    for name in PAGE_MODULES:
        source = Path(f"app/ui/pages/{name}.py").read_text(encoding="utf-8")
        assert "QTextBrowser { background: transparent" not in source, name


def test_rich_text_uses_tokens_and_escapes():
    from app.ui.pages.dashboard import DashboardPage

    page = DashboardPage.__new__(DashboardPage)
    page.ctx = type("Ctx", (), {"capabilities": staticmethod(lambda probe=False: [])})()
    page.capability_label = _Label()
    page._refresh_capabilities()
    assert page.capability_label.text == ""
```

Where `_Label` is a tiny local stub with `setText`, `setWordWrap` and `setTextFormat` no-ops and a `text` attribute. The assertion pins that no capabilities produce no raw HTML fragment.

- [ ] **Step 2: Run to confirm RED**

`pytest tests/test_ui_unification.py -q` → 3 failed.

- [ ] **Step 3: Implement**

Remove the four `QTextBrowser.setStyleSheet` calls (files/recommendations/planner/search). Replace `style="color:#…"` and inline `setStyleSheet(f"color: …")` with role properties or f-strings built from imported tokens. In `dashboard._refresh_capabilities`, keep `html.escape` and emit token-coloured spans; in `_field_label` use `setProperty("role", "detail")` instead of an inline stylesheet. Leave `status_color`/`confidence_color` semantics and all pinned text untouched.

- [ ] **Step 4: Run to confirm GREEN**

`pytest tests/test_ui_unification.py -q` → 6 passed.

- [ ] **Step 5: Verify and checkpoint**

Run all four verification commands; checkpoint the eight changed files.

---

### Task 3: Shared status, empty-state and action composition

**Files:**
- Modify: `app/ui/pages/dashboard.py`, `files.py`, `history.py`, `planner.py`, `recommendations.py`, `search.py`, `rules.py`
- Test: `tests/test_ui_unification.py`

**Interfaces:**
- Consumes: `add_actions` from Task 1; `Badge`, `EmptyState`, `Card`, `hint_label`, `muted_label`, `section_label`, `separator`, `set_cell` from `app/ui/widgets.py`.
- Produces: `EmptyState` instances on Library, Search, History, Planner and Review empty views; `Badge`/`role="detail"` status pills in detail panels; page-level action rows built with `add_actions`. Table status cells remain `set_cell` text coloured via `status_color`.

- [ ] **Step 1: Write the failing tests**

```python
def test_shared_widgets_are_used_by_pages():
    from app.ui import widgets
    sources = {
        name: Path(f"app/ui/pages/{name}.py").read_text(encoding="utf-8")
        for name in ("dashboard", "files", "history", "planner", "recommendations", "search")
    }
    assert "Badge(" in sources["dashboard"]
    for name in ("files", "history", "planner", "recommendations", "search"):
        assert "EmptyState(" in sources[name], name
    for name in ("dashboard", "files", "history", "recommendations", "settings"):
        assert "add_actions(" in sources.get(name, Path("app/ui/pages/settings.py").read_text()), name
    for name in ("files", "recommendations", "search", "planner"):
        assert "separator()" in sources[name], name


def test_empty_state_widget_exposes_heading_and_detail():
    from app.ui.widgets import EmptyState
    app = QApplication.instance() or QApplication([])
    state = EmptyState("Nothing here", "Open Scan & analyse.")
    assert state.findChildren(QLabel)[0].text() == "Nothing here"
    assert state.findChildren(QLabel)[1].text() == "Open Scan & analyse."
```

- [ ] **Step 2: Run to confirm RED**

`pytest tests/test_ui_unification.py -q` → 2 failed.

- [ ] **Step 3: Implement**

Use `add_actions` for the top action rows on Dashboard, Files, History, Recommendations and Settings; keep every named button and its text. Add `EmptyState` beside existing count labels on the five listed pages, keeping the pinned “starts empty” / “fresh session” copy. Replace the Overview capability dot HTML with `Badge`. Add `separator()` between major sections on the four listed pages. Do not replace table cell widgets or touch table column setup.

- [ ] **Step 4: Run to confirm GREEN**

`pytest tests/test_ui_unification.py -q` → 8 passed.

- [ ] **Step 5: Verify and checkpoint**

Run all four verification commands; checkpoint changed files.

---

### Task 4: Consistent action hierarchy and spacing

**Files:**
- Modify: `app/ui/pages/dashboard.py`, `files.py`, `planner.py`, `settings.py`, `recommendations.py`, `history.py`
- Test: `tests/test_ui_unification.py`

**Interfaces:**
- Consumes: `add_actions` from Task 1; all named buttons from Tasks 2–3.
- Produces: one `primary="true"` action per decisive page; page-local spacing deviations removed in favour of `scrollable_page` defaults; STATUS_COLORS and responsive dimension logic unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_primary_action_per_page():
    from app.services.context import AppContext
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    context = AppContext.create(purge=False)
    try:
        window = MainWindow(context)
        expected = {
            "scanner": "Start scan",
            "files": "Analyse",
            "search": "Search",
            "settings": "Save settings",
            "rules": "Add rule",
        }
        for key, label in expected.items():
            page = window.pages[key]
            primaries = [b for b in page.findChildren(QPushButton) if b.property("primary") is True and b.isVisible()]
            assert any(b.text() == label for b in primaries), key
    finally:
        context.close()


def test_page_spacing_uses_scrollable_defaults():
    settings = Path("app/ui/pages/settings.py").read_text(encoding="utf-8")
    planner = Path("app/ui/pages/planner.py").read_text(encoding="utf-8")
    assert "scrollable_page(self, spacing=14)" not in settings
    assert "margin=(24, 20, 24, 24)" not in planner
```

- [ ] **Step 2: Run to confirm RED**

`pytest tests/test_ui_unification.py -q` → 2 failed.

- [ ] **Step 3: Implement**

Set `primary` on the single decisive control per page and clear it from others: Scanner Start scan (Analyse gains it after files are registered), Files Analyse, Search Search, Settings Save settings, Rules Add rule, Planner Save as draft on Preview and Execute approved plan on Saved plans, History Create backup and Undo selected stay `danger`/neutral as today. Remove the Settings `spacing=14` and Planner explicit `margin` arguments; leave tab/grid spacing where a test pins geometry. Never add `outline` or focus QSS.

- [ ] **Step 4: Run to confirm GREEN**

`pytest tests/test_ui_unification.py -q` → 10 passed, plus existing UI suites green.

- [ ] **Step 5: Verify and checkpoint**

Run all four verification commands; checkpoint changed files.

---

### Task 5: Flow guidance and busy guards

**Files:**
- Modify: `app/ui/pages/rules.py`, `history.py`, `planner.py`, `files.py`, `search.py`, `dashboard.py`
- Test: `tests/test_ui_unification.py`

**Interfaces:**
- Consumes: `EmptyState` from Task 3; `BasePage.has_running_tasks() -> bool` from `app/ui/base.py`.
- Produces: next-action empty-state copy; `RulesPage.delete_button` disabled with tooltip when no row is selected; local `_busy` flags guarding synchronous maintenance/rebuild/refresh actions.

- [ ] **Step 1: Write the failing tests**

```python
def test_empty_states_name_next_action():
    from app.ui.widgets import EmptyState
    states = [
        EmptyState("No files yet", "Open Scan & analyse to register a folder."),
        EmptyState("No results", "Try a broader query or switch search mode."),
    ]
    assert "Open Scan & analyse" in states[0].findChildren(QLabel)[1].text()
    assert "broader query" in states[1].findChildren(QLabel)[1].text()


def test_rule_delete_disabled_without_selection():
    from app.ui.pages.rules import RulesPage
    app = QApplication.instance() or QApplication([])
    page = RulesPage(build_context())  # use the existing context fixture factory
    page.table.clearSelection()
    page._sync_action_states()
    assert page.delete_button.isEnabled() is False
    assert "Select a rule" in page.delete_button.toolTip()


def test_busy_controls_disabled_while_task_runs():
    from app.ui.pages.planner import PlannerPage
    from app.ui.base import BasePage

    app = QApplication.instance() or QApplication([])
    page = PlannerPage(build_context())
    page._set_busy(True)
    assert page.rebuild_button.isEnabled() is False
    page._set_busy(False)
    assert page.rebuild_button.isEnabled() is True
```

- [ ] **Step 2: Run to confirm RED**

`pytest tests/test_ui_unification.py -q` → 3 failed (missing `_sync_action_states`, `_set_busy`, copy).

- [ ] **Step 3: Implement**

Add `RulesPage._sync_action_states() -> None` connected to `itemSelectionChanged`, disabling delete/toggle without a row and setting a tooltip. Add `PlannerPage._set_busy(busy: bool) -> None` and `HistoryPage._set_busy(busy: bool) -> None` that disable refresh/rebuild/maintenance controls, call it around synchronous operations via `try/finally`, and also disable those controls when `has_running_tasks()` is true. Update the empty-state copy on Library/Search/History/Planner/Review with an explicit next step. Keep confirmations, signals and pinned button texts.

- [ ] **Step 4: Run to confirm GREEN**

`pytest tests/test_ui_unification.py -q` → 13 passed; then the existing UI suites and full suite from Global Constraints.

- [ ] **Step 5: Capture and review**

Run the full verification set. Capture offscreen screenshots of all nine pages before and after by constructing `MainWindow` with an offscreen `QApplication` and calling `grab().save(...)` into `C:\Users\seldi\AppData\Local\Temp\opencode\ui-checkpoints\screenshots\`; compare visually. Checkpoint changed files.

---

## Self-Review

- Spec coverage: theme roles → Task 1; no inline colours/rich-text override → Task 2; shared widgets/actions → Task 3; hierarchy/spacing → Task 4; thin flow slice → Task 5; verification and screenshots → Task 5. No spec section lacks a task.
- Review Focus: all five rows have a named test in their owning task.
- Type consistency: `add_actions`, `_sync_action_states`, `_set_busy`, `EmptyState`, `Badge`, `has_running_tasks` use the same names in producing and consuming tasks.
- Proportion: code blocks are test assertions only; bodies are left to the implementer.
