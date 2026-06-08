"""Query orchestrator: intent → schema RAG → SQL → validate → execute → format."""

from __future__ import annotations

from pickle import FALSE
import time
from typing import Any

from nlsearch.execution.databricks import DatabricksExecutor
from nlsearch.execution.formatter import ResultFormatter
from nlsearch.governance.defaults import DefaultExclusions
from nlsearch.governance.license import LicenseFilter
from nlsearch.intent.analyzer import IntentAnalyzer
from nlsearch.memory.session import SessionState, SessionStore
from nlsearch.models.intent import NoCoverageResponse, QueryIntent, SearchResponse
from nlsearch.semantic.glossary import BusinessGlossary
from nlsearch.semantic.schema_store import SchemaStore
from nlsearch.config import ensure_databricks_credentials, get_settings
from nlsearch.llm.refiner import LLMRefiner
from nlsearch.llm.rune_intent import LLMIntentEngine
from nlsearch.sql.generator import SQLGenerator
from nlsearch.sql.validator import SQLValidator


class QueryOrchestrator:
    def __init__(self) -> None:
        self._analyzer = IntentAnalyzer()
        self._schema = SchemaStore()
        self._glossary = BusinessGlossary()
        self._sql_gen = SQLGenerator(self._schema)
        self._sql_val = SQLValidator(self._schema)
        self._license = LicenseFilter()
        self._defaults = DefaultExclusions()
        self._sessions = SessionStore()
        self._executor = DatabricksExecutor()
        self._formatter = ResultFormatter()
        self._llm = LLMRefiner.from_settings()
        self._llm_intent = LLMIntentEngine.from_settings(self._schema, self._sessions)
        self._settings = get_settings()

    async def sync_schema(self) -> dict[str, Any]:
        return await self._schema.sync_from_unity_catalog()

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        context: dict[str, Any] | None = None,
        execute: bool = True,
        use_llm: bool | None = None,
        intent_mode: str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        latency: dict[str, float] = {}
        ctx = dict(context or {})
        intent_source = "rules"

        if not session_id:
            session_id = self._sessions.create_session()
        ctx["session_id"] = session_id

        llm_on = use_llm if use_llm is not None else bool(self._settings.llm_provider)
        mode = (intent_mode or ctx.get("intent_mode") or self._settings.llm_intent_mode).lower()
        intent_warnings: list[str] = []

        if llm_on or (execute and not self._executor.configured):
            ensure_databricks_credentials(self._settings)

        # Intent
        t1 = time.perf_counter()
        raw, intent_source = await self._resolve_intent(
            query, ctx, llm_on=llm_on, intent_mode=mode
        )
        if mode == "primary" and llm_on and intent_source != "llm":
            intent_warnings.append(
                "LLM intent unavailable or below confidence — used rule-based fallback. "
                "Check NLSEARCH_DATABRICKS_TOKEN or CLI auth and AI gateway model."
            )
        latency["intent_ms"] = (time.perf_counter() - t1) * 1000

        response = SearchResponse(session_id=session_id)

        if isinstance(raw, NoCoverageResponse):
            response.no_coverage = raw
            response.explanation = raw.message
            return self._wrap(response, latency, t0)

        intent: QueryIntent = raw

        # Session merge / update
        if intent.session_patch.get("reset"):
            self._sessions.save(session_id, SessionState())
            return self._wrap(response, latency, t0, {"message": "Session cleared"})

        intent = self._sessions.merge_into_intent(session_id, intent)
        self._sessions.apply_turn(session_id, intent, query)

        # Glossary expansion (logged in assumptions)
        terms = self._glossary.translate(query)
        if terms:
            intent.assumptions.append(f"Glossary mappings: {terms}")

        # Schema retrieval
        t2 = time.perf_counter()
        entities = [intent.result_type.value.lower()]
        schema_chunks = self._schema.retrieve_for_query(query, entities)
        schema_prompt = self._schema.format_for_prompt(schema_chunks)
        latency["schema_ms"] = (time.perf_counter() - t2) * 1000

        # Optional LLM intent refinement (rules/refine modes only)
        if (
            llm_on
            and mode != "primary"
            and self._llm.enabled
            and self._settings.llm_refine_intent
            and intent_source == "rules"
        ):
            t_llm = time.perf_counter()
            intent = await self._llm.refine_intent(
                query,
                intent,
                schema_prompt,
                min_confidence=self._settings.llm_min_confidence,
            )
            latency["llm_intent_ms"] = (time.perf_counter() - t_llm) * 1000
            intent_source = "rules+llm_refine"

        # Governance
        intent = self._license.apply(intent)
        intent = self._defaults.apply(intent, query)

        # SQL
        t3 = time.perf_counter()
        intent.sql = self._sql_gen.generate(intent, schema_prompt)
        latency["sql_gen_ms"] = (time.perf_counter() - t3) * 1000

        if llm_on and self._llm.enabled and self._settings.llm_refine_sql and FALSE:
            t_llm_sql = time.perf_counter()
            refined_sql, llm_notes = await self._llm.refine_sql(
                query, intent, intent.sql, schema_prompt
            )
            intent.sql = refined_sql
            intent.assumptions.extend(llm_notes)
            latency["llm_sql_ms1"] = (time.perf_counter() - t_llm_sql) * 1000

        t4 = time.perf_counter()
        validation = self._sql_val.validate(intent.sql, tenant_id=(context or {}).get("tenant_id"))
        latency["validation_ms"] = (time.perf_counter() - t4) * 1000

        if not validation.valid:
            response.no_coverage = NoCoverageResponse(
                code="SQL_VALIDATION_FAILED",
                message="; ".join(validation.errors),
            )
            return self._wrap(response, latency, t0)

        rows: list[dict[str, Any]] = []
        execution_meta: dict[str, Any] = {}
        if execute:
            t5 = time.perf_counter()
            result = await self._executor.execute(intent.sql)
            latency["execution_ms"] = (time.perf_counter() - t5) * 1000
            rows = result.get("rows", [])
            execution_meta = {
                "mock": result.get("mock", False),
                "message": result.get("message"),
            }
            if result.get("mock") and not rows:
                intent_warnings.append(
                    result.get("message") or "Databricks returned no rows (not configured)"
                )

        response.intent = intent
        response.latency_ms = latency
        formatted = self._formatter.format(intent, rows, response)
        if intent_warnings:
            formatted["explanation"] = (
                formatted.get("explanation", "") + " | Warnings: " + "; ".join(intent_warnings)
            )
        formatted["session_id"] = session_id
        formatted["validation_warnings"] = validation.warnings
        formatted["intent_warnings"] = intent_warnings
        formatted["execution"] = execution_meta
        formatted["llm_used"] = intent_source in ("llm", "rules+llm_refine")
        formatted["intent_source"] = intent_source
        formatted["intent_mode"] = mode
        formatted["latency_ms"] = {**latency, "total_ms": (time.perf_counter() - t0) * 1000}
        return formatted

    async def _resolve_intent(
        self,
        query: str,
        context: dict[str, Any],
        *,
        llm_on: bool,
        intent_mode: str,
    ) -> tuple[QueryIntent | NoCoverageResponse, str]:
        print("Resolving intent with mode:", intent_mode, "and LLM on:", llm_on)
        print("LLM intent enabled:", self._llm_intent.enabled)
        
        if intent_mode == "primary" and llm_on and not self._llm_intent.enabled:
            from nlsearch.llm.factory import get_llm_provider

            provider = get_llm_provider()
            print("LLM provider:", provider)
            if provider:
                self._llm_intent = LLMIntentEngine(
                    self._schema, provider=provider, session_store=self._sessions
                )
        if intent_mode == "primary" and llm_on and self._llm_intent.enabled:
            print("LLM intent enabled", self._llm_intent)
            try:
                result = await self._llm_intent.analyze(
                    query,
                    context,
                    min_confidence=self._settings.llm_min_confidence,
                )
                return result, "llm"
            except Exception:
                if not self._settings.llm_fallback_to_rules:
                    raise
            raw = self._analyzer.analyze(query, context)
            return raw, "rules_fallback"

        raw = self._analyzer.analyze(query, context)
        return raw, "rules"

    def _wrap(
        self,
        response: SearchResponse,
        latency: dict[str, float],
        t0: float,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        out = {
            "session_id": response.session_id,
            "intent": response.intent.model_dump() if response.intent else None,
            "no_coverage": response.no_coverage.model_dump() if response.no_coverage else None,
            "explanation": response.explanation,
            "latency_ms": {**latency, "total_ms": (time.perf_counter() - t0) * 1000},
        }
        if extra:
            out.update(extra)
        return out
