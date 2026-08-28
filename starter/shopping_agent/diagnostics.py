from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from starter.shopping_agent.models import Attribute, RetrievalRoute


class TraceEventType(StrEnum):
    ROUTE = "route"
    FILTERING = "filtering"
    QUESTION = "question"
    SLATE = "slate"
    LATENCY = "latency"
    FALLBACK = "fallback"


class TraceReason(StrEnum):
    STRICT_RESULTS = "strict_results"
    EMPTY_STRICT_POOL = "empty_strict_pool"
    SPARSE_STRICT_POOL = "sparse_strict_pool"
    COUNTERFACTUAL_RESULTS = "counterfactual_results"
    ELIGIBILITY_APPLIED = "eligibility_applied"
    QUESTION_SELECTED = "question_selected"
    QUESTION_SKIPPED = "question_skipped"
    SLATE_RETURNED = "slate_returned"
    TURN_COMPLETED = "turn_completed"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    session_id: str
    turn: int
    event_type: TraceEventType
    reason: TraceReason
    route: RetrievalRoute | None
    attribute: Attribute | None
    candidate_count: int
    recommendation_count: int
    intent_version: int
    elapsed_ms: float
    product_ids: tuple[str, ...] = ()


class EvaluationTrace(Protocol):
    def record(self, event: TraceEvent) -> None: ...


class NoOpEvaluationTrace:
    def record(self, event: TraceEvent) -> None:
        return None


class JsonlEvaluationTrace:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def record(self, event: TraceEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), sort_keys=True) + "\n")
