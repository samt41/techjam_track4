from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Union

from starter.shopping_agent.models import (
    Attribute,
    DialogueAct,
    RetrievalRoute,
)
from starter.shopping_agent.search_backend import SearchReason, TotalRelation


def _enum_value(value: object) -> object:
    return value.value if hasattr(value, "value") else value


@dataclass(frozen=True, slots=True)
class InterpretationTrace:
    session_id: str
    turn: int
    dialogue_act: DialogueAct
    update_kinds: tuple[str, ...]
    active_constraint_ids: tuple[str, ...]
    intent_version: int

    def as_record(self) -> dict[str, object]:
        return {
            "event_type": "interpretation",
            "session_id": self.session_id,
            "turn": self.turn,
            "dialogue_act": self.dialogue_act.value,
            "update_kinds": list(self.update_kinds),
            "active_constraint_ids": list(self.active_constraint_ids),
            "intent_version": self.intent_version,
        }


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    session_id: str
    turn: int
    intent_version: int
    route: RetrievalRoute
    terms: tuple[str, ...]
    filter_constraint_ids: tuple[str, ...]
    total_matches: int
    total_relation: TotalRelation
    returned_matches: int
    work_consumed: int
    elapsed_ms: float
    reason: SearchReason

    def as_record(self) -> dict[str, object]:
        return {
            "event_type": "retrieval",
            "session_id": self.session_id,
            "turn": self.turn,
            "intent_version": self.intent_version,
            "route": self.route.value,
            "terms": list(self.terms),
            "filter_constraint_ids": list(self.filter_constraint_ids),
            "total_matches": self.total_matches,
            "total_relation": self.total_relation.value,
            "returned_matches": self.returned_matches,
            "work_consumed": self.work_consumed,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class ConstraintTrace:
    session_id: str
    turn: int
    intent_version: int
    strict_candidate_count: int
    eligible_count: int
    relaxed_constraint_ids: tuple[str, ...]
    rejected_product_ids: tuple[str, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "event_type": "constraint",
            "session_id": self.session_id,
            "turn": self.turn,
            "intent_version": self.intent_version,
            "strict_candidate_count": self.strict_candidate_count,
            "eligible_count": self.eligible_count,
            "relaxed_constraint_ids": list(self.relaxed_constraint_ids),
            "rejected_product_ids": list(self.rejected_product_ids),
        }


@dataclass(frozen=True, slots=True)
class BeliefContributionRecord:
    parent_asin: str
    posterior: float
    contributions: tuple[tuple[str, float], ...]

    def as_json(self) -> dict[str, object]:
        return {
            "parent_asin": self.parent_asin,
            "posterior": round(self.posterior, 6),
            "contributions": [
                [component, round(value, 6)]
                for component, value in self.contributions
            ],
        }


@dataclass(frozen=True, slots=True)
class BeliefTrace:
    session_id: str
    turn: int
    intent_version: int
    population_size: int
    candidates: tuple[BeliefContributionRecord, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "event_type": "belief",
            "session_id": self.session_id,
            "turn": self.turn,
            "intent_version": self.intent_version,
            "population_size": self.population_size,
            "candidates": [record.as_json() for record in self.candidates],
        }


@dataclass(frozen=True, slots=True)
class QuestionTrace:
    session_id: str
    turn: int
    intent_version: int
    selected_attribute: Attribute | None
    current_entropy: float
    conditional_entropy: float
    information_gain: float
    coverage: float
    reason: str

    def as_record(self) -> dict[str, object]:
        return {
            "event_type": "question",
            "session_id": self.session_id,
            "turn": self.turn,
            "intent_version": self.intent_version,
            "selected_attribute": _enum_value(self.selected_attribute),
            "current_entropy": round(self.current_entropy, 6),
            "conditional_entropy": round(self.conditional_entropy, 6),
            "information_gain": round(self.information_gain, 6),
            "coverage": round(self.coverage, 6),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SlateTrace:
    session_id: str
    turn: int
    intent_version: int
    strict_product_ids: tuple[str, ...]
    exploratory_product_ids: tuple[str, ...]
    relaxed_constraint_ids: tuple[str, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "event_type": "slate",
            "session_id": self.session_id,
            "turn": self.turn,
            "intent_version": self.intent_version,
            "strict_product_ids": list(self.strict_product_ids),
            "exploratory_product_ids": list(self.exploratory_product_ids),
            "relaxed_constraint_ids": list(self.relaxed_constraint_ids),
        }


@dataclass(frozen=True, slots=True)
class RuntimeTrace:
    session_id: str
    turn: int
    startup_ms: float
    turn_ms: float
    peak_python_bytes: int
    rss_bytes: int | None
    rss_reason: str
    catalog_sha256: str
    database_sha256: str
    catalog_size_bytes: int
    database_size_bytes: int

    def as_record(self) -> dict[str, object]:
        return {
            "event_type": "runtime",
            "session_id": self.session_id,
            "turn": self.turn,
            "startup_ms": round(self.startup_ms, 3),
            "turn_ms": round(self.turn_ms, 3),
            "peak_python_bytes": self.peak_python_bytes,
            "rss_bytes": self.rss_bytes,
            "rss_reason": self.rss_reason,
            "catalog_sha256": self.catalog_sha256,
            "database_sha256": self.database_sha256,
            "catalog_size_bytes": self.catalog_size_bytes,
            "database_size_bytes": self.database_size_bytes,
        }


TraceEvent = Union[
    InterpretationTrace,
    RetrievalTrace,
    ConstraintTrace,
    BeliefTrace,
    QuestionTrace,
    SlateTrace,
    RuntimeTrace,
]


class EvaluationTrace(Protocol):
    def record(self, event: TraceEvent) -> None: ...

    def close(self) -> None: ...


class NoOpEvaluationTrace:
    __slots__ = ()

    def record(self, event: TraceEvent) -> None:
        return None

    def close(self) -> None:
        return None


class JsonlEvaluationTrace:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._handle = None

    def record(self, event: TraceEvent) -> None:
        # Keep one append handle open for the life of the trace instead of
        # reopening per event; flush each line so a downstream reader (miss
        # attribution runs after evaluation) sees a complete file. Opening and
        # closing a handle for all ~10k events per run dominated traced runtime.
        if self._handle is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("a", encoding="utf-8")
        self._handle.write(json.dumps(event.as_record(), sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
