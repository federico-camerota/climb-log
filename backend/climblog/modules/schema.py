# SPDX-License-Identifier: GPL-3.0-or-later
"""Meta-schema of module YAML files (design/03-module-framework.md §2, D-041).

The pydantic models check the shape of each part (unknown keys, field types and their options).
References between parts (an entity's key, a field's scale) are checked in `checks.py`.
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
    visible_if: str | None = None  # condition on other fields, checked in checks.py
    retired: bool = False  # hidden from forms; column and data kept (§3)
    renamed_from: Key | None = None


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


class TemplateUse(Strict):
    """A field entry that expands a template: `ph_pre_: {template: soreness, section: ph_pre}`
    adds `ph_pre_fingers`, `ph_pre_forearms`, … in its place. Only placement can be set here."""

    template: Key
    section: str | None = None
    phase: Phase | None = None


class ReferenceTemplateUse(BaseModel):
    """`q_: {template_from_reference: questions, ...}`: one field per reference row (q1..q20).
    The rows live in the sheet, so this expands once reference tables exist (M5)."""

    model_config = ConfigDict(extra="allow", frozen=True)
    template_from_reference: str


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
    if "template" in value:
        return "template field"
    if "template_from_reference" in value:
        return "reference template field"
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
    | Annotated[TemplateUse, Tag("template field")]
    | Annotated[ReferenceTemplateUse, Tag("reference template field")],
    Discriminator(
        _field_kind,
        custom_error_type="field_type",
        custom_error_message="missing or unknown field `type`; expected one of: "
        + ", ".join(_FIELD_TAGS),
    ),
]


# ---- Entities and module ----


class Section(Strict):
    """A group of fields. With a `tab`, the entity is split: one tab per section (D-006)."""

    label: str | None = None
    phase: Phase = "any"
    tab: str | None = None


class Parent(Strict):
    """Makes an entity a child (many rows per parent row, e.g. sets of a session; D-025).

    `key` lists the parent key fields repeated in the child's rows; `fixed` gives the rest,
    implied by the child's tab (`Hang sets` → `session_type: Max hangs`; D-032).
    """

    entity: Key
    key: list[Key] = Field(min_length=1)
    fixed: dict[Key, Any] = {}


class Entity(Strict):
    label: str
    tab: str | None = None
    date_field: Key = "date"
    key: list[Key] | None = None  # natural key; None means a generated id (D-015)
    id_prefix: Key | None = None
    fields: dict[Key, ModuleField] = Field(min_length=1)
    derived: Unchecked = {}  # #10
    rules: Unchecked = {}
    sections: dict[Key, Section] = {}
    anchor_tab: str | None = None  # split entities: rows of other tabs need a row here
    parent: Parent | None = None

    @property
    def is_split(self) -> bool:
        return any(section.tab for section in self.sections.values())

    def tab_fields(self) -> dict[str, list[str]]:
        """Columns of each tab, in order. Key fields are repeated on every tab of a split entity.

        Only meaningful for a checked module (`load_module` returns one).
        """
        if not self.is_split:
            assert self.tab is not None
            return {self.tab: list(self.fields)}
        key = self.key or []
        tabs = {s.tab: list(key) for s in self.sections.values() if s.tab}
        for name, field in self.fields.items():
            if name not in key and isinstance(field, BaseField) and field.section:
                tab = self.sections[field.section].tab
                assert tab is not None
                tabs[tab].append(name)
        return tabs

    @property
    def main_tab(self) -> str:
        """The tab every record has a row in: `tab`, or `anchor_tab` (first section's tab)."""
        tab = self.tab or self.anchor_tab or next(iter(self.tab_fields()))
        return tab


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
    templates: dict[Key, dict[Key, ModuleField]] = {}
    program: Unchecked | None = None  # M5
    reference: Unchecked | None = None  # M5
    forms: Unchecked | None = None  # M3
    views: Unchecked | None = None  # M3, M4
    aggregates: Unchecked | None = None  # M5
    recommendation: Unchecked | None = None  # M3
