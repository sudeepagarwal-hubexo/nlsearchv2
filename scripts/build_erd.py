#!/usr/bin/env python3
"""
Build an ERD from a Databricks connection (Unity Catalog + optional SQL FK introspection).

Outputs Mermaid (.mmd) and/or Graphviz DOT (.dot). Preview Mermaid at https://mermaid.live

Examples:
  # Live Unity Catalog (uses NLSEARCH_* from .env)
  python scripts/build_erd.py --output docs/erd

  # From synced schema_metadata.json (offline)
  python scripts/build_erd.py --from-json src/nlsearch/semantic/data/schema_metadata.json -o docs/erd

  # Subset of tables
  python scripts/build_erd.py --tables projects,companies,people -o docs/erd

  # Render PNG/SVG (requires graphviz installed)
  dot -Tsvg docs/erd/schema.dot -o docs/erd/schema.svg
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Allow running without install: repo root on path
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from nlsearch.erd.extractor import ERDExtractor
from nlsearch.erd.renderer import render_dot, render_mermaid
from nlsearch.semantic.unity_catalog import UnityCatalogSync

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("build_erd")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build ERD from Databricks schema")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("docs/erd"),
        help="Output directory (default: docs/erd)",
    )
    p.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="Use existing schema_metadata.json instead of live Unity Catalog API",
    )
    p.add_argument(
        "--sync-first",
        action="store_true",
        help="Refresh schema_metadata.json from Unity Catalog before building ERD",
    )
    p.add_argument(
        "--tables",
        type=str,
        default="",
        help="Comma-separated table allowlist (default: all in schema / json)",
    )
    p.add_argument(
        "--no-sql-fk",
        action="store_true",
        help="Skip information_schema FK query via SQL warehouse",
    )
    p.add_argument(
        "--no-infer",
        action="store_true",
        help="Do not infer relationships from *_id column naming",
    )
    p.add_argument(
        "--max-columns",
        type=int,
        default=12,
        help="Max columns per entity in diagram (default: 12)",
    )
    p.add_argument(
        "--formats",
        type=str,
        default="mermaid,dot",
        help="Comma-separated: mermaid, dot (default: both)",
    )
    return p.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    metadata_path = args.from_json or (
        _ROOT / "src" / "nlsearch" / "semantic" / "data" / "schema_metadata.json"
    )

    if args.sync_first:
        logger.info("Syncing Unity Catalog -> %s", metadata_path)
        sync = UnityCatalogSync()
        result = await sync.sync_to_file(metadata_path)
        if result.errors:
            for err in result.errors:
                logger.error("%s", err)
        logger.info("Synced %d tables", result.tables_synced)
        if result.tables_synced == 0 and not metadata_path.exists():
            return 1

    allow: set[str] | None = None
    if args.tables.strip():
        allow = {t.strip() for t in args.tables.split(",") if t.strip()}

    extractor = ERDExtractor()
    use_json = args.from_json or (metadata_path.exists() and not args.sync_first)

    if use_json and metadata_path.exists():
        logger.info("Loading schema from %s", metadata_path)
        graph = extractor.from_metadata_json(
            metadata_path,
            infer_relationships=not args.no_infer,
        )
        if allow:
            graph.tables = {k: v for k, v in graph.tables.items() if k in allow}
    else:
        logger.info("Fetching schema from Unity Catalog (%s.%s)", extractor.catalog, extractor.schema)
        graph = await extractor.from_unity_catalog(
            table_allowlist=allow,
            infer_relationships=not args.no_infer,
        )

    if not args.no_sql_fk:
        logger.info("Enriching foreign keys from SQL warehouse (information_schema)")
        graph = extractor.enrich_foreign_keys_from_sql(graph)

    args.output.mkdir(parents=True, exist_ok=True)
    formats = {f.strip().lower() for f in args.formats.split(",")}

    summary = {
        "catalog": graph.catalog,
        "schema": graph.schema,
        "tables": len(graph.tables),
        "relationships": len(graph.foreign_keys),
    }
    logger.info(
        "Graph: %d tables, %d relationships",
        summary["tables"],
        summary["relationships"],
    )

    if "mermaid" in formats:
        mmd_path = args.output / "schema.mmd"
        mmd_path.write_text(
            render_mermaid(graph, max_columns=args.max_columns),
            encoding="utf-8",
        )
        logger.info("Wrote %s", mmd_path)

    if "dot" in formats:
        dot_path = args.output / "schema.dot"
        dot_path.write_text(render_dot(graph, max_columns=args.max_columns), encoding="utf-8")
        logger.info("Wrote %s", dot_path)

    readme = args.output / "README.md"
    readme.write_text(
        _readme_content(summary, formats),
        encoding="utf-8",
    )
    logger.info("Wrote %s", readme)
    return 0


def _readme_content(summary: dict, formats: set[str]) -> str:
    lines = [
        "# Schema ERD",
        "",
        f"- **Catalog:** `{summary['catalog']}`",
        f"- **Schema:** `{summary['schema']}`",
        f"- **Tables:** {summary['tables']}",
        f"- **Relationships:** {summary['relationships']}",
        "",
        "## View the diagram",
        "",
    ]
    if "mermaid" in formats:
        lines.extend(
            [
                "1. Open [schema.mmd](./schema.mmd) in VS Code (Mermaid preview) or paste into https://mermaid.live",
                "",
            ]
        )
    if "dot" in formats:
        lines.extend(
            [
                "2. Render Graphviz:",
                "   ```bash",
                "   dot -Tsvg schema.dot -o schema.svg",
                "   dot -Tpng schema.dot -o schema.png",
                "   ```",
                "",
            ]
        )
    lines.extend(
        [
            "## Regenerate",
            "",
            "```bash",
            "cd /path/to/nlsearchv2",
            "python scripts/build_erd.py --sync-first -o docs/erd",
            "# or offline from synced metadata:",
            "python scripts/build_erd.py --from-json src/nlsearch/semantic/data/schema_metadata.json -o docs/erd",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
