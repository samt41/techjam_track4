from __future__ import annotations

import math
from dataclasses import dataclass

from starter.shopping_agent.models import (
    Attribute,
    ClarificationDecision,
    ProductRecord,
    QuestionCandidate,
    ShoppingIntent,
)


_QUESTION_ATTRIBUTES = (
    Attribute.COLOR,
    Attribute.MATERIAL,
    Attribute.SIZE,
    Attribute.STYLE,
    Attribute.BRAND,
    Attribute.FEATURE,
)
_ANSWERABILITY = {
    Attribute.COLOR: 0.95,
    Attribute.MATERIAL: 0.90,
    Attribute.SIZE: 0.85,
    Attribute.STYLE: 0.75,
    Attribute.BRAND: 0.65,
    Attribute.FEATURE: 0.50,
}
_PROMPTS = {
    Attribute.COLOR: "Which color would you prefer?",
    Attribute.MATERIAL: "Which material would you prefer?",
    Attribute.SIZE: "Which size should I look for?",
    Attribute.STYLE: "Which style would suit you best?",
    Attribute.BRAND: "Do you have a preferred brand?",
    Attribute.FEATURE: "Which feature matters most to you?",
}
_UNKNOWN = "unknown"
_NO_PREFERENCE = "no_preference"


@dataclass(frozen=True, slots=True)
class QuestionModelConfiguration:
    answerability: dict[Attribute, float]
    decline_probability: float
    response_noise: float
    turn_cost: float
    decision_threshold: float

    @classmethod
    def default(cls) -> "QuestionModelConfiguration":
        return cls(
            answerability=dict(_ANSWERABILITY),
            decline_probability=0.15,
            response_noise=0.05,
            turn_cost=0.05,
            decision_threshold=0.15,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "decline_probability": self.decline_probability,
            "response_noise": self.response_noise,
            "turn_cost": self.turn_cost,
            "decision_threshold": self.decision_threshold,
        }


class PosteriorQuestionModel:
    def __init__(self, configuration: QuestionModelConfiguration) -> None:
        self._configuration = configuration

    def score_population(
        self,
        population: tuple[tuple[float, ProductRecord], ...],
    ) -> tuple[QuestionCandidate, ...]:
        total_mass = sum(mass for mass, _ in population)
        if total_mass <= 0.0:
            return ()
        normalized = tuple(
            (mass / total_mass, product) for mass, product in population
        )
        candidates = tuple(
            self._score_attribute(attribute, normalized)
            for attribute in _QUESTION_ATTRIBUTES
        )
        return tuple(sorted(
            candidates,
            key=lambda candidate: (-candidate.score, candidate.attribute.value),
        ))

    def _score_attribute(
        self,
        attribute: Attribute,
        population: tuple[tuple[float, ProductRecord], ...],
    ) -> QuestionCandidate:
        configuration = self._configuration
        # Bucket posterior mass by canonical attribute value (or unknown).
        value_mass: dict[str, float] = {}
        for posterior, product in population:
            value = _attribute_value(product, attribute) or _UNKNOWN
            value_mass[value] = value_mass.get(value, 0.0) + posterior
        unknown_mass = value_mass.get(_UNKNOWN, 0.0)
        known_mass = 1.0 - unknown_mass
        coverage = known_mass
        answerability = configuration.answerability.get(attribute, 0.0)

        current_entropy = _entropy(
            tuple(posterior for posterior, _ in population)
        )

        known_values = tuple(
            value for value in value_mass if value != _UNKNOWN
        )
        if not known_values or known_mass <= 0.0:
            return QuestionCandidate(
                attribute=attribute,
                information_gain=0.0,
                current_entropy=current_entropy,
                conditional_entropy=current_entropy,
                effective_possibilities=1.0,
                answerability=answerability,
                coverage=coverage,
                relevance=1.0,
                score=-configuration.turn_cost,
                focus_value=None,
            )

        # Answer distribution: decline keeps the current posterior; the rest of
        # the mass is split across known values in proportion to their mass.
        answer_probability: dict[str, float] = {
            _NO_PREFERENCE: configuration.decline_probability,
        }
        remaining = 1.0 - configuration.decline_probability
        for value in known_values:
            answer_probability[value] = remaining * (value_mass[value] / known_mass)

        conditional_entropy = 0.0
        for answer, probability in answer_probability.items():
            if probability <= 0.0:
                continue
            conditional_posteriors = self._condition(
                population,
                attribute,
                answer,
            )
            conditional_entropy += probability * _entropy(conditional_posteriors)

        information_gain = max(0.0, current_entropy - conditional_entropy)
        score = (
            information_gain * answerability * coverage
            - configuration.turn_cost
        )
        focus_value = max(
            known_values,
            key=lambda value: (value_mass[value], value),
        )
        return QuestionCandidate(
            attribute=attribute,
            information_gain=information_gain,
            current_entropy=current_entropy,
            conditional_entropy=conditional_entropy,
            effective_possibilities=2.0 ** information_gain,
            answerability=answerability,
            coverage=coverage,
            relevance=1.0,
            score=score,
            focus_value=focus_value,
        )

    def _condition(
        self,
        population: tuple[tuple[float, ProductRecord], ...],
        attribute: Attribute,
        answer: str,
    ) -> tuple[float, ...]:
        if answer == _NO_PREFERENCE:
            return tuple(posterior for posterior, _ in population)
        noise = self._configuration.response_noise
        weighted: list[float] = []
        for posterior, product in population:
            value = _attribute_value(product, attribute)
            if value is None:
                likelihood = noise
            elif value == answer or answer in value or value in answer:
                likelihood = 1.0 - noise
            else:
                likelihood = noise
            weighted.append(posterior * likelihood)
        total = sum(weighted)
        if total <= 0.0:
            return tuple(posterior for posterior, _ in population)
        return tuple(value / total for value in weighted)


class ClarificationPolicy:
    def __init__(self, threshold: float = 0.15) -> None:
        self._threshold = threshold

    def choose(
        self,
        candidates: tuple[QuestionCandidate, ...],
        intent: ShoppingIntent,
        turn: int,
    ) -> ClarificationDecision | None:
        if turn >= 10:
            return None
        unavailable = set(intent.declined_attributes)
        unavailable.update(intent.asked_attributes)
        unavailable.update(
            constraint.attribute for constraint in intent.active_constraints
        )
        eligible = tuple(
            candidate
            for candidate in candidates
            if candidate.attribute not in unavailable
            and candidate.coverage > 0.0
            and candidate.information_gain > 0.0
            and candidate.score >= self._threshold
        )
        if not eligible:
            return None
        best = min(
            eligible,
            key=lambda candidate: (-candidate.score, candidate.attribute.value),
        )
        return ClarificationDecision(
            attribute=best.attribute,
            prompt=_PROMPTS[best.attribute],
            expected_information_gain=best.information_gain,
        )


def _entropy(distribution: tuple[float, ...]) -> float:
    total = sum(distribution)
    if total <= 0.0:
        return 0.0
    entropy = 0.0
    for value in distribution:
        if value <= 0.0:
            continue
        probability = value / total
        entropy -= probability * math.log2(probability)
    return entropy


def _attribute_value(product: ProductRecord, attribute: Attribute) -> str | None:
    if attribute is Attribute.BRAND:
        return product.store or None
    if attribute is Attribute.FEATURE:
        return product.features[0] if product.features else None
    return next(
        (value for key, value in product.details if key == attribute.value),
        None,
    )
