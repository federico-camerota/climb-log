# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks across the parts of a module, and template expansion (03-module-framework.md §2.1b).

The models in `schema.py` see one part at a time. These checks see the whole module: an entity's
key, a field's scale, template uses, sections and tabs, parents, `visible_if` conditions and
derived fields (`derived.py`). They
run on the module as written, so every problem has a path that exists in the YAML file;
`expand_templates` runs only once they pass.
"""

from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import Any

from climblog.expr import Env, ExprError, FieldMeta, NameInfo, prepare
from climblog.expr.nodes import ValueType
from climblog.grades import SUPPORTED
from climblog.modules.derived import DerivedPlan, check_derived
from climblog.modules.schema import (
    BaseField,
    ChoiceField,
    DateField,
    Entity,
    GradeField,
    Module,
    NumericScale,
    OrdinalScale,
    Problem,
    ReferenceTemplateUse,
    RefField,
    ScaleField,
    TemplateUse,
    YamlPath,
)

# Columns the app adds to every tab (04-storage.md §1).
RESERVED_FIELDS = frozenset({"updated_at", "deleted"})
# Tabs the app manages itself (04-storage.md §1); compared case-insensitively, like Excel does.
RESERVED_TABS = frozenset({"_meta", "_settings", "summary", "readme"})
_TAB_FORBIDDEN_CHARS = set("[]:*?/\\")
_TAB_MAX_LENGTH = 31  # Excel's limit
# The value an expression sees for each field or setting type; the others are text.
_VALUE_TYPES: dict[str, ValueType] = {
    "date": "date",
    "datetime": "date",
    "time": "time",
    "number": "number",
    "integer": "number",
    "scale": "number",
    "duration": "number",
    "percent": "number",
    "bool": "bool",
    "text": "text",
}


def cross_check(module: Module) -> list[Problem]:
    """Check references between parts of a module that the models alone cannot see."""
    problems: list[Problem] = []
    for key, value in (module.model_extra or {}).items():
        if not key.endswith("_levels"):
            problems.append(Problem((key,), "unknown key (typo?)"))
        elif not (isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
            problems.append(Problem((key,), "a level list must be a list of names"))

    for t_name, template in module.templates.items():
        for f_name, field in template.items():
            f_at: YamlPath = ("templates", t_name, f_name)
            if isinstance(field, TemplateUse | ReferenceTemplateUse):
                problems.append(Problem(f_at, "a template cannot use another template"))
                continue
            if field.section is not None:
                problems.append(
                    Problem((*f_at, "section"), "set the section where the template is used")
                )
            problems += _check_field(module, field, f_at)

    tabs: dict[str, tuple[str, YamlPath]] = {}  # casefolded tab → (entity, where it is set)
    for e_name, entity in module.entities.items():
        at: YamlPath = ("entities", e_name)
        problems += _check_entity(module, e_name, entity)
        for tab, tab_at in _tabs(entity, at):
            problems += _check_tab_name(tab, tab_at)
            other = tabs.setdefault(tab.casefold(), (e_name, tab_at))[0]
            if other != e_name:
                problems.append(Problem(tab_at, f"tab '{tab}' is already used by entity '{other}'"))
    return problems


def expand_templates(module: Module) -> Module:
    """Replace each template use with the fields it adds. Call only on a checked module."""
    entities = {
        name: entity.model_copy(
            update={"fields": {key: field for key, field, _ in _expanded(module, name, entity)}}
        )
        for name, entity in module.entities.items()
    }
    return module.model_copy(update={"entities": entities})


def _expanded(module: Module, e_name: str, entity: Entity) -> Iterator[tuple[str, Any, YamlPath]]:
    """Fields with template uses expanded in place: (key, field, path of the entry in the YAML).

    Uses of unknown templates are skipped (reported by `_check_entity`). Reference templates
    stay as they are until M5.
    """
    for key, field in entity.fields.items():
        at: YamlPath = ("entities", e_name, "fields", key)
        if not isinstance(field, TemplateUse):
            yield key, field, at
            continue
        placement = {k: v for k in ("section", "phase") if (v := getattr(field, k)) is not None}
        for t_key, t_field in module.templates.get(field.template, {}).items():
            if isinstance(t_field, BaseField):
                yield key + t_key, t_field.model_copy(update=placement), at


def _check_entity(module: Module, e_name: str, entity: Entity) -> list[Problem]:
    problems: list[Problem] = []
    at: YamlPath = ("entities", e_name)
    key = entity.key or []

    fields: dict[str, Any] = {}
    renamed: dict[str, str] = {}
    for f_key, field, f_at in _expanded(module, e_name, entity):
        if f_key in fields:
            problems.append(Problem(f_at, f"field '{f_key}' is defined twice (template use?)"))
        fields[f_key] = field
        if isinstance(field, TemplateUse | ReferenceTemplateUse):
            continue
        if f_key in RESERVED_FIELDS:
            problems.append(Problem(f_at, f"'{f_key}' is reserved for a column the app adds"))
        if field.retired and (f_key in key or field.required):
            problems.append(Problem(f_at, "a key or required field cannot be retired"))
        if field.renamed_from is not None:
            if field.renamed_from in renamed:
                other = renamed[field.renamed_from]
                problems.append(
                    Problem(f_at, f"'{other}' is already renamed from '{field.renamed_from}'")
                )
            renamed[field.renamed_from] = f_key
        problems += _check_section(entity, f_key, field, f_at)

    for f_key, field in entity.fields.items():
        f_at = (*at, "fields", f_key)
        if isinstance(field, TemplateUse) and field.template not in module.templates:
            known = ", ".join(module.templates) or "none defined"
            problems.append(
                Problem(
                    (*f_at, "template"), f"unknown template '{field.template}' (known: {known})"
                )
            )
        elif isinstance(field, BaseField):
            problems += _check_field(module, field, f_at)
    for old, new in renamed.items():
        if old in fields:
            problems.append(
                Problem((*at, "fields", new, "renamed_from"), f"'{old}' is still a field")
            )

    env = expression_env(module, fields, entity.date_field)
    for f_key, field, f_at in _expanded(module, e_name, entity):
        if isinstance(field, BaseField) and field.visible_if is not None:
            problems += _check_visible_if(env, f_key, field.visible_if, (*f_at, "visible_if"))
    for d_key in entity.derived:
        if d_key in RESERVED_FIELDS:
            problems.append(
                Problem((*at, "derived", d_key), f"'{d_key}' is reserved for a column the app adds")
            )
    problems += _derived_plan(module, e_name, derived_env(module, e_name))[1]

    date_field = fields.get(entity.date_field)
    if not isinstance(date_field, DateField) or date_field.type == "time":
        problems.append(
            Problem(
                (*at, "date_field") if "date_field" in entity.model_fields_set else at,
                f"date field '{entity.date_field}' must be a field of type date or datetime",
            )
        )
    for i, part in enumerate(key):
        if part not in fields:
            problems.append(Problem((*at, "key", i), f"key field '{part}' is not a field"))

    problems += _check_layout(entity, at)
    if entity.parent is not None:
        problems += _check_parent(module, e_name, entity, fields)
    return problems


def expression_env(module: Module, fields: Mapping[str, Any], date_field: str) -> Env:
    """What expressions in an entity can use: its stored fields (as written) and the settings."""
    names: dict[str, NameInfo] = {}
    for key, field in fields.items():
        if not isinstance(field, BaseField):
            continue
        scale = module.scales.get(field.scale) if isinstance(field, ScaleField) else None
        choices = None
        if isinstance(field, ChoiceField) and not field.allow_other:
            ordinal = module.scales.get(field.scale) if field.scale else None
            choices = field.choices or (
                ordinal.choices if isinstance(ordinal, OrdinalScale) else None
            )
        names[key] = NameInfo(
            _VALUE_TYPES.get(field.type, "text"),
            scale=(scale.min, scale.max) if isinstance(scale, NumericScale) else None,
            choices=tuple(choices) if choices else None,
            field=FieldMeta(
                field.type, field.section, tuple(field.tags), field.since, field.retired
            ),
        )
    settings = {key: _VALUE_TYPES[s.type] for key, s in module.settings.items()}
    return Env(names, settings, date_field)


def derived_env(module: Module, e_name: str) -> Env:
    """What derived fields can use: `expression_env`, plus other records (D-045).

    The parent's stored fields (`parent.x`), each child entity's stored fields and derived
    values (`children(e).x`), and every entity's stored fields (`last(e.x, ...)`).
    """
    entities = {
        name: expression_env(module, _fields(module, name), other.date_field).names
        for name, other in module.entities.items()
    }
    children = {}
    for name, other in module.entities.items():
        if other.parent is not None and other.parent.entity == e_name and name != e_name:
            plan, _ = _derived_plan(module, name, _record_env(module, name, entities))
            children[name] = {**entities[name], **plan.names}  # its problems: reported for it
    return replace(_record_env(module, e_name, entities), children=children)


def derived_plan(module: Module, e_name: str) -> DerivedPlan:
    """The derived fields of an entity of a loaded module, ready to compute."""
    plan, problems = _derived_plan(module, e_name, derived_env(module, e_name))
    assert not problems, problems  # `load_module` reported them
    return plan


def _record_env(module: Module, e_name: str, entities: Mapping[str, Mapping[str, NameInfo]]) -> Env:
    """The entity's fields, the settings, the parent's fields and the other entities."""
    entity = module.entities[e_name]
    env = expression_env(module, _fields(module, e_name), entity.date_field)
    parent = entities.get(entity.parent.entity) if entity.parent is not None else None
    return replace(env, parent=parent, entities=entities)


def _derived_plan(module: Module, e_name: str, env: Env) -> tuple[DerivedPlan, list[Problem]]:
    entity = module.entities[e_name]
    defer_fields = _has_reference_fields(entity)
    return check_derived(module, e_name, entity.derived, env, defer_fields=defer_fields)


def _fields(module: Module, e_name: str) -> dict[str, Any]:
    """An entity's fields with templates expanded (works before and after `expand_templates`)."""
    return {key: field for key, field, _ in _expanded(module, e_name, module.entities[e_name])}


def _has_reference_fields(entity: Entity) -> bool:
    """Fields made from a reference table's rows (`template_from_reference`, M5)."""
    return any(isinstance(field, ReferenceTemplateUse) for field in entity.fields.values())


def _check_visible_if(env: Env, f_key: str, source: str, at: YamlPath) -> list[Problem]:
    """A condition on the record's other fields (03-module-framework.md §2.1b)."""
    try:
        checked = prepare(source, env)
    except ExprError as error:
        return [Problem(at, str(error))]
    if checked.kind.many or checked.kind.type != "bool":
        return [Problem(at, f"visible_if must be a condition (yes/no), not {checked.kind.type}")]
    if f_key in checked.names:
        return [Problem(at, "visible_if cannot depend on its own field")]
    return []


def _check_field(module: Module, field: BaseField, at: YamlPath) -> list[Problem]:
    """Checks that depend only on the field and the module (run once per template field)."""
    if isinstance(field, GradeField):
        return [
            Problem((*at, "systems", i), f"grade system '{system}' is not supported yet "
                    f"(supported: {', '.join(SUPPORTED)})")
            for i, system in enumerate(field.systems)
            if system not in SUPPORTED
        ]  # fmt: skip
    if isinstance(field, ScaleField | ChoiceField) and field.scale is not None:
        return _check_scale_use(module, field, (*at, "scale"))
    if isinstance(field, RefField) and field.reference not in (module.reference or {}):
        known = ", ".join(sorted(module.reference or {})) or "none defined"
        return [
            Problem(
                (*at, "reference"), f"unknown reference table '{field.reference}' (known: {known})"
            )
        ]
    return []


def _check_scale_use(
    module: Module, field: ScaleField | ChoiceField, at: YamlPath
) -> list[Problem]:
    assert field.scale is not None
    scale = module.scales.get(field.scale)
    if scale is None:
        known = ", ".join(module.scales) or "none defined"
        return [Problem(at, f"unknown scale '{field.scale}' (known: {known})")]
    if isinstance(field, ScaleField) and isinstance(scale, OrdinalScale):
        return [Problem(at, f"scale '{field.scale}' is ordinal; use a choice field for it")]
    if isinstance(field, ChoiceField) and isinstance(scale, NumericScale):
        return [Problem(at, f"a choice field needs an ordinal scale; '{field.scale}' is numeric")]
    return []


def _check_section(entity: Entity, f_key: str, field: BaseField, at: YamlPath) -> list[Problem]:
    """`section` names a section of the entity; in a split entity every field needs one.

    Key fields are on every tab; `section: "*"` says so explicitly and is allowed only on them.
    """
    is_key = f_key in (entity.key or [])
    if field.section == "*":
        return [] if is_key else [Problem(at, "only key fields can be on every tab (`*`)")]
    if field.section is not None and field.section not in entity.sections:
        known = ", ".join(entity.sections) or "none defined"
        return [Problem(at, f"unknown section '{field.section}' (known: {known})")]
    if field.section is None and entity.is_split and not is_key:
        return [Problem(at, "the entity is split across tabs, so this field needs a `section`")]
    return []


def _check_layout(entity: Entity, at: YamlPath) -> list[Problem]:
    """Where the entity's rows live: one `tab`, or one tab per section (split entity)."""
    problems: list[Problem] = []
    if not entity.is_split:
        if entity.tab is None:
            problems.append(Problem(at, "an entity needs a `tab` (or sections with tabs)"))
        if entity.anchor_tab is not None:
            problems.append(Problem((*at, "anchor_tab"), "only split entities have an anchor tab"))
        return problems

    if entity.tab is not None:
        problems.append(Problem((*at, "tab"), "a split entity gets its tabs from its sections"))
    for s_name, section in entity.sections.items():
        if section.tab is None:
            problems.append(
                Problem((*at, "sections", s_name), "in a split entity every section needs a tab")
            )
    if not entity.key:
        problems.append(Problem(at, "a split entity needs a natural `key` to join its tabs"))
    tabs = {s.tab for s in entity.sections.values()}
    if entity.anchor_tab is not None and entity.anchor_tab not in tabs:
        problems.append(
            Problem((*at, "anchor_tab"), f"'{entity.anchor_tab}' is not a tab of this entity")
        )
    return problems


def _check_parent(
    module: Module, e_name: str, entity: Entity, fields: dict[str, Any]
) -> list[Problem]:
    assert entity.parent is not None
    parent = entity.parent
    at: YamlPath = ("entities", e_name, "parent")
    if parent.entity == e_name:
        return [Problem((*at, "entity"), "an entity cannot be its own parent")]
    target = module.entities.get(parent.entity)
    if target is None:
        known = ", ".join(n for n in module.entities if n != e_name)
        return [Problem((*at, "entity"), f"unknown entity '{parent.entity}' (known: {known})")]
    if target.parent is not None:
        return [Problem((*at, "entity"), f"'{parent.entity}' is itself a child (one level only)")]
    if not target.key:
        return [Problem((*at, "entity"), f"'{parent.entity}' has no natural key to refer to")]

    problems: list[Problem] = []
    linked = [*parent.key, *parent.fixed]
    if sorted(linked) != sorted(target.key):
        problems.append(
            Problem(
                at,
                f"`key` and `fixed` must together be the key of '{parent.entity}' "
                f"({', '.join(target.key)}), each field once",
            )
        )
    for i, part in enumerate(parent.key):
        if part not in fields or part not in (entity.key or []):
            problems.append(
                Problem((*at, "key", i), f"'{part}' must be a field in this entity's key")
            )
    for f_key, value in parent.fixed.items():
        field = target.fields.get(f_key)
        if isinstance(field, ChoiceField) and field.choices and value not in field.choices:
            problems.append(
                Problem((*at, "fixed", f_key), f"{value!r} is not a choice of '{f_key}'")
            )
    return problems


def _tabs(entity: Entity, at: YamlPath) -> Iterator[tuple[str, YamlPath]]:
    """Each tab name the entity uses, once, with where it is set."""
    if entity.tab is not None:
        yield entity.tab, (*at, "tab")
    seen: set[str] = set()
    for s_name, section in entity.sections.items():
        if section.tab is not None and section.tab not in seen:
            seen.add(section.tab)
            yield section.tab, (*at, "sections", s_name, "tab")


def _check_tab_name(tab: str, at: YamlPath) -> list[Problem]:
    if tab.casefold() in RESERVED_TABS:
        return [Problem(at, f"'{tab}' is a tab the app manages itself")]
    if not tab.strip() or len(tab) > _TAB_MAX_LENGTH:
        return [Problem(at, f"a tab name must be 1 to {_TAB_MAX_LENGTH} characters")]
    bad = sorted(_TAB_FORBIDDEN_CHARS & set(tab))
    if bad or tab.startswith("'") or tab.endswith("'"):
        shown = " ".join(bad) or "'"
        return [Problem(at, f"a tab name cannot contain {shown} (spreadsheet rule)")]
    return []
