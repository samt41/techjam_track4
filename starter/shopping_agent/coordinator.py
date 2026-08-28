from __future__ import annotations

from dataclasses import dataclass

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.clarification import (
    ClarificationPolicy,
    QuestionValueEstimator,
)
from starter.shopping_agent.constraint_extractor import ConstraintExtractor
from starter.shopping_agent.models import (
    Attribute,
    RecommendationHistory,
    TurnResponse,
    UserProfile,
)
from starter.shopping_agent.preference_ledger import PreferenceLedger
from starter.shopping_agent.ranking import ProductRanker
from starter.shopping_agent.response import ResponseValidator, recommendation_message
from starter.shopping_agent.retrieval import CandidateGenerator, RetrievalPlanner


@dataclass(slots=True)
class _SessionState:
    profile: UserProfile
    ledger: PreferenceLedger
    history: RecommendationHistory
    last_asked_attribute: Attribute | None


class TurnCoordinator:
    def __init__(self, catalog_index: CatalogIndex) -> None:
        self._catalog_index = catalog_index
        self._extractor = ConstraintExtractor(catalog_index)
        self._planner = RetrievalPlanner()
        self._generator = CandidateGenerator(catalog_index)
        self._ranker = ProductRanker(catalog_index)
        self._validator = ResponseValidator(catalog_index)
        self._question_estimator = QuestionValueEstimator()
        self._clarification_policy = ClarificationPolicy()
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
            history=RecommendationHistory(),
            last_asked_attribute=None,
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
        updates = self._extractor.extract(
            message,
            turn,
            asked_attribute=state.last_asked_attribute,
        )
        state.last_asked_attribute = None
        intent = state.ledger.apply(updates)
        strict_candidates = tuple(
            candidate
            for plan in self._planner.strict(intent)
            for candidate in self._generator.execute(plan)
        )
        shown_product_ids = state.history.shown_for(intent.intent_version)
        recommendations = self._ranker.rank(
            strict_candidates,
            intent,
            shown_product_ids=shown_product_ids,
            top_k=top_k,
        )
        if len(recommendations) < top_k:
            exploratory_candidates = tuple(
                candidate
                for plan in self._planner.counterfactuals(intent)
                for candidate in self._generator.execute(plan)
            )
            recommendations = self._ranker.rank(
                (*strict_candidates, *exploratory_candidates),
                intent,
                shown_product_ids=shown_product_ids,
                top_k=top_k,
            )
        recommendations = self._validator.validate(recommendations, top_k)
        state.history.record(
            intent.intent_version,
            tuple(item.parent_asin for item in recommendations),
        )
        products = tuple(
            self._catalog_index.product_by_id[item.parent_asin]
            for item in recommendations
        )
        question_candidates = self._question_estimator.score_candidates(
            products,
            tuple(max(item.score, 1e-12) for item in recommendations),
            intent,
        )
        clarification = self._clarification_policy.choose(
            question_candidates,
            intent,
            turn,
        )
        if clarification is not None:
            state.ledger.record_question(clarification.attribute)
            state.last_asked_attribute = clarification.attribute
        return TurnResponse(
            message=recommendation_message(
                recommendations,
                intent.active_constraints,
                clarification.prompt if clarification is not None else None,
            ),
            ask_attribute=(
                clarification.attribute if clarification is not None else None
            ),
            recommendations=recommendations,
        )
