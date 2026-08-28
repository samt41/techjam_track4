from __future__ import annotations

from starter.shopping_agent.models import (
    PreferenceConstraint,
    RankedRecommendation,
    TurnResponse,
)
from starter.shopping_agent.search_backend import ProductSearchBackend


class ResponseValidator:
    def __init__(self, backend: ProductSearchBackend) -> None:
        self._backend = backend

    def validate(
        self,
        recommendations: tuple[RankedRecommendation, ...],
        top_k: int,
    ) -> tuple[RankedRecommendation, ...]:
        valid: list[RankedRecommendation] = []
        seen: set[str] = set()
        for recommendation in recommendations:
            if (
                recommendation.parent_asin in seen
                or not self._backend.contains_product(recommendation.parent_asin)
            ):
                continue
            seen.add(recommendation.parent_asin)
            valid.append(recommendation)
            if len(valid) >= top_k:
                break
        return tuple(valid)


def recommendation_message(
    recommendations: tuple[RankedRecommendation, ...],
    constraints: tuple[PreferenceConstraint, ...],
    clarification_prompt: str | None,
) -> str:
    message = "Here are the strongest matches for your current preferences."
    relaxed_ids = {
        recommendation.relaxed_constraint_id
        for recommendation in recommendations
        if recommendation.relaxed_constraint_id is not None
    }
    relaxed_attributes = tuple(dict.fromkeys(
        constraint.attribute.value
        for constraint in constraints
        if constraint.constraint_id in relaxed_ids
    ))
    if relaxed_attributes:
        requirements = ", ".join(relaxed_attributes)
        message += (
            f" The final options are near matches that relax your {requirements} "
            "requirement."
        )
    if clarification_prompt is not None:
        message += f" {clarification_prompt}"
    return message


def response_payload(response: TurnResponse) -> dict[str, object]:
    return {
        "message": response.message,
        "ask_attribute": (
            None if response.ask_attribute is None else response.ask_attribute.value
        ),
        "recommendations": [
            {"parent_asin": recommendation.parent_asin}
            for recommendation in response.recommendations
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }
