from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from starter.shopping_agent.models import Attribute


class ProbeKind(StrEnum):
    POSITIVE = "positive"
    OPPOSITE_TRAP = "opposite_trap"
    UNRELATED = "unrelated"
    AMBIGUOUS = "ambiguous"
    NEGATED = "negated"
    HEDGED = "hedged"


class ExpectedDisposition(StrEnum):
    RESOLVED_SOFT = "resolved_soft"
    AMBIGUOUS = "ambiguous"
    UNGROUNDED = "ungrounded"


@dataclass(frozen=True, slots=True)
class CatalogConcept:
    concept_id: str
    attribute: Attribute
    category_scope: str | None
    surface_text: str
    contextual_text: str
    document_frequency: int
    source_kind: str
    product_ordinals: tuple[int, ...]
    aliases: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.concept_id:
            raise ValueError("concept_id must not be empty")
        if not self.surface_text or not self.contextual_text:
            raise ValueError("concept text views must not be empty")
        if self.document_frequency != len(self.product_ordinals):
            raise ValueError("document_frequency must match unique product ordinals")
        if self.document_frequency < 1:
            raise ValueError("concept must occur on at least one product")
        if tuple(sorted(set(self.product_ordinals))) != self.product_ordinals:
            raise ValueError("product ordinals must be sorted and unique")
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError("concept aliases must be unique")

    def as_record(self) -> dict[str, object]:
        return {
            "concept_id": self.concept_id,
            "attribute": self.attribute.value,
            "category_scope": self.category_scope,
            "surface_text": self.surface_text,
            "contextual_text": self.contextual_text,
            "document_frequency": self.document_frequency,
            "source_kind": self.source_kind,
            "product_ordinals": list(self.product_ordinals),
            "aliases": list(self.aliases),
        }

    @classmethod
    def from_record(cls, record: dict[str, object]) -> CatalogConcept:
        concept = cls(
            concept_id=str(record["concept_id"]),
            attribute=Attribute(str(record["attribute"])),
            category_scope=(
                None
                if record.get("category_scope") in (None, "")
                else str(record["category_scope"])
            ),
            surface_text=str(record["surface_text"]),
            contextual_text=str(record["contextual_text"]),
            document_frequency=int(record["document_frequency"]),
            source_kind=str(record["source_kind"]),
            product_ordinals=tuple(int(value) for value in record["product_ordinals"]),
            aliases=tuple(str(value) for value in record.get("aliases", ())),
        )
        concept.validate()
        return concept


@dataclass(frozen=True, slots=True)
class ProbeCase:
    case_id: str
    split: str
    clause: str
    kind: ProbeKind
    expected_disposition: ExpectedDisposition
    acceptable_concept_ids: tuple[str, ...]
    forbidden_concept_ids: tuple[str, ...]
    attribute_scope: Attribute | None = None
    category_scope: str | None = None
    provenance: str = ""
    reviewer_notes: str = ""

    def validate(self) -> None:
        if not self.case_id or not self.clause.strip():
            raise ValueError("probe case id and clause must not be empty")
        if self.split not in {"calibration", "test", "smoke"}:
            raise ValueError("probe split must be calibration, test, or smoke")
        if len(set(self.acceptable_concept_ids)) != len(self.acceptable_concept_ids):
            raise ValueError("acceptable concept ids must be unique")
        if len(set(self.forbidden_concept_ids)) != len(self.forbidden_concept_ids):
            raise ValueError("forbidden concept ids must be unique")
        if set(self.acceptable_concept_ids) & set(self.forbidden_concept_ids):
            raise ValueError("a concept cannot be both acceptable and forbidden")
        if self.kind in {ProbeKind.POSITIVE, ProbeKind.AMBIGUOUS}:
            if not self.acceptable_concept_ids:
                raise ValueError("positive and ambiguous cases need acceptable concepts")

    def query_text(self) -> str:
        context: list[str] = []
        if self.category_scope:
            context.append(f"category: {self.category_scope}")
        if self.attribute_scope:
            context.append(f"attribute: {self.attribute_scope.value}")
        context.append(self.clause)
        return "; ".join(context)

    def as_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "clause": self.clause,
            "kind": self.kind.value,
            "expected_disposition": self.expected_disposition.value,
            "acceptable_concept_ids": list(self.acceptable_concept_ids),
            "forbidden_concept_ids": list(self.forbidden_concept_ids),
            "attribute_scope": (
                None if self.attribute_scope is None else self.attribute_scope.value
            ),
            "category_scope": self.category_scope,
            "provenance": self.provenance,
            "reviewer_notes": self.reviewer_notes,
        }

    @classmethod
    def from_record(cls, record: dict[str, object]) -> ProbeCase:
        raw_attribute = record.get("attribute_scope")
        case = cls(
            case_id=str(record["case_id"]),
            split=str(record["split"]),
            clause=str(record["clause"]),
            kind=ProbeKind(str(record["kind"])),
            expected_disposition=ExpectedDisposition(
                str(record["expected_disposition"])
            ),
            acceptable_concept_ids=tuple(
                str(value) for value in record.get("acceptable_concept_ids", ())
            ),
            forbidden_concept_ids=tuple(
                str(value) for value in record.get("forbidden_concept_ids", ())
            ),
            attribute_scope=(
                None if raw_attribute in (None, "") else Attribute(str(raw_attribute))
            ),
            category_scope=(
                None
                if record.get("category_scope") in (None, "")
                else str(record["category_scope"])
            ),
            provenance=str(record.get("provenance", "")),
            reviewer_notes=str(record.get("reviewer_notes", "")),
        )
        case.validate()
        return case


@dataclass(frozen=True, slots=True)
class ConceptHit:
    concept_id: str
    score: float
    rank: int

    def validate(self) -> None:
        if not self.concept_id:
            raise ValueError("hit concept_id must not be empty")
        if not math.isfinite(self.score):
            raise ValueError("hit score must be finite")
        if self.rank < 1:
            raise ValueError("hit rank must be positive")

    def as_record(self) -> dict[str, object]:
        return {
            "concept_id": self.concept_id,
            "score": round(self.score, 8),
            "rank": self.rank,
        }
