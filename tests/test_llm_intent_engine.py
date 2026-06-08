"""Rune LLM intent engine (mocked provider)."""

from __future__ import annotations

import pytest

from nlsearch.llm.intent_parse import normalize_llm_filters, parse_rune_intent
from typing import Any

from nlsearch.llm.base import LLMProvider
from nlsearch.llm.rune_intent import LLMIntentEngine
from nlsearch.models.intent import FilterOperator, NoCoverageResponse, ResultType
from nlsearch.semantic.schema_store import SchemaStore


class MockLLM(LLMProvider):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = responses
        self._idx = 0

    @property
    def available(self) -> bool:
        return True

    async def complete_json(
        self, system: str, user: str, *, temperature: float | None = None
    ) -> dict[str, Any]:
        data = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return data


@pytest.fixture
def schema() -> SchemaStore:
    return SchemaStore()


def test_normalize_llm_field_aliases() -> None:
    data = normalize_llm_filters(
        {
            "filters": [
                {"field": "city", "operator": "=", "value": "Uppsala"},
                {"field": "stage", "operator": "=", "value": "Tender"},
                {"field": "value", "operator": ">", "value": 50_000_000},
            ]
        }
    )
    fields = {f["field"] for f in data["filters"]}
    assert "postal_town" in fields
    assert "contract_stage" in fields or "planning_stage" in fields
    assert "project_value" in fields


def test_sql_column_resolves_fqn_stage_path() -> None:
    from nlsearch.semantic.gold_layer import sql_column

    assert sql_column("contract_stage") == "cs.key"
    assert sql_column("europe_prod_catalog.mimir_model_gold.contract_stages.key") == "cs.key"


def test_normalize_llm_fqn_field() -> None:
    data = normalize_llm_filters(
        {
            "filters": [
                {
                    "field": "europe_prod_catalog.mimir_model_gold.contract_stages.key",
                    "operator": "IN",
                    "values": ["TCI", "TCR"],
                }
            ]
        }
    )
    assert data["filters"][0]["field"] == "contract_stage"


def test_parse_rune_intent_filters() -> None:
    data = {
        "result_type": "Project",
        "mode": "structured",
        "filters": [
            {"field": "postal_town", "operator": "=", "value": "Uppsala"},
            {"field": "contract_stage", "operator": "IN", "values": ["TCI", "TCR"]},
        ],
        "confidence": 0.9,
    }
    intent = parse_rune_intent(data)
    assert not isinstance(intent, NoCoverageResponse)
    assert intent.result_type == ResultType.PROJECT
    fields = {f.field for f in intent.filters}
    assert "postal_town" in fields
    assert any(f.operator == FilterOperator.IN for f in intent.filters)


def test_parse_rune_unsupported_no_coverage() -> None:
    data = {
        "result_type": "Project",
        "unsupported": ["zookeeper role"],
        "filters": [],
    }
    result = parse_rune_intent(data, query="projects with zookeeper")
    assert isinstance(result, NoCoverageResponse)


@pytest.mark.asyncio
async def test_llm_intent_engine_analyze(schema: SchemaStore) -> None:
    mock = MockLLM(
        [
            {
                "result_type": "Project",
                "mode": "structured",
                "filters": [
                    {"field": "admin_level_1", "operator": "=", "value": "Stockholm"},
                    {"field": "project_value", "operator": ">", "value": 100000000},
                ],
                "confidence": 0.92,
            }
        ]
    )
    engine = LLMIntentEngine(schema, provider=mock)
    system, user = engine.build_prompt("projects in Stockholm over 100M")
    assert "Rune" in system or "Schema" in user
    assert "Stockholm" in user or "stockholm" in user.lower()

    intent = await engine.analyze("projects in Stockholm over 100M", min_confidence=0.5)
    assert intent.result_type == ResultType.PROJECT
    assert any(f.field == "project_value" for f in intent.filters)
    assert any("Rune LLM" in a for a in intent.assumptions)


@pytest.mark.asyncio
async def test_orchestrator_primary_llm_intent() -> None:
    from nlsearch.orchestrator import QueryOrchestrator

    mock = MockLLM(
        [
            {
                "result_type": "Project",
                "mode": "structured",
                "filters": [{"field": "postal_town", "operator": "=", "value": "Solna"}],
                "confidence": 0.95,
            }
        ]
    )
    orch = QueryOrchestrator()
    orch._llm_intent = LLMIntentEngine(orch._schema, provider=mock)

    result = await orch.search(
        "projects in Solna",
        execute=False,
        use_llm=True,
        intent_mode="primary",
    )
    assert result.get("intent")
    assert result.get("intent_source") == "llm"
    assert result["intent"]["filters"][0]["value"] == "Solna"
