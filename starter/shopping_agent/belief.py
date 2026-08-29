from __future__ import annotations

import math
import re
from dataclasses import dataclass

from starter.shopping_agent.models import (
    Attribute,
    ProductRecord,
    RouteEvidence,
    ShoppingIntent,
    Strength,
    UserProfile,
)
from starter.shopping_agent.text_normalization import match_key


_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class BeliefConfiguration:
    route_scale: float
    soft_match_likelihood: float
    soft_mismatch_likelihood: float
    unknown_likelihood: float
    feature_likelihood: float
    profile_cap: float
    quality_cap: float
    temperature: float

    def as_dict(self) -> dict[str, float]:
        return {
            "route_scale": self.route_scale,
            "soft_match_likelihood": self.soft_match_likelihood,
            "soft_mismatch_likelihood": self.soft_mismatch_likelihood,
            "unknown_likelihood": self.unknown_likelihood,
            "feature_likelihood": self.feature_likelihood,
            "profile_cap": self.profile_cap,
            "quality_cap": self.quality_cap,
            "temperature": self.temperature,
        }


DEFAULT_BELIEF_CONFIGURATION = BeliefConfiguration(
    route_scale=0.60,
    soft_match_likelihood=0.80,
    soft_mismatch_likelihood=0.12,
    unknown_likelihood=0.40,
    feature_likelihood=0.55,
    profile_cap=0.35,
    quality_cap=0.40,
    temperature=1.0,
)


@dataclass(frozen=True, slots=True)
class BeliefCandidate:
    parent_asin: str
    product: ProductRecord
    route_evidence: tuple[RouteEvidence, ...]
    quality_prior: float
    strictly_eligible: bool


@dataclass(frozen=True, slots=True)
class BeliefContribution:
    component: str
    raw_value: float
    weight: float
    weighted_log_contribution: float


@dataclass(frozen=True, slots=True)
class CandidateBelief:
    parent_asin: str
    contributions: tuple[BeliefContribution, ...]
    total_log_belief: float
    posterior: float


class CandidateBeliefModel:
    def __init__(self, configuration: BeliefConfiguration) -> None:
        self._configuration = configuration

    @property
    def configuration(self) -> BeliefConfiguration:
        return self._configuration

    def score(
        self,
        candidates: tuple[BeliefCandidate, ...],
        intent: ShoppingIntent,
        profile: UserProfile,
    ) -> tuple[CandidateBelief, ...]:
        for candidate in candidates:
            if not candidate.strictly_eligible:
                raise ValueError(
                    "belief model only accepts strictly eligible candidates"
                )
        profile_terms = _grounded_terms(profile)
        contributions_by_id: dict[str, tuple[BeliefContribution, ...]] = {}
        log_belief_by_id: dict[str, float] = {}
        for candidate in candidates:
            contributions = self._contributions(candidate, intent, profile_terms)
            total = sum(
                contribution.weighted_log_contribution
                for contribution in contributions
            )
            if not math.isfinite(total):
                raise ValueError("candidate log belief must be finite")
            contributions_by_id[candidate.parent_asin] = contributions
            log_belief_by_id[candidate.parent_asin] = total

        posteriors = _stable_softmax(
            log_belief_by_id,
            self._configuration.temperature,
        )
        beliefs = tuple(
            CandidateBelief(
                parent_asin=candidate.parent_asin,
                contributions=contributions_by_id[candidate.parent_asin],
                total_log_belief=log_belief_by_id[candidate.parent_asin],
                posterior=posteriors[candidate.parent_asin],
            )
            for candidate in candidates
        )
        return tuple(sorted(
            beliefs,
            key=lambda belief: (-belief.posterior, belief.parent_asin),
        ))

    def _contributions(
        self,
        candidate: BeliefCandidate,
        intent: ShoppingIntent,
        profile_terms: frozenset[str],
    ) -> tuple[BeliefContribution, ...]:
        configuration = self._configuration
        contributions: list[BeliefContribution] = []

        route_score = sum(
            evidence.score / (60.0 + evidence.rank)
            for evidence in candidate.route_evidence
        )
        contributions.append(_contribution(
            "route",
            raw_value=route_score,
            weight=configuration.route_scale,
        ))

        for constraint in intent.active_constraints:
            if constraint.strength is not Strength.SOFT or constraint.excluded:
                continue
            values = _attribute_values(candidate.product, constraint.attribute)
            if not values:
                likelihood = configuration.unknown_likelihood
                component = f"soft:{constraint.attribute.value}:unknown"
            elif _value_matches(constraint.value, values):
                likelihood = configuration.soft_match_likelihood
                component = f"soft:{constraint.attribute.value}:match"
            else:
                likelihood = configuration.soft_mismatch_likelihood
                component = f"soft:{constraint.attribute.value}:mismatch"
            contributions.append(_contribution(
                component,
                raw_value=math.log(likelihood),
                weight=constraint.confidence,
            ))

        candidate_terms = _product_terms(candidate.product)
        grounded = profile_terms & candidate_terms
        profile_raw = (
            math.log(configuration.feature_likelihood) * len(grounded)
        )
        profile_weighted = min(configuration.profile_cap, max(0.0, profile_raw))
        contributions.append(BeliefContribution(
            component="profile",
            raw_value=float(len(grounded)),
            weight=configuration.feature_likelihood,
            weighted_log_contribution=profile_weighted,
        ))

        quality_weighted = min(
            configuration.quality_cap,
            max(0.0, candidate.quality_prior * configuration.quality_cap),
        )
        contributions.append(BeliefContribution(
            component="quality_prior",
            raw_value=candidate.quality_prior,
            weight=configuration.quality_cap,
            weighted_log_contribution=quality_weighted,
        ))
        return tuple(contributions)


def _contribution(
    component: str,
    raw_value: float,
    weight: float,
) -> BeliefContribution:
    return BeliefContribution(
        component=component,
        raw_value=raw_value,
        weight=weight,
        weighted_log_contribution=raw_value * weight,
    )


def _stable_softmax(
    log_belief_by_id: dict[str, float],
    temperature: float,
) -> dict[str, float]:
    if not log_belief_by_id:
        return {}
    scaled = {
        parent_asin: value / temperature
        for parent_asin, value in log_belief_by_id.items()
    }
    maximum = max(scaled.values())
    exponentials = {
        parent_asin: math.exp(value - maximum)
        for parent_asin, value in scaled.items()
    }
    total = sum(exponentials.values())
    if total <= 0.0 or not math.isfinite(total):
        uniform = 1.0 / len(log_belief_by_id)
        return {parent_asin: uniform for parent_asin in log_belief_by_id}
    return {
        parent_asin: value / total
        for parent_asin, value in exponentials.items()
    }


def _attribute_values(
    product: ProductRecord,
    attribute: Attribute,
) -> tuple[str, ...]:
    if attribute is Attribute.CATEGORY:
        return product.categories
    if attribute is Attribute.FEATURE:
        return product.features
    if attribute is Attribute.BRAND:
        return (product.store,) if product.store else ()
    if attribute in (Attribute.OTHER, Attribute.USE_CASE):
        return (product.searchable_text,) if product.searchable_text else ()
    return tuple(
        value
        for key, value in product.details
        if key == attribute.value and value
    )


def _value_matches(value: str, product_values: tuple[str, ...]) -> bool:
    key = match_key(value)
    return any(
        key == product_key
        or key in product_key
        or product_key in key
        for product_value in product_values
        if product_value
        for product_key in (match_key(product_value),)
    )


def _grounded_terms(profile: UserProfile) -> frozenset[str]:
    terms: set[str] = set()
    for tag in profile.preference_tags:
        terms.update(_TOKEN_RE.findall(tag.lower()))
    terms.update(_TOKEN_RE.findall(profile.summary.lower()))
    return frozenset(terms)


def _product_terms(product: ProductRecord) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(product.searchable_text.lower()))
