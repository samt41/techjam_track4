from __future__ import annotations

from dataclasses import dataclass

from starter.shopping_agent.models import (
    Attribute,
    ProductCandidate,
    RetrievalRoute,
    RouteEvidence,
    ShoppingIntent,
    Strength,
)
from starter.shopping_agent.search_backend import (
    ProductSearchBackend,
    SearchRequest,
    StructuredFilter,
)


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
        route_limit: int = 1_000,
        route_work_limit: int = 250_000,
    ) -> None:
        self._route_limit = route_limit
        self._route_work_limit = route_work_limit

    def strict(
        self,
        intent: ShoppingIntent,
        top_k: int = 10,
    ) -> tuple[PlannedSearch, ...]:
        filters = tuple(
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


def execute_search_plan(
    backend: ProductSearchBackend,
    plan: PlannedSearch,
) -> tuple[ProductCandidate, ...]:
    result = backend.search(plan.request)
    route_weight = _ROUTE_WEIGHTS[plan.request.route]
    return tuple(
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
