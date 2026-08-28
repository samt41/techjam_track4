from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from starter.shopping_agent.catalog_artifacts import (
    CATEGORY_WEIGHT,
    DESCRIPTION_WEIGHT,
    DETAILS_WEIGHT,
    FEATURE_WEIGHT,
    STORE_WEIGHT,
    TITLE_WEIGHT,
    LoadedCatalogArtifacts,
)
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    ProductRecord,
    RetrievalRoute,
)
from starter.shopping_agent.search_backend import (
    FacetBucket,
    FacetRequest,
    FacetResult,
    LexicalMode,
    SearchHit,
    SearchReason,
    SearchRequest,
    SearchResult,
    StructuredFilter,
    TotalRelation,
)
from starter.shopping_agent.text_normalization import normalize_text, search_terms


@dataclass(frozen=True, slots=True)
class SqlFilterClause:
    sql: str
    parameters: tuple[object, ...]


class LocalProductSearchBackend:
    def __init__(
        self,
        artifacts: LoadedCatalogArtifacts,
        lexical_mode: LexicalMode,
    ) -> None:
        self._artifacts = artifacts
        self._lexical_mode = lexical_mode

    @classmethod
    def open(
        cls,
        catalog_path: str | Path,
        artifact_path: str | Path,
        *,
        lexical_mode: LexicalMode = LexicalMode.AUTO,
    ) -> LocalProductSearchBackend:
        return cls(
            LoadedCatalogArtifacts.open(catalog_path, artifact_path),
            lexical_mode,
        )

    @property
    def catalog_fingerprint(self) -> str:
        return self._artifacts.manifest.catalog_sha256

    def search(self, request: SearchRequest) -> SearchResult:
        request.validate()
        if request.route in (
            RetrievalRoute.EXACT_FTS,
            RetrievalRoute.EXPANDED_FTS,
        ):
            return self._search_lexical(request)
        return self._search_quality(request)

    def _search_quality(self, request: SearchRequest) -> SearchResult:
        started_at = time.perf_counter()
        filter_clause = _compile_filter_clause(request.filters)
        total_matches = int(self._artifacts.connection.execute(
            "SELECT COUNT(*) FROM products AS p" + filter_clause.sql,
            filter_clause.parameters,
        ).fetchone()[0])
        if request.limit > request.work_limit:
            return SearchResult(
                hits=(),
                total_matches=total_matches,
                total_relation=TotalRelation.EXACT,
                route=request.route,
                reason=SearchReason.WORK_LIMIT_EXCEEDED,
                work_consumed=request.work_limit,
                elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
            )
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
            work_consumed=len(rows),
            elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
        )
        result.validate()
        return result

    def _search_lexical(self, request: SearchRequest) -> SearchResult:
        tokens = tuple(dict.fromkeys(
            token
            for lexical_term in request.lexical_terms
            for token in search_terms(lexical_term)
        ))[:40]
        if not tokens:
            return SearchResult(
                hits=(),
                total_matches=0,
                total_relation=TotalRelation.EXACT,
                route=request.route,
                reason=SearchReason.EMPTY_QUERY,
                work_consumed=0,
                elapsed_ms=0.0,
            )
        started_at = time.perf_counter()
        filter_clause = _compile_filter_clause(request.filters)
        posting_rows = self._bounded_posting_rows(
            tokens,
            filter_clause,
            request.work_limit,
        )
        if len(posting_rows) > request.work_limit:
            known_product_ids = {
                str(row[2]) for row in posting_rows[:request.work_limit]
            }
            return SearchResult(
                hits=(),
                total_matches=len(known_product_ids),
                total_relation=TotalRelation.LOWER_BOUND,
                route=request.route,
                reason=SearchReason.WORK_LIMIT_EXCEEDED,
                work_consumed=request.work_limit,
                elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
            )
        if self._lexical_mode is LexicalMode.FALLBACK:
            return self._fallback_result(
                request,
                posting_rows,
                SearchReason.FALLBACK_COMPLETED,
                started_at,
            )
        if (
            self._lexical_mode is LexicalMode.AUTO
            and not self._artifacts.manifest.fts5_built
        ):
            return self._fallback_result(
                request,
                posting_rows,
                SearchReason.FTS5_UNAVAILABLE,
                started_at,
            )
        try:
            return self._fts5_result(
                request,
                tokens,
                filter_clause,
                len(posting_rows),
                started_at,
            )
        except sqlite3.DatabaseError:
            if self._lexical_mode is LexicalMode.AUTO:
                return self._fallback_result(
                    request,
                    posting_rows,
                    SearchReason.FTS5_UNAVAILABLE,
                    started_at,
                )
            return SearchResult(
                hits=(),
                total_matches=0,
                total_relation=TotalRelation.LOWER_BOUND,
                route=request.route,
                reason=SearchReason.FTS5_UNAVAILABLE,
                work_consumed=len(posting_rows),
                elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
            )

    def _bounded_posting_rows(
        self,
        tokens: tuple[str, ...],
        filter_clause: SqlFilterClause,
        work_limit: int,
    ) -> list[tuple[object, ...]]:
        placeholders = ", ".join("?" for _ in tokens)
        term_filter_sql = (
            filter_clause.sql + " AND"
            if filter_clause.sql
            else " WHERE"
        )
        return self._artifacts.connection.execute(
            "SELECT posting.term, posting.ordinal, p.parent_asin, "
            "posting.weighted_frequency, terms.document_frequency "
            "FROM lexical_postings AS posting "
            "JOIN lexical_terms AS terms ON terms.term = posting.term "
            "JOIN products AS p ON p.ordinal = posting.ordinal"
            + term_filter_sql
            + f" posting.term IN ({placeholders}) "
            "ORDER BY posting.term ASC, posting.ordinal ASC LIMIT ?",
            (*filter_clause.parameters, *tokens, work_limit + 1),
        ).fetchall()

    def _fallback_result(
        self,
        request: SearchRequest,
        posting_rows: list[tuple[object, ...]],
        reason: SearchReason,
        started_at: float,
    ) -> SearchResult:
        score_by_product_id: dict[str, float] = {}
        product_count = self._artifacts.manifest.product_count
        for row in posting_rows:
            product_id = str(row[2])
            weighted_frequency = float(row[3])
            document_frequency = int(row[4])
            inverse_document_frequency = math.log(
                (product_count + 1.0) / (document_frequency + 1.0)
            ) + 1.0
            score_by_product_id[product_id] = (
                score_by_product_id.get(product_id, 0.0)
                + weighted_frequency * inverse_document_frequency
            )
        ranked_products = sorted(
            score_by_product_id.items(),
            key=lambda item: (-item[1], item[0]),
        )
        hits = tuple(
            SearchHit(parent_asin=product_id, score=score, rank=rank)
            for rank, (product_id, score) in enumerate(
                ranked_products[:request.limit],
                start=1,
            )
        )
        result = SearchResult(
            hits=hits,
            total_matches=len(score_by_product_id),
            total_relation=TotalRelation.EXACT,
            route=request.route,
            reason=reason,
            work_consumed=len(posting_rows),
            elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
        )
        result.validate()
        return result

    def _fts5_result(
        self,
        request: SearchRequest,
        tokens: tuple[str, ...],
        filter_clause: SqlFilterClause,
        work_consumed: int,
        started_at: float,
    ) -> SearchResult:
        expression = " OR ".join(f'"{token}"' for token in tokens)
        hard_filter_sql = (
            filter_clause.sql.replace(" WHERE ", " AND ", 1)
            if filter_clause.sql
            else ""
        )
        from_and_where = (
            " FROM products_fts "
            "JOIN products AS p ON p.ordinal = products_fts.rowid - 1 "
            "WHERE products_fts MATCH ?"
            + hard_filter_sql
        )
        parameters = (expression, *filter_clause.parameters)
        total_matches = int(self._artifacts.connection.execute(
            "SELECT COUNT(*)" + from_and_where,
            parameters,
        ).fetchone()[0])
        bm25_expression = (
            "bm25(products_fts, "
            f"{TITLE_WEIGHT}, {CATEGORY_WEIGHT}, {FEATURE_WEIGHT}, "
            f"{DETAILS_WEIGHT}, {STORE_WEIGHT}, {DESCRIPTION_WEIGHT})"
        )
        rows = self._artifacts.connection.execute(
            "SELECT p.parent_asin, -" + bm25_expression
            + from_and_where
            + " ORDER BY " + bm25_expression + " ASC, p.parent_asin ASC LIMIT ?",
            (*parameters, request.limit),
        ).fetchall()
        result = SearchResult(
            hits=tuple(
                SearchHit(
                    parent_asin=str(row[0]),
                    score=float(row[1]),
                    rank=rank,
                )
                for rank, row in enumerate(rows, start=1)
            ),
            total_matches=total_matches,
            total_relation=TotalRelation.EXACT,
            route=request.route,
            reason=SearchReason.COMPLETED,
            work_consumed=work_consumed,
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
        required_work = total_matches * (len(request.attributes) + 1)
        if required_work > request.work_limit:
            return FacetResult(
                buckets=(),
                total_matches=total_matches,
                total_relation=TotalRelation.EXACT,
                reason=SearchReason.WORK_LIMIT_EXCEEDED,
                work_consumed=request.work_limit,
                elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
            )
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
            work_consumed=required_work,
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
    for structured_filter in filters:
        structured_filter.validate()
        if structured_filter.attribute is Attribute.BUDGET:
            clause, clause_parameters = _compile_price_filter(structured_filter)
        else:
            membership = "NOT IN" if structured_filter.excluded else "IN"
            clause = (
                f"p.ordinal {membership} (SELECT ordinal FROM attributes "
                "WHERE attribute = ? AND value = ?)"
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
