# SPDX-License-Identifier: GPL-3.0-or-later
"""Differences between a workbook and its module YAML (03 §3, D-051)."""

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from conftest import LoadYaml
from workbooks import tab, write_workbook

from climblog.modules import Module, load_module
from climblog.storage import Difference, StorageError, XlsxBackend, check_schema

# A fictional module: a session split over two tabs, with a renamed and a retired field.
MODULE = """\
module: test_check
name: Test check
version: 2
kind: journal
settings:
  low_max: {type: number, default: 4}
  watch_max: {type: number, default: 6}
entities:
  session:
    label: Session
    key: [date]
    anchor_tab: Pre
    sections:
      pre: {label: Before, tab: Pre}
      post: {label: After, tab: Post}
    fields:
      date: {type: date, required: true, section: "*"}
      sleep: {type: integer, section: pre}
      mood: {type: integer, section: pre, renamed_from: feel}
      rpe: {type: integer, section: post}
      old_note: {type: text, section: post, retired: true}
"""

SYSTEM = ["updated_at", "deleted"]
META: list[list[Any]] = [["key", "value"], ["module", "test_check"], ["module_version", 2]]
SETTINGS: list[list[Any]] = [["key", "value"], ["low_max", 4], ["watch_max", 6]]


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(MODULE)


def in_sync() -> dict[str, list[Sequence[Any]]]:
    return {
        "Pre": tab(["date", "sleep", "mood", "auto:readiness", *SYSTEM]),
        "Post": tab(["date", "rpe", "old_note", *SYSTEM]),
        "_settings": [*SETTINGS],
        "_meta": [*META],
    }


def check(
    module: Module, tmp_path: Path, tabs: Mapping[str, Sequence[Sequence[Any]]]
) -> list[tuple[str, str]]:
    repo = XlsxBackend(write_workbook(tmp_path / "test.xlsx", tabs))
    return [(d.level, str(d)) for d in check_schema(module, repo)]


def test_a_workbook_in_sync_has_no_differences(module: Module, tmp_path: Path) -> None:
    assert check(module, tmp_path, in_sync()) == []


def test_a_retired_field_needs_no_column(module: Module, tmp_path: Path) -> None:
    tabs = in_sync() | {"Post": tab(["date", "rpe", *SYSTEM])}
    assert check(module, tmp_path, tabs) == []


def test_missing_tabs(module: Module, tmp_path: Path) -> None:
    tabs = in_sync()
    for name in ("Post", "_meta", "_settings"):
        del tabs[name]
    assert check(module, tmp_path, tabs) == [
        ("sync", "_meta: the tab is missing: never synced"),
        ("sync", "Post: the tab is missing"),
        ("sync", "_settings: the tab is missing"),
    ]


def test_missing_and_unknown_columns(module: Module, tmp_path: Path) -> None:
    tabs = in_sync() | {
        "Pre": tab(["date", "mood", "auto:other", "weather", "deleted"]),
        "Post": tab(["rpe", "old_note", "a_note", *SYSTEM]),
    }
    differences = [
        ("sync", "Pre: column 'sleep' is missing"),
        ("sync", "Pre: column 'updated_at' is missing"),
        ("info", "Pre: column 'weather' is not in the module"),
        ("sync", "Post: column 'date' is missing"),
        ("info", "Post: column 'a_note' is not in the module"),
    ]
    assert check(module, tmp_path, tabs) == differences


def test_a_renamed_column_is_reported_once(module: Module, tmp_path: Path) -> None:
    tabs = in_sync() | {"Pre": tab(["date", "sleep", "feel", *SYSTEM])}
    assert check(module, tmp_path, tabs) == [("sync", "Pre: column 'feel' is to be renamed 'mood'")]
    tabs = in_sync() | {"Pre": tab(["date", "sleep", "feel", "mood", *SYSTEM])}
    assert check(module, tmp_path, tabs) == [
        ("error", "Pre: columns 'feel' and 'mood' (renamed): keep one")
    ]


def test_meta_version(module: Module, tmp_path: Path) -> None:
    def meta(version: Any) -> list[tuple[str, str]]:
        tabs = in_sync() | {"_meta": [*META[:2], ["module_version", version]]}
        return check(module, tmp_path, tabs)

    assert meta(2.0) == []
    assert meta(" 2 ") == []
    assert meta(1) == [("sync", "_meta: synced with v1, the YAML is v2")]
    assert meta(3) == [
        ("error", "_meta: synced with v3, newer than the YAML (v2): an old YAML file?")
    ]
    assert meta(None) == [("sync", "_meta: no 'module_version' value")]
    assert meta("two") == [("error", "_meta: 'module_version' is not a number: two")]
    assert meta(1.5) == [("error", "_meta: 'module_version' is not a number: 1.5")]


def test_meta_module(module: Module, tmp_path: Path) -> None:
    tabs = in_sync() | {"_meta": [META[0], ["module", "journal"], META[2]]}
    assert check(module, tmp_path, tabs) == [
        ("error", "_meta: this workbook is for module 'journal', not 'test_check'")
    ]
    tabs = in_sync() | {"_meta": [META[0], META[2]]}
    assert check(module, tmp_path, tabs) == [("sync", "_meta: no 'module' value")]


def test_settings_without_a_row(module: Module, tmp_path: Path) -> None:
    tabs = in_sync() | {"_settings": SETTINGS[:2]}
    assert check(module, tmp_path, tabs) == [
        ("info", "_settings: no row for 'watch_max': the default is used")
    ]


def test_unreadable_headers_are_errors(module: Module, tmp_path: Path) -> None:
    tabs = in_sync() | {
        "Pre": tab(["date", "sleep", "sleep"]),
        "_meta": [["k", "v"]],
        "_settings": [["name"]],
    }
    assert check(module, tmp_path, tabs) == [
        ("error", "_meta: tab '_meta' needs the headers 'key' and 'value' in row 1"),
        ("error", "Pre: tab 'Pre': column key 'sleep' is in row 2 twice (B2 and C2)"),
        ("error", "_settings: tab '_settings' needs the headers 'key' and 'value' in row 1"),
    ]


def test_reference_template_columns_are_not_unknown(load: LoadYaml, tmp_path: Path) -> None:
    module = load(
        """\
        module: test_check
        name: Test check
        version: 2
        kind: program
        entities:
          quiz:
            label: Quiz
            tab: Quiz
            key: [date]
            fields:
              date: {type: date}
              q_: {template_from_reference: questions, type: integer}
        """
    )
    tabs = in_sync() | {"Quiz": tab(["date", "q1", "q2", *SYSTEM])}
    for name in ("Pre", "Post"):
        del tabs[name]
    assert check(module, tmp_path, tabs) == []


def test_a_missing_workbook_raises(module: Module, tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="workbook not found"):
        check_schema(module, XlsxBackend(tmp_path / "none.xlsx"))


def test_difference_without_a_tab() -> None:
    assert str(Difference("error", None, None, "broken")) == "broken"


def test_the_finger_strength_mockup_is_in_sync(tmp_path: Path) -> None:
    module = load_module(Path("design/modules/finger-strength.yaml"))
    path = shutil.copy("design/mockups/mockup-finger-strength.xlsx", tmp_path)
    assert check_schema(module, XlsxBackend(Path(path))) == []
