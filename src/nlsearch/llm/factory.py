"""Factory for configured LLM providers."""

from __future__ import annotations

from nlsearch.config import ensure_databricks_credentials, get_settings
from nlsearch.llm.base import LLMProvider
from nlsearch.llm.openai_provider import OpenAIProvider
from nlsearch.llm.databricks_provider import DatabricksProvider

_providers: dict[str, LLMProvider] = {}


def get_llm_provider() -> LLMProvider | None:
    settings = ensure_databricks_credentials()
    name = (settings.llm_provider or "").lower()
    if not name or name == "none":
        return None
    if name == "databricks":
        provider = DatabricksProvider()
        return provider if provider.available else None
    if name not in _providers:
        if name == "openai":
            _providers[name] = OpenAIProvider()
        else:
            return None
    provider = _providers[name]
    return provider if provider.available else None
