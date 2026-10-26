# SPDX-License-Identifier: GPL-3.0-or-later
"""The workbook a module expects: tabs, columns, headers, validation (04-storage.md §1, D-052).

Pure data, the same for every backend: `check.py` compares a workbook with it and a backend's
schema sync applies it. The look follows the mock-ups (D-014, D-029, D-033): row 1 a label
coloured by group, row 2 the field key, then data. Formula columns are #19.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from climblog.modules import Module
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
from climblog.storage.cells import RawCell
from climblog.storage.load import DELETED
from climblog.storage.load import SETTINGS_TAB as SETTINGS_TAB
from climblog.storage.write import UPDATED_AT

META_TAB = "_meta"
SYSTEM_COLUMNS = (UPDATED_AT, DELETED)  # hand-optional, at the right of every data tab (04 §1)
RANGE_DASH = "\u2013"  # en dash between a scale's min and max in labels
EARLIEST_DATE = dt.date(1990, 1, 1)  # date validation: anything typed as a real date passes

# Header colours by group (row 1 fill, row 2 pale tint), as in the mock-ups.
Group = Literal["key", "pre", "post", "any", "system"]
GROUP_COLOURS: dict[Group, tuple[str, str]] = {
    "key": ("BDD7EE", "DDEBF7"),  # blue
    "pre": ("C6E0B4", "E2EFDA"),  # green: before the session
    "post": ("F8CBAD", "FCE4D6"),  # amber: after
    "any": ("FFE699", "FFF2CC"),  # yellow: common fields
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


@dataclass(frozen=True)
class WorkbookLayout:
    module: str
    version: int
    tabs: tuple[TabLayout, ...]
    settings: tuple[SettingRow, ...]


def workbook_layout(module: Module) -> WorkbookLayout:
    """The tabs of every entity, in YAML order, and the `_settings` rows."""
    tabs = [tab for entity in module.entities.values() for tab in _entity_tabs(module, entity)]
    settings = tuple(
        SettingRow(key, setting.default, setting.label or "")
        for key, setting in module.settings.items()
    )
    return WorkbookLayout(module.module, module.version, tuple(tabs), settings)


def _entity_tabs(module: Module, entity: Entity) -> list[TabLayout]:
    unknown_ok = any(isinstance(f, ReferenceTemplateUse) for f in entity.fields.values())
    key = entity.key or (["id"] if "id" in entity.fields else [])
    tabs = []
    for tab, names in entity.tab_fields().items():
        columns = [
            _column(module, entity, name, field, name in key)
            for name in names
            if isinstance(field := entity.fields[name], BaseField)
        ]
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
