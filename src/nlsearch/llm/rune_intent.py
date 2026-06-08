"""Rune Query Understanding Engine — LLM-primary intent analysis (no SQL)."""

from __future__ import annotations

import json
import logging
from typing import Any

from nlsearch.config import get_settings
from nlsearch.llm.base import LLMProvider
from nlsearch.llm.factory import get_llm_provider
from nlsearch.llm.intent_context import build_rune_user_payload
from nlsearch.llm.intent_parse import parse_rune_intent
from nlsearch.memory.session import SessionState, SessionStore
from nlsearch.models.intent import NoCoverageResponse, QueryIntent
from nlsearch.semantic.schema_store import SchemaStore

logger = logging.getLogger(__name__)

RUNE_SYSTEM = """You are Rune Query Understanding Engine.

Your task is to convert natural language into a canonical query object.

You do not generate SQL.
You do not generate explanations.
You only produce JSON.

You have access to:

1. Schema Catalog
2. Entity Relationships
3. Business Vocabulary
4. Geo Dictionary
5. Temporal Rules
6. Conversation State

Always use metadata definitions.
Never invent fields.
Never invent enum values.
Use only filter field names listed in business_vocabulary.filter_fields.
Use gold keys for contract_stage, planning_stage, project_status, building_use_group (e.g. TCI, SOS, BUG-RES).
Use role_group codes for company_role (MCT, ARC, DEV, SCT, etc.).
Monetary amounts must be integers in SEK.
Unsupported constraints must be listed in unsupported[].

Return a single JSON object with this shape:
{
  "result_type": "Project|Company|Person|Workplace|Stat|Timeline",
  "mode": "structured|keyword|semantic|hybrid|geo|aggregation|temporal|cross_entity",
  "filters": [{"field": "...", "operator": "=|>|>=|<|<=|IN|BETWEEN|~|NOT|SemanticSearch", "value": ..., "values": [...]}],
  "sort": [{"field": "...", "direction": "ASC|DESC"}],
  "limit": null,
  "geo": {"kind": "near|within_polygon", "anchor": "...", "radius_km": 25, "exclude_cities": []},
  "aggregation": {"kind": "heatmap|count|sum", "field": "...", "group_by": []},
  "semantic_query": null,
  "cross_entity": null,
  "assumptions": [],
  "dropped_constraints": [],
  "unsupported": [],
  "confidence": 0.0
}

Schema Catalog and context are in the user message JSON."""


class LLMIntentEngine:
    """LLM-based intent identification (Rune), optional fallback to rule-based analyzer."""

    def __init__(
        self,
        schema_store: SchemaStore,
        provider: LLMProvider | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self._schema = schema_store
        self._provider = provider
        self._sessions = session_store

    @classmethod
    def from_settings(
        cls,
        schema_store: SchemaStore,
        session_store: SessionStore | None = None,
    ) -> LLMIntentEngine:
        return cls(schema_store, provider=get_llm_provider(), session_store=session_store)

    @property
    def enabled(self) -> bool:
        return self._provider is not None and self._provider.available

    def build_prompt(self, query: str, context: dict[str, Any] | None = None) -> tuple[str, str]:
        session = None
        if self._sessions and context and context.get("session_id"):
            session = self._sessions.get(context["session_id"])
        payload = build_rune_user_payload(
            query,
            self._schema,
            context=context,
            session=session,
        )
        schema_json = json.dumps(payload["schema_catalog"], ensure_ascii=False, indent=2)
        user_body = (
            f"Schema:\n\n{schema_json}\n\n"
            f"Sector Synonyms:\n\n{json.dumps(payload['sector_synonyms'], ensure_ascii=False)}\n\n"
            f"Stage Synonyms:\n\n{json.dumps(payload['stage_synonyms'], ensure_ascii=False)}\n\n"
            f"Business Vocabulary:\n\n{json.dumps(payload['business_vocabulary'], ensure_ascii=False)}\n\n"
            f"Geo Dictionary (sample):\n\n{json.dumps(payload['geo_dictionary_sample'], ensure_ascii=False)}\n\n"
            f"Temporal Rules:\n\n{json.dumps(payload['temporal_rules'], ensure_ascii=False)}\n\n"
            f"Conversation State:\n\n{json.dumps(payload['conversation_state'], ensure_ascii=False)}\n\n"
            f"Licensed regions: {json.dumps(payload.get('licensed_regions'))}\n"
            f"User region: {json.dumps(payload.get('user_region'))}\n\n"
            f"User Query:\n\n{query}"
        )
        return RUNE_SYSTEM, user_body

    async def analyze(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        *,
        min_confidence: float | None = None,
    ) -> QueryIntent | NoCoverageResponse:
        if not self.enabled:
            raise RuntimeError("LLM intent engine is not configured")

        settings = get_settings()
        threshold = min_confidence if min_confidence is not None else settings.llm_min_confidence
        system, user = self.build_prompt(query, context)
        # print("System:", system)
        # print("User:", user)
        try:
            data = await self._provider.complete_json(system, user)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Rune LLM intent analysis failed")
            raise

        confidence = float(data.get("confidence", 0))
        if confidence < threshold:
            raise ValueError(
                f"LLM intent confidence {confidence:.2f} below threshold {threshold:.2f}"
            )

        result = parse_rune_intent(data, query=query)
        if isinstance(result, QueryIntent):
            result.assumptions.append(
                f"Rune LLM intent (confidence={confidence:.2f})"
            )
        return result
