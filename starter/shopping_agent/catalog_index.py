from __future__ import annotations

from starter.shopping_agent.models import Attribute, ProductRecord
from starter.shopping_agent.search_backend import (
    FacetRequest,
    ProductSearchBackend,
)


class CatalogIndex:
    """Normalized read-only catalog vocabulary and product view."""

    def __init__(self, backend: ProductSearchBackend) -> None:
        self.backend = backend
        self.fingerprint = backend.catalog_fingerprint

    def close(self) -> None:
        self.backend.close()

    def values_for(self, attribute: Attribute) -> tuple[str, ...]:
        result = self.backend.facets(FacetRequest(
            filters=(),
            attributes=(attribute,),
            work_limit=1_000_000_000,
        ))
        return tuple(sorted(bucket.value for bucket in result.buckets))

    def get_products(
        self,
        parent_asins: tuple[str, ...],
    ) -> tuple[ProductRecord, ...]:
        return self.backend.get_products(parent_asins)

    def contains_product(self, parent_asin: str) -> bool:
        return self.backend.contains_product(parent_asin)
