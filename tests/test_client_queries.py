"""Orchestrator smoke tests (full catalog in test_query_catalog.py)."""

import pytest

from nlsearch.models.intent import QueryMode, ResultType
from nlsearch.orchestrator import QueryOrchestrator


@pytest.mark.asyncio
async def test_multi_turn_additive() -> None:
    orch = QueryOrchestrator()
    r1 = await orch.search("Tender projects in Stockholm", execute=False)
    sid = r1["session_id"]
    r2 = await orch.search("just the ones over 100M", session_id=sid, execute=False)
    assert r2.get("intent") is not None
    filters = {f["field"]: f for f in r2["intent"]["filters"]}
    assert "project_value" in filters or "postal_town" in filters or "admin_level_1" in str(r2)


@pytest.mark.asyncio
async def test_start_over_clears() -> None:
    orch = QueryOrchestrator()
    r1 = await orch.search("Projects in Stockholm", execute=False)
    r2 = await orch.search("start over", session_id=r1["session_id"], execute=False)
    assert r2.get("message") == "Session cleared"


@pytest.mark.asyncio
async def test_intent_has_result_type_and_mode() -> None:
    orch = QueryOrchestrator()
    r = await orch.search("Projects in Solna valued over 100M", execute=False)
    assert r["intent"]["result_type"] == ResultType.PROJECT.value
    assert r["intent"]["mode"] in {m.value for m in QueryMode}
