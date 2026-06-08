"""Schema metadata store with RAG-style table retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Mimir gold layer — entity → tables (from schema_metadata.json)
_ENTITY_TABLES: dict[str, list[str]] = {
    "project": [
        "project_fields",
        "site_address",
        "project_metadata",
        "contract_stages",
        "planning_stages",
        "project_statuses",
        "project_building_uses",
        "project_dimensions",
        "development_types",
        "contract_types",
    ],
    "company": ["project_roles", "role_definitions", "role_groups"],
    "person": ["project_role_contacts", "project_roles"],
    "workplace": ["project_roles"],
    "stat": ["project_fields", "site_address"],
    "cross": [
        "project_fields",
        "project_roles",
        "project_role_contacts",
        "site_address",
        "role_definitions",
    ],
    "semantic": ["project_green_building", "green_building_schemes", "project_materials", "material_definitions"],
    "temporal": ["project_fields", "project_metadata"],
    "keyword": ["project_fields", "project_documents", "project_metadata"],
}


class SchemaStore:
    def __init__(self, metadata_path: Path | None = None) -> None:
        self._metadata_path = metadata_path or Path(__file__).parent / "data" / "schema_metadata.json"
        self._tables: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        if self._metadata_path.exists():
            self._tables = json.loads(self._metadata_path.read_text())

    def replace_tables(self, tables: dict[str, dict[str, Any]]) -> None:
        self._tables = tables
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self._metadata_path.write_text(json.dumps(tables, indent=2, ensure_ascii=False))

    async def sync_from_unity_catalog(self) -> dict[str, Any]:
        from nlsearch.semantic.unity_catalog import UnityCatalogSync

        sync = UnityCatalogSync()
        result = await sync.sync_to_file(self._metadata_path)
        if result.tables_synced:
            self.reload()
        return {
            "tables_synced": result.tables_synced,
            "tables": result.tables,
            "output_path": result.output_path,
            "errors": result.errors,
        }

    def all_tables(self) -> list[str]:
        return list(self._tables.keys())

    def get_table(self, name: str) -> dict[str, Any] | None:
        return self._tables.get(name)

    def retrieve_for_query(self, query: str, entities: list[str]) -> list[dict[str, Any]]:
        """Return only relevant schema chunks (not entire catalog)."""
        low = query.lower()
        selected: set[str] = set()
        for ent in entities:
            for t in _ENTITY_TABLES.get(ent.lower(), []):
                if t in self._tables:
                    selected.add(t)

        if any(w in low for w in ("tender", "stage", "construction", "planning", "upphandling")):
            selected.update(["project_fields", "contract_stages", "planning_stages", "project_statuses"])
        if any(w in low for w in ("architect", "contractor", "client", "company", "skanska", "ncc")):
            selected.update(["project_roles", "role_definitions"])
        if any(w in low for w in ("manager", "person", "pm", "purchasing", "contact")):
            selected.update(["project_role_contacts", "project_roles"])
        if any(w in low for w in ("near", "km", "heatmap", "polygon", "patch", "göteborg", "stockholm")):
            selected.update(["project_fields", "site_address"])
        if any(w in low for w in ("hospital", "school", "residential", "office", "building")):
            selected.update(["project_fields", "project_building_uses", "building_use_definitions"])
        if any(w in low for w in ("sustainable", "breeam", "green", "low-carbon", "timber")):
            selected.update(["project_green_building", "green_building_schemes"])
        if any(w in low for w in ("material", "recladding", "facade")):
            selected.update(["project_materials", "material_definitions"])
        if any(w in low for w in ("planning ref", "document", "reference")):
            selected.update(["project_fields", "project_documents", "project_metadata"])
        if any(w in low for w in ("design", "build", "procurement", "contract type")):
            selected.update(["project_fields", "contract_types"])

        if not selected:
            selected = {"project_fields", "site_address", "project_roles"}

        return [self._tables[t] for t in selected if t in self._tables]

    def format_for_prompt(self, tables: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for t in tables:
            cols = ", ".join(c["name"] for c in t.get("columns", []))
            desc = (t.get("description") or "")[:300].replace("\n", " ")
            lines.append(f"Table: {t.get('full_name', t['table'])}\n{desc}\nColumns: {cols}")
        return "\n\n".join(lines)
