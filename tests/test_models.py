from __future__ import annotations

import unittest

from starter.shopping_agent.models import (
    Attribute,
    ClarificationDecision,
    ComparisonOperator,
    ConstraintStatus,
    EligibilityDecision,
    PreferenceConstraint,
    ProductCandidate,
    ProductRecord,
    PreferenceUpdate,
    QuestionCandidate,
    RankedRecommendation,
    RetrievalPlan,
    RetrievalRoute,
    RouteEvidence,
    Strength,
    ShoppingIntent,
    TurnResponse,
    UpdateAction,
    UserProfile,
    WeightedConcept,
)


class PreferenceConstraintTest(unittest.TestCase):
    def test_hard_constraint_requires_high_confidence(self) -> None:
        constraint = PreferenceConstraint(
            constraint_id="c1",
            attribute=Attribute.MATERIAL,
            operator=ComparisonOperator.EQUALS,
            value="leather",
            excluded=False,
            strength=Strength.HARD,
            confidence=0.89,
            source_turn=1,
            source_text="must be leather",
            status=ConstraintStatus.ACTIVE,
        )

        with self.assertRaisesRegex(ValueError, "hard constraint"):
            constraint.validate()

    def test_constraint_confidence_must_be_a_probability(self) -> None:
        constraint = PreferenceConstraint(
            constraint_id="c2",
            attribute=Attribute.COLOR,
            operator=ComparisonOperator.EQUALS,
            value="blue",
            excluded=False,
            strength=Strength.SOFT,
            confidence=1.01,
            source_turn=1,
            source_text="prefer blue",
            status=ConstraintStatus.ACTIVE,
        )

        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            constraint.validate()

    def test_retrieval_and_response_types_have_fixed_nested_values(self) -> None:
        evidence = RouteEvidence(route=RetrievalRoute.EXACT_FTS, rank=1, score=0.75)
        plan = RetrievalPlan(
            route=RetrievalRoute.EXACT_FTS,
            query_terms=("winter", "boot"),
            attribute=None,
            attribute_value=None,
            required_constraint_ids=("c1",),
            relaxed_constraint_ids=(),
            limit=100,
        )
        candidate = ProductCandidate(
            parent_asin="BOOT-1",
            evidence=(evidence,),
            relaxed_constraint_id=None,
        )
        eligibility = EligibilityDecision(eligible=True, rejection_reasons=())
        clarification = ClarificationDecision(
            attribute=Attribute.MATERIAL,
            prompt="Which material would you prefer?",
            expected_information_gain=0.8,
        )
        recommendation = RankedRecommendation(
            parent_asin=candidate.parent_asin,
            score=0.75,
            exact_match=eligibility.eligible,
            relaxed_constraint_id=None,
        )
        response = TurnResponse(
            message=clarification.prompt,
            ask_attribute=clarification.attribute,
            recommendations=(recommendation,),
        )

        self.assertEqual(plan.limit, 100)
        self.assertEqual(response.recommendations[0].parent_asin, "BOOT-1")

    def test_catalog_and_intent_types_use_explicit_fields(self) -> None:
        profile = UserProfile(
            purchase_frequency="monthly",
            average_prior_rating=4.2,
            rating_style="selective",
            preference_tags=("durable",),
            summary="Prefers durable products.",
        )
        product = ProductRecord(
            parent_asin="BOOT-1",
            title="Black winter boot",
            categories=("clothing", "boots"),
            features=("water resistant",),
            description="Warm winter boot",
            details=(("material", "leather"),),
            store="Example",
            price=89.0,
            average_rating=4.4,
            rating_number=12,
            searchable_text="black winter boot water resistant leather",
        )
        update = PreferenceUpdate(
            action=UpdateAction.SET,
            attribute=Attribute.MATERIAL,
            operator=ComparisonOperator.EQUALS,
            value="leather",
            excluded=False,
            strength=Strength.HARD,
            confidence=0.98,
            source_turn=1,
            source_text="must be leather",
        )
        concept = WeightedConcept(value="winter", weight=0.8, source_turn=1)
        intent = ShoppingIntent(
            active_constraints=(),
            constraint_history=(),
            weighted_concepts=(concept,),
            declined_attributes=frozenset(),
            asked_attributes=(),
            intent_version=0,
        )
        question = QuestionCandidate(
            attribute=Attribute.COLOR,
            information_gain=1.0,
            effective_possibilities=2.0,
            answerability=1.0,
            coverage=0.9,
            relevance=0.8,
            score=0.72,
            focus_value=None,
        )

        self.assertEqual(profile.preference_tags, ("durable",))
        self.assertEqual(product.details[0], ("material", "leather"))
        self.assertIs(update.action, UpdateAction.SET)
        self.assertEqual(intent.weighted_concepts, (concept,))
        self.assertEqual(question.effective_possibilities, 2.0)


if __name__ == "__main__":
    unittest.main()
