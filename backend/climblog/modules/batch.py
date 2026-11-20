# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch forms (03 §2.6, D-115): one row of the form per reference row still in use.

`batch_over: retest_measures` takes every row of the table; `batch_over: {reference: exercises,
where: {session: [Primer, A]}}` the rows whose field has one of the values. The form's entity
has one `ref` key field to the table, which each row fills. The other key parts (the date) and
`keep_fields` are typed once for the whole batch (`shared`). A row's record of the day is the
one with the same shared key parts and that reference key; the day's other records of the
entity are listed apart ("Also logged that day").
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from climblog.expr import Value
from climblog.modules.reference import RETIRED, display_field, match_key, per_week_label
from climblog.modules.schema import FormModel, Module, RefField


@dataclass(frozen=True)
class BatchRow:
    key: Value  # the reference row's key, as typed in its table
    label: str  # "A1 · Wall slides"
    hint: str | None  # this week's per-week value: "Prescription W3: 3x10"
    retired: bool  # retired, listed only because the day already has its record
    record: int | None  # the index of its record in the entity's records, if logged


@dataclass(frozen=True)
class Batch:
    field: str  # the entity's ref field the rows fill
    table: str
    shared: list[str]  # typed once: the other key parts (the date first), then keep_fields
    rows: list[BatchRow]
    others: list[int]  # the indexes of the matching records that are no row of the batch


def ref_field(module: Module, form: FormModel) -> str:
    """The form entity's `ref` field to the batch's table (checked at load: exactly one)."""
    batch = form.batch()
    assert batch is not None
    return next(
        n
        for n, f in module.entities[form.entity].fields.items()
        if isinstance(f, RefField) and f.reference == batch.reference and not f.retired
    )


def shared_fields(module: Module, form: FormModel) -> list[str]:
    """The fields typed once for the batch: the key parts but the ref (date first), then
    `keep_fields`."""
    entity = module.entities[form.entity]
    ref = ref_field(module, form)
    found = [p for p in entity.key or [entity.date_field or "date"] if p != ref]
    return found + [f for f in form.keep_fields if f not in found and f != ref]


def key_parts(module: Module, form: FormModel) -> list[str]:
    """The shared fields that are key parts: they choose the day's records of the batch."""
    entity = module.entities[form.entity]
    ref = ref_field(module, form)
    return [p for p in entity.key or [entity.date_field or "date"] if p != ref]


def in_batch(form: FormModel, row: Mapping[str, Value]) -> bool:
    """Whether a reference row passes the batch's filter (retired or not)."""
    batch = form.batch()
    assert batch is not None
    return all(row.get(name) in values for name, values in batch.where.items())


def batch_rows(
    module: Module,
    form: FormModel,
    table_rows: Sequence[Mapping[str, Value]],
    records: Sequence[Mapping[str, Value]],
    key: Mapping[str, Value],
    week: int | None = None,
) -> Batch:
    """The batch for the shared key values `key` (the date): the table's rows in the filter
    still in use, in sheet order, each with its record if logged, and a retired one only when
    logged; and the other records with those key values."""
    batch = form.batch()
    assert batch is not None
    table = (module.reference or {})[batch.reference]
    field = ref_field(module, form)
    parts = key_parts(module, form)
    mine = {
        i: match_key(r.get(field))
        for i, r in enumerate(records)
        if all(r.get(p) == key.get(p) for p in parts)
    }
    shown = display_field(table)
    hint = per_week_label(table)
    rows: list[BatchRow] = []
    used: set[int] = set()
    for row in table_rows:
        if not in_batch(form, row):
            continue
        wanted = match_key(row.get(table.key))
        record = next((i for i, k in mine.items() if k == wanted and i not in used), None)
        retired = row.get(RETIRED) is True
        if retired and record is None:
            continue
        if record is not None:
            used.add(record)
        name = row.get(shown) if shown else None
        label = (
            f"{row.get(table.key)} · {name}" if name not in (None, "") else str(row.get(table.key))
        )
        value = row.get(f"w{week}") if week is not None and table.per_week is not None else None
        rows.append(
            BatchRow(
                row.get(table.key),
                label,
                f"{hint} W{week}: {value}" if value not in (None, "") else None,
                retired,
                record,
            )
        )
    others = [i for i in mine if i not in used]
    return Batch(field, batch.reference, shared_fields(module, form), rows, others)
