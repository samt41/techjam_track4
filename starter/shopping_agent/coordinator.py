from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.clarification import (
    ClarificationPolicy,
    QuestionValueEstimator,
)
from starter.shopping_agent.constraint_extractor import ConstraintExtractor
from starter.shopping_agent.diagnostics import (
    EvaluationTrace,
    NoOpEvaluationTrace,
    TraceEvent,
    TraceEventType,
    TraceReason,
)
from starter.shopping_agent.models import (
    Attribute,
    RecommendationHistory,
    TurnRecord,
    TurnResponse,
    UserProfile,
    RetrievalRoute,
)
from starter.shopping_agent.preference_ledger import PreferenceLedger
from starter.shopping_agent.ranking import ProductRanker
from starter.shopping_agent.response import ResponseValidator, recommendation_message
from starter.shopping_agent.retrieval import (
    RetrievalPlanner,
    build_reliabilities,
    execute_search_plan,
    order_relaxations,
)


@dataclass(slots=True)
class _SessionState:
    profile: UserProfile
    ledger: PreferenceLedger
    history: RecommendationHistory
    last_asked_attribute: Attribute | None
    turn_history: tuple[TurnRecord, ...]


class TurnCoordinator:
    def __init__(
        self,
        catalog_index: CatalogIndex,
        trace: EvaluationTrace | None = None,
    ) -> None:
        self._catalog_index = catalog_index
        self._extractor = ConstraintExtractor(catalog_index)
        self._planner = RetrievalPlanner()
        self._ranker = ProductRanker(catalog_index.backend)
        self._validator = ResponseValidator(catalog_index.backend)
        self._question_estimator = QuestionValueEstimator()
        self._clarification_policy = ClarificationPolicy()
        self._sessions: dict[str, _SessionState] = {}
        self._closed = False
        self._trace = trace or NoOpEvaluationTrace()

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
            turn_history=(),
        )

    def turn_history(self, session_id: str) -> tuple[TurnRecord, ...]:
        state = self._sessions.get(session_id)
        if state is None:
            raise RuntimeError("reset must be called before reading turn history")
        return state.turn_history

    def respond(
        self,
        session_id: str,
        message: str,
        turn: int,
        top_k: int,
    ) -> TurnResponse:
        started = perf_counter()
        if self._closed:
            raise RuntimeError("agent is closed")
        state = self._sessions.get(session_id)
        if state is None:
            raise RuntimeError("reset must be called before respond")
        dialogue_act = self._extractor.dialogue_act(
            message,
            state.last_asked_attribute,
        )
        before_intent_version = state.ledger.intent.intent_version
        updates = self._extractor.extract(
            message,
            turn,
            asked_attribute=state.last_asked_attribute,
        )
        state.last_asked_attribute = None
        intent = state.ledger.apply(updates)
        strict_candidates_list = []
        for plan in self._planner.strict(intent, top_k):
            route_candidates = execute_search_plan(
                self._catalog_index.backend,
                plan,
            )
            strict_candidates_list.extend(route_candidates)
            self._record(
                session_id,
                turn,
                TraceEventType.ROUTE,
                (
                    TraceReason.STRICT_RESULTS
                    if route_candidates
                    else TraceReason.EMPTY_STRICT_POOL
                ),
                plan.request.route,
                None,
                len(route_candidates),
                0,
                intent.intent_version,
                0.0,
            )
        strict_candidates = tuple(strict_candidates_list)
        candidate_count = len(strict_candidates)
        shown_product_ids = state.history.shown_for(intent.intent_version)
        recommendations = self._ranker.rank(
            strict_candidates,
            intent,
            shown_product_ids=shown_product_ids,
            top_k=top_k,
        )
        if len(recommendations) < top_k:
            recommendations = self._fill_tail(
                session_id,
                turn,
                intent,
                strict_candidates,
                strict_total=len(recommendations),
                shown_product_ids=shown_product_ids,
                top_k=top_k,
            )
        self._record(
            session_id,
            turn,
            TraceEventType.FILTERING,
            TraceReason.ELIGIBILITY_APPLIED,
            None,
            None,
            len(strict_candidates),
            len(recommendations),
            intent.intent_version,
            0.0,
        )
        recommendations = self._validator.validate(recommendations, top_k)
        state.history.record(
            intent.intent_version,
            tuple(item.parent_asin for item in recommendations),
        )
        products = tuple(
            self._catalog_index.get_products(tuple(
                item.parent_asin for item in recommendations
            ))
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
        self._record(
            session_id,
            turn,
            TraceEventType.QUESTION,
            (
                TraceReason.QUESTION_SELECTED
                if clarification is not None
                else TraceReason.QUESTION_SKIPPED
            ),
            None,
            clarification.attribute if clarification is not None else None,
            len(question_candidates),
            len(recommendations),
            intent.intent_version,
            0.0,
        )
        self._record(
            session_id,
            turn,
            TraceEventType.SLATE,
            TraceReason.SLATE_RETURNED,
            None,
            None,
            candidate_count,
            len(recommendations),
            intent.intent_version,
            0.0,
            tuple(item.parent_asin for item in recommendations),
        )
        elapsed_ms = (perf_counter() - started) * 1000.0
        self._record(
            session_id,
            turn,
            TraceEventType.LATENCY,
            TraceReason.TURN_COMPLETED,
            None,
            None,
            candidate_count,
            len(recommendations),
            intent.intent_version,
            elapsed_ms,
        )
        strict_product_ids = tuple(
            item.parent_asin for item in recommendations if item.exact_match
        )
        exploratory_product_ids = tuple(
            item.parent_asin for item in recommendations if not item.exact_match
        )
        relaxed_constraint_ids = tuple(dict.fromkeys(
            item.relaxed_constraint_id
            for item in recommendations
            if item.relaxed_constraint_id is not None
        ))
        state.turn_history = (*state.turn_history, TurnRecord(
            message=message,
            dialogue_act=dialogue_act,
            updates=updates,
            before_intent_version=before_intent_version,
            after_intent_version=intent.intent_version,
            question_attribute=(
                clarification.attribute if clarification is not None else None
            ),
            strict_product_ids=strict_product_ids,
            exploratory_product_ids=exploratory_product_ids,
            relaxed_constraint_ids=relaxed_constraint_ids,
        ))[-10:]
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

    def _fill_tail(
        self,
        session_id: str,
        turn: int,
        intent,
        strict_candidates,
        strict_total: int,
        shown_product_ids,
        top_k: int,
    ):
        ordered = order_relaxations(
            build_reliabilities(intent),
            strict_total=strict_total,
            top_k=top_k,
        )
        combined = list(strict_candidates)
        recommendations = self._ranker.rank(
            tuple(combined),
            intent,
            shown_product_ids=shown_product_ids,
            top_k=top_k,
        )
        for plan in self._planner.counterfactuals(intent, ordered, top_k):
            if len(recommendations) >= top_k:
                break
            counterfactual_candidates = execute_search_plan(
                self._catalog_index.backend,
                plan,
            )
            self._record(
                session_id,
                turn,
                TraceEventType.ROUTE,
                (
                    TraceReason.COUNTERFACTUAL_RESULTS
                    if counterfactual_candidates
                    else TraceReason.SPARSE_STRICT_POOL
                ),
                plan.request.route,
                None,
                len(counterfactual_candidates),
                0,
                intent.intent_version,
                0.0,
            )
            combined.extend(counterfactual_candidates)
            recommendations = self._ranker.rank(
                tuple(combined),
                intent,
                shown_product_ids=shown_product_ids,
                top_k=top_k,
            )
        return recommendations

    def _record(
        self,
        session_id: str,
        turn: int,
        event_type: TraceEventType,
        reason: TraceReason,
        route: RetrievalRoute | None,
        attribute: Attribute | None,
        candidate_count: int,
        recommendation_count: int,
        intent_version: int,
        elapsed_ms: float,
        product_ids: tuple[str, ...] = (),
    ) -> None:
        self._trace.record(TraceEvent(
            session_id=session_id,
            turn=turn,
            event_type=event_type,
            reason=reason,
            route=route,
            attribute=attribute,
            candidate_count=candidate_count,
            recommendation_count=recommendation_count,
            intent_version=intent_version,
            elapsed_ms=round(elapsed_ms, 3),
            product_ids=product_ids,
        ))
