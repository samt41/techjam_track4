from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from time import perf_counter

from starter.shopping_agent.models import (
    ProductRecord,
    RankedRecommendation,
    ShoppingIntent,
    Strength,
)
from starter.shopping_agent.search_backend import ProductSearchBackend


MODEL_IDENTIFIERS = {
    "minilm-l4": "cross-encoder/ms-marco-MiniLM-L4-v2",
    "minilm-l6": "cross-encoder/ms-marco-MiniLM-L6-v2",
    "bge-base": "BAAI/bge-reranker-base",
}


@dataclass(frozen=True, slots=True)
class RerankEvent:
    session_id: str
    turn: int
    pool_size: int
    baseline_ids: tuple[str, ...]
    reranked_ids: tuple[str, ...]
    elapsed_ms: float
    scored_pairs: int
    cache_hits: int
    failed: bool = False


class RecordingRecommendationReranker:
    """Records the deterministic pool while returning its original top-k."""

    def __init__(self, candidate_pool_size: int = 200) -> None:
        if candidate_pool_size < 10:
            raise ValueError("candidate pool must contain at least ten products")
        self._candidate_pool_size = candidate_pool_size
        self.events: list[RerankEvent] = []

    @property
    def candidate_pool_size(self) -> int:
        return self._candidate_pool_size

    def rerank(
        self,
        session_id,
        turn,
        message,
        intent,
        recommendations,
        shown_product_ids,
        backend,
        top_k,
    ):
        del message, intent, shown_product_ids, backend
        baseline_ids = tuple(item.parent_asin for item in recommendations)
        result = recommendations[:top_k]
        self.events.append(RerankEvent(
            session_id=session_id,
            turn=turn,
            pool_size=len(recommendations),
            baseline_ids=baseline_ids,
            reranked_ids=tuple(item.parent_asin for item in result),
            elapsed_ms=0.0,
            scored_pairs=0,
            cache_hits=0,
        ))
        return result

    def close(self) -> None:
        return None


class CrossEncoderRecommendationReranker:
    """RRF-fuses deterministic rank with experiment-only cross-encoder rank."""

    def __init__(
        self,
        model_name: str,
        *,
        candidate_pool_size: int = 100,
        fusion_weight: float = 1.0,
        rrf_constant: float = 60.0,
        batch_size: int = 32,
        max_length: int = 256,
        device: str | None = None,
    ) -> None:
        if model_name not in MODEL_IDENTIFIERS:
            raise ValueError(f"unknown reranker model: {model_name}")
        if candidate_pool_size < 10:
            raise ValueError("candidate pool must contain at least ten products")
        if fusion_weight <= 0.0 or not math.isfinite(fusion_weight):
            raise ValueError("fusion weight must be finite and positive")
        if rrf_constant <= 0.0 or not math.isfinite(rrf_constant):
            raise ValueError("RRF constant must be finite and positive")
        if batch_size < 1 or max_length < 8:
            raise ValueError("batch size and max length must be positive")
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as error:  # pragma: no cover - optional dependency
            raise RuntimeError("install semantic-experiment dependencies") from error

        self.model_name = model_name
        self.model_identifier = MODEL_IDENTIFIERS[model_name]
        self._candidate_pool_size = candidate_pool_size
        self.fusion_weight = fusion_weight
        self.rrf_constant = rrf_constant
        self.batch_size = batch_size
        self.max_length = max_length
        self._model = CrossEncoder(
            self.model_identifier,
            device=device,
            max_length=max_length,
        )
        self.device = str(self._model.device)
        self.events: list[RerankEvent] = []
        self._score_cache: dict[tuple[str, str], float] = {}

    @property
    def candidate_pool_size(self) -> int:
        return self._candidate_pool_size

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
    ) -> tuple[RankedRecommendation, ...]:
        started = perf_counter()
        baseline_ids = tuple(item.parent_asin for item in recommendations)
        if len(recommendations) < 2:
            result = recommendations[:top_k]
            self._record(
                session_id, turn, baseline_ids, result, started, 0, 0, False
            )
            return result

        query = ranking_query(message, intent)
        products = backend.get_products(baseline_ids)
        product_by_id = {product.parent_asin: product for product in products}
        missing = tuple(
            item for item in recommendations if item.parent_asin not in product_by_id
        )
        if missing:
            raise ValueError("reranker could not load every candidate product")

        scores: dict[str, float] = {}
        uncached_ids: list[str] = []
        uncached_pairs: list[tuple[str, str]] = []
        cache_hits = 0
        for item in recommendations:
            cache_key = (query, item.parent_asin)
            cached = self._score_cache.get(cache_key)
            if cached is None:
                uncached_ids.append(item.parent_asin)
                uncached_pairs.append((query, product_document(product_by_id[item.parent_asin])))
            else:
                scores[item.parent_asin] = cached
                cache_hits += 1
        if uncached_pairs:
            predicted = self._model.predict(
                uncached_pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            for parent_asin, raw_score in zip(uncached_ids, predicted, strict=True):
                score = float(raw_score)
                if not math.isfinite(score):
                    raise ValueError("cross-encoder produced a non-finite score")
                scores[parent_asin] = score
                self._score_cache[(query, parent_asin)] = score

        cross_order = sorted(
            recommendations,
            key=lambda item: (-scores[item.parent_asin], item.parent_asin),
        )
        cross_rank = {
            item.parent_asin: rank for rank, item in enumerate(cross_order, start=1)
        }
        base_rank = {
            item.parent_asin: rank for rank, item in enumerate(recommendations, start=1)
        }

        def fused_score(item: RankedRecommendation) -> float:
            return (
                1.0 / (self.rrf_constant + base_rank[item.parent_asin])
                + self.fusion_weight
                / (self.rrf_constant + cross_rank[item.parent_asin])
            )

        reranked = tuple(sorted(
            recommendations,
            key=lambda item: (
                item.parent_asin in shown_product_ids,
                not item.exact_match,
                -fused_score(item),
                -scores[item.parent_asin],
                base_rank[item.parent_asin],
                item.parent_asin,
            ),
        ))
        result = reranked[:top_k]
        self._record(
            session_id,
            turn,
            baseline_ids,
            result,
            started,
            len(uncached_pairs),
            cache_hits,
            False,
        )
        return result

    def _record(
        self,
        session_id,
        turn,
        baseline_ids,
        result,
        started,
        scored_pairs,
        cache_hits,
        failed,
    ) -> None:
        self.events.append(RerankEvent(
            session_id=session_id,
            turn=turn,
            pool_size=len(baseline_ids),
            baseline_ids=tuple(baseline_ids),
            reranked_ids=tuple(item.parent_asin for item in result),
            elapsed_ms=(perf_counter() - started) * 1000.0,
            scored_pairs=scored_pairs,
            cache_hits=cache_hits,
            failed=failed,
        ))

    def close(self) -> None:
        # The matrix runner deliberately reuses one loaded model across datasets.
        # Process teardown releases the optional experiment dependency afterward.
        return None


def ranking_query(message: str, intent: ShoppingIntent) -> str:
    parts: list[str] = ["shopping request"]
    for constraint in intent.active_constraints:
        qualifier = "exclude" if constraint.excluded else (
            "require" if constraint.strength is Strength.HARD else "prefer"
        )
        parts.append(
            f"{qualifier} {constraint.attribute.value}: {constraint.value}"
        )
    active_groups = {
        constraint.preference_group_id for constraint in intent.active_constraints
    }
    for concept in intent.weighted_concepts:
        if concept.preference_group_id in active_groups:
            parts.append(f"related preference: {concept.value}")
    if len(parts) == 1 and message.strip():
        parts.append(f"customer says: {message.strip()}")
    return "; ".join(dict.fromkeys(parts))


def product_document(product: ProductRecord) -> str:
    parts = [
        f"title: {product.title}",
        f"category: {' > '.join(product.categories)}",
    ]
    if product.details:
        parts.append("details: " + "; ".join(
            f"{key}: {value}" for key, value in product.details
        ))
    if product.features:
        parts.append("features: " + "; ".join(product.features))
    if product.description:
        parts.append(f"description: {product.description}")
    if product.store:
        parts.append(f"brand or store: {product.store}")
    return " | ".join(parts)


def latency_summary(events: list[RerankEvent]) -> dict[str, float | int]:
    latencies = sorted(event.elapsed_ms for event in events)
    return {
        "event_count": len(events),
        "scored_pairs": sum(event.scored_pairs for event in events),
        "cache_hits": sum(event.cache_hits for event in events),
        "failures": sum(event.failed for event in events),
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "latency_ms_mean": (
            0.0 if not latencies else round(statistics.fmean(latencies), 6)
        ),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 6)
    index = max(0, min(len(values) - 1, round((len(values) - 1) * fraction)))
    return round(values[index], 6)
