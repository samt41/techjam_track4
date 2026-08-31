from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from experiments.semantic.schemas import (
    CatalogConcept,
    ConceptHit,
    ExpectedDisposition,
    ProbeCase,
    ProbeKind,
)
from starter.shopping_agent.models import Attribute
from starter.shopping_agent.text_normalization import search_terms


_SEMANTIC_ATTRIBUTES = frozenset({
    Attribute.CATEGORY,
    Attribute.MATERIAL,
    Attribute.COLOR,
    Attribute.SIZE,
    Attribute.STYLE,
    Attribute.BRAND,
    Attribute.FEATURE,
})


class PublicAgent(Protocol):
    def reset(self, session_id: str, user_profile: dict) -> None: ...

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CapturedTurn:
    sample_id: str
    turn: int
    user_message: str
    attribute_scope: Attribute | None
    response_sha256: str

    def as_record(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "turn": self.turn,
            "user_message": self.user_message,
            "attribute_scope": (
                None if self.attribute_scope is None else self.attribute_scope.value
            ),
            "response_sha256": self.response_sha256,
        }


class PublicMessageCaptureAgent:
    """Observe public messages while returning the wrapped response unchanged."""

    def __init__(self, agent: PublicAgent, sample_ids: tuple[str, ...]) -> None:
        self._agent = agent
        self._sample_ids = sample_ids
        self._reset_count = 0
        self._sample_by_session: dict[str, str] = {}
        self._asked_attribute_by_session: dict[str, Attribute | None] = {}
        self._turns: list[CapturedTurn] = []

    @property
    def turns(self) -> tuple[CapturedTurn, ...]:
        return tuple(self._turns)

    def reset(self, session_id: str, user_profile: dict) -> None:
        if self._reset_count >= len(self._sample_ids):
            raise ValueError("more evaluator sessions than public sample ids")
        self._sample_by_session[session_id] = self._sample_ids[self._reset_count]
        self._asked_attribute_by_session[session_id] = None
        self._reset_count += 1
        self._agent.reset(session_id, user_profile)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        response = self._agent.respond(session_id, user_message, turn, top_k)
        sample_id = self._sample_by_session[session_id]
        self._turns.append(CapturedTurn(
            sample_id=sample_id,
            turn=turn,
            user_message=user_message,
            attribute_scope=self._asked_attribute_by_session[session_id],
            response_sha256=_response_sha256(response),
        ))
        self._asked_attribute_by_session[session_id] = _response_attribute(response)
        return response

    def close(self) -> None:
        self._agent.close()


@dataclass(frozen=True, slots=True)
class PublicObservation:
    case: ProbeCase
    sample_id: str
    scenario_type: str
    target_ordinal: int

    def as_record(self) -> dict[str, object]:
        return {
            **self.case.as_record(),
            "sample_id": self.sample_id,
            "scenario_type": self.scenario_type,
            "target_ordinal": self.target_ordinal,
        }

    @classmethod
    def from_record(cls, record: dict[str, object]) -> PublicObservation:
        return cls(
            case=ProbeCase.from_record(record),
            sample_id=str(record["sample_id"]),
            scenario_type=str(record["scenario_type"]),
            target_ordinal=int(record["target_ordinal"]),
        )


def derive_public_observations(
    turns: tuple[CapturedTurn, ...],
    samples: list[dict],
    product_ordinals: dict[str, int],
    concepts: tuple[CatalogConcept, ...],
) -> tuple[PublicObservation, ...]:
    """Join target labels after capture and retain explicitly grounded turns.

    A relevant concept must belong to the target product and have its complete
    surface form or an approved alias present in the observed user message.
    This produces a public regression benchmark, not an open-vocabulary probe.
    """
    samples_by_id = {str(sample["sample_id"]): sample for sample in samples}
    target_ordinals = {
        product_ordinals[str(sample["ground_truth"]["parent_asin"])]
        for sample in samples
    }
    concepts_by_ordinal: dict[int, list[CatalogConcept]] = defaultdict(list)
    for concept in concepts:
        for ordinal in concept.product_ordinals:
            if ordinal in target_ordinals:
                concepts_by_ordinal[ordinal].append(concept)

    observations: list[PublicObservation] = []
    for captured in turns:
        sample = samples_by_id[captured.sample_id]
        target = str(sample["ground_truth"]["parent_asin"])
        target_ordinal = product_ordinals[target]
        scope = (
            captured.attribute_scope
            if captured.attribute_scope in _SEMANTIC_ATTRIBUTES
            else None
        )
        acceptable = tuple(sorted(
            concept.concept_id
            for concept in concepts_by_ordinal[target_ordinal]
            if (scope is None or concept.attribute is scope)
            and _concept_is_explicit(captured.user_message, concept)
        ))
        if not acceptable:
            continue
        case = ProbeCase(
            case_id=f"{captured.sample_id}-turn-{captured.turn}",
            split="test",
            clause=captured.user_message,
            kind=ProbeKind.POSITIVE,
            expected_disposition=ExpectedDisposition.RESOLVED_SOFT,
            acceptable_concept_ids=acceptable,
            forbidden_concept_ids=(),
            attribute_scope=scope,
            provenance="captured from unchanged public evaluator",
            reviewer_notes="labels are exact target-product concepts",
        )
        case.validate()
        observations.append(PublicObservation(
            case=case,
            sample_id=captured.sample_id,
            scenario_type=str(sample["scenario_type"]),
            target_ordinal=target_ordinal,
        ))
    return tuple(observations)


def public_retrieval_metrics(
    observations: tuple[PublicObservation, ...],
    hits_by_case: dict[str, tuple[ConceptHit, ...]],
    concepts: tuple[CatalogConcept, ...],
) -> dict[str, object]:
    concepts_by_id = {concept.concept_id: concept for concept in concepts}
    result = _metric_group(observations, hits_by_case, concepts_by_id)
    scenarios = sorted({item.scenario_type for item in observations})
    result["by_scenario"] = {
        scenario: _metric_group(
            tuple(item for item in observations if item.scenario_type == scenario),
            hits_by_case,
            concepts_by_id,
        )
        for scenario in scenarios
    }
    return result


def _metric_group(
    observations: tuple[PublicObservation, ...],
    hits_by_case: dict[str, tuple[ConceptHit, ...]],
    concepts_by_id: dict[str, CatalogConcept],
) -> dict[str, object]:
    concept_hits = {1: 0, 5: 0, 10: 0}
    target_posting_hits = {1: 0, 5: 0, 10: 0}
    reciprocal_ranks: list[float] = []
    hit_sessions: dict[int, set[str]] = {1: set(), 5: set(), 10: set()}
    for observation in observations:
        hits = hits_by_case.get(observation.case.case_id, ())
        identifiers = tuple(hit.concept_id for hit in hits)
        acceptable = set(observation.case.acceptable_concept_ids)
        rank = next(
            (index for index, value in enumerate(identifiers, start=1)
             if value in acceptable),
            None,
        )
        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
        for cutoff in concept_hits:
            concept_hits[cutoff] += int(rank is not None and rank <= cutoff)
            target_found = any(
                observation.target_ordinal
                in concepts_by_id[concept_id].product_ordinals
                for concept_id in identifiers[:cutoff]
            )
            target_posting_hits[cutoff] += int(target_found)
            if target_found:
                hit_sessions[cutoff].add(observation.sample_id)
    count = len(observations)
    session_count = len({item.sample_id for item in observations})

    def rate(value: int, denominator: int) -> float:
        return 0.0 if denominator == 0 else round(value / denominator, 6)

    return {
        "observation_count": count,
        "session_count": session_count,
        "explicit_concept_recall_at_1": rate(concept_hits[1], count),
        "explicit_concept_recall_at_5": rate(concept_hits[5], count),
        "explicit_concept_recall_at_10": rate(concept_hits[10], count),
        "mean_reciprocal_rank": (
            0.0 if not reciprocal_ranks
            else round(sum(reciprocal_ranks) / len(reciprocal_ranks), 6)
        ),
        "target_posting_recall_at_1": rate(target_posting_hits[1], count),
        "target_posting_recall_at_5": rate(target_posting_hits[5], count),
        "target_posting_recall_at_10": rate(target_posting_hits[10], count),
        "session_target_posting_coverage_at_1": rate(
            len(hit_sessions[1]), session_count
        ),
        "session_target_posting_coverage_at_5": rate(
            len(hit_sessions[5]), session_count
        ),
        "session_target_posting_coverage_at_10": rate(
            len(hit_sessions[10]), session_count
        ),
    }


def _concept_is_explicit(message: str, concept: CatalogConcept) -> bool:
    query_terms = set(search_terms(message))
    views = (concept.surface_text, *concept.aliases)
    return any(
        bool(terms) and set(terms).issubset(query_terms)
        for terms in (search_terms(view) for view in views)
    )


def _response_attribute(response: dict) -> Attribute | None:
    raw_value = response.get("ask_attribute")
    if raw_value in (None, ""):
        return None
    try:
        return Attribute(str(raw_value))
    except ValueError:
        return None


def _response_sha256(response: dict) -> str:
    encoded = json.dumps(
        response,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
