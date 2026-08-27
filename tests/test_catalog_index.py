from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import Attribute
from tests.fixtures import sample_products, write_catalog


class CatalogIndexTest(unittest.TestCase):
    def test_catalog_search_prefers_title_then_features(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = CatalogIndex.from_path(
                write_catalog(Path(directory), sample_products())
            )

            rows = index.search_fts(("winter", "boot"), limit=10)

            self.assertEqual(rows[0].parent_asin, "BOOT-1")
            self.assertEqual(rows[1].parent_asin, "BOOT-2")

    def test_quality_fallback_is_complete_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = CatalogIndex.from_path(
                write_catalog(Path(directory), sample_products())
            )

            first = index.quality_fallback(category="boots", limit=10)
            second = index.quality_fallback(category="boots", limit=10)

            self.assertEqual(len(first), 10)
            self.assertEqual(first, second)
            self.assertEqual(first[0].parent_asin, "BOOT-1")

    def test_catalog_exposes_normalized_metadata_vocabularies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = CatalogIndex.from_path(
                write_catalog(Path(directory), sample_products())
            )

            self.assertEqual(
                index.values_for(Attribute.MATERIAL),
                ("leather", "rubber", "synthetic"),
            )
            leather_products = index.products_for(Attribute.MATERIAL, "Leather")
            self.assertEqual(
                tuple(product.parent_asin for product in leather_products),
                ("BOOT-1",),
            )

    def test_catalog_preserves_opaque_product_identifier_case(self) -> None:
        products = sample_products()
        products[0]["parent_asin"] = "MiXeD-1"
        with tempfile.TemporaryDirectory() as directory:
            index = CatalogIndex.from_path(write_catalog(Path(directory), products))

            self.assertEqual(index.products[0].parent_asin, "MiXeD-1")


if __name__ == "__main__":
    unittest.main()
