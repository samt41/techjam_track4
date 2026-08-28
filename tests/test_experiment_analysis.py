from __future__ import annotations

import unittest

from experiments.analyze_public import (
    FailureAnalysis,
    MissReason,
    TargetProfile,
    analyze_session,
    code_revision,
)


def target_profile(
    parent_asin: str,
    *,
    material: str = "canvas",
    color: str = "black",
    price: float | None = 70.0,
    searchable_text: str = "canvas boot durable",
) -> TargetProfile:
    return TargetProfile(
        parent_asin=parent_asin,
        attributes={"material": material, "color": color},
        price=price,
        searchable_text=searchable_text,
    )


def interpretation_event(constraint_ids: tuple[str, ...]) -> dict:
    return {
        "event_type": "interpretation",
        "session_id": "s",
        "turn": 1,
        "dialogue_act": "request",
        "update_kinds": ["explicit_requirement"],
        "active_constraint_ids": list(constraint_ids),
        "intent_version": 1,
    }


def retrieval_event(
    route: str,
    *,
    reason: str = "completed",
    returned: int = 5,
    total: int = 5,
    filter_constraint_ids: tuple[str, ...] = (),
) -> dict:
    return {
        "event_type": "retrieval",
        "session_id": "s",
        "turn": 1,
        "intent_version": 1,
        "route": route,
        "terms": [],
        "filter_constraint_ids": list(filter_constraint_ids),
        "total_matches": total,
        "total_relation": "exact",
        "returned_matches": returned,
        "work_consumed": 1,
        "elapsed_ms": 0.1,
        "reason": reason,
    }


def constraint_event(rejected: tuple[str, ...]) -> dict:
    return {
        "event_type": "constraint",
        "session_id": "s",
        "turn": 1,
        "intent_version": 1,
        "strict_candidate_count": 5,
        "eligible_count": 4,
        "relaxed_constraint_ids": [],
        "rejected_product_ids": list(rejected),
    }


def belief_event(parent_asins: tuple[str, ...]) -> dict:
    return {
        "event_type": "belief",
        "session_id": "s",
        "turn": 1,
        "intent_version": 1,
        "population_size": len(parent_asins),
        "candidates": [
            {"parent_asin": parent_asin, "posterior": 0.1, "contributions": []}
            for parent_asin in parent_asins
        ],
    }


def slate_event(strict: tuple[str, ...]) -> dict:
    return {
        "event_type": "slate",
        "session_id": "s",
        "turn": 1,
        "intent_version": 1,
        "strict_product_ids": list(strict),
        "exploratory_product_ids": [],
        "relaxed_constraint_ids": [],
    }


def miss_outcome() -> dict:
    return {
        "sample_id": "sample-1",
        "scenario_type": "buying",
        "hit": False,
        "first_hit_turn": None,
        "best_rank": None,
        "reciprocal_rank": 0.0,
    }


class AnalyzeSessionTest(unittest.TestCase):
    def test_hit_outcome_has_no_failure(self) -> None:
        result = analyze_session(
            target=target_profile("TARGET"),
            trace=(slate_event(("TARGET",)),),
            outcome={**miss_outcome(), "hit": True, "best_rank": 1},
        )
        self.assertIsNone(result)

    def test_target_removed_by_constraint_is_rejected(self) -> None:
        constraint_id = "t1:material:equals:leather:include:1"
        failure = analyze_session(
            target=target_profile("TARGET", material="canvas"),
            trace=(
                interpretation_event((constraint_id,)),
                retrieval_event(
                    "metadata",
                    filter_constraint_ids=(constraint_id,),
                ),
                constraint_event(("TARGET",)),
                slate_event(("OTHER-1",)),
            ),
            outcome=miss_outcome(),
        )

        self.assertIsInstance(failure, FailureAnalysis)
        self.assertIs(failure.primary_reason, MissReason.TARGET_REJECTED)
        self.assertEqual(failure.constraint_id, constraint_id)

    def test_target_absent_but_hard_incompatible_is_rejected(self) -> None:
        constraint_id = "t1:material:equals:leather:include:1"
        failure = analyze_session(
            target=target_profile("TARGET", material="canvas"),
            trace=(
                interpretation_event((constraint_id,)),
                retrieval_event(
                    "metadata",
                    returned=3,
                    total=3,
                    filter_constraint_ids=(constraint_id,),
                ),
                slate_event(("OTHER-1",)),
            ),
            outcome=miss_outcome(),
        )

        self.assertIs(failure.primary_reason, MissReason.TARGET_REJECTED)
        self.assertEqual(failure.constraint_id, constraint_id)

    def test_soft_constraint_does_not_count_as_rejection(self) -> None:
        # A soft constraint (never a hard filter) must not attribute the miss to
        # rejection even if the target's metadata differs from its value.
        soft_id = "t1:brand:equals:not:include:1"
        failure = analyze_session(
            target=target_profile("TARGET", material="canvas"),
            trace=(
                interpretation_event((soft_id,)),
                retrieval_event("metadata", returned=3, total=3),
                belief_event(("TARGET", "OTHER-1")),
                slate_event(("OTHER-1",)),
            ),
            outcome=miss_outcome(),
        )

        self.assertIsNot(failure.primary_reason, MissReason.TARGET_REJECTED)
        self.assertIs(failure.primary_reason, MissReason.TARGET_RANKED_BELOW_TEN)

    def test_target_in_population_but_below_ten_is_ranked_out(self) -> None:
        failure = analyze_session(
            target=target_profile("TARGET"),
            trace=(
                interpretation_event(()),
                belief_event(("TARGET", "OTHER-1")),
                slate_event(("OTHER-1",)),
            ),
            outcome=miss_outcome(),
        )

        self.assertIs(failure.primary_reason, MissReason.TARGET_RANKED_BELOW_TEN)

    def test_target_eligible_but_absent_is_not_retrieved(self) -> None:
        constraint_id = "t1:material:equals:canvas:include:1"
        failure = analyze_session(
            target=target_profile("TARGET", material="canvas"),
            trace=(
                interpretation_event((constraint_id,)),
                retrieval_event("metadata", returned=2, total=2),
                slate_event(("OTHER-1",)),
            ),
            outcome=miss_outcome(),
        )

        self.assertIs(failure.primary_reason, MissReason.TARGET_NOT_RETRIEVED)

    def test_route_failure_is_attributed_when_work_budget_exhausted(self) -> None:
        failure = analyze_session(
            target=target_profile("TARGET", material="canvas", searchable_text=""),
            trace=(
                interpretation_event(()),
                retrieval_event(
                    "exact_fts",
                    reason="work_limit_exceeded",
                    returned=0,
                    total=0,
                ),
                slate_event(("OTHER-1",)),
            ),
            outcome=miss_outcome(),
        )

        self.assertIs(failure.primary_reason, MissReason.ROUTE_FAILURE)

    def test_every_miss_receives_a_nonempty_reason(self) -> None:
        failure = analyze_session(
            target=target_profile("TARGET"),
            trace=(interpretation_event(()), slate_event(("OTHER-1",))),
            outcome=miss_outcome(),
        )

        self.assertIsNotNone(failure)
        self.assertTrue(failure.primary_reason.value)


class CodeRevisionTest(unittest.TestCase):
    def test_code_revision_is_a_nonempty_string(self) -> None:
        revision = code_revision()
        self.assertIsInstance(revision, str)
        self.assertTrue(revision)


if __name__ == "__main__":
    unittest.main()
