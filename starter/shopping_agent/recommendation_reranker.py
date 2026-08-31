from __future__ import annotations

from typing import Protocol

from starter.shopping_agent.models import RankedRecommendation, ShoppingIntent
from starter.shopping_agent.search_backend import ProductSearchBackend


class RecommendationReranker(Protocol):
    """Optional second-stage ordering applied after deterministic eligibility."""

    @property
    def candidate_pool_size(self) -> int: ...

    def rerank(
        self,
        session_id: str,
        turn: int,
        message: str,
        intent: ShoppingIntent,
        recommendations: tuple[RankedRecommendation, ...],
        shown_product_ids: frozenset[str],
        backend: ProductSearchBackend,
        top_k: int,
    ) -> tuple[RankedRecommendation, ...]: ...

    def close(self) -> None: ...
