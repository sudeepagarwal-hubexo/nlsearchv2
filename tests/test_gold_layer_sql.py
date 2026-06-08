"""Gold-layer SQL generation against schema_metadata.json."""

from __future__ import annotations

from pathlib import Path

import pytest

from nlsearch.models.intent import FilterOperator, FilterPredicate, QueryIntent, QueryMode, ResultType
from nlsearch.semantic.schema_store import SchemaStore
from nlsearch.sql.generator import SQLGenerator

METADATA = Path(__file__).parents[1] / "src" / "nlsearch" / "semantic" / "data" / "schema_metadata.json"


@pytest.fixture
def generator() -> SQLGenerator:
    return SQLGenerator(SchemaStore(metadata_path=METADATA))


def test_project_sql_uses_gold_hub(generator: SQLGenerator) -> None:
    intent = QueryIntent(
        result_type=ResultType.PROJECT,
        mode=QueryMode.STRUCTURED,
        filters=[
            FilterPredicate(field="postal_town", operator=FilterOperator.EQ, value="Solna"),
            FilterPredicate(field="project_value", operator=FilterOperator.GT, value=100_000_000),
            FilterPredicate(field="contract_stage", operator=FilterOperator.EQ, value="Tender"),
        ],
    )
    sql = generator.generate(intent)
    assert "project_fields" in sql
    assert "site_address" in sql
    assert "pf.project_value" in sql
    assert "sa.postal_town" in sql
    assert "cs.key" in sql
    assert "europe_prod_catalog" in sql or "mimir_model_gold" in sql


def test_development_type_new(generator: SQLGenerator) -> None:
    intent = QueryIntent(
        result_type=ResultType.PROJECT,
        mode=QueryMode.STRUCTURED,
        filters=[
            FilterPredicate(field="development_type", operator=FilterOperator.EQ, value="New"),
            FilterPredicate(field="building_use_group", operator=FilterOperator.EQ, value="BUG-RES"),
        ],
    )
    sql = generator.generate(intent)
    assert "development_types" in sql
    assert "dt.development_type = 'New'" in sql
    assert "pf.development_type_id" in sql
    assert "project_building_uses" in sql
    assert "building_use_definitions" in sql
    assert "pbu.is_primary = TRUE" in sql
    assert "bud.building_use_code = pbu.building_use_code" in sql
    assert "bud.building_use_group LIKE 'BUG-RES%'" in sql
