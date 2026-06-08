"""Result formatter with explanations (AC-3, AC-5)."""

from __future__ import annotations

from typing import Any

from nlsearch.models.intent import QueryIntent, SearchResponse


class ResultFormatter:
    def format(
        self,
        intent: QueryIntent,
        rows: list[dict[str, Any]],
        response: SearchResponse,
    ) -> dict[str, Any]:
        parts = [
            f"Resolved: {intent.to_expression()}",
            f"Mode: {intent.mode.value} → {intent.result_type.value}",
        ]
        if intent.assumptions:
            parts.append("Assumptions: " + "; ".join(intent.assumptions))
        if intent.default_exclusions_applied:
            parts.append("Defaults: " + "; ".join(intent.default_exclusions_applied))
        if intent.dropped_constraints:
            parts.append("Dropped (unsupported): " + "; ".join(intent.dropped_constraints))
        if intent.license_notice:
            parts.append(intent.license_notice)

        response.explanation = " | ".join(parts)
        return {
            "intent": intent.model_dump(),
            "expression": intent.to_expression(),
            "sql": intent.sql,
            "rows": rows,
            "row_count": len(rows),
            "explanation": response.explanation,
            "requires_clarification": response.requires_clarification,
            "clarification_question": response.clarification_question,
        }
