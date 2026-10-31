# 02 · Architecture

## Overview

```
 Browser (desktop)
 ┌──────────────────────────────────────────────┐
 │ React + TypeScript SPA                        │
 │  · schema-driven forms   · dashboards/widgets │
 │  · analysis explorer     · settings           │
 └───────────────▲──────────────────────────────┘
                 │ JSON over HTTP (/api/...)
 ┌───────────────┴──────────────────────────────┐
 │ FastAPI app (Python)                          │
 │  modules/   load + validate module YAML       │
 │  engine/    derived fields, statuses, rules   │
 │  analytics/ pandas: aggregates, stats, load   │
 │  plugins/   custom rules/views in Python      │
 │  storage/   Repository → backends             │
 │       ├── XlsxBackend   (openpyxl)            │
 │       └── GSheetsBackend (Sheets API, gspread)│
 └───────────────┬──────────────────────────────┘
                 │
     local .xlsx files  /  Google Sheets
```

The backend is the only component that touches data. The frontend is generic: it renders
forms and widgets from module schemas and view definitions served by the API.

## Stack (decided, see `decisions.md`)
| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, pydantic v2 | typed API, easy to extend in Python |
| Data/analysis | pandas, numpy, scipy (statsmodels later if needed) | correlations, regressions, rolling stats |
| Excel | openpyxl | read/write xlsx, data validation, styling |
| Google | Sheets API v4 and Drive API v3 over REST with google-auth's `AuthorizedSession` (D-063); login with `google-auth-oauthlib` (D-062) | no extra client library, typed, one call reads a whole sheet |
| Frontend | Vite + React + TypeScript | rich forms, fast UI |
| Server state | TanStack Query | caching, refetch after writes |
| Forms | react-hook-form + zod (zod schema generated from module schema JSON) | |
| Charts | Apache ECharts (`echarts-for-react`) | calendar heatmaps, radar, large set of chart types, good interactivity |
| UI kit | Mantine (D-039) | responsive, ready-made forms/date pickers; library code stays a dependency |
| Tooling | `uv` (Python), `pnpm` (JS), pytest, vitest, ruff, eslint/prettier | |

## Runtime
- `climblog serve`: FastAPI serves the API and the built SPA on `http://127.0.0.1:8000`.
  `make build` writes the SPA into the Python package (`backend/climblog/static/`, git-ignored);
  `/api/*` goes to the API (unknown paths: JSON 404), `/assets/*` to the bundled files, and every
  other path returns `index.html` so client-side routes survive a reload (D-039).
- `climblog serve --lan` (backlog, D-069): would bind `0.0.0.0` for phone access and **require
  a PIN/token** (set on first run) because the API can write data.
- Dev mode (`make dev`): Vite dev server on `127.0.0.1:5173` (hot reload) proxying `/api` to
  `climblog serve --reload` on `:8000`; Ctrl-C stops both.
- App config (D-051): `~/.config/climblog/config.toml` (`$XDG_CONFIG_HOME` honoured; another
  file with `--config` or `CLIMBLOG_CONFIG`) holds paths only, no training data, and is not part
  of the repo. Each module names its YAML and its workbook; backups default to
  `~/.local/share/climblog/backups/<module>/` (`$XDG_DATA_HOME`). `~` is expanded and relative
  paths are relative to the config file. Unknown keys are errors. `[google]` names the OAuth
  client file and, optionally, the token (D-062), `max_age_seconds` (D-063), `poll_seconds` (D-068) and, for the sheets
  the app creates, `folder`, `locale` and `time_zone` (D-065); the LAN PIN
  hash (D-010) is added when it is needed.
  ```toml
  [modules.finger_strength]          # the YAML's `module:` id
  definition = "~/climb-log/modules/finger-strength.yaml"
  workbook = "~/climbing/finger-strength.xlsx"   # or google_sheet = "<ID or URL>" (D-063)

  [backups]                          # optional, these are the defaults
  folder = "~/.local/share/climblog/backups"
  every_minutes = 30
  keep = 30

  [snapshots]                        # optional (D-055)
  folder = "~/.local/share/climblog/snapshots"
  ```

## Data flow
1. **Startup**: load module YAMLs, then each module's data source, then read all tabs as rows
   (`storage/load.py`: cells parsed by type, invalid cells go to a *data issues* list, split
   tabs joined), then compute derived fields (`modules/compute.py`). Analytics build pandas
   DataFrames from these records (M4). Kept in memory and persisted as a **local snapshot** on disk (`04-storage.md` §6), so the app starts instantly and works read-only offline.
2. **Read** requests are served from the snapshot. Analytics run on its DataFrames.
3. **Write** (create/update/delete a record): validate with pydantic, then `storage/write.py`
   checks the values as they would read back, finds the record by its natural key, and writes
   row edits (appends into free rows, updates checked against the row as read, soft deletes)
   through the backend in one save (D-049); then update the cache and recompute that module's
   derived fields.
4. **External change detection**: a local file's `mtime` is checked on every read; while
   `climblog serve` runs, each Google module is read again every `[google] poll_seconds`
   (default 60) in the background, Drive's `modifiedTime` or the copy's age deciding (D-063,
   D-068); a manual "Reload" button comes with the UI. On change, the module's snapshot is
   taken again.

## Backend package layout (planned)
```
backend/climblog/
  main.py              # FastAPI app factory, static SPA mount
  cli.py               # climblog serve | import-legacy | check | backup
  config.py            # app config (TOML): module sources, backups (D-051)
  text.py              # accent-insensitive matching for search (D-024)
  grades.py            # French and gym grades with a numeric index (D-047)
  expr/                # expression language: parse, check, evaluate, functions (D-043)
  modules/
    schema.py          # pydantic models for module YAML (the "meta-schema")
    loader.py          # load + validate YAML, resolve plugins
    checks.py          # checks across the parts of a module, template expansion
    derived.py         # derived fields: load-time check, order, per-record values (D-044)
    compute.py         # whole tables: prev(), parent/children, last() (D-045)
  engine/
    rules.py           # windows (counts over recent records), recommendations (M3)
  storage/
    cells.py           # read cells by field type, data issues (D-046)
    base.py            # Repository protocol, Table, row edits, errors (D-048, D-049)
    load.py            # tabs → records: keys, defaults, joins, data issues (D-048)
    write.py           # records → row edits: add, update, soft delete (D-049)
    check.py           # workbook vs YAML differences for `climblog check` (D-051)
    xlsx.py            # XlsxBackend: read, atomic writes, lock check (D-048, D-049)
    gsheets.py         # GSheetsBackend
    layout.py          # the tabs and columns a module expects (D-052)
    sync.py            # schema sync: check first, then the backend applies the layout (D-052)
    xlsx_sync.py       # xlsx schema sync: tabs, headers, validation, colours, names (D-052)
    backup.py          # rotating copies before writes (D-049)
    snapshot.py        # local snapshot: CachedRepository, offline read-only (D-055)
  analytics/
    timeseries.py  load.py  correlate.py  calendar.py  search.py
  plugins/
    fear_ladder.py     # ladder advancement rule
  api/
    modules.py records.py analytics.py today.py settings.py sources.py
  importers/
    legacy_journal.py legacy_fear.py legacy_shoulder.py
frontend/src/
  api/                 # client.ts, queries.ts (TanStack Query), schema.ts (generated, D-073)
  layout/ pages/ components/ lib/ forms/ widgets/
modules/               # module YAML definitions (user-editable)
  journal.yaml fear-of-falling.yaml shoulder.yaml
```

## Key interfaces

```python
class Repository(Protocol):                               # storage/base.py (D-048, D-049)
    def list_tables(self) -> list[str]: ...
    def read_table(self, table: str) -> Table: ...    # row 2 keys; rows of {key: raw cell}
    def read_kv(self, table: str) -> dict[str, RawCell]: ...       # _meta, _settings
    def last_modified(self) -> datetime: ...
    def apply(self, edits: Sequence[Append | Update]) -> list[int]: ...  # one save, all or none
    def write_kv(self, table: str, values: Mapping[str, RawCell]) -> None: ...
    def exists(self) -> bool: ...
    def sync_schema(self, layout: WorkbookLayout, meta: Mapping[str, RawCell]) -> list[str]: ...
    # additive schema sync in one save; creates the workbook if missing (D-052)
```

Both backends implement it. Analytics and the engine never know which one is in use.

## API sketch
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/modules` | module list + full schemas (fields, forms, views, settings) (D-058: done) |
| GET | `/api/modules/{m}/{entity}` | records (+ derived fields), filters, paging (D-058: done without filters and paging) |
| POST | `/api/modules/{m}/{entity}` | add a record (D-075: done) |
| GET/PATCH/DELETE | `/api/modules/{m}/{entity}/record?<key>` | read, change, soft delete one record (D-075: done) |
| GET | `/api/today?date=` | composed "Today" flow: which forms are due, prefilled values |
| GET | `/api/recommendation?date=` | next-session recommendation + reasons (D-071; D-076: done per module) |
| GET | `/api/modules/{m}/views/{view}` | each widget's data for a module view, computed in Python (D-072) |
| POST | `/api/analytics/query` | generic metric query (metric(s), range, grouping, filters) |
| GET | `/api/analytics/correlations` | correlation matrix / pair with lags |
| GET | `/api/search?q=` | full-text search across text fields |
| GET/PUT | `/api/modules/{m}/settings` | thresholds etc. (stored in the sheet's `_settings`) |
| GET | `/api/issues` | data-validation problems found in the sheets |
| POST | `/api/sources/reload` | force reload |


The read API (D-058, `api/modules.py`, `catalog.py`): the app loads the app config and every
module's YAML on the **first API request** (not when it is built, so it starts without a
config; `climblog serve --config FILE` passes another file). `GET /api/modules` lists each
module with its id, name, version, kind and schema (the YAML as JSON), or the problems of a
YAML that doesn't load; the config's own problems are listed too. `GET /api/modules/{m}/{entity}`
returns `records` (each with `values`, its stored fields, `derived`, the app-computed values, and
`rows`, tab → sheet row), the data `issues` of the entity's tabs, `as_of` and `offline`. It
reads through the module's snapshot (`CachedRepository`, D-055) and computes the derived values
on every request. Errors: an unknown module or entity is 404, a module whose YAML doesn't load
409 with its problems, a workbook that can't be read with no snapshot 503. Dates are ISO
(`2026-10-14`, times `18:30:00`).

The write API (D-075, `api/modules.py` through `RecordWriter`): `POST /api/modules/{m}/{entity}`
with `{"values": {…}}` adds a record; `GET`, `PATCH` (`{"values": {…}, "expected": {…}}`) and
`DELETE` on `/api/modules/{m}/{entity}/record?date=2026-10-30&session_no=2` read, change and
soft delete one, the key given as one query parameter per key field (blank parts take their
defaults, as on read). Values are checked as if typed in the sheet (ISO or day-first dates,
`h:mm` durations, decimal commas). `expected` holds the fields as the client read them: one
that changed since (a hand edit on the phone, another window) is a 409, so a form never
overwrites what it didn't show. A write answers with the record as read back (`values`,
`derived`, `rows`) and `as_of`; a delete with 204. Errors carry `{message, field}`: 404 unknown
module, entity or record; 409 a taken key, a changed record, or a module that doesn't load; 422 an
unknown field or a bad value (`field` names it); 423 a local workbook open in Excel or
LibreOffice; 503 the workbook can't be reached (the snapshot is read-only). Writes to one module
go one at a time. Each request looks at the source once (`CachedRepository.pinned()`).
## Security and privacy
- Binds to localhost. LAN mode (backlog, D-069) would require a PIN.
- Google OAuth token is stored under `~/.config/climblog/` with 0600 permissions and
  minimal scopes: `spreadsheets` and `drive.file` (only the files the app creates) (D-062).
- No telemetry and no external calls except Google APIs when that backend is configured.
