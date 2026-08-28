from __future__ import annotations

from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.coordinator import TurnCoordinator
from starter.shopping_agent.diagnostics import EvaluationTrace
from starter.shopping_agent.models import UserProfile
from starter.shopping_agent.response import response_payload


class Agent:
    """Organizer adapter for the deterministic offline shopping coordinator."""

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        trace: EvaluationTrace | None = None,
    ) -> None:
        self._coordinator = TurnCoordinator(
            CatalogIndex.from_path(catalog_path),
            trace=trace,
        )

    def reset(self, session_id: str, user_profile: dict[str, object]) -> None:
        self._coordinator.reset(session_id, _profile_from_payload(user_profile))

    def close(self) -> None:
        self._coordinator.close()

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict[str, object]:
        return response_payload(self._coordinator.respond(
            session_id,
            user_message,
            turn,
            top_k,
        ))


def _profile_from_payload(payload: dict[str, object]) -> UserProfile:
    average_rating = payload.get("average_prior_rating")
    raw_tags = payload.get("preference_tags")
    return UserProfile(
        purchase_frequency=str(payload.get("purchase_frequency") or "unknown"),
        average_prior_rating=(
            None if average_rating in (None, "") else float(average_rating)
        ),
        rating_style=str(payload.get("rating_style") or "unknown"),
        preference_tags=(
            tuple(str(tag) for tag in raw_tags)
            if isinstance(raw_tags, (list, tuple))
            else ()
        ),
        summary=str(payload.get("summary") or ""),
    )
