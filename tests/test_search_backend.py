from __future__ import annotations

import unittest
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory

from starter.shopping_agent.local_search_backend import LocalProductSearchBackend
from starter.shopping_agent.models import Attribute, ComparisonOperator, RetrievalRoute
from starter.shopping_agent.search_backend import (
    FacetBucket,
    FacetRequest,
    FacetResult,
    ProductSearchBackend,
    SearchHit,
    SearchRequest,
    SearchReason,
    SearchResult,
    StructuredFilter,
    TotalRelation,
)
from tests.fixtures import build_test_artifacts, excluded_prefix_products, sample_products


class SearchResultTest(unittest.TestCase):
    def test_exact_total_cannot_be_smaller_than_returned_hits(self) -> None:
        result = SearchResult(
            hits=(SearchHit(parent_asin="BOOT-1", score=1.0, rank=1),),
            total_matches=0,
            total_relation=TotalRelation.EXACT,
            route=RetrievalRoute.EXACT_FTS,
            reason=SearchReason.COMPLETED,
            work_consumed=1,
            elapsed_ms=0.1,
        )

        with self.assertRaisesRegex(ValueError, "total_matches"):
            result.validate()

    def test_duplicate_product_identifiers_are_rejected(self) -> None:
        result = SearchResult(
            hits=(
                SearchHit(parent_asin="BOOT-1", score=1.0, rank=1),
                SearchHit(parent_asin="BOOT-1", score=0.9, rank=2),
            ),
            total_matches=2,
            total_relation=TotalRelation.EXACT,
            route=RetrievalRoute.EXACT_FTS,
            reason=SearchReason.COMPLETED,
            work_consumed=2,
            elapsed_ms=0.1,
        )

        with self.assertRaisesRegex(ValueError, "unique"):
            result.validate()

    def test_hit_ranks_must_match_result_order(self) -> None:
        result = SearchResult(
            hits=(SearchHit(parent_asin="BOOT-1", score=1.0, rank=2),),
            total_matches=1,
            total_relation=TotalRelation.EXACT,
            route=RetrievalRoute.EXACT_FTS,
            reason=SearchReason.COMPLETED,
            work_consumed=1,
            elapsed_ms=0.1,
        )

        with self.assertRaisesRegex(ValueError, "rank"):
            result.validate()

    def test_non_finite_hit_score_is_rejected(self) -> None:
        result = SearchResult(
            hits=(SearchHit(parent_asin="BOOT-1", score=float("nan"), rank=1),),
            total_matches=1,
            total_relation=TotalRelation.EXACT,
            route=RetrievalRoute.EXACT_FTS,
            reason=SearchReason.COMPLETED,
            work_consumed=1,
            elapsed_ms=0.1,
        )

        with self.assertRaisesRegex(ValueError, "finite"):
            result.validate()


class SearchRequestTest(unittest.TestCase):
    def test_hard_filter_retains_originating_constraint(self) -> None:
        material_filter = StructuredFilter(
            constraint_id="material-leather",
            attribute=Attribute.MATERIAL,
            operator=ComparisonOperator.EQUALS,
            value="leather",
            excluded=False,
            confidence=0.95,
        )
        request = SearchRequest(
            route=RetrievalRoute.METADATA,
            lexical_terms=("boots",),
            filters=(material_filter,),
            limit=10,
            work_limit=1_000,
        )

        request.validate()

        self.assertEqual(request.filters[0].constraint_id, "material-leather")

    def test_filter_rejects_confidence_outside_probability_range(self) -> None:
        material_filter = StructuredFilter(
            constraint_id="material-leather",
            attribute=Attribute.MATERIAL,
            operator=ComparisonOperator.EQUALS,
            value="leather",
            excluded=False,
            confidence=1.1,
        )

        with self.assertRaisesRegex(ValueError, "confidence"):
            material_filter.validate()

    def test_hard_filter_rejects_provisional_confidence(self) -> None:
        material_filter = StructuredFilter(
            constraint_id="material-leather",
            attribute=Attribute.MATERIAL,
            operator=ComparisonOperator.EQUALS,
            value="leather",
            excluded=False,
            confidence=0.89,
        )

        with self.assertRaisesRegex(ValueError, "hard filter confidence"):
            material_filter.validate()

    def test_non_numeric_filter_rejects_range_operator(self) -> None:
        material_filter = StructuredFilter(
            constraint_id="material-leather",
            attribute=Attribute.MATERIAL,
            operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
            value="leather",
            excluded=False,
            confidence=1.0,
        )

        with self.assertRaisesRegex(ValueError, "range operator"):
            material_filter.validate()

    def test_budget_filter_rejects_non_finite_value(self) -> None:
        budget_filter = StructuredFilter(
            constraint_id="budget-nan",
            attribute=Attribute.BUDGET,
            operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
            value="nan",
            excluded=False,
            confidence=1.0,
        )

        with self.assertRaisesRegex(ValueError, "finite numeric"):
            budget_filter.validate()


class FacetContractTest(unittest.TestCase):
    def test_exact_facet_bucket_cannot_exceed_matching_population(self) -> None:
        result = FacetResult(
            buckets=(FacetBucket(attribute=Attribute.COLOR, value="black", count=2),),
            total_matches=1,
            total_relation=TotalRelation.EXACT,
            reason=SearchReason.COMPLETED,
            work_consumed=2,
            elapsed_ms=0.1,
        )

        with self.assertRaisesRegex(ValueError, "bucket count"):
            result.validate()

    def test_facet_request_requires_a_positive_work_limit(self) -> None:
        request = FacetRequest(
            filters=(),
            attributes=(Attribute.COLOR,),
            work_limit=0,
        )

        with self.assertRaisesRegex(ValueError, "work_limit"):
            request.validate()


class FixedContractShapeTest(unittest.TestCase):
    def test_contract_types_have_only_named_fields(self) -> None:
        contract_types = (
            StructuredFilter,
            SearchRequest,
            SearchHit,
            SearchResult,
            FacetRequest,
            FacetBucket,
            FacetResult,
        )

        for contract_type in contract_types:
            field_names = {field.name for field in fields(contract_type)}
            self.assertNotIn("payload", field_names)
            self.assertNotIn("metadata", field_names)

    def test_backend_protocol_exposes_the_fixed_operations(self) -> None:
        operation_names = {
            "catalog_fingerprint",
            "search",
            "facets",
            "get_products",
            "contains_product",
            "close",
        }

        self.assertTrue(operation_names.issubset(vars(ProductSearchBackend)))


class LocalSearchBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)

    def backend(
        self,
        products: list[dict[str, object]],
    ) -> LocalProductSearchBackend:
        catalog_path, artifact_path = build_test_artifacts(self.root, products)
        backend = LocalProductSearchBackend.open(catalog_path, artifact_path)
        self.addCleanup(backend.close)
        return backend

    def hard_filter(
        self,
        attribute: Attribute,
        value: str,
        *,
        excluded: bool = False,
        operator: ComparisonOperator = ComparisonOperator.EQUALS,
    ) -> StructuredFilter:
        return StructuredFilter(
            constraint_id=f"{attribute.value}-{operator.value}-{value}",
            attribute=attribute,
            operator=operator,
            value=value,
            excluded=excluded,
            confidence=1.0,
        )

    def test_quality_search_finds_valid_products_beyond_old_route_cap(self) -> None:
        backend = self.backend(excluded_prefix_products())
        request = SearchRequest(
            route=RetrievalRoute.CATEGORY_FALLBACK,
            lexical_terms=(),
            filters=(StructuredFilter(
                constraint_id="exclude-leather",
                attribute=Attribute.MATERIAL,
                operator=ComparisonOperator.EQUALS,
                value="leather",
                excluded=True,
                confidence=1.0,
            ),),
            limit=10,
            work_limit=50_000,
        )

        result = backend.search(request)

        self.assertEqual(len(result.hits), 10)
        self.assertEqual(result.total_matches, 50)
        self.assertTrue(
            all(hit.parent_asin.startswith("CANVAS-") for hit in result.hits)
        )

    def test_positive_attribute_filters_intersect(self) -> None:
        backend = self.backend(sample_products())
        request = SearchRequest(
            route=RetrievalRoute.METADATA,
            lexical_terms=(),
            filters=(
                self.hard_filter(Attribute.MATERIAL, "leather"),
                self.hard_filter(Attribute.COLOR, "black"),
            ),
            limit=10,
            work_limit=1_000,
        )

        result = backend.search(request)

        self.assertEqual(result.total_matches, 1)
        self.assertEqual(
            tuple(hit.parent_asin for hit in result.hits),
            ("BOOT-1",),
        )

    def test_positive_filter_and_exclusion_apply_together(self) -> None:
        backend = self.backend(sample_products())
        request = SearchRequest(
            route=RetrievalRoute.METADATA,
            lexical_terms=(),
            filters=(
                self.hard_filter(Attribute.CATEGORY, "boots"),
                self.hard_filter(Attribute.MATERIAL, "leather", excluded=True),
            ),
            limit=10,
            work_limit=1_000,
        )

        result = backend.search(request)

        self.assertEqual(result.total_matches, 11)
        self.assertNotIn("BOOT-1", tuple(hit.parent_asin for hit in result.hits))

    def test_upper_and_lower_price_bounds_are_pushed_down(self) -> None:
        backend = self.backend(sample_products())
        request = SearchRequest(
            route=RetrievalRoute.METADATA,
            lexical_terms=(),
            filters=(
                self.hard_filter(
                    Attribute.BUDGET,
                    "50",
                    operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                ),
                self.hard_filter(
                    Attribute.BUDGET,
                    "70",
                    operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
                ),
            ),
            limit=10,
            work_limit=1_000,
        )

        result = backend.search(request)

        self.assertEqual(result.total_matches, 4)
        self.assertEqual(
            {hit.parent_asin for hit in result.hits},
            {"BOOT-2", "BOOT-10", "BOOT-11", "BOOT-12"},
        )

    def test_unknown_price_is_ineligible_for_hard_budget(self) -> None:
        products = sample_products()
        products[1]["price"] = None
        backend = self.backend(products)
        request = SearchRequest(
            route=RetrievalRoute.METADATA,
            lexical_terms=(),
            filters=(self.hard_filter(
                Attribute.BUDGET,
                "70",
                operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
            ),),
            limit=20,
            work_limit=1_000,
        )

        result = backend.search(request)

        self.assertEqual(result.total_matches, 10)
        self.assertNotIn("BOOT-2", tuple(hit.parent_asin for hit in result.hits))

    def test_equal_quality_products_use_stable_identifier_order(self) -> None:
        products = [
            {"parent_asin": "PRODUCT-Z", "title": "Boot"},
            {"parent_asin": "PRODUCT-A", "title": "Boot"},
        ]
        backend = self.backend(products)
        request = SearchRequest(
            route=RetrievalRoute.CATEGORY_FALLBACK,
            lexical_terms=(),
            filters=(),
            limit=10,
            work_limit=1_000,
        )

        result = backend.search(request)

        self.assertEqual(
            tuple(hit.parent_asin for hit in result.hits),
            ("PRODUCT-A", "PRODUCT-Z"),
        )

    def test_facet_counts_use_the_same_hard_filters(self) -> None:
        backend = self.backend(sample_products())
        request = FacetRequest(
            filters=(
                self.hard_filter(Attribute.CATEGORY, "boots"),
                self.hard_filter(Attribute.MATERIAL, "leather", excluded=True),
            ),
            attributes=(Attribute.MATERIAL,),
            work_limit=1_000,
        )

        result = backend.facets(request)

        self.assertEqual(result.total_matches, 11)
        self.assertEqual(
            result.buckets,
            (
                FacetBucket(attribute=Attribute.MATERIAL, value="synthetic", count=10),
                FacetBucket(attribute=Attribute.MATERIAL, value="rubber", count=1),
            ),
        )

    def test_product_lookup_preserves_requested_identifier_order(self) -> None:
        backend = self.backend(sample_products())

        products = backend.get_products(("BOOT-2", "MISSING", "BOOT-1"))

        self.assertEqual(
            tuple(product.parent_asin for product in products),
            ("BOOT-2", "BOOT-1"),
        )
        self.assertEqual(products[1].details[0], ("material", "leather"))
        self.assertTrue(backend.contains_product("BOOT-1"))
        self.assertFalse(backend.contains_product("MISSING"))


if __name__ == "__main__":
    unittest.main()
