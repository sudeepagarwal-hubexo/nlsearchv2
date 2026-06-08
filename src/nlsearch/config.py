from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NLSEARCH_", env_file=".env", extra="ignore")

    app_name: str = "Hubexo NL Search"
    debug: bool = False
    timezone: str = "Europe/Stockholm"
    default_currency: str = "SEK"

    # Session memory: in-memory if redis_url empty
    redis_url: str = ""
    session_ttl_seconds: int = 3600

    # Optional LLM for SQL / intent refinement
    llm_provider: str = ""  # openai | databricks | none
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    llm_temperature: float = 0.0
    # rules = rule-based only; refine = rules + LLM polish; primary = Rune LLM intent first
    llm_intent_mode: str = "rules"
    llm_refine_intent: bool = True
    llm_refine_sql: bool = False
    llm_min_confidence: float = 0.55
    llm_fallback_to_rules: bool = True

    # Databricks — leave token empty to resolve via CLI profile (_token_from_client)
    databricks_profile: str = ""
    databricks_host: str = ""
    databricks_http_path: str = ""
    databricks_token: str = ""
    skip_databricks_cli: bool = False  # set true in tests (NLSEARCH_SKIP_DATABRICKS_CLI)

    databricks_ai_gateway_host: str = ""
    databricks_ai_gateway_token: str = ""
    databricks_workspace_id: int = 0
    databricks_ai_gateway_endpoint: str = ""
    # databricks_ai_gateway_model: str = "databricks-claude-opus-4-8"
    databricks_ai_gateway_model: str = "databricks-gpt-5-4-nano"
    # databricks_ai_gateway_model: str = "databricks-gpt-5-nano"

    # Unity Catalog schema sync
    unity_catalog_name: str = "europe_prod_catalog"
    unity_schema_name: str = "mimir_model_gold"
    unity_table_allowlist: str = ""

    licensed_regions: str = "Stockholm,Göteborg,Skåne,Västra Götaland,Uppsala,Solna,Blekinge,Halland,Småland"

    fx_gbp_to_sek: float = 13.5
    fx_usd_to_sek: float = 10.5
    fx_eur_to_sek: float = 11.5


_workspace_client: Any = None


def get_workspace_client(profile: str | None = None) -> Any:
    """Lazy WorkspaceClient — uses NLSEARCH_DATABRICKS_PROFILE (no get_settings recursion)."""
    global _workspace_client
    if _workspace_client is not None:
        return _workspace_client
    from databricks.sdk import WorkspaceClient

    prof = profile or Settings().databricks_profile
    _workspace_client = WorkspaceClient(profile=prof)
    return _workspace_client


def _token_from_client(profile: str | None = None) -> str:
    """OAuth token from Databricks CLI / SDK when NLSEARCH_DATABRICKS_TOKEN is unset."""
    try:
        client = get_workspace_client(profile)
        auth = client.config.authenticate()
        return auth.get("Authorization", "").removeprefix("Bearer ")
    except Exception:
        return ""


def _https_host(host: str) -> str:
    h = (host or "").strip().rstrip("/")
    if not h:
        return ""
    return h if h.startswith("http") else f"https://{h}"


def _wire_ai_gateway(s: Settings) -> None:
    """Mirror SQL warehouse credentials into AI gateway settings when unset."""
    if s.databricks_token and not s.databricks_ai_gateway_token:
        s.databricks_ai_gateway_token = s.databricks_token
    if s.databricks_host and not s.databricks_ai_gateway_host:
        s.databricks_ai_gateway_host = s.databricks_host
    if s.databricks_host and not s.databricks_ai_gateway_endpoint:
        base = _https_host(s.databricks_host)
        s.databricks_ai_gateway_endpoint = f"{base}/ai-gateway/mlflow/v1"


def _resolve_databricks_from_cli(s: Settings) -> None:
    """When NLSEARCH_DATABRICKS_TOKEN is empty, use CLI auth via _token_from_client()."""
    if s.databricks_token or s.skip_databricks_cli:
        return
    token = _token_from_client(s.databricks_profile)
    if not token:
        return
    s.databricks_token = token
    try:
        client = get_workspace_client(s.databricks_profile)
        s.databricks_host = s.databricks_host or (client.config.host or "")
        s.databricks_workspace_id = s.databricks_workspace_id or int(
            client.config.workspace_id or 0
        )
    except Exception:
        pass


@lru_cache
def get_settings() -> Settings:
    """Load settings; resolve Databricks token from CLI if not in .env."""
    s = Settings()
    _resolve_databricks_from_cli(s)
    _wire_ai_gateway(s)
    return s


def ensure_databricks_credentials(settings: Settings | None = None) -> Settings:
    """Re-run CLI token resolution and AI gateway wiring (idempotent)."""
    s = settings or get_settings()
    _resolve_databricks_from_cli(s)
    _wire_ai_gateway(s)
    return s
