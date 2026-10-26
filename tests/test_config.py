# SPDX-License-Identifier: GPL-3.0-or-later
"""The app config: where it is, paths, defaults and problems (02-architecture.md, D-051)."""

import datetime as dt
from pathlib import Path
from textwrap import dedent

import pytest

from climblog.config import ConfigError, config_path, load_config

FINGERS = Path("modules/finger-strength.yaml").absolute()


def write(folder: Path, text: str) -> Path:
    file = folder / "config.toml"
    file.write_text(dedent(text), encoding="utf-8")
    return file


def problems(file: Path) -> list[str]:
    with pytest.raises(ConfigError) as error:
        load_config(file)
    return error.value.problems


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No real config or home folder: HOME is a temp folder, no CLIMBLOG_CONFIG or XDG_*."""
    for variable in ("CLIMBLOG_CONFIG", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_path_defaults_to_the_xdg_config_folder(tmp_path: Path) -> None:
    assert config_path() == tmp_path / "home/.config/climblog/config.toml"


def test_path_follows_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config_path() == tmp_path / "xdg/climblog/config.toml"


def test_a_relative_xdg_variable_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")  # the XDG spec says to ignore it
    assert config_path() == tmp_path / "home/.config/climblog/config.toml"


def test_the_option_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIMBLOG_CONFIG", "~/env.toml")
    assert config_path() == Path.home() / "env.toml"
    assert config_path(Path("flag.toml")) == Path("flag.toml")


def test_module_paths_are_relative_to_the_config_file(tmp_path: Path) -> None:
    file = write(
        tmp_path,
        f"""\
        [modules.finger_strength]
        definition = "{FINGERS}"
        workbook = "data/fingers.xlsx"

        [modules.journal]
        definition = "~/modules/journal.yaml"
        workbook = "/elsewhere/journal.xlsx"
        """,
    )
    config = load_config(file)
    assert config.modules["finger_strength"].definition == FINGERS
    assert config.modules["finger_strength"].workbook == tmp_path / "data/fingers.xlsx"
    assert config.modules["journal"].definition == tmp_path / "home/modules/journal.yaml"
    assert config.modules["journal"].workbook == Path("/elsewhere/journal.xlsx")


def test_backups_default_to_the_xdg_data_folder(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, ""))
    assert config.modules == {}
    backups = config.backups.for_module("finger_strength")
    assert backups.folder == tmp_path / "home/.local/share/climblog/backups/finger_strength"
    assert (backups.every, backups.keep) == (dt.timedelta(minutes=30), 30)


def test_backups_can_be_configured(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path,
            """\
            [backups]
            folder = "backups"
            every_minutes = 10
            keep = 5
            """,
        )
    )
    backups = config.backups.for_module("journal")
    assert backups.folder == tmp_path / "backups/journal"
    assert (backups.every, backups.keep) == (dt.timedelta(minutes=10), 5)


def test_repository_is_the_workbook_with_its_backups(tmp_path: Path) -> None:
    file = write(
        tmp_path,
        f"""\
        [modules.finger_strength]
        definition = "{FINGERS}"
        workbook = "fingers.xlsx"
        """,
    )
    repo = load_config(file).repository("finger_strength")
    assert repo.path == tmp_path / "fingers.xlsx"
    assert repo.backups is not None
    assert repo.backups.folder.name == "finger_strength"
    assert not repo.backups.folder.exists()  # created on the first write only


def test_module_loads_the_yaml_of_that_id(tmp_path: Path) -> None:
    file = write(
        tmp_path,
        f"""\
        [modules.finger_strength]
        definition = "{FINGERS}"
        workbook = "fingers.xlsx"

        [modules.fingers]
        definition = "{FINGERS}"
        workbook = "fingers.xlsx"
        """,
    )
    config = load_config(file)
    assert config.module("finger_strength").module == "finger_strength"
    with pytest.raises(ValueError, match="defines module 'finger_strength', not 'fingers'"):
        config.module("fingers")


def test_problems_are_listed_together(tmp_path: Path) -> None:
    file = write(
        tmp_path,
        """\
        colour = "blue"

        [modules.journal]
        definition = "journal.yaml"
        workbok = "journal.xlsx"

        [modules.Bad-Name]
        definition = "x.yaml"
        workbook = "x.xlsx"

        [backups]
        keep = 0
        """,
    )
    assert problems(file) == [
        "modules.journal.workbook: Field required",
        "modules.journal.workbok: unknown key",
        "modules.Bad-Name.[key]: String should match pattern '^[a-z][a-z0-9_]*$'",
        "backups.keep: Input should be greater than or equal to 1",
        "colour: unknown key",
    ]


def test_toml_syntax_errors_give_the_line(tmp_path: Path) -> None:
    file = write(tmp_path, "[modules.journal\n")
    (problem,) = problems(file)
    assert "line 1" in problem
    assert str(ConfigError(file, [problem])).startswith(f"{file}: ")


def test_a_missing_file_says_where_it_looked(tmp_path: Path) -> None:
    assert problems(tmp_path / "none.toml") == ["no config file here (see README, Configure)"]


def test_an_unreadable_file_is_a_problem(tmp_path: Path) -> None:
    file = tmp_path / "config.toml"
    file.write_bytes(b"\xff\xfe")
    (problem,) = problems(file)
    assert problem.startswith("cannot read:")


def test_snapshots_default_to_the_xdg_data_folder(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, ""))
    assert config.snapshots.snapshots().folder == tmp_path / "home/.local/share/climblog/snapshots"
    config = load_config(write(tmp_path, '[snapshots]\nfolder = "cache"\n'))
    assert config.snapshots.snapshots().folder == tmp_path / "cache"


def test_cached_is_the_workbook_through_its_snapshot(tmp_path: Path) -> None:
    file = write(
        tmp_path,
        f"""\
        [modules.finger_strength]
        definition = "{FINGERS}"
        workbook = "fingers.xlsx"
        """,
    )
    cached = load_config(file).cached("finger_strength")
    assert cached.module == "finger_strength"
    assert cached.source.path == tmp_path / "fingers.xlsx"  # type: ignore[attr-defined]
    assert cached.snapshots.folder.name == "snapshots"
