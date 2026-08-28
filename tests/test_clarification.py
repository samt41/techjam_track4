from __future__ import annotations

import unittest

from starter.shopping_agent.clarification import (
    ClarificationPolicy,
    PosteriorQuestionModel,
    QuestionModelConfiguration,
)
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    EvidenceKind,
    PreferenceUpdate,
    ProductRecord,
    QuestionCandidate,
    Strength,
    UpdateAction,
)
from starter.shopping_agent.preference_ledger import PreferenceLedger


CONFIG = QuestionModelConfiguration.default()


def question(attribute: Attribute, score: float = 0.8) -> QuestionCandidate:
    return QuestionCandidate(
        attribute=attribute,
        information_gain=1.0,
        current_entropy=1.0,
        conditional_entropy=0.0,
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


def _product(parent_asin: str, color: str) -> ProductRecord:
    return ProductRecord(
        parent_asin=parent_asin,
        title=parent_asin,
        categories=("Boots",),
        features=("durable",),
        description="boot",
        details=(("color", color),),
        store="Example",
        price=80.0,
        average_rating=4.5,
        rating_number=100,
        searchable_text=f"{color} boot",
    )


def balanced_twenty_population() -> tuple[tuple[float, ProductRecord], ...]:
    """Top ten all black, but the full posterior population is balanced."""
    population: list[tuple[float, ProductRecord]] = []
    for number in range(10):
        population.append((0.06, _product(f"BLACK-{number:02d}", "black")))
    for number in range(10):
        population.append((0.04, _product(f"BLUE-{number:02d}", "blue")))
    return tuple(population)


def choose_from_beliefs(
    population: tuple[tuple[float, ProductRecord], ...],
    final_slate_size: int,
) -> QuestionCandidate:
    candidates = PosteriorQuestionModel(CONFIG).score_population(population)
    return max(
        candidates,
        key=lambda candidate: (candidate.score, candidate.attribute.value),
    )


class PosteriorQuestionModelTest(unittest.TestCase):
    def test_question_uses_preliminary_strict_beliefs_not_final_slate(self) -> None:
        decision = choose_from_beliefs(
            balanced_twenty_population(),
            final_slate_size=10,
        )

        self.assertIs(decision.attribute, Attribute.COLOR)
        self.assertGreater(decision.information_gain, 0.0)

    def test_balanced_partition_has_more_gain_than_skewed(self) -> None:
        model = PosteriorQuestionModel(CONFIG)
        balanced = model.score_population((
            (0.25, _product("A", "black")),
            (0.25, _product("B", "blue")),
            (0.25, _product("C", "black")),
            (0.25, _product("D", "blue")),
        ))
        skewed = model.score_population((
            (0.7, _product("A", "black")),
            (0.1, _product("B", "blue")),
            (0.1, _product("C", "black")),
            (0.1, _product("D", "black")),
        ))
        balanced_color = next(c for c in balanced if c.attribute is Attribute.COLOR)
        skewed_color = next(c for c in skewed if c.attribute is Attribute.COLOR)

        self.assertGreater(
            balanced_color.information_gain,
            skewed_color.information_gain,
        )

    def test_unknown_mass_reduces_coverage(self) -> None:
        model = PosteriorQuestionModel(CONFIG)
        candidates = model.score_population((
            (0.5, _product("A", "black")),
            (0.5, ProductRecord(
                parent_asin="B",
                title="B",
                categories=("Boots",),
                features=("durable",),
                description="boot",
                details=(),
                store="Example",
                price=80.0,
                average_rating=4.5,
                rating_number=100,
                searchable_text="boot",
            )),
        ))
        color = next(c for c in candidates if c.attribute is Attribute.COLOR)

        self.assertAlmostEqual(color.coverage, 0.5)

    def test_conditional_entropy_never_exceeds_current_entropy(self) -> None:
        candidates = PosteriorQuestionModel(CONFIG).score_population(
            balanced_twenty_population()
        )

        self.assertTrue(all(
            candidate.conditional_entropy <= candidate.current_entropy + 1e-9
            for candidate in candidates
        ))

    def test_empty_population_yields_no_candidates(self) -> None:
        self.assertEqual(PosteriorQuestionModel(CONFIG).score_population(()), ())


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
            (question(Attribute.COLOR, 0.9),),
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
                question(Attribute.COLOR, 0.9),
                question(Attribute.MATERIAL, 0.8),
                question(Attribute.SIZE, 0.7),
                question(Attribute.STYLE, 0.6),
            ),
            ledger.intent,
            turn=2,
        )

        self.assertIsNotNone(decision)
        self.assertIs(decision.attribute, Attribute.STYLE)

    def test_policy_does_not_ask_on_final_turn(self) -> None:
        decision = ClarificationPolicy(threshold=0.1).choose(
            (question(Attribute.COLOR),),
            PreferenceLedger().intent,
            turn=10,
        )

        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
