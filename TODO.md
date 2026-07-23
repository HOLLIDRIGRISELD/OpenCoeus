# OpenCoeus engineering backlog

`PROJECT_PLAN.md` is the source of truth for product scope. This file tracks the next actionable work needed to deliver it.

## Current baseline — complete

- [x] Cross-platform scan-only desktop application for Windows, macOS, and Linux.
- [x] Safe traversal, exact SHA-256 duplicate detection, local SQLite audit history, and CSV export.
- [x] Offline PDF/DOCX text extraction and filename suggestions.
- [x] Platform-aware protected folders and non-destructive default policy.

## Next: selective drive review

- [ ] Build a folder-selection tree for a selected drive or root folder.
- [ ] Allow individual folder inclusion and exclusion before scan results are analysed for organisation.
- [ ] Detect and recommend exclusion for system folders, installed applications, game libraries, source-code projects, package dependencies, virtual environments, and version-control repositories.
- [ ] Explain every recommendation and permit an explicit user override.
- [ ] Store user exclusions locally as reusable scan profiles.

## Next: controlled organisation without AI

- [ ] Add deterministic rules based on extensions, filename patterns, dates, sizes, and user-selected profiles.
- [ ] Preserve the selected folder's structure by default; never flatten or mix unrelated folders.
- [ ] Keep text-derived title suggestions optional and separate from proposed file actions.
- [ ] Add a result preview that shows `original path -> proposed path` for every proposed action.

## Required before file changes

- [ ] Add explicit per-action and bulk approval controls.
- [ ] Add collision detection and a re-scan immediately before applying changes.
- [ ] Add a persistent, reversible transaction journal for renames, moves, and approved duplicate resolution.
- [ ] Never delete a file automatically; require explicit approval to resolve each duplicate group.

## Later: advanced data workflows and release

- [ ] Define supported spreadsheet schemas before enabling `.xlsx` or `.xlsm` consolidation.
- [ ] Implement read-only spreadsheet inspection, followed by an approved master-workbook workflow.
- [ ] Evaluate optional local NLP categorisation after the deterministic workflow is reliable.
- [ ] Build, package, and test on clean offline Windows, macOS, and Linux machines.
