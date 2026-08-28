from __future__ import annotations

from pathlib import Path
from time import perf_counter

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.coordinator import TurnCoordinator
from starter.shopping_agent.diagnostics import EvaluationTrace
from starter.shopping_agent.local_search_backend import LocalProductSearchBackend
from starter.shopping_agent.models import TurnRecord, UserProfile
from starter.shopping_agent.response import response_payload
from starter.shopping_agent.search_backend import LexicalMode


class Agent:
    """Organizer adapter for the deterministic offline shopping coordinator."""

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        artifact_path: str | Path | None = None,
        lexical_mode: LexicalMode = LexicalMode.AUTO,
        trace: EvaluationTrace | None = None,
        exploration: str = "disabled",
    ) -> None:
        resolved_catalog_path = Path(catalog_path)
        resolved_artifact_path = (
            Path(artifact_path)
            if artifact_path is not None
            else resolved_catalog_path.with_suffix(".artifacts")
        )
        started = perf_counter()
        catalog_index = CatalogIndex(LocalProductSearchBackend.open(
            resolved_catalog_path,
            resolved_artifact_path,
            lexical_mode=lexical_mode,
        ))
        startup_ms = (perf_counter() - started) * 1000.0
        self._coordinator = TurnCoordinator(
            catalog_index,
            trace=trace,
            startup_ms=startup_ms,
            exploration=exploration,
        )

    def reset(self, session_id: str, user_profile: dict[str, object]) -> None:
        self._coordinator.reset(session_id, _profile_from_payload(user_profile))

    def close(self) -> None:
        self._coordinator.close()

    def turn_history(self, session_id: str) -> tuple[TurnRecord, ...]:
        return self._coordinator.turn_history(session_id)

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
