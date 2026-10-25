# SPDX-License-Identifier: GPL-3.0-or-later
"""Rotating copies of a local workbook, taken before writes (04-storage.md §2, D-049).

The first write of each app session makes a copy, later writes at most one every `every`;
only the newest `keep` copies are kept. Backups hold personal data: their folder is git-ignored.
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
        now = self.clock()
        if self._last is not None and now - self._last < self.every:
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        copy = self.folder / f"{now.strftime(_STAMP)}{workbook.suffix}"
        shutil.copy2(workbook, copy)
        self._last = now
        self._prune(workbook.suffix)
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
