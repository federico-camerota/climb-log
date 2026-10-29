# SPDX-License-Identifier: GPL-3.0-or-later
"""The app config (02-architecture.md, D-051): which workbook or Google Sheet each module lives
in (D-063), backups, the Google login (D-062).

A TOML file, by default `~/.config/climblog/config.toml` (`$XDG_CONFIG_HOME` honoured), or the
file named by `--config` or `CLIMBLOG_CONFIG`. It holds paths, never training data, and is not
part of the repo. Paths may start with `~`; relative ones are relative to the config file.
"""

import datetime as dt
import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from climblog.modules import Module, load_module
from climblog.modules.schema import Key
from climblog.storage import Backups, GSheetsBackend, Repository, StorageError, XlsxBackend
from climblog.storage.google_client import RestSheetsClient, Session
from climblog.storage.snapshot import CachedRepository, Snapshots

ENV_VAR = "CLIMBLOG_CONFIG"


class ConfigError(Exception):
    """A config file that cannot be used, with all its problems."""

    def __init__(self, file: Path, problems: list[str]) -> None:
        self.file = file
        self.problems = problems
        super().__init__("\n".join(self.lines()))

    def lines(self) -> list[str]:
        return [f"{self.file}: {problem}" for problem in self.problems]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="after")
    @classmethod
    def _resolve(cls, value: Any, info: ValidationInfo) -> Any:
        """`~` expanded; a relative path is relative to the config file's folder."""
        if isinstance(value, Path) and isinstance(info.context, Mapping):
            return info.context["base"] / value.expanduser()
        return value


class BackupConfig(_Strict):
    folder: Path | None = None  # None: $XDG_DATA_HOME/climblog/backups
    every_minutes: float = Field(default=30, gt=0)
    keep: int = Field(default=30, ge=1)

    def for_module(self, name: str) -> Backups:
        folder = self.folder or _xdg("XDG_DATA_HOME", ".local/share") / "climblog" / "backups"
        return Backups(
            folder / name, every=dt.timedelta(minutes=self.every_minutes), keep=self.keep
        )


class SnapshotConfig(_Strict):
    folder: Path | None = None  # None: $XDG_DATA_HOME/climblog/snapshots

    def snapshots(self) -> Snapshots:
        return Snapshots(
            self.folder or _xdg("XDG_DATA_HOME", ".local/share") / "climblog" / "snapshots"
        )


class GoogleConfig(_Strict):
    client_secret: Path | None = None  # the OAuth desktop client's JSON, downloaded from Google
    token: Path | None = None  # None: $XDG_CONFIG_HOME/climblog/google-token.json
    # Read a sheet again after this long even if Drive saw no change (it lags ~3 min, D-063).
    max_age_seconds: float = Field(default=60, ge=0)

    def token_file(self) -> Path:
        return self.token or _xdg("XDG_CONFIG_HOME", ".config") / "climblog" / "google-token.json"


class ModuleConfig(_Strict):
    definition: Path  # the module YAML
    workbook: Path | None = None  # a local .xlsx, or
    google_sheet: str | None = None  # a Google Sheet: its ID, or its URL (D-063)

    @field_validator("google_sheet", mode="after")
    @classmethod
    def _sheet_id(cls, value: str) -> str:  # only when set: defaults are not validated
        """The ID from `https://docs.google.com/spreadsheets/d/<ID>/edit…`, or the ID itself."""
        if match := re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value):
            return match.group(1)
        if re.fullmatch(r"[A-Za-z0-9_-]{20,}", value.strip()):
            return value.strip()
        raise ValueError("not a Google Sheet ID or URL")

    @model_validator(mode="after")
    def _one_place(self) -> "ModuleConfig":
        if (self.workbook is None) == (self.google_sheet is None):
            raise ValueError("set either workbook or google_sheet")
        return self

    @property
    def location(self) -> str:
        """Where the module lives, for messages."""
        return str(self.workbook) if self.workbook else f"Google Sheet {self.google_sheet}"


class AppConfig(_Strict):
    modules: dict[Key, ModuleConfig] = {}
    backups: BackupConfig = BackupConfig()
    snapshots: SnapshotConfig = SnapshotConfig()
    google: GoogleConfig = GoogleConfig()

    def module(self, name: str) -> Module:
        """The module's YAML, loaded. Raises `ModuleError`, or `ValueError` if its id differs."""
        file = self.modules[name].definition
        module = load_module(file)
        if module.module != name:
            raise ValueError(f"{file} defines module '{module.module}', not '{name}'")
        return module

    def repository(self, name: str) -> Repository:
        """The module's workbook (with its backups, taken only on writes) or Google Sheet."""
        module = self.modules[name]
        if module.google_sheet is not None:
            return GSheetsBackend(
                module.google_sheet,
                RestSheetsClient(self.google_session),
                max_age=dt.timedelta(seconds=self.google.max_age_seconds),
            )
        assert module.workbook is not None
        return XlsxBackend(module.workbook, backups=self.backups.for_module(name))

    def google_session(self) -> Session:
        """A session with the saved Google login (made when the sheet is first read)."""
        from google.auth.transport.requests import AuthorizedSession

        from climblog.google_auth import GoogleAuthError, load_credentials  # imports this module

        try:
            return AuthorizedSession(load_credentials(self.google))
        except GoogleAuthError as error:
            raise StorageError(str(error)) from None

    def cached(self, name: str) -> CachedRepository:
        """The module's workbook through its local snapshot (D-020, D-055)."""
        return CachedRepository(name, self.repository(name), self.snapshots.snapshots())


def config_path(explicit: Path | None = None) -> Path:
    """`explicit` (`--config`), else `CLIMBLOG_CONFIG`, else `~/.config/climblog/config.toml`."""
    if explicit is not None:
        return explicit
    if env := os.environ.get(ENV_VAR):
        return Path(env).expanduser()
    return _xdg("XDG_CONFIG_HOME", ".config") / "climblog" / "config.toml"


def load_config(file: Path) -> AppConfig:
    """Read and check a config file. Raises `ConfigError` listing every problem."""
    try:
        doc = tomllib.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(file, ["no config file here (see README, Configure)"]) from None
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(file, [f"cannot read: {error}"]) from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(file, [str(error)]) from None
    try:
        return AppConfig.model_validate(doc, context={"base": file.parent.absolute()})
    except ValidationError as error:
        raise ConfigError(file, [_problem(e) for e in error.errors()]) from None


def _problem(error: Any) -> str:
    path = ".".join(str(part) for part in error["loc"])
    message = "unknown key" if error["type"] == "extra_forbidden" else error["msg"]
    return f"{path}: {message}" if path else message


def _xdg(variable: str, fallback: str) -> Path:
    """An XDG base directory: the variable when set to an absolute path, else ~/fallback."""
    value = os.environ.get(variable, "")
    return Path(value) if os.path.isabs(value) else Path.home() / fallback
