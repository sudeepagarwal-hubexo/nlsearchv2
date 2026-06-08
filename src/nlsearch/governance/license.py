"""Licensing scope hard post-filter (AC-6) — never NL-overridable."""

from __future__ import annotations

from nlsearch.config import get_settings
from nlsearch.models.intent import FilterPredicate, QueryIntent


class LicenseFilter:
    def __init__(self) -> None:
        settings = get_settings()
        self._licensed = {r.strip() for r in settings.licensed_regions.split(",") if r.strip()}

    def apply(self, intent: QueryIntent) -> QueryIntent:
        """Annotate intent with license notice; strip out-of-scope region filters from execution."""
        requested_regions: list[str] = []
        for f in intent.filters:
            if f.field in ("region", "city") and f.value:
                requested_regions.append(str(f.value))
            if f.field == "region" and f.values:
                requested_regions.extend(str(v) for v in f.values)

        out_of_scope = [r for r in requested_regions if r not in self._licensed]
        if out_of_scope:
            intent.license_notice = (
                f"{', '.join(out_of_scope)} outside your licensed area not shown; "
                "in-scope results only."
            )
            # Keep filter but flag — executor applies post-filter
            intent.session_patch["license_regions"] = list(self._licensed)
        return intent

    def is_region_licensed(self, region: str) -> bool:
        return region in self._licensed
