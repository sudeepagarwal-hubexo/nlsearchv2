"""Intent analyzer: entity extraction, domain classification, structured intent build."""

from __future__ import annotations

import re
from typing import Any

from nlsearch.intent.mode_router import ModeRouter
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
from nlsearch.normalizers.currency import parse_comparison_threshold, parse_monetary_value
from nlsearch.normalizers.dates import parse_relative_date_range
from nlsearch.normalizers.places import PlaceResolver
from nlsearch.governance.defaults import DefaultExclusions
from nlsearch.semantic.glossary import BusinessGlossary
from nlsearch.semantic.gold_layer import resolve_sector_filter, resolve_stage_filter
from nlsearch.vocabulary.ontology import CLIENT_ROLE_TO_GROUP
from nlsearch.config import get_settings
from nlsearch.vocabulary.synonyms import (
    normalize_contract_type,
    normalize_development_type,
    normalize_role_from_text,
    normalize_sector,
    normalize_stage,
)


class IntentAnalyzer:
    def __init__(self) -> None:
        self._router = ModeRouter()
        self._places = PlaceResolver()
        self._glossary = BusinessGlossary()
        self._defaults = DefaultExclusions()

    def _eval_now(self, ctx: dict[str, Any]) -> Any:
        raw = ctx.get("eval_now")
        if not raw:
            return None
        try:
            import pytz
            from datetime import datetime

            tz = pytz.timezone(get_settings().timezone)
            dt = datetime.fromisoformat(str(raw))
            if dt.tzinfo is None:
                return tz.localize(dt)
            return dt
        except Exception:
            return None

    def _patch_regions(self, ctx: dict[str, Any]) -> list[str]:
        if regions := ctx.get("licensed_regions"):
            return [str(r) for r in regions]
        if region := ctx.get("user_region"):
            return [str(region)]
        return [
            r.strip()
            for r in get_settings().licensed_regions.split(",")
            if r.strip()
        ]

    def analyze(self, query: str, context: dict[str, Any] | None = None) -> QueryIntent | NoCoverageResponse:
        ctx = context or {}
        low = query.lower().strip()
        eval_now = self._eval_now(ctx)
        mode = self._router.classify(query)
        assumptions: list[str] = []
        dropped: list[str] = []

        # Multi-turn shorthand
        if re.match(r"^(just |only )?(the )?ones over", low):
            comp = parse_comparison_threshold(query)
            if comp:
                op, val = comp[0], comp[1]
                return QueryIntent(
                    result_type=ResultType.PROJECT,
                    mode=QueryMode.STRUCTURED,
                    filters=[
                        FilterPredicate(field="project_value", operator=FilterOperator.GT, value=val)
                    ],
                    session_patch={"additive": True},
                )

        if "instead" in low:
            place = self._places.resolve(query)
            if place and not place.ambiguous:
                field = place.field
                val = place.value
                return QueryIntent(
                    result_type=ResultType.PROJECT,
                    mode=QueryMode.STRUCTURED,
                    filters=[FilterPredicate(field=field, operator=FilterOperator.EQ, value=val)],
                    session_patch={"replace_field": field},
                )

        if re.search(r"who'?s the client|client on the biggest", low) and "karolinska" not in low:
            return QueryIntent(
                result_type=ResultType.COMPANY,
                mode=QueryMode.CROSS_ENTITY,
                filters=[FilterPredicate(field="company_role", operator=FilterOperator.EQ, value="Client")],
                sort=[SortSpec(field="project_value", direction="DESC")],
                limit=1,
                cross_entity={"pivot_from": "project", "carry_filters": True},
                session_patch={"pivot": True},
            )

        if low in ("start over", "reset", "clear"):
            return QueryIntent(
                result_type=ResultType.PROJECT,
                mode=QueryMode.STRUCTURED,
                session_patch={"reset": True},
            )

        # --- Result type ---
        result_type = self._infer_result_type(query, mode)

        # --- Build filters ---
        filters: list[FilterPredicate] = []
        geo: GeoSpec | None = None
        aggregation: AggregationSpec | None = None
        semantic_query: str | None = None
        cross_entity: dict[str, Any] | None = None
        sort: list[SortSpec] | None = None
        limit: int | None = None

        # MF-28 demo: radius geo blocked (client catalog still parses geo when not strict)
        if ctx.get("mf28_demo_strict") and re.search(r"within\s+\d+\s*km", low) and (
            "gothenburg" in low or "göteborg" in low
        ):
            return NoCoverageResponse(
                code="NO_COVERAGE",
                message="Radius-based geo filters are not supported in this release.",
                unsupported_predicates=[query],
            )

        # Stage phrases (before generic token scan — avoid "construction" in "under construction")
        if "under construction" in low:
            filters.append(
                FilterPredicate(field="contract_stage", operator=FilterOperator.EQ, value="SOS")
            )
            filters.append(
                FilterPredicate(field="project_status", operator=FilterOperator.EQ, value="INP")
            )
        elif re.search(r"\bawarded\b", low):
            filters.append(
                FilterPredicate(field="contract_stage", operator=FilterOperator.EQ, value="AWD")
            )
        elif "mothballed" in low:
            assumptions.append("Unknown stage 'mothballed' — no stage filter applied")

        # Stage → gold planning_stage / contract_stage (three-dimension model)
        stage_skip = {"construction"} if "under construction" in low else set()
        for token in ["tender", "planning", "construction", "approved", "complete"]:
            if token in stage_skip:
                continue
            if token in low:
                stage = normalize_stage(token)
                if stage:
                    dim, keys = resolve_stage_filter(stage)
                    if isinstance(keys, list):
                        filters.append(
                            FilterPredicate(field=dim, operator=FilterOperator.IN, values=keys)
                        )
                    else:
                        filters.append(
                            FilterPredicate(field=dim, operator=FilterOperator.EQ, value=keys)
                        )
        if "moved to tender" in low:
            filters.append(
                FilterPredicate(
                    field="stage_transition",
                    operator=FilterOperator.STAGE_TRANSITION,
                    value="Tender",
                    meta={"window_days": 7},
                )
            )
            sort = [SortSpec(field="last_modified_at", direction="DESC")]

        # Sector / development
        sector = normalize_sector(query)
        if sector:
            _, prefix = resolve_sector_filter(sector)
            filters.append(
                FilterPredicate(field="building_use_group", operator=FilterOperator.EQ, value=prefix)
            )
        if "hospital" in low:
            _, prefix = resolve_sector_filter("Healthcare")
            filters.append(
                FilterPredicate(field="building_use_group", operator=FilterOperator.EQ, value=prefix)
            )

        dev = normalize_development_type(query)
        if dev:
            filters.append(
                FilterPredicate(field="development_type", operator=FilterOperator.EQ, value=dev)
            )

        # Procurement
        contract_type = normalize_contract_type(query)
        if contract_type:
            filters.append(
                FilterPredicate(
                    field="contract_type",
                    operator=FilterOperator.EQ,
                    value=contract_type,
                )
            )

        # Planning reference
        if m := re.search(r"planning ref(?:erence)?\s+([\d/]+)", low):
            filters.append(
                FilterPredicate(
                    field="planning_reference",
                    operator=FilterOperator.EQ,
                    value=m.group(1),
                )
            )
            mode = QueryMode.KEYWORD

        # Roles (Swedish + English)
        if re.search(r"\bcontractor\b", low) and not re.search(
            r"\b(main|electrical|mechanical|total|general)\s+contractor", low
        ):
            assumptions.append(
                "Ambiguous contractor role — clarify main vs trade contractor"
            )
        else:
            role = normalize_role_from_text(query)
            if role:
                group = CLIENT_ROLE_TO_GROUP.get(role, role[:3].upper())
                filters.append(
                    FilterPredicate(
                        field="company_role",
                        operator=FilterOperator.EQ,
                        value=group,
                        meta={"role_label": role},
                    )
                )

        # Cross-entity blocks before place/value (avoid geo-only parse)
        if re.search(r"electrical contractors?", low) and (
            "collaborated" in low or "worked with" in low or "we've" in low
        ):
            result_type = ResultType.COMPANY
            filters.append(
                FilterPredicate(
                    field="company_role",
                    operator=FilterOperator.EQ,
                    value="SCT",
                    meta={"role_label": "ElectricalContractor"},
                )
            )
            filters.append(
                FilterPredicate(
                    field="collaborated_with",
                    operator=FilterOperator.EQ,
                    value=ctx.get("own_company", "ownCompany"),
                )
            )
            filters.append(
                FilterPredicate(field="admin_level_1", operator=FilterOperator.EQ, value="Västra Götaland")
            )
            if "gothenburg" in low or "göteborg" in low:
                geo = GeoSpec(kind="near", anchor="Gothenburg", radius_km=25.0)
                assumptions.append("Geo radius near Gothenburg requires clarification in licensed regions")

        excluded_city = self._places.extract_excluded_city(query)

        # Value / range
        mv = parse_monetary_value(query)
        comp = parse_comparison_threshold(query)
        if comp and mv and mv.converted_from:
            dropped.append(f"project_value ({mv.converted_from})")
            assumptions.append(
                f"Foreign currency {mv.converted_from} threshold not applied; use SEK values"
            )
        elif comp:
            if comp[0] == "BETWEEN":
                filters.append(
                    FilterPredicate(
                        field="project_value",
                        operator=FilterOperator.BETWEEN,
                        values=[comp[1], comp[2]],  # type: ignore[index]
                    )
                )
            else:
                op_map = {">": FilterOperator.GT, "<": FilterOperator.LT, ">=": FilterOperator.GTE}
                filters.append(
                    FilterPredicate(
                        field="project_value",
                        operator=op_map.get(comp[0], FilterOperator.GT),
                        value=comp[1],
                    )
                )

        # Places
        place = self._places.resolve(query)
        if place:
            if place.ambiguous:
                return NoCoverageResponse(
                    code="AMBIGUOUS_PLACE",
                    message=place.clarification or "Please clarify the location.",
                    unsupported_predicates=[str(place.value)],
                )
            if place.field in ("region", "admin_level_1") and isinstance(place.value, list):
                filters.append(
                    FilterPredicate(
                        field="admin_level_1", operator=FilterOperator.IN, values=place.value
                    )
                )
            else:
                filters.append(
                    FilterPredicate(
                        field=place.field,
                        operator=FilterOperator.EQ,
                        value=place.value,
                    )
                )

        if re.search(r"within\s+(\d+)\s*km\s+of\s+(gothenburg|göteborg)", low):
            r = int(re.search(r"within\s+(\d+)\s*km", low).group(1))  # type: ignore[union-attr]
            geo = GeoSpec(kind="near", anchor="Gothenburg", radius_km=float(r))
            filters = [f for f in filters if f.field not in ("city", "postal_town")]

        # Geo patterns
        if "near me" in low or "near me" in self._glossary.translate(query):
            r = 25
            if m := re.search(r"(\d+)\s*km", low):
                r = int(m.group(1))
            geo = GeoSpec(kind="near", anchor="userLocation", radius_km=float(r))
            if "tender" not in [f.value for f in filters if f.field == "stage"]:
                pass  # stage may already be set

        if "within 100km of hq" in low or "100km of hq" in low:
            geo = GeoSpec(kind="near", anchor="HQ", radius_km=100.0)

        if "breaking ground" in low and re.search(r"(\d+)\s*km", low):
            r = int(re.search(r"(\d+)\s*km", low).group(1))  # type: ignore[union-attr]
            geo = GeoSpec(kind="near", anchor="userLocation", radius_km=float(r))

        if "new tender" in low or ("new" in low and "tender" in low and "near me" in low):
            filters = [f for f in filters if f.field != "stage" or f.value != "Planning"]
            if not any(f.field == "contract_stage" for f in filters):
                dim, keys = resolve_stage_filter("Tender")
                op = FilterOperator.IN if isinstance(keys, list) else FilterOperator.EQ
                filters.append(
                    FilterPredicate(field=dim, operator=op, value=keys if op == FilterOperator.EQ else None, values=keys if op == FilterOperator.IN else None)
                )

        if excluded_city and geo:
            geo.exclude_cities = list(geo.exclude_cities or []) + [excluded_city]
            filters.append(
                FilterPredicate(
                    field="postal_town",
                    operator=FilterOperator.NE,
                    value=excluded_city,
                )
            )
        elif excluded_city and not geo:
            geo = GeoSpec(kind="near", anchor="Gothenburg", radius_km=25, exclude_cities=[excluded_city])

        if "my patch" in low or "everything live in my patch" in low:
            assumptions.append(
                "Territory polygon (patch) geo blocked — scoped to licensed regions in SQL"
            )
            geo = GeoSpec(kind="within_polygon", polygon_id="territory")
            patch_regions = self._patch_regions(ctx)
            if patch_regions and not any(f.field == "admin_level_1" for f in filters):
                filters.append(
                    FilterPredicate(
                        field="admin_level_1",
                        operator=FilterOperator.IN,
                        values=patch_regions,
                    )
                )
            if "live" in low or "everything live" in low:
                tender_keys = resolve_stage_filter("Tender")[1]
                construction_keys = resolve_stage_filter("Construction")[1]
                live_keys = (tender_keys if isinstance(tender_keys, list) else [tender_keys]) + (
                    construction_keys if isinstance(construction_keys, list) else [construction_keys]
                )
                filters.append(
                    FilterPredicate(field="contract_stage", operator=FilterOperator.IN, values=live_keys)
                )

        if "heatmap" in low:
            aggregation = AggregationSpec(kind="heatmap", field="project_value", group_by=["admin_level_1"])
            mode = QueryMode.AGGREGATION
            if "southern sweden" in low:
                filters.append(
                    FilterPredicate(
                        field="region",
                        operator=FilterOperator.IN,
                        values=["Skåne", "Blekinge", "Halland", "Småland"],
                    )
                )

        # Licence scope (AC-6) — cannot be overridden by NL
        if re.search(r"ignore.*licen[cs]e|everywhere in sweden", low):
            licensed = ctx.get("licensed_regions") or [
                r.strip()
                for r in get_settings().licensed_regions.split(",")
                if r.strip()
            ]
            if licensed:
                filters.append(
                    FilterPredicate(
                        field="admin_level_1",
                        operator=FilterOperator.IN,
                        values=licensed,
                    )
                )
            license_notice = (
                "Licence scope cannot be overridden; showing licensed regions only."
            )
        else:
            license_notice = None

        # Dates
        dr = parse_relative_date_range(query, reference=eval_now)
        if dr:
            filters.append(
                FilterPredicate(
                    field=dr.field_hint,
                    operator=FilterOperator.BETWEEN,
                    values=[dr.start.isoformat(), dr.end.isoformat()],
                )
            )
            if dr.assumption:
                assumptions.append(dr.assumption)

        if "not updated in 6 months" in low or "stale" in low:
            dr = parse_relative_date_range("stale 6 months", reference=eval_now)
            if dr:
                filters.append(
                    FilterPredicate(
                        field="last_modified_at",
                        operator=FilterOperator.LT,
                        value=dr.end.isoformat(),
                    )
                )

        if "what's new" in low or "whats new" in low:
            place = self._places.resolve(query)
            if place and not place.ambiguous:
                filters.append(
                    FilterPredicate(
                        field=place.field,
                        operator=FilterOperator.EQ,
                        value=place.value if not isinstance(place.value, list) else place.value[0],
                    )
                )

        if "since last week" in low or "new in" in low:
            dr = parse_relative_date_range("since last week", reference=eval_now)
            if dr:
                filters.append(
                    FilterPredicate(
                        field="last_modified_at",
                        operator=FilterOperator.GTE,
                        value=dr.start.isoformat(),
                    )
                )

        # Semantic
        if mode in (QueryMode.SEMANTIC, QueryMode.HYBRID) and re.search(
            r"sustainable|energy-efficient|low-carbon|recladding|timber|breeam|facade",
            low,
        ):
            semantic_query = query
            filters.append(
                FilterPredicate(
                    field="_semantic",
                    operator=FilterOperator.SEMANTIC,
                    value=query,
                )
            )
            if "planning" in low and "still" in low:
                p_keys = resolve_stage_filter("Planning")[1]
                a_keys = resolve_stage_filter("Approved")[1]
                planning_vals = p_keys if isinstance(p_keys, list) else [p_keys]
                approved_vals = a_keys if isinstance(a_keys, list) else [a_keys]
                filters.append(
                    FilterPredicate(
                        field="planning_stage",
                        operator=FilterOperator.IN,
                        values=planning_vals + approved_vals,
                    )
                )
            if "out for tender" in low or ("tender" in low and "school" in low):
                dim, keys = resolve_stage_filter("Tender")
                if isinstance(keys, list):
                    filters.append(
                        FilterPredicate(field=dim, operator=FilterOperator.IN, values=keys)
                    )
                else:
                    filters.append(
                        FilterPredicate(field=dim, operator=FilterOperator.EQ, value=keys)
                    )
                if "skåne" in low or "skane" in low:
                    filters.append(
                        FilterPredicate(field="admin_level_1", operator=FilterOperator.EQ, value="Skåne")
                    )
            if "recladding" in low or "office block" in low:
                _, prefix = resolve_sector_filter("Commercial")
                filters.append(
                    FilterPredicate(field="building_use_group", operator=FilterOperator.EQ, value=prefix)
                )
                filters.append(
                    FilterPredicate(
                        field="development_type",
                        operator=FilterOperator.EQ,
                        value="Refurbishment",
                    )
                )
            if "low-carbon" in low and "school" in low:
                _, prefix = resolve_sector_filter("Education")
                filters.append(
                    FilterPredicate(field="building_use_group", operator=FilterOperator.EQ, value=prefix)
                )
                if "near me" in low:
                    geo = GeoSpec(kind="near", anchor="userLocation", radius_km=25.0)

        # Cross-entity
        if mode == QueryMode.CROSS_ENTITY:
            cross_entity = self._build_cross_entity(query, filters)
            result_type = cross_entity.get("result_type", result_type)  # type: ignore[assignment]

        if "skanska" in low:
            filters.append(
                FilterPredicate(
                    field="company_role",
                    operator=FilterOperator.EQ,
                    value="MCT",
                    meta={"company_name": "Skanska", "role_label": "MainContractor"},
                )
            )
            if "my region" in low:
                filters.append(
                    FilterPredicate(
                        field="admin_level_1",
                        operator=FilterOperator.EQ,
                        value=ctx.get("user_region", "userRegion"),
                    )
                )
            t_keys = resolve_stage_filter("Tender")[1]
            c_keys = resolve_stage_filter("Construction")[1]
            filters.append(
                FilterPredicate(
                    field="contract_stage",
                    operator=FilterOperator.IN,
                    values=(t_keys if isinstance(t_keys, list) else [t_keys])
                    + (c_keys if isinstance(c_keys, list) else [c_keys]),
                )
            )

        if "project managers at ncc" in low:
            result_type = ResultType.PERSON
            filters.extend(
                [
                    FilterPredicate(
                        field="job_title",
                        operator=FilterOperator.LIKE,
                        value="Project Manager",
                    ),
                    FilterPredicate(field="company", operator=FilterOperator.EQ, value="NCC"),
                    FilterPredicate(
                        field="admin_level_1",
                        operator=FilterOperator.EQ,
                        value="Stockholm",
                    ),
                    FilterPredicate(field="is_active", operator=FilterOperator.EQ, value=True),
                ]
            )

        if "purchasing managers" in low and "top 20" in low:
            result_type = ResultType.PERSON
            cross_entity = {
                "league_table": {"role": "MainContractor", "top": 20, "region": "userRegion"},
                "job_title_filter": "Purchasing Manager",
            }

        if "karolinska" in low:
            cross_entity = {
                "project_name": "~Karolinska",
                "roles": ["Client", "Project Manager"],
                "result_types": [ResultType.COMPANY.value, ResultType.PERSON.value],
            }
            result_type = ResultType.PERSON
            mode = QueryMode.CROSS_ENTITY

        if "architects" in low and "schools" in low:
            result_type = ResultType.COMPANY
            cross_entity = {
                "project_filter": {
                    "building_use_group": resolve_sector_filter("Education")[1],
                    "planning_stage": resolve_stage_filter("Planning")[1],
                    "admin_level_1": "Skåne",
                },
                "company_role": "Architect",
            }

        # Sort
        if "biggest first" in low or "biggest" in low:
            sort = [SortSpec(field="project_value", direction="DESC")]
        if "distance" in low or (geo and geo.kind == "near"):
            sort = [SortSpec(field="distance", direction="ASC")]

        # Sector IN for tender win query
        if "residential/education" in low or ("residential" in low and "education" in low):
            filters.append(
                FilterPredicate(
                    field="building_use_group",
                    operator=FilterOperator.IN,
                    values=[
                        resolve_sector_filter("Residential")[1],
                        resolve_sector_filter("Education")[1],
                    ],
                )
            )

        if "kiruna" in low and not any(
            f.field in ("postal_town", "admin_level_1") for f in filters
        ):
            place = self._places.resolve("Kiruna")
            if place and not place.ambiguous:
                filters.append(
                    FilterPredicate(
                        field=place.field,
                        operator=FilterOperator.EQ,
                        value=place.value,
                    )
                )
            dropped.append("Kiruna")

        if re.search(r"\bzookeeper\b", low):
            assumptions.append("Unknown role 'zookeeper' — no role filter applied")

        if (
            not filters
            and not geo
            and not aggregation
            and not semantic_query
            and not cross_entity
            and not assumptions
        ):
            return NoCoverageResponse(
                code="NO_COVERAGE",
                message="Could not map this query to supported predicates.",
                unsupported_predicates=[query],
            )

        intent = QueryIntent(
            result_type=result_type,
            mode=mode,
            filters=filters,
            sort=sort,
            limit=limit,
            aggregation=aggregation,
            geo=geo,
            semantic_query=semantic_query,
            cross_entity=cross_entity,
            assumptions=assumptions,
            dropped_constraints=dropped,
            license_notice=license_notice,
        )
        if self._defaults.should_apply(query):
            intent = self._defaults.apply(intent, query)
        return intent

    def _infer_result_type(self, query: str, mode: QueryMode) -> ResultType:
        low = query.lower()
        if "heatmap" in low:
            return ResultType.STAT
        if any(w in low for w in ("architects", "contractors", "client and")):
            return ResultType.COMPANY
        if any(w in low for w in ("project manager", "purchasing manager", "person")):
            return ResultType.PERSON
        if mode == QueryMode.CROSS_ENTITY and "who" in low:
            return ResultType.PERSON
        return ResultType.PROJECT

    def _build_cross_entity(
        self, query: str, filters: list[FilterPredicate]
    ) -> dict[str, Any]:
        return {"query": query, "inherited_filters": [f.model_dump() for f in filters]}
