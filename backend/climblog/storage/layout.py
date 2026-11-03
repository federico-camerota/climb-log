# SPDX-License-Identifier: GPL-3.0-or-later
"""The workbook a module expects: tabs, columns, headers, validation (04-storage.md §1, D-052).

Pure data, the same for every backend: `check.py` compares a workbook with it and a backend's
schema sync applies it. The look follows the mock-ups (D-014, D-029, D-033): row 1 a label
coloured by group, row 2 the field key, then data. Formula columns come from the compiler (D-054).
"""

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from climblog.modules import Module
from climblog.modules.formulas import (
    ColumnMap,
    Dialect,
    FormulaColumn,
    Template,
    app_only_values,
    compile_formulas,
    formula_columns,
    side_by_side_formulas,
    summary_formulas,
)
from climblog.modules.schema import (
    BaseField,
    BoolField,
    ChoiceField,
    DateField,
    Entity,
    NumberField,
    NumericScale,
    OrdinalScale,
    Phase,
    ReferenceTemplateUse,
    ScaleField,
    TextField,
)
from climblog.modules.summary import row_label, summary_plan
from climblog.storage.cells import RawCell
from climblog.storage.load import DELETED
from climblog.storage.load import SETTINGS_TAB as SETTINGS_TAB
from climblog.storage.write import UPDATED_AT

META_TAB = "_meta"
SYSTEM_COLUMNS = (UPDATED_AT, DELETED)  # hand-optional, at the right of every data tab (04 §1)
RANGE_DASH = "\u2013"  # en dash between a scale's min and max in labels
EARLIEST_DATE = dt.date(1990, 1, 1)  # date validation: anything typed as a real date passes

# Header colours by group (row 1 fill, row 2 pale tint), as in the mock-ups.
Group = Literal["key", "pre", "post", "any", "auto", "system"]
GROUP_COLOURS: dict[Group, tuple[str, str]] = {
    "key": ("BDD7EE", "DDEBF7"),  # blue
    "pre": ("C6E0B4", "E2EFDA"),  # green: before the session
    "post": ("F8CBAD", "FCE4D6"),  # amber: after
    "any": ("FFE699", "FFF2CC"),  # yellow: common fields
    "auto": ("BFBFBF", "E7E6E6"),  # grey: AUTOMATIC, formulas (D-018)
    "system": ("E7E6E6", "F2F2F2"),  # light grey: filled by the app
}
_PHASE_GROUP: dict[Phase, Group] = {"pre": "pre", "post": "post", "next_day": "post", "any": "any"}


@dataclass(frozen=True)
class ListRule:
    values: tuple[str, ...]
    strict: bool = True  # False: other values are accepted after a warning (`allow_other`)


@dataclass(frozen=True)
class RangeRule:
    kind: Literal["whole", "decimal"]
    min: float | None
    max: float | None


@dataclass(frozen=True)
class DateRule:
    kind: Literal["date", "time"]


Validation = ListRule | RangeRule | DateRule


@dataclass(frozen=True)
class ColourScale:
    """Scale cells coloured red → yellow → green on the scale's own range, as in the mock-ups
    (fixed ends, so a single value already has its colour)."""

    min: float
    max: float
    lower_better: bool


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    group: Group
    validation: Validation | None = None
    number_format: str | None = None  # data cells; None keeps General
    colour_scale: ColourScale | None = None  # never for a neutral scale
    width: float = 10
    renamed_from: str | None = None
    old_label: str | None = None  # the label generated for `renamed_from`, to replace it
    retired: bool = False  # kept if there, never created
    formula: bool = False  # an `auto:` column: its cells hold formulas (D-053)
    levels: tuple[str, ...] | None = None  # a status: its levels, best first (colours)
    hidden: bool = False  # `auto:_key`


@dataclass(frozen=True)
class TabLayout:
    name: str
    columns: tuple[ColumnSpec, ...]
    unknown_ok: bool = False  # reference-template fields (M5): other columns can't be judged


@dataclass(frozen=True)
class SettingRow:
    key: str
    default: RawCell
    label: str


Formulas = Callable[[ColumnMap, Dialect], dict[tuple[str, str], Template]]
"""The `auto:` formulas, once the backend knows where every column is (D-053)."""


@dataclass(frozen=True)
class ReportCell:
    """A cell of a report tab: text, or a formula (`=…`)."""

    row: int
    column: int  # 1-based
    value: str
    number_format: str | None = None
    bold: bool = False
    name: str | None = None  # what a formula shows: a value's name, or `field#n` side by side


@dataclass(frozen=True)
class ReportTab:
    """A tab the app writes whole on every sync (the Summary, D-085): its cells, once the
    backend knows where every column is. Row 2 holds keys, as on a data tab, so its formulas
    read back with `read_formulas` for the drift check."""

    name: str
    cells: Callable[[ColumnMap, Dialect], list[ReportCell]]


@dataclass(frozen=True)
class WorkbookLayout:
    module: str
    version: int
    tabs: tuple[TabLayout, ...]
    settings: tuple[SettingRow, ...]
    formulas: Formulas = lambda columns, dialect: {}
    title: str = ""  # the module's name, for a new Google Sheet
    report: ReportTab | None = None


def workbook_layout(module: Module) -> WorkbookLayout:
    """The tabs of every entity, in YAML order, and the `_settings` rows."""
    placed, _ = formula_columns(module)
    tabs = [
        tab for entity in module.entities.values() for tab in _entity_tabs(module, entity, placed)
    ]
    settings = tuple(
        SettingRow(key, setting.default, setting.label or "")
        for key, setting in module.settings.items()
    )

    def formulas(columns: ColumnMap, dialect: Dialect) -> dict[tuple[str, str], Template]:
        return compile_formulas(module, columns, dialect)

    return WorkbookLayout(
        module.module,
        module.version,
        tuple(tabs),
        settings,
        formulas,
        module.name,
        summary_tab(module),
    )


# ---- The Summary tab (D-085) ----

DATE_FORMAT = "DD/MM/YYYY"
DAY_ROW = 3  # B3: =TODAY(), the day every formula reads (a test puts a date there)
SUMMARY_NOTE = (
    "Written by climb-log from the module's YAML: nothing to type here. "
    "Schema sync (climblog check --apply) writes it again."
)


def summary_tab(module: Module) -> ReportTab | None:
    """The module's Summary tab, if it has a `summary:` (rows of values, the latest records
    side by side, then the values the formulas use but the rows don't show)."""
    plan = summary_plan(module) if module.summary is not None else None
    if plan is None:
        return None

    def cells(columns: ColumnMap, dialect: Dialect) -> list[ReportCell]:
        day = f"$B${DAY_ROW}"
        out = [
            ReportCell(1, 1, plan.title, bold=True),
            ReportCell(DAY_ROW, 1, "Day", bold=True),
            ReportCell(DAY_ROW, 2, "=TODAY()", DATE_FORMAT),
        ]
        refs: dict[str, str] = {"date": day}
        values: list[tuple[int, int, str]] = []  # where each value goes: (row, column, name)
        row = DAY_ROW + 1
        for item in plan.rows:
            out.append(ReportCell(row, 1, item.label, bold=True))
            for column, name in enumerate(item.names(), start=2):
                refs.setdefault(name, f"${_column_letter(column)}${row}")
                values.append((row, column, name))
            row += 1
        width = max(len(item.names()) for item in plan.rows)
        sessions = plan.side_by_side
        if sessions is not None:
            entity = module.entities[sessions.entity]
            width = max(width, sessions.last)
            row += 1
            out.append(ReportCell(row, 1, f"LAST {sessions.last} SESSIONS", bold=True))
            row += 1
            fields = [entity.date_field, *(f for g in sessions.groups for f in g.fields)]
            side = side_by_side_formulas(
                module, columns, day, sessions.entity, fields, sessions.last, dialect
            )
            lines: list[tuple[str, str | None]] = [("Date", entity.date_field)]
            for group in sessions.groups:
                lines.append((group.label, None))
                lines += [
                    (row_label(module, sessions.entity, f, sessions.labels), f)
                    for f in group.fields
                ]
            for label, field in lines:
                out.append(ReportCell(row, 1, label, bold=field in (None, entity.date_field)))
                if field is not None:
                    fmt = DATE_FORMAT if field == entity.date_field else None
                    for n in range(1, sessions.last + 1):
                        cell = ReportCell(row, n + 1, side[(field, n)], fmt, name=f"{field}#{n}")
                        out.append(cell)
                row += 1
        hidden = [name for name in _value_names(module) if name not in refs]
        if hidden:  # the values the shown ones read, below everything else
            row += 1
            out.append(ReportCell(row, 1, "Values used above", bold=True))
            row += 1
            for name in hidden:
                refs[name] = f"$B${row}"
                out.append(ReportCell(row, 1, name))
                values.append((row, 2, name))
                row += 1
        formulas = summary_formulas(module, columns, refs, dialect)
        types = _value_types(module)
        for r, c, name in values:
            fmt = DATE_FORMAT if types.get(name) == "date" else None
            out.append(ReportCell(r, c, formulas[name], fmt, name=name))
        out.append(ReportCell(row + 1, 1, SUMMARY_NOTE))
        keys = ["item", *(f"c{i}" for i in range(1, width + 1))]
        out += [ReportCell(2, i, key) for i, key in enumerate(keys, start=1)]
        return out

    return ReportTab(plan.tab, cells)


def _value_names(module: Module) -> list[str]:
    """Every value the summary's formulas compute, in order."""
    from climblog.modules.checks import recommendation_plan

    plan = summary_plan(module)
    assert plan is not None
    advice = recommendation_plan(module)
    names = [s.key for s in advice.values.steps] + ["headline", "text"] if advice else []
    app_only = app_only_values(module)
    return names + [s.key for s in plan.values.steps if s.key not in app_only]


def _value_types(module: Module) -> dict[str, str]:
    from climblog.modules.checks import recommendation_plan

    plan = summary_plan(module)
    assert plan is not None
    advice = recommendation_plan(module)
    found = {**(advice.values.names if advice else {}), **plan.values.names}
    return {name: info.type for name, info in found.items()}


def _column_letter(i: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(i)


def _entity_tabs(
    module: Module, entity: Entity, placed: Sequence[FormulaColumn]
) -> list[TabLayout]:
    unknown_ok = any(isinstance(f, ReferenceTemplateUse) for f in entity.fields.values())
    key = entity.key or (["id"] if "id" in entity.fields else [])
    tabs = []
    for tab, names in entity.tab_fields().items():
        columns = [
            _column(module, entity, name, field, name in key)
            for name in names
            if isinstance(field := entity.fields[name], BaseField)
        ]
        # The AUTOMATIC block (its hidden key last), then the system columns, as in the mock-ups.
        autos = [c for c in placed if c.tab == tab]
        autos = [c for c in autos if not c.hidden] + [c for c in autos if c.hidden]
        columns += [_formula(c) for c in autos]
        columns += [_system(name) for name in SYSTEM_COLUMNS]
        tabs.append(TabLayout(tab, tuple(columns), unknown_ok))
    return tabs


def _column(
    module: Module, entity: Entity, name: str, field: BaseField, is_key: bool
) -> ColumnSpec:
    phase = field.phase
    if phase == "any" and field.section and field.section in entity.sections:
        phase = entity.sections[field.section].phase
    old = field.renamed_from
    return ColumnSpec(
        key=name,
        label=label(module, name, field),
        group="key" if is_key else _PHASE_GROUP[phase],
        validation=_validation(module, field),
        number_format=_number_format(field),
        colour_scale=_colour_scale(module, field),
        width=_width(field),
        renamed_from=old,
        old_label=label(module, old, field) if old else None,
        retired=field.retired,
    )


def _formula(column: FormulaColumn) -> ColumnSpec:
    return ColumnSpec(
        column.key,
        column.label,
        "auto",
        number_format=column.number_format,
        width=12,
        formula=True,
        levels=column.levels,
        hidden=column.hidden,
    )


def _system(name: str) -> ColumnSpec:
    return ColumnSpec(name, f"{name}\n(app fills)", "system", width=12)


def label(module: Module, name: str, field: BaseField) -> str:
    """Row 1: the field's label (or its key in words) with its unit or scale range."""
    text = field.label or name.replace("_", " ").capitalize()
    if "(" in text:
        return text  # the label already says it: "Block left (kg)"
    if isinstance(field, NumberField) and field.unit:
        return f"{text}\n({field.unit})"
    if isinstance(field, ScaleField):
        scale = module.scales[field.scale]
        if isinstance(scale, NumericScale):
            arrow = " ↓" if scale.direction == "lower_better" else ""
            return f"{text}\n({_number(scale.min)}{RANGE_DASH}{_number(scale.max)}{arrow})"
    return text


def _validation(module: Module, field: BaseField) -> Validation | None:
    match field:
        case ChoiceField():
            choices = field.choices
            if choices is None:
                scale = module.scales[field.scale or ""]
                assert isinstance(scale, OrdinalScale)  # checked at load
                choices = scale.choices
            return ListRule(tuple(choices), strict=not field.allow_other)
        case ScaleField():
            scale = module.scales[field.scale]
            assert isinstance(scale, NumericScale)  # an ordinal scale needs a choice field
            if scale.min == int(scale.min) and scale.max == int(scale.max):
                return ListRule(tuple(str(n) for n in range(int(scale.min), int(scale.max) + 1)))
            return RangeRule("decimal", scale.min, scale.max)
        case BoolField():
            return ListRule(("Yes", "No"))
        case NumberField() if field.min is not None or field.max is not None:
            return RangeRule(
                "whole" if field.type == "integer" else "decimal", field.min, field.max
            )
        case DateField(type="date"):
            return DateRule("date")
        case DateField(type="time"):
            return DateRule("time")
    return None


def _number_format(field: BaseField) -> str | None:
    match field:
        case DateField(type="date"):
            return "DD/MM/YYYY"
        case DateField(type="datetime"):
            return "DD/MM/YYYY HH:MM"
        case DateField(type="time"):
            return "HH:MM"
        case TextField():
            return "@"  # notes stay as typed (04 §3b)
    return None


def _colour_scale(module: Module, field: BaseField) -> ColourScale | None:
    if isinstance(field, ScaleField):
        scale = module.scales[field.scale]
        if isinstance(scale, NumericScale) and scale.direction != "neutral":
            return ColourScale(scale.min, scale.max, scale.direction == "lower_better")
    return None


def _width(field: BaseField) -> float:
    if isinstance(field, TextField):
        return 40 if field.multiline else 32
    if isinstance(field, DateField):
        return 11
    if isinstance(field, ChoiceField):
        return 14
    return 10


def _number(value: float) -> str:
    return f"{value:g}"
