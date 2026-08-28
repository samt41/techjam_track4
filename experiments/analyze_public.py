from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum


class MissReason(StrEnum):
    TARGET_REJECTED = "target_rejected"
    TARGET_NOT_RETRIEVED = "target_not_retrieved"
    TARGET_RANKED_BELOW_TEN = "target_ranked_below_ten"
    ROUTE_FAILURE = "route_failure"
    FALLBACK_EXHAUSTED = "fallback_exhausted"
    STALE_OVERRIDE_EVIDENCE = "stale_override_evidence"
    INSUFFICIENT_TARGET_METADATA = "insufficient_target_metadata"
    UNKNOWN = "unknown"


_FAILURE_REASONS = frozenset({
    "work_limit_exceeded",
    "route_timeout",
    "fts5_unavailable",
    "artifact_mismatch",
    "artifact_missing",
    "malformed_artifact",
})
_HARD_ROUTES = frozenset({"metadata", "exact_fts", "expanded_fts"})


@dataclass(frozen=True, slots=True)
class TargetProfile:
    parent_asin: str
    attributes: dict[str, str]
    price: float | None
    searchable_text: str


@dataclass(frozen=True, slots=True)
class FailureAnalysis:
    sample_id: str
    scenario_type: str
    primary_reason: MissReason
    constraint_id: str | None
    detail: str

    def as_record(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "scenario_type": self.scenario_type,
            "primary_reason": self.primary_reason.value,
            "constraint_id": self.constraint_id,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class _ParsedConstraint:
    constraint_id: str
    attribute: str
    operator: str
    value: str
    excluded: bool


def analyze_session(
    target: TargetProfile,
    trace: tuple[dict, ...],
    outcome: dict,
) -> FailureAnalysis | None:
    if outcome.get("hit"):
        return None
    sample_id = str(outcome.get("sample_id", ""))
    scenario_type = str(outcome.get("scenario_type", ""))

    active_constraints = _latest_active_constraints(trace)
    incompatible = _incompatible_constraint(target, active_constraints)
    rejected_target = any(
        target.parent_asin in event.get("rejected_product_ids", [])
        for event in trace
        if event.get("event_type") == "constraint"
    )
    in_population = any(
        any(
            candidate.get("parent_asin") == target.parent_asin
            for candidate in event.get("candidates", [])
        )
        for event in trace
        if event.get("event_type") == "belief"
    )
    in_slate = any(
        target.parent_asin in event.get("strict_product_ids", [])
        or target.parent_asin in event.get("exploratory_product_ids", [])
        for event in trace
        if event.get("event_type") == "slate"
    )

    def build(reason: MissReason, constraint_id: str | None, detail: str) -> FailureAnalysis:
        return FailureAnalysis(
            sample_id=sample_id,
            scenario_type=scenario_type,
            primary_reason=reason,
            constraint_id=constraint_id,
            detail=detail,
        )

    # Priority order: rejection, then rank-out, then retrieval/route causes.
    if rejected_target or (not in_population and incompatible is not None):
        return build(
            MissReason.TARGET_REJECTED,
            incompatible.constraint_id if incompatible else None,
            "target violates an active hard constraint",
        )
    if in_population and not in_slate:
        return build(
            MissReason.TARGET_RANKED_BELOW_TEN,
            None,
            "target entered the belief population but ranked outside the slate",
        )
    if _has_route_failure(trace):
        return build(
            MissReason.ROUTE_FAILURE,
            None,
            "a retrieval route failed before producing eligible results",
        )
    if not target.searchable_text and not target.attributes:
        return build(
            MissReason.INSUFFICIENT_TARGET_METADATA,
            None,
            "target lacks metadata needed to retrieve or rank it",
        )
    if not in_population and incompatible is None:
        return build(
            MissReason.TARGET_NOT_RETRIEVED,
            None,
            "target is eligible but never entered the bounded pool",
        )
    return build(MissReason.UNKNOWN, None, "no dominant cause identified")


def _latest_active_constraints(trace: tuple[dict, ...]) -> tuple[str, ...]:
    latest: tuple[str, ...] = ()
    for event in trace:
        if event.get("event_type") == "interpretation":
            latest = tuple(event.get("active_constraint_ids", []))
    return latest


def _incompatible_constraint(
    target: TargetProfile,
    constraint_ids: tuple[str, ...],
) -> _ParsedConstraint | None:
    for constraint_id in constraint_ids:
        parsed = _parse_constraint(constraint_id)
        if parsed is None:
            continue
        if not _target_satisfies(target, parsed):
            return parsed
    return None


def _parse_constraint(constraint_id: str) -> _ParsedConstraint | None:
    # Format: t{turn}:{attribute}:{operator}:{value}:{polarity}:{ordinal}
    parts = constraint_id.split(":")
    if len(parts) < 6:
        return None
    _, attribute, operator, value, polarity, _ = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
    return _ParsedConstraint(
        constraint_id=constraint_id,
        attribute=attribute,
        operator=operator,
        value=value.replace("-", " "),
        excluded=polarity == "exclude",
    )


def _target_satisfies(target: TargetProfile, constraint: _ParsedConstraint) -> bool:
    if constraint.attribute == "budget":
        if target.price is None:
            return False
        try:
            boundary = float(constraint.value)
        except ValueError:
            return True
        if constraint.operator == "less_than_or_equal":
            satisfied = target.price <= boundary
        elif constraint.operator == "greater_than_or_equal":
            satisfied = target.price >= boundary
        else:
            satisfied = target.price == boundary
        return satisfied != constraint.excluded

    haystack = " ".join((
        target.searchable_text.lower(),
        *(str(value).lower() for value in target.attributes.values()),
    ))
    present = constraint.value.lower() in haystack
    if constraint.excluded:
        return not present
    return present


def _has_route_failure(trace: tuple[dict, ...]) -> bool:
    for event in trace:
        if event.get("event_type") != "retrieval":
            continue
        if event.get("route") not in _HARD_ROUTES:
            continue
        if event.get("reason") in _FAILURE_REASONS:
            return True
    return False


def code_revision() -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown_revision"
    revision = result.stdout.strip()
    return revision or "unknown_revision"
