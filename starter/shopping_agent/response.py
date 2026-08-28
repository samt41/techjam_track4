from __future__ import annotations

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import RankedRecommendation, TurnResponse


class ResponseValidator:
    def __init__(self, catalog_index: CatalogIndex) -> None:
        self._catalog_index = catalog_index

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
                or recommendation.parent_asin not in self._catalog_index.product_by_id
            ):
                continue
            seen.add(recommendation.parent_asin)
            valid.append(recommendation)
            if len(valid) >= top_k:
                break
        return tuple(valid)


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
