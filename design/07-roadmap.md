# 07 · Implementation roadmap

Each milestone ends in something runnable and tested. Status: ☐ todo · ◐ in progress · ☑ done.

### M0 · Skeleton ☑
- Repo layout (`backend/`, `frontend/`, `modules/`, `design/`), `uv` + `pnpm` projects,
  ruff/eslint/prettier, pytest/vitest, a `Makefile` (`make dev`, `make test`, `make build`).
- FastAPI hello + SPA served by FastAPI; `climblog serve`.
- Choose the UI kit (Mantine vs shadcn/ui). → Mantine (D-039).
- Project basics (`08-workflow.md` §7): README, CHANGELOG (LICENSE already added, D-036), CONTRIBUTING,
  `CLAUDE.md` commands section, pre-commit config (incl. the personal-data check),
  GitHub Actions CI, PR and issue templates, branch protection on `main`,
  GitHub milestones/issues for M1. → pre-commit and CI done (D-040);
  README, CONTRIBUTING, PR and issue templates done (README screenshots wait for M3).
- **Done when**: `make dev` shows an empty app; `make test` passes.

### M1 · Module framework + local storage ☑
- Meta-schema (pydantic) for module YAML; loader with good error messages; JSON Schema export. → done (D-041).
- Expression evaluator (safe AST), `bands`, `when`, `worst_of`, `flip`, `prev`. → parser, load-time check and evaluator done (D-043); derived fields with `bands`/`when`/`worst_of`/`map_from`, checked at load and computed in dependency order, done (D-044); `prev`, `parent.x`, `children(e).x` and `last` computed over whole tables (D-045).
- Natural keys, **split entities** (one tab per section), **child entities** (sets), templates (`soreness`), `visible_if`; orphan-row detection. → schema side done (D-042); `visible_if` checked (D-043); orphan rows in #14.
- Text handling: raw-text writes, decimal commas, accent-insensitive search (D-024). → reading cells by type with data issues, decimal commas and accent-insensitive search done (D-046); raw-text writes done (D-049).
- `Repository` interface + `XlsxBackend`: read/append/update/soft delete, atomic save,
  lock detection, backups. Two-row headers (labels + keys), data validation. → reading done
  (Repository, XlsxBackend, loading with joins and data issues, D-048); writes done (record
  add/update/soft delete with conflict check, free-row appends, raw text, atomic save, lock
  check, rotating backups, D-049).
- Schema sync (create tabs, headers, validation, additive changes) + `climblog check`. → app
  config and the read-only `climblog check` done (D-051); schema sync (`check --apply`) done
  (D-052).
- **Formula compiler** (D-018): derived fields → per-row sheet formulas, `_settings`
  references, pre-filled formula buffer, conditional formatting, drift check. → compiler and
  LibreOffice parity test done (D-053); formula columns, buffer, status colours and drift
  check in xlsx done (D-054).
- Local snapshot (D-020). → done: gzipped JSON of the rows, `CachedRepository` (D-055).
- `modules/journal.yaml` complete; legacy journal importer + parity report; grade parser (French + gym). → grade parser done (D-047); journal complete, every legacy rule tested (D-056); importer and parity report done (D-061).
- **Synthetic fixture generator** (D-034): fictional workbooks in the legacy layouts (with their
  original formulas) and in the new layout, used by importer, parity and hand-entry tests. →
  journal fixtures done, generated at test time; `make fixtures` (D-060).
- **Finger strength** journal (`modules/finger-strength.yaml`, local xlsx): child entities, conditional fields; end-to-end test of the xlsx backend (D-019, D-025). → done: moved to `modules/`, round trip sync → write → read → derive (D-059). Its conditional fields are covered by the child tabs (hang-only and curl-only fields live in `Hang sets` and `Curl sets`), so it needs no `visible_if`; `visible_if` is checked at load (D-043) and comes to forms with the UI.
- Read API: `/api/modules`, `/api/modules/{m}/{entity}`. → done, through the snapshot (D-058).
- **Done when**: the imported journal loads, and the derived values match the legacy sheet
  (parity tests green on the 2 real sessions + synthetic fixtures covering edge cases). →
  done: the owner imported the real journal and its parity report passed (D-061). Released
  as v0.1.0.

### M2 · Google Sheets backend ☑  *(moved up, D-013)*
- **Backend contract tests** (`tests/test_backend_*.py`): what every `Repository` must do
  (read, write, schema sync), run on each backend through a small harness
  (`tests/backends.py`). → done for xlsx (#49); reading on Google too, on an in-memory Google
  and, opt-in, the real API (#51); writing (#52) and schema sync (#53) too.
- OAuth desktop login (`climblog google login | status | logout`). → done (D-062, #50).
- `GSheetsBackend`: reading, `google_sheet` in the config (→ done, D-063, #51); append,
  update by key, conflict check (→ done, D-064, #52); change polling, Drive-export backups
  (→ done, D-068, #55).
- Schema sync on Google: headers, dropdowns, colours, formulas, warning-only protection; a new
  sheet in the app's Drive folder (→ done, D-065, #53).
- `climblog module create --google` / "move module to Google" (copy a local workbook into a
  new Google Sheet with headers, dropdowns, colours). → done (D-067, #54): `module create FILE
  --google`, `module move MODULE --to-google`; the owner moves the real journal.
- Verify hand entry on the phone (Google Sheets app): dropdowns work, dates parse, blank
  `session_no`/`id` are accepted, rows are picked up by the app. → the checklist is in
  04-storage.md §3, *Hand entry on the phone* (#56); → done: the owner moved the real journal
  to Google and every item passed on the phone.
- **Done when**: the journal works identically from local and Google, with the backend
  contract tests passing for both; a session typed by hand on the phone appears in the app. →
  done: the journal lives on Google, `climblog check journal` is clean, and a session typed on
  the phone reached the app. Released as v0.2.0.

### M3 · Journal app (logging + parity views) ☐  *(re-scoped, D-069)*
Logging happens mainly in the app on the computer; Google Sheets on the phone is the fallback
away from home (D-069). Issues in the milestone "M3 · Journal app", in this order:
- App shell: pages, navigation (desktop-first), data fetching (D-070). → done (D-073, #70):
  routes, sidebar, light/dark, Settings → modules, record counts; API types generated.
- Write API (a session write is split across the section tabs, `storage/write.py`).
- Schema-driven forms (pre-session, post-session, rest day; a record created at pre and
  completed at post). → done (D-077, #72).
- `window()` and a declarative readiness recommendation (D-071). → done (D-076, #73):
  `recommendation:` block, `GET /api/recommendation`, formulas checked against the legacy Summary.
- Today page: due forms, log check, recommendation. → done (D-080, #74).
- Records page with search and the data issues (orphan section rows, bad values) → done
  (D-081, #75); editing and fixing records, including those typed on the phone → done
  (D-082, #76).
- Journal dashboard at parity (D-072): status board, last N sessions, monthly averages,
  reflections, rest days.
- Generated `Summary` tab in the sheet ("Recent": latest statuses, suggested next session), so
  the recommendation is also in the sheet away from home.
- README screenshots of the Today page and dashboard (left out of M0: the app was empty).
- **Done when**: I log full sessions (pre, post, rest day) from the app on the computer and
  review them there (Today log check and recommendation, records with data issues, dashboard
  at parity with the old Summary sheets); a session typed on the phone in the sheet shows up
  and can be fixed in the app; the sheet's Summary tab matches the app's recommendation; the
  old journal spreadsheet is no longer needed.

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

### Backlog (no milestone yet)
- **LAN mode + PIN** (D-010): the app from the phone on the home network. Out of M3: the phone
  logs in Google Sheets (D-069).
- **Gym log**: a sheet-first module for logging at the gym how each boulder or route attempt
  felt (one row per attempt, typed on the phone, reviewed in the app). The module framework
  covers it as it is: a new module YAML and `climblog module create FILE --google`.

## Testing strategy
- **Backend contract tests** run against both backends (xlsx in a temp dir; Google against
  a test spreadsheet, opt-in via an env var).
- **Parity tests**: fixtures from the legacy workbooks with the expected computed values.
- **Formula parity**: the generated formulas are evaluated by LibreOffice headless (xlsx) and
  read back from a test Google Sheet, and must equal the Python results on the same fixtures.
  → both done: `test_formula_parity.py` (LibreOffice) and `test_gsheets_parity.py` (Google,
  opt-in with `CLIMBLOG_GOOGLE_LIVE=1`, D-066).
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
