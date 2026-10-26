# SPDX-License-Identifier: GPL-3.0-or-later
"""Read spreadsheet cells by field type, collecting data issues (04-storage.md §3b, §4, D-046).

Cells typed by hand can be messy (`7,5`, `Y`, `max hangs `, `24/10/2026`). Each becomes a
typed value or, if it cannot be read, a data issue with its tab, row and column: the record
still loads, without that value. Text cells are kept exactly as written and never produce an
issue, so note contents never reach a message. Nothing here logs.
"""

import datetime as dt
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from climblog.expr import Checked, Value, evaluate, prepare
from climblog.grades import GradeError, parse_grade
from climblog.modules.checks import expression_env
from climblog.modules.schema import (
    NEXT,
    BaseField,
    BoolField,
    ChoiceField,
    DateField,
    DurationField,
    GradeField,
    Module,
    MultichoiceField,
    NumberField,
    NumericScale,
    OrdinalScale,
    PercentField,
    RefField,
    ScaleField,
    TextField,
)
from climblog.text import fold

RawCell = str | int | float | bool | dt.datetime | dt.date | dt.time | dt.timedelta | None
"""A cell as openpyxl or the Sheets API gives it."""

_EPOCH = dt.datetime(1899, 12, 30)  # day 0 of spreadsheet date serials
_MAX_SERIAL = 2958465  # 9999-12-31
_NUMBER = re.compile(r"[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)")
_DATE = re.compile(
    r"(?:(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})"  # ISO
    r"|(?P<d2>\d{1,2})(?P<sep>[/.-])(?P<m2>\d{1,2})(?P=sep)(?P<y2>\d{4}|\d{2}))"  # day first
    r"(?:[ T](?P<time>\d{1,2}:\d{2}(?::\d{2})?))?"
)
_TIME = re.compile(r"(?P<h>\d{1,2}):(?P<min>\d{2})(?::(?P<s>\d{2}))?")
_DURATION = re.compile(r"(?P<h>\d+):(?P<min>[0-5]\d)")
_YES = frozenset({"yes", "y", "true", "si", "1"})  # folded: Sì → si
_NO = frozenset({"no", "n", "false", "0"})


class CellError(ValueError):
    """A cell that cannot be read as its field's type."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class DataIssue:
    """A problem in the sheet: shown in the UI with its place (04 §4)."""

    tab: str
    row: int | None  # the sheet's row number (1-based; data starts at row 3); None: whole tab
    field: str | None  # the column's key (row 2); None: whole row or tab
    message: str


def parse_cell(module: Module, field: BaseField, raw: RawCell) -> Value:
    """The cell's value for the field's type; blank is None. Raises `CellError`."""
    if isinstance(field, TextField):
        return _text(raw)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    match field:
        case DateField(type="date"):
            return _date(raw)
        case DateField(type="datetime"):
            return _datetime(raw)
        case DateField():
            return _time(raw)
        case NumberField():
            value = _number(raw)
            if field.type == "integer":
                value = _whole(value)
            return _in_range(value, field.min, field.max)
        case ScaleField():
            scale = module.scales[field.scale]
            assert isinstance(scale, NumericScale)  # checked at load
            return _in_range(_number(raw), scale.min, scale.max)
        case PercentField():
            return _in_range(_number(raw, percent=True), 0, 100)
        case DurationField():
            return _in_range(_duration(raw), field.min, field.max)
        case ChoiceField():
            return _choice(_choices(module, field), field, _plain(raw))
        case MultichoiceField():
            items = [item for item in _plain(raw).split(";") if item.strip()]
            return "; ".join(_choice(field.choices, field, item) for item in items) or None
        case BoolField():
            return _bool(raw)
        case GradeField():
            try:
                return parse_grade(_plain(raw), field.systems).text
            except GradeError as error:
                raise CellError(f"{_show(raw)} {error.reason}") from None
        case RefField():  # references are checked in M5
            return _plain(raw).strip()
    raise TypeError(f"no parser for {type(field).__name__}")  # pragma: no cover


class RowParser:
    """Reads the rows of one entity's tabs: every stored field, then the required ones.

    A blank cell of a field with `default:` reads as the default (D-048); a bad cell stays blank.
    """

    def __init__(self, module: Module, entity: str) -> None:
        self.module = module
        self.entity = module.entities[entity]
        self.fields = {k: f for k, f in self.entity.fields.items() if isinstance(f, BaseField)}
        env = expression_env(module, self.entity.fields, self.entity.date_field)
        self.conditions: dict[str, Checked] = {
            key: prepare(field.visible_if, env)
            for key, field in self.fields.items()
            if field.required and field.visible_if is not None
        }

    def parse(
        self,
        raw: Mapping[str, RawCell],
        *,
        tab: str,
        row: int,
        fields: Collection[str] | None = None,
        required: bool = True,
    ) -> tuple[dict[str, Value], list[DataIssue]]:
        """The row's values (a bad cell is None) and its data issues.

        `fields`: the fields on this tab (default: all). Unknown columns are left out: schema
        sync keeps them and `climblog check` lists them (D-051, D-052). `required=False` leaves
        the required check to `missing`, for rows joined with other tabs first.
        """
        values: dict[str, Value] = {}
        issues: list[DataIssue] = []
        for key, field in self._fields(fields):
            try:
                value = parse_cell(self.module, field, raw.get(key))
            except CellError as error:
                values[key] = None
                issues.append(DataIssue(tab, row, key, error.message))
                continue
            values[key] = self._default(field) if value is None else value
        if required:
            bad = {issue.field for issue in issues}
            issues += self.missing(values, tab=tab, row=row, fields=fields, skip=bad)
        return values, issues

    def missing(
        self,
        values: Mapping[str, Value],
        *,
        tab: str,
        row: int,
        fields: Collection[str] | None = None,
        skip: Collection[str | None] = (),
    ) -> list[DataIssue]:
        """Required fields left empty in a row (`skip`: fields already reported as bad)."""
        return [
            DataIssue(tab, row, key, "required, but empty")
            for key, field in self._fields(fields)
            if field.required
            and values.get(key) is None
            and key not in skip
            and self._expected(key, field, values)
        ]

    def _fields(self, keys: Collection[str] | None) -> list[tuple[str, BaseField]]:
        return [(k, f) for k, f in self.fields.items() if keys is None or k in keys]

    def _default(self, field: BaseField) -> Value:
        if field.default is None or field.default == NEXT:  # `next`: numbered by the loader
            return None
        try:
            return parse_cell(self.module, field, field.default)
        except CellError:
            return field.default  # type: ignore[no-any-return]

    def _expected(self, key: str, field: BaseField, values: Mapping[str, Value]) -> bool:
        """A required field is not expected while hidden (`visible_if`) or before its `since:`."""
        day = values.get(self.entity.date_field)
        if field.since is not None and isinstance(day, dt.date) and _day(day) < field.since:
            return False
        condition = self.conditions.get(key)
        return condition is None or evaluate(condition, values, {}) is True


# ---- Values by type ----


def _show(raw: RawCell) -> str:
    """A bad value for a message, shortened (never a text cell's content: those never fail)."""
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return f"{raw:g}"
    text = raw.strip() if isinstance(raw, str) else _plain(raw)
    return repr(text if len(text) <= 40 else text[:39] + "…")


def _plain(raw: RawCell) -> str:
    """A cell as the sheet shows it: 5 → "5", 7.0 → "7", a date → ISO."""
    match raw:
        case None:
            return ""
        case bool():
            return "TRUE" if raw else "FALSE"
        case float() if raw.is_integer():
            return str(int(raw))
        case dt.datetime() if raw.time() == dt.time():
            return raw.date().isoformat()
        case dt.datetime():
            return raw.isoformat(sep=" ")
        case dt.date() | dt.time():
            return raw.isoformat()
    return str(raw)


def _text(raw: RawCell) -> Value:
    """Text is kept exactly as written: leading `'` or `=`, spaces, line breaks (04 §3b)."""
    if isinstance(raw, str):
        return raw or None
    return _plain(raw) or None


def _number(raw: RawCell, *, percent: bool = False) -> int | float:
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return raw
    if not isinstance(raw, str):
        raise CellError(f"{_show(raw)} is not a number")
    text = raw.strip()
    if percent:
        text = text.removesuffix("%").rstrip()
    if not _NUMBER.fullmatch(text):
        raise CellError(f"{_show(raw)} is not a number")
    text = text.replace(",", ".")  # decimal comma (D-024)
    return float(text) if "." in text else int(text)


def _whole(value: int | float) -> int:
    if isinstance(value, float):
        if not value.is_integer():
            raise CellError(f"{value:g} is not a whole number")
        return int(value)
    return value


def _in_range(value: int | float, low: float | None, high: float | None) -> int | float:
    if low is not None and value < low:
        raise CellError(f"{value:g} is below the minimum {low:g}")
    if high is not None and value > high:
        raise CellError(f"{value:g} is above the maximum {high:g}")
    return value


def _duration(raw: RawCell) -> int | float:
    """Minutes: a number, `h:mm`, or a time or duration cell."""
    if isinstance(raw, dt.timedelta):
        minutes = raw.total_seconds() / 60
    elif isinstance(raw, dt.time):
        minutes = raw.hour * 60 + raw.minute + raw.second / 60
    elif isinstance(raw, str) and (found := _DURATION.fullmatch(raw.strip())):
        minutes = int(found["h"]) * 60 + int(found["min"])
    else:
        try:
            return _number(raw)
        except CellError:
            raise CellError(f"{_show(raw)} is not a duration in minutes or h:mm") from None
    return int(minutes) if float(minutes).is_integer() else minutes


def _serial(raw: int | float) -> dt.datetime:
    """A spreadsheet date serial (days since 1899-12-30, with the time as a fraction)."""
    if not 1 <= raw <= _MAX_SERIAL:
        raise CellError(f"{raw:g} is not a date")
    return _EPOCH + dt.timedelta(days=raw)


def _date_text(raw: str, kind: str) -> dt.datetime:
    """ISO or day-first (never month-first), with an optional time; 2-digit years are 20xx."""
    found = _DATE.fullmatch(raw.strip())
    if found is None:
        raise CellError(f"{_show(raw)} is not a {kind} (e.g. 2026-10-24 or 24/10/2026)")
    if found["y"]:
        year, month, day = found["y"], found["m"], found["d"]
    else:
        year, month, day = found["y2"], found["m2"], found["d2"]
    try:
        moment = dt.datetime(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day))
        if found["time"]:
            moment = dt.datetime.combine(moment, _time_text(found["time"]))
    except (ValueError, CellError):
        raise CellError(f"{_show(raw)} is not a valid {kind}") from None
    return moment


def _date(raw: RawCell) -> dt.date:
    match raw:
        case dt.datetime():
            return raw.date()
        case dt.date():
            return raw
        case bool():
            pass
        case int() | float():
            return _serial(raw).date()
        case str():
            return _date_text(raw, "date").date()
    raise CellError(f"{_show(raw)} is not a date")


def _datetime(raw: RawCell) -> dt.datetime:
    match raw:
        case dt.datetime():
            return raw
        case dt.date():
            return dt.datetime.combine(raw, dt.time())
        case bool():
            pass
        case int() | float():
            return _serial(raw).replace(microsecond=0)
        case str():
            return _date_text(raw, "date and time")
    raise CellError(f"{_show(raw)} is not a date and time")


def _time_text(text: str) -> dt.time:
    found = _TIME.fullmatch(text.strip())
    if found is None:
        raise CellError(f"{_show(text)} is not a time (e.g. 18:30)")
    try:
        return dt.time(int(found["h"]), int(found["min"]), int(found["s"] or 0))
    except ValueError:
        raise CellError(f"{_show(text)} is not a valid time") from None


def _time(raw: RawCell) -> dt.time:
    match raw:
        case dt.datetime():
            return raw.time()
        case dt.time():
            return raw
        case bool():
            pass
        case int() | float() if 0 <= raw < 1:  # a day fraction
            return (dt.datetime.min + dt.timedelta(days=raw)).replace(microsecond=0).time()
        case str():
            return _time_text(raw)
    raise CellError(f"{_show(raw)} is not a time")


def _choices(module: Module, field: ChoiceField) -> list[str]:
    if field.choices is not None:
        return field.choices
    scale = module.scales[field.scale or ""]
    assert isinstance(scale, OrdinalScale)  # checked at load
    return scale.choices


def _choice(choices: list[str], field: ChoiceField | MultichoiceField, text: str) -> str:
    """The canonical choice, matched ignoring case and surrounding spaces (D-046)."""
    key = text.strip().casefold()
    for choice in choices:
        if choice.casefold() == key:
            return choice
    if isinstance(field, ChoiceField):
        for legacy, current in field.choice_map.items():
            if legacy.casefold() == key:
                return current
    if field.allow_other:
        return text.strip()
    raise CellError(f"{_show(text)} is not one of: {', '.join(choices)}")


def _bool(raw: RawCell) -> bool:
    if isinstance(raw, bool):
        return raw
    word = fold(_plain(raw).strip())
    if word in _YES:
        return True
    if word in _NO:
        return False
    raise CellError(f"{_show(raw)} is not Yes or No")


def _day(value: dt.date) -> dt.date:
    return value.date() if isinstance(value, dt.datetime) else value
