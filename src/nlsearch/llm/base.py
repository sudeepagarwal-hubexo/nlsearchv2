"""LLM provider protocol for optional intent/SQL refinement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    @property
    @abstractmethod
    def available(self) -> bool:
        """True when API credentials and dependencies are configured."""

    @abstractmethod
    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Return parsed JSON object from model response."""
