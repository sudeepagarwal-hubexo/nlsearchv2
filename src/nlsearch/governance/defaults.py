"""Default exclusions (AC-5) — applied and named; override via explicit phrasing."""

from __future__ import annotations

import re

from nlsearch.models.intent import FilterOperator, FilterPredicate, QueryIntent, ResultType
from nlsearch.vocabulary.synonyms import DEFAULT_EXCLUDED_STATUS_KEYS


class DefaultExclusions:
    def should_apply(self, query: str) -> bool:
        low = query.lower()
        if re.search(r"\b(include cancelled|show archived|include on-hold|inactive)\b", low):
            return False
        return True

    def apply(self, intent: QueryIntent, query: str) -> QueryIntent:
        if not self.should_apply(query):
            return intent
        if intent.default_exclusions_applied or any(
            f.meta.get("default_exclusion") for f in intent.filters
        ):
            return intent

        applied: list[str] = []
        if intent.result_type == ResultType.PROJECT:
            intent.filters.append(
                FilterPredicate(
                    field="project_status",
                    operator=FilterOperator.NOT,
                    values=list(DEFAULT_EXCLUDED_STATUS_KEYS),
                    meta={"default_exclusion": True},
                )
            )
            applied.append(
                "Excluded frozen project_status (cancelled/on_hold/archived/status_pending)"
            )

        if intent.result_type == ResultType.PERSON:
            if not any(f.field == "is_active" for f in intent.filters):
                intent.filters.append(
                    FilterPredicate(field="is_active", operator=FilterOperator.EQ, value=True)
                )
                applied.append("Person isActive=true")

        intent.default_exclusions_applied = applied
        return intent
