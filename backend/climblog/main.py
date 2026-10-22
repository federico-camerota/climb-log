# SPDX-License-Identifier: GPL-3.0-or-later
"""FastAPI application factory."""

from fastapi import FastAPI

from climblog import __version__, api


def create_app() -> FastAPI:
    """Build a new app instance (a fresh one per call, so tests stay independent)."""
    app = FastAPI(title="climb-log", version=__version__)
    app.include_router(api.router)
    return app
