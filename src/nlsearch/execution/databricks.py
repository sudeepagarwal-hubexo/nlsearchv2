"""Databricks SQL Warehouse execution adapter."""

from __future__ import annotations

from typing import Any

from nlsearch.config import ensure_databricks_credentials, get_settings
from databricks import sql as db_sql


class DatabricksExecutor:
    """Execute validated SQL against Databricks SQL Warehouse."""

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        return bool(
            self._settings.databricks_host
            and self._settings.databricks_http_path
            and self._settings.databricks_token
        )


    async def execute(self, sql: str, limit: int = 1000) -> dict[str, Any]:
        return await self.execute_databricks_sql_connector(sql, limit)

    async def execute_databricks_sql_connector(self, sql: str, limit: int = 1000) -> dict[str, Any]:
        self._settings = ensure_databricks_credentials(self._settings)
        if not self.configured:
            return {
                "rows": [],
                "row_count": 0,
                "mock": True,
                "message": (
                    "Databricks SQL not configured — set NLSEARCH_DATABRICKS_TOKEN "
                    "and NLSEARCH_DATABRICKS_HTTP_PATH, or use Databricks CLI auth"
                ),
            }

        host = self._settings.databricks_host.replace("https://", "").replace("http://", "")
        conn = db_sql.connect(
            server_hostname=host,
            http_path=self._settings.databricks_http_path,
            access_token=self._settings.databricks_token,
        )
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            raw = cursor.fetchmany(limit)
            columns = [d[0] for d in (cursor.description or [])]
            if columns:
                rows = [dict(zip(columns, row)) for row in raw]
            else:
                rows = [{"row": row} for row in raw]
            return {"rows": rows, "row_count": len(rows), "mock": False}
        finally:
            cursor.close()
            conn.close()


    async def execute_http_api(self, sql: str, limit: int = 1000) -> dict[str, Any]:
        print(f"Databricks configured: {self.configured}")
        print(f"Databricks host: {self._settings.databricks_host}")
        print(f"Databricks http path: {self._settings.databricks_http_path}")
        print(f"Databricks token: {self._settings.databricks_token}")
        print(f"Databricks sql: {sql}")
        print(f"Databricks limit: {limit}")
        
        if not self.configured:
            return {
                "rows": [],
                "row_count": 0,
                "mock": True,
                "message": "Databricks not configured — returning empty mock result",
            }

        # Production: use databricks-sql-connector or REST API
        import httpx

        url = f"https://{self._settings.databricks_host}/api/2.0/sql/statements"
        headers = {"Authorization": f"Bearer {self._settings.databricks_token}"}
        payload = {
            "warehouse_id": self._settings.databricks_http_path,
            "statement": sql,
            "row_limit": limit,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return {"rows": data.get("result", {}).get("data_array", []), "row_count": 0, "mock": False}
