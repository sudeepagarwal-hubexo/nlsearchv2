"""Merge rule-based intent/SQL with optional LLM refinement."""

from __future__ import annotations

import json
import logging
from typing import Any

from nlsearch.llm.base import LLMProvider
from nlsearch.llm.factory import get_llm_provider
from nlsearch.models.intent import FilterOperator, FilterPredicate, QueryIntent, QueryMode, ResultType, SortSpec

logger = logging.getLogger(__name__)

_INTENT_SYSTEM = """You are a Hubexo NL search intent refiner.
Given a user query, rule-based draft intent, and schema context, return JSON:
{
  "result_type": "Project|Company|Person|Workplace|Stat|Timeline",
  "mode": "structured|keyword|semantic|hybrid|geo|aggregation|temporal|cross_entity",
  "filters": [{"field": "...", "operator": "=|>|>=|<|<=|IN|BETWEEN|~|SemanticSearch", "value": ..., "values": [...]}],
  "sort": [{"field": "...", "direction": "ASC|DESC"}],
  "limit": null,
  "semantic_query": null,
  "assumptions": [],
  "dropped_constraints": [],
  "confidence": 0.0-1.0
}
Preserve licensing and security constraints. Use integer SEK for value. Do not invent tables."""

_SQL_SYSTEM = """You are a SQL expert for Databricks (ANSI SQL).
Given schema context, structured intent, and draft SQL, return JSON:
{"sql": "SELECT ...", "assumptions": [], "warnings": []}
Only SELECT. Respect tenant and region filters from intent."""


class LLMRefiner:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider

    @classmethod
    def from_settings(cls) -> LLMRefiner:
        return cls(provider=get_llm_provider())

    @property
    def enabled(self) -> bool:
        return self._provider is not None and self._provider.available

    async def refine_intent(
        self,
        query: str,
        draft: QueryIntent,
        schema_context: str,
        *,
        min_confidence: float = 0.85,
    ) -> QueryIntent:
        if not self.enabled:
            return draft

        user = json.dumps(
            {
                "query": query,
                "draft_intent": draft.model_dump(),
                "schema_context": schema_context,
            },
            default=str,
        )
        try:
            data = await self._provider.complete_json(_INTENT_SYSTEM, user)  # type: ignore[union-attr]
        except Exception:
            logger.exception("LLM intent refinement failed; using rule-based draft")
            draft.assumptions.append("LLM intent refinement skipped (error)")
            return draft

        confidence = float(data.get("confidence", 0))
        if confidence < min_confidence:
            draft.assumptions.append(f"LLM confidence {confidence:.2f} below threshold; kept rule-based intent")
            return draft

        merged = _merge_intent(draft, data)
        merged.assumptions.append(f"LLM intent refinement applied (confidence={confidence:.2f})")
        return merged

    async def refine_sql(
        self,
        query: str,
        intent: QueryIntent,
        draft_sql: str,
        schema_context: str,
    ) -> tuple[str, list[str]]:
        if not self.enabled:
            return draft_sql, []

        user = json.dumps(
            {
                "query": query,
                "intent": intent.model_dump(),
                "draft_sql": draft_sql,
                "schema_context": schema_context,
            },
            default=str,
        )
        try:
            data = await self._provider.complete_json(_SQL_SYSTEM, user)  # type: ignore[union-attr]
        except Exception:
            logger.exception("LLM SQL refinement failed; using rule-based SQL")
            return draft_sql, ["LLM SQL refinement skipped (error)"]

        sql = (data.get("sql") or draft_sql).strip()
        assumptions = list(data.get("assumptions") or [])
        return sql, assumptions


def _merge_intent(draft: QueryIntent, llm: dict[str, Any]) -> QueryIntent:
    """Prefer LLM filters when present; keep session/geo from draft."""
    try:
        result_type = ResultType(llm.get("result_type", draft.result_type.value))
    except ValueError:
        result_type = draft.result_type

    try:
        mode = QueryMode(llm.get("mode", draft.mode.value))
    except ValueError:
        mode = draft.mode

    filters: list[FilterPredicate] = []
    for f in llm.get("filters") or []:
        op_raw = f.get("operator", "=")
        try:
            op = FilterOperator(op_raw)
        except ValueError:
            op = FilterOperator.EQ
        filters.append(
            FilterPredicate(
                field=f["field"],
                operator=op,
                value=f.get("value"),
                values=f.get("values"),
            )
        )
    if not filters:
        filters = list(draft.filters)

    sort = draft.sort
    if llm.get("sort"):
        sort = [SortSpec(field=s["field"], direction=s.get("direction", "ASC")) for s in llm["sort"]]

    return QueryIntent(
        result_type=result_type,
        mode=mode,
        filters=filters,
        sort=sort,
        limit=llm.get("limit") or draft.limit,
        aggregation=draft.aggregation,
        geo=draft.geo,
        semantic_query=llm.get("semantic_query") or draft.semantic_query,
        cross_entity=draft.cross_entity,
        assumptions=list(draft.assumptions) + list(llm.get("assumptions") or []),
        dropped_constraints=list(draft.dropped_constraints) + list(llm.get("dropped_constraints") or []),
        session_patch=draft.session_patch,
    )
