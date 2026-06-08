"""Load ontologies from vocabulary/data/*.json (synced from gold dimension tables)."""

from __future__ import annotations

import ast
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).parent / "data"

# Client ODT stage labels → gold dimension keys (built from warehouse + spec)
CLIENT_STAGE_CONTRACT_KEYS: dict[str, list[str]] = {
    "Tender": ["TCI", "TCR", "ATR", "PRE", "NEG"],
    "Construction": ["SOS", "AWD"],
    "Complete": ["COM"],
}

CLIENT_STAGE_PLANNING_KEYS: dict[str, list[str]] = {
    "Planning": ["EPL", "DIP", "SCH", "REZ", "APP"],
    "Approved": ["APR", "DCO"],
}

# Client sector label → building_use_group code (from building_use_groups.json)
CLIENT_SECTOR_TO_BUG: dict[str, str] = {
    "Residential": "BUG-RES",
    "Commercial": "BUG-COM",
    "Healthcare": "BUG-HLT",
    "Education": "BUG-EDU",
    "Retail": "BUG-RET",
    "Industrial": "BUG-IND",
    "Hospitality": "BUG-RET",
}

# Client role → role_group_code prefix (from role_groups.json)
CLIENT_ROLE_TO_GROUP: dict[str, str] = {
    "Client": "DEV",
    "MainContractor": "MCT",
    "Architect": "ARC",
    "ElectricalContractor": "SCT",
    "MechanicalContractor": "SCT",
    "Consultant": "ENG",
    "Developer": "DEV",
    "Funder": "OTH",
    "ProjectManager": "ENG",
    "PurchasingManager": "ENG",
}

# Specific role codes for high-traffic NL terms (from role_definitions labels)
CLIENT_ROLE_CODES: dict[str, list[str]] = {
    "Client": ["DEV-002"],
    "Byggherre": ["DEV-028", "DEV-002"],
    "ElectricalContractor": ["SCT-040"],
}

# Frozen project_status keys to exclude (AC-5)
EXCLUDED_PROJECT_STATUS_KEYS = ("CAN", "HOL", "PND", "SFS")


def _parse_i18n(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return [raw]
    return []


def _load_json(name: str) -> list[dict[str, Any]]:
    path = _DATA_DIR / f"{name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


@lru_cache
def ontology_loaded() -> bool:
    return (_DATA_DIR / "contract_stages.json").exists()


@lru_cache
def build_alias_index() -> dict[str, tuple[str, str]]:
    """
    Lowercase alias → (ontology_kind, canonical_value).
    Kinds: contract_stage, planning_stage, project_status, contract_type,
           development_type, building_use_group, role_group, role_code, scheme, place
    """
    index: dict[str, tuple[str, str]] = {}

    def add(alias: str, kind: str, canonical: str) -> None:
        key = alias.strip().lower()
        if key and len(key) > 1:
            index[key] = (kind, canonical)

    for row in _load_json("contract_stages"):
        c = row.get("canonical", "")
        add(c, "contract_stage", c)
        add(row.get("label_en", ""), "contract_stage", c)
        for lbl in _parse_i18n(row.get("labels_i18n")):
            add(lbl, "contract_stage", c)

    for row in _load_json("planning_stages"):
        c = row.get("canonical", "")
        add(c, "planning_stage", c)
        add(row.get("label_en", ""), "planning_stage", c)
        for lbl in _parse_i18n(row.get("labels_i18n")):
            add(lbl, "planning_stage", c)

    for row in _load_json("project_statuses"):
        c = row.get("canonical", "")
        add(c, "project_status", c)
        add(row.get("label_en", ""), "project_status", c)
        for lbl in _parse_i18n(row.get("labels_i18n")):
            add(lbl, "project_status", c)

    for row in _load_json("contract_types"):
        c = row.get("canonical", "")
        add(c, "contract_type", c)

    for row in _load_json("development_types"):
        c = row.get("canonical", "")
        add(c, "development_type", c)

    for row in _load_json("building_use_groups"):
        c = row.get("canonical", "")
        add(c, "building_use_group", c)
        add(row.get("label_en", ""), "building_use_group", c)

    for row in _load_json("role_groups"):
        c = row.get("canonical", "")
        add(c, "role_group", c)
        add(row.get("label_en", ""), "role_group", c)

    for row in _load_json("role_definitions"):
        c = row.get("canonical", "")
        add(c, "role_code", c)
        add(row.get("label_en", ""), "role_code", c)
        for lbl in _parse_i18n(row.get("labels_i18n")):
            add(lbl, "role_code", c)

    for row in _load_json("green_building_schemes"):
        c = row.get("canonical", "")
        add(c, "green_scheme", c)
        add(row.get("label_en", ""), "green_scheme", c)

    # Client doc shortcuts
    for label, keys in CLIENT_STAGE_CONTRACT_KEYS.items():
        for k in keys:
            add(label, "client_stage_contract", label)
    return index


def resolve_client_stage(stage_label: str) -> tuple[str, str | list[str]]:
    """
    Map client stage (Tender, Planning, …) to (dimension_field, key or list of keys).
    """
    if stage_label in CLIENT_STAGE_CONTRACT_KEYS:
        return "contract_stage", CLIENT_STAGE_CONTRACT_KEYS[stage_label]
    if stage_label in CLIENT_STAGE_PLANNING_KEYS:
        return "planning_stage", CLIENT_STAGE_PLANNING_KEYS[stage_label]
    # Fallback: try alias index for a single key
    idx = build_alias_index()
    hit = idx.get(stage_label.lower())
    if hit and hit[0] in ("contract_stage", "planning_stage"):
        return hit[0], hit[1]
    return "contract_stage", stage_label


def resolve_sector_to_bug(sector: str) -> str:
    return CLIENT_SECTOR_TO_BUG.get(sector, sector)


def resolve_role_pattern(role: str) -> str:
    """SQL LIKE pattern for project_role_code."""
    codes = CLIENT_ROLE_CODES.get(role)
    if codes:
        return codes[0]  # exact code preferred in EXISTS
    group = CLIENT_ROLE_TO_GROUP.get(role, role[:3].upper())
    return f"{group}%"


def resolve_role_codes(role: str) -> list[str] | None:
    return CLIENT_ROLE_CODES.get(role)


def lookup_alias(text: str) -> tuple[str, str] | None:
    """Find first matching ontology alias in text."""
    low = text.lower()
    index = build_alias_index()
    # Longest match first
    for alias in sorted(index.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return index[alias]
    return None


@lru_cache
def load_places_gazetteer(countries: tuple[str, ...] = ("SE", "NO")) -> dict[str, dict[str, str]]:
    """Build place gazetteer from facet_places.json (postal_town → admin levels)."""
    gazetteer: dict[str, dict[str, str]] = {}
    for row in _load_json("facet_places"):
        if countries and row.get("country") not in countries:
            continue
        town = (row.get("postal_town") or "").strip()
        if not town:
            continue
        key = town.lower()
        if key not in gazetteer:
            gazetteer[key] = {
                "postal_town": town,
                "admin_level_1": row.get("admin_level_1") or "",
                "admin_level_2": row.get("admin_level_2") or "",
                "country": row.get("country") or "",
            }
    return gazetteer
