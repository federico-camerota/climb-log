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

### Changed
- `make install` fails if `uv.lock` is out of date instead of updating it (`uv sync --locked`).
