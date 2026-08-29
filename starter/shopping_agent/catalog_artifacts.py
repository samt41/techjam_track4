from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from starter.shopping_agent.models import Attribute, ProductRecord
from starter.shopping_agent.text_normalization import (
    flatten_text,
    normalize_text,
    search_terms,
)


ARTIFACT_SCHEMA_VERSION = 1
DATABASE_FILENAME = "catalog.sqlite3"
MANIFEST_FILENAME = "manifest.json"
NORMALIZATION_VERSION = "nfkc-casefold-v1"
FTS_TOKENIZER = "unicode61-remove-diacritics-2"
TITLE_WEIGHT = 6.0
CATEGORY_WEIGHT = 4.0
FEATURE_WEIGHT = 2.5
DETAILS_WEIGHT = 2.5
STORE_WEIGHT = 1.5
DESCRIPTION_WEIGHT = 1.0
POSTING_BATCH_SIZE = 1_000


class ArtifactBuildError(RuntimeError):
    """Raised when a catalog artifact cannot be built safely."""


class ArtifactValidationError(RuntimeError):
    """Raised when an artifact does not match its fixed schema or catalog."""


@dataclass(frozen=True, slots=True)
class CatalogArtifactManifest:
    schema_version: int
    catalog_sha256: str
    catalog_size_bytes: int
    product_count: int
    database_sha256: str
    database_size_bytes: int
    lexical_term_count: int
    fts5_built: bool
    normalization_version: str
    fts_tokenizer: str
    title_weight: float
    category_weight: float
    feature_weight: float
    details_weight: float
    store_weight: float
    description_weight: float
    posting_batch_size: int

    def validate(self) -> None:
        if self.schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ArtifactValidationError(
                f"unsupported artifact schema version {self.schema_version}"
            )
        for field_name, digest in (
            ("catalog_sha256", self.catalog_sha256),
            ("database_sha256", self.database_sha256),
        ):
            invalid_character = any(
                character not in "0123456789abcdef" for character in digest
            )
            if len(digest) != 64 or invalid_character:
                raise ArtifactValidationError(f"invalid {field_name}")
        for field_name, value in (
            ("catalog_size_bytes", self.catalog_size_bytes),
            ("product_count", self.product_count),
            ("database_size_bytes", self.database_size_bytes),
            ("lexical_term_count", self.lexical_term_count),
        ):
            if value < 0:
                raise ArtifactValidationError(f"{field_name} must be non-negative")
        actual_configuration = (
            self.normalization_version,
            self.fts_tokenizer,
            self.title_weight,
            self.category_weight,
            self.feature_weight,
            self.details_weight,
            self.store_weight,
            self.description_weight,
            self.posting_batch_size,
        )
        expected_configuration = (
            NORMALIZATION_VERSION,
            FTS_TOKENIZER,
            TITLE_WEIGHT,
            CATEGORY_WEIGHT,
            FEATURE_WEIGHT,
            DETAILS_WEIGHT,
            STORE_WEIGHT,
            DESCRIPTION_WEIGHT,
            POSTING_BATCH_SIZE,
        )
        if actual_configuration != expected_configuration:
            raise ArtifactValidationError(
                "artifact build configuration does not match this runtime"
            )

    def to_json(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "catalog_sha256": self.catalog_sha256,
            "catalog_size_bytes": self.catalog_size_bytes,
            "product_count": self.product_count,
            "database_sha256": self.database_sha256,
            "database_size_bytes": self.database_size_bytes,
            "lexical_term_count": self.lexical_term_count,
            "fts5_built": self.fts5_built,
            "normalization_version": self.normalization_version,
            "fts_tokenizer": self.fts_tokenizer,
            "title_weight": self.title_weight,
            "category_weight": self.category_weight,
            "feature_weight": self.feature_weight,
            "details_weight": self.details_weight,
            "store_weight": self.store_weight,
            "description_weight": self.description_weight,
            "posting_batch_size": self.posting_batch_size,
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> CatalogArtifactManifest:
        try:
            payload = json.loads(text)
            if not isinstance(payload["fts5_built"], bool):
                raise TypeError("fts5_built must be a boolean")
            manifest = cls(
                schema_version=int(payload["schema_version"]),
                catalog_sha256=str(payload["catalog_sha256"]),
                catalog_size_bytes=int(payload["catalog_size_bytes"]),
                product_count=int(payload["product_count"]),
                database_sha256=str(payload["database_sha256"]),
                database_size_bytes=int(payload["database_size_bytes"]),
                lexical_term_count=int(payload["lexical_term_count"]),
                fts5_built=payload["fts5_built"],
                normalization_version=str(payload["normalization_version"]),
                fts_tokenizer=str(payload["fts_tokenizer"]),
                title_weight=float(payload["title_weight"]),
                category_weight=float(payload["category_weight"]),
                feature_weight=float(payload["feature_weight"]),
                details_weight=float(payload["details_weight"]),
                store_weight=float(payload["store_weight"]),
                description_weight=float(payload["description_weight"]),
                posting_batch_size=int(payload["posting_batch_size"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ArtifactValidationError("malformed artifact manifest") from error
        manifest.validate()
        return manifest


@dataclass(frozen=True, slots=True)
class ParsedCatalog:
    products: tuple[ProductRecord, ...]
    catalog_sha256: str
    catalog_size_bytes: int


class CatalogArtifactBuilder:
    def __init__(self, *, fts5_enabled: bool = True) -> None:
        self._fts5_enabled = fts5_enabled

    def build(
        self,
        catalog_path: str | Path,
        artifact_path: str | Path,
    ) -> CatalogArtifactManifest:
        source_path = Path(catalog_path)
        output_path = Path(artifact_path)
        if output_path.exists():
            raise ArtifactBuildError(
                f"refusing to overwrite existing artifact directory: {output_path}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(tempfile.mkdtemp(
            prefix=f".{output_path.name}.tmp-",
            dir=output_path.parent,
        ))
        try:
            parsed_catalog = _parse_catalog(source_path)
            database_path = temporary_path / DATABASE_FILENAME
            fts5_built, lexical_term_count = _build_database(
                database_path,
                parsed_catalog.products,
                fts5_enabled=self._fts5_enabled,
            )
            manifest = CatalogArtifactManifest(
                schema_version=ARTIFACT_SCHEMA_VERSION,
                catalog_sha256=parsed_catalog.catalog_sha256,
                catalog_size_bytes=parsed_catalog.catalog_size_bytes,
                product_count=len(parsed_catalog.products),
                database_sha256=_sha256_file(database_path),
                database_size_bytes=database_path.stat().st_size,
                lexical_term_count=lexical_term_count,
                fts5_built=fts5_built,
                normalization_version=NORMALIZATION_VERSION,
                fts_tokenizer=FTS_TOKENIZER,
                title_weight=TITLE_WEIGHT,
                category_weight=CATEGORY_WEIGHT,
                feature_weight=FEATURE_WEIGHT,
                details_weight=DETAILS_WEIGHT,
                store_weight=STORE_WEIGHT,
                description_weight=DESCRIPTION_WEIGHT,
                posting_batch_size=POSTING_BATCH_SIZE,
            )
            (temporary_path / MANIFEST_FILENAME).write_text(
                manifest.to_json(),
                encoding="utf-8",
            )
            loaded = LoadedCatalogArtifacts.open(source_path, temporary_path)
            loaded.close()
            temporary_path.replace(output_path)
            return manifest
        except Exception:
            shutil.rmtree(temporary_path, ignore_errors=True)
            raise


class LoadedCatalogArtifacts:
    def __init__(
        self,
        path: Path,
        manifest: CatalogArtifactManifest,
        connection: sqlite3.Connection,
    ) -> None:
        self.path = path
        self.manifest = manifest
        self.connection = connection
        self._closed = False

    @classmethod
    def open(
        cls,
        catalog_path: str | Path,
        artifact_path: str | Path,
    ) -> LoadedCatalogArtifacts:
        source_path = Path(catalog_path)
        directory_path = Path(artifact_path)
        manifest_path = directory_path / MANIFEST_FILENAME
        database_path = directory_path / DATABASE_FILENAME
        if not manifest_path.is_file() or not database_path.is_file():
            raise ArtifactValidationError(
                f"artifact files are missing from {directory_path}"
            )
        try:
            manifest_text = manifest_path.read_text(encoding="utf-8")
        except OSError as error:
            raise ArtifactValidationError("artifact manifest cannot be read") from error
        manifest = CatalogArtifactManifest.from_json(manifest_text)
        catalog_sha256 = _sha256_file(source_path)
        if catalog_sha256 != manifest.catalog_sha256:
            raise ArtifactValidationError(
                "catalog fingerprint does not match artifact; rebuild explicitly"
            )
        if source_path.stat().st_size != manifest.catalog_size_bytes:
            raise ArtifactValidationError("catalog size does not match artifact manifest")
        if database_path.stat().st_size != manifest.database_size_bytes:
            raise ArtifactValidationError("artifact database size does not match manifest")
        # The full-database SHA-256 is intentionally not verified on open: it
        # hashes ~575 MB on every startup. The catalog fingerprint above already
        # binds the artifacts to their source catalog, and the size check plus
        # SQLite's own page integrity catch truncation/corruption. Rebuild
        # explicitly if deeper verification is needed.

        database_uri = database_path.resolve().as_uri() + "?mode=ro"
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database_uri, uri=True)
            connection.execute("PRAGMA query_only = ON")
            # Read-path tuning for the large (~575 MB) artifact DB: memory-map the
            # file so hot pages are served without per-read syscalls, enlarge the
            # page cache, and keep temporary b-trees in RAM. All read-only and safe.
            connection.execute("PRAGMA mmap_size = 1073741824")  # 1 GiB
            connection.execute("PRAGMA cache_size = -131072")     # 128 MiB page cache
            connection.execute("PRAGMA temp_store = MEMORY")
            product_count = int(connection.execute(
                "SELECT COUNT(*) FROM products"
            ).fetchone()[0])
            if product_count != manifest.product_count:
                raise ArtifactValidationError(
                    "artifact product count does not match manifest"
                )
        except (OSError, sqlite3.DatabaseError) as error:
            if connection is not None:
                connection.close()
            raise ArtifactValidationError("artifact database cannot be opened") from error
        except Exception:
            if connection is not None:
                connection.close()
            raise
        if connection is None:
            raise ArtifactValidationError("artifact database cannot be opened")
        return cls(directory_path, manifest, connection)

    def close(self) -> None:
        if not self._closed:
            self.connection.close()
            self._closed = True


def _parse_catalog(catalog_path: Path) -> ParsedCatalog:
    try:
        catalog_bytes = catalog_path.read_bytes()
    except OSError as error:
        raise ArtifactBuildError(f"catalog cannot be read: {catalog_path}") from error
    products: list[ProductRecord] = []
    product_ids: set[str] = set()
    for line_number, raw_line in enumerate(catalog_bytes.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ArtifactBuildError(
                f"catalog line {line_number} is not valid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise ArtifactBuildError(f"catalog line {line_number} must be an object")
        product = _parse_product(payload, line_number)
        if product.parent_asin in product_ids:
            raise ArtifactBuildError(
                f"catalog contains duplicate parent_asin {product.parent_asin}"
            )
        product_ids.add(product.parent_asin)
        products.append(product)
    return ParsedCatalog(
        products=tuple(products),
        catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(),
        catalog_size_bytes=len(catalog_bytes),
    )


def _parse_product(payload: dict[str, object], line_number: int) -> ProductRecord:
    parent_asin = str(payload.get("parent_asin") or "").strip()
    if not parent_asin:
        raise ArtifactBuildError(
            f"catalog product on line {line_number} is missing parent_asin"
        )
    categories = _normalized_sequence(payload.get("categories"), "categories", line_number)
    features = _normalized_sequence(payload.get("features"), "features", line_number)
    raw_details = payload.get("details") or {}
    if not isinstance(raw_details, dict):
        raise ArtifactBuildError(
            f"catalog details on line {line_number} must be an object"
        )
    details = tuple(
        (normalize_text(key), normalize_text(value))
        for key, value in raw_details.items()
        if value not in (None, "")
    )
    description = flatten_text(payload.get("description"))
    title = normalize_text(payload.get("title"))
    store = normalize_text(payload.get("store"))
    searchable_text = " ".join(
        part
        for part in (
            title,
            " ".join(categories),
            " ".join(features),
            flatten_text(raw_details),
            store,
            description,
        )
        if part
    )
    return ProductRecord(
        parent_asin=parent_asin,
        title=title,
        categories=categories,
        features=features,
        description=description,
        details=details,
        store=store,
        price=_optional_float(payload.get("price")),
        average_rating=_optional_float(payload.get("average_rating")),
        rating_number=_non_negative_int(payload.get("rating_number"), line_number),
        searchable_text=searchable_text,
    )


def _normalized_sequence(
    value: object,
    field_name: str,
    line_number: int,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ArtifactBuildError(
            f"catalog {field_name} on line {line_number} must be a list"
        )
    return tuple(normalize_text(item) for item in value if item not in (None, ""))


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed_value = float(value)
    except (TypeError, ValueError):
        return None
    return parsed_value if math.isfinite(parsed_value) else None


def _non_negative_int(value: object, line_number: int) -> int:
    try:
        parsed_value = int(value or 0)
    except (TypeError, ValueError) as error:
        raise ArtifactBuildError(
            f"catalog rating_number on line {line_number} must be an integer"
        ) from error
    if parsed_value < 0:
        raise ArtifactBuildError(
            f"catalog rating_number on line {line_number} must be non-negative"
        )
    return parsed_value


def _build_database(
    database_path: Path,
    products: tuple[ProductRecord, ...],
    *,
    fts5_enabled: bool,
) -> tuple[bool, int]:
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript("""
            PRAGMA journal_mode = DELETE;
            PRAGMA synchronous = FULL;
            CREATE TABLE products (
                ordinal INTEGER PRIMARY KEY,
                parent_asin TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                categories_json TEXT NOT NULL,
                features_json TEXT NOT NULL,
                description TEXT NOT NULL,
                details_json TEXT NOT NULL,
                store TEXT NOT NULL,
                price REAL,
                average_rating REAL,
                rating_number INTEGER NOT NULL,
                searchable_text TEXT NOT NULL,
                quality_prior REAL NOT NULL
            );
            CREATE TABLE attributes (
                ordinal INTEGER NOT NULL,
                attribute TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (ordinal, attribute, value)
            );
            CREATE TABLE lexical_postings (
                term TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                weighted_frequency REAL NOT NULL,
                PRIMARY KEY (term, ordinal)
            );
            CREATE TABLE lexical_terms (
                term TEXT PRIMARY KEY,
                document_frequency INTEGER NOT NULL
            );
        """)
        fts5_built = fts5_enabled and _create_fts5_table(connection)
        document_frequencies: Counter[str] = Counter()
        material_vocabulary = _material_vocabulary(products)
        keyed_feature_vocabulary = _keyed_feature_vocabulary(products)
        product_rows: list[tuple[object, ...]] = []
        attribute_rows: list[tuple[int, str, str]] = []
        posting_rows: list[tuple[str, int, float]] = []
        fts_rows: list[tuple[object, ...]] = []
        for ordinal, product in enumerate(products):
            product = _with_recovered_materials(product, material_vocabulary)
            product = _with_recovered_keyed_features(product, keyed_feature_vocabulary)
            product_rows.append((
                ordinal,
                product.parent_asin,
                product.title,
                json.dumps(product.categories, separators=(",", ":")),
                json.dumps(product.features, separators=(",", ":")),
                product.description,
                json.dumps(product.details, separators=(",", ":")),
                product.store,
                product.price,
                product.average_rating,
                product.rating_number,
                product.searchable_text,
                _quality_score(product),
            ))
            attribute_rows.extend(
                (ordinal, attribute.value, value)
                for attribute in Attribute
                for value in _attribute_values(product, attribute)
            )
            weighted_terms = _weighted_terms(product)
            posting_rows.extend(
                (term, ordinal, weighted_frequency)
                for term, weighted_frequency in sorted(weighted_terms.items())
            )
            document_frequencies.update(weighted_terms)
            if fts5_built:
                fts_rows.append((
                    ordinal + 1,
                    product.title,
                    " ".join(product.categories),
                    " ".join(product.features),
                    " ".join(f"{key} {value}" for key, value in product.details),
                    product.store,
                    product.description,
                ))
            if len(product_rows) >= POSTING_BATCH_SIZE:
                _insert_product_batch(
                    connection,
                    product_rows,
                    attribute_rows,
                    posting_rows,
                    fts_rows,
                )
                product_rows.clear()
                attribute_rows.clear()
                posting_rows.clear()
                fts_rows.clear()
        _insert_product_batch(
            connection,
            product_rows,
            attribute_rows,
            posting_rows,
            fts_rows,
        )
        connection.executemany(
            "INSERT INTO lexical_terms VALUES (?, ?)",
            sorted(document_frequencies.items()),
        )
        connection.executescript("""
            CREATE INDEX attributes_lookup
                ON attributes(attribute, value, ordinal);
            CREATE INDEX lexical_term_lookup
                ON lexical_postings(term, ordinal);
        """)
        connection.commit()
        connection.execute("VACUUM")
        return fts5_built, len(document_frequencies)
    finally:
        connection.close()


def _create_fts5_table(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE products_fts USING fts5("
            "title, categories, features, details, store, description, content='', "
            "tokenize='unicode61 remove_diacritics 2')"
        )
    except sqlite3.OperationalError:
        return False
    return True


def _insert_product_batch(
    connection: sqlite3.Connection,
    product_rows: list[tuple[object, ...]],
    attribute_rows: list[tuple[int, str, str]],
    posting_rows: list[tuple[str, int, float]],
    fts_rows: list[tuple[object, ...]],
) -> None:
    connection.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        product_rows,
    )
    connection.executemany(
        "INSERT INTO attributes VALUES (?, ?, ?)",
        attribute_rows,
    )
    connection.executemany(
        "INSERT INTO lexical_postings VALUES (?, ?, ?)",
        posting_rows,
    )
    if fts_rows:
        connection.executemany(
            "INSERT INTO products_fts(rowid, title, categories, features, details, "
            "store, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
            fts_rows,
        )


def _weighted_terms(product: ProductRecord) -> Counter[str]:
    weighted_terms: Counter[str] = Counter()
    weighted_fields = (
        (product.title, TITLE_WEIGHT),
        (" ".join(product.categories), CATEGORY_WEIGHT),
        (" ".join(product.features), FEATURE_WEIGHT),
        (
            " ".join(f"{key} {value}" for key, value in product.details),
            DETAILS_WEIGHT,
        ),
        (product.store, STORE_WEIGHT),
        (product.description, DESCRIPTION_WEIGHT),
    )
    for text, weight in weighted_fields:
        for term in search_terms(text):
            weighted_terms[term] += weight
    return weighted_terms


_MATERIAL_TOKEN_RE = re.compile(r"[a-z]+")
_MATERIAL_PERCENT_RE = re.compile(r"\d+\s*%|\bpercent\b")
_MATERIAL_BLEND_RE = re.compile(r"\band\b|[/,&+]")
_MATERIAL_VOCAB_FLOOR = 2


def _material_vocabulary(products: tuple[ProductRecord, ...]) -> frozenset[str]:
    counts: Counter[str] = Counter()
    for product in products:
        for key, value in product.details:
            if key != Attribute.MATERIAL.value:
                continue
            tokens = _MATERIAL_TOKEN_RE.findall(value)
            if len(tokens) == 1:
                counts[tokens[0]] += 1
    return frozenset(
        token for token, count in counts.items() if count >= _MATERIAL_VOCAB_FLOOR
    )


def _feature_material_tokens(
    features: tuple[str, ...],
    vocabulary: frozenset[str],
) -> tuple[str, ...]:
    found: list[str] = []
    for feature in features:
        stripped = _MATERIAL_PERCENT_RE.sub(" ", feature)
        for part in _MATERIAL_BLEND_RE.split(stripped):
            tokens = _MATERIAL_TOKEN_RE.findall(part)
            if tokens and tokens[-1] in vocabulary:
                found.append(tokens[-1])
    return tuple(dict.fromkeys(found))


def _with_recovered_materials(
    product: ProductRecord,
    vocabulary: frozenset[str],
) -> ProductRecord:
    """Fold materials recovered from free-text features into ``details``.

    Making the recovered material part of the canonical ``details`` is the single
    source every consumer reads: the structured ``attributes`` table (retrieval
    SQL), the stored ``details_json`` the runtime rebuilds a ProductRecord from,
    and therefore the eligibility gate and soft scorer. Writing it only into the
    attributes table would let retrieval accept a product the gate then rejects.
    """
    existing = {value for key, value in product.details if key == Attribute.MATERIAL.value}
    recovered = tuple(
        token
        for token in _feature_material_tokens(product.features, vocabulary)
        if token not in existing
    )
    if not recovered:
        return product
    added = tuple((Attribute.MATERIAL.value, token) for token in recovered)
    return replace(product, details=(*product.details, *added))


# Free-text features frequently carry a mis-filed structured value as
# "key: value", such as "color: black" or "size: medium". These attributes are
# read from details at query time, so recovering the value into details lets a
# structured constraint reach it. The key must name one of these attributes and
# the value must be a short, recurring value (see _keyed_feature_vocabulary),
# never a marketing sentence. Material is handled separately above; brand is not
# recovered because it is read from the store field, not details.
_KEYED_FEATURE_ATTRIBUTES = {
    "color": Attribute.COLOR,
    "colour": Attribute.COLOR,
    "size": Attribute.SIZE,
    "style": Attribute.STYLE,
}
_KEYED_FEATURE_RE = re.compile(r"^([a-z][a-z ]+?)\s*:\s*(.+)$")
_KEYED_VALUE_SPLIT_RE = re.compile(r";|\b[a-z ]+\s*:")
_KEYED_VALUE_FLOOR = 2
_KEYED_VALUE_MAX_TOKENS = 4
_KEYED_VALUE_MAX_LENGTH = 25


def _keyed_feature_value(feature: str) -> tuple[Attribute, str] | None:
    match = _KEYED_FEATURE_RE.match(feature)
    if match is None:
        return None
    attribute = _KEYED_FEATURE_ATTRIBUTES.get(match.group(1).strip())
    if attribute is None:
        return None
    # Keep only the first clause, dropping a trailing second key/value such as
    # "black; material: polyester" or "gucci model: gg0163sk".
    value = _KEYED_VALUE_SPLIT_RE.split(match.group(2))[0].strip().strip(".-\"' ")
    tokens = _MATERIAL_TOKEN_RE.findall(value)
    if not (0 < len(tokens) <= _KEYED_VALUE_MAX_TOKENS):
        return None
    if not (1 < len(value) <= _KEYED_VALUE_MAX_LENGTH):
        return None
    return attribute, value


def _keyed_feature_vocabulary(
    products: tuple[ProductRecord, ...],
) -> frozenset[tuple[Attribute, str]]:
    """Recurring (attribute, value) pairs implied by "key: value" features.

    A value is kept only if it appears on at least ``_KEYED_VALUE_FLOOR``
    products, which drops one-off typos and per-product noise while keeping real
    values like "black" or "rose gold" that were only ever written into a
    feature string.
    """
    counts: Counter[tuple[Attribute, str]] = Counter()
    for product in products:
        seen: set[tuple[Attribute, str]] = set()
        for feature in product.features:
            keyed = _keyed_feature_value(feature)
            if keyed is not None and keyed not in seen:
                seen.add(keyed)
                counts[keyed] += 1
    return frozenset(
        pair for pair, count in counts.items() if count >= _KEYED_VALUE_FLOOR
    )


def _with_recovered_keyed_features(
    product: ProductRecord,
    vocabulary: frozenset[tuple[Attribute, str]],
) -> ProductRecord:
    """Fold recurring "key: value" features into structured details."""
    existing = {(key, value) for key, value in product.details}
    added: list[tuple[str, str]] = []
    for feature in product.features:
        keyed = _keyed_feature_value(feature)
        if keyed is None or keyed not in vocabulary:
            continue
        attribute, value = keyed
        row = (attribute.value, value)
        if row not in existing:
            existing.add(row)
            added.append(row)
    if not added:
        return product
    return replace(product, details=(*product.details, *added))


def _attribute_values(
    product: ProductRecord,
    attribute: Attribute,
) -> tuple[str, ...]:
    if attribute is Attribute.CATEGORY:
        return tuple(dict.fromkeys(product.categories))
    if attribute is Attribute.FEATURE:
        return tuple(dict.fromkeys(product.features))
    if attribute is Attribute.BRAND:
        return (product.store,) if product.store else ()
    if attribute is Attribute.BUDGET:
        return () if product.price is None else (str(product.price),)
    detail_values = tuple(
        value for key, value in product.details if key == attribute.value
    )
    return tuple(dict.fromkeys(detail_values))


def _quality_score(product: ProductRecord) -> float:
    if product.average_rating is None or product.rating_number <= 0:
        return 0.0
    positive_ratio = max(0.0, min(1.0, product.average_rating / 5.0))
    count = product.rating_number
    z_score = 1.96
    denominator = 1.0 + z_score * z_score / count
    centre = positive_ratio + z_score * z_score / (2.0 * count)
    margin = z_score * math.sqrt(
        (
            positive_ratio * (1.0 - positive_ratio)
            + z_score * z_score / (4.0 * count)
        )
        / count
    )
    return (centre - margin) / denominator


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise ArtifactValidationError(f"cannot hash file: {path}") from error
    return digest.hexdigest()
