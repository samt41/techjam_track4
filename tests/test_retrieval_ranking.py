from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    PreferenceUpdate,
    RetrievalRoute,
    Strength,
    UpdateAction,
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


if __name__ == "__main__":
    unittest.main()
