"""Build Rune prompt context: schema, vocabulary, geo, temporal rules, session state."""

from __future__ import annotations

import json
from typing import Any

from nlsearch.memory.session import SessionState
from nlsearch.semantic.gold_layer import LOGICAL_FIELD_SQL, TABLES
from nlsearch.semantic.schema_store import SchemaStore
from nlsearch.vocabulary.ontology import (
    CLIENT_ROLE_TO_GROUP,
    CLIENT_SECTOR_TO_BUG,
    CLIENT_STAGE_CONTRACT_KEYS,
    CLIENT_STAGE_PLANNING_KEYS,
)
from nlsearch.vocabulary.synonyms import SECTOR_ALIASES, STAGE_CANONICAL


def sector_synonyms_for_prompt() -> dict[str, str]:
    return dict(SECTOR_ALIASES)


def stage_synonyms_for_prompt() -> dict[str, str]:
    return dict(STAGE_CANONICAL)


def entity_relationships() -> dict[str, list[str]]:
    """Hub-and-spoke joins used by the SQL generator."""
    return {
        "project_fields": [
            "site_address",
            "contract_stages",
            "planning_stages",
            "project_statuses",
            "development_types",
            "project_building_uses",
            "building_use_definitions",
            "project_roles",
            "project_role_contacts",
            "project_green_building",
            "project_metadata",
        ],
        "project_roles": ["role_definitions", "role_groups", "project_role_contacts"],
        "dimension_tables": list(TABLES.values()),
    }


def temporal_rules(context: dict[str, Any] | None) -> dict[str, Any]:
    ctx = context or {}
    return {
        "timezone": "Europe/Stockholm",
        "eval_now": ctx.get("eval_now"),
        "relative_phrases": {
            "last 30 days": "last_modified_at BETWEEN eval_now-30d AND eval_now",
            "last week": "last_modified_at >= eval_now-7d",
            "next year": "construction_start_date in calendar year eval_now.year+1",
            "stale / not updated 6 months": "last_modified_at < eval_now-180d",
        },
        "field_binding": {
            "updated/new": "last_modified_at",
            "start/ground/breaking": "construction_start_date",
            "complete/finish": "construction_end_date",
        },
    }


def geo_dictionary_sample(max_places: int = 40) -> dict[str, Any]:
    """Compact place hints for the model (not full facet dump)."""
    try:
        from nlsearch.normalizers.places import _FALLBACK_GAZETTEER
        from nlsearch.vocabulary.ontology import load_places_gazetteer

        gaz = load_places_gazetteer(("SE", "NO"))
        if not gaz:
            gaz = _FALLBACK_GAZETTEER  # type: ignore[assignment]
        sample = {}
        for i, (key, meta) in enumerate(gaz.items()):
            if i >= max_places:
                break
            sample[key] = meta
        return sample
    except Exception:
        from nlsearch.normalizers.places import _FALLBACK_GAZETTEER

        return dict(list(_FALLBACK_GAZETTEER.items())[:max_places])


def business_vocabulary() -> dict[str, Any]:
    return {
        "role_groups": CLIENT_ROLE_TO_GROUP,
        "sector_to_building_use_group": CLIENT_SECTOR_TO_BUG,
        "contract_stage_keys": CLIENT_STAGE_CONTRACT_KEYS,
        "planning_stage_keys": CLIENT_STAGE_PLANNING_KEYS,
        "filter_fields": sorted(LOGICAL_FIELD_SQL.keys()),
        "project_status_exclusions_default": ["CAN", "HOL", "PND", "SFS"],
    }


def schema_catalog_json(schema_store: SchemaStore, query: str) -> dict[str, Any]:
    """Relevant tables + columns for this query (RAG), as JSON-serializable catalog."""
    entities = ["project", "company", "person", "cross", "semantic", "temporal", "keyword"]
    chunks = schema_store.retrieve_for_query(query, entities)
    catalog: dict[str, Any] = {"tables": [], "relationships": entity_relationships()}
    for t in chunks:
        catalog["tables"].append(
            {
                "table": t.get("table"),
                "full_name": t.get("full_name"),
                "description": (t.get("description") or "")[:400],
                "columns": [
                    {"name": c["name"], "type": c.get("type", "string")}
                    for c in t.get("columns", [])
                ],
            }
        )
    return catalog


def conversation_state(session: SessionState | None) -> dict[str, Any]:
    if not session or not session.filters:
        return {"active_filters": [], "result_type": None}
    return {
        "active_filters": session.filters,
        "result_type": session.result_type.value if session.result_type else None,
        "sort": session.sort,
        "limit": session.limit,
    }


def build_rune_user_payload(
    query: str,
    schema_store: SchemaStore,
    *,
    context: dict[str, Any] | None = None,
    session: SessionState | None = None,
) -> dict[str, Any]:
    ctx = context or {}
    return {
        "query": query,
        "schema_catalog": schema_catalog_json(schema_store, query),
        "sector_synonyms": sector_synonyms_for_prompt(),
        "stage_synonyms": stage_synonyms_for_prompt(),
        "business_vocabulary": business_vocabulary(),
        "geo_dictionary_sample": geo_dictionary_sample(),
        "temporal_rules": temporal_rules(ctx),
        "conversation_state": conversation_state(session),
        "licensed_regions": ctx.get("licensed_regions"),
        "user_region": ctx.get("user_region"),
    }
