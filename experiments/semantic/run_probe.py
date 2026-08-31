from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from time import perf_counter

from experiments.semantic.encoders import (
    ENCODER_CONFIGURATIONS,
    SentenceTransformerEncoder,
)
from experiments.semantic.metrics import retrieval_metrics
from experiments.semantic.probe import load_concepts, load_probe
from experiments.semantic.search import dense_search, lexical_search


def run_probe(
    concept_path: str | Path,
    probe_path: str | Path,
    output_path: str | Path,
    model_names: tuple[str, ...],
    *,
    batch_size: int = 64,
    top_k: int = 5,
) -> Path:
    concepts = load_concepts(concept_path)
    cases = load_probe(probe_path, concepts)
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"probe output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    lexical_hits = {
        case.case_id: lexical_search(case, concepts, top_k=top_k)
        for case in cases
    }
    systems: dict[str, object] = {
        "lexical": {
            "metrics": retrieval_metrics(cases, lexical_hits).as_record(),
            "hits": _hit_records(lexical_hits),
        }
    }

    query_texts = tuple(case.query_text() for case in cases)
    surface_texts = tuple(concept.surface_text for concept in concepts)
    contextual_texts = tuple(concept.contextual_text for concept in concepts)
    for model_name in model_names:
        try:
            configuration = ENCODER_CONFIGURATIONS[model_name]
        except KeyError as error:
            raise ValueError(f"unknown encoder configuration: {model_name}") from error
        started = perf_counter()
        encoder = SentenceTransformerEncoder(
            configuration,
            batch_size=batch_size,
        )
        loaded_seconds = perf_counter() - started
        started = perf_counter()
        surface_vectors = encoder.encode_documents(surface_texts)
        contextual_vectors = encoder.encode_documents(contextual_texts)
        catalog_seconds = perf_counter() - started
        started = perf_counter()
        query_vectors = encoder.encode_queries(query_texts)
        query_seconds = perf_counter() - started
        started = perf_counter()
        hits = dense_search(
            cases,
            concepts,
            query_vectors,
            surface_vectors,
            contextual_vectors,
            top_k=top_k,
        )
        search_seconds = perf_counter() - started
        systems[model_name] = {
            "model_id": configuration.model_id,
            "requested_revision": configuration.revision,
            "resolved_revision": encoder.resolved_revision,
            "dimension": encoder.dimension,
            "load_seconds": round(loaded_seconds, 6),
            "catalog_encode_seconds": round(catalog_seconds, 6),
            "query_encode_seconds": round(query_seconds, 6),
            "query_ms_per_case": round(query_seconds * 1000.0 / len(cases), 6),
            "search_seconds": round(search_seconds, 6),
            "metrics": retrieval_metrics(cases, hits).as_record(),
            "hits": _hit_records(hits),
        }

    payload = {
        "schema_version": 1,
        "concept_sha256": _sha256(Path(concept_path)),
        "probe_sha256": _sha256(Path(probe_path)),
        "concept_count": len(concepts),
        "case_count": len(cases),
        "top_k": top_k,
        "platform": platform.platform(),
        "python": sys.version,
        "systems": systems,
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _hit_records(hits_by_case) -> dict[str, list[dict[str, object]]]:
    return {
        case_id: [hit.as_record() for hit in hits]
        for case_id, hits in sorted(hits_by_case.items())
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run lexical and neural retrieval over a semantic probe"
    )
    parser.add_argument("--concepts", required=True)
    parser.add_argument("--probe", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=tuple(ENCODER_CONFIGURATIONS),
        default=("arctic-s", "bge-small", "arctic-xs", "minilm-l6"),
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    path = run_probe(
        args.concepts,
        args.probe,
        args.output,
        tuple(args.models),
        batch_size=args.batch_size,
        top_k=args.top_k,
    )
    print(path)


if __name__ == "__main__":
    main()
