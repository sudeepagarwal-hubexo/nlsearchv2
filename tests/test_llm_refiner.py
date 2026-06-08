"""LLM refinement hooks (mocked — no API key required)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from nlsearch.llm.base import LLMProvider
from nlsearch.llm.refiner import LLMRefiner
from nlsearch.models.intent import FilterOperator, FilterPredicate, QueryIntent, QueryMode, ResultType


class MockLLM(LLMProvider):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = responses
        self._idx = 0

    @property
    def available(self) -> bool:
        return True

    async def complete_json(self, system: str, user: str, *, temperature: float | None = None) -> dict[str, Any]:
        data = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return data


@pytest.mark.asyncio
async def test_refine_intent_merges_high_confidence() -> None:
    draft = QueryIntent(
        result_type=ResultType.PROJECT,
        mode=QueryMode.STRUCTURED,
        filters=[FilterPredicate(field="city", operator=FilterOperator.EQ, value="Solna")],
    )
    mock = MockLLM(
        [
            {
                "result_type": "Project",
                "mode": "structured",
                "filters": [
                    {"field": "city", "operator": "=", "value": "Solna"},
                    {"field": "value", "operator": ">", "value": 100000000},
                ],
                "confidence": 0.95,
            }
        ]
    )
    refiner = LLMRefiner(provider=mock)
    refined = await refiner.refine_intent("Projects in Solna over 100M", draft, "schema")
    fields = {f.field for f in refined.filters}
    assert "value" in fields
    assert any("LLM intent refinement" in a for a in refined.assumptions)


@pytest.mark.asyncio
async def test_refine_intent_skips_low_confidence() -> None:
    draft = QueryIntent(result_type=ResultType.PROJECT, mode=QueryMode.STRUCTURED, filters=[])
    mock = MockLLM([{"result_type": "Project", "filters": [], "confidence": 0.1}])
    refiner = LLMRefiner(provider=mock)
    refined = await refiner.refine_intent("ambiguous", draft, "", min_confidence=0.85)
    assert refined.filters == []


@pytest.mark.asyncio
async def test_refine_sql_returns_model_sql() -> None:
    intent = QueryIntent(result_type=ResultType.PROJECT, mode=QueryMode.STRUCTURED)
    mock = MockLLM([{"sql": "SELECT project_id FROM projects WHERE city = 'Solna'", "assumptions": []}])
    refiner = LLMRefiner(provider=mock)
    sql, notes = await refiner.refine_sql("q", intent, "SELECT * FROM projects", "")
    assert "project_id" in sql
    assert notes == []
