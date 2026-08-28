from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.constraint_extractor import ConstraintExtractor
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    Strength,
    UpdateAction,
)
from tests.fixtures import sample_products, write_catalog


class ConstraintExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        catalog_path = write_catalog(
            Path(self.temporary_directory.name),
            sample_products(),
        )
        self.extractor = ConstraintExtractor(CatalogIndex.from_path(catalog_path))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_negation_and_override_are_distinct_updates(self) -> None:
        updates = self.extractor.extract(
            "Actually ignore leather; I need canvas",
            turn=3,
            asked_attribute=None,
        )

        self.assertEqual(
            [(update.action, update.value) for update in updates],
            [
                (UpdateAction.REMOVE, "leather"),
                (UpdateAction.SET, "canvas"),
            ],
        )
        self.assertTrue(
            all(update.attribute is Attribute.MATERIAL for update in updates)
        )

    def test_hard_soft_and_negative_cues_have_distinct_semantics(self) -> None:
        must_update = self.extractor.extract(
            "It must be leather", turn=1, asked_attribute=None
        )[0]
        prefer_update = self.extractor.extract(
            "I prefer black", turn=1, asked_attribute=None
        )[0]
        negative_update = self.extractor.extract(
            "Not leather, but black is fine", turn=1, asked_attribute=None
        )[0]

        self.assertEqual(
            (must_update.attribute, must_update.strength, must_update.confidence),
            (Attribute.MATERIAL, Strength.HARD, 0.92),
        )
        self.assertEqual(
            (prefer_update.attribute, prefer_update.strength, prefer_update.confidence),
            (Attribute.COLOR, Strength.SOFT, 0.80),
        )
        self.assertEqual(
            (negative_update.value, negative_update.excluded, negative_update.confidence),
            ("leather", True, 0.98),
        )

    def test_price_bounds_use_comparison_operators(self) -> None:
        upper = self.extractor.extract(
            "Keep it under $100", turn=1, asked_attribute=None
        )[0]
        lower = self.extractor.extract(
            "At least 40 dollars", turn=2, asked_attribute=None
        )[0]

        self.assertEqual(
            (upper.attribute, upper.operator, upper.value),
            (Attribute.BUDGET, ComparisonOperator.LESS_THAN_OR_EQUAL, "100"),
        )
        self.assertEqual(
            (lower.attribute, lower.operator, lower.value),
            (Attribute.BUDGET, ComparisonOperator.GREATER_THAN_OR_EQUAL, "40"),
        )

    def test_short_answer_uses_asked_attribute(self) -> None:
        update = self.extractor.extract(
            "canvas", turn=2, asked_attribute=Attribute.MATERIAL
        )[0]

        self.assertEqual(
            (update.action, update.attribute, update.value, update.confidence),
            (UpdateAction.SET, Attribute.MATERIAL, "canvas", 0.98),
        )

    def test_no_preference_declines_asked_attribute(self) -> None:
        update = self.extractor.extract(
            "no preference", turn=2, asked_attribute=Attribute.COLOR
        )[0]

        self.assertEqual(
            (update.action, update.attribute, update.value),
            (UpdateAction.DECLINE, Attribute.COLOR, None),
        )

    def test_negation_scope_stops_at_contrast_word(self) -> None:
        updates = self.extractor.extract(
            "not leather but rubber", turn=1, asked_attribute=None
        )

        self.assertEqual(
            [(update.value, update.excluded) for update in updates],
            [("leather", True), ("rubber", False)],
        )


if __name__ == "__main__":
    unittest.main()
