from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from experiments.semantic.schemas import CatalogConcept, ConceptHit, ProbeCase
from starter.shopping_agent.retrieval import _EXPANSIONS
from starter.shopping_agent.text_normalization import search_terms


def lexical_search(
    case: ProbeCase,
    concepts: tuple[CatalogConcept, ...],
    *,
    top_k: int = 5,
) -> tuple[ConceptHit, ...]:
    query_tokens = set(search_terms(case.query_text()))
    expanded_tokens = set(query_tokens)
    for token in tuple(query_tokens):
        for expansion in _EXPANSIONS.get(token, ()):
            expanded_tokens.update(search_terms(expansion))
    scored: list[tuple[str, float]] = []
    for concept in _scoped_concepts(case, concepts):
        concept_tokens = set(search_terms(
            f"{concept.surface_text} {' '.join(concept.aliases)}"
        ))
        overlap = expanded_tokens & concept_tokens
        if not overlap:
            continue
        score = len(overlap) / math.sqrt(
            max(1, len(expanded_tokens)) * max(1, len(concept_tokens))
        )
        scored.append((concept.concept_id, score))
    return _hits(scored, top_k)


def dense_search(
    cases: tuple[ProbeCase, ...],
    concepts: tuple[CatalogConcept, ...],
    query_vectors: object,
    surface_vectors: object,
    contextual_vectors: object,
    *,
    top_k: int = 5,
) -> dict[str, tuple[ConceptHit, ...]]:
    """Exact cosine search over already normalized vectors.

    NumPy is used for catalog-scale experiments. A pure-Python path keeps the
    algorithm testable without installing optional experiment dependencies.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - exercised in minimal environments
        return _dense_search_python(
            cases, concepts, query_vectors, surface_vectors, contextual_vectors,
            top_k=top_k,
        )

    queries = np.asarray(query_vectors, dtype=np.float32)
    surfaces = np.asarray(surface_vectors, dtype=np.float32)
    contexts = np.asarray(contextual_vectors, dtype=np.float32)
    if queries.ndim != 2 or surfaces.ndim != 2 or contexts.ndim != 2:
        raise ValueError("embedding matrices must have two dimensions")
    if surfaces.shape != contexts.shape or surfaces.shape[0] != len(concepts):
        raise ValueError("concept vector rows must match concepts")
    if queries.shape[0] != len(cases) or queries.shape[1] != surfaces.shape[1]:
        raise ValueError("query vector shape does not match cases or concepts")
    scores = np.maximum(queries @ surfaces.T, queries @ contexts.T)
    result: dict[str, tuple[ConceptHit, ...]] = {}
    for case_index, case in enumerate(cases):
        scoped = [
            index
            for index, concept in enumerate(concepts)
            if _in_scope(case, concept)
        ]
        ranked = sorted(
            ((concepts[index].concept_id, float(scores[case_index, index]))
             for index in scoped),
            key=lambda item: (-item[1], item[0]),
        )
        result[case.case_id] = _hits(ranked, top_k, presorted=True)
    return result


def _dense_search_python(
    cases: tuple[ProbeCase, ...],
    concepts: tuple[CatalogConcept, ...],
    query_vectors: Sequence[Sequence[float]],
    surface_vectors: Sequence[Sequence[float]],
    contextual_vectors: Sequence[Sequence[float]],
    *,
    top_k: int,
) -> dict[str, tuple[ConceptHit, ...]]:
    if len(query_vectors) != len(cases):
        raise ValueError("query vector rows must match probe cases")
    if len(surface_vectors) != len(concepts) or len(contextual_vectors) != len(concepts):
        raise ValueError("concept vector rows must match concepts")
    result: dict[str, tuple[ConceptHit, ...]] = {}
    for case, query in zip(cases, query_vectors):
        scored: list[tuple[str, float]] = []
        for concept, surface, contextual in zip(
            concepts, surface_vectors, contextual_vectors
        ):
            if not _in_scope(case, concept):
                continue
            if len(query) != len(surface) or len(surface) != len(contextual):
                raise ValueError("embedding dimensions must agree")
            score = max(
                sum(float(a) * float(b) for a, b in zip(query, surface)),
                sum(float(a) * float(b) for a, b in zip(query, contextual)),
            )
            scored.append((concept.concept_id, score))
        result[case.case_id] = _hits(scored, top_k)
    return result


def _scoped_concepts(
    case: ProbeCase,
    concepts: tuple[CatalogConcept, ...],
) -> tuple[CatalogConcept, ...]:
    return tuple(concept for concept in concepts if _in_scope(case, concept))


def _in_scope(case: ProbeCase, concept: CatalogConcept) -> bool:
    if case.attribute_scope is not None and concept.attribute is not case.attribute_scope:
        return False
    if (
        case.category_scope is not None
        and concept.category_scope is not None
        and concept.category_scope != case.category_scope
    ):
        return False
    return True


def _hits(
    scored: Sequence[tuple[str, float]],
    top_k: int,
    *,
    presorted: bool = False,
) -> tuple[ConceptHit, ...]:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    best_by_id: dict[str, float] = defaultdict(lambda: -math.inf)
    for concept_id, score in scored:
        if score > best_by_id[concept_id]:
            best_by_id[concept_id] = score
    ranked = (
        list(scored)
        if presorted and len(best_by_id) == len(scored)
        else sorted(best_by_id.items(), key=lambda item: (-item[1], item[0]))
    )
    hits = tuple(
        ConceptHit(concept_id=concept_id, score=score, rank=rank)
        for rank, (concept_id, score) in enumerate(ranked[:top_k], start=1)
    )
    for hit in hits:
        hit.validate()
    return hits
