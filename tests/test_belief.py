from __future__ import annotations

import unittest

from starter.shopping_agent.belief import (
    BeliefCandidate,
    BeliefConfiguration,
    CandidateBeliefModel,
)
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    ConstraintStatus,
    EvidenceKind,
    PreferenceConstraint,
    ProductRecord,
    RetrievalRoute,
    RouteEvidence,
    ShoppingIntent,
    Strength,
    UserProfile,
)


TEST_CONFIG = BeliefConfiguration(
    route_scale=1.0,
    soft_match_likelihood=0.80,
    soft_mismatch_likelihood=0.10,
    unknown_likelihood=0.40,
    feature_likelihood=0.60,
    profile_cap=0.50,
    quality_cap=0.50,
    temperature=1.0,
)

PROFILE = UserProfile(
    purchase_frequency="monthly",
    average_prior_rating=4.2,
    rating_style="selective",
    preference_tags=("durable",),
    summary="Prefers durable products.",
)


def product(
    parent_asin: str,
    *,
    color: str | None = "black",
    material: str = "leather",
    text: str = "durable everyday boot",
) -> ProductRecord:
    details = [("material", material)]
    if color is not None:
        details.insert(0, ("color", color))
    return ProductRecord(
        parent_asin=parent_asin,
        title=parent_asin,
        categories=("Boots",),
        features=("durable",),
        description="Everyday boot",
        details=tuple(details),
        store="Example",
        price=80.0,
        average_rating=4.5,
        rating_number=100,
        searchable_text=text,
    )


def candidate(
    parent_asin: str,
    *,
    color: str | None = "black",
    material: str = "leather",
    quality_prior: float = 0.5,
    strictly_eligible: bool = True,
    text: str = "durable everyday boot",
) -> BeliefCandidate:
    return BeliefCandidate(
        parent_asin=parent_asin,
        product=product(parent_asin, color=color, material=material, text=text),
        route_evidence=(RouteEvidence(RetrievalRoute.EXACT_FTS, rank=1, score=1.2),),
        quality_prior=quality_prior,
        strictly_eligible=strictly_eligible,
    )


def belief_candidates() -> tuple[BeliefCandidate, ...]:
    return (
        candidate("BLACK-1", color="black"),
        candidate("BLUE-1", color="blue"),
        candidate("UNKNOWN-1", color=None),
    )


def _constraint(
    attribute: Attribute,
    value: str,
    *,
    strength: Strength,
    evidence_kind: EvidenceKind,
) -> PreferenceConstraint:
    return PreferenceConstraint(
        constraint_id=f"c:{attribute.value}:{value}",
        attribute=attribute,
        operator=ComparisonOperator.EQUALS,
        value=value,
        excluded=False,
        strength=strength,
        confidence=0.80 if strength is Strength.SOFT else 0.98,
        source_turn=1,
        source_text=value,
        evidence_kind=evidence_kind,
        preference_group_id=f"g:{attribute.value}",
        status=ConstraintStatus.ACTIVE,
    )


def _intent(constraints: tuple[PreferenceConstraint, ...]) -> ShoppingIntent:
    return ShoppingIntent(
        active_constraints=constraints,
        constraint_history=constraints,
        weighted_concepts=(),
        declined_attributes=frozenset(),
        asked_attributes=(),
        intent_version=1,
    )


def soft_color_intent(value: str) -> ShoppingIntent:
    return _intent((
        _constraint(
            Attribute.COLOR,
            value,
            strength=Strength.SOFT,
            evidence_kind=EvidenceKind.PROVISIONAL_PREFERENCE,
        ),
    ))


def hard_material_intent(value: str) -> ShoppingIntent:
    return _intent((
        _constraint(
            Attribute.MATERIAL,
            value,
            strength=Strength.HARD,
            evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
        ),
    ))


def hard_ineligible_candidate() -> BeliefCandidate:
    return candidate("INELIGIBLE-1", material="canvas", strictly_eligible=False)


class CandidateBeliefModelTest(unittest.TestCase):
    def test_candidate_beliefs_normalize_and_explain_components(self) -> None:
        beliefs = CandidateBeliefModel(TEST_CONFIG).score(
            candidates=belief_candidates(),
            intent=soft_color_intent("black"),
            profile=PROFILE,
        )

        self.assertAlmostEqual(sum(item.posterior for item in beliefs), 1.0)
        self.assertTrue(all(item.contributions for item in beliefs))

    def test_belief_model_never_receives_hard_ineligible_product(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly eligible"):
            CandidateBeliefModel(TEST_CONFIG).score(
                candidates=(hard_ineligible_candidate(),),
                intent=hard_material_intent("leather"),
                profile=PROFILE,
            )

    def test_matching_soft_evidence_outranks_mismatch(self) -> None:
        beliefs = CandidateBeliefModel(TEST_CONFIG).score(
            candidates=belief_candidates(),
            intent=soft_color_intent("black"),
            profile=PROFILE,
        )
        posterior_by_id = {item.parent_asin: item.posterior for item in beliefs}

        self.assertGreater(posterior_by_id["BLACK-1"], posterior_by_id["BLUE-1"])
        self.assertGreater(posterior_by_id["BLACK-1"], posterior_by_id["UNKNOWN-1"])
        self.assertGreater(posterior_by_id["UNKNOWN-1"], posterior_by_id["BLUE-1"])

    def test_posteriors_are_finite_and_sum_to_one_with_zero_signal(self) -> None:
        beliefs = CandidateBeliefModel(TEST_CONFIG).score(
            candidates=(candidate("A"), candidate("B")),
            intent=_intent(()),
            profile=PROFILE,
        )

        self.assertAlmostEqual(sum(item.posterior for item in beliefs), 1.0)
        self.assertTrue(all(0.0 <= item.posterior <= 1.0 for item in beliefs))

    def test_ties_break_by_product_id(self) -> None:
        beliefs = CandidateBeliefModel(TEST_CONFIG).score(
            candidates=(candidate("B-2"), candidate("A-1")),
            intent=_intent(()),
            profile=PROFILE,
        )

        self.assertEqual([item.parent_asin for item in beliefs], ["A-1", "B-2"])

    def test_profile_contribution_is_clamped_to_configured_cap(self) -> None:
        strong_profile = UserProfile(
            purchase_frequency="daily",
            average_prior_rating=5.0,
            rating_style="generous",
            preference_tags=("durable", "everyday", "boot"),
            summary="durable everyday boot",
        )
        beliefs = CandidateBeliefModel(TEST_CONFIG).score(
            candidates=(candidate("A"),),
            intent=_intent(()),
            profile=strong_profile,
        )
        profile_contributions = [
            contribution
            for belief in beliefs
            for contribution in belief.contributions
            if contribution.component == "profile"
        ]

        self.assertTrue(profile_contributions)
        self.assertLessEqual(
            profile_contributions[0].weighted_log_contribution,
            TEST_CONFIG.profile_cap + 1e-9,
        )

    def test_direct_session_evidence_outranks_maximum_profile_prior(self) -> None:
        matching_profile = UserProfile(
            purchase_frequency="daily",
            average_prior_rating=5.0,
            rating_style="generous",
            preference_tags=("blue",),
            summary="blue",
        )
        beliefs = CandidateBeliefModel(TEST_CONFIG).score(
            candidates=(
                candidate("BLACK-1", color="black", text="black boot"),
                candidate("BLUE-1", color="blue", text="blue boot"),
            ),
            intent=soft_color_intent("black"),
            profile=matching_profile,
        )
        posterior_by_id = {item.parent_asin: item.posterior for item in beliefs}

        self.assertGreater(posterior_by_id["BLACK-1"], posterior_by_id["BLUE-1"])


if __name__ == "__main__":
    unittest.main()
