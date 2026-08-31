from __future__ import annotations

from typing import Protocol

from starter.shopping_agent.models import (
    Attribute,
    PreferenceUpdate,
    ProductCandidate,
    ShoppingIntent,
)
from starter.shopping_agent.search_backend import ProductSearchBackend


class AdditionalCandidateProvider(Protocol):
    """Optional low-authority source of strictly gated retrieval candidates."""

    def candidates(
        self,
        message: str,
        asked_attribute: Attribute | None,
        updates: tuple[PreferenceUpdate, ...],
        intent: ShoppingIntent,
        backend: ProductSearchBackend,
        top_k: int,
    ) -> tuple[ProductCandidate, ...]: ...

    def close(self) -> None: ...
