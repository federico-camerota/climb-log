# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (`design/08-workflow.md` §3).

## [Unreleased]

### Added
- Forms show a field with `visible_if` only while its condition holds, and a hidden field isn't
  saved or counted as missing on Today; text fields with `suggest_from_history` (the journal's
  venue and partners) suggest the values typed before (#122, D-100).
- The `forms:` block of a module YAML is checked at load: its entity, sections and child forms
  (D-100).
- The finger-strength Log form edits the session's sets: hang sets or curl sets by session
  type, "+ set" copying the previous set's protocol and load, sets removed or changed, all saved
  with the session; Today lists the finger-strength form (#124, D-101).
- Records filters as the legacy Log Search: a date range, weekdays, a status class and value;
  the search finds derived values too (statuses, log check) and highlights the words found
  (D-102).
- Today shows the weakest area of the latest session with the recommendation, and this week's
  training load (load, sessions, ratio, finger training) (D-102).
- The Log form says it is read-only, with Save off, when the workbook can't be reached (D-102).
- Finger-strength sessions log wellbeing: mood and energy before, fatigue and mood after, from
  2026-11-03 (module v4: run `climblog check finger_strength --apply` to add the columns)
  (D-101).

### Changed
- CI skips lint and tests when only Markdown changed, cancels a pull request's superseded
  runs, and runs pytest on every core (pytest-xdist, also in `make test`) (D-104).
- The finger-strength session's start time is optional: Today no longer counts it as missing
  (D-101).
- The unused field options `hidden_in_form` and `searchable` are removed: a module that sets
  them no longer loads (D-099, D-100).
- The commit check refuses the app's snapshots (`*.json.gz`) outside the fictional-data folders,
  and OAuth secrets, tokens and `.env` files anywhere, not only spreadsheets (it also catches a
  file added by force past `.gitignore`).

## [0.4.0] - 2026-11-03

M4: analytics: the metric layer, new charts, training load, before/after and grades, the
Explore page with correlations (`design/07-roadmap.md`).

### Added
- README screenshots of the training load and the Explore page (#104); the demo journal of
  `scripts/demo_journal.py` covers 26 weeks (`--weeks`).
- Metric catalogue and query API (#97, D-090): `GET /api/metrics` lists every numeric field and
  derived value of the loaded modules (and the choice fields that filter them);
  `GET /api/metrics/query` lines metrics up by record, day, week or month, with an aggregate,
  a rolling mean, a lag for "the day after", filters and the n behind every value; modules are
  joined by calendar day.
- Widget library v1 (#98, D-091): `bars` (per period or per value of a field), `weekbars`
  (counts per week by value, or sums stacked by a field), `stacked`, `box_by` (Tukey box plots
  with n) and `scatter` (with a trend line, across entities with a lag), and the `line`'s
  `split_by` and `x`, drawn on the dashboard. A chart of a field that isn't a number is a load
  error; a line's legend shows the field's label, not its key.
- Training load (#99, D-092): the journal's new `load` dashboard shows the weekly session-RPE
  load (sessions without duration or effort flagged), sessions and days trained, rest days,
  finger training on its own chart (sessions without effort flagged), the acute:chronic
  workload ratio with zones as context, monotony, strain and training streaks, and sessions
  per week by type.
- Before → after (#100, D-093): the journal's new `progress` dashboard shows how sessions change
  mood and each body part's soreness (means before and after, the change and n, per session
  type), and soreness by body part and week before sessions, after them and on rest days. A
  body part counts from its `since:` date.
- Grade charts (#101, D-094), in the `progress` dashboard: the hardest grade tried per session
  over time (French and gym on their own axes, gym grades per venue), sessions by hardest
  grade tried per month, and by setting and venue (gym grades always per venue); values typed
  in the sheet that aren't grades are counted.
- Click a day of the dashboard's training calendar to see its records in a drawer: statuses,
  scores and the filled fields by section, with Edit and "Log this day" (D-098).
- Explore page (#102, D-095): any metrics of any module over a range, per record, day, week or
  month, with an aggregate, a rolling mean, filters on choice fields, as a line or bars, with
  n; two units at most, each on its own axis (a metric without a unit gets an axis of its
  own); the class scores' LOW/WATCH/GOOD bands behind a line; repeated labels told apart
  ("Mood · Wellbeing · before"); the view is in the URL, so it can be bookmarked.
- Correlations (#103, D-096), as Explore tabs: two metrics against each other (Spearman and
  Pearson r with 95% intervals and n, Y read days later), a correlation matrix, and what goes
  with a good session (each metric known before climbing against the feel score or any
  score, ranked); under the minimum n (`[analytics] min_n`, default 10) results are greyed
  out or hidden; a pair can be read per record, day, week or month; each tab has its own date
  range and filters (those of its metrics); words add "could be none" when the 95% interval
  includes 0. New dependency:
  scipy (BSD-3).
- Metrics leave out a field's values dated before its `since:` (Explore and correlations
  counted values typed before a body part was tracked).

### Changed
- M4 scoped (`design/07-roadmap.md`): eight issues, the analyses useful on little data first
  and the correlation tools last; the rest of `05-analytics.md` moved to the backlog (D-086).
  Analytics in plain Python with scipy, no pandas (D-087); modules joined by date (D-088).
- Faster tests (D-089): coverage measures with Python 3.12's `sys.monitoring`
  (`core = "sysmon"`); the Python tests took ~8 minutes in CI, mostly the coverage tracer's
  overhead (locally 462 s → 177 s).

### Fixed
- A finger-strength set added through the app without a set number is no longer refused: it
  gets the next number for its date, as a blank Set # typed in the sheet does (#114, D-050).
- Dashboard charts are drawn as SVG instead of on a canvas (D-097): in Firefox on Linux with GPU
  canvas acceleration, some charts stayed blank until clicked.

## [0.3.0] - 2026-11-02

M3: the journal app: logging, Today, records, dashboard and the sheet's Summary tab
(`design/07-roadmap.md`).

### Added
- README screenshots of Today and the dashboard (#80), made by `scripts/screenshots.py`
  (headless Firefox) on the fictional journal of `scripts/demo_journal.py`.
- Summary tab in the sheet (#79, D-085): schema sync writes a `Summary` tab with the latest
  session, days since, latest status, weakest area, LOW sessions in 14 days, the suggested next
  session and the last 4 sessions side by side, as formulas compiled from the module YAML, so the
  sheet on the phone shows what the app shows; a cell changed by hand is drift.
- Dashboard, part 2 (#78, D-084): a training calendar (a square per day on a grid, coloured by
  the day's status, rest days lighter, a letter for gym, outdoor, home wall or rest; from the
  first record's month, at most 12 months), the last 4, 8 or 12
  sessions side by side with the latest notes, the best reflections of the last 2 weeks and
  those needing attention, the rest days of the last 2 weeks, and monthly averages over 6, 12,
  24 or all months, as the legacy Summary sheets.
- Dashboard, part 1 (#77, D-083): the journal's dashboard with the latest status and days since
  the last session, the status board by class (as the legacy Summary – Trends: last 4 vs the 4
  before, direction, LOW in the last 12) and the scores by class over time with the status bands,
  a rolling mean and a range picker; `GET /api/modules/{m}/views/{view}`. Views in the module
  YAML are now checked when it loads.
- Editing records (#76, D-082): click a record on the Records page to edit the whole record in
  a drawer, its data issues under their fields (a bad value shown as typed), or delete it after
  a confirmation; the issues panel deletes rows the app leaves out (a duplicate key, no date,
  an orphan) and creates the missing session of an orphan section row.
- App shell (#70, D-073): a sidebar with Today, Log, Records, Dashboards and Settings,
  pages per module and entity in the URL (`/records/journal/session`), a light/dark toggle,
  Settings listing the modules (and what is wrong with one that doesn't load), and on Records
  the count of records and data issues with when they were read (an *offline* warning when
  only the snapshot is available). Today, Log and Dashboards are placeholders for their
  issues. Data is refetched when the window regains focus.
- The sidebar can be hidden on a wide window with the header's burger, and stays as left
  across reloads (D-074).
- Records page (#75, D-081): a sortable table of each entity's records, newest first, with a
  column picker grouped by section ("Wellbeing note (before)" rather than seven "Note"),
  search that ignores accents and says in which hidden field it matched, data issues marked
  in their cell and listed in a panel, and CSV export for an Italian spreadsheet; the table
  scrolls within one screen, so its scrollbars stay in view.
- Today page (#74, D-080): the next-session recommendation with its reasons, and the forms due
  on the chosen day (a session or a rest day when nothing is logged; each session's pre and
  post forms after), done / partial / missing with what is missing, linking to each form;
  `GET /api/today?date=`. A field marked `optional: true` in the module YAML may stay blank in
  a done form.
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

### Fixed
- A sheet formula reading a split entity's latest record with `last()` took that tab's latest
  row, an older session's value when the latest session had no row there yet; it now finds the
  record on the main tab, as the app does (D-085). Schema sync rewrites these formulas once.

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

[Unreleased]: https://github.com/federico-camerota/climb-log/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/federico-camerota/climb-log/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/federico-camerota/climb-log/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/federico-camerota/climb-log/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/federico-camerota/climb-log/releases/tag/v0.1.0
