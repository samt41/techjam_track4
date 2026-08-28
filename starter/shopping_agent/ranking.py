from __future__ import annotations

from starter.shopping_agent.belief import (
    DEFAULT_BELIEF_CONFIGURATION,
    BeliefCandidate,
    BeliefConfiguration,
    CandidateBeliefModel,
)
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
    UserProfile,
)
from starter.shopping_agent.search_backend import ProductSearchBackend


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
        backend: ProductSearchBackend,
        eligibility_gate: EligibilityGate | None = None,
        belief_configuration: BeliefConfiguration | None = None,
        profile: UserProfile | None = None,
    ) -> None:
        self._backend = backend
        self._eligibility_gate = eligibility_gate or EligibilityGate()
        self._belief_model = CandidateBeliefModel(
            belief_configuration or DEFAULT_BELIEF_CONFIGURATION
        )
        self._profile = profile or _NEUTRAL_PROFILE

    def rank(
        self,
        candidates: tuple[ProductCandidate, ...],
        intent: ShoppingIntent,
        shown_product_ids: frozenset[str],
        top_k: int,
        profile: UserProfile | None = None,
    ) -> tuple[RankedRecommendation, ...]:
        active_profile = profile or self._profile
        evidence_by_id: dict[str, list[RouteEvidence]] = {}
        relaxed_by_id: dict[str, str | None] = {}
        strict_ids: set[str] = set()
        for candidate in candidates:
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

        products = self._backend.get_products(tuple(evidence_by_id))
        product_by_id = {product.parent_asin: product for product in products}
        eligible: list[tuple[str, str | None, float, ProductRecord, tuple[RouteEvidence, ...]]] = []
        for parent_asin, evidence in evidence_by_id.items():
            product = product_by_id.get(parent_asin)
            if product is None:
                continue
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
            eligible.append((
                parent_asin,
                relaxed_constraint_id,
                score,
                product,
                tuple(evidence),
            ))

        strict_entries = [entry for entry in eligible if entry[1] is None]
        posterior_by_id, contributions_by_id = self._beliefs(
            strict_entries,
            intent,
            active_profile,
        )
        ranked = [
            RankedRecommendation(
                parent_asin=parent_asin,
                score=score,
                exact_match=relaxed_constraint_id is None,
                relaxed_constraint_id=relaxed_constraint_id,
                posterior=posterior_by_id.get(parent_asin, 0.0),
                belief_contributions=contributions_by_id.get(parent_asin, ()),
            )
            for parent_asin, relaxed_constraint_id, score, _, _ in eligible
        ]
        strict = sorted(
            (item for item in ranked if item.exact_match),
            key=lambda item: (
                item.parent_asin in shown_product_ids,
                -item.posterior,
                -item.score,
                item.parent_asin,
            ),
        )
        exploratory = sorted(
            (item for item in ranked if not item.exact_match),
            key=lambda item: (
                item.parent_asin in shown_product_ids,
                -item.score,
                item.parent_asin,
            ),
        )
        return tuple((*strict, *exploratory)[:max(0, top_k)])

    def _beliefs(
        self,
        strict_entries: list[
            tuple[str, str | None, float, ProductRecord, tuple[RouteEvidence, ...]]
        ],
        intent: ShoppingIntent,
        profile: UserProfile,
    ) -> tuple[dict[str, float], dict[str, tuple[tuple[str, float], ...]]]:
        if not strict_entries:
            return {}, {}
        belief_candidates = tuple(
            BeliefCandidate(
                parent_asin=parent_asin,
                product=product,
                route_evidence=evidence,
                quality_prior=0.0,
                strictly_eligible=True,
            )
            for parent_asin, _, _, product, evidence in strict_entries
        )
        beliefs = self._belief_model.score(
            belief_candidates,
            intent,
            profile,
        )
        posterior_by_id = {
            belief.parent_asin: belief.posterior for belief in beliefs
        }
        contributions_by_id = {
            belief.parent_asin: tuple(
                (contribution.component, contribution.weighted_log_contribution)
                for contribution in belief.contributions
            )
            for belief in beliefs
        }
        return posterior_by_id, contributions_by_id


_NEUTRAL_PROFILE = UserProfile(
    purchase_frequency="unknown",
    average_prior_rating=None,
    rating_style="unknown",
    preference_tags=(),
    summary="",
)


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
