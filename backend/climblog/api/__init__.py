# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP API, mounted under /api."""

from fastapi import APIRouter

from climblog.api import health, modules

router = APIRouter(prefix="/api")
router.include_router(health.router)
router.include_router(modules.router)
