"""OpenAI-backed LLM provider (optional dependency)."""

from __future__ import annotations

import json
import re
from typing import Any

from nlsearch.config import get_settings
from nlsearch.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Any = None

    @property
    def available(self) -> bool:
        return bool(self._settings.openai_api_key and self._settings.llm_provider.lower() == "openai")

    def _client_lazy(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "openai package required: pip install 'nlsearch[llm]'"
                ) from exc
            self._client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        return self._client

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("OpenAI provider not configured (NLSEARCH_LLM_PROVIDER=openai)")

        temp = temperature if temperature is not None else self._settings.llm_temperature
        response = await self._client_lazy().chat.completions.create(
            model=self._settings.openai_model,
            temperature=temp,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
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
