# SPDX-License-Identifier: GPL-3.0-or-later
"""Fields prefilled from another module's same-day record (03 §2.1, §2.6, D-022, D-114).

`from: journal.session.hardest_grade` copies a field of the other module's record dated the
same day; `from: journal.session.setting+session_type` joins several, `"Indoor · Climbing"`
(blank parts left out), and `from_map` turns that text into this field's value. A value this
field can't take (not mapped, not one of its choices, a grade that doesn't parse) prefills
nothing. Only the app's forms prefill (D-114): the sheet is typed by hand.

The module file names the other module by its `module:` id; whether it is configured, and has
that entity and those fields, is known only with the app config (`source_problems`): a problem
switches that field's prefill off, the module still loads.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from climblog.expr import Value
from climblog.modules.schema import BaseField, GradeField, Module

FROM_SYNTAX = "module.entity.field, or module.entity.field+other_field"
_FROM = re.compile(
    r"^([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*(?:\+[a-z][a-z0-9_]*)*)$"
)
JOIN = " · "


@dataclass(frozen=True)
class Source:
    module: str  # the other module's `module:` id
    entity: str
    fields: tuple[str, ...]  # joined with " · " when more than one


def parse_from(text: str) -> Source | None:
    found = _FROM.match(text.strip())
    if found is None:
        return None
    module, entity, fields = found.groups()
    return Source(module, entity, tuple(fields.split("+")))


def prefilled(module: Module, entity: str) -> dict[str, Source]:
    """The entity's fields with a `from:`, and where each comes from."""
    found: dict[str, Source] = {}
    for name, field in module.entities[entity].fields.items():
        if isinstance(field, BaseField) and field.from_ is not None and not field.retired:
            source = parse_from(field.from_)
            if source is not None:
                found[name] = source
    return found


FindModule = Callable[[str], Module | None]  # a configured module by its `module:` id


def source_problems(module: Module, find: FindModule) -> dict[tuple[str, str], str]:
    """Each `from:` whose module, entity or fields aren't there, as (entity, field) → why."""
    problems: dict[tuple[str, str], str] = {}
    for e_name in module.entities:
        for name, source in prefilled(module, e_name).items():
            other = find(source.module)
            if other is None:
                why = f"no module '{source.module}' in the app config"
            elif source.entity not in other.entities:
                why = f"module '{source.module}' has no entity '{source.entity}'"
            else:
                fields = other.entities[source.entity].fields
                missing = [f for f in source.fields if f not in fields]
                why = (
                    f"{source.module}.{source.entity} has no field '{missing[0]}'"
                    if missing
                    else ""
                )
            if why:
                problems[(e_name, name)] = f"{e_name}.{name}: not prefilled ({why})"
    return problems


def value_from(
    module: Module, field: BaseField, source: Source, record: Mapping[str, Value]
) -> Value:
    """The value the field takes from the other module's record, or None when it can't take
    one (parsed as the field's own cell, D-048)."""
    from climblog.storage.cells import CellError, parse_cell  # storage imports the modules

    parts = [record.get(f) for f in source.fields]
    texts = [_text(v) for v in parts if v is not None and _text(v) != ""]
    if not texts:
        return None
    joined = JOIN.join(texts)
    if field.from_map:
        mapped = field.from_map.get(joined)
        if mapped is None:
            return None
        joined = mapped
    elif len(texts) == 1 and len(source.fields) == 1:
        single = parts[0]
        if not isinstance(single, str):
            return single if _fits(module, field, single) else None
    if isinstance(field, GradeField) and not _same_system(joined, field.systems):
        return None  # a Font 6B+ is no French 6b+ (D-105)
    try:
        return parse_cell(module, field, joined)
    except CellError:
        return None


def _same_system(text: str, systems: Sequence[str]) -> bool:
    """Whether the grade, read as any system would read it, is one of these systems."""
    from climblog.grades import SUPPORTED, GradeError, parse_grade

    try:
        return parse_grade(text, SUPPORTED).system in systems
    except GradeError:
        return False


def _fits(module: Module, field: BaseField, value: Value) -> bool:
    from climblog.storage.cells import CellError, parse_cell

    try:
        return parse_cell(module, field, value) is not None
    except CellError:
        return False


def _text(value: Value) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


@dataclass(frozen=True)
class Candidate:
    """A same-day record of the other module, and what it prefills."""

    module: str
    entity: str
    label: str  # "Session 2 · Indoor · Climbing · 7a"
    key: dict[str, Value]
    values: dict[str, Value]  # this entity's field → value


def candidates(
    module: Module,
    entity: str,
    find: Callable[[str], tuple[Module, Mapping[str, Sequence[Mapping[str, Value]]]] | None],
    day: object,
) -> tuple[list[Candidate], list[str]]:
    """The other modules' records dated `day` that prefill the entity's fields, in their order,
    and why some fields can't be prefilled."""
    import datetime as dt

    sources = prefilled(module, entity)
    notes: list[str] = []
    by_source: dict[tuple[str, str], list[str]] = {}
    for name, source in sources.items():
        by_source.setdefault((source.module, source.entity), []).append(name)
    found: list[Candidate] = []
    for (other_id, other_entity), names in by_source.items():
        other = find(other_id)
        if other is None:
            notes += [f"{entity}.{n}: not prefilled (no module '{other_id}' loaded)" for n in names]
            continue
        other_module, tables = other
        ent = other_module.entities.get(other_entity)
        if ent is None:
            notes += [f"{entity}.{n}: not prefilled (no entity '{other_entity}')" for n in names]
            continue
        keys = ent.key or [ent.date_field]
        for record in tables.get(other_entity, ()):
            when = record.get(ent.date_field)
            when = when.date() if isinstance(when, dt.datetime) else when
            if when != day:
                continue
            values: dict[str, Value] = {}
            for name in names:
                field = module.entities[entity].fields[name]
                assert isinstance(field, BaseField)
                value = value_from(module, field, sources[name], record)
                if value is not None:
                    values[name] = value
            numbers = [
                str(record.get(k))
                for k in keys
                if k != ent.date_field and record.get(k) is not None
            ]
            head = " ".join([ent.label, *numbers])  # "Session 2"
            label = JOIN.join([head, *(_text(v) for v in values.values())])
            found.append(
                Candidate(other_id, other_entity, label, {k: record.get(k) for k in keys}, values)
            )
    return found, notes
