from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from time import perf_counter

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from experiments.semantic.encoders import (
    ENCODER_CONFIGURATIONS,
    SentenceTransformerEncoder,
)
from experiments.semantic.probe import load_concepts
from experiments.semantic.public_sessions import (
    PublicMessageCaptureAgent,
    PublicObservation,
    derive_public_observations,
    public_retrieval_metrics,
)
from experiments.semantic.search import dense_search, lexical_search
from experiments.semantic.schemas import CatalogConcept
from starter.agent import Agent


def run_public_session_probe(
    catalog_path: str | Path,
    dataset_path: str | Path,
    artifact_path: str | Path,
    concept_path: str | Path,
    output_path: str | Path,
    model_names: tuple[str, ...],
    *,
    batch_size: int = 64,
    top_k: int = 10,
) -> Path:
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"public semantic output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    samples = load_jsonl(dataset_path)
    catalog_ids, categories, products = catalog_index(catalog_path)
    product_ordinals = {
        parent_asin: ordinal
        for ordinal, parent_asin in enumerate(products)
    }
    base_agent = Agent(catalog_path, artifact_path=artifact_path)
    capture = PublicMessageCaptureAgent(
        base_agent,
        tuple(str(sample["sample_id"]) for sample in samples),
    )
    evaluation_started = perf_counter()
    try:
        evaluation = evaluate(capture, samples, catalog_ids, categories, products)
    finally:
        capture.close()
    evaluation_seconds = perf_counter() - evaluation_started

    concepts = load_concepts(concept_path)
    observations = derive_public_observations(
        capture.turns,
        samples,
        product_ordinals,
        concepts,
    )
    systems = _run_systems(
        observations,
        concepts,
        model_names,
        batch_size=batch_size,
        top_k=top_k,
    )

    evaluation_sessions = evaluation.pop("sessions")
    payload = {
        "schema_version": 1,
        "benchmark_kind": "public-session-shadow-regression",
        "catalog_sha256": _sha256(Path(catalog_path)),
        "dataset_sha256": _sha256(Path(dataset_path)),
        "concept_sha256": _sha256(Path(concept_path)),
        "platform": platform.platform(),
        "python": sys.version,
        "public_session_count": len(samples),
        "captured_turn_count": len(capture.turns),
        "labeled_observation_count": len(observations),
        "labeled_session_count": len({item.sample_id for item in observations}),
        "concept_count": len(concepts),
        "top_k": top_k,
        "evaluation_seconds": round(evaluation_seconds, 6),
        "unchanged_public_evaluation": evaluation,
        "public_session_outcomes": evaluation_sessions,
        "captured_turns": [item.as_record() for item in capture.turns],
        "observations": [item.as_record() for item in observations],
        "systems": systems,
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def replay_public_session_probe(
    capture_path: str | Path,
    concept_path: str | Path,
    output_path: str | Path,
    model_names: tuple[str, ...],
    *,
    batch_size: int = 64,
    top_k: int = 10,
) -> Path:
    source = json.loads(Path(capture_path).read_text(encoding="utf-8"))
    if source.get("benchmark_kind") != "public-session-shadow-regression":
        raise ValueError("capture is not a public-session shadow regression")
    actual_concept_hash = _sha256(Path(concept_path))
    if source.get("concept_sha256") != actual_concept_hash:
        raise ValueError("capture concept inventory does not match requested inventory")
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"public semantic output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    concepts = load_concepts(concept_path)
    observations = tuple(
        PublicObservation.from_record(record)
        for record in source["observations"]
    )
    systems = _run_systems(
        observations,
        concepts,
        model_names,
        batch_size=batch_size,
        top_k=top_k,
    )
    payload = {
        key: value
        for key, value in source.items()
        if key != "systems"
    }
    payload.update({
        "replayed_from_sha256": _sha256(Path(capture_path)),
        "platform": platform.platform(),
        "python": sys.version,
        "top_k": top_k,
        "systems": systems,
    })
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output



def _run_systems(
    observations: tuple[PublicObservation, ...],
    concepts: tuple[CatalogConcept, ...],
    model_names: tuple[str, ...],
    *,
    batch_size: int,
    top_k: int,
) -> dict[str, object]:
    cases = tuple(item.case for item in observations)
    lexical_hits = {
        case.case_id: lexical_search(case, concepts, top_k=top_k)
        for case in cases
    }
    systems: dict[str, object] = {
        "lexical": {
            "metrics": public_retrieval_metrics(
                observations, lexical_hits, concepts
            ),
            "hits": _hit_records(lexical_hits),
        }
    }

    query_texts = tuple(case.query_text() for case in cases)
    surface_texts = tuple(concept.surface_text for concept in concepts)
    contextual_texts = tuple(concept.contextual_text for concept in concepts)
    for model_name in model_names:
        configuration = ENCODER_CONFIGURATIONS[model_name]
        started = perf_counter()
        encoder = SentenceTransformerEncoder(configuration, batch_size=batch_size)
        load_seconds = perf_counter() - started
        started = perf_counter()
        surface_vectors = encoder.encode_documents(surface_texts)
        contextual_vectors = encoder.encode_documents(contextual_texts)
        catalog_encode_seconds = perf_counter() - started
        started = perf_counter()
        query_vectors = encoder.encode_queries(query_texts)
        query_encode_seconds = perf_counter() - started
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
            "load_seconds": round(load_seconds, 6),
            "catalog_encode_seconds": round(catalog_encode_seconds, 6),
            "query_encode_seconds": round(query_encode_seconds, 6),
            "query_ms_per_observation": round(
                1000.0 * query_encode_seconds / max(1, len(observations)), 6
            ),
            "search_seconds": round(search_seconds, 6),
            "metrics": public_retrieval_metrics(observations, hits, concepts),
            "hits": _hit_records(hits),
        }

    return systems


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
        description="Run semantic retrieval in shadow over all public sessions"
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--artifacts", default="data/catalog.artifacts")
    parser.add_argument(
        "--concepts", default="experiments/semantic/generated/concepts.jsonl"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--capture",
        help="replay a prior lexical-only public-session capture",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=tuple(ENCODER_CONFIGURATIONS),
        default=("arctic-s", "bge-small", "arctic-xs", "minilm-l6"),
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    if args.capture:
        output = replay_public_session_probe(
            args.capture,
            args.concepts,
            args.output,
            tuple(args.models),
            batch_size=args.batch_size,
            top_k=args.top_k,
        )
    else:
        output = run_public_session_probe(
            args.catalog,
            args.dataset,
            args.artifacts,
            args.concepts,
            args.output,
            tuple(args.models),
            batch_size=args.batch_size,
            top_k=args.top_k,
        )
    print(output)


if __name__ == "__main__":
    main()
