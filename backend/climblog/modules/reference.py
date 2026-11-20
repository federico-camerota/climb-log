# SPDX-License-Identifier: GPL-3.0-or-later
"""Reference tables (03-module-framework.md §2.5, D-112): the columns of each table.

A table's columns are its fields, then one column per program week (`per_week`: `w1`…`wN`),
then `retired` (Yes: kept for the records that point at the row, left out of new choices).
Loading, writing and the sheet's layout all read the columns from here.
"""

from climblog.expr import Value
from climblog.modules.schema import (
    BaseField,
    BoolField,
    ChoiceField,
    Module,
    NumberField,
    ReferenceTable,
    RefField,
    TextField,
)

RETIRED = "retired"  # a reference row no longer offered (Yes), kept for old records
# Hidden formula columns of a reference tab (D-113): every row's key as matched (trimmed, blank
# when deleted), for lookups; and the keys still offered (not retired), for `ref` dropdowns.
KEY_HELPER = "auto:key"
CHOICE_HELPER = "auto:choice"
# Field types a reference table can have: what is typed by hand in one cell.
FIELD_TYPES = (TextField, ChoiceField, NumberField, BoolField, RefField)


def reference_weeks(module: Module) -> int:
    """How many per-week columns a table with `per_week` gets: the program's weeks."""
    return module.program.weeks if module.program is not None else 0


def reference_columns(module: Module, name: str) -> dict[str, BaseField]:
    """Every column of the table as a field, in sheet order (key first): its fields, the
    per-week columns and `retired`. Only meaningful for a checked module."""
    table = (module.reference or {})[name]
    columns = {table.key: _field(table, table.key)}
    columns |= {k: f for k, f in table.fields.items() if isinstance(f, BaseField)}
    if table.per_week is not None:
        per_week = table.per_week
        for n, key in enumerate(table.week_columns(reference_weeks(module)), start=1):
            label = f"W{n}\n{per_week_label(table)}"
            if per_week.type == "text":
                columns[key] = TextField(type="text", label=label)
            else:
                columns[key] = NumberField(type=per_week.type, label=label)
    columns[RETIRED] = BoolField(type="bool", label="Retired", default=False)
    return columns


def match_key(value: Value) -> Value:
    """A key as compared (D-113): text trimmed and in any case, as the sheet's MATCH and
    dropdowns compare it (`a3 ` is `A3`); blank as None."""
    found = clean_key(value)
    return found.casefold() if isinstance(found, str) else found


def display_field(table: ReferenceTable) -> str | None:
    """The field a form shows next to the key ("A3 · Wall slides"): `display`, or the first
    text field after the key."""
    if table.display is not None:
        return table.display
    return next(
        (n for n, f in table.fields.items() if n != table.key and isinstance(f, TextField)), None
    )


def clean_key(value: Value) -> Value:
    """A key as matched: text without the spaces around it (`A3 ` is `A3`), blank as None."""
    if isinstance(value, str):
        return value.strip() or None
    return value


def per_week_label(table: ReferenceTable) -> str | None:
    """What each per-week column holds, in words ("Prescription"); none without `per_week`."""
    per_week = table.per_week
    if per_week is None:
        return None
    return per_week.label or per_week.name.replace("_", " ").capitalize()


def table_label(name: str, table: ReferenceTable) -> str:
    return table.label or name.replace("_", " ").capitalize()


def _field(table: ReferenceTable, name: str) -> BaseField:
    field = table.fields[name]
    assert isinstance(field, BaseField)  # checked at load
    return field
