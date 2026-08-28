from __future__ import annotations

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    EligibilityDecision,
    PreferenceConstraint,
    ProductCandidate,
    ProductRecord,
    RankedRecommendation,
    RouteEvidence,
    ShoppingIntent,
    Strength,
)


class EligibilityGate:
    def evaluate(
        self,
        product: ProductRecord,
        constraints: tuple[PreferenceConstraint, ...],
    ) -> EligibilityDecision:
        reasons: list[str] = []
        for constraint in constraints:
            if constraint.strength is not Strength.HARD:
                continue
            matches = _matches(product, constraint)
            violates = matches if constraint.excluded else not matches
            if violates:
                prefix = "excluded" if constraint.excluded else "required"
                reasons.append(
                    f"{prefix}:{constraint.attribute.value}:{constraint.value}"
                )
        return EligibilityDecision(
            eligible=not reasons,
            rejection_reasons=tuple(reasons),
        )


class ProductRanker:
    def __init__(
        self,
        catalog_index: CatalogIndex,
        eligibility_gate: EligibilityGate | None = None,
    ) -> None:
        self._catalog_index = catalog_index
        self._eligibility_gate = eligibility_gate or EligibilityGate()

    def rank(
        self,
        candidates: tuple[ProductCandidate, ...],
        intent: ShoppingIntent,
        shown_product_ids: frozenset[str],
        top_k: int,
    ) -> tuple[RankedRecommendation, ...]:
        evidence_by_id: dict[str, list[RouteEvidence]] = {}
        relaxed_by_id: dict[str, str | None] = {}
        for candidate in candidates:
            if candidate.parent_asin not in self._catalog_index.product_by_id:
                continue
            evidence_by_id.setdefault(candidate.parent_asin, []).extend(
                candidate.evidence
            )
            if candidate.relaxed_constraint_id is not None:
                relaxed_by_id[candidate.parent_asin] = candidate.relaxed_constraint_id

        ranked: list[RankedRecommendation] = []
        for parent_asin, evidence in evidence_by_id.items():
            product = self._catalog_index.product_by_id[parent_asin]
            eligibility = self._eligibility_gate.evaluate(
                product,
                intent.active_constraints,
            )
            if not eligibility.eligible:
                continue
            score = sum(item.score / (60.0 + item.rank) for item in evidence)
            score += _soft_preference_score(product, intent)
            ranked.append(RankedRecommendation(
                parent_asin=parent_asin,
                score=score,
                exact_match=True,
                relaxed_constraint_id=relaxed_by_id.get(parent_asin),
            ))
        ranked.sort(key=lambda item: (
            item.parent_asin in shown_product_ids,
            -item.score,
            item.parent_asin,
        ))
        return tuple(ranked[:max(0, top_k)])


def _matches(product: ProductRecord, constraint: PreferenceConstraint) -> bool:
    if constraint.attribute is Attribute.BUDGET:
        if product.price is None:
            return False
        boundary = float(constraint.value)
        if constraint.operator is ComparisonOperator.LESS_THAN_OR_EQUAL:
            return product.price <= boundary
        if constraint.operator is ComparisonOperator.GREATER_THAN_OR_EQUAL:
            return product.price >= boundary
        return product.price == boundary

    values = _product_values(product, constraint.attribute)
    return any(
        constraint.value == value
        or constraint.value in value
        or value in constraint.value
        for value in values
        if value
    )


def _product_values(product: ProductRecord, attribute: Attribute) -> tuple[str, ...]:
    if attribute is Attribute.CATEGORY:
        return product.categories
    if attribute is Attribute.FEATURE:
        return product.features
    if attribute is Attribute.BRAND:
        return (product.store,)
    if attribute in (Attribute.OTHER, Attribute.USE_CASE):
        return (product.searchable_text,)
    return tuple(value for key, value in product.details if key == attribute.value)


def _soft_preference_score(product: ProductRecord, intent: ShoppingIntent) -> float:
    score = 0.0
    for constraint in intent.active_constraints:
        if constraint.strength is Strength.SOFT:
            matches = _matches(product, constraint)
            if matches != constraint.excluded:
                score += 0.01 * constraint.confidence
    return score
