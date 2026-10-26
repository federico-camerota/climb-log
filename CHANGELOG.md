# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (`design/08-workflow.md` §3).

## [Unreleased]

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
- The climbing journal module is complete in `modules/journal.yaml`, with a test for every rule
  of the legacy workbook; new functions `incomplete(...)` (the Log check) and `month(date)`
  (D-056).

### Fixed
- Set rows typed by hand with a blank Set # load with the next number for that date
  (`default: next`) instead of being left out with a data issue (D-050, #35).
- A retired field whose column is missing is no longer reported as a data issue (D-052).
- `round()` works on 15 significant digits as the sheets do: a mean of 5.824999999999999
  (5.825 on paper) now rounds to 5.83, not 5.82 (D-053).
- `flip` and `flip_all` turn only values on a lower-is-better scale, as documented: the journal's
  wellbeing and mental scores no longer invert mood, energy and the other higher-is-better
  items (D-056).

### Changed
- `make install` fails if `uv.lock` is out of date instead of updating it (`uv sync --locked`).
