# SPDX-License-Identifier: GPL-3.0-or-later
"""The `climblog` command line."""

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import uvicorn

from climblog.config import AppConfig, ConfigError, config_path, load_config
from climblog.importers.legacy_journal import import_legacy, parity, read_legacy
from climblog.modules import Module, ModuleError, load_module
from climblog.modules.formulas import formula_columns
from climblog.storage import StorageError, check_schema, sync_module
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
) -> None:
    """Start the web app on http://127.0.0.1:PORT."""
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
        typer.echo(f"{name} ({app_config.modules[name].workbook})")
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
            typer.echo(f"imported into {app_config.modules[module].workbook}")
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


module_app = typer.Typer(help="Check module definition files (YAML).", no_args_is_help=True)
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
def schema() -> None:
    """Print the JSON Schema of module files (committed as modules/module.schema.json)."""
    typer.echo(json.dumps(Module.model_json_schema(), indent=2, ensure_ascii=False))
