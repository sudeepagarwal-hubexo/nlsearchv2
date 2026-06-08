"""Keyword vs semantic vs structured router (client AC-2)."""

from __future__ import annotations

import re

from nlsearch.models.intent import QueryMode


class ModeRouter:
    def classify(self, query: str) -> QueryMode:
        low = query.lower()

        if re.search(
            r"sustainable|energy-efficient|low-carbon|mass-timber|recladding|"
            r"breeam|facade renovation",
            low,
        ):
            if re.search(r"near me|within \d+km", low):
                return QueryMode.HYBRID
            return QueryMode.SEMANTIC

        if re.search(r"heatmap|league table|aggregate|total value across", low):
            return QueryMode.AGGREGATION

        if re.search(
            r"near me|within \d+km|radius|polygon|patch|not in \w+|gothenburg|göteborg.*km",
            low,
        ):
            return QueryMode.GEO

        if re.search(r"stage transition|moved to tender|breaking ground", low):
            return QueryMode.TEMPORAL

        if re.search(
            r"who's the client|which architects|project managers at|collaborated|"
            r"worked with before|top \d+ contractors",
            low,
        ):
            return QueryMode.CROSS_ENTITY

        if re.search(r"planning ref|planning_reference|~\w+|reference\s+\d", low):
            return QueryMode.KEYWORD

        if re.search(r"similar to|like project", low):
            return QueryMode.SIMILARITY

        # Structured predicates present
        if re.search(
            r"\b(stage|tender|sector|valued|over \d|between \d|sort|biggest|"
            r"residential|hospital|refurbishment|design.and.build)\b",
            low,
        ):
            return QueryMode.STRUCTURED

        return QueryMode.HYBRID
