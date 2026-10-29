# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract: schema sync, on every backend (03 §3, 04 §1, D-052).

A new workbook gets every tab with its two header rows, `_settings` and `_meta`; an existing
one gets what is missing, additively. Backend-specific sync (styles, dropdowns and colour rules,
named ranges, lock files, backups) is tested next to its backend, e.g. `test_sync.py`.
"""

import datetime as dt
from typing import Any

import pytest
from backends import Backend
from conftest import LoadYaml
from workbooks import D20, SYNC_MODULE, existing_tabs

from climblog import __version__
from climblog.modules import Module
from climblog.storage import (
    Repository,
    StorageError,
    SyncRefused,
    check_schema,
    load_data,
    sync_module,
    workbook_layout,
)

CONTRACT = "sync"

TABS = ("Pre", "Post", "_settings", "_meta")


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(SYNC_MODULE)


def headers(backend: Backend, repo: Repository, tab: str) -> list[tuple[Any, Any]]:
    labels, keys = backend.cells(repo, tab)[:2]
    return list(zip(labels, keys, strict=True))


# ---- A new workbook ----


@pytest.fixture
def created(module: Module, backend: Backend) -> Repository:
    repo = backend.new()
    assert sync_module(module, repo) == [
        "created the workbook",
        "created tab 'Pre'",
        "created tab 'Post'",
        "created tab '_settings'",
        "created tab '_meta'",
    ]
    return repo


def test_a_new_workbook_checks_clean_and_loads(module: Module, created: Repository) -> None:
    assert check_schema(module, created) == []
    data = load_data(module, created)
    assert data.issues == []
    assert data.settings == {
        "low_max": 4,
        "start": dt.date(2026, 10, 1),
        "strict": True,
        "motto": "=keep going",
    }
    assert created.list_tables() == list(TABS)


def test_new_tabs_have_both_header_rows(backend: Backend, created: Repository) -> None:
    assert headers(backend, created, "Pre") == [
        ("Date", "date"),
        ("Pain\n(1\u201310 ↓)", "pain"),
        ("Kind", "kind"),
        ("key (auto, hidden)", "auto:_key"),
        ("updated_at\n(app fills)", "updated_at"),
        ("deleted\n(app fills)", "deleted"),
    ]
    assert [key for _, key in headers(backend, created, "Post")] == [
        *("date", "mood", "note", "auto:_key", "updated_at", "deleted"),
    ]


def test_settings_rows_and_meta(backend: Backend, created: Repository) -> None:
    assert backend.cells(created, "_settings") == [
        ("key", "value", "label"),
        ("low_max", 4, "LOW at or below"),
        ("start", dt.datetime(2026, 10, 1), None),
        ("strict", "Yes", None),
        ("motto", "=keep going", None),  # text, not a formula
    ]
    meta = created.read_kv("_meta")
    assert (meta["module"], meta["module_version"], meta["app_version"]) == (
        *("test_sync", 2, __version__),
    )
    assert dt.datetime.fromisoformat(str(meta["schema_synced_at"])) <= dt.datetime.now()


def test_syncing_again_changes_nothing_but_meta(
    module: Module, backend: Backend, created: Repository
) -> None:
    before = [backend.cells(created, name) for name in TABS[:3]]
    assert sync_module(module, created) == []
    assert [backend.cells(created, name) for name in TABS[:3]] == before


def test_a_retired_field_gets_no_column(module: Module, backend: Backend) -> None:
    repo = backend.new()
    sync_module(module, repo)
    assert "old_note" not in [key for _, key in headers(backend, repo, "Post")]


# ---- An existing workbook ----


@pytest.fixture
def existing(backend: Backend) -> Repository:
    return backend.make(existing_tabs())


def test_missing_columns_are_added_at_the_right(
    module: Module, backend: Backend, existing: Repository
) -> None:
    done = sync_module(module, existing)
    assert done == [
        "Pre: added column 'kind'",
        "Pre: added column 'auto:_key'",
        "Pre: added column 'updated_at'",
        "Pre: added column 'deleted'",
        "Post: renamed column 'feel' to 'mood'",
        "Post: added column 'auto:_key'",
        "_settings: added 'strict'",
        "_settings: added 'motto'",
    ]
    assert headers(backend, existing, "Pre") == [
        ("Day", "date"),  # a reworded label is kept
        ("Pain", "pain"),
        ("Status", "auto:status"),
        ("Weather", "weather"),
        ("Kind", "kind"),
        ("key (auto, hidden)", "auto:_key"),
        ("updated_at\n(app fills)", "updated_at"),
        ("deleted\n(app fills)", "deleted"),
    ]
    # Data and the formula of a column the module doesn't know are kept.
    assert backend.cells(existing, "Pre")[2][:4] == (D20, 3, '=IF(B3="","",B3*2)', "sunny")


def test_a_rename_replaces_the_key_and_a_generated_label(
    module: Module, backend: Backend, existing: Repository
) -> None:
    sync_module(module, existing)
    assert headers(backend, existing, "Post")[1] == ("Mood\n(1\u201310)", "mood")  # was the key
    assert backend.cells(existing, "Post")[2][:4] == (D20, 7, "Bene", "vecchia")
    data = load_data(module, existing)
    assert data.entities["session"].records[0]["mood"] == 7


def test_a_reworded_label_survives_a_rename(
    module: Module, backend: Backend, existing: Repository
) -> None:
    backend.edit(existing, "Post", "B1", "How I felt")
    sync_module(module, existing)
    assert backend.cells(existing, "Post")[0][1] == "How I felt"


def test_existing_settings_keep_their_values(
    module: Module, backend: Backend, existing: Repository
) -> None:
    sync_module(module, existing)
    assert backend.cells(existing, "_settings") == [
        ("key", "value"),
        ("start", dt.datetime(2026, 9, 1)),
        ("low_max", 3),
        ("strict", "Yes"),
        ("motto", "=keep going"),
    ]
    assert existing.read_kv("_meta")["module_version"] == 2


def test_the_synced_workbook_checks_clean(module: Module, existing: Repository) -> None:
    sync_module(module, existing)
    assert [str(d) for d in check_schema(module, existing)] == [
        "Pre: column 'weather' is not in the module"
    ]


def test_an_empty_tab_gets_its_headers_from_column_a(module: Module, backend: Backend) -> None:
    repo = backend.make({"Pre": []})
    sync_module(module, repo)
    assert [key for _, key in headers(backend, repo, "Pre")][:2] == ["date", "pain"]


def test_errors_are_not_synced(module: Module, backend: Backend, existing: Repository) -> None:
    backend.edit(existing, "_meta", "B2", "journal")
    before = [backend.cells(existing, name) for name in TABS]
    with pytest.raises(SyncRefused, match="for module 'journal', not 'test_sync'"):
        sync_module(module, existing)
    assert [backend.cells(existing, name) for name in TABS] == before


def test_an_unreadable_settings_tab_is_a_storage_error(module: Module, backend: Backend) -> None:
    repo = backend.make({"_settings": [["name", "number"]]})
    with pytest.raises(StorageError, match="needs the headers 'key' and 'value'"):
        repo.sync_schema(workbook_layout(module), {})
