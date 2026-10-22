# SPDX-License-Identifier: GPL-3.0-or-later
"""Meta-schema of module YAML files (design/03-module-framework.md §2, D-041).

The pydantic models check the shape of each part (unknown keys, field types and their options).
`cross_check` then checks references between parts (an entity's key, a field's scale) and
returns problems with their YAML path, so the loader can point at the line.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StringConstraints,
    Tag,
    model_validator,
)

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
"""Ids of modules, fields, scales and settings: snake_case."""

YamlPath = tuple[str | int, ...]

# Blocks validated in later issues and milestones (#8, M3 to M5): accepted as they are until then.
Unchecked = dict[str, Any]

Direction = Literal["higher_better", "lower_better", "neutral"]
Phase = Literal["pre", "post", "next_day", "any"]
GradeSystem = Literal["french", "uiaa", "yds", "font", "v", "gym"]

# Columns the app adds to every tab (04-storage.md §1).
RESERVED_FIELDS = frozenset({"updated_at", "deleted"})


@dataclass(frozen=True)
class Problem:
    """One thing wrong in a module file. Line and column are 1-based, set by the loader."""

    path: YamlPath
    message: str
    line: int | None = None
    column: int | None = None


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _check_range(low: float | None, high: float | None) -> None:
    if low is not None and high is not None and low > high:
        raise ValueError(f"min ({low:g}) is greater than max ({high:g})")


# ---- Scales ----


class NumericScale(Strict):
    type: Literal["numeric"] = "numeric"
    min: float
    max: float
    direction: Direction

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.min >= self.max:
            raise ValueError(f"min ({self.min:g}) must be less than max ({self.max:g})")
        return self


class OrdinalScale(Strict):
    type: Literal["ordinal"]
    choices: list[str] = Field(min_length=2)
    direction: Direction


# Union tags contain a space, so they never collide with YAML keys in error locations.
def _scale_kind(value: Any) -> str:
    is_ordinal = isinstance(value, dict) and value.get("type") == "ordinal"
    return "ordinal scale" if is_ordinal else "numeric scale"


Scale = Annotated[
    Annotated[NumericScale, Tag("numeric scale")] | Annotated[OrdinalScale, Tag("ordinal scale")],
    Discriminator(_scale_kind),
]


# ---- Settings ----

_SETTING_VALUE_TYPES: dict[str, tuple[type, ...]] = {
    "number": (int, float),
    "integer": (int,),
    "date": (dt.date,),
    "text": (str,),
    "bool": (bool,),
}


class Setting(Strict):
    type: Literal["number", "integer", "date", "text", "bool"]
    default: Any  # required: the app needs a value before the sheet's _settings tab exists
    label: str | None = None
    help: str | None = None

    @model_validator(mode="after")
    def _default_matches_type(self) -> Self:
        expected = _SETTING_VALUE_TYPES[self.type]
        # bool is a subclass of int in Python, so `default: true` is not a number.
        is_bool = isinstance(self.default, bool)
        if not isinstance(self.default, expected) or (is_bool and self.type != "bool"):
            raise ValueError(f"default {self.default!r} is not a valid {self.type}")
        return self


# ---- Fields (03-module-framework.md §2.1) ----


class BaseField(Strict):
    label: str | None = None
    help: str | None = None
    required: bool = False
    default: Any = None
    phase: Phase = "any"
    section: str | None = None
    tags: list[Key] = []
    since: dt.date | None = None
    from_: str | None = Field(default=None, alias="from")  # prefilled from another module
    hidden_in_form: bool = False


class DateField(BaseField):
    type: Literal["date", "datetime", "time"]


class NumberField(BaseField):
    type: Literal["number", "integer"]
    min: float | None = None
    max: float | None = None
    step: float | None = Field(default=None, gt=0)
    unit: str | None = None

    @model_validator(mode="after")
    def _range(self) -> Self:
        _check_range(self.min, self.max)
        return self


class ScaleField(BaseField):
    type: Literal["scale"]
    scale: Key


class ChoiceField(BaseField):
    type: Literal["choice"]
    choices: list[str] | None = Field(default=None, min_length=1)
    scale: Key | None = None  # an ordinal scale supplies the choices instead
    allow_other: bool = False
    choice_map: dict[str, str] = {}  # legacy value → current choice

    @model_validator(mode="after")
    def _choices_or_scale(self) -> Self:
        if (self.choices is None) == (self.scale is None):
            raise ValueError("give either `choices` or an ordinal `scale`, not both or neither")
        return self


class MultichoiceField(BaseField):
    type: Literal["multichoice"]
    choices: list[str] = Field(min_length=1)
    allow_other: bool = False


class BoolField(BaseField):
    type: Literal["bool"]


class TextField(BaseField):
    type: Literal["text"]
    multiline: bool = False
    searchable: bool = True
    suggest_from_history: bool = False


class GradeField(BaseField):
    type: Literal["grade"]
    systems: list[GradeSystem] = Field(min_length=1)  # auto-detected among these (D-017)


class DurationField(BaseField):
    type: Literal["duration"]  # minutes
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _range(self) -> Self:
        _check_range(self.min, self.max)
        return self


class RefField(BaseField):
    type: Literal["ref"]
    reference: Key


class PercentField(BaseField):
    type: Literal["percent"]


class TemplateUse(BaseModel):
    """A field entry that expands a template (`ph_pre_: {template: soreness}`). Checked in #8."""

    model_config = ConfigDict(extra="allow", frozen=True)
    template: str | None = None
    template_from_reference: str | None = None


# `type:` value → model tag. Date-like and number-like types share a model.
_FIELD_TAGS = {
    "date": "date",
    "datetime": "date",
    "time": "date",
    "number": "number",
    "integer": "number",
    "scale": "scale",
    "choice": "choice",
    "multichoice": "multichoice",
    "bool": "bool",
    "text": "text",
    "grade": "grade",
    "duration": "duration",
    "ref": "ref",
    "percent": "percent",
}


def _field_kind(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    if "template" in value or "template_from_reference" in value:
        return "template field"
    kind = _FIELD_TAGS.get(value.get("type"))  # type: ignore[arg-type]
    return f"{kind} field" if kind else None


ModuleField = Annotated[
    Annotated[DateField, Tag("date field")]
    | Annotated[NumberField, Tag("number field")]
    | Annotated[ScaleField, Tag("scale field")]
    | Annotated[ChoiceField, Tag("choice field")]
    | Annotated[MultichoiceField, Tag("multichoice field")]
    | Annotated[BoolField, Tag("bool field")]
    | Annotated[TextField, Tag("text field")]
    | Annotated[GradeField, Tag("grade field")]
    | Annotated[DurationField, Tag("duration field")]
    | Annotated[RefField, Tag("ref field")]
    | Annotated[PercentField, Tag("percent field")]
    | Annotated[TemplateUse, Tag("template field")],
    Discriminator(
        _field_kind,
        custom_error_type="field_type",
        custom_error_message="missing or unknown field `type`; expected one of: "
        + ", ".join(_FIELD_TAGS),
    ),
]


# ---- Entities and module ----


class Entity(Strict):
    label: str
    tab: str | None = None
    date_field: Key = "date"
    key: list[Key] | None = None  # natural key; None means a generated id (D-015)
    id_prefix: Key | None = None
    fields: dict[Key, ModuleField] = Field(min_length=1)
    derived: Unchecked = {}  # expressions: #9, #10
    rules: Unchecked = {}
    # Split and child entities: #8.
    sections: Unchecked | None = None
    anchor_tab: str | None = None
    parent: Unchecked | None = None


class Module(Strict):
    # Extra top-level keys are allowed only as named level lists (`reflect_levels`);
    # `cross_check` reports any other one as unknown.
    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)

    module: Key
    name: str
    version: int = Field(ge=1)
    kind: Literal["journal", "program"]
    description: str | None = None
    status_levels: list[str] = []
    settings: dict[Key, Setting] = {}
    scales: dict[Key, Scale] = {}
    entities: dict[Key, Entity] = Field(min_length=1)
    templates: Unchecked | None = None  # #8
    program: Unchecked | None = None  # M5
    reference: Unchecked | None = None  # M5
    forms: Unchecked | None = None  # M3
    views: Unchecked | None = None  # M3, M4
    aggregates: Unchecked | None = None  # M5
    recommendation: Unchecked | None = None  # M3


def cross_check(module: Module) -> list[Problem]:
    """Check references between parts of a module that the models alone cannot see."""
    problems: list[Problem] = []
    for key, value in (module.model_extra or {}).items():
        if not key.endswith("_levels"):
            problems.append(Problem((key,), "unknown key (typo?)"))
        elif not (isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
            problems.append(Problem((key,), "a level list must be a list of names"))

    references = set(module.reference or {})
    for e_name, entity in module.entities.items():
        at: YamlPath = ("entities", e_name)
        fields = entity.fields

        date_field = fields.get(entity.date_field)
        if not isinstance(date_field, DateField) or date_field.type == "time":
            problems.append(
                Problem(
                    (*at, "date_field") if "date_field" in entity.model_fields_set else at,
                    f"date field '{entity.date_field}' must be a field of type date or datetime",
                )
            )
        for i, part in enumerate(entity.key or []):
            if part not in fields:
                problems.append(Problem((*at, "key", i), f"key field '{part}' is not a field"))

        for f_name, field in fields.items():
            f_at = (*at, "fields", f_name)
            if f_name in RESERVED_FIELDS:
                problems.append(Problem(f_at, f"'{f_name}' is reserved for a column the app adds"))
            if isinstance(field, ScaleField | ChoiceField) and field.scale is not None:
                problems += _check_scale_use(module, field, (*f_at, "scale"))
            if isinstance(field, RefField) and field.reference not in references:
                known = ", ".join(sorted(references)) or "none defined"
                problems.append(
                    Problem(
                        (*f_at, "reference"),
                        f"unknown reference table '{field.reference}' (known: {known})",
                    )
                )
    return problems


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
