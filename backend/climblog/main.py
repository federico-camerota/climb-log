# SPDX-License-Identifier: GPL-3.0-or-later
"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from climblog import __version__, api
from climblog.catalog import Catalog

# Where `make build` puts the frontend (vite.config.ts, D-039).
STATIC_DIR = Path(__file__).parent / "static"

NOT_BUILT_PAGE = """<!doctype html>
<title>climb-log</title>
<p>The frontend is not built. Run <code>make build</code>, or use <code>make dev</code>
for development.</p>
"""


def create_app(static_dir: Path = STATIC_DIR, catalog: Catalog | None = None) -> FastAPI:
    """Build a new app instance (a fresh one per call, so tests stay independent).

    `catalog`: the modules to serve; by default loaded from the app config on the first API
    request (D-058).
    """
    app = FastAPI(title="climb-log", version=__version__)
    app.state.catalog = catalog
    app.include_router(api.router)
    _add_spa(app, static_dir)
    return app


def _add_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the single-page app: bundled assets, root files, and index.html for any other path.

    Registered after the API router, so /api routes always win.
    """
    root = static_dir.resolve()
    index = root / "index.html"
    if (root / "assets").is_dir():
        # Bundled JS/CSS; file names contain a content hash, so browsers may cache them.
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            # Unknown API paths stay JSON errors instead of returning the app.
            raise HTTPException(status_code=404)
        if not index.is_file():
            return HTMLResponse(NOT_BUILT_PAGE, status_code=503)
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            return FileResponse(file)  # e.g. favicon.ico from frontend/public
        # Client-side routes (/explore, /log/...) are handled by React: always send the app.
        # no-cache: the browser revalidates, so a new build is picked up on reload.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
