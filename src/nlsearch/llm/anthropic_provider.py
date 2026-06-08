"""Anthropic-backed LLM provider (optional dependency)."""

from __future__ import annotations

import json
import re
from typing import Any

from nlsearch.config import get_settings
from nlsearch.llm.base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Any = None

    @property
    def available(self) -> bool:
        return bool(self._settings.Anthropic_api_key and self._settings.llm_provider.lower() == "Anthropic")

    def _client_lazy(self) -> Any:
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise RuntimeError(
                    "Anthropic package required: pip install 'nlsearch[llm]'"
                ) from exc
            self._client = AsyncAnthropic(api_key=self._settings.Anthropic_api_key)
        return self._client

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("Anthropic provider not configured (NLSEARCH_LLM_PROVIDER=Anthropic)")

        response = await self._client_lazy().messages.create(
            model=self._settings.anthropic_model,
            temperature=temperature if temperature is not None else self._settings.llm_temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = response.content[0].text or "{}"
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
