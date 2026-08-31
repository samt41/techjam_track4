from __future__ import annotations

import json
from pathlib import Path

from experiments.semantic.schemas import CatalogConcept, ProbeCase, ProbeKind
from starter.shopping_agent.text_normalization import search_terms


def load_concepts(path: str | Path) -> tuple[CatalogConcept, ...]:
    concepts = tuple(
        CatalogConcept.from_record(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    _require_unique((concept.concept_id for concept in concepts), "concept id")
    return concepts


def load_probe(
    path: str | Path,
    concepts: tuple[CatalogConcept, ...],
    *,
    require_open_vocabulary: bool = True,
) -> tuple[ProbeCase, ...]:
    cases = tuple(
        ProbeCase.from_record(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    validate_probe(cases, concepts, require_open_vocabulary=require_open_vocabulary)
    return cases


def validate_probe(
    cases: tuple[ProbeCase, ...],
    concepts: tuple[CatalogConcept, ...],
    *,
    require_open_vocabulary: bool = True,
) -> None:
    if not cases:
        raise ValueError("probe must contain at least one case")
    _require_unique((case.case_id for case in cases), "probe case id")
    normalized_clauses = (" ".join(search_terms(case.clause)) for case in cases)
    _require_unique(normalized_clauses, "normalized probe clause")
    concept_by_id = {concept.concept_id: concept for concept in concepts}
    for case in cases:
        case.validate()
        referenced = (*case.acceptable_concept_ids, *case.forbidden_concept_ids)
        unknown = tuple(value for value in referenced if value not in concept_by_id)
        if unknown:
            raise ValueError(
                f"probe case {case.case_id} references unknown concepts: {unknown}"
            )
        if require_open_vocabulary and case.kind is ProbeKind.POSITIVE:
            query_tokens = set(search_terms(case.clause))
            target_tokens = {
                token
                for concept_id in case.acceptable_concept_ids
                for token in search_terms(concept_by_id[concept_id].surface_text)
            }
            if query_tokens & target_tokens:
                raise ValueError(
                    f"positive case {case.case_id} has lexical target overlap"
                )


def _require_unique(values, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
