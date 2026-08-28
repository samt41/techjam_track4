from __future__ import annotations

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import (
    Attribute,
    ProductCandidate,
    RetrievalPlan,
    RetrievalRoute,
    RouteEvidence,
    ShoppingIntent,
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


class RetrievalPlanner:
    def __init__(self, route_limit: int = 200) -> None:
        self._route_limit = route_limit

    def strict(self, intent: ShoppingIntent) -> tuple[RetrievalPlan, ...]:
        required_ids = tuple(
            constraint.constraint_id for constraint in intent.active_constraints
        )
        plans: list[RetrievalPlan] = []
        positive_constraints = tuple(
            constraint
            for constraint in intent.active_constraints
            if not constraint.excluded
        )
        for constraint in positive_constraints:
            if constraint.attribute is Attribute.BUDGET:
                continue
            plans.append(RetrievalPlan(
                route=RetrievalRoute.METADATA,
                query_terms=(constraint.value,),
                attribute=constraint.attribute,
                attribute_value=constraint.value,
                required_constraint_ids=required_ids,
                relaxed_constraint_ids=(),
                limit=self._route_limit,
            ))

        exact_terms = tuple(dict.fromkeys(
            constraint.value for constraint in positive_constraints
        ))
        if not exact_terms:
            exact_terms = tuple(dict.fromkeys(
                concept.value for concept in intent.weighted_concepts
            ))
        if exact_terms:
            plans.append(RetrievalPlan(
                route=RetrievalRoute.EXACT_FTS,
                query_terms=exact_terms,
                attribute=None,
                attribute_value=None,
                required_constraint_ids=required_ids,
                relaxed_constraint_ids=(),
                limit=self._route_limit,
            ))
            expanded_terms = tuple(dict.fromkeys(
                term
                for exact_term in exact_terms
                for term in (exact_term, *_EXPANSIONS.get(exact_term, ()))
            ))
            plans.append(RetrievalPlan(
                route=RetrievalRoute.EXPANDED_FTS,
                query_terms=expanded_terms,
                attribute=None,
                attribute_value=None,
                required_constraint_ids=required_ids,
                relaxed_constraint_ids=(),
                limit=self._route_limit,
            ))

        category = next(
            (
                constraint.value
                for constraint in reversed(positive_constraints)
                if constraint.attribute is Attribute.CATEGORY
            ),
            None,
        )
        plans.append(RetrievalPlan(
            route=RetrievalRoute.CATEGORY_FALLBACK,
            query_terms=() if category is None else (category,),
            attribute=Attribute.CATEGORY if category is not None else None,
            attribute_value=category,
            required_constraint_ids=required_ids,
            relaxed_constraint_ids=(),
            limit=self._route_limit,
        ))
        return tuple(plans)

    def counterfactuals(self, intent: ShoppingIntent) -> tuple[RetrievalPlan, ...]:
        return ()


class CandidateGenerator:
    def __init__(self, catalog_index: CatalogIndex) -> None:
        self._catalog_index = catalog_index

    def execute(self, plan: RetrievalPlan) -> tuple[ProductCandidate, ...]:
        if (
            plan.route is RetrievalRoute.METADATA
            and plan.attribute is not None
            and plan.attribute_value is not None
        ):
            products = self._catalog_index.products_for(
                plan.attribute,
                plan.attribute_value,
            )[:plan.limit]
        elif plan.route in (RetrievalRoute.EXACT_FTS, RetrievalRoute.EXPANDED_FTS):
            products = self._catalog_index.search_fts(plan.query_terms, plan.limit)
        else:
            products = self._catalog_index.quality_fallback(
                plan.attribute_value,
                plan.limit,
            )
        relaxed_id = (
            plan.relaxed_constraint_ids[0]
            if len(plan.relaxed_constraint_ids) == 1
            else None
        )
        weight = _ROUTE_WEIGHTS[plan.route]
        return tuple(
            ProductCandidate(
                parent_asin=product.parent_asin,
                evidence=(RouteEvidence(
                    route=plan.route,
                    rank=rank,
                    score=weight,
                ),),
                relaxed_constraint_id=relaxed_id,
            )
            for rank, product in enumerate(products, start=1)
        )
