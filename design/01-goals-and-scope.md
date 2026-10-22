# 01 · Goals and scope

## Vision
A local web app that is the day-to-day front end for my climbing training data. The data
stays in spreadsheets (local `.xlsx` or Google Sheets) that I own and can still open and
edit by hand. The app handles logging, visualization, analysis and planning, which are
awkward in spreadsheets.

## Goals
- **G1 · Logging**: fast, guided forms (pre-session, post-session, rest day, program
  check-ins), usable on a phone over the local network. One "Today" flow that collects
  everything relevant for the day across all active modules. No duplicate entry.
- **G2 · Spreadsheets as the source of truth**: every piece of data lives in a spreadsheet
  in a clean, human-readable layout. Backends: local `.xlsx` and Google Sheets.
- **G3 · Parity**: everything the current workbooks compute (statuses, scores, review
  flags, summaries, search) is reproduced (see `00-current-state.md`).
- **G4 · Dynamic analysis**: interactive charts with any time range, filters,
  cross-module correlations, training-load metrics and calendar views
  (see `05-analytics.md`).
- **G5 · Decision support**: a "next session" recommendation that combines readiness,
  program rules (shoulder status, fall-ladder progression) and patterns found in my own
  history, always showing *why*.
- **G6 · Flexibility**: what is tracked is defined in config (module YAML files). Adding
  or retiring a field, changing thresholds, or adding a new program needs no code in the
  common case (see `03-module-framework.md`).

## Non-goals (for now)
- Multi-user accounts, cloud hosting, sharing with a coach. It is single-user and local.
  LAN access from my phone is the only remote access.
- Native mobile app. A responsive web UI is enough.
- A database as source of truth. An in-memory cache or SQLite index is allowed but is
  always rebuildable from the sheets.
- Medical advice. Shoulder and fear rules stay as tracking heuristics, worded as in the
  originals.

## Constraints
- Runs locally with one command on Linux; Python + Node toolchains are acceptable.
- Data volume is small (hundreds to a few thousand rows per year). Performance concerns
  are about Google API latency and quotas, not computation.
- Must tolerate hand edits in the sheets: invalid cells are reported, not fatal.
- Notes may be in any language (currently Italian); the UI is in English.
