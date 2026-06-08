"""SQL generation for Mimir gold layer (project_fields hub + joins)."""

from __future__ import annotations

from nlsearch.models.intent import FilterOperator, QueryIntent, ResultType
from nlsearch.semantic.gold_layer import (
    DEFAULT_EXCLUDED_STATUS_KEYS,
    PROJECT_HUB,
    PROCUREMENT_TO_CONTRACT_TYPE,
    QualifiedTable,
    catalog_schema_from_metadata,
    resolve_sector_filter,
    resolve_stage_filter,
    role_code_pattern,
    sql_column,
)
from nlsearch.semantic.schema_store import SchemaStore


class SQLGenerator:
    def __init__(self, schema: SchemaStore | None = None) -> None:
        self._schema = schema or SchemaStore()
        cat, sch = catalog_schema_from_metadata(self._schema._tables)  # noqa: SLF001
        self._catalog = cat
        self._schema_name = sch

    def _fqn(self, table: str) -> str:
        return QualifiedTable(self._catalog, self._schema_name, table).fqn

    def generate(self, intent: QueryIntent, schema_context: str = "") -> str:
        if intent.result_type == ResultType.COMPANY:
            return self._company_sql(intent)
        if intent.result_type == ResultType.PERSON:
            return self._person_sql(intent)
        if intent.aggregation and intent.aggregation.kind == "heatmap":
            return self._heatmap_sql(intent)
        return self._project_sql(intent)

    def _base_project_from(self) -> str:
        pf = self._fqn(PROJECT_HUB)
        sa = self._fqn("site_address")
        cs = self._fqn("contract_stages")
        pls = self._fqn("planning_stages")
        pst = self._fqn("project_statuses")
        dt = self._fqn("development_types")
        pbu = self._fqn("project_building_uses")
        bud = self._fqn("building_use_definitions")
        return (
            f"FROM {pf} pf\n"
            f"LEFT JOIN {sa} sa ON sa.project_id = pf.project_id\n"
            f"LEFT JOIN {cs} cs ON cs.id = pf.contract_stage_id\n"
            f"LEFT JOIN {pls} pls ON pls.id = pf.planning_stage_id\n"
            f"LEFT JOIN {pst} pst ON pst.id = pf.project_status_id\n"
            f"LEFT JOIN {dt} dt ON dt.id = pf.development_type_id\n"
            f"LEFT JOIN {pbu} pbu ON pbu.project_id = pf.project_id AND pbu.is_primary = TRUE\n"
            f"LEFT JOIN {bud} bud ON bud.building_use_code = pbu.building_use_code"
        )

    def _project_sql(self, intent: QueryIntent) -> str:
        clauses: list[str] = []
        extra_joins: list[str] = []

        for f in intent.filters:
            if f.field == "_semantic":
                clauses.append(
                    f"(pf.description ILIKE '%{self._escape(str(f.value))}%' "
                    f"OR pf.project_heading ILIKE '%{self._escape(str(f.value))}%')"
                )
                continue
            if f.field == "stage_transition":
                extra_joins.append(self._stage_history_join())
                clauses.append(f"h.to_contract_stage = '{f.value}'")
                days = f.meta.get("window_days", 7)
                clauses.append(f"h.transition_at >= current_date() - INTERVAL {days} DAYS")
                continue

            sql_frag = self._filter_to_sql(f)
            if sql_frag:
                clauses.append(sql_frag)

        if intent.geo and intent.geo.kind == "near":
            anchor = intent.geo.anchor or "userLocation"
            r = intent.geo.radius_km or 25
            clauses.append(
                f"ST_DWithin(ST_Point(sa.longitude, sa.latitude), {anchor}, {r * 1000})"
            )
            for city in intent.geo.exclude_cities or []:
                clauses.append(f"sa.postal_town != '{self._escape(city)}'")

        # within_polygon (user patch) — no territory geometry in gold; region via filters
        license_regions = intent.session_patch.get("license_regions")
        if license_regions:
            regs = ", ".join(f"'{self._escape(r)}'" for r in license_regions)
            clauses.append(f"sa.admin_level_1 IN ({regs})")

        # Default visibility
        clauses.append("pf.visibility = 'visible'")

        where = " AND ".join(clauses) if clauses else "1=1"
        joins = "\n".join(extra_joins)
        sql = (
            f"SELECT pf.project_id, pf.project_heading, pf.project_value, pf.currency,\n"
            f"       dt.development_type, pf.contract_type, bud.building_use_group, pbu.building_use_code,\n"
            f"       pf.construction_start_date, pf.construction_end_date,\n"
            f"       sa.postal_town, sa.admin_level_1, sa.latitude, sa.longitude,\n"
            f"       cs.key AS contract_stage, pls.key AS planning_stage, pst.key AS project_status\n"
            f"{self._base_project_from()}\n"
            f"{joins}\n"
            f"WHERE {where}"
        )

        if intent.sort:
            order = ", ".join(
                f"{sql_column(s.field) if s.field in ('value', 'project_value') else sql_column(s.field)} {s.direction}"
                for s in intent.sort
            )
            sql += f"\nORDER BY {order}"

        if intent.limit:
            sql += f"\nLIMIT {intent.limit}"

        return sql.strip()

    def _filter_to_sql(self, f) -> str | None:
        field = f.field
        col = sql_column(field)

        if field in ("stage", "contract_stage", "planning_stage"):
            stage_col = "pls.key" if field == "planning_stage" else "cs.key"
            if f.operator == FilterOperator.IN and f.values:
                vals = ", ".join(f"'{self._escape(str(v))}'" for v in f.values)
                return f"{stage_col} IN ({vals})"
            if f.value:
                if field == "stage":
                    dim, keys = resolve_stage_filter(str(f.value))
                    stage_col = "pls.key" if dim == "planning_stage" else "cs.key"
                    if isinstance(keys, list):
                        vals = ", ".join(f"'{self._escape(k)}'" for k in keys)
                        return f"{stage_col} IN ({vals})"
                    return f"{stage_col} = '{self._escape(keys)}'"
                return f"{stage_col} = '{self._escape(str(f.value))}'"

        if field == "sector" and f.value:
            _, prefix = resolve_sector_filter(str(f.value))
            return f"bud.building_use_group LIKE '{self._escape(prefix)}%'"

        if field in ("procurement_route",) and f.value:
            ct = PROCUREMENT_TO_CONTRACT_TYPE.get(str(f.value), str(f.value))
            return f"pf.contract_type = '{self._escape(ct)}'"

        if field == "development_type" and f.value:
            return f"dt.development_type = '{self._escape(str(f.value))}'"

        if field == "company_role" and f.value:
            pattern = role_code_pattern(str(f.value))
            meta_name = f.meta.get("company_name")
            parts = [f"EXISTS (SELECT 1 FROM {self._fqn('project_roles')} pr "
                     f"WHERE pr.project_id = pf.project_id "
                     f"AND pr.project_role_code LIKE '{self._escape(pattern)}'"]
            if meta_name:
                parts[0] += f" AND pr.company_name ILIKE '%{self._escape(meta_name)}%'"
            parts[0] += ")"
            return parts[0]

        if field == "collaborated_with":
            return (
                f"EXISTS (SELECT 1 FROM {self._fqn('project_roles')} pr "
                f"WHERE pr.company_id = '{self._escape(str(f.value))}')"
            )

        if f.operator == FilterOperator.BETWEEN and f.values:
            return f"{col} BETWEEN '{f.values[0]}' AND '{f.values[1]}'"
        if f.operator == FilterOperator.IN and f.values:
            if field in ("sector", "building_use_group"):
                likes = " OR ".join(
                    f"bud.building_use_group LIKE '{self._escape(str(v))}%'"
                    for v in f.values
                )
                return f"({likes})"
            vals = ", ".join(f"'{self._escape(str(v))}'" for v in f.values)
            return f"{col} IN ({vals})"
        if f.operator == FilterOperator.NOT and f.values:
            if field in ("stage", "project_status"):
                vals = ", ".join(f"'{self._escape(str(v))}'" for v in f.values)
                return f"pst.key NOT IN ({vals})"
            vals = ", ".join(f"'{self._escape(str(v))}'" for v in f.values)
            return f"{col} NOT IN ({vals})"
        if f.operator == FilterOperator.LIKE:
            return f"{col} ILIKE '%{self._escape(str(f.value))}%'"
        if f.operator == FilterOperator.GT:
            return f"{col} > {f.value}"
        if f.operator == FilterOperator.LT:
            return f"{col} < '{self._escape(str(f.value))}'"
        if f.operator == FilterOperator.GTE:
            return f"{col} >= '{self._escape(str(f.value))}'"
        if f.operator == FilterOperator.EQ:
            if field == "building_use_group":
                return f"bud.building_use_group LIKE '{self._escape(str(f.value))}%'"
            return f"{col} = '{self._escape(str(f.value))}'"
        if f.operator == FilterOperator.NE:
            return f"{col} != '{self._escape(str(f.value))}'"
        return None

    def _heatmap_sql(self, intent: QueryIntent) -> str:
        clauses = []
        for f in intent.filters:
            frag = self._filter_to_sql(f)
            if frag:
                clauses.append(frag)
        clauses.append("pf.visibility = 'visible'")
        where = " AND ".join(clauses) if clauses else "1=1"
        weight = intent.aggregation.field if intent.aggregation else "project_value"
        col = sql_column(weight)
        return (
            f"SELECT sa.admin_level_1 AS region, SUM({col}) AS weight\n"
            f"{self._base_project_from()}\n"
            f"WHERE {where}\n"
            f"GROUP BY sa.admin_level_1"
        ).strip()

    def _company_sql(self, intent: QueryIntent) -> str:
        pr = self._fqn("project_roles")
        clauses = ["1=1"]
        for f in intent.filters:
            if f.field == "company_role" and f.value:
                clauses.append(f"pr.project_role_code LIKE '{self._escape(role_code_pattern(str(f.value)))}'")
            elif f.field == "region" and f.value:
                clauses.append(
                    f"EXISTS (SELECT 1 FROM {self._fqn('site_address')} sa "
                    f"JOIN {self._fqn(PROJECT_HUB)} pf ON pf.project_id = sa.project_id "
                    f"WHERE pr.project_id = pf.project_id AND sa.admin_level_1 = '{self._escape(str(f.value))}')"
                )
        where = " AND ".join(clauses)
        return (
            f"SELECT DISTINCT pr.company_id, pr.company_name, pr.project_role_code\n"
            f"FROM {pr} pr\n"
            f"WHERE {where}"
        ).strip()

    def _person_sql(self, intent: QueryIntent) -> str:
        prc = self._fqn("project_role_contacts")
        pr = self._fqn("project_roles")
        clauses = ["1=1"]
        for f in intent.filters:
            if f.field == "job_title" and f.value:
                clauses.append(f"prc.person_role_type ILIKE '%{self._escape(str(f.value))}%'")
            elif f.field == "company" and f.value:
                clauses.append(f"pr.company_name ILIKE '%{self._escape(str(f.value))}%'")
            elif f.field == "workplace.region" and f.value:
                clauses.append(f"sa.admin_level_1 = '{self._escape(str(f.value))}'")
        where = " AND ".join(clauses)
        sa = self._fqn("site_address")
        pf = self._fqn(PROJECT_HUB)
        return (
            f"SELECT DISTINCT prc.contact_id, prc.person_role_type, pr.company_name\n"
            f"FROM {prc} prc\n"
            f"JOIN {pr} pr ON pr.assignment_id = prc.assignment_id\n"
            f"LEFT JOIN {pf} pf ON pf.project_id = pr.project_id\n"
            f"LEFT JOIN {sa} sa ON sa.project_id = pf.project_id\n"
            f"WHERE {where}"
        ).strip()

    def _stage_history_join(self) -> str:
        return f"INNER JOIN {self._fqn('project_metadata')} h ON h.project_id = pf.project_id"

    @staticmethod
    def _escape(val: str) -> str:
        return val.replace("'", "''")
