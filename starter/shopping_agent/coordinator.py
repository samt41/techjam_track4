from __future__ import annotations

from dataclasses import dataclass

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.constraint_extractor import ConstraintExtractor
from starter.shopping_agent.models import TurnResponse, UserProfile
from starter.shopping_agent.preference_ledger import PreferenceLedger
from starter.shopping_agent.ranking import ProductRanker
from starter.shopping_agent.response import ResponseValidator
from starter.shopping_agent.retrieval import CandidateGenerator, RetrievalPlanner


@dataclass(slots=True)
class _SessionState:
    profile: UserProfile
    ledger: PreferenceLedger


class TurnCoordinator:
    def __init__(self, catalog_index: CatalogIndex) -> None:
        self._catalog_index = catalog_index
        self._extractor = ConstraintExtractor(catalog_index)
        self._planner = RetrievalPlanner()
        self._generator = CandidateGenerator(catalog_index)
        self._ranker = ProductRanker(catalog_index)
        self._validator = ResponseValidator(catalog_index)
        self._sessions: dict[str, _SessionState] = {}
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._sessions.clear()
            self._catalog_index.close()
            self._closed = True

    def reset(self, session_id: str, profile: UserProfile) -> None:
        self._sessions[session_id] = _SessionState(
            profile=profile,
            ledger=PreferenceLedger(),
        )

    def respond(
        self,
        session_id: str,
        message: str,
        turn: int,
        top_k: int,
    ) -> TurnResponse:
        if self._closed:
            raise RuntimeError("agent is closed")
        state = self._sessions.get(session_id)
        if state is None:
            raise RuntimeError("reset must be called before respond")
        updates = self._extractor.extract(message, turn, asked_attribute=None)
        intent = state.ledger.apply(updates)
        candidates = tuple(
            candidate
            for plan in self._planner.strict(intent)
            for candidate in self._generator.execute(plan)
        )
        recommendations = self._ranker.rank(
            candidates,
            intent,
            shown_product_ids=frozenset(),
            top_k=top_k,
        )
        recommendations = self._validator.validate(recommendations, top_k)
        return TurnResponse(
            message="Here are the strongest matches for your current preferences.",
            ask_attribute=None,
            recommendations=recommendations,
        )
