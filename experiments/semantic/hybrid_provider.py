from __future__ import annotations

import math
import re
from dataclasses import dataclass
from time import perf_counter

from experiments.semantic.artifacts import load_embedding_artifact
from experiments.semantic.encoders import (
    ENCODER_CONFIGURATIONS,
    SentenceTransformerEncoder,
)
from experiments.semantic.probe import load_concepts
from experiments.semantic.schemas import CatalogConcept
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    PreferenceUpdate,
    ProductCandidate,
    RetrievalRoute,
    RouteEvidence,
    ShoppingIntent,
    Strength,
)
from starter.shopping_agent.search_backend import (
    AttributeTarget,
    ProductSearchBackend,
    SearchRequest,
    StructuredFilter,
)
from starter.shopping_agent.text_normalization import normalize_text


_UNSAFE_RE = re.compile(
    r"\b(?:not|no|without|avoid|exclude|instead of|rather than|don'?t|do not)\b"
)
_GENERIC_RE = re.compile(
    r"\b(?:still exploring|use your judgment|ask me about one specific attribute|"
    r"options are not quite right)\b"
)
_MATERIAL_RE = re.compile(
    r"\b(?:made from|made of|material|fabric|fibre|fiber|hide|textile)\b"
)
_SUPPORTED_ATTRIBUTES = frozenset({
    Attribute.CATEGORY,
    Attribute.MATERIAL,
    Attribute.COLOR,
    Attribute.SIZE,
    Attribute.STYLE,
    Attribute.BRAND,
    Attribute.FEATURE,
})


@dataclass(frozen=True, slots=True)
class HybridConfiguration:
    minimum_score: float
    minimum_margin: float
    route_weight: float = 0.45
    concept_top_k: int = 25
    product_limit: int = 1_000
    work_limit: int = 250_000

    def validate(self) -> None:
        if not -1.0 <= self.minimum_score <= 1.0:
            raise ValueError("minimum semantic score must be a cosine value")
        if not 0.0 <= self.minimum_margin <= 2.0:
            raise ValueError("minimum semantic margin is invalid")
        if self.route_weight <= 0.0:
            raise ValueError("semantic route weight must be positive")
        if self.concept_top_k < 1 or self.product_limit < 1:
            raise ValueError("semantic limits must be positive")


@dataclass(frozen=True, slots=True)
class SemanticResolution:
    clause: str
    concept_id: str | None
    concept_ids: tuple[str, ...]
    score: float
    margin: float
    accepted: bool
    reason: str
    elapsed_ms: float

    def as_record(self) -> dict[str, object]:
        return {
            "clause": self.clause,
            "concept_id": self.concept_id,
            "concept_ids": list(self.concept_ids),
            "score": round(self.score, 8),
            "margin": round(self.margin, 8),
            "accepted": self.accepted,
            "reason": self.reason,
            "elapsed_ms": round(self.elapsed_ms, 6),
        }


class SemanticHybridProvider:
    def __init__(
        self,
        concept_path: str,
        artifact_path: str,
        model_name: str,
        configuration: HybridConfiguration,
        *,
        batch_size: int = 16,
    ) -> None:
        configuration.validate()
        self.configuration = configuration
        self.concepts = load_concepts(concept_path)
        self._artifact = load_embedding_artifact(artifact_path, concept_path)
        if self._artifact.model_name != model_name:
            raise ValueError("semantic model and embedding artifact do not match")
        self._encoder = SentenceTransformerEncoder(
            ENCODER_CONFIGURATIONS[model_name], batch_size=batch_size
        )
        if self._encoder.resolved_revision != self._artifact.resolved_revision:
            raise ValueError("semantic query model revision does not match artifact")
        self._indices_by_attribute = {
            attribute: tuple(
                index
                for index, concept in enumerate(self.concepts)
                if concept.attribute is attribute
            )
            for attribute in _SUPPORTED_ATTRIBUTES
        }
        self._concept_by_id = {
            concept.concept_id: concept for concept in self.concepts
        }
        self.resolutions: list[SemanticResolution] = []

    def candidates(
        self,
        message: str,
        asked_attribute: Attribute | None,
        updates: tuple[PreferenceUpdate, ...],
        intent: ShoppingIntent,
        backend: ProductSearchBackend,
        top_k: int,
    ) -> tuple[ProductCandidate, ...]:
        del updates, top_k
        resolution = self.resolve(message, asked_attribute)
        self.resolutions.append(resolution)
        if not resolution.accepted or not resolution.concept_ids:
            return ()
        candidates: list[ProductCandidate] = []
        for concept_rank, concept_id in enumerate(resolution.concept_ids, start=1):
            concept = self._concept_by_id[concept_id]
            request = SearchRequest(
                route=RetrievalRoute.SEMANTIC,
                lexical_terms=(),
                filters=_hard_filters(intent),
                targets=(AttributeTarget(concept.attribute, (concept.surface_text,)),),
                limit=self.configuration.product_limit,
                work_limit=self.configuration.work_limit,
            )
            result = backend.search(request)
            candidates.extend(
                ProductCandidate(
                    parent_asin=hit.parent_asin,
                    evidence=(RouteEvidence(
                        route=RetrievalRoute.SEMANTIC,
                        rank=hit.rank,
                        score=self.configuration.route_weight / concept_rank,
                    ),),
                    relaxed_constraint_id=None,
                )
                for hit in result.hits
            )
        return tuple(candidates)

    def resolve(
        self,
        message: str,
        asked_attribute: Attribute | None = None,
    ) -> SemanticResolution:
        started = perf_counter()
        clause = _semantic_clause(message)
        normalized = normalize_text(clause)
        if not normalized or _GENERIC_RE.search(normalized):
            return _resolution(clause, (), 0.0, 0.0, False, "generic", started)
        if _UNSAFE_RE.search(normalized):
            return _resolution(
                clause, (), 0.0, 0.0, False, "symbolic_boundary", started
            )
        scope = _scope(asked_attribute, normalized)
        scoped_indices = (
            self._indices_by_attribute[scope]
            if scope in self._indices_by_attribute
            else tuple(range(len(self.concepts)))
        )
        exact = tuple(
            index
            for index in scoped_indices
            if normalize_text(self.concepts[index].surface_text) == normalized
            or normalized in {
                normalize_text(alias) for alias in self.concepts[index].aliases
            }
        )
        if exact:
            return _resolution(
                clause, self.concepts[exact[0]].concept_id, 1.0, 1.0,
                False, "already_exact", started,
            )
        query_text = (
            f"attribute: {scope.value}; {clause}" if scope is not None else clause
        )
        vector = self._encoder.encode_queries((query_text,))[0]
        try:
            import numpy as np
        except ImportError as error:  # pragma: no cover - optional dependency
            raise RuntimeError("install semantic-experiment dependencies") from error
        indices = np.asarray(scoped_indices, dtype=np.int64)
        surface_scores = self._artifact.surface_vectors[indices] @ vector
        context_scores = self._artifact.contextual_vectors[indices] @ vector
        scores = np.maximum(surface_scores, context_scores)
        order = sorted(
            range(len(scoped_indices)),
            key=lambda offset: (
                -float(scores[offset]),
                self.concepts[scoped_indices[offset]].concept_id,
            ),
        )[:max(2, self.configuration.concept_top_k)]
        if not order:
            return _resolution(clause, (), 0.0, 0.0, False, "empty_scope", started)
        winner_offset = order[0]
        winner_score = float(scores[winner_offset])
        runner_score = float(scores[order[1]]) if len(order) > 1 else -1.0
        margin = winner_score - runner_score
        accepted = (
            winner_score >= self.configuration.minimum_score
            and margin >= self.configuration.minimum_margin
        )
        reason = "accepted" if accepted else (
            "below_score" if winner_score < self.configuration.minimum_score
            else "ambiguous_margin"
        )
        ranked_concept_ids = tuple(
            self.concepts[scoped_indices[offset]].concept_id
            for offset in order[:self.configuration.concept_top_k]
        )
        return _resolution(
            clause,
            ranked_concept_ids,
            winner_score,
            margin,
            accepted,
            reason,
            started,
        )

    def close(self) -> None:
        return None


def _semantic_clause(message: str) -> str:
    normalized = message.strip()
    if ":" in normalized:
        return normalized.rsplit(":", 1)[1].strip(" .")
    if ". " in normalized and normalized.casefold().startswith("i'm looking"):
        return normalized.split(". ", 1)[1].strip(" .")
    return normalized


def _scope(asked_attribute: Attribute | None, clause: str) -> Attribute | None:
    if asked_attribute in _SUPPORTED_ATTRIBUTES:
        return asked_attribute
    if _MATERIAL_RE.search(clause):
        return Attribute.MATERIAL
    return None


def _hard_filters(intent: ShoppingIntent) -> tuple[StructuredFilter, ...]:
    return tuple(
        StructuredFilter(
            constraint_id=constraint.constraint_id,
            attribute=constraint.attribute,
            operator=constraint.operator,
            value=constraint.value,
            excluded=constraint.excluded,
            confidence=constraint.confidence,
        )
        for constraint in intent.active_constraints
        if constraint.strength is Strength.HARD
    )


def _resolution(
    clause: str,
    concept_ids: tuple[str, ...] | str,
    score: float,
    margin: float,
    accepted: bool,
    reason: str,
    started: float,
) -> SemanticResolution:
    if not math.isfinite(score) or not math.isfinite(margin):
        raise ValueError("semantic scores must be finite")
    normalized_ids = (
        (concept_ids,) if isinstance(concept_ids, str) else concept_ids
    )
    return SemanticResolution(
        clause=clause,
        concept_id=normalized_ids[0] if normalized_ids else None,
        concept_ids=normalized_ids,
        score=score,
        margin=margin,
        accepted=accepted,
        reason=reason,
        elapsed_ms=(perf_counter() - started) * 1000.0,
    )
