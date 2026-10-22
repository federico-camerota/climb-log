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

### Changed
- `make install` fails if `uv.lock` is out of date instead of updating it (`uv sync --locked`).
