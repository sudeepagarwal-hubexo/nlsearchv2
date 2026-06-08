"""Unity Catalog schema sync from Databricks."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from nlsearch.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    tables_synced: int = 0
    tables: list[str] = field(default_factory=list)
    output_path: str = ""
    errors: list[str] = field(default_factory=list)


class UnityCatalogSync:
    """Pull table/column metadata from Databricks Unity Catalog into schema_metadata.json."""

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        return bool(
            self._settings.databricks_host
            and self._settings.databricks_token
            and self._settings.unity_catalog_name
            and self._settings.unity_schema_name
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.databricks_token}"}

    def _base_url(self) -> str:
        host = self._settings.databricks_host.removeprefix("https://").removeprefix("http://")
        return f"https://{host}"

    async def list_tables(self) -> list[str]:
        catalog = self._settings.unity_catalog_name
        schema = self._settings.unity_schema_name
        url = f"{self._base_url()}/api/2.1/unity-catalog/tables"
        params = {"catalog_name": catalog, "schema_name": schema}
        names: list[str] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            page_token: str | None = None
            while True:
                p = dict(params)
                if page_token:
                    p["page_token"] = page_token
                resp = await client.get(url, headers=self._headers(), params=p)
                resp.raise_for_status()
                data = resp.json()
                for t in data.get("tables", []):
                    names.append(t["name"])
                page_token = data.get("next_page_token")
                if not page_token:
                    break
        return names

    async def get_table_metadata(self, table_name: str) -> dict[str, Any]:
        catalog = self._settings.unity_catalog_name
        schema = self._settings.unity_schema_name
        full_name = f"{catalog}.{schema}.{table_name}"
        url = f"{self._base_url()}/api/2.1/unity-catalog/tables/{full_name}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            raw = resp.json()

        columns = []
        for col in raw.get("columns", []):
            columns.append(
                {
                    "name": col.get("name", ""),
                    "type": col.get("type_text") or col.get("type_name", "string"),
                    "description": (col.get("comment") or "")[:500],
                }
            )
        return {
            "table": table_name,
            "description": raw.get("comment") or f"{full_name} (Unity Catalog)",
            "catalog": catalog,
            "schema": schema,
            "full_name": full_name,
            "columns": columns,
        }

    async def sync_to_file(self, output_path: Path | None = None) -> SyncResult:
        result = SyncResult()
        if not self.configured:
            result.errors.append(
                "Databricks Unity Catalog not configured "
                "(NLSEARCH_DATABRICKS_HOST, TOKEN, UNITY_CATALOG_NAME, UNITY_SCHEMA_NAME)"
            )
            return result

        out = output_path or Path(__file__).parent / "data" / "schema_metadata.json"
        allow = self._settings.unity_table_allowlist
        allow_set = {t.strip() for t in allow.split(",") if t.strip()} if allow else None

        metadata: dict[str, Any] = {}
        try:
            table_names = await self.list_tables()
        except Exception as exc:
            logger.exception("Unity Catalog list_tables failed")
            result.errors.append(str(exc))
            return result

        for name in table_names:
            if allow_set and name not in allow_set:
                continue
            try:
                metadata[name] = await self.get_table_metadata(name)
                result.tables.append(name)
            except Exception as exc:
                result.errors.append(f"{name}: {exc}")

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
        result.tables_synced = len(result.tables)
        result.output_path = str(out)
        return result

    def sync_to_file_sync(self, output_path: Path | None = None) -> SyncResult:
        import asyncio

        return asyncio.run(self.sync_to_file(output_path))
