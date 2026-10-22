# SPDX-License-Identifier: GPL-3.0-or-later
"""The `climblog` command line."""

from typing import Annotated

import typer
import uvicorn

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
