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
    if isinstance(value, NumericScale | OrdinalScale):  # serialising a loaded module
        return "ordinal scale" if isinstance(value, OrdinalScale) else "numeric scale"
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

# `default: next` on an integer key field: a blank cell is the row's position among the rows
# with the same other key parts, in sheet order (set numbers, D-050).
NEXT = "next"


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
    optional: bool = False  # left blank, its form still counts as done on Today (D-080)

    @model_validator(mode="after")
    def _optional(self) -> Self:
        if self.optional and self.required:
            raise ValueError("a field cannot be both required and optional")
        return self


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
    if isinstance(value, BaseModel):  # serialising a loaded module
        return _MODEL_TAGS.get(type(value))
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


# ---- Derived fields (03-module-framework.md §2.2, D-044) ----
# Expressions are strings here; `derived.py` checks them against the entity's fields.


def _else_kind(value: Any) -> str:
    if isinstance(value, BaseModel):  # serialising a loaded module
        return "else item" if isinstance(value, Otherwise) else "case item"
    return "else item" if isinstance(value, dict) and "else" in value else "case item"


class Band(Strict):
    le: float | str  # a number or an expression (`settings.low_max`)
    label: str


class Case(Strict):
    if_: str = Field(alias="if")
    then: str  # a label, not an expression


class Otherwise(Strict):
    else_: str = Field(alias="else")


BandItem = Annotated[
    Annotated[Band, Tag("case item")] | Annotated[Otherwise, Tag("else item")],
    Discriminator(_else_kind),
]
CaseItem = Annotated[
    Annotated[Case, Tag("case item")] | Annotated[Otherwise, Tag("else item")],
    Discriminator(_else_kind),
]


# `sheet_formula` (03 §2.2b, D-053): true = compiled to a formula column, false = app only,
# "=..." = this formula instead, `{field}` standing for that field's cell in the row.
SheetFormula = bool | Annotated[str, StringConstraints(pattern=r"^=")]


class ExprDerived(Strict):
    expr: str
    require: str | None = None  # the result is blank unless this holds
    sheet_formula: SheetFormula = True


class _Labelled(Strict):
    """A `bands:` or `when:` result: a status on `levels` (default `status_levels`), or text."""

    require: str | None = None
    levels: Key | None = None  # a level list of the module (`reflect_levels`)
    sheet_formula: SheetFormula = True
    type: Literal["text"] | None = None  # a message, not a status

    def items(self) -> list[Band | Case | Otherwise]:
        raise NotImplementedError  # pragma: no cover

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.levels is not None and self.type is not None:
            raise ValueError("give `levels` for a status or `type: text` for a message, not both")
        items = self.items()
        if any(isinstance(item, Otherwise) for item in items[:-1]):
            raise ValueError("`else` must be the last item")
        if len(items) == 1 and isinstance(items[0], Otherwise):
            raise ValueError("an `else` alone is not a rule; write the value as an expression")
        return self

    @property
    def otherwise(self) -> str | None:
        last = self.items()[-1]
        return last.else_ if isinstance(last, Otherwise) else None

    def labels(self) -> list[str]:
        """Every label the result can take, in order, each once."""
        found = [
            item.label if isinstance(item, Band) else item.then
            for item in self.items()
            if not isinstance(item, Otherwise)
        ]
        if self.otherwise is not None:
            found.append(self.otherwise)
        return list(dict.fromkeys(found))


class BandsDerived(_Labelled):
    bands_of: str
    bands: list[BandItem] = Field(min_length=1)

    def items(self) -> list[Band | Case | Otherwise]:
        return list(self.bands)


class WhenDerived(_Labelled):
    when: list[CaseItem] = Field(min_length=1)

    def items(self) -> list[Band | Case | Otherwise]:
        return list(self.when)


class MapDerived(Strict):
    """`map_from: status` + `map: {RED: text, …}`: a text for each value of a status or choice."""

    map_from: Key
    map: dict[str, str] = Field(min_length=1)
    sheet_formula: SheetFormula = True


class PluginDerived(Strict):
    plugin: str  # app-only Python code (§2.3); not checked or computed yet
    sheet_formula: SheetFormula = True  # only a hand-written formula gives it a column


class ReferenceGroupDerived(Strict):
    per_reference_group: Unchecked  # M5


_DERIVED_KEYS = {
    "expr": "expr entry",
    "bands_of": "bands entry",
    "bands": "bands entry",
    "when": "when entry",
    "map_from": "map entry",
    "map": "map entry",
    "plugin": "plugin entry",
    "per_reference_group": "reference group entry",
}


def _derived_kind(value: Any) -> str | None:
    if isinstance(value, str):
        return "plain expression"
    if isinstance(value, BaseModel):  # serialising a loaded module
        return _MODEL_TAGS.get(type(value))
    if isinstance(value, dict):
        return next((_DERIVED_KEYS[k] for k in value if k in _DERIVED_KEYS), None)
    return None


Derived = Annotated[
    Annotated[str, Tag("plain expression")]
    | Annotated[ExprDerived, Tag("expr entry")]
    | Annotated[BandsDerived, Tag("bands entry")]
    | Annotated[WhenDerived, Tag("when entry")]
    | Annotated[MapDerived, Tag("map entry")]
    | Annotated[PluginDerived, Tag("plugin entry")]
    | Annotated[ReferenceGroupDerived, Tag("reference group entry")],
    Discriminator(
        _derived_kind,
        custom_error_type="derived_kind",
        custom_error_message="a derived field is an expression, or has one of: expr, bands_of, "
        "when, map_from, plugin",
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
    derived: dict[Key, Derived] = {}
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


# Model class → its union tag, for serialising a loaded module (the discriminators above read
# dicts when loading YAML, and models when dumping, e.g. for the read API).
_MODEL_TAGS: dict[type, str] = {
    DateField: "date field",
    NumberField: "number field",
    ScaleField: "scale field",
    ChoiceField: "choice field",
    MultichoiceField: "multichoice field",
    BoolField: "bool field",
    TextField: "text field",
    GradeField: "grade field",
    DurationField: "duration field",
    RefField: "ref field",
    PercentField: "percent field",
    TemplateUse: "template field",
    ReferenceTemplateUse: "reference template field",
    ExprDerived: "expr entry",
    BandsDerived: "bands entry",
    WhenDerived: "when entry",
    MapDerived: "map entry",
    PluginDerived: "plugin entry",
    ReferenceGroupDerived: "reference group entry",
}


class RecommendationRule(Strict):
    if_: str | None = Field(None, alias="if")  # None: the last rule, when no other holds
    headline: str | None = None  # e.g. RECOVER; the message alone when there is none
    message: str


class Recommendation(Strict):
    """The next-session recommendation (D-076): values computed for a day, then the first rule
    that holds. The app and the sheet's Summary tab share this one definition (D-071)."""

    label: str = "Suggested next session"
    # Derived entries of the day asked: `date` is that day (TODAY() in the sheet); they read
    # the records with last(e.x, until=date) and window(e.x, days=n, until=date).
    values: dict[Key, Derived] = {}
    rules: list[RecommendationRule] = Field(min_length=1)
    reasons: dict[Key, str] = {}  # value → its label, shown with the result in this order

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if any(rule.if_ is None for rule in self.rules[:-1]):
            raise ValueError("only the last rule can leave out `if`")
        return self


# ---- Views (dashboards, 03 §2.7, D-083) ----


class _Widget(Strict):
    label: str | None = None  # the widget's title


class KpiWidget(_Widget):
    """One number or status: the metric in the latest record, or the days since it."""

    widget: Literal["kpi"]
    metric: str  # `entity.field`, a stored field or a derived value
    agg: Literal["latest", "days_since_latest"] = "latest"


class StatusClass(Strict):
    label: str  # e.g. Wellbeing
    score: str  # `entity.field`
    status: str  # `entity.field`


class StatusBoardWidget(_Widget):
    """Per class: the latest status and score, the average of the last `compare_last` records
    vs the ones before, the direction (`settings.trend_delta`), and the LOW records among the
    last `window` (the legacy Summary - Trends status board)."""

    widget: Literal["status_board"]
    classes: list[StatusClass] = Field(min_length=1)
    compare_last: int = Field(4, ge=1)
    window: int = Field(12, ge=1)


class Series(Strict):
    metric: str  # `entity.field`
    label: str | None = None


class LineWidget(_Widget):
    """Metrics over the records, with the status bands behind them and a rolling mean; the
    last `last` records shown at first (a range picker shows more)."""

    widget: Literal["line"]
    series: list[Series] = Field(min_length=1)
    bands: list[BandItem] = []  # as a derived entry's (`le: settings.low_max`, …)
    rolling: int | None = Field(None, ge=2)
    last: int = Field(12, ge=1)
    split_by: list[str] = []  # one line per combination of these fields: not drawn yet (M4)
    x: str | None = None  # an x axis other than the records' dates (`entity.field`): M4


Letter = Annotated[str, Field(min_length=1, max_length=2)]


class HeatmapMark(Strict):
    """A letter on a day's square from a field of its records, e.g. setting Outdoor → O."""

    field: str  # `entity.field` of the metric's entity
    letters: dict[str, Letter] = Field(min_length=1)  # value → letter; other values: none


class HeatmapWidget(_Widget):
    """A calendar from the first record's month, at most the last `months` months: each day
    coloured by the worst of its records' status (`metric`), the days of another entity
    (`extra`, e.g. rest days) in lighter colours, and a letter per day (`mark`, `extra_mark`)."""

    widget: Literal["heatmap_calendar"]
    metric: str  # `entity.field`, a status
    extra: str | None = None  # `entity.field`, e.g. rest_day.status
    months: int = Field(12, ge=1)
    mark: HeatmapMark | None = None  # e.g. {field: session.setting, letters: {Outdoor: O}}
    extra_mark: Letter | None = None  # the letter of a day with only an extra record, e.g. R


class SideGroup(Strict):
    label: str  # e.g. Wellbeing
    fields: list[str] = Field(min_length=1)  # the entity's fields or derived values


class SideBySideWidget(_Widget):
    """The latest records side by side, newest first: `last` at first (a picker shows up to
    12), their fields in `groups`, and the latest record's `notes` below."""

    widget: Literal["side_by_side"]
    entity: str
    last: int = Field(4, ge=1, le=12)
    groups: list[SideGroup] = Field(min_length=1)
    notes: list[str] = []  # text fields
    labels: dict[str, str] = {}  # a row's label (default: the form's, or the derived name)


class FeedList(Strict):
    label: str  # e.g. Best 'what felt good'
    text: str  # a text field
    score: str | None = None  # its score: the highest first (none: the newest first)


class Attention(Strict):
    status: str  # a status field or derived value, e.g. reflect_status
    equals: str  # e.g. NEEDS ATTENTION
    fields: list[str] = Field(min_length=1)  # the texts shown for such a record


class TextFeedWidget(_Widget):
    """Texts of the last `window_days` days: per list the `top` ones by their score (then the
    newest), as the legacy "top 3 of the last 2 weeks"; and the records needing attention."""

    widget: Literal["text_feed"]
    entity: str
    lists: list[FeedList] = Field(min_length=1)
    window_days: int = Field(14, ge=0)
    top: int = Field(3, ge=1)
    attention: Attention | None = None


class TableWidget(_Widget):
    """An entity's records of the last `window_days` days (or the `last` ones), newest first,
    with the averages of some columns and the latest note."""

    widget: Literal["table"]
    entity: str
    columns: list[str] = Field(min_length=1)  # the entity's fields or derived values
    window_days: int | None = Field(None, ge=0)
    last: int | None = Field(None, ge=1)
    averages: list[str] = []  # columns averaged over the rows shown
    note: str | None = None  # a text field: its latest non-blank value up to the day
    labels: dict[str, str] = {}  # a column's label (default: the form's, or the derived name)


class MonthlyClass(Strict):
    label: str
    score: str  # `entity.field`


class MonthlyExtra(Strict):
    label: str
    count: str | None = None  # an entity: its records in the month
    mean: str | None = None  # `entity.field`: its average in the month

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.count is None) == (self.mean is None):
            raise ValueError("give either count (an entity) or mean (entity.field)")
        return self


class MonthlyWidget(_Widget):
    """Per calendar month (the last `months` at first, a picker shows more): the records of
    `count`, each class's average, `overall` (the average of the class averages), the `low`
    statuses, and `extra` counts or averages (the legacy Summary - Trends monthly table)."""

    widget: Literal["monthly"]
    count: str  # the entity counted ("Sessions logged"); a month without one shows no averages
    count_label: str = "Records"
    classes: list[MonthlyClass] = []
    overall: str | None = None  # the label of the average of the class averages
    low: str | None = None  # `entity.field`, a status: the LOW ones per month
    extra: list[MonthlyExtra] = []
    months: int = Field(6, ge=1)


class LaterWidget(BaseModel):
    """A widget of the planned library (03 §2.7) the app doesn't draw yet (M4/M5): its options
    are checked when it is."""

    model_config = ConfigDict(extra="allow", frozen=True)
    widget: Literal[
        "status_strip",
        "bars",
        "weekbars",
        "stacked",
        "box_by",
        "scatter",
        "radar",
        "delta_table",
        "ladder",
        "program_grid",
        "before_after",
    ]


Widget = Annotated[
    KpiWidget
    | StatusBoardWidget
    | LineWidget
    | HeatmapWidget
    | SideBySideWidget
    | TextFeedWidget
    | TableWidget
    | MonthlyWidget
    | LaterWidget,
    Field(discriminator="widget"),
]


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
    views: dict[Key, list[Widget]] | None = None  # D-083
    aggregates: Unchecked | None = None  # M5
    recommendation: Recommendation | None = None  # M3 (D-076)
