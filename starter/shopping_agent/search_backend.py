from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    ProductRecord,
    RetrievalRoute,
)


class SearchReason(StrEnum):
    COMPLETED = "completed"
    FTS5_UNAVAILABLE = "fts5_unavailable"
    WORK_LIMIT_EXCEEDED = "work_limit_exceeded"
    EMPTY_QUERY = "empty_query"
    FALLBACK_COMPLETED = "fallback_completed"
    ROUTE_TIMEOUT = "route_timeout"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    ARTIFACT_MISSING = "artifact_missing"
    MALFORMED_ARTIFACT = "malformed_artifact"


class LexicalMode(StrEnum):
    AUTO = "auto"
    FTS5 = "fts5"
    FALLBACK = "fallback"


class TotalRelation(StrEnum):
    EXACT = "exact"
    LOWER_BOUND = "lower_bound"


@dataclass(frozen=True, slots=True)
class StructuredFilter:
    constraint_id: str
    attribute: Attribute
    operator: ComparisonOperator
    value: str
    excluded: bool
    confidence: float

    def validate(self) -> None:
        if not self.constraint_id:
            raise ValueError("constraint_id must not be empty")
        if not self.value:
            raise ValueError("filter value must not be empty")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("filter confidence must be between 0 and 1")
        if self.confidence < 0.90:
            raise ValueError("hard filter confidence must be at least 0.90")
        if (
            self.attribute is not Attribute.BUDGET
            and self.operator is not ComparisonOperator.EQUALS
        ):
            raise ValueError("range operator requires a numeric budget filter")
        if self.attribute is Attribute.BUDGET:
            try:
                numeric_value = float(self.value)
            except ValueError as error:
                raise ValueError(
                    "budget filter value must be finite numeric text"
                ) from error
            if not math.isfinite(numeric_value):
                raise ValueError("budget filter value must be finite numeric text")


@dataclass(frozen=True, slots=True)
class SearchRequest:
    route: RetrievalRoute
    lexical_terms: tuple[str, ...]
    filters: tuple[StructuredFilter, ...]
    limit: int
    work_limit: int

    def validate(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be positive")
        if self.work_limit < 1:
            raise ValueError("work_limit must be positive")
        for lexical_term in self.lexical_terms:
            if not lexical_term:
                raise ValueError("lexical terms must not be empty")
        for structured_filter in self.filters:
            structured_filter.validate()


@dataclass(frozen=True, slots=True)
class SearchHit:
    parent_asin: str
    score: float
    rank: int

    def validate(self) -> None:
        if not self.parent_asin:
            raise ValueError("parent_asin must not be empty")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")
        if self.rank < 1:
            raise ValueError("rank must be positive")


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: tuple[SearchHit, ...]
    total_matches: int
    total_relation: TotalRelation
    route: RetrievalRoute
    reason: SearchReason
    work_consumed: int
    elapsed_ms: float

    def validate(self) -> None:
        if self.total_matches < len(self.hits):
            raise ValueError("total_matches cannot be smaller than returned hits")
        if self.work_consumed < 0:
            raise ValueError("work_consumed must be non-negative")
        if not math.isfinite(self.elapsed_ms) or self.elapsed_ms < 0.0:
            raise ValueError("elapsed_ms must be finite and non-negative")
        product_ids = tuple(hit.parent_asin for hit in self.hits)
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("search hit product identifiers must be unique")
        for expected_rank, hit in enumerate(self.hits, start=1):
            hit.validate()
            if hit.rank != expected_rank:
                raise ValueError("search hit rank must match result order")


@dataclass(frozen=True, slots=True)
class FacetRequest:
    filters: tuple[StructuredFilter, ...]
    attributes: tuple[Attribute, ...]
    work_limit: int

    def validate(self) -> None:
        if not self.attributes:
            raise ValueError("facet attributes must not be empty")
        if len(set(self.attributes)) != len(self.attributes):
            raise ValueError("facet attributes must be unique")
        if self.work_limit < 1:
            raise ValueError("work_limit must be positive")
        for structured_filter in self.filters:
            structured_filter.validate()


@dataclass(frozen=True, slots=True)
class FacetBucket:
    attribute: Attribute
    value: str
    count: int

    def validate(self) -> None:
        if not self.value:
            raise ValueError("facet value must not be empty")
        if self.count < 0:
            raise ValueError("facet bucket count must be non-negative")


@dataclass(frozen=True, slots=True)
class FacetResult:
    buckets: tuple[FacetBucket, ...]
    total_matches: int
    total_relation: TotalRelation
    reason: SearchReason
    work_consumed: int
    elapsed_ms: float

    def validate(self) -> None:
        if self.total_matches < 0:
            raise ValueError("total_matches must be non-negative")
        if self.work_consumed < 0:
            raise ValueError("work_consumed must be non-negative")
        if not math.isfinite(self.elapsed_ms) or self.elapsed_ms < 0.0:
            raise ValueError("elapsed_ms must be finite and non-negative")
        bucket_keys = tuple((bucket.attribute, bucket.value) for bucket in self.buckets)
        if len(set(bucket_keys)) != len(bucket_keys):
            raise ValueError("facet buckets must be unique")
        for bucket in self.buckets:
            bucket.validate()
            if self.total_relation is TotalRelation.EXACT and bucket.count > self.total_matches:
                raise ValueError("facet bucket count cannot exceed exact total_matches")


class ProductSearchBackend(Protocol):
    @property
    def catalog_fingerprint(self) -> str: ...

    def search(self, request: SearchRequest) -> SearchResult: ...

    def facets(self, request: FacetRequest) -> FacetResult: ...

    def get_products(
        self, parent_asins: tuple[str, ...]
    ) -> tuple[ProductRecord, ...]: ...

    def contains_product(self, parent_asin: str) -> bool: ...

    def close(self) -> None: ...
