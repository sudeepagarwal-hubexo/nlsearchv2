"""Render SchemaGraph to Mermaid ER diagram and Graphviz DOT."""

from __future__ import annotations

import re

from nlsearch.erd.models import SchemaGraph, Table

_MERMAID_SAFE = re.compile(r"[^a-zA-Z0-9_]")


def _mermaid_id(name: str) -> str:
    return _MERMAID_SAFE.sub("_", name)


def _mermaid_type(sql_type: str) -> str:
    t = (sql_type or "string").lower().split("(")[0].strip()
    mapping = {
        "string": "string",
        "varchar": "string",
        "bigint": "int",
        "int": "int",
        "integer": "int",
        "double": "float",
        "float": "float",
        "boolean": "boolean",
        "bool": "boolean",
        "date": "date",
        "timestamp": "datetime",
        "decimal": "float",
    }
    return mapping.get(t, "string")


def render_mermaid(
    graph: SchemaGraph,
    *,
    max_columns: int = 12,
    include_descriptions: bool = False,
) -> str:
    """Mermaid erDiagram (GitHub / VS Code / mermaid.live)."""
    lines = ["erDiagram"]
    table_names = graph.table_names()

    for fk in graph.foreign_keys:
        if fk.from_table not in graph.tables or fk.to_table not in graph.tables:
            continue
        left = _mermaid_id(fk.to_table)
        right = _mermaid_id(fk.from_table)
        label = fk.from_column.replace("_", " ")
        lines.append(f'    {left} ||--o{{ {right} : "{label}"')

    for name in table_names:
        table = graph.tables[name]
        entity = _mermaid_id(name)
        lines.append(f"    {entity} {{")
        shown = table.columns[:max_columns]
        for col in shown:
            pk = " PK" if col.is_primary_key else ""
            fk_mark = ""
            if any(f.from_table == name and f.from_column == col.name for f in graph.foreign_keys):
                fk_mark = " FK"
            dtype = _mermaid_type(col.data_type)
            lines.append(f"        {dtype} {col.name}{pk}{fk_mark}")
        if len(table.columns) > max_columns:
            lines.append(f"        string _more_{len(table.columns) - max_columns}_columns")
        lines.append("    }")

    if include_descriptions:
        lines.append("")
        lines.append("%% Table descriptions")
        for name in table_names:
            desc = graph.tables[name].description.replace("\n", " ")
            if desc:
                lines.append(f"%% {_mermaid_id(name)}: {desc[:120]}")

    lines.append("")
    lines.append(f"%% catalog={graph.catalog} schema={graph.schema} tables={len(table_names)}")
    return "\n".join(lines) + "\n"


def render_dot(
    graph: SchemaGraph,
    *,
    max_columns: int = 10,
) -> str:
    """Graphviz DOT for dot -Tpng / svg."""
    lines = [
        "digraph ERD {",
        '  rankdir=LR;',
        '  node [shape=plaintext, fontname="Helvetica"];',
        '  edge [fontname="Helvetica", fontsize=10];',
        "",
    ]

    for name in graph.table_names():
        table = graph.tables[name]
        label = _html_table_label(table, max_columns=max_columns)
        lines.append(f'  "{name}" [label=<{label}>];')

    lines.append("")
    for fk in graph.foreign_keys:
        if fk.from_table in graph.tables and fk.to_table in graph.tables:
            lines.append(
                f'  "{fk.from_table}" -> "{fk.to_table}" '
                f'[label="{fk.from_column}"];'
            )

    lines.append("}")
    return "\n".join(lines) + "\n"


def _html_table_label(table: Table, *, max_columns: int) -> str:
    rows = [
        f'<tr><td colspan="2" bgcolor="#lightblue"><b>{table.name}</b></td></tr>',
        '<tr><td><b>Column</b></td><td><b>Type</b></td></tr>',
    ]
    for col in table.columns[:max_columns]:
        flags = []
        if col.is_primary_key:
            flags.append("PK")
        suffix = f" ({','.join(flags)})" if flags else ""
        rows.append(f"<tr><td>{col.name}{suffix}</td><td>{col.data_type}</td></tr>")
    if len(table.columns) > max_columns:
        rows.append(f"<tr><td colspan=\"2\">… +{len(table.columns) - max_columns} more</td></tr>")
    return f"<table border=\"0\" cellborder=\"1\" cellspacing=\"0\">{''.join(rows)}</table>"
