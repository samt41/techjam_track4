from __future__ import annotations

from dataclasses import dataclass

from starter.shopping_agent.models import (
    Attribute,
    ConstraintReliability,
    EvidenceKind,
    PreferenceConstraint,
    ProductCandidate,
    RetrievalRoute,
    RouteEvidence,
    ShoppingIntent,
    Strength,
)
from starter.shopping_agent.search_backend import (
    ProductSearchBackend,
    SearchRequest,
    SearchResult,
    StructuredFilter,
)


_FIRM_EVIDENCE = frozenset({
    EvidenceKind.EXPLICIT_REQUIREMENT,
    EvidenceKind.CATEGORY_ANCHOR,
})


_ROUTE_WEIGHTS = {
    RetrievalRoute.METADATA: 1.40,
    RetrievalRoute.EXACT_FTS: 1.20,
    RetrievalRoute.EXPANDED_FTS: 0.80,
    RetrievalRoute.CATEGORY_FALLBACK: 0.25,
    RetrievalRoute.COUNTERFACTUAL: 0.15,
}
_EXPANSIONS = {
    "boots": ("boot", "footwear"),
    "boot": ("boots", "footwear"),
    "shoes": ("shoe", "footwear"),
    "shoe": ("shoes", "footwear"),
    "waterproof": ("water resistant", "weather resistant"),
    "warm": ("insulated", "thermal", "lined"),
}


@dataclass(frozen=True, slots=True)
class PlannedSearch:
    request: SearchRequest
    relaxed_constraint_id: str | None


class RetrievalPlanner:
    def __init__(
        self,
        route_limit: int = 200,
        route_work_limit: int = 250_000,
    ) -> None:
        self._route_limit = route_limit
        self._route_work_limit = route_work_limit

    def strict(
        self,
        intent: ShoppingIntent,
        top_k: int = 10,
    ) -> tuple[PlannedSearch, ...]:
        filters = _hard_filters(intent.active_constraints)
        positive_constraints = tuple(
            constraint
            for constraint in intent.active_constraints
            if not constraint.excluded
            and constraint.attribute is not Attribute.BUDGET
        )
        exact_terms = tuple(dict.fromkeys(
            constraint.value for constraint in positive_constraints
        ))
        if not exact_terms:
            exact_terms = tuple(dict.fromkeys(
                concept.value for concept in intent.weighted_concepts
            ))
        result_limit = max(top_k, self._route_limit)
        routes: list[tuple[RetrievalRoute, tuple[str, ...]]] = [
            (RetrievalRoute.METADATA, ()),
        ]
        if exact_terms:
            routes.append((RetrievalRoute.EXACT_FTS, exact_terms))
            expanded_terms = tuple(dict.fromkeys(
                term
                for exact_term in exact_terms
                for term in (exact_term, *_EXPANSIONS.get(exact_term, ()))
            ))
            routes.append((RetrievalRoute.EXPANDED_FTS, expanded_terms))
        category = next(
            (
                constraint.value
                for constraint in reversed(positive_constraints)
                if constraint.attribute is Attribute.CATEGORY
            ),
            None,
        )
        routes.append((
            RetrievalRoute.CATEGORY_FALLBACK,
            () if category is None else (category,),
        ))
        return tuple(
            PlannedSearch(
                request=SearchRequest(
                    route=route,
                    lexical_terms=query_terms,
                    filters=filters,
                    limit=result_limit,
                    work_limit=self._route_work_limit,
                ),
                relaxed_constraint_id=None,
            )
            for route, query_terms in routes
        )

    def counterfactuals(
        self,
        intent: ShoppingIntent,
        ordered: tuple[ConstraintReliability, ...],
        top_k: int = 10,
    ) -> tuple[PlannedSearch, ...]:
        constraint_by_id = {
            constraint.constraint_id: constraint
            for constraint in intent.active_constraints
        }
        result_limit = max(top_k, self._route_limit)
        return tuple(
            counterfactual_plan(
                intent,
                constraint_by_id[reliability.constraint_id],
                result_limit=result_limit,
                work_limit=self._route_work_limit,
            )
            for reliability in ordered
            if reliability.constraint_id in constraint_by_id
        )


def _hard_filters(
    constraints: tuple[PreferenceConstraint, ...],
) -> tuple[StructuredFilter, ...]:
    return tuple(
        StructuredFilter(
            constraint_id=constraint.constraint_id,
            attribute=constraint.attribute,
            operator=constraint.operator,
            value=constraint.value,
            excluded=constraint.excluded,
            confidence=constraint.confidence,
        )
        for constraint in constraints
        if constraint.strength is Strength.HARD
    )


def build_reliabilities(
    intent: ShoppingIntent,
) -> tuple[ConstraintReliability, ...]:
    """Reliability record for every hard, non-excluded constraint."""
    reliabilities: list[ConstraintReliability] = []
    for constraint in intent.active_constraints:
        if constraint.strength is not Strength.HARD or constraint.excluded:
            continue
        recovered = sum(
            1
            for historical in intent.constraint_history
            if historical.preference_group_id == constraint.preference_group_id
            and historical is not constraint
        )
        reliabilities.append(ConstraintReliability(
            constraint_id=constraint.constraint_id,
            confidence=constraint.confidence,
            evidence_kind=constraint.evidence_kind,
            firm=constraint.evidence_kind in _FIRM_EVIDENCE,
            catalog_coverage=0,
            pool_collapse=False,
            confirmation_count=1,
            recovered_count=recovered,
        ))
    return tuple(reliabilities)


def order_relaxations(
    reliabilities: tuple[ConstraintReliability, ...],
    strict_total: int,
    top_k: int,
) -> tuple[ConstraintReliability, ...]:
    """Reliability-ordered constraints eligible for tail-fill relaxation.

    Firm constraints are protected while any strict match exists; only after
    zero strict matches (and no uncertain relaxation succeeded first) may a firm
    constraint be relaxed as a last resort. Excluded constraints never appear
    because build_reliabilities omits them.
    """
    if strict_total >= top_k:
        return ()
    uncertain = [item for item in reliabilities if not item.firm]
    firm = [item for item in reliabilities if item.firm]
    ordered = _sort_reliabilities(uncertain)
    if strict_total == 0:
        ordered += _sort_reliabilities(firm)
    return tuple(ordered)


def _sort_reliabilities(
    reliabilities: list[ConstraintReliability],
) -> list[ConstraintReliability]:
    return sorted(
        reliabilities,
        key=lambda item: (
            not item.pool_collapse,
            item.confidence,
            item.confirmation_count,
            item.recovered_count,
            item.constraint_id,
        ),
    )


def counterfactual_plan(
    intent: ShoppingIntent,
    relaxed: PreferenceConstraint,
    result_limit: int,
    work_limit: int,
) -> PlannedSearch:
    retained = tuple(
        constraint
        for constraint in intent.active_constraints
        if constraint.constraint_id != relaxed.constraint_id
    )
    query_terms = tuple(dict.fromkeys(
        constraint.value
        for constraint in retained
        if not constraint.excluded
        and constraint.attribute is not Attribute.BUDGET
    ))
    return PlannedSearch(
        request=SearchRequest(
            route=RetrievalRoute.COUNTERFACTUAL,
            lexical_terms=query_terms,
            filters=_hard_filters(retained),
            limit=result_limit,
            work_limit=work_limit,
        ),
        relaxed_constraint_id=relaxed.constraint_id,
    )


def execute_search_plan(
    backend: ProductSearchBackend,
    plan: PlannedSearch,
) -> tuple[ProductCandidate, ...]:
    candidates, _ = execute_search_plan_traced(backend, plan)
    return candidates


def execute_search_plan_traced(
    backend: ProductSearchBackend,
    plan: PlannedSearch,
) -> tuple[tuple[ProductCandidate, ...], "SearchResult"]:
    result = backend.search(plan.request)
    route_weight = _ROUTE_WEIGHTS[plan.request.route]
    candidates = tuple(
        ProductCandidate(
            parent_asin=hit.parent_asin,
            evidence=(RouteEvidence(
                route=plan.request.route,
                rank=hit.rank,
                score=route_weight,
            ),),
            relaxed_constraint_id=plan.relaxed_constraint_id,
        )
        for hit in result.hits
    )
    return candidates, result
