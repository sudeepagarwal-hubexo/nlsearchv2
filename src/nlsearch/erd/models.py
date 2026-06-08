"""ERD graph models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Column:
    name: str
    data_type: str
    description: str = ""
    is_primary_key: bool = False


@dataclass
class ForeignKey:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    constraint_name: str = ""
    source: str = "catalog"  # catalog | inferred


@dataclass
class Table:
    name: str
    full_name: str
    description: str = ""
    columns: list[Column] = field(default_factory=list)


@dataclass
class SchemaGraph:
    catalog: str
    schema: str
    tables: dict[str, Table] = field(default_factory=dict)
    foreign_keys: list[ForeignKey] = field(default_factory=list)

    def table_names(self) -> list[str]:
        return sorted(self.tables.keys())
