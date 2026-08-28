from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    ProductCandidate,
    RouteEvidence,
    PreferenceUpdate,
    RetrievalRoute,
    Strength,
    UpdateAction,
    RecommendationHistory,
)
from starter.shopping_agent.preference_ledger import PreferenceLedger
from starter.shopping_agent.ranking import EligibilityGate, ProductRanker
from starter.shopping_agent.retrieval import CandidateGenerator, RetrievalPlanner
from tests.fixtures import sample_products, write_catalog


def preference(
    attribute: Attribute,
    value: str,
    *,
    operator: ComparisonOperator = ComparisonOperator.EQUALS,
    excluded: bool = False,
    strength: Strength = Strength.HARD,
) -> PreferenceUpdate:
    return PreferenceUpdate(
        action=UpdateAction.ADD,
        attribute=attribute,
        operator=operator,
        value=value,
        excluded=excluded,
        strength=strength,
        confidence=0.98 if strength is Strength.HARD else 0.80,
        source_turn=1,
        source_text=value,
    )


class RetrievalRankingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        path = write_catalog(Path(self.temporary_directory.name), sample_products())
        self.index = CatalogIndex.from_path(path)

    def tearDown(self) -> None:
        self.index.close()
        self.temporary_directory.cleanup()

    def test_strict_plans_cover_metadata_fts_and_fallback_routes(self) -> None:
        ledger = PreferenceLedger()
        intent = ledger.apply((
            preference(Attribute.CATEGORY, "boots"),
            preference(Attribute.MATERIAL, "leather"),
        ))

        plans = RetrievalPlanner().strict(intent)

        self.assertEqual(
            {plan.route for plan in plans},
            {
                RetrievalRoute.METADATA,
                RetrievalRoute.EXACT_FTS,
                RetrievalRoute.EXPANDED_FTS,
                RetrievalRoute.CATEGORY_FALLBACK,
            },
        )
        material_plan = next(
            plan
            for plan in plans
            if plan.route is RetrievalRoute.METADATA
            and plan.attribute is Attribute.MATERIAL
        )
        self.assertEqual(material_plan.attribute_value, "leather")

    def test_metadata_generator_returns_ranked_route_evidence(self) -> None:
        ledger = PreferenceLedger()
        intent = ledger.apply((preference(Attribute.MATERIAL, "leather"),))
        plan = next(
            plan
            for plan in RetrievalPlanner().strict(intent)
            if plan.route is RetrievalRoute.METADATA
        )

        candidates = CandidateGenerator(self.index).execute(plan)

        self.assertEqual(candidates[0].parent_asin, "BOOT-1")
        self.assertEqual(candidates[0].evidence[0].rank, 1)
        self.assertIs(candidates[0].evidence[0].route, RetrievalRoute.METADATA)

    def test_eligibility_enforces_hard_exclusions_and_price_bounds(self) -> None:
        ledger = PreferenceLedger()
        intent = ledger.apply((
            preference(Attribute.MATERIAL, "leather", excluded=True),
            preference(
                Attribute.BUDGET,
                "80",
                operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
            ),
        ))
        gate = EligibilityGate()

        leather = gate.evaluate(self.index.product_by_id["BOOT-1"], intent.active_constraints)
        affordable = gate.evaluate(self.index.product_by_id["BOOT-2"], intent.active_constraints)

        self.assertFalse(leather.eligible)
        self.assertIn("excluded:material:leather", leather.rejection_reasons)
        self.assertTrue(affordable.eligible)

    def test_ranker_fuses_duplicate_candidates_and_prioritizes_eligible(self) -> None:
        ledger = PreferenceLedger()
        intent = ledger.apply((preference(Attribute.CATEGORY, "boots"),))
        generator = CandidateGenerator(self.index)
        candidates = tuple(
            candidate
            for plan in RetrievalPlanner().strict(intent)
            for candidate in generator.execute(plan)
        )

        ranked = ProductRanker(self.index).rank(
            candidates,
            intent,
            shown_product_ids=frozenset(),
            top_k=10,
        )

        self.assertEqual(len(ranked), 10)
        self.assertEqual(len({item.parent_asin for item in ranked}), 10)
        self.assertTrue(all(item.exact_match for item in ranked))
        self.assertGreater(ranked[0].score, 0.0)

    def test_recommendation_history_is_scoped_to_intent_version(self) -> None:
        history = RecommendationHistory()
        history.record(intent_version=1, product_ids=("A", "B"))

        self.assertEqual(history.shown_for(intent_version=1), frozenset({"A", "B"}))
        self.assertEqual(history.shown_for(intent_version=2), frozenset())

    def test_counterfactual_plan_relaxes_exactly_one_nonexcluded_constraint(self) -> None:
        ledger = PreferenceLedger()
        intent = ledger.apply((
            preference(Attribute.MATERIAL, "leather"),
            preference(Attribute.COLOR, "black"),
            preference(Attribute.FEATURE, "slippery", excluded=True),
        ))
        excluded_id = next(
            constraint.constraint_id
            for constraint in intent.active_constraints
            if constraint.excluded
        )

        plans = RetrievalPlanner().counterfactuals(intent)

        self.assertTrue(plans)
        self.assertTrue(all(len(plan.relaxed_constraint_ids) == 1 for plan in plans))
        self.assertNotIn(
            excluded_id,
            [plan.relaxed_constraint_ids[0] for plan in plans],
        )
        self.assertTrue(all(
            plan.relaxed_constraint_ids[0] not in plan.required_constraint_ids
            for plan in plans
        ))

    def test_ranker_allocates_seven_strict_and_three_exploratory_slots(self) -> None:
        evidence = RouteEvidence(
            route=RetrievalRoute.EXACT_FTS,
            rank=1,
            score=1.0,
        )
        candidates = tuple(
            ProductCandidate(
                parent_asin=f"BOOT-{number}",
                evidence=(evidence,),
                relaxed_constraint_id=None if number <= 9 else "relaxed-material",
            )
            for number in range(1, 13)
        )

        ranked = ProductRanker(self.index).rank(
            candidates,
            PreferenceLedger().intent,
            shown_product_ids=frozenset(),
            top_k=10,
        )

        self.assertEqual(sum(item.exact_match for item in ranked), 7)
        self.assertEqual(sum(not item.exact_match for item in ranked), 3)
        self.assertTrue(all(item.exact_match for item in ranked[:7]))

    def test_counterfactual_candidate_crosses_only_its_named_constraint(self) -> None:
        ledger = PreferenceLedger()
        intent = ledger.apply((preference(Attribute.MATERIAL, "leather"),))
        plan = RetrievalPlanner().counterfactuals(intent)[0]
        candidates = CandidateGenerator(self.index).execute(plan)

        ranked = ProductRanker(self.index).rank(
            candidates,
            intent,
            shown_product_ids=frozenset(),
            top_k=10,
        )

        self.assertTrue(ranked)
        self.assertTrue(all(not item.exact_match for item in ranked))
        self.assertTrue(all(
            item.relaxed_constraint_id == plan.relaxed_constraint_ids[0]
            for item in ranked
        ))


if __name__ == "__main__":
    unittest.main()
