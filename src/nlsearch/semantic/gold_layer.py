"""Map client NL vocabulary (ODT) to Mimir gold-layer tables and columns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Hub table — all project-scoped queries anchor here
PROJECT_HUB = "project_fields"

# Tables joined from schema_metadata.json (mimir_model_gold)
TABLES = {
    "project_hub": PROJECT_HUB,
    "site": "site_address",
    "roles": "project_roles",
    "role_contacts": "project_role_contacts",
    "contract_stages": "contract_stages",
    "planning_stages": "planning_stages",
    "project_statuses": "project_statuses",
    "development_types": "development_types",
    "building_uses": "project_building_uses",
    "building_use_defs": "building_use_definitions",
    "green_building": "project_green_building",
    "dimensions": "project_dimensions",
    "metadata": "project_metadata",
}

# NL sector → building_use_group (synced via ontology.CLIENT_SECTOR_TO_BUG)
SECTOR_TO_BUILDING_USE: dict[str, str] = {
    "Residential": "BUG-RES",
    "Healthcare": "BUG-HLT",
    "Education": "BUG-EDU",
    "Commercial": "BUG-COM",
    "Retail": "BUG-RET",
    "Industrial": "BUG-IND",
}

# Client development_type labels → gold project_fields.development_type
DEVELOPMENT_TYPE_GOLD: dict[str, str] = {
    "NewBuild": "New",
    "New": "New",
    "Refurbishment": "Refurbishment",
    "Extension": "Extension",
}

# Procurement route (client) → contract_type on project_fields
PROCUREMENT_TO_CONTRACT_TYPE: dict[str, str] = {
    "Design and Build": "Design Build",
    "Design-Build": "Design Build",
    "Design Build": "Design Build",
}

# Logical filter field (intent) → SQL column reference
LOGICAL_FIELD_SQL: dict[str, str] = {
    "project_id": "pf.project_id",
    "value": "pf.project_value",
    "project_value": "pf.project_value",
    "currency": "pf.currency",
    "development_type": "dt.development_type",
    "contract_type": "pf.contract_type",
    "procurement_route": "pf.contract_type",
    "building_use_code": "pbu.building_use_code",
    "building_use_group": "bud.building_use_group",
    "sector": "bud.building_use_group",
    "ownership_type": "pf.ownership_type",
    "construction_start": "pf.construction_start_date",
    "construction_end": "pf.construction_end_date",
    "updated_at": "pf.last_modified_at",
    "project_heading": "pf.project_heading",
    "description": "pf.description",
    "planning_reference": "pf.project_heading",
    "city": "sa.postal_town",
    "postal_town": "sa.postal_town",
    "region": "sa.admin_level_1",
    "district": "sa.admin_level_2",
    "country": "sa.country",
    "latitude": "sa.latitude",
    "longitude": "sa.longitude",
    "contract_stage": "cs.key",
    "planning_stage": "pls.key",
    "project_status": "pst.key",
    "stage": "cs.key",
    "company_role": "pr.project_role_code",
    "company_name": "pr.company_name",
    "company_id": "pr.company_id",
    "visibility": "pf.visibility",
}

# Role labels (client) → gold project_role_code prefix patterns (role_definitions)
ROLE_TO_CODE_PREFIX: dict[str, str] = {
    "Client": "CLI",
    "MainContractor": "MCT",
    "Architect": "ARC",
    "ElectricalContractor": "MEC",
    "MechanicalContractor": "MMC",
    "Consultant": "CON",
    "Developer": "DEV",
    "ProjectManager": "PM",
    "PurchasingManager": "PUR",
}

# Excluded project_status keys (AC-5) — from project_statuses.json
DEFAULT_EXCLUDED_STATUS_KEYS = ("CAN", "HOL", "PND", "SFS")


@dataclass
class QualifiedTable:
    catalog: str
    schema: str
    name: str

    @property
    def fqn(self) -> str:
        return f"{self.catalog}.{self.schema}.{self.name}"


def catalog_schema_from_metadata(tables: dict[str, Any]) -> tuple[str, str]:
    for meta in tables.values():
        if meta.get("catalog") and meta.get("schema"):
            return meta["catalog"], meta["schema"]
    return "europe_prod_catalog", "mimir_model_gold"


def resolve_stage_filter(stage: str) -> tuple[str, str | list[str]]:
    """Return (intent_field, gold key or list of keys) for a client stage label."""
    from nlsearch.vocabulary.ontology import resolve_client_stage

    return resolve_client_stage(stage)


def resolve_sector_filter(sector: str) -> tuple[str, str]:
    """Return (field, value) — building_use_group code."""
    from nlsearch.vocabulary.ontology import resolve_sector_to_bug

    return "building_use_group", resolve_sector_to_bug(sector)


def sql_column(logical_field: str) -> str:
    """Map intent logical field → SQL expression (never pf-prefix FQN paths)."""
    if logical_field in LOGICAL_FIELD_SQL:
        return LOGICAL_FIELD_SQL[logical_field]

    low = logical_field.lower()
    if logical_field.startswith(("cs.", "pls.", "pst.", "sa.", "pf.", "dt.", "bud.", "pbu.")):
        return logical_field
    if "contract_stage" in low or "contract_stages" in low:
        return "cs.key"
    if "planning_stage" in low or "planning_stages" in low:
        return "pls.key"
    if "project_status" in low or "project_statuses" in low:
        return "pst.key"
    if "building_use_group" in low or "building_use_definitions" in low:
        return "bud.building_use_group"
    if "building_use_code" in low or "project_building_uses" in low:
        return "pbu.building_use_code"
    if "development_type" in low:
        return "dt.development_type"
    if "postal_town" in low or low in ("city", "town"):
        return "sa.postal_town"
    if "admin_level_1" in low or low == "region":
        return "sa.admin_level_1"

    return f"pf.{logical_field}"


def role_code_pattern(role: str) -> str:
    from nlsearch.vocabulary.ontology import resolve_role_pattern

    return resolve_role_pattern(role)
