from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import Attribute
from tests.fixtures import sample_products, write_catalog


class CatalogIndexTest(unittest.TestCase):
    def _open_index(self, directory: str, products: list[dict[str, object]]) -> CatalogIndex:
        index = CatalogIndex.from_path(write_catalog(Path(directory), products))
        self.addCleanup(index.close)
        return index

    def test_close_releases_the_sqlite_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = self._open_index(directory, sample_products())

            index.close()

            with self.assertRaises(sqlite3.ProgrammingError):
                index.search_fts(("boot",), limit=1)

    def test_catalog_search_prefers_title_then_features(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = self._open_index(directory, sample_products())

            rows = index.search_fts(("winter", "boot"), limit=10)

            self.assertEqual(rows[0].parent_asin, "BOOT-1")
            self.assertEqual(rows[1].parent_asin, "BOOT-2")

    def test_quality_fallback_is_complete_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = self._open_index(directory, sample_products())

            first = index.quality_fallback(category="boots", limit=10)
            second = index.quality_fallback(category="boots", limit=10)

            self.assertEqual(len(first), 10)
            self.assertEqual(first, second)
            self.assertEqual(first[0].parent_asin, "BOOT-1")

    def test_quality_fallback_reuses_immutable_category_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = self._open_index(directory, sample_products())
            with patch(
                "starter.shopping_agent.catalog_index._quality_score",
                wraps=__import__(
                    "starter.shopping_agent.catalog_index",
                    fromlist=["_quality_score"],
                )._quality_score,
            ) as quality_score:
                index.quality_fallback(category="boots", limit=10)
                index.quality_fallback(category="boots", limit=5)

            self.assertLessEqual(quality_score.call_count, len(index.products))

    def test_catalog_exposes_normalized_metadata_vocabularies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = self._open_index(directory, sample_products())

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
            index = self._open_index(directory, products)

            self.assertEqual(index.products[0].parent_asin, "MiXeD-1")

    def test_catalog_treats_display_only_prices_as_unknown(self) -> None:
        products = sample_products()[:2]
        products[0]["price"] = "—"
        products[1]["price"] = "from 12.99"
        with tempfile.TemporaryDirectory() as directory:
            index = self._open_index(directory, products)

            self.assertEqual(
                tuple(product.price for product in index.products),
                (None, None),
            )


if __name__ == "__main__":
    unittest.main()
