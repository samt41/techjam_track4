from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from starter.shopping_agent.catalog_artifacts import (
    ArtifactBuildError,
    ArtifactValidationError,
    CatalogArtifactBuilder,
    LoadedCatalogArtifacts,
)
from starter.shopping_agent.build_catalog_artifacts import main
from tests.fixtures import sample_products, write_catalog


class CatalogArtifactTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)

    def test_artifacts_are_atomic_and_catalog_bound(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())
        artifact_path = self.root / "catalog.artifacts"
        manifest = CatalogArtifactBuilder().build(catalog_path, artifact_path)

        loaded = LoadedCatalogArtifacts.open(catalog_path, artifact_path)
        self.addCleanup(loaded.close)
        self.assertEqual(loaded.manifest.catalog_sha256, manifest.catalog_sha256)

        products = sample_products()
        products.append({
            "parent_asin": "BOOT-EXTRA",
            "title": "Extra boot",
            "categories": ["Clothing", "Boots"],
        })
        write_catalog(self.root, products)

        with self.assertRaisesRegex(ArtifactValidationError, "fingerprint"):
            LoadedCatalogArtifacts.open(catalog_path, artifact_path)

    def test_builder_refuses_to_overwrite_artifacts(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())
        artifact_path = self.root / "catalog.artifacts"
        CatalogArtifactBuilder().build(catalog_path, artifact_path)

        with self.assertRaisesRegex(ArtifactBuildError, "overwrite"):
            CatalogArtifactBuilder().build(catalog_path, artifact_path)

    def test_failed_build_removes_temporary_directory(self) -> None:
        products = sample_products()
        products[0]["categories"] = "not-a-list"
        catalog_path = write_catalog(self.root, products)
        artifact_path = self.root / "catalog.artifacts"

        with self.assertRaisesRegex(ArtifactBuildError, "categories"):
            CatalogArtifactBuilder().build(catalog_path, artifact_path)

        self.assertFalse(artifact_path.exists())
        self.assertEqual(tuple(self.root.glob(".catalog.artifacts.tmp-*")), ())

    def test_build_is_byte_deterministic(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())

        first_manifest = CatalogArtifactBuilder().build(
            catalog_path,
            self.root / "first.artifacts",
        )
        second_manifest = CatalogArtifactBuilder().build(
            catalog_path,
            self.root / "second.artifacts",
        )

        self.assertEqual(first_manifest, second_manifest)

    def test_manifest_records_the_fixed_build_configuration(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())

        manifest = CatalogArtifactBuilder().build(
            catalog_path,
            self.root / "catalog.artifacts",
        )

        self.assertEqual(manifest.normalization_version, "nfkc-casefold-v1")
        self.assertEqual(manifest.fts_tokenizer, "unicode61-remove-diacritics-2")
        self.assertEqual(manifest.title_weight, 6.0)
        self.assertEqual(manifest.posting_batch_size, 1_000)

    def test_database_preserves_identifiers_and_normalized_fields(self) -> None:
        products = sample_products()
        products[0]["title"] = "  BLACK   Winter BOOT  "
        products[0]["price"] = "not-a-price"
        catalog_path = write_catalog(self.root, products)
        artifact_path = self.root / "catalog.artifacts"
        CatalogArtifactBuilder().build(catalog_path, artifact_path)

        loaded = LoadedCatalogArtifacts.open(catalog_path, artifact_path)
        self.addCleanup(loaded.close)
        row = loaded.connection.execute(
            "SELECT parent_asin, title, price FROM products WHERE ordinal = 0"
        ).fetchone()

        self.assertEqual(row, ("BOOT-1", "black winter boot", None))

    def test_loader_skips_expensive_database_hash_but_checks_size(self) -> None:
        # The full-database SHA-256 is deliberately not verified on open (it
        # hashes ~575 MB every startup). The catalog fingerprint binds the
        # artifacts to their source, and a size mismatch still fails fast.
        catalog_path = write_catalog(self.root, sample_products())
        artifact_path = self.root / "catalog.artifacts"
        CatalogArtifactBuilder().build(catalog_path, artifact_path)
        database_path = artifact_path / "catalog.sqlite3"

        # A valid artifact opens without paying for a database hash.
        loaded = LoadedCatalogArtifacts.open(catalog_path, artifact_path)
        loaded.close()

        # A truncation (size change) is still rejected cheaply.
        database_path.write_bytes(database_path.read_bytes()[:-16])
        with self.assertRaisesRegex(ArtifactValidationError, "size"):
            LoadedCatalogArtifacts.open(catalog_path, artifact_path)

    def test_loaded_database_is_read_only_and_closable(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())
        artifact_path = self.root / "catalog.artifacts"
        CatalogArtifactBuilder().build(catalog_path, artifact_path)
        loaded = LoadedCatalogArtifacts.open(catalog_path, artifact_path)

        with self.assertRaisesRegex(Exception, "readonly|read-only"):
            loaded.connection.execute("DELETE FROM products")

        loaded.close()
        with self.assertRaisesRegex(Exception, "closed"):
            loaded.connection.execute("SELECT 1")

    def test_build_command_reports_fixed_artifact_measurements(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())
        artifact_path = self.root / "catalog.artifacts"
        output = io.StringIO()

        with redirect_stdout(output):
            return_code = main((
                "--catalog",
                str(catalog_path),
                "--output",
                str(artifact_path),
            ))

        self.assertEqual(return_code, 0)
        report = output.getvalue()
        self.assertIn("catalog_sha256=", report)
        self.assertIn("product_count=12", report)
        self.assertIn("database_size_bytes=", report)
        self.assertIn("fts5_built=", report)
        self.assertIn("elapsed_ms=", report)

    def test_build_command_returns_nonzero_when_output_exists(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())
        artifact_path = self.root / "catalog.artifacts"
        CatalogArtifactBuilder().build(catalog_path, artifact_path)
        errors = io.StringIO()

        with redirect_stderr(errors):
            return_code = main((
                "--catalog",
                str(catalog_path),
                "--output",
                str(artifact_path),
            ))

        self.assertEqual(return_code, 1)
        self.assertIn("overwrite", errors.getvalue())

    def test_fts_index_does_not_duplicate_source_text(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())
        artifact_path = self.root / "catalog.artifacts"
        manifest = CatalogArtifactBuilder().build(catalog_path, artifact_path)
        if not manifest.fts5_built:
            self.skipTest("SQLite runtime does not provide FTS5")
        loaded = LoadedCatalogArtifacts.open(catalog_path, artifact_path)
        self.addCleanup(loaded.close)

        create_sql = loaded.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'products_fts'"
        ).fetchone()[0]
        matching_row = loaded.connection.execute(
            "SELECT rowid FROM products_fts "
            "WHERE products_fts MATCH 'boot' ORDER BY rowid LIMIT 1"
        ).fetchone()

        self.assertIn("content=''", create_sql)
        self.assertIsNotNone(matching_row)


if __name__ == "__main__":
    unittest.main()
