"""Conversation session filter state (AC-7): additive / replace / pivot / reset."""

from __future__ import annotations

import json
import uuid
from typing import Any

from nlsearch.config import get_settings
from nlsearch.models.intent import FilterPredicate, QueryIntent, ResultType


class SessionState:
    def __init__(self) -> None:
        self.filters: list[dict[str, Any]] = []
        self.result_type: ResultType | None = ResultType.PROJECT
        self.last_results_meta: dict[str, Any] = {}
        self.sort: list[dict[str, str]] | None = None
        self.limit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filters": self.filters,
            "result_type": self.result_type.value if self.result_type else None,
            "last_results_meta": self.last_results_meta,
            "sort": self.sort,
            "limit": self.limit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        s = cls()
        s.filters = data.get("filters", [])
        rt = data.get("result_type")
        s.result_type = ResultType(rt) if rt else ResultType.PROJECT
        s.last_results_meta = data.get("last_results_meta", {})
        s.sort = data.get("sort")
        s.limit = data.get("limit")
        return s


class SessionStore:
    def __init__(self) -> None:
        self._memory: dict[str, SessionState] = {}
        self._redis = None
        settings = get_settings()
        if settings.redis_url:
            try:
                import redis

                self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            except Exception:
                self._redis = None

    def create_session(self) -> str:
        sid = str(uuid.uuid4())
        self.save(sid, SessionState())
        return sid

    def get(self, session_id: str) -> SessionState:
        if self._redis:
            raw = self._redis.get(f"nlsearch:session:{session_id}")
            if raw:
                return SessionState.from_dict(json.loads(raw))
        return self._memory.get(session_id, SessionState())

    def save(self, session_id: str, state: SessionState) -> None:
        data = json.dumps(state.to_dict())
        if self._redis:
            ttl = get_settings().session_ttl_seconds
            self._redis.setex(f"nlsearch:session:{session_id}", ttl, data)
        self._memory[session_id] = state

    def apply_turn(self, session_id: str, intent: QueryIntent, utterance: str) -> SessionState:
        state = self.get(session_id)
        low = utterance.lower().strip()

        if low in ("start over", "reset", "clear", "new search"):
            state = SessionState()
            self.save(session_id, state)
            return state

        # Replace one field: "now in Göteborg instead"
        if "instead" in low and intent.filters:
            replace_field = intent.filters[0].field
            state.filters = [f for f in state.filters if f.get("field") != replace_field]

        # Pivot: "who's the client on the biggest one?"
        if intent.result_type != state.result_type and state.filters:
            state.result_type = intent.result_type
            if intent.sort:
                state.sort = [{"field": s.field, "direction": s.direction} for s in intent.sort]
            if intent.limit:
                state.limit = intent.limit
            self.save(session_id, state)
            return state

        # Additive: "just the ones over 100M"
        for f in intent.filters:
            fd = {"field": f.field, "operator": f.operator.value, "value": f.value, "values": f.values}
            if not any(
                existing.get("field") == f.field and existing.get("operator") == f.operator.value
                for existing in state.filters
            ):
                state.filters.append(fd)

        if intent.sort:
            state.sort = [{"field": s.field, "direction": s.direction} for s in intent.sort]
        if intent.limit:
            state.limit = intent.limit
        if intent.result_type:
            state.result_type = intent.result_type

        self.save(session_id, state)
        return state

    def merge_into_intent(self, session_id: str, intent: QueryIntent) -> QueryIntent:
        state = self.get(session_id)
        if not state.filters:
            return intent

        existing_fields = {f.field for f in intent.filters}
        for sf in state.filters:
            if sf["field"] not in existing_fields:
                intent.filters.append(
                    FilterPredicate(
                        field=sf["field"],
                        operator=sf["operator"],  # type: ignore[arg-type]
                        value=sf.get("value"),
                        values=sf.get("values"),
                    )
                )
        if state.sort and not intent.sort:
            from nlsearch.models.intent import SortSpec

            intent.sort = [SortSpec(**s) for s in state.sort]
        if state.limit and not intent.limit:
            intent.limit = state.limit
        if state.result_type and intent.result_type == ResultType.PROJECT:
            intent.result_type = state.result_type
        return intent
