from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from starter.shopping_agent.catalog_artifacts import LoadedCatalogArtifacts
from starter.shopping_agent.models import Attribute, ComparisonOperator, ProductRecord
from starter.shopping_agent.search_backend import (
    FacetBucket,
    FacetRequest,
    FacetResult,
    SearchHit,
    SearchReason,
    SearchRequest,
    SearchResult,
    StructuredFilter,
    TotalRelation,
)
from starter.shopping_agent.text_normalization import normalize_text


@dataclass(frozen=True, slots=True)
class SqlFilterClause:
    sql: str
    parameters: tuple[object, ...]


class LocalProductSearchBackend:
    def __init__(self, artifacts: LoadedCatalogArtifacts) -> None:
        self._artifacts = artifacts

    @classmethod
    def open(
        cls,
        catalog_path: str | Path,
        artifact_path: str | Path,
    ) -> LocalProductSearchBackend:
        return cls(LoadedCatalogArtifacts.open(catalog_path, artifact_path))

    @property
    def catalog_fingerprint(self) -> str:
        return self._artifacts.manifest.catalog_sha256

    def search(self, request: SearchRequest) -> SearchResult:
        request.validate()
        started_at = time.perf_counter()
        filter_clause = _compile_filter_clause(request.filters)
        total_matches = int(self._artifacts.connection.execute(
            "SELECT COUNT(*) FROM products AS p" + filter_clause.sql,
            filter_clause.parameters,
        ).fetchone()[0])
        rows = self._artifacts.connection.execute(
            "SELECT p.parent_asin, p.quality_prior FROM products AS p"
            + filter_clause.sql
            + " ORDER BY p.quality_prior DESC, p.parent_asin ASC LIMIT ?",
            (*filter_clause.parameters, request.limit),
        ).fetchall()
        hits = tuple(
            SearchHit(
                parent_asin=str(row[0]),
                score=float(row[1]),
                rank=rank,
            )
            for rank, row in enumerate(rows, start=1)
        )
        result = SearchResult(
            hits=hits,
            total_matches=total_matches,
            total_relation=TotalRelation.EXACT,
            route=request.route,
            reason=SearchReason.COMPLETED,
            work_consumed=total_matches,
            elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
        )
        result.validate()
        return result

    def facets(self, request: FacetRequest) -> FacetResult:
        request.validate()
        started_at = time.perf_counter()
        filter_clause = _compile_filter_clause(request.filters)
        total_matches = int(self._artifacts.connection.execute(
            "SELECT COUNT(*) FROM products AS p" + filter_clause.sql,
            filter_clause.parameters,
        ).fetchone()[0])
        buckets: list[FacetBucket] = []
        for attribute in request.attributes:
            facet_filter_sql = (
                filter_clause.sql + " AND"
                if filter_clause.sql
                else " WHERE"
            )
            rows = self._artifacts.connection.execute(
                "SELECT facet.value, COUNT(*) FROM products AS p "
                "JOIN attributes AS facet ON facet.ordinal = p.ordinal"
                + facet_filter_sql
                + " facet.attribute = ? GROUP BY facet.value "
                "ORDER BY COUNT(*) DESC, facet.value ASC",
                (*filter_clause.parameters, attribute.value),
            ).fetchall()
            buckets.extend(
                FacetBucket(
                    attribute=attribute,
                    value=str(row[0]),
                    count=int(row[1]),
                )
                for row in rows
            )
        result = FacetResult(
            buckets=tuple(buckets),
            total_matches=total_matches,
            total_relation=TotalRelation.EXACT,
            reason=SearchReason.COMPLETED,
            work_consumed=total_matches * (len(request.attributes) + 1),
            elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
        )
        result.validate()
        return result

    def get_products(
        self,
        parent_asins: tuple[str, ...],
    ) -> tuple[ProductRecord, ...]:
        if not parent_asins:
            return ()
        unique_parent_asins = tuple(dict.fromkeys(parent_asins))
        placeholders = ", ".join("?" for _ in unique_parent_asins)
        rows = self._artifacts.connection.execute(
            "SELECT parent_asin, title, categories_json, features_json, description, "
            "details_json, store, price, average_rating, rating_number, searchable_text "
            f"FROM products WHERE parent_asin IN ({placeholders})",
            unique_parent_asins,
        ).fetchall()
        product_by_id = {
            str(row[0]): _product_from_row(row)
            for row in rows
        }
        return tuple(
            product_by_id[parent_asin]
            for parent_asin in parent_asins
            if parent_asin in product_by_id
        )

    def contains_product(self, parent_asin: str) -> bool:
        row = self._artifacts.connection.execute(
            "SELECT 1 FROM products WHERE parent_asin = ?",
            (parent_asin,),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._artifacts.close()


def _compile_filter_clause(
    filters: tuple[StructuredFilter, ...],
) -> SqlFilterClause:
    clauses: list[str] = []
    parameters: list[object] = []
    for index, structured_filter in enumerate(filters):
        structured_filter.validate()
        if structured_filter.attribute is Attribute.BUDGET:
            clause, clause_parameters = _compile_price_filter(structured_filter)
        else:
            alias = f"attribute_{index}"
            existence = "NOT EXISTS" if structured_filter.excluded else "EXISTS"
            clause = (
                f"{existence} (SELECT 1 FROM attributes AS {alias} "
                f"WHERE {alias}.ordinal = p.ordinal "
                f"AND {alias}.attribute = ? AND {alias}.value = ?)"
            )
            clause_parameters = (
                structured_filter.attribute.value,
                normalize_text(structured_filter.value),
            )
        clauses.append(clause)
        parameters.extend(clause_parameters)
    if not clauses:
        return SqlFilterClause(sql="", parameters=())
    return SqlFilterClause(
        sql=" WHERE " + " AND ".join(clauses),
        parameters=tuple(parameters),
    )


def _product_from_row(row: tuple[object, ...]) -> ProductRecord:
    raw_categories = json.loads(str(row[2]))
    raw_features = json.loads(str(row[3]))
    raw_details = json.loads(str(row[5]))
    return ProductRecord(
        parent_asin=str(row[0]),
        title=str(row[1]),
        categories=tuple(str(value) for value in raw_categories),
        features=tuple(str(value) for value in raw_features),
        description=str(row[4]),
        details=tuple(
            (str(detail[0]), str(detail[1]))
            for detail in raw_details
        ),
        store=str(row[6]),
        price=None if row[7] is None else float(row[7]),
        average_rating=None if row[8] is None else float(row[8]),
        rating_number=int(row[9]),
        searchable_text=str(row[10]),
    )


def _compile_price_filter(
    structured_filter: StructuredFilter,
) -> tuple[str, tuple[object, ...]]:
    try:
        price = float(structured_filter.value)
    except ValueError as error:
        raise ValueError("budget filter value must be numeric") from error
    if structured_filter.operator is ComparisonOperator.LESS_THAN_OR_EQUAL:
        comparison = "<="
    elif structured_filter.operator is ComparisonOperator.GREATER_THAN_OR_EQUAL:
        comparison = ">="
    else:
        comparison = "="
    if structured_filter.excluded:
        return f"(p.price IS NULL OR NOT (p.price {comparison} ?))", (price,)
    return f"p.price {comparison} ?", (price,)
