from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

from starter.shopping_agent.models import Attribute, ProductRecord
from starter.shopping_agent.text_normalization import flatten_text, normalize_text, search_terms


class CatalogIndex:
    def __init__(
        self,
        products: tuple[ProductRecord, ...],
        connection: sqlite3.Connection,
        fingerprint: str,
    ) -> None:
        self.products = products
        self.connection = connection
        self.fingerprint = fingerprint
        self.product_by_id = {product.parent_asin: product for product in products}
        self._values_by_attribute: dict[Attribute, tuple[str, ...]] = {}
        self._products_by_attribute_value: dict[
            tuple[Attribute, str], tuple[ProductRecord, ...]
        ] = {}
        self._build_metadata_indexes()

    @classmethod
    def from_path(cls, path: str | Path) -> CatalogIndex:
        catalog_path = Path(path)
        digest = hashlib.sha256()
        records: list[ProductRecord] = []
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        rows: list[tuple[str, str, str, str, str, str, str]] = []
        with catalog_path.open("rb") as handle:
            for raw_line in handle:
                if not raw_line.strip():
                    continue
                digest.update(raw_line)
                payload = json.loads(raw_line)
                parent_asin = str(payload.get("parent_asin") or "").strip()
                if not parent_asin:
                    raise ValueError("catalog product is missing parent_asin")
                categories = tuple(
                    normalize_text(item) for item in payload.get("categories", []) if item
                )
                features = tuple(
                    normalize_text(item) for item in payload.get("features", []) if item
                )
                raw_details = payload.get("details") or {}
                details = tuple(
                    (normalize_text(key), normalize_text(value))
                    for key, value in raw_details.items()
                    if value not in (None, "")
                )
                description = flatten_text(payload.get("description"))
                title = normalize_text(payload.get("title"))
                store = normalize_text(payload.get("store"))
                searchable_text = " ".join(
                    part for part in (
                        title,
                        " ".join(categories),
                        " ".join(features),
                        flatten_text(raw_details),
                        store,
                        description,
                    ) if part
                )
                record = ProductRecord(
                    parent_asin=parent_asin,
                    title=title,
                    categories=categories,
                    features=features,
                    description=description,
                    details=details,
                    store=store,
                    price=_optional_float(payload.get("price")),
                    average_rating=_optional_float(payload.get("average_rating")),
                    rating_number=int(payload.get("rating_number") or 0),
                    searchable_text=searchable_text,
                )
                records.append(record)
                rows.append((
                    record.parent_asin,
                    title,
                    " ".join(categories),
                    " ".join(features),
                    flatten_text(raw_details),
                    store,
                    description,
                ))
        connection.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        connection.commit()
        return cls(tuple(records), connection, digest.hexdigest())

    def search_fts(self, terms: tuple[str, ...], limit: int) -> tuple[ProductRecord, ...]:
        tokens = tuple(dict.fromkeys(token for term in terms for token in search_terms(term)))
        if not tokens or limit <= 0:
            return ()
        expression = " OR ".join(f'"{token}"' for token in tokens[:40])
        rows = self.connection.execute(
            "SELECT parent_asin FROM products WHERE products MATCH ? "
            "ORDER BY bm25(products, 0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0), parent_asin LIMIT ?",
            (expression, limit),
        ).fetchall()
        return tuple(self.product_by_id[str(row[0])] for row in rows)

    def quality_fallback(self, category: str | None, limit: int) -> tuple[ProductRecord, ...]:
        normalized_category = normalize_text(category)
        eligible = (
            product for product in self.products
            if not normalized_category
            or any(normalized_category in value for value in product.categories)
        )
        ranked = sorted(
            eligible,
            key=lambda product: (-_quality_score(product), product.parent_asin),
        )
        return tuple(ranked[:max(0, limit)])

    def values_for(self, attribute: Attribute) -> tuple[str, ...]:
        return self._values_by_attribute.get(attribute, ())

    def products_for(
        self,
        attribute: Attribute,
        value: str,
    ) -> tuple[ProductRecord, ...]:
        return self._products_by_attribute_value.get(
            (attribute, normalize_text(value)),
            (),
        )

    def _build_metadata_indexes(self) -> None:
        mutable_products: dict[tuple[Attribute, str], list[ProductRecord]] = {}
        for product in self.products:
            for attribute in Attribute:
                for value in _attribute_values(product, attribute):
                    mutable_products.setdefault((attribute, value), []).append(product)
        for (attribute, value), products in mutable_products.items():
            self._products_by_attribute_value[(attribute, value)] = tuple(products)
        for attribute in Attribute:
            self._values_by_attribute[attribute] = tuple(sorted(
                value
                for indexed_attribute, value in mutable_products
                if indexed_attribute is attribute
            ))


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _quality_score(product: ProductRecord) -> float:
    if product.average_rating is None or product.rating_number <= 0:
        return 0.0
    positive_ratio = max(0.0, min(1.0, product.average_rating / 5.0))
    count = product.rating_number
    z = 1.96
    denominator = 1.0 + z * z / count
    centre = positive_ratio + z * z / (2.0 * count)
    margin = z * math.sqrt(
        (positive_ratio * (1.0 - positive_ratio) + z * z / (4.0 * count)) / count
    )
    return (centre - margin) / denominator


def _attribute_values(
    product: ProductRecord,
    attribute: Attribute,
) -> tuple[str, ...]:
    if attribute is Attribute.CATEGORY:
        return product.categories
    if attribute is Attribute.FEATURE:
        return product.features
    if attribute is Attribute.BRAND:
        return (product.store,) if product.store else ()
    if attribute is Attribute.BUDGET:
        return () if product.price is None else (str(product.price),)
    detail_values = tuple(
        value for key, value in product.details if key == attribute.value
    )
    return tuple(dict.fromkeys(detail_values))
