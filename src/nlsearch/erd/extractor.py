"""Extract schema graph from Unity Catalog, SQL warehouse, or local metadata JSON."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from nlsearch.config import get_settings
from nlsearch.erd.models import Column, ForeignKey, SchemaGraph, Table
from nlsearch.semantic.unity_catalog import UnityCatalogSync

logger = logging.getLogger(__name__)

# Columns ending with _id often reference <table>_id on entity `table` (singular/plural heuristics)
_ID_SUFFIX = re.compile(r"^(.+)_id$", re.I)


class ERDExtractor:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def catalog(self) -> str:
        return self._settings.unity_catalog_name

    @property
    def schema(self) -> str:
        return self._settings.unity_schema_name

    async def from_unity_catalog(
        self,
        *,
        table_allowlist: set[str] | None = None,
        infer_relationships: bool = True,
    ) -> SchemaGraph:
        sync = UnityCatalogSync()
        names = await sync.list_tables()
        if table_allowlist:
            names = [n for n in names if n in table_allowlist]

        graph = SchemaGraph(catalog=self.catalog, schema=self.schema)
        for name in names:
            meta = await sync.get_table_metadata(name)
            graph.tables[name] = _table_from_metadata(meta)

        if infer_relationships:
            graph.foreign_keys.extend(_infer_foreign_keys(graph))

        return graph

    def from_metadata_json(
        self,
        path: Path,
        *,
        infer_relationships: bool = True,
    ) -> SchemaGraph:
        raw = json.loads(path.read_text())
        graph = SchemaGraph(catalog=self.catalog, schema=self.schema)
        for key, meta in raw.items():
            graph.tables[key] = _table_from_metadata(meta)
        if infer_relationships:
            graph.foreign_keys.extend(_infer_foreign_keys(graph))
        return graph

    def enrich_foreign_keys_from_sql(self, graph: SchemaGraph) -> SchemaGraph:
        """Query system.information_schema via databricks-sql-connector."""
        fks = _fetch_fk_from_warehouse(self.catalog, self.schema)
        if fks:
            graph.foreign_keys = fks + [
                fk
                for fk in graph.foreign_keys
                if fk.source == "inferred"
                and not _fk_exists(fks, fk)
            ]
        return graph

    async def build(
        self,
        *,
        metadata_json: Path | None = None,
        use_sql_fk: bool = True,
        infer_relationships: bool = True,
        table_allowlist: set[str] | None = None,
    ) -> SchemaGraph:
        if metadata_json and metadata_json.exists():
            graph = self.from_metadata_json(metadata_json, infer_relationships=infer_relationships)
        else:
            graph = await self.from_unity_catalog(
                table_allowlist=table_allowlist,
                infer_relationships=infer_relationships,
            )

        if use_sql_fk:
            try:
                graph = self.enrich_foreign_keys_from_sql(graph)
            except Exception:
                logger.warning("SQL FK introspection failed; using inferred relationships only", exc_info=True)
        return graph


def _table_from_metadata(meta: dict[str, Any]) -> Table:
    cols: list[Column] = []
    pk_candidates = {c.get("name") for c in meta.get("columns", []) if c.get("name", "").endswith("_id")}
    for c in meta.get("columns", []):
        name = c.get("name", "")
        cols.append(
            Column(
                name=name,
                data_type=c.get("type", "string"),
                description=(c.get("description") or "")[:120],
                is_primary_key=name in pk_candidates and name == f"{meta.get('table', '')}_id",
            )
        )
    # Mark first *_id as PK if table_id pattern exists
    tname = meta.get("table", "")
    for col in cols:
        if col.name == f"{tname}_id" or col.name == "id":
            col.is_primary_key = True

    return Table(
        name=meta.get("table", ""),
        full_name=meta.get("full_name", meta.get("table", "")),
        description=(meta.get("description") or "")[:200],
        columns=cols,
    )


def _infer_foreign_keys(graph: SchemaGraph) -> list[ForeignKey]:
    table_set = set(graph.tables.keys())
    fks: list[ForeignKey] = []

    for tname, table in graph.tables.items():
        for col in table.columns:
            m = _ID_SUFFIX.match(col.name)
            if not m:
                continue
            stem = m.group(1).lower()
            if stem == tname.rstrip("s") or stem == tname:
                continue  # own PK

            targets = _resolve_target_tables(stem, table_set)
            for target in targets:
                pk_col = _guess_pk_column(graph.tables[target])
                if pk_col:
                    fks.append(
                        ForeignKey(
                            from_table=tname,
                            from_column=col.name,
                            to_table=target,
                            to_column=pk_col,
                            source="inferred",
                        )
                    )
                    break
    return _dedupe_fks(fks)


def _resolve_target_tables(stem: str, table_set: set[str]) -> list[str]:
    candidates = [
        stem,
        f"{stem}s",
        f"{stem}es",
        stem.replace("_", ""),
    ]
    found: list[str] = []
    for c in candidates:
        if c in table_set:
            found.append(c)
    # partial match (e.g. project -> projects)
    if not found:
        for t in table_set:
            if stem in t or t.startswith(stem):
                found.append(t)
    return found[:1]


def _guess_pk_column(table: Table) -> str | None:
    for col in table.columns:
        if col.is_primary_key:
            return col.name
    for col in table.columns:
        if col.name == "id" or col.name.endswith("_id"):
            return col.name
    return table.columns[0].name if table.columns else None


def _dedupe_fks(fks: list[ForeignKey]) -> list[ForeignKey]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[ForeignKey] = []
    for fk in fks:
        key = (fk.from_table, fk.from_column, fk.to_table, fk.to_column)
        if key not in seen:
            seen.add(key)
            out.append(fk)
    return out


def _fk_exists(existing: list[ForeignKey], fk: ForeignKey) -> bool:
    return any(
        e.from_table == fk.from_table
        and e.from_column == fk.from_column
        and e.to_table == fk.to_table
        for e in existing
    )


def _fetch_fk_from_warehouse(catalog: str, schema: str) -> list[ForeignKey]:
    settings = get_settings()
    if not (
        settings.databricks_host
        and settings.databricks_http_path
        and settings.databricks_token
    ):
        return []

    try:
        from databricks import sql as db_sql
    except ImportError as exc:
        raise RuntimeError("databricks-sql-connector required") from exc

    query = f"""
    SELECT
      rc.constraint_name,
      fk.table_name AS fk_table,
      fk.column_name AS fk_column,
      pk.table_name AS pk_table,
      pk.column_name AS pk_column
    FROM {catalog}.information_schema.referential_constraints AS rc
    JOIN {catalog}.information_schema.key_column_usage AS fk
      ON rc.constraint_catalog = fk.constraint_catalog
      AND rc.constraint_schema = fk.constraint_schema
      AND rc.constraint_name = fk.constraint_name
    JOIN {catalog}.information_schema.key_column_usage AS pk
      ON rc.unique_constraint_catalog = pk.constraint_catalog
      AND rc.unique_constraint_schema = pk.constraint_schema
      AND rc.unique_constraint_name = pk.constraint_name
    WHERE fk.table_schema = '{schema}'
      AND pk.table_schema = '{schema}'
    """

    host = settings.databricks_host.removeprefix("https://").removeprefix("http://")
    fks: list[ForeignKey] = []
    with db_sql.connect(
        server_hostname=host,
        http_path=settings.databricks_http_path,
        access_token=settings.databricks_token,
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [d[0] for d in cursor.description] if cursor.description else []

    for row in rows:
        data = dict(zip(columns, row)) if columns else {}
        if not data:
            continue
        fks.append(
            ForeignKey(
                from_table=str(data.get("fk_table", "")),
                from_column=str(data.get("fk_column", "")),
                to_table=str(data.get("pk_table", "")),
                to_column=str(data.get("pk_column", "")),
                constraint_name=str(data.get("constraint_name", "")),
                source="catalog",
            )
        )
    return _dedupe_fks(fks)
