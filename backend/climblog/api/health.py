# SPDX-License-Identifier: GPL-3.0-or-later
"""Liveness check: confirms the server is up and reports which version is running."""

from fastapi import APIRouter
from pydantic import BaseModel

from climblog import __version__

router = APIRouter()


class Health(BaseModel):
    status: str
    version: str


@router.get("/health")
def get_health() -> Health:
    return Health(status="ok", version=__version__)
