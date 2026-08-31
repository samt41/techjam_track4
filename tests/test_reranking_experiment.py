from __future__ import annotations

import unittest

from experiments.reranking.analyze_matrix import paired_outcomes
from experiments.reranking.rerankers import (
    RerankEvent,
    product_document,
    ranking_query,
)
from experiments.reranking.run_configuration import candidate_pool_metrics
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    ConstraintStatus,
    EvidenceKind,
    PreferenceConstraint,
    ProductRecord,
    ShoppingIntent,
    Strength,
)


def intent() -> ShoppingIntent:
    constraint = PreferenceConstraint(
        constraint_id="c1",
        attribute=Attribute.MATERIAL,
        operator=ComparisonOperator.EQUALS,
        value="leather",
        excluded=False,
        strength=Strength.HARD,
        confidence=0.92,
        source_turn=1,
        source_text="must be leather",
        evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
        preference_group_id="g1",
        status=ConstraintStatus.ACTIVE,
    )
    return ShoppingIntent(
        active_constraints=(constraint,),
        constraint_history=(constraint,),
        weighted_concepts=(),
        declined_attributes=frozenset(),
        asked_attributes=(),
        intent_version=0,
    )


class RerankingFormattingTest(unittest.TestCase):
    def test_query_uses_symbolic_intent_instead_of_control_boilerplate(self) -> None:
        query = ranking_query("Those options are not right", intent())

        self.assertIn("require material: leather", query)
        self.assertNotIn("options are not right", query)

    def test_product_document_exposes_compact_structured_fields(self) -> None:
        document = product_document(ProductRecord(
            parent_asin="P1",
            title="Winter boot",
            categories=("Shoes", "Boots"),
            features=("insulated", "waterproof"),
            description="Cold weather footwear",
            details=(("material", "leather"),),
            store="Example",
            price=90.0,
            average_rating=4.5,
            rating_number=10,
            searchable_text="",
        ))

        self.assertIn("title: Winter boot", document)
        self.assertIn("material: leather", document)
        self.assertIn("features: insulated; waterproof", document)


class CandidateOracleTest(unittest.TestCase):
    def test_oracle_joins_targets_only_after_runtime_events(self) -> None:
        event = RerankEvent(
            session_id="runtime-1",
            turn=1,
            pool_size=25,
            baseline_ids=("OTHER", "TARGET"),
            reranked_ids=("TARGET", "OTHER"),
            elapsed_ms=1.0,
            scored_pairs=2,
            cache_hits=0,
        )
        sample = {
            "sample_id": "sample-1",
            "scenario_type": "buying",
            "ground_truth": {"parent_asin": "TARGET"},
            "intent_card": {"hard_constraints": [], "soft_preferences": []},
            "behavior": {"scenario_type": "buying"},
        }
        metrics = candidate_pool_metrics(
            [event], {"runtime-1": "sample-1"}, [sample], {"TARGET": {}}
        )

        self.assertEqual(metrics["session_candidate_coverage"]["10"], 1.0)
        self.assertEqual(metrics["session_reranked_top_ten_coverage"], 1.0)
        self.assertEqual(metrics["minimum_candidate_rank_max"], 2)


class PairedMatrixTest(unittest.TestCase):
    def test_paired_outcomes_expose_gains_and_regressions(self) -> None:
        baseline = [
            {"sample_id": "a", "hit": False, "reciprocal_rank": 0.0},
            {"sample_id": "b", "hit": True, "reciprocal_rank": 0.5},
        ]
        current = [
            {"sample_id": "a", "hit": True, "reciprocal_rank": 1.0},
            {"sample_id": "b", "hit": True, "reciprocal_rank": 0.25},
        ]

        result = paired_outcomes(current, baseline)

        self.assertEqual(result["gained_hit"], 1)
        self.assertEqual(result["improved_reciprocal_rank"], 1)
        self.assertEqual(result["worsened_reciprocal_rank"], 1)


if __name__ == "__main__":
    unittest.main()
