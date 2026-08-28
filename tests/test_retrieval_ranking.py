from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.local_search_backend import LocalProductSearchBackend
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    PreferenceUpdate,
    ProductCandidate,
    RecommendationHistory,
    RetrievalRoute,
    RouteEvidence,
    Strength,
    UpdateAction,
)
from starter.shopping_agent.preference_ledger import PreferenceLedger
from starter.shopping_agent.ranking import EligibilityGate, ProductRanker
from starter.shopping_agent.retrieval import RetrievalPlanner, execute_search_plan
from tests.fixtures import build_test_artifacts, sample_products


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
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        catalog_path, artifact_path = build_test_artifacts(
            Path(temporary_directory.name),
            sample_products(),
        )
        self.index = CatalogIndex(LocalProductSearchBackend.open(
            catalog_path,
            artifact_path,
        ))
        self.addCleanup(self.index.close)

    def test_strict_routes_share_one_immutable_hard_filter_tuple(self) -> None:
        intent = PreferenceLedger().apply((
            preference(Attribute.CATEGORY, "boots"),
            preference(Attribute.MATERIAL, "leather"),
        ))

        plans = RetrievalPlanner().strict(intent)

        self.assertEqual(
            {plan.request.route for plan in plans},
            {
                RetrievalRoute.METADATA,
                RetrievalRoute.EXACT_FTS,
                RetrievalRoute.EXPANDED_FTS,
                RetrievalRoute.CATEGORY_FALLBACK,
            },
        )
        shared_filters = plans[0].request.filters
        self.assertTrue(all(
            plan.request.filters is shared_filters for plan in plans
        ))
        self.assertEqual(
            {structured_filter.constraint_id for structured_filter in shared_filters},
            {constraint.constraint_id for constraint in intent.active_constraints},
        )

    def test_backend_plan_returns_ranked_route_evidence(self) -> None:
        intent = PreferenceLedger().apply((
            preference(Attribute.MATERIAL, "leather"),
        ))
        plan = next(
            plan
            for plan in RetrievalPlanner().strict(intent)
            if plan.request.route is RetrievalRoute.METADATA
        )

        candidates = execute_search_plan(self.index.backend, plan)

        self.assertEqual(candidates[0].parent_asin, "BOOT-1")
        self.assertEqual(candidates[0].evidence[0].rank, 1)
        self.assertIs(candidates[0].evidence[0].route, RetrievalRoute.METADATA)

    def test_eligibility_enforces_hard_exclusions_and_price_bounds(self) -> None:
        intent = PreferenceLedger().apply((
            preference(Attribute.MATERIAL, "leather", excluded=True),
            preference(
                Attribute.BUDGET,
                "80",
                operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
            ),
        ))
        leather, affordable = self.index.get_products(("BOOT-1", "BOOT-2"))
        gate = EligibilityGate()

        leather_decision = gate.evaluate(leather, intent.active_constraints)
        affordable_decision = gate.evaluate(affordable, intent.active_constraints)

        self.assertFalse(leather_decision.eligible)
        self.assertIn(
            "excluded:material:leather",
            leather_decision.rejection_reasons,
        )
        self.assertTrue(affordable_decision.eligible)

    def test_ranker_fuses_duplicate_candidates_and_prioritizes_eligible(self) -> None:
        intent = PreferenceLedger().apply((
            preference(Attribute.CATEGORY, "boots"),
        ))
        candidates = tuple(
            candidate
            for plan in RetrievalPlanner().strict(intent)
            for candidate in execute_search_plan(self.index.backend, plan)
        )

        ranked = ProductRanker(self.index.backend).rank(
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

    def test_ranker_places_every_strict_product_before_exploration(self) -> None:
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

        ranked = ProductRanker(self.index.backend).rank(
            candidates,
            PreferenceLedger().intent,
            shown_product_ids=frozenset(),
            top_k=10,
        )

        self.assertEqual(sum(item.exact_match for item in ranked), 9)
        self.assertFalse(ranked[-1].exact_match)
        self.assertTrue(all(item.exact_match for item in ranked[:-1]))


if __name__ == "__main__":
    unittest.main()
