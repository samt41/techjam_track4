from __future__ import annotations

import tracemalloc
from dataclasses import dataclass
from time import perf_counter

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.clarification import (
    ClarificationPolicy,
    PosteriorQuestionModel,
    QuestionModelConfiguration,
)
from starter.shopping_agent.constraint_extractor import ConstraintExtractor
from starter.shopping_agent.diagnostics import (
    BeliefContributionRecord,
    BeliefTrace,
    ConstraintTrace,
    EvaluationTrace,
    InterpretationTrace,
    NoOpEvaluationTrace,
    QuestionTrace,
    RetrievalTrace,
    RuntimeTrace,
    SlateTrace,
)
from starter.shopping_agent.models import (
    Attribute,
    RankedRecommendation,
    RecommendationHistory,
    ShoppingIntent,
    TurnRecord,
    TurnResponse,
    UserProfile,
)
from starter.shopping_agent.preference_ledger import PreferenceLedger
from starter.shopping_agent.ranking import ProductRanker
from starter.shopping_agent.response import ResponseValidator, recommendation_message
from starter.shopping_agent.retrieval import (
    PlannedSearch,
    RetrievalPlanner,
    build_reliabilities,
    execute_search_plan_traced,
    order_relaxations,
)
from starter.shopping_agent.search_backend import SearchResult


try:  # pragma: no cover - platform dependent
    import resource as _resource
except ImportError:  # pragma: no cover - Windows has no resource module
    _resource = None

_REJECTED_TRACE_CAP = 50
_BELIEF_TRACE_CAP = 20


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
        startup_ms: float = 0.0,
        exploration: str = "disabled",
    ) -> None:
        self._catalog_index = catalog_index
        self._extractor = ConstraintExtractor(catalog_index)
        self._planner = RetrievalPlanner()
        self._ranker = ProductRanker(catalog_index.backend)
        self._validator = ResponseValidator(catalog_index.backend)
        self._question_model = PosteriorQuestionModel(
            QuestionModelConfiguration.default()
        )
        self._clarification_policy = ClarificationPolicy()
        self._sessions: dict[str, _SessionState] = {}
        self._closed = False
        self._trace = trace or NoOpEvaluationTrace()
        self._startup_ms = startup_ms
        self._exploration_enabled = exploration != "disabled"
        self._traced = not isinstance(self._trace, NoOpEvaluationTrace)
        if self._traced and not tracemalloc.is_tracing():
            tracemalloc.start()

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
        self._trace.record(InterpretationTrace(
            session_id=session_id,
            turn=turn,
            dialogue_act=dialogue_act,
            update_kinds=tuple(update.evidence_kind.value for update in updates),
            active_constraint_ids=tuple(
                constraint.constraint_id
                for constraint in intent.active_constraints
            ),
            intent_version=intent.intent_version,
        ))

        strict_candidates_list = []
        for plan in self._planner.strict(intent, top_k):
            route_candidates, result = execute_search_plan_traced(
                self._catalog_index.backend,
                plan,
            )
            strict_candidates_list.extend(route_candidates)
            self._emit_retrieval(
                session_id, turn, intent, plan, result, len(route_candidates)
            )
        strict_candidates = tuple(strict_candidates_list)

        shown_product_ids = state.history.shown_for(intent.intent_version)
        recommendations = self._ranker.rank(
            strict_candidates,
            intent,
            shown_product_ids=shown_product_ids,
            top_k=top_k,
            profile=state.profile,
        )
        # Estimate the clarifying question from the full preliminary strict
        # belief population before any counterfactual tail fill runs, so the
        # question sees the true posterior spread rather than the final slate.
        strict_population = self._ranker.strict_population(
            strict_candidates,
            intent,
            profile=state.profile,
        )
        question_candidates = self._question_model.score_population(
            strict_population
        )
        clarification = self._clarification_policy.choose(
            question_candidates,
            intent,
            turn,
        )

        # Counterfactual tail fill runs when the slate is short AND exploration
        # is enabled, OR — regardless of the flag — when the strict pool is
        # empty, since a last-resort relaxation is the only way to return any
        # slate at all. On the public set, exploration only ever fires on
        # sessions that already have strict results (where it changes nothing),
        # so it is disabled by default; the empty-pool guarantee is preserved.
        needs_tail_fill = len(recommendations) < top_k and (
            self._exploration_enabled or len(recommendations) == 0
        )
        if needs_tail_fill:
            recommendations = self._fill_tail(
                session_id,
                turn,
                intent,
                strict_candidates,
                strict_total=len(recommendations),
                shown_product_ids=shown_product_ids,
                top_k=top_k,
                profile=state.profile,
            )
        recommendations = self._validator.validate(recommendations, top_k)
        state.history.record(
            intent.intent_version,
            tuple(item.parent_asin for item in recommendations),
        )
        if clarification is not None:
            state.ledger.record_question(clarification.attribute)
            state.last_asked_attribute = clarification.attribute

        self._emit_constraint(
            session_id, turn, intent, strict_candidates,
            strict_population, recommendations,
        )
        self._emit_belief(session_id, turn, intent, recommendations)
        self._emit_question(
            session_id, turn, intent, question_candidates, clarification
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
        self._trace.record(SlateTrace(
            session_id=session_id,
            turn=turn,
            intent_version=intent.intent_version,
            strict_product_ids=strict_product_ids,
            exploratory_product_ids=exploratory_product_ids,
            relaxed_constraint_ids=relaxed_constraint_ids,
        ))
        self._emit_runtime(
            session_id, turn, (perf_counter() - started) * 1000.0
        )

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
        intent: ShoppingIntent,
        strict_candidates,
        strict_total: int,
        shown_product_ids,
        top_k: int,
        profile,
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
            profile=profile,
        )
        for plan in self._planner.counterfactuals(intent, ordered, top_k):
            if len(recommendations) >= top_k:
                break
            counterfactual_candidates, result = execute_search_plan_traced(
                self._catalog_index.backend,
                plan,
            )
            self._emit_retrieval(
                session_id, turn, intent, plan, result,
                len(counterfactual_candidates),
            )
            combined.extend(counterfactual_candidates)
            recommendations = self._ranker.rank(
                tuple(combined),
                intent,
                shown_product_ids=shown_product_ids,
                top_k=top_k,
                profile=profile,
            )
        return recommendations

    def _emit_retrieval(
        self,
        session_id: str,
        turn: int,
        intent: ShoppingIntent,
        plan: PlannedSearch,
        result: SearchResult,
        returned: int,
    ) -> None:
        self._trace.record(RetrievalTrace(
            session_id=session_id,
            turn=turn,
            intent_version=intent.intent_version,
            route=plan.request.route,
            terms=plan.request.lexical_terms,
            filter_constraint_ids=tuple(
                structured_filter.constraint_id
                for structured_filter in plan.request.filters
            ),
            total_matches=result.total_matches,
            total_relation=result.total_relation,
            returned_matches=returned,
            work_consumed=result.work_consumed,
            elapsed_ms=result.elapsed_ms,
            reason=result.reason,
        ))

    def _emit_constraint(
        self,
        session_id: str,
        turn: int,
        intent: ShoppingIntent,
        strict_candidates,
        strict_population,
        recommendations: tuple[RankedRecommendation, ...],
    ) -> None:
        candidate_ids = tuple(dict.fromkeys(
            candidate.parent_asin
            for candidate in strict_candidates
            if candidate.relaxed_constraint_id is None
        ))
        eligible_ids = {product.parent_asin for _, product in strict_population}
        rejected = tuple(
            candidate_id
            for candidate_id in candidate_ids
            if candidate_id not in eligible_ids
        )[:_REJECTED_TRACE_CAP]
        relaxed = tuple(dict.fromkeys(
            item.relaxed_constraint_id
            for item in recommendations
            if item.relaxed_constraint_id is not None
        ))
        self._trace.record(ConstraintTrace(
            session_id=session_id,
            turn=turn,
            intent_version=intent.intent_version,
            strict_candidate_count=len(candidate_ids),
            eligible_count=len(eligible_ids),
            relaxed_constraint_ids=relaxed,
            rejected_product_ids=rejected,
        ))

    def _emit_belief(
        self,
        session_id: str,
        turn: int,
        intent: ShoppingIntent,
        recommendations: tuple[RankedRecommendation, ...],
    ) -> None:
        strict = tuple(
            item for item in recommendations if item.exact_match
        )[:_BELIEF_TRACE_CAP]
        self._trace.record(BeliefTrace(
            session_id=session_id,
            turn=turn,
            intent_version=intent.intent_version,
            population_size=sum(1 for item in recommendations if item.exact_match),
            candidates=tuple(
                BeliefContributionRecord(
                    parent_asin=item.parent_asin,
                    posterior=item.posterior,
                    contributions=item.belief_contributions,
                )
                for item in strict
            ),
        ))

    def _emit_question(
        self,
        session_id: str,
        turn: int,
        intent: ShoppingIntent,
        question_candidates,
        clarification,
    ) -> None:
        if clarification is not None:
            selected = next(
                candidate
                for candidate in question_candidates
                if candidate.attribute is clarification.attribute
            )
            attribute = clarification.attribute
            reason = "question_selected"
        elif question_candidates:
            selected = question_candidates[0]
            attribute = None
            reason = "question_skipped"
        else:
            self._trace.record(QuestionTrace(
                session_id=session_id,
                turn=turn,
                intent_version=intent.intent_version,
                selected_attribute=None,
                current_entropy=0.0,
                conditional_entropy=0.0,
                information_gain=0.0,
                coverage=0.0,
                reason="no_population",
            ))
            return
        self._trace.record(QuestionTrace(
            session_id=session_id,
            turn=turn,
            intent_version=intent.intent_version,
            selected_attribute=attribute,
            current_entropy=selected.current_entropy,
            conditional_entropy=selected.conditional_entropy,
            information_gain=selected.information_gain,
            coverage=selected.coverage,
            reason=reason,
        ))

    def _emit_runtime(
        self,
        session_id: str,
        turn: int,
        turn_ms: float,
    ) -> None:
        peak_python_bytes = 0
        if tracemalloc.is_tracing():
            _, peak_python_bytes = tracemalloc.get_traced_memory()
        rss_bytes, rss_reason = _process_rss()
        manifest = self._catalog_index.backend.manifest
        self._trace.record(RuntimeTrace(
            session_id=session_id,
            turn=turn,
            startup_ms=self._startup_ms,
            turn_ms=turn_ms,
            peak_python_bytes=int(peak_python_bytes),
            rss_bytes=rss_bytes,
            rss_reason=rss_reason,
            catalog_sha256=manifest.catalog_sha256,
            database_sha256=manifest.database_sha256,
            catalog_size_bytes=manifest.catalog_size_bytes,
            database_size_bytes=manifest.database_size_bytes,
        ))


def _process_rss() -> tuple[int | None, str]:
    if _resource is None:
        return None, "rss_unavailable"
    usage = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is kilobytes on Linux and bytes on macOS; normalize to bytes.
    import sys

    scale = 1 if sys.platform == "darwin" else 1024
    return int(usage) * scale, "rusage_maxrss"
