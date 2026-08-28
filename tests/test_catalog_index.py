from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.local_search_backend import LocalProductSearchBackend
from starter.shopping_agent.models import Attribute
from tests.fixtures import build_test_artifacts, sample_products


class CatalogIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self._fixture_number = 0

    def _open_index(
        self,
        products: list[dict[str, object]],
    ) -> CatalogIndex:
        self._fixture_number += 1
        directory = self.root / str(self._fixture_number)
        directory.mkdir()
        catalog_path, artifact_path = build_test_artifacts(
            directory,
            products,
        )
        index = CatalogIndex(LocalProductSearchBackend.open(
            catalog_path,
            artifact_path,
        ))
        self.addCleanup(index.close)
        return index

    def test_close_releases_the_sqlite_connection(self) -> None:
        index = self._open_index(sample_products())

        index.close()

        with self.assertRaises(sqlite3.ProgrammingError):
            index.get_products(("BOOT-1",))

    def test_catalog_exposes_normalized_metadata_vocabularies(self) -> None:
        index = self._open_index(sample_products())

        self.assertEqual(
            index.values_for(Attribute.MATERIAL),
            ("leather", "rubber", "synthetic"),
        )

    def test_catalog_preserves_opaque_product_identifier_case(self) -> None:
        products = sample_products()
        products[0]["parent_asin"] = "MiXeD-1"
        index = self._open_index(products)

        loaded = index.get_products(("MiXeD-1",))

        self.assertEqual(loaded[0].parent_asin, "MiXeD-1")

    def test_catalog_treats_display_only_prices_as_unknown(self) -> None:
        products = sample_products()[:2]
        products[0]["price"] = "—"
        products[1]["price"] = "from 12.99"
        index = self._open_index(products)

        loaded = index.get_products(("BOOT-1", "BOOT-2"))

        self.assertEqual(
            tuple(product.price for product in loaded),
            (None, None),
        )

    def test_catalog_exposes_artifact_fingerprint(self) -> None:
        index = self._open_index(sample_products())

        self.assertEqual(len(index.fingerprint), 64)


if __name__ == "__main__":
    unittest.main()
