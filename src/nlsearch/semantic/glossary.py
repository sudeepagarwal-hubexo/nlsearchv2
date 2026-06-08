"""Business glossary: map NL terms to Mimir gold-layer fields."""

from __future__ import annotations

from nlsearch.semantic.gold_layer import DEVELOPMENT_TYPE_GOLD, PROCUREMENT_TO_CONTRACT_TYPE


class BusinessGlossary:
    """Term → gold field mapping (ODT vocabulary + architecture doc)."""

    def __init__(self) -> None:
        self._terms: dict[str, str] = {
            "builder": "project_roles.company_name",
            "contractor": "project_roles.project_role_code",
            "cost": "project_fields.project_value",
            "budget": "project_fields.project_value",
            "gdv": "project_fields.project_value",
            "value": "project_fields.project_value",
            "byggherre": "project_roles:Client",
            "gc": "project_roles:MainContractor",
            "huvudentreprenör": "project_roles:MainContractor",
            "upphandling": "contract_stage:Tender",
            "tender": "contract_stage:Tender",
            "byggstart": "contract_stage:Main Contract",
            "planning": "planning_stage:Early Planning",
            "pm": "project_role_contacts:Project Manager",
            "client": "project_roles:Client",
            "architect": "project_roles:Architect",
            "patch": "site_address:territory_polygon",
            "near me": "site_address:geo",
            "hq": "geo:HQ",
            "sector": "project_fields.building_use_group",
            "residential": "building_use_group:BUG-RES",
            "hospital": "building_use_group:BUG-HEA",
            "school": "building_use_group:BUG-EDU",
            "office": "building_use_group:BUG-COM",
            "refurbishment": "project_fields.development_type:Refurbishment",
            "new build": "project_fields.development_type:New",
            "new-build": "project_fields.development_type:New",
            "design and build": "project_fields.contract_type:Design Build",
            "design-and-build": "project_fields.contract_type:Design Build",
        }

    def translate(self, phrase: str) -> dict[str, str]:
        low = phrase.lower()
        hits: dict[str, str] = {}
        for term, field in self._terms.items():
            if term in low:
                hits[term] = field
        return hits

    def expand_entity(self, text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        low = text.lower()
        if "villa" in low or "apartment" in low:
            result["building_use_code"] = "BU-23"
        if "skanska" in low:
            result["company_name"] = "Skanska"
        if "ncc" in low:
            result["company_name"] = "NCC"
        if "emaar" in low:
            result["company_name"] = "Emaar"
        for label, gold in DEVELOPMENT_TYPE_GOLD.items():
            if label.lower() in low:
                result["development_type"] = gold
        for label, gold in PROCUREMENT_TO_CONTRACT_TYPE.items():
            if label.lower() in low:
                result["contract_type"] = gold
        return result
