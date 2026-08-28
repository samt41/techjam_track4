from __future__ import annotations

import unittest

from starter.shopping_agent.clarification import (
    ClarificationPolicy,
    QuestionValueEstimator,
)
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    EvidenceKind,
    PreferenceUpdate,
    QuestionCandidate,
    Strength,
    UpdateAction,
)
from starter.shopping_agent.preference_ledger import PreferenceLedger


def candidate(attribute: Attribute, score: float = 0.8) -> QuestionCandidate:
    return QuestionCandidate(
        attribute=attribute,
        information_gain=1.0,
        effective_possibilities=2.0,
        answerability=1.0,
        coverage=1.0,
        relevance=1.0,
        score=score,
        focus_value=None,
    )


def preference(attribute: Attribute, value: str) -> PreferenceUpdate:
    return PreferenceUpdate(
        action=UpdateAction.SET,
        attribute=attribute,
        operator=ComparisonOperator.EQUALS,
        value=value,
        excluded=False,
        strength=Strength.SOFT,
        confidence=0.80,
        source_turn=1,
        source_text=value,
        evidence_kind=EvidenceKind.PROVISIONAL_PREFERENCE,
        preference_group_id=f"test-{attribute.value}",
    )


class QuestionValueEstimatorTest(unittest.TestCase):
    def test_balanced_attribute_has_more_information_than_skewed_attribute(self) -> None:
        estimator = QuestionValueEstimator()
        balanced = estimator.score(
            Attribute.COLOR,
            weighted_values=(
                ("red", 0.25),
                ("blue", 0.25),
                ("red", 0.25),
                ("blue", 0.25),
            ),
        )
        skewed = estimator.score(
            Attribute.MATERIAL,
            weighted_values=(
                ("cotton", 0.25),
                ("cotton", 0.25),
                ("cotton", 0.25),
                ("linen", 0.25),
            ),
        )

        self.assertGreater(balanced.information_gain, skewed.information_gain)
        self.assertAlmostEqual(balanced.effective_possibilities, 2.0)

    def test_unknown_bucket_reduces_coverage(self) -> None:
        result = QuestionValueEstimator().score(
            Attribute.SIZE,
            weighted_values=(("medium", 0.5), (None, 0.5)),
        )

        self.assertEqual(result.coverage, 0.5)


class ClarificationPolicyTest(unittest.TestCase):
    def test_override_makes_question_attribute_askable_in_new_scope(self) -> None:
        ledger = PreferenceLedger()
        ledger.apply((preference(Attribute.COLOR, "red"),))
        ledger.record_question(Attribute.COLOR)
        ledger.apply((PreferenceUpdate(
            action=UpdateAction.RETRACT_PROVISIONAL,
            attribute=None,
            operator=ComparisonOperator.EQUALS,
            value=None,
            excluded=False,
            strength=Strength.SOFT,
            confidence=0.98,
            source_turn=2,
            source_text="actually",
            evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
            preference_group_id="override",
        ),))

        decision = ClarificationPolicy(threshold=0.1).choose(
            (candidate(Attribute.COLOR, 0.9),),
            ledger.intent,
            turn=2,
        )

        self.assertIsNotNone(decision)
        self.assertIs(decision.attribute, Attribute.COLOR)

    def test_policy_rejects_answered_declined_and_previously_asked_attributes(self) -> None:
        ledger = PreferenceLedger()
        ledger.apply((
            preference(Attribute.COLOR, "red"),
            PreferenceUpdate(
                action=UpdateAction.DECLINE,
                attribute=Attribute.MATERIAL,
                operator=ComparisonOperator.EQUALS,
                value=None,
                excluded=False,
                strength=Strength.SOFT,
                confidence=0.98,
                source_turn=1,
                source_text="no preference",
                evidence_kind=EvidenceKind.CLARIFICATION_ANSWER,
                preference_group_id="test-decline",
            ),
        ))
        ledger.record_question(Attribute.SIZE)

        decision = ClarificationPolicy(threshold=0.1).choose(
            (
                candidate(Attribute.COLOR, 0.9),
                candidate(Attribute.MATERIAL, 0.8),
                candidate(Attribute.SIZE, 0.7),
                candidate(Attribute.STYLE, 0.6),
            ),
            ledger.intent,
            turn=2,
        )

        self.assertIsNotNone(decision)
        self.assertIs(decision.attribute, Attribute.STYLE)

    def test_policy_does_not_ask_on_final_turn(self) -> None:
        decision = ClarificationPolicy(threshold=0.1).choose(
            (candidate(Attribute.COLOR),),
            PreferenceLedger().intent,
            turn=10,
        )

        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
