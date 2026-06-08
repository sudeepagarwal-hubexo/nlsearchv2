"""Structured intent object (AC-1): executable by the app, never free-text-only."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ResultType(str, Enum):
    PROJECT = "Project"
    COMPANY = "Company"
    PERSON = "Person"
    WORKPLACE = "Workplace"
    STAT = "Stat"
    TIMELINE = "Timeline"


class QueryMode(str, Enum):
    STRUCTURED = "structured"
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    GEO = "geo"
    AGGREGATION = "aggregation"
    SIMILARITY = "similarity"
    TEMPORAL = "temporal"
    CROSS_ENTITY = "cross_entity"


class FilterOperator(str, Enum):
    EQ = "="
    NE = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    IN = "IN"
    BETWEEN = "BETWEEN"
    LIKE = "~"
    NOT = "NOT"
    NEAR = "Near"
    WITHIN_POLYGON = "WithinPolygon"
    SEMANTIC = "SemanticSearch"
    STAGE_TRANSITION = "StageTransition"


class FilterPredicate(BaseModel):
    field: str
    operator: FilterOperator = FilterOperator.EQ
    value: Any = None
    values: list[Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SortSpec(BaseModel):
    field: str
    direction: str = "ASC"  # ASC | DESC


class GeoSpec(BaseModel):
    kind: str  # near | within_polygon | heatmap
    anchor: str | None = None  # userLocation | HQ | place name
    radius_km: float | None = None
    polygon_id: str | None = None
    exclude_cities: list[str] = Field(default_factory=list)
    weight_field: str | None = None


class AggregationSpec(BaseModel):
    kind: str  # heatmap | count | sum | league_table
    field: str | None = None
    group_by: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class QueryIntent(BaseModel):
    """AC-1 structured intent returned for every supported search."""

    result_type: ResultType
    mode: QueryMode
    filters: list[FilterPredicate] = Field(default_factory=list)
    sort: list[SortSpec] | None = None
    limit: int | None = None
    aggregation: AggregationSpec | None = None
    geo: GeoSpec | None = None
    semantic_query: str | None = None
    cross_entity: dict[str, Any] | None = None
    assumptions: list[str] = Field(default_factory=list)
    dropped_constraints: list[str] = Field(default_factory=list)
    default_exclusions_applied: list[str] = Field(default_factory=list)
    license_notice: str | None = None
    sql: str | None = None
    session_patch: dict[str, Any] = Field(default_factory=dict)

    def to_expression(self) -> str:
        """Human-readable filter expression for logging / UI."""
        parts: list[str] = []
        for f in self.filters:
            if f.operator == FilterOperator.BETWEEN and f.values:
                parts.append(f"{f.field} BETWEEN {f.values[0]} AND {f.values[1]}")
            elif f.operator == FilterOperator.IN and f.values:
                vals = ", ".join(str(v) for v in f.values)
                parts.append(f"{f.field} IN ({vals})")
            elif f.operator == FilterOperator.SEMANTIC:
                parts.append(f'SemanticSearch("{f.value}")')
            elif f.operator == FilterOperator.NEAR:
                r = f.meta.get("radius_km", 25)
                parts.append(f"Near({f.value}, radius={r}km)")
            else:
                parts.append(f"{f.field}{f.operator.value}{f.value!r}")
        if self.geo and self.geo.kind == "heatmap":
            parts.append(f"Heatmap(weight={self.geo.weight_field})")
        if self.sort:
            for s in self.sort:
                parts.append(f"SortBy={s.field} {s.direction}")
        if self.limit:
            parts.append(f"Limit={self.limit}")
        return " AND ".join(parts) if parts else "(no filters)"


class NoCoverageResponse(BaseModel):
    """Typed message when nothing in the query can be executed (AC-1)."""

    code: str
    message: str
    unsupported_predicates: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    session_id: str
    intent: QueryIntent | None = None
    no_coverage: NoCoverageResponse | None = None
    explanation: str = ""
    latency_ms: dict[str, float] = Field(default_factory=dict)
    requires_clarification: bool = False
    clarification_question: str | None = None
