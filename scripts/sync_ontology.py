#!/usr/bin/env python3
"""
Extract ontology / synonym seeds from Mimir gold dimension tables via Databricks SQL.

Writes JSON files under src/nlsearch/vocabulary/data/ for use by synonyms.py.

Usage:
  python scripts/sync_ontology.py
  python scripts/sync_ontology.py --dry-run   # print SQL only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
_OUT = _ROOT / "src" / "nlsearch" / "vocabulary" / "data"

# Dimension tables: (ontology_name, SQL returning canonical + label + aliases columns)
_QUERIES: dict[str, str] = {
    "contract_stages": """
        SELECT cs.key AS canonical, cs.label AS label_en,
               collect_set(cst.label) AS labels_i18n
        FROM {catalog}.{schema}.contract_stages cs
        LEFT JOIN {catalog}.{schema}.contract_stage_translations cst
          ON cst.contract_stage_id = cs.id
        GROUP BY cs.key, cs.label
    """,
    "planning_stages": """
        SELECT ps.key AS canonical, ps.label AS label_en,
               collect_set(pst.label) AS labels_i18n
        FROM {catalog}.{schema}.planning_stages ps
        LEFT JOIN {catalog}.{schema}.planning_stage_translations pst
          ON pst.planning_stage_id = ps.id
        GROUP BY ps.key, ps.label
    """,
    "project_statuses": """
        SELECT pst.key AS canonical, pst.label AS label_en,
               collect_set(pstt.label) AS labels_i18n
        FROM {catalog}.{schema}.project_statuses pst
        LEFT JOIN {catalog}.{schema}.project_status_translations pstt
          ON pstt.project_status_id = pst.id
        GROUP BY pst.key, pst.label
    """,
    "contract_types": """
        SELECT contract_type AS canonical, description AS label_en
        FROM {catalog}.{schema}.contract_types
    """,
    "development_types": """
        SELECT development_type AS canonical, description AS label_en
        FROM {catalog}.{schema}.development_types
    """,
    "building_use_groups": """
        SELECT building_use_group AS canonical, building_use_group_name AS label_en
        FROM {catalog}.{schema}.building_use_groups
    """,
    "building_use_definitions": """
        SELECT building_use_code AS canonical, building_use_name AS label_en,
               building_use_group AS group_code, record_type
        FROM {catalog}.{schema}.building_use_definitions
        ORDER BY used_count DESC NULLS LAST
        LIMIT 500
    """,
    "role_definitions": """
        SELECT rd.project_role_code AS canonical, rd.label AS label_en,
               rd.role_group_code AS group_code,
               collect_set(rdt.label) AS labels_i18n
        FROM {catalog}.{schema}.role_definitions rd
        LEFT JOIN {catalog}.{schema}.role_definition_translations rdt
          ON rdt.project_role_code = rd.project_role_code
        GROUP BY rd.project_role_code, rd.label, rd.role_group_code
    """,
    "role_groups": """
        SELECT group_code AS canonical, label AS label_en
        FROM {catalog}.{schema}.role_groups
    """,
    "green_building_schemes": """
        SELECT scheme_code AS canonical, scheme_name AS label_en
        FROM {catalog}.{schema}.green_building_schemes
    """,
    "document_types": """
        SELECT document_type_code AS canonical, label AS label_en
        FROM {catalog}.{schema}.document_types
    """,
    "ownership_types": """
        SELECT ownership_type AS canonical, ownership_level AS label_en
        FROM {catalog}.{schema}.ownership_types
    """,
    # Facet samples from project hub (distinct values in use)
    "facet_contract_types": """
        SELECT DISTINCT contract_type AS canonical
        FROM {catalog}.{schema}.project_fields
        WHERE contract_type IS NOT NULL
    """,
    "facet_development_types": """
        SELECT DISTINCT development_type AS canonical
        FROM {catalog}.{schema}.project_fields
        WHERE development_type IS NOT NULL
    """,
    "facet_building_use_groups": """
        SELECT DISTINCT building_use_group AS canonical
        FROM {catalog}.{schema}.project_fields
        WHERE building_use_group IS NOT NULL
    """,
    "facet_places": """
        SELECT DISTINCT postal_town, admin_level_1, admin_level_2, country
        FROM {catalog}.{schema}.site_address
        WHERE country IS NOT NULL
        LIMIT 2000
    """,
    "facet_companies": """
        SELECT DISTINCT company_name AS canonical
        FROM {catalog}.{schema}.project_roles
        WHERE company_name IS NOT NULL
        ORDER BY canonical
        LIMIT 500
    """,
}


def _run_query(sql: str) -> list[dict]:
    from nlsearch.config import get_settings

    settings = get_settings()
    from databricks import sql as db_sql

    host = settings.databricks_host.removeprefix("https://").removeprefix("http://")
    with db_sql.connect(
        server_hostname=host,
        http_path=settings.databricks_http_path,
        access_token=settings.databricks_token,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=_OUT)
    args = parser.parse_args()

    from nlsearch.semantic.gold_layer import catalog_schema_from_metadata
    from nlsearch.semantic.schema_store import SchemaStore

    store = SchemaStore()
    catalog, schema = catalog_schema_from_metadata(store._tables)  # noqa: SLF001

    args.output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, int] = {}

    for name, template in _QUERIES.items():
        sql = template.format(catalog=catalog, schema=schema).strip()
        if args.dry_run:
            print(f"-- {name}\n{sql};\n")
            continue
        try:
            rows = _run_query(sql)
        except Exception as exc:
            print(f"WARN {name}: {exc}", file=sys.stderr)
            rows = []
        path = args.output / f"{name}.json"
        path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        manifest[name] = len(rows)
        print(f"Wrote {path} ({len(rows)} rows)")

    if not args.dry_run:
        (args.output / "_manifest.json").write_text(
            json.dumps({"catalog": catalog, "schema": schema, "counts": manifest}, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
