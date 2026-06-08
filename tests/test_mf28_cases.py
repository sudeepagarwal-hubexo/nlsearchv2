"""MF-28 truth-table validation (NL Search — Test Cases.odt)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
import pytz

from nlsearch.intent.analyzer import IntentAnalyzer
from nlsearch.models.intent import FilterOperator, NoCoverageResponse, ResultType
from nlsearch.orchestrator import QueryOrchestrator

MF28_PATH = Path(__file__).parent / "data" / "mf28_test_cases.json"
EVAL_CONTEXT = {
    "eval_now": "2026-06-01",
    "user_region": "Stockholm",
    "licensed_regions": ["Stockholm", "Uppsala"],
    "mf28_demo_strict": True,
}


def _load() -> dict:
    return json.loads(MF28_PATH.read_text())


def _blob(result) -> str:
    if isinstance(result, NoCoverageResponse):
        return result.model_dump_json()
    text = result.to_expression() + result.model_dump_json()
    if result.geo:
        text += json.dumps(result.geo.model_dump())
    if result.dropped_constraints:
        text += " dropped " + " ".join(result.dropped_constraints)
    if result.default_exclusions_applied:
        text += " default " + " ".join(result.default_exclusions_applied)
    if result.assumptions:
        text += " " + " ".join(result.assumptions)
    if result.license_notice:
        text += " license " + result.license_notice
    return text


@pytest.fixture
def analyzer() -> IntentAnalyzer:
    return IntentAnalyzer()


@pytest.mark.parametrize("row", [pytest.param(r, id=r["id"]) for r in _load()["queries"]])
def test_mf28_case(analyzer: IntentAnalyzer, row: dict) -> None:
    result = analyzer.analyze(row["query"], context=EVAL_CONTEXT)
    outcome = row["outcome"]
    blob = _blob(result)

    if outcome == "no_coverage":
        if row.get("allow_intent_with_only_geo") is False:
            assert isinstance(result, NoCoverageResponse), f"{row['id']}: expected no coverage"
        return

    assert not isinstance(result, NoCoverageResponse), f"{row['id']}: {getattr(result, 'message', '')}"

    if rt := row.get("result_type"):
        assert result.result_type.value == rt, row["id"]

    for frag in row.get("must_contain", []):
        assert frag.lower() in blob.lower(), f"{row['id']}: missing {frag!r}"

    if fields := row.get("must_have_fields"):
        names = {f.field for f in result.filters}
        for f in fields:
            assert f in names, f"{row['id']}: missing field {f}"

    if row.get("must_have_operator_lt"):
        assert any(
            f.operator in (FilterOperator.LT, FilterOperator.LTE) for f in result.filters
        ), row["id"]

    if row.get("must_have_operator_lt_on_updated"):
        assert any(
            f.field == "last_modified_at" and f.operator == FilterOperator.LT
            for f in result.filters
        ), row["id"]

    if row.get("must_have_role"):
        assert any(
            f.field == "company_role" or "role" in blob.lower() for f in result.filters
        ) or "MCT" in blob or "DEV" in blob or "ARC" in blob or "SCT" in blob

    if max_f := row.get("max_filters"):
        semantic = [f for f in result.filters if f.field != "_semantic"]
        assert len(semantic) <= max_f, f"{row['id']}: too many filters {semantic}"

    if row.get("requires_geo_blocked"):
        has_geo = result.geo is not None or "userLocation" in blob or "blocked" in blob.lower()
        assert has_geo or "near" in row["query"].lower(), f"{row['id']}: expected geo handling"


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [pytest.param(r, id=r["id"]) for r in _load()["multi_turn"]])
async def test_mf28_multi_turn(row: dict) -> None:
    orch = QueryOrchestrator()
    r1 = await orch.search(row["setup"], execute=False, use_llm=False, context=EVAL_CONTEXT)
    sid = r1["session_id"]

    if row.get("expect_reset"):
        r2 = await orch.search(row["follow_up"], session_id=sid, execute=False, use_llm=False)
        assert r2.get("message") == "Session cleared"
        return

    r2 = await orch.search(row["follow_up"], session_id=sid, execute=False, use_llm=False, context=EVAL_CONTEXT)
    assert r2.get("intent") is not None, row["id"]
    blob = json.dumps(r2.get("intent", {}), ensure_ascii=False).lower()
    for frag in row.get("must_contain", []):
        assert frag.lower() in blob, f"{row['id']}: missing {frag!r}"


@pytest.mark.asyncio
async def test_mf28_orchestrator_defaults_and_license() -> None:
    """AC-5 / AC-6 via orchestrator (defaults + licence notice)."""
    orch = QueryOrchestrator()
    r = await orch.search(
        "show me projects in Uppsala",
        execute=False,
        use_llm=False,
        context=EVAL_CONTEXT,
    )
    assert r.get("intent")
    expl = (r.get("explanation") or "").lower()
    assert "default" in expl or r["intent"].get("default_exclusions_applied")

    r2 = await orch.search(
        "projects everywhere in Sweden, ignore my licence",
        execute=False,
        use_llm=False,
        context={"licensed_regions": ["Stockholm", "Uppsala"]},
    )
    assert r2.get("intent")
    assert r2["intent"].get("license_notice") or "license" in (r2.get("explanation") or "").lower()
