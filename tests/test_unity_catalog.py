"""Unity Catalog schema sync (HTTP mocked)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nlsearch.config import Settings
from nlsearch.semantic.schema_store import SchemaStore
from nlsearch.semantic.unity_catalog import UnityCatalogSync


@pytest.mark.asyncio
async def test_unity_catalog_sync_writes_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "schema_metadata.json"

    def fake_settings() -> Settings:
        return Settings(
            databricks_host="dbc-example.cloud.databricks.com",
            databricks_token="token",
            unity_catalog_name="gold",
            unity_schema_name="hubexo",
        )

    monkeypatch.setattr("nlsearch.semantic.unity_catalog.get_settings", fake_settings)

    list_resp = {"tables": [{"name": "projects"}, {"name": "companies"}]}
    table_resp = {
        "comment": "Projects table",
        "columns": [
            {"name": "project_id", "type_text": "string", "comment": "PK"},
            {"name": "value", "type_text": "bigint", "comment": "GDV SEK"},
        ],
    }

    sync = UnityCatalogSync()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            _resp(200, list_resp),
            _resp(200, table_resp),
            _resp(200, {**table_resp, "comment": "Companies"}),
        ]
        result = await sync.sync_to_file(out)

    assert result.tables_synced == 2
    assert out.exists()
    data = json.loads(out.read_text())
    assert "projects" in data
    assert data["projects"]["columns"][0]["name"] == "project_id"


@pytest.mark.asyncio
async def test_schema_store_reload_after_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SchemaStore(metadata_path=tmp_path / "schema_metadata.json")
    assert store.all_tables() == []

    store.replace_tables(
        {
            "projects": {
                "table": "projects",
                "description": "test",
                "columns": [{"name": "id", "type": "string", "description": ""}],
            }
        }
    )
    store.reload()
    assert "projects" in store.all_tables()


def _resp(status: int, json_body: dict):
    from unittest.mock import MagicMock

    r = MagicMock()
    r.status_code = status
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=json_body)
    return r
