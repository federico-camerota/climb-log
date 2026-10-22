# 07 · Implementation roadmap

Each milestone ends in something runnable and tested. Status: ☐ todo · ◐ in progress · ☑ done.

### M0 · Skeleton ◐
- Repo layout (`backend/`, `frontend/`, `modules/`, `design/`), `uv` + `pnpm` projects,
  ruff/eslint/prettier, pytest/vitest, a `Makefile` (`make dev`, `make test`, `make build`).
- FastAPI hello + SPA served by FastAPI; `climblog serve`.
- Choose the UI kit (Mantine vs shadcn/ui).
- Project basics (`08-workflow.md` §7): README, CHANGELOG (LICENSE already added, D-036), CONTRIBUTING,
  `CLAUDE.md` commands section, pre-commit config (incl. the personal-data check),
  GitHub Actions CI, PR and issue templates, branch protection on `main`,
  GitHub milestones/issues for M1.
- **Done when**: `make dev` shows an empty app; `make test` passes.

### M1 · Module framework + local storage ☐
- Meta-schema (pydantic) for module YAML; loader with good error messages; JSON Schema export.
- Expression evaluator (safe AST), `bands`, `when`, `worst_of`, `flip`, `prev`.
- Natural keys, **split entities** (one tab per section), **child entities** (sets), templates (`soreness`), `visible_if`; orphan-row detection.
- Text handling: raw-text writes, decimal commas, accent-insensitive search (D-024).
- `Repository` interface + `XlsxBackend`: read/append/update/soft delete, atomic save,
  lock detection, backups. Two-row headers (labels + keys), data validation.
- Schema sync (create tabs, headers, validation, additive changes) + `climblog check`.
- **Formula compiler** (D-018): derived fields → per-row sheet formulas, `_settings`
  references, pre-filled formula buffer, conditional formatting, drift check.
- Local snapshot (D-020).
- `modules/journal.yaml` complete; legacy journal importer + parity report; grade parser (French + gym).
- **Synthetic fixture generator** (D-034): fictional workbooks in the legacy layouts (with their
  original formulas) and in the new layout, used by importer, parity and hand-entry tests.
- **Finger strength** journal (`modules/finger-strength.yaml`, local xlsx): child entities, conditional fields; end-to-end test of the xlsx backend (D-019, D-025).
- Read API: `/api/modules`, `/api/modules/{m}/{entity}`.
- **Done when**: the imported journal loads, and the derived values match the legacy sheet
  (parity tests green on the 2 real sessions + synthetic fixtures covering edge cases).

### M2 · Google Sheets backend ☐  *(moved up, D-013)*
- OAuth desktop login (`climblog google login`), `GSheetsBackend` (batchGet, append,
  update by key, conflict check), change polling, Drive-export backups.
- `climblog module create --google` / "move module to Google" (copy a local workbook into a
  new Google Sheet with headers, dropdowns, colours).
- Verify hand entry on the phone (Google Sheets app): dropdowns work, dates parse, blank
  `session_no`/`id` are accepted, rows are picked up by the app.
- **Done when**: the journal works identically from local and Google, with the backend
  contract tests passing for both; a session typed by hand on the phone appears in the app.

### M3 · Journal app (logging + parity views) ☐
- Write API (a session write is split across the section tabs); schema-driven forms
  (pre/post/rest day); Today page with due list and log check.
- Records table + search; data-issues panel (orphan section rows, bad values).
- Journal dashboard at parity: status board, last N sessions, monthly averages,
  reflections, rest days, readiness recommendation.
- Generated `Summary` tab with formulas (latest statuses, suggested next session).
- **Done when**: I log a full session on my phone (LAN mode + PIN) and no longer need the old journal spreadsheet.

### M4 · Analytics ☐
- Metric query layer; widget library v1 (kpi, line+bands, bars, box_by, scatter, calendar heatmap).
- Explore page; correlation pair + matrix; training load (session-RPE, ACWR, monotony/strain);
  pre→post deltas; grade charts.
- **Done when**: the explorer can answer "does sleep relate to my session feel?" with n and CI.

### M5 · Program modules ☐
- `program:` block (weeks, phases, runs), reference tables, `ref` fields, prefilled fields.
- `shoulder.yaml` + importer (plan, exercise log, check-ins, retests); review-flag rule;
  program grid, weekly dashboard, retests view; next-morning reminder.
- `fear-of-falling.yaml` + importer (fear map, ladder, falls, 20Q, weekly review);
  ladder plugin (advancement assistant); fear widgets (ladder, radar, predicted vs actual).
- Combined recommendation card.
- **Done when**: both programs are logged through the app or by hand in their sheets, with
  parity with the legacy dashboards.

### M6 · Polish & extensibility ☐
- Settings UI (thresholds, sources, backups restore, data issues).
- Saved explorer views, period reports, exports.
- Optional: offline outbox for Google; module editor UI; insights feed.

## Testing strategy
- **Backend contract tests** run against both backends (xlsx in a temp dir; Google against
  a test spreadsheet, opt-in via an env var).
- **Parity tests**: fixtures from the legacy workbooks with the expected computed values.
- **Formula parity**: the generated formulas are evaluated by LibreOffice headless (xlsx) and
  read back from a test Google Sheet, and must equal the Python results on the same fixtures.
- **Hand-entry tests**: fixtures with rows typed "by a human" (blank keys, reordered columns, Italian notes starting with `'`,
  `7,5` decimals, legacy choice values, orphan section rows).
- **Expression/rules unit tests** for each rule in `00-current-state.md`.
- **Frontend**: component tests for the form renderer from sample schemas; a Playwright
  smoke test of "log a session" end to end.

## Order rationale
The Journal comes first because it holds the most data and is the main daily habit; it also
exercises every framework feature except programs. Google comes right after the core
because logging by hand in Google Sheets while away is a primary use case (D-013), and the
sheet layout must be validated for hand entry before many records exist.
