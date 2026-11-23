# OpenCoeus UI Unification Design

**Date:** 2026-11-22
**Status:** proposed

## Intent

The desktop UI already has one dark token system and a set of shared widgets, but the nine pages
drift: inline colours bypass `theme.py`, four pages duplicate the same transparent rich-text
override, `Badge`/`EmptyState`/`section_label`/`separator` are defined but unused, page headers and
action rows differ, and empty tables rarely say what to do next. The user wants the app to *look
good and unified*, plus a thin slice of flow guidance — not a new visual identity.

## Goals

- One visual language: every visible colour, border and radius comes from `app/ui/theme.py`.
- Actually use the shared widgets that already exist (`Badge`, `EmptyState`, `Card`, label helpers,
  `make_table`) instead of page-local lookalikes.
- One consistent page pattern: intro area, right-aligned action group, content, empty state.
- Thin flow slice: empty states name a next action; destructive/long-running controls show a
  disabled state instead of silently doing nothing.
- All existing UI tests stay green; no new dependency.

## Non-goals / anti-goals

- No new palette, typeface, icon set, branding, or page/nav restructure.
- No new dependencies, no Qt designer files, no web layer.
- No focus outline or press outline of any kind — the removed yellow outline stays removed.
- No changes to scan/analysis/classification/search logic, quality gate, database schema or CLI.
- No change to responsive dimensions asserted by tests (sidebar 176–260 px, header ≥64 px, stat
  card height, table widths) or to pinned button text.
- No modal confirm added to rule deletion (tests drive it directly); no threading refactor of
  synchronous history maintenance.

## Constraints

- Nine pages and their exact keys are pinned by `tests/test_ui_smoke.py`.
- `tests/test_ui_polish.py` requires `outline: none`, no other `outline:` declarations, no QSS
  focus selectors, token contrast values, and specific button texts (`Cancel`, “save”).
- `tests/test_ui_responsive.py` pins sidebar/header sizing, hidden labels, column counts at three
  breakpoints, stat-card height, and table widths under an enlarged font.
- `tests/test_rules_ui.py` pins rule row counts and delete behaviour; `tests/test_profiles.py`
  pins profile label text.
- `QT_QPA_PLATFORM=offscreen` for the full suite.

## Approaches

1. **Unify inside the current world (chosen).** Keep the dark editorial palette and page
   structure; centralise inline styling, reuse existing shared widgets, normalise headers/actions
   and spacing. Small diff, low regression risk, no license/dependency issue. Trade-off: the look
   stays recognisably the same.
2. **Replace the visual world.** New palette, type, icons and layout language across all nine
   pages. Highest visual impact, highest risk against the responsive width assertions and a much
   larger diff. Rejected.
3. **Flow-first redesign.** A scan→analyse→review→plan→execute progress rail with next-action
   prompts and stronger safety feedback. Rejected as a full approach; the user chose a *thin
   slice* of it: next-action empty states and disabled guards, no rail.

Chosen: **1 + thin slice of 3.**

## Design

### 1. Theme is the only source of visual values

- Add semantic QSS roles to `app/ui/theme.py` for the cases currently styled inline:
  surface/sub-surface text, detail/code text, link text, and section separators.
- Add one global `QTextBrowser` block to `STYLESHEET` (transparent, no border, token colours).
  Delete the four per-page `setStyleSheet` overrides on rich-text views.
- Replace hardcoded hex strings in page HTML and inline `setStyleSheet` calls with constants or
  role properties exported from `theme.py`. Near-duplicate colours collapse onto existing
  `TEXT`/`MUTED`/`FAINT` tokens; no new palette values. `STATUS_COLORS`, contrast values and
  `outline: none` remain unchanged.

### 2. Shared widgets replace page-local lookalikes

- Status pills in detail panels and the Overview category mix become `Badge` (or the same role
  property). Table status cells keep coloured `QTableWidgetItem` text via a shared theme helper:
  `setCellWidget` would break selection, tooltips, row data and the pinned column widths.
- Empty tables use `EmptyState` with a concrete next action while keeping existing count labels
  and pinned “starts empty” / “fresh session” copy.
- Use `section_label` and `separator` for section boundaries; use `Card(trailing=…)` for
  right-aligned action groups.
- Add one small `add_actions(layout, *widgets)` helper in `widgets.py` for a consistent
  right-aligned, wrapping action row; page-level widget attributes and texts stay unchanged.

### 3. Consistent page rhythm and actions

- Normalise primary/danger/flat roles: the accent marks the one decisive next step — Start scan
  on Scanner (Analyse takes over once files are registered), Approve/Execute on Planner, Save on
  Settings; pages without a decisive action have none. Danger only for destructive actions. Keep
  pinned labels and tooltips (`Ctrl+1`, `Ctrl+8`).
- Move page-local spacing deviations (Settings margin, Planner explicit margin, tab margins, grid
  spacing) onto the `scrollable_page` default where no test pins them. Do not touch table column
  sizing or the responsive shell.

### 4. Thin flow slice

- Every emptied table states the next step, e.g. “No files yet — open Scan & analyse to register
  a folder.”
- Rule delete disables when no row is selected, with a tooltip explaining why; no modal confirm,
  no silent no-op, no repeated status messages.
- Refresh/Rebuild-preview and History maintenance controls disable while a tracked page task runs
  or while their own synchronous operation is in progress (local busy flag); no threading
  refactor. Existing confirmations and failure emissions stay.

### 5. Tests (TDD, RED → confirm → GREEN)

- New `tests/test_ui_unification.py`: no inline hex colours in page modules (token constants
  allowed), zero per-page rich-text stylesheet overrides, status views use the shared role or
  `Badge`, empty states present on the pinned pages, rule delete disabled without selection,
  busy controls disabled while a task runs.
- Re-run `tests/test_ui_smoke.py`, `test_ui_chrome.py`, `test_ui_responsive.py`,
  `test_ui_polish.py`, `test_planner_ui.py`, `test_rules_ui.py`.

## Files expected to change

`app/ui/theme.py`, `app/ui/widgets.py`, `app/ui/pages/*.py` (subset), `tests/test_ui_unification.py`.
No service, repository, model, CLI or analysis file changes.

## Verification

```
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check app tests main.py
.venv\Scripts\python.exe -m compileall -q app tests main.py
.venv\Scripts\python.exe -m pytest tests/test_quality_gate.py -q
```
Capture the rendered GUI offscreen after implementation and compare against the pre-change
capture; do not rely on reading QSS alone.

## Left to the builder

Exact role names and helper signatures, which specific pages adopt each shared widget, the precise
next-action copy, the test implementation, and how to make the offscreen capture. A reviewer will
check this document before approval.
