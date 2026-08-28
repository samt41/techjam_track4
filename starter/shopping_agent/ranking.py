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
        strict_ids: set[str] = set()
        for candidate in candidates:
            if candidate.parent_asin not in self._catalog_index.product_by_id:
                continue
            evidence_by_id.setdefault(candidate.parent_asin, []).extend(
                candidate.evidence
            )
            if candidate.relaxed_constraint_id is None:
                strict_ids.add(candidate.parent_asin)
            else:
                relaxed_by_id.setdefault(
                    candidate.parent_asin,
                    candidate.relaxed_constraint_id,
                )

        ranked: list[RankedRecommendation] = []
        for parent_asin, evidence in evidence_by_id.items():
            product = self._catalog_index.product_by_id[parent_asin]
            strict_eligibility = self._eligibility_gate.evaluate(
                product,
                intent.active_constraints,
            )
            relaxed_constraint_id = None
            if not (parent_asin in strict_ids and strict_eligibility.eligible):
                relaxed_constraint_id = relaxed_by_id.get(parent_asin)
                if relaxed_constraint_id is None:
                    continue
            applicable_constraints = tuple(
                constraint
                for constraint in intent.active_constraints
                if constraint.constraint_id != relaxed_constraint_id
            )
            eligibility = self._eligibility_gate.evaluate(
                product,
                applicable_constraints,
            )
            if not eligibility.eligible:
                continue
            score = sum(item.score / (60.0 + item.rank) for item in evidence)
            score += _soft_preference_score(product, intent)
            ranked.append(RankedRecommendation(
                parent_asin=parent_asin,
                score=score,
                exact_match=relaxed_constraint_id is None,
                relaxed_constraint_id=relaxed_constraint_id,
            ))
        ranked.sort(key=lambda item: (
            item.parent_asin in shown_product_ids,
            -item.score,
            item.parent_asin,
        ))
        strict = [item for item in ranked if item.exact_match]
        exploratory = [item for item in ranked if not item.exact_match]
        if not exploratory or top_k <= 0:
            return tuple(strict[:max(0, top_k)])

        exploratory_target = min(3, max(1, round(top_k * 0.30)))
        strict_target = max(0, top_k - exploratory_target)
        selected = strict[:strict_target]
        selected.extend(exploratory[:exploratory_target])
        if len(selected) < top_k:
            selected_ids = {item.parent_asin for item in selected}
            remaining = (
                item
                for item in (*strict[strict_target:], *exploratory[exploratory_target:])
                if item.parent_asin not in selected_ids
            )
            selected.extend(tuple(remaining)[:top_k - len(selected)])
        return tuple(selected[:top_k])


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
