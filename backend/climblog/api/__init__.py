# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP API, mounted under /api."""

from fastapi import APIRouter

from climblog.api import (
    correlation,
    health,
    metrics,
    modules,
    recommendation,
    reference,
    today,
    views,
)

router = APIRouter(prefix="/api")
router.include_router(correlation.router)
router.include_router(health.router)
router.include_router(metrics.router)
# before modules: `/modules/{m}/reference` is not an entity
router.include_router(reference.router)
router.include_router(modules.router)
router.include_router(recommendation.router)
router.include_router(today.router)
router.include_router(views.router)
