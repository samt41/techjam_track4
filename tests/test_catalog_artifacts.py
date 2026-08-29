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
    _feature_material_tokens,
    _keyed_feature_value,
    _keyed_feature_vocabulary,
    _material_vocabulary,
    _with_recovered_keyed_features,
    _with_recovered_materials,
)
from starter.shopping_agent.build_catalog_artifacts import main
from starter.shopping_agent.models import Attribute, ProductRecord
from tests.fixtures import sample_products, write_catalog


def _product(features: tuple[str, ...], material: str | None = None) -> ProductRecord:
    details = ((Attribute.MATERIAL.value, material),) if material else ()
    return ProductRecord(
        parent_asin="X",
        title="item",
        categories=("boots",),
        features=features,
        description="",
        details=details,
        store="store",
        price=None,
        average_rating=None,
        rating_number=0,
        searchable_text="",
    )


class MaterialCanonicalizationTest(unittest.TestCase):
    _VOCAB = frozenset({"leather", "textile", "cotton", "fur", "synthetic"})

    def test_percentage_and_qualifier_prefixes_resolve_to_the_material(self) -> None:
        for feature in ("100% leather", "faux leather", "genuine leather", "soft leather"):
            self.assertEqual(
                _feature_material_tokens((feature,), self._VOCAB),
                ("leather",),
                msg=feature,
            )

    def test_component_phrases_do_not_resolve_to_the_material(self) -> None:
        for feature in ("leather sole", "leather lining", "leather upper"):
            self.assertEqual(
                _feature_material_tokens((feature,), self._VOCAB),
                (),
                msg=feature,
            )

    def test_blend_contributes_every_material_token(self) -> None:
        self.assertEqual(
            _feature_material_tokens(("100% leather and textile",), self._VOCAB),
            ("leather", "textile"),
        )

    def test_material_outside_the_vocabulary_is_ignored(self) -> None:
        self.assertEqual(_feature_material_tokens(("titanium",), self._VOCAB), ())

    def test_vocabulary_requires_repeated_single_token_material_values(self) -> None:
        products = (
            _product((), material="leather"),
            _product((), material="leather"),
            _product((), material="titanium"),
            _product((), material="faux fur"),
        )
        self.assertEqual(_material_vocabulary(products), frozenset({"leather"}))

    def test_recovered_material_is_added_to_details(self) -> None:
        # The gate reads product.details, so the recovered material must land
        # there (not only in the attributes table) or the product is retrieved
        # then rejected.
        product = _product(("100% leather", "buckle closure"))
        augmented = _with_recovered_materials(product, self._VOCAB)
        materials = [v for k, v in augmented.details if k == Attribute.MATERIAL.value]
        self.assertEqual(materials, ["leather"])

    def test_existing_structured_material_is_not_duplicated(self) -> None:
        product = _product(("100% leather",), material="leather")
        augmented = _with_recovered_materials(product, self._VOCAB)
        materials = [v for k, v in augmented.details if k == Attribute.MATERIAL.value]
        self.assertEqual(materials, ["leather"])

    def test_feature_only_material_becomes_filterable(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = Path(temporary_directory.name)
        seed = [
            {
                "parent_asin": f"SEED-{n}",
                "title": "leather boot",
                "features": ["durable"],
                "details": {"material": "leather", "color": "black"},
                "categories": ["Clothing", "Boots"],
                "store": "Example",
                "average_rating": 4.5,
                "rating_number": 100,
                "price": 90.0,
            }
            for n in range(2)
        ]
        feature_only = [
            {
                "parent_asin": f"BELT-{n}",
                "title": "leather belt",
                "features": ["100% leather", "buckle closure"],
                "details": {"color": "brown"},
                "categories": ["Clothing", "Belts"],
                "store": "Example",
                "average_rating": 4.5,
                "rating_number": 100,
                "price": 40.0,
            }
            for n in range(3)
        ]
        catalog_path = write_catalog(root, seed + feature_only)
        artifact_path = root / "catalog.artifacts"
        CatalogArtifactBuilder().build(catalog_path, artifact_path)
        loaded = LoadedCatalogArtifacts.open(catalog_path, artifact_path)
        self.addCleanup(loaded.close)

        material_rows = loaded.connection.execute(
            "SELECT COUNT(*) FROM attributes WHERE attribute = 'material' AND value = 'leather'"
        ).fetchone()[0]
        # The stored details_json (what the runtime gate reads) also carries it.
        belt_details = loaded.connection.execute(
            "SELECT details_json FROM products WHERE parent_asin = 'BELT-0'"
        ).fetchone()[0]

        self.assertEqual(material_rows, 5)
        self.assertIn("leather", belt_details)


class KeyedFeatureRecoveryTest(unittest.TestCase):
    def test_parses_a_short_keyed_value(self) -> None:
        self.assertEqual(
            _keyed_feature_value("color: black"),
            (Attribute.COLOR, "black"),
        )
        self.assertEqual(
            _keyed_feature_value("size : medium"),
            (Attribute.SIZE, "medium"),
        )

    def test_drops_a_trailing_second_key(self) -> None:
        # "gucci model: gg0163sk" must reduce to the brand-style head, and a
        # semicolon-joined second attribute must not leak in.
        self.assertEqual(
            _keyed_feature_value("style: pumps; material: leather"),
            (Attribute.STYLE, "pumps"),
        )

    def test_rejects_marketing_sentences_and_unknown_keys(self) -> None:
        self.assertIsNone(
            _keyed_feature_value("material: 100% quality controlled before packaging"),
        )
        self.assertIsNone(_keyed_feature_value("care: hand wash only"))
        self.assertIsNone(_keyed_feature_value("a plain feature phrase"))

    def test_vocabulary_requires_a_recurring_value(self) -> None:
        products = (
            _product(("color: black",)),
            _product(("color: black",)),
            _product(("color: chartreuse",)),  # single occurrence, below floor
        )
        vocabulary = _keyed_feature_vocabulary(products)
        self.assertIn((Attribute.COLOR, "black"), vocabulary)
        self.assertNotIn((Attribute.COLOR, "chartreuse"), vocabulary)

    def test_recovered_value_is_added_to_details(self) -> None:
        product = _product(("color: black", "some other feature"))
        vocabulary = frozenset({(Attribute.COLOR, "black")})
        augmented = _with_recovered_keyed_features(product, vocabulary)
        colors = [v for k, v in augmented.details if k == Attribute.COLOR.value]
        self.assertEqual(colors, ["black"])

    def test_value_outside_vocabulary_is_not_added(self) -> None:
        product = _product(("color: chartreuse",))
        augmented = _with_recovered_keyed_features(product, frozenset())
        self.assertEqual(augmented.details, product.details)


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
