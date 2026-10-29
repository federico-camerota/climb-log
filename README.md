# climb-log

[![CI](https://github.com/federico-camerota/climb-log/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/federico-camerota/climb-log/actions/workflows/ci.yml)

A local web app for logging and analysing climbing training. The data stays in spreadsheets
you own (local `.xlsx` or Google Sheets) and can still edit by hand; the app adds guided
logging forms, interactive charts, cross-module analysis and a "next session" recommendation.
What is tracked is defined in config files (module YAMLs), not in code.

**Status: early development, not usable yet.** The skeleton (backend, frontend, tooling, CI)
is in place; the module framework and spreadsheet storage come next. See the
[roadmap](design/07-roadmap.md).

## Quick start

Prerequisites (Linux):
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 from `.python-version`)
- Node 22 (`.node-version`; e.g. via [fnm](https://github.com/Schniz/fnm)) and
  [pnpm](https://pnpm.io/)
- `make`, and git ≥ 2.31 to run the hooks on every file

```sh
make install   # Python and frontend dependencies from the lock files, plus the git hooks
make dev       # backend + Vite with hot reload: open http://127.0.0.1:5173
```

To run the built app the way it will be used:

```sh
make build
uv run climblog serve   # http://127.0.0.1:8000 (--config FILE for another app config)
```

`make test` runs the tests, `make lint` the format, lint and type checks, and `make help`
lists every target.

## Configure

The app finds each module's workbook through `~/.config/climblog/config.toml` (another file
with `--config FILE` or `CLIMBLOG_CONFIG`). It holds paths only and stays out of the repo:

```toml
[modules.finger_strength]
definition = "~/climb-log/modules/finger-strength.yaml"
workbook = "~/climbing/finger-strength.xlsx"

[backups]          # optional
folder = "~/climbing/backups"

[snapshots]        # optional: the app's local copy of the data, safe to delete
folder = "~/climbing/snapshots"
```

`uv run climblog check` then lists, for every module, where the workbook and the YAML
disagree (formulas changed by hand included), without changing anything; `uv run climblog
check --apply` creates what is missing (the workbook too), puts changed formulas back, and
never deletes columns or data. All options are in
[`design/02-architecture.md`](design/02-architecture.md#runtime).

## Import your legacy journal

```sh
uv run climblog import-legacy --journal Climbing_Journal.xlsx --dry-run   # read and compare only
uv run climblog import-legacy --journal Climbing_Journal.xlsx             # into a new journal workbook
```
The legacy file is only read. The report lists what was imported or skipped and compares the
values your legacy sheets computed with the app's.

## Connect Google Sheets

A module can live in a Google Sheet instead of a local workbook (M2, in progress). The app uses
its own OAuth client in a Google Cloud project of yours; setting it up takes a few minutes, once:

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and
   enable the **Google Sheets API** and the **Google Drive API**.
2. Under *Google Auth Platform*, on *Branding*, set the app name and your email, and the app
   links Google asks for before publishing: home page
   `https://github.com/federico-camerota/climb-log`, privacy policy
   `https://github.com/federico-camerota/climb-log/blob/main/PRIVACY.md` (or your fork's), and
   `github.com` as an authorized domain. Add no logo and no scopes under *Data access*: both
   would make Google ask for verification (the app asks for its scopes at login). On
   *Audience*, choose **External**, then **publish the app** (*In production*): while it is in
   *Testing*, Google ends the login after 7 days. No verification is needed for your own use;
   at login Google warns that the app isn't verified, and you continue.
3. Under *Clients*, create an OAuth client of type **Desktop app** and download its JSON.
   Keep it outside the repository, e.g. `~/.config/climblog/client_secret.json`.
4. Name it in the config, and log in (your browser opens Google's consent page):

```toml
[google]
client_secret = "~/.config/climblog/client_secret.json"
# token = "~/.config/climblog/google-token.json"   # the default
```

```sh
uv run climblog google login    # --no-browser prints the address to open instead
uv run climblog google status   # checks the login with Google
uv run climblog google logout   # revokes the access and deletes the token
```

The app asks for Google Sheets and for the Drive files it creates itself, nothing else. The
token is saved readable by you only, and is never printed or logged.

A module then names its sheet instead of a workbook (the ID, or the URL as the browser shows
it). Reading works today; writing, schema sync and creating the module's sheet are coming
(M2), and until the app creates the sheet itself Google won't let it see when the sheet changes.

```toml
[modules.journal]
definition = "~/climb-log/modules/journal.yaml"
google_sheet = "https://docs.google.com/spreadsheets/d/<ID>/edit"
```

## Documentation

The design lives in [`design/`](design/README.md): goals, architecture, the module framework,
storage, analytics, UI, the [roadmap](design/07-roadmap.md) and the
[decision log](design/decisions.md). How the project is developed is in
[`design/08-workflow.md`](design/08-workflow.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
Changes are listed in the [changelog](CHANGELOG.md).

## Data and privacy

Training notes are personal data and this repository is public, so it contains **fictional
data only**: test fixtures and mock-up workbooks are generated by scripts in the repo. Real
journals, backups and credentials are git-ignored, and a pre-commit check rejects spreadsheets
outside the folders for fictional data.

How the app handles your data, Google data included, is in [PRIVACY.md](PRIVACY.md).

## License

[GPL-3.0-or-later](LICENSE).
