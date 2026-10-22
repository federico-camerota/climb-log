# SPDX-License-Identifier: GPL-3.0-or-later
"""The `climblog` command line."""

import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from climblog.modules import Module, ModuleError, load_module

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
            load_module(file)
        except ModuleError as error:
            failed = True
            for line in error.lines():
                typer.echo(line, err=True)
        else:
            typer.echo(f"{file}: ok")
    if failed:
        raise typer.Exit(1)


@module_app.command()
def schema() -> None:
    """Print the JSON Schema of module files (committed as modules/module.schema.json)."""
    typer.echo(json.dumps(Module.model_json_schema(), indent=2, ensure_ascii=False))
