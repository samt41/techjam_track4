from __future__ import annotations

from dataclasses import dataclass

from experiments.semantic.schemas import ConceptHit, ProbeCase, ProbeKind


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    positive_count: int
    recall_at_1: float
    recall_at_5: float
    mean_reciprocal_rank: float
    opposite_forbidden_at_1: int
    opposite_forbidden_at_5: int
    unrelated_result_at_1: int

    def as_record(self) -> dict[str, object]:
        return {
            "positive_count": self.positive_count,
            "recall_at_1": round(self.recall_at_1, 6),
            "recall_at_5": round(self.recall_at_5, 6),
            "mean_reciprocal_rank": round(self.mean_reciprocal_rank, 6),
            "opposite_forbidden_at_1": self.opposite_forbidden_at_1,
            "opposite_forbidden_at_5": self.opposite_forbidden_at_5,
            "unrelated_result_at_1": self.unrelated_result_at_1,
        }


def retrieval_metrics(
    cases: tuple[ProbeCase, ...],
    hits_by_case: dict[str, tuple[ConceptHit, ...]],
) -> RetrievalMetrics:
    positives = tuple(
        case for case in cases if case.kind in {ProbeKind.POSITIVE, ProbeKind.AMBIGUOUS}
    )
    reciprocal_ranks: list[float] = []
    recall_one = 0
    recall_five = 0
    opposite_one = 0
    opposite_five = 0
    unrelated_one = 0
    for case in cases:
        hits = hits_by_case.get(case.case_id, ())
        ids = tuple(hit.concept_id for hit in hits)
        if case in positives:
            acceptable = set(case.acceptable_concept_ids)
            rank = next(
                (index for index, concept_id in enumerate(ids, start=1)
                 if concept_id in acceptable),
                None,
            )
            reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
            recall_one += int(rank == 1)
            recall_five += int(rank is not None and rank <= 5)
        if case.kind is ProbeKind.OPPOSITE_TRAP:
            forbidden = set(case.forbidden_concept_ids)
            opposite_one += int(bool(ids[:1]) and ids[0] in forbidden)
            opposite_five += int(any(value in forbidden for value in ids[:5]))
        if case.kind is ProbeKind.UNRELATED:
            unrelated_one += int(bool(ids))
    count = len(positives)
    return RetrievalMetrics(
        positive_count=count,
        recall_at_1=0.0 if not count else recall_one / count,
        recall_at_5=0.0 if not count else recall_five / count,
        mean_reciprocal_rank=(
            0.0 if not reciprocal_ranks else sum(reciprocal_ranks) / len(reciprocal_ranks)
        ),
        opposite_forbidden_at_1=opposite_one,
        opposite_forbidden_at_5=opposite_five,
        unrelated_result_at_1=unrelated_one,
    )
