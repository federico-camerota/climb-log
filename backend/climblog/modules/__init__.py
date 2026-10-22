# SPDX-License-Identifier: GPL-3.0-or-later
"""Module definitions: the YAML meta-schema and its loader (design/03-module-framework.md)."""

from climblog.modules.loader import ModuleError, load_module
from climblog.modules.schema import Module, Problem

__all__ = ["Module", "ModuleError", "Problem", "load_module"]
