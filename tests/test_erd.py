"""ERD builder tests (offline JSON)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nlsearch.erd.extractor import ERDExtractor
from nlsearch.erd.renderer import render_dot, render_mermaid

METADATA = Path(__file__).parents[1] / "src" / "nlsearch" / "semantic" / "data" / "schema_metadata.json"


@pytest.mark.skipif(not METADATA.exists(), reason="schema_metadata.json not present")
def test_erd_from_metadata_json() -> None:
    extractor = ERDExtractor()
    graph = extractor.from_metadata_json(METADATA, infer_relationships=True)
    assert len(graph.tables) > 0
    mmd = render_mermaid(graph, max_columns=5)
    assert "erDiagram" in mmd
    dot = render_dot(graph, max_columns=5)
    assert "digraph ERD" in dot


def test_erd_renderer_minimal() -> None:
    from nlsearch.erd.models import Column, ForeignKey, SchemaGraph, Table

    graph = SchemaGraph(catalog="c", schema="s")
    graph.tables["projects"] = Table(
        name="projects",
        full_name="c.s.projects",
        columns=[Column("project_id", "string", is_primary_key=True)],
    )
    graph.tables["companies"] = Table(
        name="companies",
        full_name="c.s.companies",
        columns=[Column("company_id", "string", is_primary_key=True)],
    )
    graph.foreign_keys.append(
        ForeignKey("project_companies", "project_id", "projects", "project_id")
    )
    mmd = render_mermaid(graph)
    assert "projects" in mmd
    assert "companies" in mmd
