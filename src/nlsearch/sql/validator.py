"""SQL validation: syntax, schema, business rules, security, cost."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nlsearch.semantic.schema_store import SchemaStore


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SQLValidator:
    FORBIDDEN = re.compile(
        r"\b(DROP|DELETE|INSERT|UPDATE|TRUNCATE|ALTER|GRANT|REVOKE|EXEC|EXECUTE)\b",
        re.I,
    )

    def __init__(self, schema: SchemaStore | None = None) -> None:
        self._schema = schema or SchemaStore()
        self._columns_by_table: dict[str, set[str]] = {}
        for name, meta in self._schema._tables.items():  # noqa: SLF001
            self._columns_by_table[name] = {c["name"] for c in meta.get("columns", [])}

    def validate(self, sql: str, tenant_id: str | None = None) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        if self.FORBIDDEN.search(sql):
            errors.append("Only SELECT statements are permitted")

        if not re.match(r"^\s*SELECT\b", sql, re.I):
            errors.append("SQL must start with SELECT")

        # Table existence (support catalog.schema.table and aliases)
        for table in re.findall(r"\bFROM\s+([\w.]+)\s+(\w+)?", sql, re.I):
            raw = table[0] if isinstance(table, tuple) else table
            name = raw.split(".")[-1]
            if name not in self._schema.all_tables():
                errors.append(f"Unknown table: {name}")
        if "project_fields" not in sql and "project_roles" not in sql:
            warnings.append("SQL does not reference gold hub tables (project_fields / project_roles)")

        # Full table scan heuristic
        if re.search(r"WHERE\s+1\s*=\s*1\s*$", sql, re.I | re.M):
            warnings.append("Query may perform full table scan — consider adding filters")

        # Tenant RLS placeholder
        if tenant_id and "tenant_id" not in sql.lower():
            warnings.append("tenant_id filter not present — RLS should be applied at warehouse layer")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
