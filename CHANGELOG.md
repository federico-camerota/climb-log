# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (`design/08-workflow.md` §3).

## [Unreleased]

### Added
- App shell (#70, D-073): a sidebar with Today, Log, Records, Dashboards and Settings,
  pages per module and entity in the URL (`/records/journal/session`), a light/dark toggle,
  Settings listing the modules (and what is wrong with one that doesn't load), and on Records
  the count of records and data issues with when they were read (an *offline* warning when
  only the snapshot is available). Today, Log and Dashboards are placeholders for their
  issues. Data is refetched when the window regains focus.
- The sidebar can be hidden on a wide window with the header's burger, and stays as left
  across reloads (D-074).
- Records page (#75, D-081): a sortable table of each entity's records, newest first, with a
  column picker, search that ignores accents, data issues marked in their cell and listed in a
  panel, and CSV export for an Italian spreadsheet.
- Today page (#74, D-080): the next-session recommendation with its reasons, and the forms due
  on the chosen day (a session or a rest day when nothing is logged; each session's pre and
  post forms after), done / partial / missing with what is missing, linking to each form;
  `GET /api/today?date=`.
- Log forms (#72, D-077): the journal's pre-session, post-session and rest-day forms, built
  from the module YAML; a session created at pre and completed at post; scales as compact
  dropdowns that start blank with the best value first (D-078), decimal commas, Italian notes;
  drafts kept until saved; every bad value shown under its field at once (D-079); the
  statuses after saving.
- Write API (#71, D-075): add, read one, change and soft delete records over HTTP
  (`POST /api/modules/{m}/{entity}`, `GET`/`PATCH`/`DELETE …/record?date=…&session_no=…`), with
  conflicts detected against the values the client read, and clear errors (the field at fault,
  a locked workbook, offline).
- Next-session recommendation (#73, D-071, D-076): a `recommendation:` block in the module YAML
  (values for a day, rules, reasons) with the journal's legacy rule (RECOVER / MODERATE /
  GREEN LIGHT) and messages, `GET /api/recommendation?date=`, and its sheet formulas, checked
  with LibreOffice against the app and the legacy Summary. New expression forms:
  `window(e.x, days=n, until=d)`, `last(e.x, until=d)` and `count(…, equals=v)`.
- `make api-types` generates the frontend's API types from the backend's OpenAPI schema;
  `make lint` checks they are up to date.

### Changed
- Reading a module asks its source whether it changed once per request, and a Google snapshot
  reads every tab from one copy: fewer Drive calls (a read after a change about twice as fast).
- M3 re-scoped (`design/07-roadmap.md`): logging mainly in the app on the computer, Google
  Sheets on the phone as the fallback; LAN mode moved to the backlog (D-069). Frontend
  libraries, the declarative readiness rule and backend-computed dashboards decided
  (D-070–D-072).

## [0.2.0] - 2026-10-30

M2: the Google Sheets backend (`design/07-roadmap.md`).

### Added
- Google login: `climblog google login | status | logout` with an OAuth desktop client named
  by `[google] client_secret` in the app config; the token is kept in the config folder,
  readable by the owner only, refreshed when needed and never printed; logout revokes it.
  Setup steps in the README, *Connect Google Sheets* (D-062, #50).
- Reading modules from Google Sheets: `google_sheet = "<ID or URL>"` in a module's config
  instead of `workbook`; one call reads the whole sheet with its number formats, so dates,
  times and durations read as from an `.xlsx`. The sheet is read again when Drive sees a change
  or the copy is older than `[google] max_age_seconds` (60 by default; Drive lags about 3
  minutes behind an edit). Plain REST, no new dependency (D-063, #51).
- Writing modules on Google Sheets: records are added, changed and deleted as in a local
  workbook (first free row of the formula buffer, conflict check on a fresh read, buffer
  top-up), all the cells of one write in one request that Google applies all or none; text
  stays text (`'` and `=` notes as typed). Busy answers (429, 5xx) are tried again for up to
  half a minute. Formulas read from a sheet in an Italian (decimal-comma) locale are compared
  in the app's syntax (D-064, #52).
- Schema sync on Google Sheets: `climblog check --apply` makes a Google-hosted module's sheet
  match its YAML as for a local workbook (tabs, styled and frozen headers, dropdowns, colour
  scales, status colours, formula columns with their buffer, named settings, `_meta`), in one
  request; headers and formula columns get a warning-only protection. A sheet the app creates
  goes into a `climb-log` Drive folder, in the it_IT locale and Europe/Rome time zone (`[google]
  folder`, `locale`, `time_zone`) (D-065, #53). The drift check works there too, and an opt-in
  live test checks that every value Google computes is the app's (D-066, #53).
- `climblog module move MODULE --to-google` copies a local module into a new Google Sheet, raw
  cells and all, checks the copy (records, settings, data issues, formulas computed by Google)
  and prints the config line; the workbook is only read. `climblog module create FILE --google`
  makes a new module's sheet (D-067, #54).
- While `climblog serve` runs, Google modules are read again every `[google] poll_seconds` (60)
  so phone entries reach the snapshot, and Google modules are backed up locally: the sheet is
  exported as `.xlsx` into the backups folder before writes and when a change is seen, at most
  every 30 minutes (D-068, #55).
- A checklist for hand entry on the phone (04-storage.md §3), to run once the journal is on
  Google, before M2 closes (#56).
- `PRIVACY.md`: the privacy policy Google asks for before an OAuth app can be published; the
  README setup steps now include it and the home page link.

### Changed
- The storage tests that every backend must pass are a contract suite
  (`tests/test_backend_*.py`), run on each backend through `tests/backends.py`; the tests
  particular to `.xlsx` stay in `test_xlsx*.py` and `test_sync.py` (#49). The read contract
  also runs on the Google backend, on an in-memory Google and, with `CLIMBLOG_GOOGLE_LIVE=1`,
  on the real API (#51), and so do the write (#52) and sync (#53) contracts.

## [0.1.0] - 2026-10-27

M1: the module framework and local storage (`design/07-roadmap.md`).

### Added
- Python backend skeleton: FastAPI app with `GET /api/health` (status and version) (D-038).
- `climblog serve` command (`--port`, `--reload`), bound to `127.0.0.1` only (D-010, D-038).
- Tooling: `uv` project and lock file, ruff, mypy `--strict`, pytest with coverage;
  `make test`, `make lint`, `make fmt`.
- Frontend skeleton: Vite + React + TypeScript (strict) with Mantine; header with a server
  status badge from `/api/health`; light/dark theme follows the OS (D-039).
- `climblog serve` serves the built SPA, with `index.html` for client-side routes and a hint
  page when the frontend is not built (D-039).
- `make install`, `make dev` (backend + Vite with hot reload), `make build`; `make test` and
  `make lint` now cover the frontend (vitest, tsc, eslint, prettier).
- pre-commit hooks, installed by `make install`: file hygiene, private-key detection, a
  personal-data check that rejects spreadsheets outside `design/mockups/` and `tests/fixtures/`,
  and the `make lint` checks (D-040).
- GitHub Actions CI: hooks, lint and tests on every pull request and push to `main` (D-040).
- `README.md` (status, quick start, data and privacy), `CONTRIBUTING.md`, a pull request
  template with the review sections and checklist, and bug / feature issue forms.
- Module YAML meta-schema and loader: `climblog module validate FILE...` reports every problem
  with file, line and path; `climblog module schema` prints the JSON Schema, committed as
  `modules/module.schema.json` for editor autocompletion (D-041).
- Module templates (expanded at load), split entities (one tab per section) and child entities
  are validated, with checks on sections, tab names, parents and renamed/retired fields (D-042).
- Expression language for derived fields and conditions: safe parser (no `eval`), checks at
  load with "did you mean" suggestions and the position of the problem, and per-record
  evaluation with the legacy blank-cell rules; `visible_if` conditions are checked when a module
  loads (D-043).
- Derived fields: expressions, `bands:` thresholds, `when:` cases and `map_from:` lookups are
  checked when a module loads (status labels against `status_levels` or a `levels:` list,
  `type: text` for messages) and computed per record in dependency order; new `worst_of()`.
  Entries that need later issues (`prev`, program, reference tables, plugins) are accepted and
  left for later (D-044).
- Cross-record expressions: `prev(x, n)`, `parent.x`, `children(e)` / `children(e).x` and
  `last(e.x, before=d)`, checked at load and computed over whole tables (children before
  parents, rows in date order); journal days since the previous session or climb, shoulder
  review flags and finger-strength set totals are now computed (D-045).
- Cells are read by field type with data issues (tab, row, column) instead of errors: decimal
  commas, ISO and day-first dates, date serials, `h:mm` durations, `75%`, Yes/No variants
  (incl. Sì), choices ignoring case and spaces, legacy choice values, raw text; required fields
  left empty are reported. Accent-insensitive search helper (D-046).
- Grade parser: French (`6b+`) and gym (plain numbers) grades with a numeric index, the
  system detected per value, slash grades (`6a/6a+`) halfway; bad grades are data issues and
  unsupported systems a load error (D-047).
- Reading local workbooks: a `Repository` interface and the `.xlsx` backend (openpyxl), and
  loading records with blank = default, ignored empty rows, duplicate keys, soft-deleted rows,
  split tabs joined on the key, settings from `_settings`, and data issues for orphan rows and
  missing tabs or columns (D-048). New dependency: `openpyxl` (MIT); `types-openpyxl`
  (Apache-2.0) for mypy.
- Writing local workbooks: add, update and soft-delete records (`RecordWriter`), split over
  their tabs, into the first free row of the formula buffer; updates refused when the row was
  edited in the sheet meanwhile; deleting a session also deletes its sets; text written as
  text, never as a formula; atomic save, refusal while the file is open in Excel or
  LibreOffice, rotating backups (D-049).
- App config `~/.config/climblog/config.toml` (or `--config` / `CLIMBLOG_CONFIG`): each
  module's YAML and workbook, and the backups folder, interval and count (D-051).
- `climblog check [MODULE...]`: lists where each workbook and its YAML disagree (missing tabs
  and columns, pending renames, unknown columns, `_meta` version) without changing anything;
  exit code 1 when something needs syncing or fixing (D-051).
- Schema sync, `climblog check --apply`: creates the workbook, missing tabs and columns (with
  styled header rows, coloured by group), `_settings` rows with defaults and named cells, and
  `_meta`; applies `renamed_from` renames; rewrites dropdowns, number ranges and scale colours
  on every sync. Additive only: columns, data and hand-reworded labels are kept (D-052).
- Formula compiler: derived fields become per-row sheet formulas with the app's blank rules,
  for `.xlsx` (`_xlfn.` names) and Google Sheets, reading other tabs, parent and child rows,
  `prev` and `last` through a hidden `auto:_key` column; `sheet_formula: false` or a
  hand-written `"=..."` per entry. `climblog module validate` lists the entries that stay app
  only. A parity test recalculates the formulas in LibreOffice and compares every cell with
  the app; CI installs LibreOffice for it (D-053).
- Formula columns in local workbooks: schema sync adds the AUTOMATIC columns (hidden key
  column, number formats, coloured statuses) and writes their formulas into a 200-row buffer,
  rewriting formulas changed by hand; app writes keep 50 buffer rows free. `climblog check`
  reports formulas changed by hand and values the sheet computed differently from the app
  (D-054).
- Local snapshot of each module (`~/.local/share/climblog/snapshots/`, gzipped JSON): reads
  come from it while the workbook is unchanged, it is refreshed when the workbook changes, and
  it is used read-only when the workbook can't be reached. Always safe to delete (D-055).
- The climbing journal module is complete in `modules/journal.yaml`, with a test for every rule
  of the legacy workbook; new functions `incomplete(...)` (the Log check) and `month(date)`
  (D-056).
- Read API: `GET /api/modules` (modules and their schemas) and `GET /api/modules/{m}/{entity}`
  (records with their derived values, data issues, "data as of"), through the local snapshot;
  `climblog serve --config FILE` (D-058).
- The finger strength module is complete in `modules/finger-strength.yaml`, with an end-to-end
  test of the local workbook: sync, write, read, derive (D-059).
- Fictional journal workbooks for the tests, in the legacy layout (its formulas included) and
  the new one with the hand-entry cases; `make fixtures` writes them to open (D-060).
- `climblog import-legacy --journal Climbing_Journal.xlsx [--dry-run]`: imports the legacy
  journal into a new journal workbook (refusing one that has records) and reports what it read,
  skipped, and how the values the legacy sheets computed compare with the app's (D-061).

### Fixed
- Rest days compute their weekday, as the legacy Rest Days tab does (found by the importer's
  parity report, D-061).
- Set rows typed by hand with a blank Set # load with the next number for that date
  (`default: next`) instead of being left out with a data issue (D-050, #35).
- A retired field whose column is missing is no longer reported as a data issue (D-052).
- `round()` works on 15 significant digits as the sheets do: a mean of 5.824999999999999
  (5.825 on paper) now rounds to 5.83, not 5.82 (D-053).
- `flip` and `flip_all` turn only values on a lower-is-better scale, as documented: the journal's
  wellbeing and mental scores no longer invert mood, energy and the other higher-is-better
  items (D-056).

### Changed
- CI no longer installs LibreOffice: the formula parity tests are skipped there and run
  locally before changes to formulas, expressions or sync (D-057).
- `make install` fails if `uv.lock` is out of date instead of updating it (`uv sync --locked`).

[Unreleased]: https://github.com/federico-camerota/climb-log/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/federico-camerota/climb-log/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/federico-camerota/climb-log/releases/tag/v0.1.0
