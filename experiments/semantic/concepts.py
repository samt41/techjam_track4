from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from experiments.semantic.schemas import CatalogConcept
from starter.shopping_agent.models import Attribute
from starter.shopping_agent.text_normalization import normalize_text, search_terms


_ATTRIBUTES = frozenset({
    Attribute.CATEGORY,
    Attribute.MATERIAL,
    Attribute.COLOR,
    Attribute.SIZE,
    Attribute.STYLE,
    Attribute.BRAND,
    Attribute.FEATURE,
})
_ATTRIBUTE_LABELS = {
    Attribute.CATEGORY: "product category",
    Attribute.MATERIAL: "product material",
    Attribute.COLOR: "product color",
    Attribute.SIZE: "product size",
    Attribute.STYLE: "product style",
    Attribute.BRAND: "product brand",
    Attribute.FEATURE: "product feature",
}
_GENERIC_VALUES = frozenset({"none", "unknown", "n/a", "not applicable"})


def stable_concept_id(
    attribute: Attribute,
    category_scope: str | None,
    surface_text: str,
    source_kind: str,
) -> str:
    identity = "\0".join((
        attribute.value,
        category_scope or "",
        normalize_text(surface_text),
        source_kind,
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"concept-{digest}"


def concepts_from_database(
    database_path: str | Path,
    *,
    feature_document_frequency_floor: int = 2,
    feature_max_tokens: int = 12,
    feature_max_characters: int = 100,
) -> tuple[CatalogConcept, ...]:
    """Derive a deterministic global concept inventory from catalog artifacts."""
    path = Path(database_path)
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT attribute, value, ordinal FROM attributes "
            "ORDER BY attribute ASC, value ASC, ordinal ASC"
        ).fetchall()
    finally:
        connection.close()

    ordinals_by_key: dict[tuple[Attribute, str], list[int]] = defaultdict(list)
    for raw_attribute, raw_value, raw_ordinal in rows:
        try:
            attribute = Attribute(str(raw_attribute))
        except ValueError:
            continue
        if attribute not in _ATTRIBUTES:
            continue
        value = normalize_text(raw_value)
        if not _include_value(
            attribute,
            value,
            feature_max_tokens=feature_max_tokens,
            feature_max_characters=feature_max_characters,
        ):
            continue
        ordinals_by_key[(attribute, value)].append(int(raw_ordinal))

    concepts: list[CatalogConcept] = []
    for (attribute, value), raw_ordinals in sorted(
        ordinals_by_key.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        ordinals = tuple(sorted(set(raw_ordinals)))
        if (
            attribute is Attribute.FEATURE
            and len(ordinals) < feature_document_frequency_floor
        ):
            continue
        source_kind = "structured_value"
        concept = CatalogConcept(
            concept_id=stable_concept_id(attribute, None, value, source_kind),
            attribute=attribute,
            category_scope=None,
            surface_text=value,
            contextual_text=f"{_ATTRIBUTE_LABELS[attribute]}: {value}",
            document_frequency=len(ordinals),
            source_kind=source_kind,
            product_ordinals=ordinals,
        )
        concept.validate()
        concepts.append(concept)
    return tuple(concepts)


def write_inventory(
    concepts: tuple[CatalogConcept, ...],
    destination: str | Path,
) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(concept.as_record(), sort_keys=True) + "\n"
            for concept in concepts
        ),
        encoding="utf-8",
    )
    return path


def inventory_sha256(concepts: tuple[CatalogConcept, ...]) -> str:
    digest = hashlib.sha256()
    for concept in concepts:
        digest.update(json.dumps(
            concept.as_record(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _include_value(
    attribute: Attribute,
    value: str,
    *,
    feature_max_tokens: int,
    feature_max_characters: int,
) -> bool:
    if not value or value in _GENERIC_VALUES or not search_terms(value):
        return False
    if attribute is not Attribute.FEATURE:
        return True
    return (
        len(value) <= feature_max_characters
        and len(search_terms(value)) <= feature_max_tokens
    )
