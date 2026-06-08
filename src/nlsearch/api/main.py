"""FastAPI gateway for NL search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nlsearch import __version__
from nlsearch.config import get_settings
from nlsearch.orchestrator import QueryOrchestrator

app = FastAPI(title=get_settings().app_name, version=(version := __version__))
_orchestrator = QueryOrchestrator()

_WEB_DIR = Path(__file__).resolve().parent / "static"
if _WEB_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=_WEB_DIR), name="ui")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language search query")
    session_id: str | None = None
    execute: bool = True
    use_llm: bool | None = Field(
        default=None,
        description="Enable LLM when provider configured; default follows NLSEARCH_LLM_PROVIDER",
    )
    intent_mode: str | None = Field(
        default=None,
        description="Intent pipeline: rules (default), refine (rules+LLM polish), primary (Rune LLM first)",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="user_region, licensed_regions, eval_now, tenant_id, session hints",
    )


class SearchResult(BaseModel):
    session_id: str
    intent: dict[str, Any] | None = None
    expression: str | None = None
    sql: str | None = None
    rows: list[Any] = Field(default_factory=list)
    row_count: int = 0
    explanation: str = ""
    no_coverage: dict[str, Any] | None = None
    intent_source: str | None = None
    intent_mode: str | None = None
    intent_warnings: list[str] = Field(default_factory=list)
    execution: dict[str, Any] = Field(default_factory=dict)
    llm_used: bool = False
    latency_ms: dict[str, float] = Field(default_factory=dict)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": version}


@app.get("/")
async def web_ui() -> FileResponse:
    """Search UI — textarea query + categorized result tables."""
    index = _WEB_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Web UI not found")
    return FileResponse(index)


@app.post("/v1/search", response_model=SearchResult)
async def search(body: SearchRequest) -> dict[str, Any]:
    try:
        return await _orchestrator.search(
            query=body.query,
            session_id=body.session_id,
            context=body.context,
            execute=body.execute,
            use_llm=body.use_llm,
            intent_mode=body.intent_mode,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/intent")
async def intent_only(body: SearchRequest) -> dict[str, Any]:
    """Return structured intent without executing SQL."""
    return await _orchestrator.search(
        query=body.query,
        session_id=body.session_id,
        context=body.context,
        execute=False,
        use_llm=body.use_llm,
        intent_mode=body.intent_mode,
    )


@app.post("/v1/admin/schema/sync")
async def sync_unity_catalog_schema() -> dict[str, Any]:
    """Pull table/column metadata from Databricks Unity Catalog into local schema store."""
    try:
        return await _orchestrator.sync_schema()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/v1/admin/schema/tables")
async def list_schema_tables() -> dict[str, Any]:
    store = _orchestrator._schema
    return {"tables": store.all_tables(), "count": len(store.all_tables())}


@app.delete("/v1/session/{session_id}")
async def clear_session(session_id: str) -> dict[str, str]:
    from nlsearch.memory.session import SessionState

    _orchestrator._sessions.save(session_id, SessionState())
    return {"status": "cleared", "session_id": session_id}
