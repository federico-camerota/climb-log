# 02 · Architecture

## Overview

```
 Browser (desktop / phone on LAN)
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
| Google | Google Sheets API v4 via `gspread` + `google-auth-oauthlib` | mature, batch reads |
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
- `climblog serve --lan`: binds `0.0.0.0` for phone access and **requires a PIN/token**
  (set on first run) because the API can write data.
- Dev mode (`make dev`): Vite dev server on `127.0.0.1:5173` (hot reload) proxying `/api` to
  `climblog serve --reload` on `:8000`; Ctrl-C stops both.
- App config: `~/.config/climblog/config.toml` holds the data sources per module, the
  Google token path, the backup location and the LAN PIN hash. It contains no training data.

## Data flow
1. **Startup**: load module YAMLs, then each module's data source, then read all tabs into
   pandas DataFrames, then validate (invalid cells go to a *data issues* list), then compute
   derived fields. Kept in memory and persisted as a **local snapshot** on disk (`04-storage.md` §6), so the app starts instantly and works read-only offline.
2. **Read** requests are served from the snapshot. Analytics run on its DataFrames.
3. **Write** (create/update/delete a record): validate with pydantic, write through to the
   backend (row append or row update by `id`), then update the cache and recompute that
   module's derived fields.
4. **External change detection**: local file `mtime` polling; Google via Drive
   `modifiedTime` polling (e.g. every 30–60 s while the UI is open) plus a manual
   "Reload" button. On change, reload the affected module.

## Backend package layout (planned)
```
backend/climblog/
  main.py              # FastAPI app factory, static SPA mount
  cli.py               # climblog serve | import-legacy | check | backup
  config.py            # app config (TOML)
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
    base.py            # Repository protocol, TableSchema, errors
    xlsx.py            # XlsxBackend
    gsheets.py         # GSheetsBackend
    sync.py            # header/schema sync, data validation, styling
    backup.py
  analytics/
    timeseries.py  load.py  correlate.py  calendar.py  search.py
  plugins/
    fear_ladder.py     # ladder advancement rule
  api/
    modules.py records.py analytics.py today.py settings.py sources.py
  importers/
    legacy_journal.py legacy_fear.py legacy_shoulder.py
frontend/src/
  api/ forms/ widgets/ pages/ lib/
modules/               # module YAML definitions (user-editable)
  journal.yaml fear-of-falling.yaml shoulder.yaml
```

## Key interfaces

```python
class Repository(Protocol):
    def list_tables(self) -> list[str]: ...
    def read_table(self, table: str) -> pd.DataFrame: ...          # header row → columns
    def append_rows(self, table: str, rows: list[dict]) -> None: ...
    def update_row(self, table: str, id: str, values: dict) -> None: ...
    def delete_row(self, table: str, id: str) -> None: ...         # soft delete (see storage)
    def ensure_table(self, table: str, columns: list[ColumnSpec]) -> SyncReport: ...
    def read_kv(self, table: str) -> dict[str, str]: ...           # _meta, _settings
    def write_kv(self, table: str, values: dict[str, str]) -> None: ...
    def last_modified(self) -> datetime: ...
```

Both backends implement it. Analytics and the engine never know which one is in use.

## API sketch
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/modules` | module list + full schemas (fields, forms, views, settings) |
| GET | `/api/modules/{m}/{entity}` | records (+ derived fields), filters, paging |
| POST/PATCH/DELETE | `/api/modules/{m}/{entity}[/{id}]` | write records |
| GET | `/api/today?date=` | composed "Today" flow: which forms are due, prefilled values |
| GET | `/api/recommendation?date=` | next-session recommendation + reasons |
| POST | `/api/analytics/query` | generic metric query (metric(s), range, grouping, filters) |
| GET | `/api/analytics/correlations` | correlation matrix / pair with lags |
| GET | `/api/search?q=` | full-text search across text fields |
| GET/PUT | `/api/modules/{m}/settings` | thresholds etc. (stored in the sheet's `_settings`) |
| GET | `/api/issues` | data-validation problems found in the sheets |
| POST | `/api/sources/reload` | force reload |

## Security and privacy
- Binds to localhost by default. LAN mode requires a PIN.
- Google OAuth token is stored under `~/.config/climblog/` with 0600 permissions and
  minimal scopes (`spreadsheets`, plus `drive.metadata.readonly` for modifiedTime, or
  `drive.file` if we create the sheets).
- No telemetry and no external calls except Google APIs when that backend is configured.
