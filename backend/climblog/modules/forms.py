# SPDX-License-Identifier: GPL-3.0-or-later
"""A module's forms (`forms:`, 03 §2.6) and what is due on a day: the Today page (D-080).

`form_fields` is the rule the frontend's forms follow (`frontend/src/forms/schema.ts`): a form
shows the fields of its sections (in its phase), plus fields of other sections whose own
`phase` is the form's; key and retired fields are left out.

What is due on a day: when no form's entity has a record that day, the module's entry forms
(no phase, or `pre`) are listed as missing, any one of them (a session or a rest day); once
there are records, each record's forms are listed (pre, then post), done / partial / missing by
how many of their scored fields (everything but text) are filled.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from climblog.expr import Value
from climblog.modules.schema import BaseField, Entity, Module, TextField

DONE, PARTIAL, MISSING = "done", "partial", "missing"


@dataclass(frozen=True)
class Form:
    name: str
    entity: str
    phase: str | None
    sections: tuple[str, ...] | None  # None: every field of the entity
    repeats: bool  # child rows repeated in the form (finger-strength sets): not handled yet


@dataclass(frozen=True)
class Due:
    """One form to fill on the day, for one record (or a new one)."""

    form: str
    label: str  # "Pre session"
    key: dict[str, Value]  # the record's key; just the date for a new record
    status: str  # done / partial / missing
    missing: list[str]  # the sections (or fields) still to fill
    log_check: Value = None  # the record's own check, when the entity has one (`log_check`)


@dataclass(frozen=True)
class Day:
    """A module's forms on a day, and its latest record up to it."""

    items: list[Due]
    any_one: bool  # nothing logged yet: the items are alternatives (a session or a rest day)
    last: dt.date | None  # the latest record of the first form's entity, on or before the day
    last_label: str | None = None  # that entity's label, e.g. "Session"
    notes: list[str] = field(default_factory=list)  # forms left out, and why


def forms_of(module: Module) -> dict[str, Form]:
    """The module's forms that name an entity of the module (the block is not checked yet)."""
    found: dict[str, Form] = {}
    for name, raw in (module.forms or {}).items():
        if not isinstance(raw, Mapping) or raw.get("entity") not in module.entities:
            continue
        sections = raw.get("sections")
        found[name] = Form(
            name,
            str(raw["entity"]),
            str(raw["phase"]) if raw.get("phase") is not None else None,
            tuple(str(s) for s in sections) if isinstance(sections, list) else None,
            bool(raw.get("children")),
        )
    return found


def form_label(name: str) -> str:
    """`pre_session` → "Pre session"."""
    text = name.replace("_", " ")
    return text[:1].upper() + text[1:]


def form_fields(module: Module, form: Form) -> list[str]:
    """The fields the form shows, in YAML order (the frontend's `formGroups`)."""
    entity = module.entities[form.entity]
    keys = set(entity.key or [entity.date_field or "date"])
    sections = entity.sections or {}
    found = []
    for name, f in entity.fields.items():
        assert isinstance(f, BaseField)  # templates are expanded at load
        if name in keys or f.retired:
            continue
        section = f.section
        own = _phase(f.phase)
        phase = own or (_phase(sections[section].phase) if section in sections else None)
        in_form = form.sections is None or (section is not None and section in form.sections)
        same_phase = form.phase is None or phase is None or phase == form.phase
        pulled = own is not None and own == form.phase  # e.g. the session's duration
        if (in_form and same_phase) or pulled:
            found.append(name)
    return found


def due(
    module: Module,
    tables: Mapping[str, Sequence[Mapping[str, Value]]],
    day: dt.date,
) -> Day:
    """The module's forms on `day`. `tables[entity]` holds each record's stored and derived
    values (deleted ones left out)."""
    forms = forms_of(module)
    notes = [
        f"{form_label(f.name)}: forms with repeated rows come later"
        for f in forms.values()
        if f.repeats
    ]
    usable = [f for f in forms.values() if not f.repeats and f.phase != "next_day"]
    if not usable:
        return Day([], False, None, notes=notes)
    on_day = {
        name: _sorted(
            module.entities[name],
            [r for r in tables.get(name, ()) if _day(r, module.entities[name]) == day],
        )
        for name in dict.fromkeys(f.entity for f in usable)
    }
    entry = [f for f in usable if f.phase in (None, "pre")]
    items: list[Due] = []
    if not any(on_day.values()):
        for f in entry:
            items.append(
                Due(
                    f.name,
                    form_label(f.name),
                    {_date_field(module.entities[f.entity]): day},
                    MISSING,
                    [],
                )
            )
    else:
        for e_name, records in on_day.items():
            entity = module.entities[e_name]
            for record in records:
                key = {part: record.get(part) for part in entity.key or [_date_field(entity)]}
                for f in (f for f in usable if f.entity == e_name):
                    status, missing = _status(module, f, record, day)
                    items.append(
                        Due(
                            f.name,
                            form_label(f.name),
                            key,
                            status,
                            missing,
                            record.get("log_check"),
                        )
                    )
    first = module.entities[usable[0].entity]
    dates = [
        d
        for r in tables.get(usable[0].entity, ())
        if (d := _day(r, first)) is not None and d <= day
    ]
    return Day(
        items,
        not any(on_day.values()) and len(entry) > 1,
        max(dates, default=None),
        first.label,
        notes,
    )


def _status(
    module: Module, form: Form, record: Mapping[str, Value], day: dt.date
) -> tuple[str, list[str]]:
    """Done when every scored field is filled (text is optional), partial when some are."""
    entity = module.entities[form.entity]
    names = [n for n in form_fields(module, form) if _tracked(entity, n, day)]
    scored = [n for n in names if not isinstance(entity.fields[n], TextField)] or names
    empty = [n for n in scored if record.get(n) is None]
    if not empty:
        return DONE, []
    status = MISSING if len(empty) == len(scored) else PARTIAL
    return status, _where(module, entity, empty)


def _tracked(entity: Entity, name: str, day: dt.date) -> bool:
    """Not a field added after the day (`since`)."""
    f = entity.fields[name]
    assert isinstance(f, BaseField)
    return f.since is None or f.since <= day


def _where(module: Module, entity: Entity, names: list[str]) -> list[str]:
    """The empty fields' sections, by label, in order (the fields themselves without sections)."""
    sections = entity.sections or {}
    found: list[str] = []
    for name in names:
        f = entity.fields[name]
        assert isinstance(f, BaseField)
        if f.section is not None and f.section in sections:
            label = sections[f.section].label or f.section
        else:
            label = f.label or name
        if label not in found:
            found.append(label)
    return found


def _phase(phase: str | None) -> str | None:
    """`any` (the schema's default) is no phase."""
    return None if phase in (None, "any") else phase


def _date_field(entity: Entity) -> str:
    return entity.date_field or "date"


def _day(record: Mapping[str, Value], entity: Entity) -> dt.date | None:
    value: Any = record.get(_date_field(entity))
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, dt.date) else None


def _sorted(entity: Entity, records: list[Mapping[str, Value]]) -> list[Mapping[str, Value]]:
    """A day's records by their other key parts (session 1, then 2)."""
    parts = [p for p in entity.key or [] if p != _date_field(entity)]
    return sorted(records, key=lambda r: tuple(str(r.get(p) or "") for p in parts))
