from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.constraint_extractor import (
    ConstraintExtractor,
    _resolve_phrase,
)
from starter.shopping_agent.local_search_backend import LocalProductSearchBackend
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    EvidenceKind,
    Strength,
    UpdateAction,
)
from tests.fixtures import build_test_artifacts, sample_products


def extractor_products() -> list[dict[str, object]]:
    """A catalog where each metadata value appears often enough to survive the
    document-frequency floor.

    The shared ``sample_products`` catalog records ``leather``/``black``/
    ``rubber``/``brown`` on a single product each (document frequency 1), which
    the gazetteer now treats as data-entry noise and drops. These extraction
    tests exercise real classification of those words, so they need a catalog
    where the values are attested more than once.
    """
    products: list[dict[str, object]] = []
    specs = (
        ("leather", "black"),
        ("rubber", "brown"),
        ("synthetic", "gray"),
    )
    number = 1
    for material, color in specs:
        for _ in range(4):
            products.append({
                "parent_asin": f"BOOT-{number}",
                "title": f"{color} {material} boot",
                "features": ["basic footwear"],
                "details": {"material": material, "color": color},
                "description": ["General use"],
                "categories": ["Clothing", "Boots"],
                "store": "Example",
                "average_rating": 4.0,
                "rating_number": 100,
                "price": 50.0 + number,
            })
            number += 1
    return products


class ResolvePhraseTest(unittest.TestCase):
    """The pure document-frequency classification rule (no catalog needed)."""

    def test_structured_attribute_beats_the_feature_bucket(self) -> None:
        # "cotton": category 28, material 103, feature 215. Feature is the
        # free-text residual bucket; the strongest structured reading wins.
        resolved = _resolve_phrase("cotton", {
            Attribute.CATEGORY: ("cotton", 28),
            Attribute.MATERIAL: ("cotton", 103),
            Attribute.FEATURE: ("cotton", 215),
        })
        self.assertEqual(resolved, ("cotton", Attribute.MATERIAL))

    def test_feature_is_the_residual_class_when_no_structured_survives(self) -> None:
        # "lace": only a singleton material claim (below floor) plus feature.
        resolved = _resolve_phrase("lace", {
            Attribute.MATERIAL: ("lace", 1),
            Attribute.FEATURE: ("lace", 86),
        })
        self.assertEqual(resolved, ("lace", Attribute.FEATURE))

    def test_highest_document_frequency_structured_reading_wins(self) -> None:
        resolved = _resolve_phrase("silver", {
            Attribute.COLOR: ("silver", 145),
            Attribute.MATERIAL: ("silver", 8),
            Attribute.FEATURE: ("silver", 3),
        })
        self.assertEqual(resolved, ("silver", Attribute.COLOR))

    def test_size_is_exempt_from_the_document_frequency_floor(self) -> None:
        # A rare size still resolves as a size (mirrors the old single-letter
        # size exemption); other single-occurrence structured values do not.
        resolved = _resolve_phrase("one size", {
            Attribute.SIZE: ("one size", 1),
            Attribute.COLOR: ("one size", 1),
        })
        self.assertEqual(resolved, ("one size", Attribute.SIZE))

    def test_document_frequency_tie_breaks_by_attribute_priority(self) -> None:
        resolved = _resolve_phrase("navy", {
            Attribute.COLOR: ("navy", 5),
            Attribute.STYLE: ("navy", 5),
        })
        self.assertEqual(resolved, ("navy", Attribute.COLOR))

    def test_single_token_junk_below_floor_is_dropped(self) -> None:
        self.assertIsNone(_resolve_phrase("zzz", {Attribute.BRAND: ("zzz", 1)}))

    def test_multi_token_value_below_floor_is_kept(self) -> None:
        # A multi-word phrase is specific and will not fire from incidental
        # sentence words, so it survives even at document frequency 1.
        resolved = _resolve_phrase("chelsea boot", {
            Attribute.CATEGORY: ("chelsea boot", 1),
        })
        self.assertEqual(resolved, ("chelsea boot", Attribute.CATEGORY))

    def test_stopwords_never_classify(self) -> None:
        # Function words that are also junk catalog values (brand "on", color
        # "a") must not manufacture constraints.
        self.assertIsNone(_resolve_phrase("on", {Attribute.BRAND: ("on", 7)}))
        self.assertIsNone(_resolve_phrase("a", {Attribute.COLOR: ("a", 3)}))

    def test_single_character_non_size_is_dropped(self) -> None:
        self.assertIsNone(_resolve_phrase("d", {Attribute.COLOR: ("d", 2)}))
        self.assertEqual(
            _resolve_phrase("l", {Attribute.SIZE: ("l", 1)}),
            ("l", Attribute.SIZE),
        )

    def test_original_value_is_preserved_over_the_canonical_phrase(self) -> None:
        # The gazetteer canonicalizes to a token-joined phrase, but the emitted
        # value must be the original catalog string (case/spacing intact).
        resolved = _resolve_phrase("faux fur", {
            Attribute.MATERIAL: ("Faux Fur", 12),
        })
        self.assertEqual(resolved, ("Faux Fur", Attribute.MATERIAL))


class ConstraintExtractorTest(unittest.TestCase):
    def test_evidence_kinds_distinguish_anchor_preference_and_exclusion(self) -> None:
        updates = self.extractor.extract(
            "I need black boots but not leather",
            turn=1,
            asked_attribute=None,
        )
        evidence_by_value = {
            update.value: update.evidence_kind
            for update in updates
            if update.value is not None
        }

        self.assertEqual(evidence_by_value["boots"], EvidenceKind.CATEGORY_ANCHOR)
        self.assertEqual(
            evidence_by_value["black"],
            EvidenceKind.EXPLICIT_REQUIREMENT,
        )
        self.assertEqual(evidence_by_value["leather"], EvidenceKind.EXCLUSION)

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self._fixture_number = 0
        self.index = self.open_index(extractor_products())
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

    def test_common_word_metadata_values_do_not_become_constraints(self) -> None:
        # The catalog contains junk single-word metadata values that collide
        # with ordinary English ("key" as a brand, "m"/"a" as a color). These
        # must not be extracted from incidental sentence words, or they pollute
        # the lexical query and bury the true target.
        products = sample_products()
        products[0]["details"] = {"material": "leather", "color": "black"}
        products[0]["store"] = "key"
        products[1]["details"] = {"material": "leather", "color": "m"}
        index = self.open_index(products)
        extractor = ConstraintExtractor(index)

        updates = extractor.extract(
            "I need leather wallets. A key requirement is durability.",
            turn=1,
            asked_attribute=None,
        )
        values = {
            (update.attribute, update.value)
            for update in updates
            if update.value is not None
        }

        self.assertNotIn((Attribute.BRAND, "key"), values)
        self.assertNotIn((Attribute.COLOR, "m"), values)
        self.assertIn((Attribute.MATERIAL, "leather"), values)

    def test_negation_and_override_are_distinct_updates(self) -> None:
        updates = self.extractor.extract(
            "Actually ignore leather; I need canvas",
            turn=3,
            asked_attribute=None,
        )

        self.assertEqual(
            [(update.action, update.value) for update in updates],
            [
                (UpdateAction.RETRACT_PROVISIONAL, None),
                (UpdateAction.REMOVE, "leather"),
                (UpdateAction.SET, "canvas"),
            ],
        )
        self.assertTrue(
            all(
                update.attribute is Attribute.MATERIAL
                for update in updates[1:]
            )
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

    def test_verbose_decline_replies_are_declines_not_constraints(self) -> None:
        # The evaluator's boundary/decline replies are full sentences, not the
        # short "no preference". They must decline the asked attribute rather
        # than becoming a literal attribute value.
        for reply in (
            "I don't have an additional preference for brand.",
            "I don't have a preference for brand; please use your judgment.",
            "I don't have a preference for brand, please use your judgment.",
        ):
            update = self.extractor.extract(
                reply, turn=2, asked_attribute=Attribute.BRAND
            )[0]
            self.assertEqual(
                (update.action, update.attribute, update.value),
                (UpdateAction.DECLINE, Attribute.BRAND, None),
                msg=reply,
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

    def test_correction_emits_typed_provisional_retraction(self) -> None:
        updates = self.extractor.extract(
            "Actually I need black boots", turn=3, asked_attribute=None
        )

        self.assertIs(updates[0].action, UpdateAction.RETRACT_PROVISIONAL)
        self.assertIsNone(updates[0].attribute)
        self.assertTrue(all(update.preference_group_id for update in updates))


if __name__ == "__main__":
    unittest.main()
