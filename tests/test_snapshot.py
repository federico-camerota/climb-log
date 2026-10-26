# SPDX-License-Identifier: GPL-3.0-or-later
"""The local snapshot: saved, loaded, kept fresh, used offline, always safe to delete (D-055)."""

import datetime as dt
import gzip
import json
import os
from pathlib import Path

import pytest
from conftest import LoadYaml
from workbooks import tab, write_workbook

from climblog.modules import Module
from climblog.storage import (
    Append,
    CachedRepository,
    Snapshot,
    SnapshotReadOnly,
    SnapshotRepository,
    Snapshots,
    StorageError,
    TableNotFound,
    XlsxBackend,
    load_data,
)
from climblog.storage.snapshot import take

MODULE = """\
module: test_snapshot
name: Test snapshot
version: 1
kind: journal
settings:
  low_max: {type: number, default: 4}
entities:
  session:
    label: Session
    tab: Sessions
    key: [date]
    fields:
      date: {type: date}
      start: {type: time}
      minutes: {type: duration}
      kg: {type: number}
      ok: {type: bool}
      note: {type: text}
"""

D20 = dt.datetime(2026, 10, 20)
COLUMNS = ["date", "start", "minutes", "kg", "ok", "note"]


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(MODULE)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return write_workbook(
        tmp_path / "test.xlsx",
        {
            "Sessions": tab(
                COLUMNS,
                [D20, dt.time(18, 30), dt.timedelta(minutes=90), 12.5, "Yes", "[ESEMPIO] così"],
                [D20 + dt.timedelta(days=1), None, None, 10, "No", "=non una formula"],
            ),
            "_settings": [["key", "value"], ["low_max", 3]],
            "_meta": [["key", "value"], ["module", "test_snapshot"]],
            "Broken": [["x"], ["a", "a"]],  # a key twice in row 2: left out of the snapshot
        },
    )


@pytest.fixture
def snapshots(tmp_path: Path) -> Snapshots:
    return Snapshots(tmp_path / "snapshots")


def test_a_snapshot_round_trips(path: Path, snapshots: Snapshots) -> None:
    repo = XlsxBackend(path)
    snapshot = take("test_snapshot", repo, clock=lambda: dt.datetime(2026, 10, 26, 9, 0))
    assert sorted(snapshot.tab_names) == ["Sessions", "_meta", "_settings"]
    saved = snapshots.save(snapshot)
    assert saved == snapshots.path("test_snapshot")
    loaded = snapshots.load("test_snapshot")
    assert loaded == snapshot
    assert loaded is not None
    assert loaded.tables["Sessions"] == repo.read_table("Sessions")
    assert loaded.read_at == dt.datetime(2026, 10, 26, 9, 0)
    assert loaded.source_modified == repo.last_modified()


def test_records_load_the_same_from_a_snapshot(
    module: Module, path: Path, snapshots: Snapshots
) -> None:
    repo = XlsxBackend(path)
    offline = SnapshotRepository(take("test_snapshot", repo))
    assert load_data(module, offline) == load_data(module, repo)


def test_the_file_is_private_and_gzipped_json(path: Path, snapshots: Snapshots) -> None:
    file = snapshots.save(take("test_snapshot", XlsxBackend(path)))
    assert os.stat(file).st_mode & 0o777 == 0o600
    assert os.stat(file.parent).st_mode & 0o777 == 0o700
    with gzip.open(file, "rt", encoding="utf-8") as handle:
        doc = json.load(handle)
    assert doc["format"] == 1
    assert doc["tables"]["Sessions"]["rows"][0][1]["start"] == {"t": "18:30:00"}
    assert doc["tables"]["Sessions"]["rows"][0][1]["minutes"] == {"td": 5400.0}


@pytest.mark.parametrize(
    "content",
    [
        b"not gzip",
        gzip.compress(b"{not json"),
        gzip.compress(json.dumps({"format": 0, "module": "test_snapshot"}).encode()),
        gzip.compress(json.dumps({"format": 1, "module": "other"}).encode()),
        gzip.compress(json.dumps({"format": 1, "module": "test_snapshot"}).encode()),
        gzip.compress(
            json.dumps(
                {
                    "format": 1,
                    "module": "test_snapshot",
                    "source_modified": "2026-10-20T00:00:00",
                    "read_at": "2026-10-20T00:00:00",
                    "tables": {
                        "T": {"columns": ["a"], "numbers": {}, "rows": [[3, {"a": {"x": 1}}]]}
                    },
                    "kv": {},
                }
            ).encode()
        ),
        gzip.compress(
            json.dumps(
                {
                    "format": 1,
                    "module": "test_snapshot",
                    "source_modified": "2026-10-20T00:00:00",
                    "read_at": "2026-10-20T00:00:00",
                    "tables": {},
                    "kv": {"_meta": {"a": [1, 2]}},
                }
            ).encode()
        ),
    ],
)
def test_a_damaged_or_old_snapshot_is_ignored(snapshots: Snapshots, content: bytes) -> None:
    snapshots.folder.mkdir()
    snapshots.path("test_snapshot").write_bytes(content)
    assert snapshots.load("test_snapshot") is None


def test_a_missing_snapshot_is_none_and_delete_is_safe(snapshots: Snapshots) -> None:
    assert snapshots.load("test_snapshot") is None
    snapshots.delete("test_snapshot")  # nothing there: no error


def test_a_snapshot_is_read_only(path: Path) -> None:
    offline = SnapshotRepository(take("test_snapshot", XlsxBackend(path)))
    assert offline.exists()
    assert offline.read_kv("_settings") == {"low_max": 3}
    with pytest.raises(TableNotFound):
        offline.read_table("Nope")
    with pytest.raises(TableNotFound):
        offline.read_kv("Nope")
    with pytest.raises(SnapshotReadOnly):
        offline.apply([Append("Sessions", {"kg": 1})])
    with pytest.raises(SnapshotReadOnly):
        offline.write_kv("_settings", {"low_max": 5})
    with pytest.raises(SnapshotReadOnly):
        offline.sync_schema(None, {})  # type: ignore[arg-type]


# ---- Through the snapshot ----


def test_reads_come_from_a_fresh_snapshot(path: Path, snapshots: Snapshots) -> None:
    cached = CachedRepository("test_snapshot", XlsxBackend(path), snapshots)
    assert cached.as_of is None
    assert cached.read_table("Sessions") == XlsxBackend(path).read_table("Sessions")
    first = cached.as_of
    assert first is not None and snapshots.path("test_snapshot").exists()
    # A new session, as the next app start: the snapshot on disk is used, not the workbook.
    again = CachedRepository("test_snapshot", Unreadable(path), snapshots)
    assert again.list_tables() == cached.list_tables()
    assert again.as_of == first and not again.offline


def test_a_changed_workbook_is_read_again(path: Path, snapshots: Snapshots) -> None:
    cached = CachedRepository("test_snapshot", XlsxBackend(path), snapshots)
    cached.read_kv("_settings")
    rows = cached.apply([Append("Sessions", {"date": D20 + dt.timedelta(days=5)})])
    assert rows == [5]
    assert len(cached.read_table("Sessions").rows) == 3
    assert cached.last_modified() == XlsxBackend(path).last_modified()
    cached.write_kv("_settings", {"low_max": 5})
    assert cached.read_kv("_settings") == {"low_max": 5}
    assert snapshots.load("test_snapshot") is not None


def test_offline_the_snapshot_is_used_read_only(path: Path, snapshots: Snapshots) -> None:
    CachedRepository("test_snapshot", XlsxBackend(path), snapshots).refresh()
    path.unlink()  # the workbook out of reach
    cached = CachedRepository("test_snapshot", XlsxBackend(path), snapshots)
    assert len(cached.read_table("Sessions").rows) == 2
    assert cached.offline
    with pytest.raises(SnapshotReadOnly):
        cached.apply([Append("Sessions", {"kg": 1})])
    with pytest.raises(SnapshotReadOnly):
        cached.write_kv("_settings", {"low_max": 5})


def test_offline_without_a_snapshot_is_an_error(path: Path, snapshots: Snapshots) -> None:
    path.unlink()
    with pytest.raises(StorageError, match="workbook not found"):
        CachedRepository("test_snapshot", XlsxBackend(path), snapshots).read_table("Sessions")


def test_sync_goes_to_the_workbook(module: Module, tmp_path: Path, snapshots: Snapshots) -> None:
    from climblog.storage import sync_module

    path = tmp_path / "new.xlsx"
    cached = CachedRepository("test_snapshot", XlsxBackend(path), snapshots)
    assert not cached.exists()
    assert sync_module(module, cached)[0] == "created the workbook"
    assert "Sessions" in cached.list_tables()


class Unreadable(XlsxBackend):
    """A workbook that only tells when it changed (to prove reads use the snapshot)."""

    def list_tables(self) -> list[str]:
        raise AssertionError("read the workbook")


def test_snapshot_equality_ignores_nothing(path: Path) -> None:
    repo = XlsxBackend(path)
    a = take("test_snapshot", repo, clock=lambda: D20)
    b = Snapshot(a.module, a.source_modified, a.read_at, a.tables, a.kv)
    assert a == b


def test_plain_dates_and_the_source_time(snapshots: Snapshots) -> None:
    snapshot = Snapshot(
        "test_snapshot", D20, D20, {}, {"_settings": {"start": dt.date(2026, 10, 1)}}
    )
    snapshots.save(snapshot)
    loaded = snapshots.load("test_snapshot")
    assert loaded == snapshot
    assert SnapshotRepository(snapshot).last_modified() == D20


def test_a_failed_save_leaves_nothing_behind(
    path: Path, snapshots: Snapshots, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = take("test_snapshot", XlsxBackend(path))

    def broken(*args: object, **kwargs: object) -> str:
        raise OSError("disk full")

    monkeypatch.setattr("climblog.storage.snapshot.json.dumps", broken)
    with pytest.raises(OSError, match="disk full"):
        snapshots.save(snapshot)
    assert list(snapshots.folder.iterdir()) == []


def test_formulas_come_from_the_workbook(path: Path, snapshots: Snapshots) -> None:
    offline = SnapshotRepository(take("test_snapshot", XlsxBackend(path)))
    with pytest.raises(StorageError, match="not formulas"):
        offline.read_formulas("Sessions")
    cached = CachedRepository("test_snapshot", XlsxBackend(path), snapshots)
    assert cached.read_formulas("Sessions") == XlsxBackend(path).read_formulas("Sessions")
    cached.refresh()  # a snapshot to fall back on
    path.unlink()
    cached = CachedRepository("test_snapshot", XlsxBackend(path), snapshots)
    cached.refresh()  # offline: the snapshot taken above
    with pytest.raises(SnapshotReadOnly):
        cached.read_formulas("Sessions")
