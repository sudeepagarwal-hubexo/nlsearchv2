"""Parse Rune canonical JSON into QueryIntent or NoCoverageResponse."""

from __future__ import annotations

from typing import Any

from nlsearch.models.intent import (
    AggregationSpec,
    FilterOperator,
    FilterPredicate,
    GeoSpec,
    NoCoverageResponse,
    QueryIntent,
    QueryMode,
    ResultType,
    SortSpec,
)

_OPERATOR_MAP = {
    "=": FilterOperator.EQ,
    "==": FilterOperator.EQ,
    "!=": FilterOperator.NE,
    ">": FilterOperator.GT,
    ">=": FilterOperator.GTE,
    "<": FilterOperator.LT,
    "<=": FilterOperator.LTE,
    "IN": FilterOperator.IN,
    "in": FilterOperator.IN,
    "BETWEEN": FilterOperator.BETWEEN,
    "between": FilterOperator.BETWEEN,
    "~": FilterOperator.LIKE,
    "LIKE": FilterOperator.LIKE,
    "SemanticSearch": FilterOperator.SEMANTIC,
    "semanticsearch": FilterOperator.SEMANTIC,
    "NOT": FilterOperator.NOT,
    "Near": FilterOperator.NEAR,
    "StageTransition": FilterOperator.STAGE_TRANSITION,
}


def _parse_operator(raw: str) -> FilterOperator:
    return _OPERATOR_MAP.get(raw, FilterOperator.EQ)


def _parse_geo(data: dict[str, Any] | None) -> GeoSpec | None:
    if not data:
        return None
    return GeoSpec(
        kind=data.get("kind", "near"),
        anchor=data.get("anchor"),
        radius_km=data.get("radius_km"),
        polygon_id=data.get("polygon_id"),
        exclude_cities=list(data.get("exclude_cities") or []),
        weight_field=data.get("weight_field"),
    )


def _parse_aggregation(data: dict[str, Any] | None) -> AggregationSpec | None:
    if not data:
        return None
    return AggregationSpec(
        kind=data.get("kind", "count"),
        field=data.get("field"),
        group_by=list(data.get("group_by") or []),
        params=dict(data.get("params") or {}),
    )


_FIELD_ALIASES = {
    "city": "postal_town",
    "town": "postal_town",
    "value": "project_value",
    "region": "admin_level_1",
    "stage": "contract_stage",
    "updated_at": "last_modified_at",
    "construction_start": "construction_start_date",
    "construction_end": "construction_end_date",
}


def _canonical_field(field: str) -> str:
    """Normalize LLM/schema-catalog field paths to intent logical names."""
    raw = (field or "").strip()
    if raw in _FIELD_ALIASES:
        return _FIELD_ALIASES[raw]
    low = raw.lower()
    if "contract_stage" in low or "contract_stages" in low:
        return "contract_stage"
    if "planning_stage" in low or "planning_stages" in low:
        return "planning_stage"
    if "project_status" in low or "project_statuses" in low:
        return "project_status"
    if "building_use_group" in low:
        return "building_use_group"
    if "building_use_code" in low or "project_building_uses" in low:
        return "building_use_code"
    if "development_type" in low:
        return "development_type"
    if "project_value" in low or low in ("value", "cost", "budget"):
        return "project_value"
    if low.endswith(".key") or low.endswith(".id"):
        parent = raw.rsplit(".", 1)[0].lower()
        if "contract" in parent:
            return "contract_stage"
        if "planning" in parent:
            return "planning_stage"
        if "status" in parent:
            return "project_status"
    tail = raw.split(".")[-1]
    return _FIELD_ALIASES.get(tail, tail)


def normalize_llm_filters(data: dict[str, Any]) -> dict[str, Any]:
    """Map common LLM field names to gold-layer intent fields."""
    from nlsearch.semantic.gold_layer import resolve_stage_filter
    from nlsearch.vocabulary.synonyms import normalize_stage

    out = dict(data)
    filters: list[dict[str, Any]] = []
    for f in data.get("filters") or []:
        if not f.get("field"):
            continue
        field = _canonical_field(str(f["field"]))
        nf = dict(f)
        nf["field"] = field
        if field in ("contract_stage", "planning_stage", "stage") and nf.get("value") and not nf.get("values"):
            stage = normalize_stage(str(nf["value"]))
            if stage:
                dim, keys = resolve_stage_filter(stage)
                nf["field"] = dim
                if isinstance(keys, list):
                    nf["values"] = keys
                    nf.pop("value", None)
                else:
                    nf["value"] = keys
        if field == "project_value" and nf.get("value") is not None:
            try:
                nf["value"] = int(nf["value"])
            except (TypeError, ValueError):
                pass
        filters.append(nf)
    out["filters"] = filters
    return out


def parse_rune_intent(data: dict[str, Any], *, query: str = "") -> QueryIntent | NoCoverageResponse:
    data = normalize_llm_filters(data)
    """Map LLM JSON to typed intent. `unsupported` → NoCoverage when no executable filters."""
    unsupported = list(data.get("unsupported") or data.get("unsupported_constraints") or [])
    dropped = list(data.get("dropped_constraints") or data.get("dropped") or [])
    assumptions = list(data.get("assumptions") or [])

    try:
        result_type = ResultType(data.get("result_type", "Project"))
    except ValueError:
        result_type = ResultType.PROJECT

    try:
        mode = QueryMode(data.get("mode", "structured"))
    except ValueError:
        mode = QueryMode.STRUCTURED

    filters: list[FilterPredicate] = []
    for f in data.get("filters") or []:
        if not f.get("field"):
            continue
        op = _parse_operator(str(f.get("operator", "=")))
        filters.append(
            FilterPredicate(
                field=f["field"],
                operator=op,
                value=f.get("value"),
                values=f.get("values"),
                meta=dict(f.get("meta") or {}),
            )
        )

    sort = None
    if data.get("sort"):
        sort = [
            SortSpec(field=s["field"], direction=s.get("direction", "ASC"))
            for s in data["sort"]
            if s.get("field")
        ]

    geo = _parse_geo(data.get("geo"))
    aggregation = _parse_aggregation(data.get("aggregation"))

    if unsupported and not filters and not geo and not aggregation:
        return NoCoverageResponse(
            code="NO_COVERAGE",
            message="Could not map this query to supported predicates.",
            unsupported_predicates=unsupported,
        )

    if not filters and not geo and not aggregation and not data.get("semantic_query"):
        if unsupported:
            return NoCoverageResponse(
                code="NO_COVERAGE",
                message="Could not map this query to supported predicates.",
                unsupported_predicates=unsupported or [query],
            )

    return QueryIntent(
        result_type=result_type,
        mode=mode,
        filters=filters,
        sort=sort,
        limit=data.get("limit"),
        aggregation=aggregation,
        geo=geo,
        semantic_query=data.get("semantic_query"),
        cross_entity=data.get("cross_entity"),
        assumptions=assumptions,
        dropped_constraints=dropped,
        license_notice=data.get("license_notice"),
        session_patch=dict(data.get("session_patch") or {}),
    )
