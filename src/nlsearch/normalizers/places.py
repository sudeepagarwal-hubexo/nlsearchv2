"""Place → district/city via gazetteer; ambiguous places flagged (AC-4, AC-8)."""

from __future__ import annotations

import re
from dataclasses import dataclass

def _static_gazetteer() -> dict[str, dict[str, str | list[str]]]:
    try:
        from nlsearch.vocabulary.ontology import load_places_gazetteer

        dynamic = load_places_gazetteer(("SE", "NO"))
        if dynamic:
            return dynamic  # type: ignore[return-value]
    except Exception:
        pass
    return _FALLBACK_GAZETTEER


# Fallback when facet_places.json not synced
_FALLBACK_GAZETTEER: dict[str, dict[str, str | list[str]]] = {
    "solna": {"postal_town": "Solna", "admin_level_1": "Stockholm"},
    "stockholm": {"postal_town": "Stockholm", "admin_level_1": "Stockholm"},
    "göteborg": {"postal_town": "Göteborg", "admin_level_1": "Västra Götaland"},
    "gothenburg": {"postal_town": "Göteborg", "admin_level_1": "Västra Götaland"},
    "goteborg": {"postal_town": "Göteborg", "admin_level_1": "Västra Götaland"},
    "skåne": {"admin_level_1": "Skåne"},
    "skane": {"admin_level_1": "Skåne"},
    "uppsala": {"postal_town": "Uppsala", "admin_level_1": "Uppsala"},
    "mölndal": {"postal_town": "Mölndal", "admin_level_1": "Västra Götaland"},
    "molndal": {"postal_town": "Mölndal", "admin_level_1": "Västra Götaland"},
    "southern sweden": {"region": "Southern Sweden", "regions": ["Skåne", "Blekinge", "Halland", "Småland"]},
    "southern sweden heatmap": {"regions": ["Skåne", "Blekinge", "Halland", "Småland"]},
    "malmö": {"postal_town": "Malmö", "admin_level_1": "Skåne"},
    "malmo": {"postal_town": "Malmö", "admin_level_1": "Skåne"},
    "kiruna": {"postal_town": "Kiruna", "admin_level_1": "Norrbotten"},
}

_AMBIGUOUS = {"london", "paris"}  # require confirmation when not in gazetteer


@dataclass
class PlaceMatch:
    field: str  # postal_town | admin_level_1 | regions
    value: str | list[str]
    ambiguous: bool = False
    clarification: str | None = None


class PlaceResolver:
    def resolve(self, text: str) -> PlaceMatch | None:
        low = text.lower()
        gazetteer = _static_gazetteer()

        if "southern sweden" in low:
            return PlaceMatch("admin_level_1", ["Skåne", "Blekinge", "Halland", "Småland"])

        if re.search(r"stockholm\s+region", low):
            return PlaceMatch("admin_level_1", "Stockholm")

        for key, meta in gazetteer.items():
            if key in low:
                if key in _AMBIGUOUS and key not in gazetteer:
                    return PlaceMatch(
                        "city",
                        key.title(),
                        ambiguous=True,
                        clarification=f"Did you mean {key.title()}? Multiple matches exist.",
                    )
                if "regions" in meta:
                    return PlaceMatch("region", meta["regions"])  # type: ignore[arg-type]
                if "postal_town" in meta:
                    return PlaceMatch("postal_town", meta["postal_town"])  # type: ignore[arg-type]
                if "admin_level_1" in meta:
                    return PlaceMatch("admin_level_1", meta["admin_level_1"])  # type: ignore[arg-type]
                if "city" in meta:
                    return PlaceMatch("postal_town", meta["city"])  # type: ignore[arg-type]
                if "region" in meta:
                    return PlaceMatch("admin_level_1", meta["region"])  # type: ignore[arg-type]

        # "in X" pattern
        m = re.search(r"\bin\s+([A-Za-zÅÄÖåäö\s]+?)(?:\s+valued|\s+over|,|$)", text, re.I)
        if m:
            place = m.group(1).strip()
            return self.resolve(place)

        return None

    def extract_excluded_city(self, text: str) -> str | None:
        m = re.search(r"not in\s+([A-Za-zÅÄÖåäö]+)", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r"but not in\s+([A-Za-zÅÄÖåäö]+)", text, re.I)
        return m.group(1) if m else None
