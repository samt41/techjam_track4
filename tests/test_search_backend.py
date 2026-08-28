from __future__ import annotations

import unittest
from dataclasses import fields

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


if __name__ == "__main__":
    unittest.main()
