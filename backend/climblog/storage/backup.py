# SPDX-License-Identifier: GPL-3.0-or-later
"""Rotating copies of a module's workbook, taken before writes (04-storage.md §2, §3, D-049).

The first write of each app session makes a copy, later writes at most one every `every`;
only the newest `keep` copies are kept. A local workbook is copied; a Google Sheet is exported
as `.xlsx` through Drive (D-068), also when the app sees it changed by hand. Backups hold
personal data: their folder is the owner's only and outside the repository.
"""

import datetime as dt
import shutil
from collections.abc import Callable
from pathlib import Path

_STAMP = "%Y%m%d-%H%M%S"


class Backups:
    def __init__(
        self,
        folder: Path,
        *,
        every: dt.timedelta = dt.timedelta(minutes=30),
        keep: int = 30,
        clock: Callable[[], dt.datetime] = dt.datetime.now,
    ) -> None:
        if keep < 1:
            raise ValueError("keep at least one backup")
        self.folder = folder
        self.every = every
        self.keep = keep
        self.clock = clock
        self._last: dt.datetime | None = None  # the last copy made by this app session

    def before_write(self, workbook: Path) -> Path | None:
        """Copy the workbook if a backup is due; the copy's path, or None."""
        return self.take(lambda copy: shutil.copy2(workbook, copy), workbook.suffix)

    def take(self, save: Callable[[Path], object], suffix: str = ".xlsx") -> Path | None:
        """If a backup is due, `save` one at the path given (made readable by the owner only);
        its path, or None."""
        now = self.clock()
        if self._last is not None and now - self._last < self.every:
            return None
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        copy = self.folder / f"{now.strftime(_STAMP)}{suffix}"
        save(copy)
        copy.chmod(0o600)
        self._last = now
        self._prune(suffix)
        return copy

    def _prune(self, suffix: str) -> None:
        copies = sorted(p for p in self.folder.glob(f"*{suffix}") if _is_stamp(p.stem))
        for old in copies[: -self.keep]:
            old.unlink()


def _is_stamp(name: str) -> bool:
    try:
        dt.datetime.strptime(name, _STAMP)
    except ValueError:
        return False
    return True
