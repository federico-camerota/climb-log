# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures shared by the module tests: write a YAML snippet to a temp file and load it."""

from collections.abc import Callable
from pathlib import Path
from textwrap import dedent

import pytest

from climblog.modules import Module, ModuleError, load_module

WriteYaml = Callable[[str], Path]
LoadYaml = Callable[[str], Module]
Problems = Callable[[str], list[str]]


@pytest.fixture
def write(tmp_path: Path) -> WriteYaml:
    def write(text: str) -> Path:
        file = tmp_path / "test.yaml"
        file.write_text(dedent(text), encoding="utf-8")
        return file

    return write


@pytest.fixture
def load(write: WriteYaml) -> LoadYaml:
    return lambda text: load_module(write(text))


@pytest.fixture
def problems(load: LoadYaml) -> Problems:
    """The error lines (`line:column path: message`) of a module that must fail to load."""

    def problems(text: str) -> list[str]:
        with pytest.raises(ModuleError) as error:
            load(text)
        return [line.removeprefix(f"{error.value.file}:") for line in error.value.lines()]

    return problems
