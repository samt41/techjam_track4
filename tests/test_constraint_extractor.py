from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.constraint_extractor import ConstraintExtractor
from starter.shopping_agent.local_search_backend import LocalProductSearchBackend
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    Strength,
    UpdateAction,
)
from tests.fixtures import build_test_artifacts, sample_products


class ConstraintExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self._fixture_number = 0
        self.index = self.open_index(sample_products())
        self.extractor = ConstraintExtractor(self.index)

    def open_index(self, products: list[dict[str, object]]) -> CatalogIndex:
        self._fixture_number += 1
        directory = Path(self.temporary_directory.name) / str(self._fixture_number)
        directory.mkdir()
        catalog_path, artifact_path = build_test_artifacts(directory, products)
        index = CatalogIndex(LocalProductSearchBackend.open(
            catalog_path,
            artifact_path,
        ))
        self.addCleanup(index.close)
        return index

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

    def test_extraction_does_not_compile_patterns_per_catalog_value(self) -> None:
        with patch(
            "starter.shopping_agent.constraint_extractor.re.compile",
            wraps=__import__("re").compile,
        ) as compile_pattern:
            self.extractor.extract(
                "I need black leather boots",
                turn=1,
                asked_attribute=None,
            )

        self.assertLessEqual(compile_pattern.call_count, 5)

    def test_stopword_like_catalog_values_do_not_become_constraints(self) -> None:
        products = sample_products()
        products[0]["details"] = {"material": "leather", "color": "i"}
        index = self.open_index(products)
        extractor = ConstraintExtractor(index)

        updates = extractor.extract("I need boots", turn=1, asked_attribute=None)

        self.assertNotIn("i", [update.value for update in updates])

    def test_slate_feedback_is_not_extracted_as_new_intent(self) -> None:
        updates = self.extractor.extract(
            "show me others", turn=2, asked_attribute=None
        )

        self.assertEqual(updates, ())

    def test_correction_marks_updates_as_intent_override(self) -> None:
        updates = self.extractor.extract(
            "Actually I need black boots", turn=3, asked_attribute=None
        )

        self.assertTrue(updates)
        self.assertTrue(all(update.intent_override for update in updates))


if __name__ == "__main__":
    unittest.main()
