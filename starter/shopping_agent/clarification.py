from __future__ import annotations

import math

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


class QuestionValueEstimator:
    def score(
        self,
        attribute: Attribute,
        weighted_values: tuple[tuple[str | None, float], ...],
    ) -> QuestionCandidate:
        positive_values = tuple(
            (value, max(0.0, weight))
            for value, weight in weighted_values
            if weight > 0.0
        )
        total_weight = sum(weight for _, weight in positive_values)
        if total_weight <= 0.0:
            return QuestionCandidate(
                attribute=attribute,
                information_gain=0.0,
                effective_possibilities=1.0,
                answerability=_ANSWERABILITY.get(attribute, 0.0),
                coverage=0.0,
                relevance=0.0,
                score=-0.05,
                focus_value=None,
            )

        bucket_weights: dict[str, float] = {}
        for value, weight in positive_values:
            bucket = value or "unknown"
            bucket_weights[bucket] = bucket_weights.get(bucket, 0.0) + weight
        probabilities = tuple(
            weight / total_weight for weight in bucket_weights.values()
        )
        entropy = -sum(
            probability * math.log2(probability)
            for probability in probabilities
            if probability > 0.0
        )
        unknown_weight = bucket_weights.get("unknown", 0.0)
        coverage = 1.0 - unknown_weight / total_weight
        answerability = _ANSWERABILITY.get(attribute, 0.0)
        relevance = 1.0
        question_score = (
            entropy * answerability * coverage * relevance - 0.05
        )
        known_buckets = tuple(
            (value, weight)
            for value, weight in bucket_weights.items()
            if value != "unknown"
        )
        focus_value = (
            max(known_buckets, key=lambda item: (item[1], item[0]))[0]
            if known_buckets
            else None
        )
        return QuestionCandidate(
            attribute=attribute,
            information_gain=entropy,
            effective_possibilities=2.0 ** entropy,
            answerability=answerability,
            coverage=coverage,
            relevance=relevance,
            score=question_score,
            focus_value=focus_value,
        )

    def score_candidates(
        self,
        products: tuple[ProductRecord, ...],
        weights: tuple[float, ...],
        intent: ShoppingIntent,
    ) -> tuple[QuestionCandidate, ...]:
        if len(products) != len(weights):
            raise ValueError("products and weights must have equal lengths")
        candidates = tuple(
            self.score(
                attribute,
                tuple(
                    (_attribute_value(product, attribute), weight)
                    for product, weight in zip(products, weights, strict=True)
                ),
            )
            for attribute in _QUESTION_ATTRIBUTES
        )
        return tuple(sorted(
            candidates,
            key=lambda candidate: (-candidate.score, candidate.attribute.value),
        ))


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


def _attribute_value(product: ProductRecord, attribute: Attribute) -> str | None:
    if attribute is Attribute.BRAND:
        return product.store or None
    if attribute is Attribute.FEATURE:
        return product.features[0] if product.features else None
    return next(
        (value for key, value in product.details if key == attribute.value),
        None,
    )
