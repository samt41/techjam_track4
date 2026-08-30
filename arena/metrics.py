from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass

# This metric chain is transcribed from evaluator/local_evaluator.py:188-201 and
# :278-295, and is deliberately NOT imported from there (D-08). The duplication is
# load-bearing rather than debt: cross-agreement between two independent code paths
# is the validation evidence (D-06), and importing the evaluator's own function
# would make that agreement a tautology instead of a check. The evaluator is also
# immutable, so this copy can drift only if someone edits this file.

MAX_TURNS = 10  # evaluator/local_evaluator.py:15

# HR@10 / MRR / Efficiency, per the competition's TechnicalScore definition.
TECHNICAL_SCORE_WEIGHTS = (0.50, 0.30, 0.20)

DEFAULT_CURVE_DEPTHS = (1, 3, 5, 10)

# A bucket this small cannot resolve a one-session swing from noise: at n=10 a
# single session moves HR@10 by 0.10 against a sigma of 0.094868, so the swing is
# barely one standard error and carries no decision content.
NOT_DECISION_GRADE_BELOW = 40


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    sample_id: str
    scenario_type: str
    hit: bool
    first_hit_turn: int | None
    best_rank: int | None
    reciprocal_rank: float

    def validate(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id must not be empty")
        if self.best_rank is not None and not 1 <= self.best_rank <= MAX_TURNS:
            raise ValueError("best_rank must be between 1 and 10")
        if self.first_hit_turn is not None and not 1 <= self.first_hit_turn <= MAX_TURNS:
            raise ValueError("first_hit_turn must be between 1 and 10")
        if not 0.0 <= self.reciprocal_rank <= 1.0:
            raise ValueError("reciprocal_rank must be between 0 and 1")
        if self.hit != (self.first_hit_turn is not None):
            raise ValueError("hit must agree with first_hit_turn presence")

    def as_record(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "scenario_type": self.scenario_type,
            "hit": self.hit,
            "first_hit_turn": self.first_hit_turn,
            "best_rank": self.best_rank,
            "reciprocal_rank": self.reciprocal_rank,
        }


@dataclass(frozen=True, slots=True)
class MetricSummary:
    sample_count: int
    hit_rate_at_10: float
    mrr: float
    mttc: float

    def as_record(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "hit_rate_at_10": self.hit_rate_at_10,
            "mrr": self.mrr,
            "mttc": self.mttc,
        }


@dataclass(frozen=True, slots=True)
class ScenarioSummary:
    scenario_type: str
    summary: MetricSummary
    binomial_standard_error: float
    decision_grade: bool

    def as_record(self) -> dict[str, object]:
        return {
            "scenario_type": self.scenario_type,
            **self.summary.as_record(),
            "binomial_standard_error": self.binomial_standard_error,
            "decision_grade": self.decision_grade,
        }


def metric_summary(sessions: tuple[SessionOutcome, ...]) -> MetricSummary:
    count = len(sessions)
    if count == 0:
        # The evaluator returns mttc=None here (local_evaluator.py:190), which would
        # make efficiency() raise on a None subtraction. Fail closed instead, matching
        # this repo's convention of raising a domain error at a contract violation.
        raise ValueError("metric summary requires at least one session")
    hit_rate = sum(1 for item in sessions if item.hit) / count
    mrr = statistics.fmean(item.reciprocal_rank for item in sessions)
    mttc = statistics.fmean(
        item.first_hit_turn if item.first_hit_turn is not None else MAX_TURNS + 1
        for item in sessions
    )
    return MetricSummary(
        sample_count=count,
        hit_rate_at_10=round(hit_rate, 6),
        mrr=round(mrr, 6),
        mttc=round(mttc, 6),
    )


def efficiency(summary: MetricSummary) -> float:
    # Consumes the ALREADY-ROUNDED mttc. That consumption order is what reproduces
    # the MEAS-16 anchor to 6 dp; computing efficiency from an unrounded mean would
    # diverge in the last digits and break the anchor.
    #
    # The unrounded return is also deliberate and mirrors local_evaluator.py:279-280,
    # where the unrounded value feeds technical_score; the evaluator rounds it to 6 dp
    # only at OUTPUT (local_evaluator.py:286). So on the anchor this function
    # legitimately returns 0.7575000000000001 while the evaluator's summary.json
    # legitimately reports 0.7575. Any caller writing efficiency into a file must
    # round to 6 dp itself -- arena/leaderboard.py does exactly that.
    return max(0.0, min(1.0, (11.0 - summary.mttc) / 10.0))


def technical_score(summary: MetricSummary) -> float:
    hit_rate_weight, mrr_weight, efficiency_weight = TECHNICAL_SCORE_WEIGHTS
    # The efficiency term is the UNROUNDED value and only the final score is rounded,
    # exactly as local_evaluator.py:279-280, 287 does.
    return round(
        hit_rate_weight * summary.hit_rate_at_10
        + mrr_weight * summary.mrr
        + efficiency_weight * efficiency(summary),
        6,
    )


def hit_rate_curve(
    sessions: tuple[SessionOutcome, ...],
    depths: tuple[int, ...] = DEFAULT_CURVE_DEPTHS,
) -> dict[int, float]:
    count = len(sessions)
    if count == 0:
        raise ValueError("hit rate curve requires at least one session")
    # Iterating depths in the given order keeps the mapping's key order deterministic.
    return {
        depth: round(
            sum(
                1
                for item in sessions
                if item.best_rank is not None and item.best_rank <= depth
            )
            / count,
            6,
        )
        for depth in depths
    }


def binomial_standard_error(hit_rate: float, count: int) -> float:
    # MEAS-09 quotes 0.086 and 0.050 for the n=10 and n=30 buckets, but those were
    # computed from the OVERALL p=0.92 applied to the bucket n. D-15 mandates the
    # bucket's OWN observed p, so this returns 0.094868 and 0.054772 instead. That
    # divergence is correct and must not be "fixed" back to the MEAS-09 figures.
    if count <= 0:
        raise ValueError("bucket size must be positive")
    return math.sqrt(hit_rate * (1.0 - hit_rate) / count)


def scenario_breakout(
    sessions: tuple[SessionOutcome, ...],
) -> tuple[ScenarioSummary, ...]:
    grouped: dict[str, list[SessionOutcome]] = defaultdict(list)
    for item in sessions:
        grouped[item.scenario_type].append(item)
    # sorted(grouped) for deterministic order, exactly as local_evaluator.py:293 does.
    rows: list[ScenarioSummary] = []
    for name in sorted(grouped):
        summary = metric_summary(tuple(grouped[name]))
        rows.append(
            ScenarioSummary(
                scenario_type=name,
                summary=summary,
                binomial_standard_error=binomial_standard_error(
                    summary.hit_rate_at_10,
                    summary.sample_count,
                ),
                decision_grade=summary.sample_count >= NOT_DECISION_GRADE_BELOW,
            )
        )
    return tuple(rows)
