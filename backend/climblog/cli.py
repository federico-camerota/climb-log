# SPDX-License-Identifier: GPL-3.0-or-later
"""The `climblog` command line."""

import datetime as dt
import json
import os
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import uvicorn

from climblog import google_auth
from climblog.config import (
    ENV_VAR,
    AppConfig,
    ConfigError,
    GoogleConfig,
    config_path,
    load_config,
)
from climblog.importers.legacy_journal import import_legacy, parity, read_legacy
from climblog.modules import Module, ModuleError, load_module
from climblog.modules.formulas import formula_columns
from climblog.storage import StorageError, check_schema, move_to_google, sync_module
from climblog.storage.drift import drift_differences, find_drift

# Localhost only: LAN access needs the PIN (D-010), which does not exist yet.
HOST = "127.0.0.1"

app = typer.Typer(help="climb-log: log and analyse climbing training.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Keep subcommands explicit (`climblog serve`) even while there is only one."""


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Restart on code changes (development).")] = False,
    config: Annotated[
        Path | None,
        typer.Option(
            help="Config file (default: $CLIMBLOG_CONFIG, ~/.config/climblog/config.toml)."
        ),
    ] = None,
) -> None:
    """Start the web app on http://127.0.0.1:PORT."""
    if config is not None:  # the app is built by uvicorn: it reads the file from the environment
        os.environ[ENV_VAR] = str(config.resolve())
    uvicorn.run("climblog.main:create_app", factory=True, host=HOST, port=port, reload=reload)


@app.command()
def check(
    modules: Annotated[
        list[str] | None, typer.Argument(help="Modules to check (default: all configured).")
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(
            help="Config file (default: $CLIMBLOG_CONFIG, ~/.config/climblog/config.toml)."
        ),
    ] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Create what is missing (schema sync, additive only).")
    ] = False,
) -> None:
    """Compare each module's workbook with its YAML and list the differences.

    Changes nothing unless --apply: then missing tabs and columns are created (the workbook too),
    renames applied, dropdowns rewritten and _meta updated. Columns and data are never deleted.
    """
    try:
        app_config = load_config(config_path(config))
    except ConfigError as error:
        _fail(error.lines())
    names = modules or list(app_config.modules)
    if not names:
        _fail([f"{config_path(config)}: no modules configured"])
    unknown = [name for name in names if name not in app_config.modules]
    if unknown:
        _fail([f"not in the config: {', '.join(unknown)}"])
    failed = False
    for name in names:
        typer.echo(f"{name} ({app_config.modules[name].location})")
        lines, ok = _check_module(app_config, name, apply)
        typer.echo("\n".join(f"  {line}" for line in lines))
        failed |= not ok
    if failed:
        raise typer.Exit(1)


def _check_module(app_config: AppConfig, name: str, apply: bool) -> tuple[list[str], bool]:
    """The lines to print for one module, and whether it is in sync (`info` lines aside)."""
    done: list[str] = []
    try:
        module, repo = app_config.module(name), app_config.repository(name)
        if apply:
            done = [f"synced: {line}" for line in sync_module(module, repo)] or [
                "synced: nothing to add (dropdowns and _meta refreshed)"
            ]
        differences = check_schema(module, repo)
        if not any(d.level == "error" for d in differences):
            differences += drift_differences(find_drift(module, repo))  # D-054
    except ModuleError as error:
        return error.lines(), False
    except (ValueError, StorageError) as error:
        return [*done, f"error: {error}"], False
    if not differences:
        return [*done, "ok"], True
    lines = [f"{d.level}: {d}" for d in differences]
    return [*done, *lines], all(d.level == "info" for d in differences)


def _fail(lines: list[str]) -> NoReturn:
    for line in lines:
        typer.echo(line, err=True)
    raise typer.Exit(1)


@app.command("import-legacy")
def import_legacy_command(
    journal: Annotated[
        Path,
        typer.Option(
            help="The legacy Climbing_Journal.xlsx (only read).", exists=True, dir_okay=False
        ),
    ],
    module: Annotated[str, typer.Option(help="The journal module in the app config.")] = "journal",
    config: Annotated[
        Path | None,
        typer.Option(
            help="Config file (default: $CLIMBLOG_CONFIG, ~/.config/climblog/config.toml)."
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Read and compare only; write nothing.")
    ] = False,
) -> None:
    """Import a legacy journal into the module's (new) workbook, then compare the values the
    legacy sheets computed with the app's (D-061). Runs locally; never in CI."""
    try:
        app_config = load_config(config_path(config))
    except ConfigError as error:
        _fail(error.lines())
    if module not in app_config.modules:
        _fail([f"not in the config: {module}"])
    try:
        definition = app_config.module(module)
        legacy = read_legacy(journal, definition)
        if not dry_run:
            report = import_legacy(journal, definition, app_config.repository(module))
            typer.echo(f"imported into {app_config.modules[module].location}")
            typer.echo(
                f"  {report.counts['session']} sessions, {report.counts['rest_day']} rest days"
            )
    except (ModuleError, ValueError, StorageError) as error:
        _fail([f"error: {error}"])
    if dry_run:
        typer.echo(f"read {legacy.count('session')} sessions, {legacy.count('rest_day')} rest days")
    typer.echo(f"  settings: {legacy.settings}")
    for line in [*legacy.skipped, *legacy.unread]:
        typer.echo(f"  {line}")
    if not legacy.computed:
        typer.echo(
            "parity: the legacy workbook holds no computed values; open it in Excel or "
            "LibreOffice, save it, and run with --dry-run to compare"
        )
        return
    typer.echo("parity (values the legacy sheets computed vs the app's):")
    failed = False
    for column in parity(legacy, definition):
        status = "ok" if not column.mismatches else "DIFFERS"
        typer.echo(
            f"  {status}: {column.entity}.{column.field}: {column.matching}/{column.compared} match"
        )
        if column.mismatches and column.known:
            typer.echo(f"    known difference: {column.known}")
        elif column.mismatches:
            failed = True
        for day, sheet_value, app_value in column.mismatches[:5]:
            typer.echo(f"    {day}: sheet {sheet_value!r}, app {app_value!r}")
    if failed:
        raise typer.Exit(1)


module_app = typer.Typer(
    help="Module definition files (YAML), and where modules live.", no_args_is_help=True
)
app.add_typer(module_app, name="module")


@module_app.command()
def validate(
    files: Annotated[
        list[Path], typer.Argument(help="Module YAML files.", exists=True, dir_okay=False)
    ],
) -> None:
    """Check module files and list every problem with its line."""
    failed = False
    for file in files:
        try:
            module = load_module(file)
        except ModuleError as error:
            failed = True
            for line in error.lines():
                typer.echo(line, err=True)
        else:
            typer.echo(f"{file}: ok")
            _, app_only = formula_columns(module)
            for entry in app_only:  # derived fields without a sheet column (D-053)
                typer.echo(f"  note: {entry}")
    if failed:
        raise typer.Exit(1)


@module_app.command()
def create(
    definition: Annotated[
        Path, typer.Argument(help="The module's YAML.", exists=True, dir_okay=False)
    ],
    google: Annotated[bool, typer.Option("--google", help="Make it a Google Sheet.")] = False,
    config: Annotated[
        Path | None,
        typer.Option(
            help="Config file (default: $CLIMBLOG_CONFIG, ~/.config/climblog/config.toml)."
        ),
    ] = None,
) -> None:
    """Make a new Google Sheet for a module, synced with its YAML, and print its config lines.

    A local workbook needs no command: name it in the config and run `climblog check --apply`.
    """
    if not google:
        _fail(["only --google: a local workbook is made by `climblog check MODULE --apply`"])
    try:
        app_config = load_config(config_path(config))
        module = load_module(definition)
    except ConfigError as error:
        _fail(error.lines())
    except ModuleError as error:
        _fail(error.lines())
    if module.module in app_config.modules:
        where = app_config.modules[module.module].location
        _fail([f"module '{module.module}' is already in the config ({where})"])
    repo = app_config.google_sheet(None)
    try:
        sync_module(module, repo)
    except StorageError as error:
        _fail([f"error: {error}"])
    assert repo.spreadsheet_id is not None
    folder = app_config.google.folder
    typer.echo(f"created Google Sheet '{module.name}' in your Drive folder '{folder}':")
    typer.echo(f"  {_sheet_url(repo.spreadsheet_id)}")
    typer.echo("Add this to the config:")
    typer.echo(_config_block(module.module, definition.resolve(), repo.spreadsheet_id))


@module_app.command()
def move(
    module: Annotated[str, typer.Argument(help="The module, as named in the config.")],
    to_google: Annotated[
        bool, typer.Option("--to-google", help="Move it to a new Google Sheet.")
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option(
            help="Config file (default: $CLIMBLOG_CONFIG, ~/.config/climblog/config.toml)."
        ),
    ] = None,
) -> None:
    """Copy a module's local workbook into a new Google Sheet and check the copy (D-067).

    The workbook is only read. When the check passes, put the printed `google_sheet` line in
    the config instead of `workbook`; until then the module stays local.
    """
    if not to_google:
        _fail(["only --to-google: a module moves from a local workbook to Google Sheets"])
    try:
        app_config = load_config(config_path(config))
    except ConfigError as error:
        _fail(error.lines())
    if module not in app_config.modules:
        _fail([f"not in the config: {module}"])
    settings = app_config.modules[module]
    if settings.workbook is None:
        _fail([f"{module} is already on Google ({settings.location})"])
    google = app_config.google_sheet(None)
    typer.echo(f"{module}: copying {settings.workbook} to a new Google Sheet")
    try:
        report = move_to_google(app_config.module(module), app_config.repository(module), google)
    except (ModuleError, ValueError, StorageError) as error:
        lines = error.lines() if isinstance(error, ModuleError) else [f"error: {error}"]
        _fail(lines)
    typer.echo(f"  created {google.label}: {_sheet_url(report.spreadsheet_id)}")
    copied = ", ".join(f"{tab} {rows}" for tab, rows in report.copied.items())
    typer.echo(f"  rows copied: {copied}")
    for line in report.not_copied:
        typer.echo(f"  not copied (not in the module): {line}")
    if report.differences:
        typer.echo("  the copy differs; the sheet is kept for a look, the module stays local:")
        for line in report.differences:
            typer.echo(f"    {line}")
        raise typer.Exit(1)
    typer.echo("  checked: the same records, settings and data issues; formulas give the app's")
    typer.echo(f"Replace `workbook = ...` under [modules.{module}] in the config with:")
    typer.echo(f'google_sheet = "{report.spreadsheet_id}"')


def _sheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def _config_block(module: str, definition: Path, spreadsheet_id: str) -> str:
    return f'[modules.{module}]\ndefinition = "{definition}"\ngoogle_sheet = "{spreadsheet_id}"'


@module_app.command()
def schema() -> None:
    """Print the JSON Schema of module files (committed as modules/module.schema.json)."""
    typer.echo(json.dumps(Module.model_json_schema(), indent=2, ensure_ascii=False))


google_app = typer.Typer(help="Log in to Google Sheets (D-062).", no_args_is_help=True)
app.add_typer(google_app, name="google")

ConfigOption = Annotated[
    Path | None,
    typer.Option(help="Config file (default: $CLIMBLOG_CONFIG, ~/.config/climblog/config.toml)."),
]


def _google_config(config: Path | None) -> GoogleConfig:
    try:
        return load_config(config_path(config)).google
    except ConfigError as error:
        _fail(error.lines())


@google_app.command()
def login(
    config: ConfigOption = None,
    browser: Annotated[
        bool, typer.Option(help="Open the browser (--no-browser: print the address to open).")
    ] = True,
) -> None:
    """Give the app access to Google Sheets: opens Google's consent page, saves the token."""
    try:
        path = google_auth.login(_google_config(config), open_browser=browser)
    except google_auth.GoogleAuthError as error:
        _fail([f"error: {error}"])
    typer.echo(f"logged in; token saved in {path} (readable by you only)")


@google_app.command()
def status(config: ConfigOption = None) -> None:
    """Check the saved login with Google (refreshes it once). Exits 1 when it can't be used."""
    google = _google_config(config)
    try:
        credentials = google_auth.load_credentials(google, refresh=True)
    except google_auth.GoogleAuthError as error:
        _fail([f"{google.token_file()}: {error}"])
    typer.echo(f"logged in ({google.token_file()})")
    typer.echo(f"  scopes: {', '.join(credentials.scopes or ())}")
    if credentials.expiry is not None:  # naive UTC in google-auth
        until = credentials.expiry.replace(tzinfo=dt.UTC).astimezone()
        typer.echo(f"  access token valid until {until:%H:%M} (renewed automatically)")


@google_app.command()
def logout(config: ConfigOption = None) -> None:
    """Revoke the app's access with Google and delete the saved token."""
    google = _google_config(config)
    revoked = google_auth.logout(google)
    if revoked is None:
        typer.echo("not logged in: nothing to do")
    elif revoked:
        typer.echo(f"access revoked; {google.token_file()} deleted")
    else:
        typer.echo(
            f"{google.token_file()} deleted, but Google did not confirm the revoke: remove "
            "climb-log at https://myaccount.google.com/permissions"
        )
