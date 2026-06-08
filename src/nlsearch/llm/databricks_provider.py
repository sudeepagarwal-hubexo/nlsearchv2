"""Databricks-backed LLM provider (optional dependency)."""

from __future__ import annotations

import json
import re
from typing import Any

from nlsearch.config import ensure_databricks_credentials, get_settings
from nlsearch.llm.base import LLMProvider


class DatabricksProvider(LLMProvider):
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Any = None

    @property
    def available(self) -> bool:
        s = ensure_databricks_credentials(self._settings)
        return bool(
            s.llm_provider.lower() == "databricks"
            and s.databricks_ai_gateway_token
            and (s.databricks_ai_gateway_endpoint or s.databricks_host)
            and s.databricks_ai_gateway_model
        )

    def _client_lazy(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "openai package required: pip install 'nlsearch[llm]'"
                ) from exc
            s = ensure_databricks_credentials(self._settings)
            base = s.databricks_ai_gateway_endpoint
            if not base and s.databricks_host:
                from nlsearch.config import _https_host

                # https://dbc-33376193-7527.cloud.databricks.com/ai-gateway/mlflow/v1/chat/completions
                base = f"{_https_host(s.databricks_host)}/ai-gateway/mlflow/v1"
            self._client = AsyncOpenAI(
                api_key=s.databricks_ai_gateway_token,
                base_url=base,
            )
        return self._client

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError(
                "Databricks LLM not configured — set NLSEARCH_DATABRICKS_TOKEN "
                "or log in via Databricks CLI (profile in NLSEARCH_DATABRICKS_PROFILE)"
            )

        s = ensure_databricks_credentials(self._settings)
        temp = temperature if temperature is not None else s.llm_temperature

        try:
            response = await self._client_lazy().chat.completions.create(
                model=s.databricks_ai_gateway_model,
                # temperature=temp,
                # response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            print("\nResponse:", response)
        except Exception as e:
            print("Error:", e)
            raise
        
        text = response.choices[0].message.content or "{}"
        return _parse_json(text)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise
