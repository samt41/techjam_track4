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


# Products fetch and belief scoring are linear in the candidate pool, so the
# whole SQL-shortlisted strict population is scored — the SQLite backend exists
# precisely so recall is not truncated to a small set. Only the quadratic
# entropy question model is separately bounded (see clarification._POPULATION_CAP).
# A generous safety ceiling still guards against a pathological unfiltered route.
_POPULATION_CAP = 5_000


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
        self._scored_cache: tuple[object, ...] | None = None

    def rank(
        self,
        candidates: tuple[ProductCandidate, ...],
        intent: ShoppingIntent,
        shown_product_ids: frozenset[str],
        top_k: int,
        profile: UserProfile | None = None,
    ) -> tuple[RankedRecommendation, ...]:
        active_profile = profile or self._profile
        eligible, posterior_by_id, contributions_by_id = self._scored(
            candidates, intent, active_profile
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

    def strict_population(
        self,
        candidates: tuple[ProductCandidate, ...],
        intent: ShoppingIntent,
        profile: UserProfile | None = None,
    ) -> tuple[tuple[float, ProductRecord], ...]:
        """Preliminary strict belief population as (posterior, product) pairs.

        Covers the bounded strictly eligible population (highest evidence score
        first) so question estimation sees the posterior distribution rather
        than the final top_k slate.
        """
        active_profile = profile or self._profile
        eligible, posterior_by_id, _ = self._scored(
            candidates, intent, active_profile
        )
        return tuple(
            (posterior_by_id.get(parent_asin, 0.0), product)
            for parent_asin, relaxed_constraint_id, _, product, _ in eligible
            if relaxed_constraint_id is None
        )

    def _scored(
        self,
        candidates: tuple[ProductCandidate, ...],
        intent: ShoppingIntent,
        profile: UserProfile,
    ) -> tuple[
        list[tuple[str, str | None, float, ProductRecord, tuple[RouteEvidence, ...]]],
        dict[str, float],
        dict[str, tuple[tuple[str, float], ...]],
    ]:
        # Memoize so the coordinator's rank() and strict_population() calls on
        # the same candidate objects and intent do not fetch or belief-score
        # twice within one turn. The key is object identity, so the cache MUST
        # retain references to those inputs (see the assignment below): CPython
        # recycles the id() of a freed object, so without a live reference a
        # later turn's new tuple could be allocated at a previous turn's address
        # and score a false cache hit — a nondeterministic cross-run corruption.
        cache_key = (id(candidates), id(intent), id(profile))
        if self._scored_cache is not None and self._scored_cache[0] == cache_key:
            return self._scored_cache[1]

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

        # Bound the materialized population by cheap evidence-only RRF before
        # fetching products or scoring beliefs. Route hits are already ordered,
        # so the tail carries negligible fusion weight.
        evidence_score = {
            parent_asin: sum(item.score / (60.0 + item.rank) for item in evidence)
            for parent_asin, evidence in evidence_by_id.items()
        }
        bounded_ids = sorted(
            evidence_by_id,
            key=lambda parent_asin: (-evidence_score[parent_asin], parent_asin),
        )[:_POPULATION_CAP]

        products = self._backend.get_products(tuple(bounded_ids))
        product_by_id = {product.parent_asin: product for product in products}
        eligible: list[
            tuple[str, str | None, float, ProductRecord, tuple[RouteEvidence, ...]]
        ] = []
        belief_candidates: list[BeliefCandidate] = []
        for parent_asin in bounded_ids:
            product = product_by_id.get(parent_asin)
            if product is None:
                continue
            evidence = tuple(evidence_by_id[parent_asin])
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
            if not self._eligibility_gate.evaluate(
                product,
                applicable_constraints,
            ).eligible:
                continue
            score = evidence_score[parent_asin]
            score += _soft_preference_score(product, intent)
            eligible.append((
                parent_asin,
                relaxed_constraint_id,
                score,
                product,
                evidence,
            ))
            if relaxed_constraint_id is None:
                belief_candidates.append(BeliefCandidate(
                    parent_asin=parent_asin,
                    product=product,
                    route_evidence=evidence,
                    quality_prior=0.0,
                    strictly_eligible=True,
                ))

        posterior_by_id: dict[str, float] = {}
        contributions_by_id: dict[str, tuple[tuple[str, float], ...]] = {}
        if belief_candidates:
            beliefs = self._belief_model.score(
                tuple(belief_candidates),
                intent,
                profile,
            )
            for belief in beliefs:
                posterior_by_id[belief.parent_asin] = belief.posterior
                contributions_by_id[belief.parent_asin] = tuple(
                    (contribution.component, contribution.weighted_log_contribution)
                    for contribution in belief.contributions
                )

        result = (eligible, posterior_by_id, contributions_by_id)
        # Retain the keyed inputs alongside the result so their id() cannot be
        # reused by a later allocation while this entry is live.
        self._scored_cache = (cache_key, result, candidates, intent, profile)
        return result


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
