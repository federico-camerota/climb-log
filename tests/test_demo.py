# SPDX-License-Identifier: GPL-3.0-or-later
"""The fictional demo set (scripts/demo.py, D-108): every module loads clean, matches its YAML,
and the fields with a `since:` have values only from that day on."""

import datetime as dt
from pathlib import Path

import pytest

from climblog.config import load_config
from climblog.expr import Value
from climblog.grades import Grade, parse_grade
from climblog.storage import check_schema, load_data
from demo import FILES, write

SINCE = dt.date(2026, 11, 6)  # the journal's newest fields (#117, #128)


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("demo")
    write(folder, end=SINCE + dt.timedelta(days=20), seed=5, weeks=6)
    return folder


def test_every_module_loads_clean_and_in_sync(demo: Path) -> None:
    config = load_config(demo / "config.toml")
    assert set(config.modules) == set(FILES)
    for name in FILES:
        module, repo = config.module(name), config.repository(name)
        data = load_data(module, repo)
        assert data.issues == []
        assert all(data.entities[e].records for e in module.entities), name
        assert check_schema(module, repo) == []  # as `climblog check`
    assert config.backups.folder == demo / "backups"
    assert config.snapshots.folder == demo / "snapshots"


def day(record: dict[str, Value]) -> dt.date:
    date = record["date"]
    assert isinstance(date, dt.date)
    return date


def grade(record: dict[str, Value], field: str) -> Grade:
    text = record[field]
    assert isinstance(text, str)
    return parse_grade(text, ["french", "font"])


def test_new_fields_only_from_their_since(demo: Path) -> None:
    config = load_config(demo / "config.toml")
    sessions = load_data(config.module("journal"), config.repository("journal"))
    records = sessions.entities["session"].records
    before = [r for r in records if day(r) < SINCE]
    after = [r for r in records if day(r) >= SINCE]
    assert before and after
    for field in ("hardest_send", "send_type", "ph_post_lower_back"):
        assert all(r.get(field) is None for r in before), field
        assert any(r.get(field) is not None for r in after), field


def test_a_send_is_never_harder_than_the_grade_tried(demo: Path) -> None:
    config = load_config(demo / "config.toml")
    data = load_data(config.module("journal"), config.repository("journal"))
    sends = [r for r in data.entities["session"].records if r.get("hardest_send")]
    assert sends
    for record in sends:
        assert record["send_discipline"] == record["tried_discipline"]
        tried, sent = grade(record, "hardest_grade"), grade(record, "hardest_send")
        assert sent.system == tried.system
        assert sent.index <= tried.index
