"""Full client query catalog regression (nl2sql-hubexo.odt)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nlsearch.intent.analyzer import IntentAnalyzer
from nlsearch.models.intent import NoCoverageResponse
from nlsearch.orchestrator import QueryOrchestrator

CATALOG_PATH = Path(__file__).parent / "data" / "client_query_catalog.json"


def _load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text())


def _catalog_queries():
    for row in _load_catalog()["queries"]:
        yield pytest.param(row, id=row["id"])


@pytest.fixture
def analyzer() -> IntentAnalyzer:
    return IntentAnalyzer()


@pytest.mark.parametrize("row", list(_catalog_queries()))
def test_catalog_row(analyzer: IntentAnalyzer, row: dict) -> None:
    result = analyzer.analyze(row["query"])
    assert not isinstance(result, NoCoverageResponse), (
        f"{row['id']}: {getattr(result, 'message', result)}"
    )

    if row.get("result_type"):
        assert result.result_type.value == row["result_type"], row["id"]

    if row.get("mode"):
        assert result.mode.value == row["mode"], row["id"]

    blob = result.to_expression() + result.model_dump_json()
    if result.geo:
        blob += json.dumps(result.geo.model_dump())
    for fragment in row.get("must_contain", []):
        assert fragment in blob, f"{row['id']}: missing {fragment!r} in {blob}"

    if fields := row.get("must_have_fields"):
        filter_fields = {f.field for f in result.filters}
        for f in fields:
            assert f in filter_fields, f"{row['id']}: missing field {f}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [pytest.param(r, id=r["id"]) for r in _load_catalog()["multi_turn"]],
)
async def test_multi_turn_catalog(row: dict) -> None:
    orch = QueryOrchestrator()
    r1 = await orch.search(row["setup"], execute=False, use_llm=False)
    sid = r1["session_id"]

    if row.get("expect_reset"):
        r2 = await orch.search(row["follow_up"], session_id=sid, execute=False, use_llm=False)
        assert r2.get("message") == "Session cleared"
        return

    r2 = await orch.search(row["follow_up"], session_id=sid, execute=False, use_llm=False)
    assert r2.get("intent") is not None, row["id"]
    blob = json.dumps(r2["intent"])
    for fragment in row.get("must_contain", []):
        assert fragment.lower() in blob.lower(), f"{row['id']}: missing {fragment!r}"
