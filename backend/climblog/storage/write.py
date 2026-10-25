# SPDX-License-Identifier: GPL-3.0-or-later
"""Write records through a `Repository`: add, update, soft delete (04-storage.md §1, D-049).

A record is found by its natural key in the loaded data (`load.py`) and written as row edits,
one per tab it has a row in, applied in one save. Values are checked as if read back from the
sheet (`parse_cell`), so a write never creates a data issue. Every row written gets
`updated_at`; a soft delete fills `deleted` on the record's rows and on its children's.
"""

import datetime as dt
from collections.abc import Callable, Mapping

from climblog.expr import Value
from climblog.modules.schema import NEXT, BaseField, Entity, Module
from climblog.storage.base import Append, Edit, Repository, StorageError, Update
from climblog.storage.cells import CellError, RawCell, parse_cell
from climblog.storage.load import DELETED, Key, ModuleData, describe_key, load_data

UPDATED_AT = "updated_at"


class WriteError(StorageError):
    """A write that doesn't fit the module or the data (unknown field, existing key, …)."""


class RecordNotFound(WriteError):
    """No record with that key."""


class RecordWriter:
    """Writes one module's records; reads the current data from the same repository."""

    def __init__(
        self,
        module: Module,
        repo: Repository,
        *,
        clock: Callable[[], dt.datetime] = dt.datetime.now,
    ) -> None:
        self.module = module
        self.repo = repo
        self.clock = clock

    def add(self, entity: str, values: Mapping[str, Value]) -> None:
        """A new record. Its key (with defaults) must be complete and not taken; a child needs
        its parent. A section tab of a split entity gets a row only when it has a value."""
        ent = self._entity(entity)
        record = self._check(ent, values)
        key = self._complete_key(ent, record)
        record.update(zip(_key(ent), key, strict=True))
        self._check_free(ent, key)
        data = load_data(self.module, self.repo)
        self._check_parent(ent, record, data)

        now = self._now()
        edits: list[Edit] = []
        for tab, fields in ent.tab_fields().items():
            cells = {f: _cell(record[f]) for f in fields if f in record}
            has_data = any(record.get(f) is not None for f in fields if f not in _key(ent))
            if tab == ent.main_tab or has_data:
                edits.append(Append(tab, self._stamped(tab, cells, now)))
        self.repo.apply(edits)

    def update(self, entity: str, key: Mapping[str, Value], values: Mapping[str, Value]) -> None:
        """New values for some fields of a record. A tab it has no row in yet gets one; a row
        changed in the sheet since it was read is a conflict. Key fields can't change."""
        ent = self._entity(entity)
        changes = self._check(ent, values)
        data = load_data(self.module, self.repo)
        record, places = self._find(entity, key, data)
        for part in _key(ent):
            if part in changes and changes[part] != record.get(part):
                raise WriteError(f"{part} can't be changed: delete the record and add it again")
        self._check_parent(ent, record | changes, data)

        now = self._now()
        edits: list[Edit] = []
        for tab, fields in ent.tab_fields().items():
            cells = {f: _cell(changes[f]) for f in fields if f in changes and f not in _key(ent)}
            if not cells:
                continue
            if tab in places:
                expected = self._row(tab, places[tab])
                edits.append(Update(tab, places[tab], self._stamped(tab, cells, now), expected))
            else:
                keys = {part: _cell(record[part]) for part in _key(ent)}
                edits.append(Append(tab, self._stamped(tab, keys | cells, now)))
        if edits:
            self.repo.apply(edits)

    def delete(self, entity: str, key: Mapping[str, Value]) -> None:
        """Soft delete: `deleted` filled on every row of the record and of its children."""
        data = load_data(self.module, self.repo)
        record, places = self._find(entity, key, data)
        rows = list(places.items()) + self._children_rows(entity, record, data)
        now = self._now()
        edits: list[Edit] = [
            Update(tab, number, self._stamped(tab, {DELETED: now}, now), self._row(tab, number))
            for tab, number in rows
        ]
        self.repo.apply(edits)

    # ---- Records ----

    def _entity(self, name: str) -> Entity:
        if name not in self.module.entities:
            raise WriteError(f"no entity '{name}' in module {self.module.module}")
        entity = self.module.entities[name]
        if not entity.key:
            raise WriteError(f"{entity.label} has generated ids: writing it comes later (M5)")
        return entity

    def _check(self, entity: Entity, values: Mapping[str, Value]) -> dict[str, Value]:
        """The values as the sheet would read them back; an unknown field or bad value fails."""
        unknown = [name for name in values if name not in entity.fields]
        if unknown:
            raise WriteError(f"{entity.label} has no field {', '.join(unknown)}")
        checked = {}
        for name, value in values.items():
            try:
                checked[name] = parse_cell(self.module, _field(entity, name), _cell(value))
            except CellError as error:
                raise WriteError(f"{name}: {error.message}") from None
        return checked

    def _complete_key(self, entity: Entity, values: Mapping[str, Value]) -> Key:
        """The key from the values, a blank part taking its default; still blank fails."""
        key = tuple(self._or_default(entity, part, values.get(part)) for part in _key(entity))
        if None in key:
            blank = _key(entity)[key.index(None)]
            raise WriteError(f"no {blank}: a {entity.label.lower()} needs one")
        return key

    def _or_default(self, entity: Entity, name: str, value: Value) -> Value:
        """The value, or the field's default when blank (as on read, D-048). A `next` number
        is not filled in yet: it stays blank (D-050)."""
        field = _field(entity, name)
        if value is None and field.default not in (None, NEXT):
            return parse_cell(self.module, field, field.default)  # checked at load
        return value

    def _find(
        self, name: str, key: Mapping[str, Value], data: ModuleData
    ) -> tuple[dict[str, Value], dict[str, int]]:
        """The record with that key (defaults fill missing parts) and its rows."""
        entity = self._entity(name)
        parts = _key(entity)
        given = self._check(entity, key)
        unknown = [part for part in given if part not in parts]
        if unknown:
            raise WriteError(f"{', '.join(unknown)} is not part of the {entity.label.lower()} key")
        wanted = self._complete_key(entity, given)
        records = data.entities[name]
        for record, places in zip(records.records, records.places, strict=True):
            if tuple(record.get(part) for part in parts) == wanted:
                return record, places
        raise RecordNotFound(f"no {entity.label.lower()} for {describe_key(parts, wanted)}")

    def _check_free(self, entity: Entity, key: Key) -> None:
        """No row of the entity's tabs has the key yet: also an orphan section row, which the
        loaded data leaves out but a new record would hide."""
        parts = _key(entity)
        for tab in entity.tab_fields():
            for row in self.repo.read_table(tab).rows:
                if row.cells.get(DELETED) not in (None, ""):
                    continue
                try:
                    found = tuple(
                        self._or_default(
                            entity, p, parse_cell(self.module, _field(entity, p), row.cells.get(p))
                        )
                        for p in parts
                    )
                except CellError:
                    continue  # a bad key cell: already a data issue, it can't match
                if found == key:
                    raise WriteError(
                        f"{tab} already has a row for {describe_key(parts, key)} (row {row.number})"
                    )

    def _check_parent(self, entity: Entity, record: Mapping[str, Value], data: ModuleData) -> None:
        link = entity.parent
        if link is None:
            return
        want = tuple(record.get(part) for part in link.key)
        for parent in data.entities[link.entity].records:
            same_key = tuple(parent.get(part) for part in link.key) == want
            if same_key and all(parent.get(f) == v for f, v in link.fixed.items()):
                return
        tab = self.module.entities[link.entity].main_tab
        raise WriteError(f"no {tab} row for {describe_key(link.key, want)}")

    def _children_rows(
        self, name: str, record: Mapping[str, Value], data: ModuleData
    ) -> list[tuple[str, int]]:
        """The rows of the record's children, in every child entity (one level, D-042)."""
        rows: list[tuple[str, int]] = []
        for child_name, child in self.module.entities.items():
            link = child.parent
            if link is None or link.entity != name:
                continue
            if not all(record.get(f) == v for f, v in link.fixed.items()):
                continue
            want = tuple(record.get(part) for part in link.key)
            children = data.entities[child_name]
            for values, places in zip(children.records, children.places, strict=True):
                if tuple(values.get(part) for part in link.key) == want:
                    rows += places.items()
        return rows

    # ---- Rows ----

    def _row(self, tab: str, number: int) -> Mapping[str, RawCell]:
        """The row's cells as read, for the conflict check (its number came from this read)."""
        return next(row.cells for row in self.repo.read_table(tab).rows if row.number == number)

    def _stamped(
        self, tab: str, cells: Mapping[str, RawCell], now: dt.datetime
    ) -> dict[str, RawCell]:
        """The cells, with `updated_at` when the tab has that column (hand-optional, 04 §1)."""
        if UPDATED_AT in self.repo.read_table(tab).columns:
            return {**cells, UPDATED_AT: now}
        return dict(cells)

    def _now(self) -> dt.datetime:
        return self.clock().replace(microsecond=0)


def _key(entity: Entity) -> list[str]:
    return entity.key or []


def _field(entity: Entity, name: str) -> BaseField:
    field = entity.fields[name]
    assert isinstance(field, BaseField)  # templates are expanded at load
    return field


def _cell(value: Value) -> RawCell:
    """A value as written to the sheet: Yes/No for booleans, everything else as it is."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value
