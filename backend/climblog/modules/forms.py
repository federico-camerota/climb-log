# SPDX-License-Identifier: GPL-3.0-or-later
"""A module's forms (`forms:`, 03 §2.6) and what is due on a day: the Today page (D-080).

`form_fields` is the rule the frontend's forms follow (`frontend/src/forms/schema.ts`): a form
shows the fields of its sections (in its phase), plus fields of other sections whose own
`phase` is the form's; key and retired fields are left out.

What is due on a day: when no form's entity has a record that day, the module's entry forms
(no phase, or `pre`) are listed as missing, any one of them (a session or a rest day); once
there are records, each record's forms are listed (pre, then post), done / partial / missing by
how many of their scored fields (everything but text) are filled. A field hidden by its
`visible_if` doesn't count (`hidden`), as the form doesn't show it.

A form whose entity is dated by a week (a training plan, D-110) is never due: its records of
the day's week are listed instead (`Day.plan`), today's first, then by day, those without a
day last.
"""

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from climblog.expr import Value, evaluate, prepare
from climblog.modules.checks import expression_env
from climblog.modules.schema import BaseField, ChoiceField, DateField, Entity, Module, TextField

DONE, PARTIAL, MISSING = "done", "partial", "missing"
ANOTHER = "another"  # a form with `repeat: true`: one more record can be added (D-107)


@dataclass(frozen=True)
class Form:
    name: str
    entity: str
    phase: str | None
    sections: tuple[str, ...] | None  # None: every field of the entity
    repeats: bool  # child rows in the form (finger-strength sets): the form's own fields count
    another: bool = False  # `repeat: true`: many records a day (meals), Today offers one more


@dataclass(frozen=True)
class Due:
    """One form to fill on the day, for one record (or a new one)."""

    form: str
    label: str  # "Pre session"
    key: dict[str, Value]  # the record's key; just the date for a new record
    status: str  # done / partial / missing, or another (a repeated form's next record)
    missing: list[str]  # the sections (or fields) still to fill
    log_check: Value = None  # the record's own check, when the entity has one (`log_check`)


@dataclass(frozen=True)
class Planned:
    """A planned session of the day's week (D-110)."""

    form: str  # the form that edits it
    key: dict[str, Value]  # its key, the week as typed (`2026-W47`)
    day: str | None  # Mon…Sun, or none: sometime that week
    line: str  # "Tue · Climbing · Limit bouldering"
    today: bool  # planned for the day itself


@dataclass(frozen=True)
class Day:
    """A module's forms on a day, and its latest record up to it."""

    items: list[Due]
    any_one: bool  # nothing logged yet: the items are alternatives (a session or a rest day)
    last: dt.date | None  # the latest record of the first form's entity, on or before the day
    last_label: str | None = None  # that entity's label, e.g. "Session"
    notes: list[str] = field(default_factory=list)  # forms left out, and why
    plan: list[Planned] = field(default_factory=list)  # the week's planned sessions (D-110)
    plan_form: str | None = None  # the form that plans one more
    plan_week: str | None = None  # the day's week, `2026-W47`
    plan_field: str | None = None  # the field the week goes in (the form's date field)


def forms_of(module: Module) -> dict[str, Form]:
    """The module's forms (checked at load: their entity, sections and child forms exist)."""
    return {
        name: Form(
            name,
            form.entity,
            form.phase,
            tuple(form.sections) if form.sections is not None else None,
            bool(form.children),
            form.repeat,
        )
        for name, form in (module.forms or {}).items()
    }


def hidden(
    module: Module, entity: str, values: Mapping[str, Value], settings: Mapping[str, Value]
) -> list[str]:
    """The entity's fields hidden by their `visible_if` for these values: the condition isn't
    yes (03 §2.1b). A form doesn't show them, and they don't count as missing."""
    ent = module.entities[entity]
    env = expression_env(module, ent.fields, ent.date_field)
    return [
        name
        for name, f in ent.fields.items()
        if isinstance(f, BaseField)
        and f.visible_if is not None
        and evaluate(prepare(f.visible_if, env), values, settings) is not True
    ]


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
        if form.phase == "next_day":  # only the next-morning fields (D-114)
            same_phase = phase == "next_day"
        else:
            same_phase = form.phase is None or phase is None or phase == form.phase
        pulled = own is not None and own == form.phase  # e.g. the session's duration
        if (in_form and same_phase) or pulled:
            found.append(name)
    return found


def due(
    module: Module,
    tables: Mapping[str, Sequence[Mapping[str, Value]]],
    day: dt.date,
    settings: Mapping[str, Value] | None = None,
) -> Day:
    """The module's forms on `day`. `tables[entity]` holds each record's stored and derived
    values (deleted ones left out)."""
    forms = forms_of(module)
    notes: list[str] = []
    mornings = _next_mornings(module, forms.values(), tables, day, settings or {})
    usable = [f for f in forms.values() if f.phase != "next_day"]
    planning = [f for f in usable if by_week(module.entities[f.entity])]
    usable = [f for f in usable if f not in planning]
    plan = _plan(module, planning, tables, day)
    if not usable:
        return Day(mornings, False, None, notes=notes, **plan)
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
                    status, missing = _status(module, f, record, day, settings or {})
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
        for f in entry:  # a repeated form: after the day's records, one more (D-107)
            if f.another and on_day.get(f.entity):
                date = _date_field(module.entities[f.entity])
                items.append(Due(f.name, form_label(f.name), {date: day}, ANOTHER, []))
    first = module.entities[usable[0].entity]
    dates = [
        d
        for r in tables.get(usable[0].entity, ())
        if (d := _day(r, first)) is not None and d <= day
    ]
    return Day(
        items + mornings,
        not any(on_day.values()) and len(entry) > 1,
        max(dates, default=None),
        first.label,
        notes,
        **plan,
    )


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
NEXT_MORNING_DAYS = 3  # a next-morning item is asked for until filled, up to this many days (D-114)


def _next_mornings(
    module: Module,
    forms: Iterable[Form],
    tables: Mapping[str, Sequence[Mapping[str, Value]]],
    day: dt.date,
    settings: Mapping[str, Value],
) -> list[Due]:
    """The `phase: next_day` forms of the records of the last few days (D-114) still to fill:
    "Next morning · Check-in of Tue 18", the latest record first."""
    items: list[Due] = []
    for f in (f for f in forms if f.phase == "next_day"):
        entity = module.entities[f.entity]
        for back in range(1, NEXT_MORNING_DAYS + 1):
            then = day - dt.timedelta(days=back)
            records = [r for r in tables.get(f.entity, ()) if _day(r, entity) == then]
            for record in _sorted(entity, records):
                status, missing = _status(module, f, record, then, settings)
                if status == DONE:
                    continue
                key = {part: record.get(part) for part in entity.key or [_date_field(entity)]}
                when = f"{WEEKDAYS[then.weekday()]} {then.day}"
                label = f"{form_label(f.name)} · {entity.label} of {when}"
                items.append(Due(f.name, label, key, status, missing, record.get("log_check")))
    return items


def by_week(entity: Entity) -> bool:
    """Whether the entity's records are dated by a week (a plan, D-110)."""
    dating = entity.fields.get(_date_field(entity))
    return isinstance(dating, DateField) and dating.type == "week"


def _plan(
    module: Module,
    forms: Sequence[Form],
    tables: Mapping[str, Sequence[Mapping[str, Value]]],
    day: dt.date,
) -> dict[str, Any]:
    """The planned sessions of the day's week, today's first, then by day, those without a day
    last; and the form that plans one more."""
    if not forms:
        return {}
    from climblog.modules.program import week_text  # it imports the schema

    monday = day - dt.timedelta(days=day.weekday())
    today = WEEKDAYS[day.weekday()]
    found: list[tuple[tuple[int, int, int], Planned]] = []
    for e_name in dict.fromkeys(f.entity for f in forms):
        entity = module.entities[e_name]
        form = next(f.name for f in forms if f.entity == e_name)
        date = _date_field(entity)
        weekday = _weekday_field(entity)
        keys = entity.key or [date]
        shown = [n for n in entity.fields if n not in keys and n != weekday]
        for record in _sorted(
            entity, [r for r in tables.get(e_name, ()) if _day(r, entity) == monday]
        ):
            when = record.get(weekday) if weekday else None
            when = when if isinstance(when, str) and when in WEEKDAYS else None
            parts = [when or "Any day"]
            parts += [str(v) for n in shown if (v := record.get(n)) not in (None, "")]
            key = {p: week_text(monday) if p == date else record.get(p) for p in keys}
            order = (
                0 if when == today else 1,
                WEEKDAYS.index(when) if when else len(WEEKDAYS),
                len(found),
            )
            found.append((order, Planned(form, key, when, " · ".join(parts), when == today)))
    return {
        "plan": [planned for _, planned in sorted(found, key=lambda item: item[0])],
        "plan_form": forms[0].name,
        "plan_week": week_text(monday),
        "plan_field": _date_field(module.entities[forms[0].entity]),
    }


def _weekday_field(entity: Entity) -> str | None:
    """The field naming a planned session's day: a choice of Mon…Sun."""
    for name, f in entity.fields.items():
        if isinstance(f, ChoiceField) and tuple(f.choices or ()) == WEEKDAYS:
            return name
    return None


def _status(
    module: Module,
    form: Form,
    record: Mapping[str, Value],
    day: dt.date,
    settings: Mapping[str, Value],
) -> tuple[str, list[str]]:
    """Done when every scored field is filled (text and `optional: true` fields may stay
    blank, and fields hidden by `visible_if` don't count), partial when some are."""
    entity = module.entities[form.entity]
    away = set(hidden(module, form.entity, record, settings))
    if form.phase != "next_day":  # filled the morning after, not on the day (D-114)
        away |= {n for n in entity.fields if _field_phase(entity, n) == "next_day"}
    names = [
        n
        for n in form_fields(module, form)
        if _tracked(entity, n, day) and not _optional(entity, n) and n not in away
    ]
    scored = [n for n in names if not isinstance(entity.fields[n], TextField)] or names
    empty = [n for n in scored if record.get(n) is None]
    if not empty:
        return DONE, []
    status = MISSING if len(empty) == len(scored) else PARTIAL
    return status, _where(module, entity, empty)


def _field_phase(entity: Entity, name: str) -> str | None:
    """The field's own phase, else its section's."""
    f = entity.fields[name]
    if not isinstance(f, BaseField):
        return None
    own = _phase(f.phase)
    if own is not None:
        return own
    section = (entity.sections or {}).get(f.section or "")
    return _phase(section.phase) if section is not None else None


def _tracked(entity: Entity, name: str, day: dt.date) -> bool:
    """Not a field added after the day (`since`)."""
    f = entity.fields[name]
    assert isinstance(f, BaseField)
    return f.since is None or f.since <= day


def _optional(entity: Entity, name: str) -> bool:
    """A field that may stay blank in a done form (`optional: true`)."""
    f = entity.fields[name]
    assert isinstance(f, BaseField)
    return f.optional


def field_label(name: str, f: BaseField) -> str:
    """A field's label as the forms show it (the frontend's `fieldLabel`, without the ↓ of a
    lower-is-better scale): its own `label`, else its name without the section prefix and
    phase, capitalized (`wb_mood_pre` in `wb_pre` → "Mood", `life_stress` → "Life stress")."""
    if f.label is not None:
        return f.label
    words = name.split("_")
    parts = (f.section or "").split("_")
    prefix = words[0]
    sectioned = f.section is not None and f.section != "*"
    if len(words) > 1 and sectioned and (prefix == parts[0] or len(prefix) <= 2):
        words = words[1:]  # wb_mood_pre in wb_pre, rf_good_score in reflect
    phase = _phase(f.phase) or (parts[1] if len(parts) > 1 else None)
    last = len(words) - 1
    words = [w for i, w in enumerate(words) if not (w == phase and i in (0, last))]
    joined = " ".join(words)
    return joined[:1].upper() + joined[1:]


def _where(module: Module, entity: Entity, names: list[str]) -> list[str]:
    """The empty fields' sections, by label, in order (the fields themselves without sections,
    labelled as in the form)."""
    sections = entity.sections or {}
    found: list[str] = []
    for name in names:
        f = entity.fields[name]
        assert isinstance(f, BaseField)
        if f.section is not None and f.section in sections:
            label = sections[f.section].label or f.section
        else:
            label = field_label(name, f)
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
