# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared by the tests: write a module YAML snippet and load it; an expression environment;
the storage backend each contract test runs on."""

import datetime as dt
from collections.abc import Callable, Iterator
from pathlib import Path
from textwrap import dedent

import pytest
from backends import BACKENDS, Backend, harness

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


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Backend]:
    """Each storage backend in turn, for the contract tests (`backends.py`); the test module's
    `CONTRACT` is skipped on a backend that doesn't meet it yet."""
    name: str = request.param
    chosen = harness(name, tmp_path)
    contract: str = request.module.CONTRACT
    if contract in chosen.pending:
        pytest.skip(f"{name}: the {contract} contract comes with {chosen.pending[contract]}")
    try:
        yield chosen
    finally:
        chosen.close()


S10 = (1.0, 10.0)
S5 = (1.0, 5.0)
LEVELS = ("GOOD", "WATCH", "LOW")
REFLECT = ("GOOD", "WORTH NOTING", "NEEDS ATTENTION")

# A fictional record: a few pre/post scales, soreness on two body parts, and plain fields.
ENV = Env(
    names={
        "date": NameInfo("date", field=FieldMeta("date")),
        "session_type": NameInfo(
            "text", choices=("Max hangs", "Finger curls"), field=FieldMeta("choice")
        ),
        # higher is better: mood, energy, fun; lower is better (↓): fatigue and soreness
        "mood": NameInfo("number", scale=S10, field=FieldMeta("scale", "pre"), lower_better=False),
        "energy": NameInfo(
            "number", scale=S10, field=FieldMeta("scale", "pre"), lower_better=False
        ),
        "fatigue": NameInfo(
            "number", scale=S10, field=FieldMeta("scale", "post"), lower_better=True
        ),
        "fun": NameInfo("number", scale=S5, field=FieldMeta("scale", "post"), lower_better=False),
        "fingers": NameInfo(
            "number",
            scale=S10,
            field=FieldMeta("scale", "body", tags=("soreness",)),
            lower_better=True,
        ),
        "elbows": NameInfo(
            "number",
            scale=S10,
            field=FieldMeta("scale", "body", tags=("soreness",), since=dt.date(2026, 10, 20)),
            lower_better=True,
        ),
        "old_skin": NameInfo(
            "number",
            scale=S10,
            field=FieldMeta("scale", "body", ("soreness",), retired=True),
            lower_better=True,
        ),
        "minutes": NameInfo("number", field=FieldMeta("duration")),
        "notes": NameInfo("text", field=FieldMeta("text", "post")),
        "red_flag": NameInfo("bool", field=FieldMeta("bool")),
        "status": NameInfo("text"),  # a derived value: not selectable by fields()
        # derived statuses (bands:/when: results, D-044)
        "pre_status": NameInfo("text", choices=LEVELS, levels=LEVELS),
        "post_status": NameInfo("text", choices=LEVELS, levels=LEVELS),
        "reflect": NameInfo("text", choices=REFLECT, levels=REFLECT),
    },
    settings={"low_max": "number", "start": "date"},
    # Other records (D-045): this record is a child of a block; it has sets; there are rest days.
    parent={
        "date": NameInfo("date", field=FieldMeta("date")),
        "goal": NameInfo("text", choices=("Power", "Endurance"), field=FieldMeta("choice")),
    },
    children={
        "set": {
            "kg": NameInfo("number", field=FieldMeta("number")),
            "rpe": NameInfo("number", scale=S10, field=FieldMeta("scale"), lower_better=False),
            "volume": NameInfo("number"),  # a derived value of the set
        }
    },
    entities={
        "rest_day": {
            "date": NameInfo("date", field=FieldMeta("date")),
            "sleep": NameInfo("number", scale=S10, field=FieldMeta("scale"), lower_better=False),
        }
    },
)
