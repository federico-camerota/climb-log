# SPDX-License-Identifier: GPL-3.0-or-later
"""Change polling for Google modules (04-storage.md §3, §6, D-068).

While `climblog serve` runs, each module on Google Sheets is read again every `[google]
poll_seconds` (60 by default; 0 turns it off), first right at start: its local snapshot follows
what was typed on the phone even when no page asks, and the backend's backup on a seen change
(D-068) keeps a local copy of it. Reading goes through the same `CachedRepository` the API uses;
a module that can't be read is logged and tried again next time. Local workbooks are not polled:
each read already checks the file's modified time.
"""

import asyncio
import logging

from fastapi import FastAPI

from climblog.catalog import Catalog, Entry, served
from climblog.storage import StorageError

log = logging.getLogger(__name__)


def google_entries(catalog: Catalog) -> list[Entry]:
    """The modules on Google Sheets whose YAML loaded."""
    modules = catalog.config.modules
    return [
        entry
        for name, entry in catalog.entries.items()
        if entry.repo is not None and modules[name].google_sheet is not None
    ]


def poll_once(catalog: Catalog) -> None:
    """Read each Google module again (its snapshot is taken again if it changed)."""
    for entry in google_entries(catalog):
        assert entry.repo is not None
        try:
            entry.repo.refresh()
        except StorageError as error:
            log.warning("could not read module %s: %s", entry.name, error)


async def poll(app: FastAPI) -> None:
    """Poll until cancelled (the app's lifespan)."""
    catalog = await asyncio.to_thread(served, app.state)
    interval = catalog.config.google.poll_seconds
    if not interval or not google_entries(catalog):
        return
    while True:
        await asyncio.to_thread(poll_once, catalog)
        await asyncio.sleep(interval)
