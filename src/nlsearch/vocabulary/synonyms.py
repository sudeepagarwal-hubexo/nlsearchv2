"""Role and stage synonym normalization — backed by ontology data when present."""

from __future__ import annotations

import re

from nlsearch.vocabulary.ontology import (
    EXCLUDED_PROJECT_STATUS_KEYS,
    build_alias_index,
    ontology_loaded,
    resolve_client_stage,
    resolve_sector_to_bug,
)

# Client-facing stage labels (ODT) before gold key expansion
STAGE_CANONICAL = {
    "planning": "Planning",
    "approved": "Approved",
    "tender": "Tender",
    "upphandling": "Tender",
    "anbud": "Tender",
    "construction": "Construction",
    "byggstart": "Construction",
    "complete": "Complete",
    "completed": "Complete",
}

ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(byggherre|beställare)\b", re.I), "Client"),
    (re.compile(r"\b(byggherre)\b", re.I), "Byggherre"),
    (re.compile(r"\b(client)\b", re.I), "Client"),
    (re.compile(r"\b(huvudentreprenör|main\s*contractor|gc|general\s*contractor)\b", re.I), "MainContractor"),
    (re.compile(r"\b(total\s*contractor)\b", re.I), "MainContractor"),
    (re.compile(r"\b(architect|arkitekt)\b", re.I), "Architect"),
    (re.compile(r"\b(electrical\s*contractor|el-?entreprenör|elentreprenör)\b", re.I), "ElectricalContractor"),
    (re.compile(r"\b(mechanical\s*contractor)\b", re.I), "MechanicalContractor"),
    (re.compile(r"\b(consultant|konsult)\b", re.I), "Consultant"),
    (re.compile(r"\b(developer|utvecklare|promoter)\b", re.I), "Developer"),
    (re.compile(r"\b(funder|finansiär)\b", re.I), "Funder"),
    (re.compile(r"\b(project\s*manager|pm|projektledare)\b", re.I), "ProjectManager"),
    (re.compile(r"\b(purchasing\s*manager|inköpschef)\b", re.I), "PurchasingManager"),
]

SECTOR_ALIASES = {
    "office": "Commercial",
    "kontor": "Commercial",
    "residential": "Residential",
    "bostad": "Residential",
    "housing": "Residential",
    "healthcare": "Healthcare",
    "hospital": "Healthcare",
    "sjukhus": "Healthcare",
    "education": "Education",
    "school": "Education",
    "skola": "Education",
    "commercial": "Commercial",
    "retail": "Retail",
    "industrial": "Industrial",
}

DEVELOPMENT_TYPE_ALIASES = {
    "new-build": "New",
    "new build": "New",
    "newbuild": "New",
    "nyproduktion": "New",
    "refurbishment": "Refurbishment",
    "renovation": "Refurbishment",
    "ombyggnad": "Refurbishment",
    "refurb": "Refurbishment",
    "extension": "Extension",
    "demolition": "Demolition",
}

PROCUREMENT_ALIASES = {
    "design and build": "Design Build",
    "design-and-build": "Design Build",
    "design & build": "Design Build",
    "traditional": "General/Traditional",
    "general/traditional": "General/Traditional",
}


def normalize_stage(text: str) -> str | None:
    key = text.strip().lower()
    if key in STAGE_CANONICAL:
        return STAGE_CANONICAL[key]
    for alias, canonical in STAGE_CANONICAL.items():
        if alias in key:
            return canonical
    if ontology_loaded():
        hit = build_alias_index().get(key)
        if hit and hit[0] in ("contract_stage", "planning_stage"):
            # Map gold key label back via client buckets
            for client, _ in [
                ("Tender", None),
                ("Planning", None),
                ("Construction", None),
            ]:
                dim, keys = resolve_client_stage(client)
                if isinstance(keys, list) and hit[1] in keys:
                    return client
                if hit[1] == keys:
                    return client
    return None


def normalize_role_from_text(text: str) -> str | None:
    for pattern, role in ROLE_PATTERNS:
        if pattern.search(text):
            return role
    return None


def normalize_sector(text: str) -> str | None:
    low = text.lower().strip()
    for alias, canonical in SECTOR_ALIASES.items():
        if alias in low:
            return canonical
    return None


def normalize_development_type(text: str) -> str | None:
    low = text.lower().strip()
    for alias, canonical in DEVELOPMENT_TYPE_ALIASES.items():
        if alias in low:
            return canonical
    if ontology_loaded():
        idx = build_alias_index()
        for alias, (kind, val) in idx.items():
            if kind == "development_type" and alias in low:
                return val
    return None


def normalize_contract_type(text: str) -> str | None:
    low = text.lower().strip()
    for alias, canonical in PROCUREMENT_ALIASES.items():
        if alias in low:
            return canonical
    if ontology_loaded():
        idx = build_alias_index()
        for alias, (kind, val) in idx.items():
            if kind == "contract_type" and alias in low:
                return val
    return None


def sector_to_building_use_group(sector: str) -> str:
    return resolve_sector_to_bug(sector)


DEFAULT_EXCLUDED_STATUS_KEYS = EXCLUDED_PROJECT_STATUS_KEYS
