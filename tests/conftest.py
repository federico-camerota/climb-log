# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared by the tests: write a module YAML snippet and load it; an expression environment."""

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent

import pytest

from climblog.expr import Env, FieldMeta, NameInfo
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


S10 = (1.0, 10.0)
S5 = (1.0, 5.0)

# A fictional record: a few pre/post scales, soreness on two body parts, and plain fields.
ENV = Env(
    names={
        "date": NameInfo("date", field=FieldMeta("date")),
        "session_type": NameInfo(
            "text", choices=("Max hangs", "Finger curls"), field=FieldMeta("choice")
        ),
        "mood": NameInfo("number", scale=S10, field=FieldMeta("scale", "pre")),
        "energy": NameInfo("number", scale=S10, field=FieldMeta("scale", "pre")),
        "fatigue": NameInfo("number", scale=S10, field=FieldMeta("scale", "post")),
        "fun": NameInfo("number", scale=S5, field=FieldMeta("scale", "post")),
        "fingers": NameInfo(
            "number", scale=S10, field=FieldMeta("scale", "body", tags=("soreness",))
        ),
        "elbows": NameInfo(
            "number",
            scale=S10,
            field=FieldMeta("scale", "body", tags=("soreness",), since=dt.date(2026, 10, 20)),
        ),
        "old_skin": NameInfo(
            "number", scale=S10, field=FieldMeta("scale", "body", ("soreness",), retired=True)
        ),
        "minutes": NameInfo("number", field=FieldMeta("duration")),
        "notes": NameInfo("text", field=FieldMeta("text", "post")),
        "red_flag": NameInfo("bool", field=FieldMeta("bool")),
        "status": NameInfo("text"),  # a derived value: not selectable by fields()
    },
    settings={"low_max": "number", "start": "date"},
)
