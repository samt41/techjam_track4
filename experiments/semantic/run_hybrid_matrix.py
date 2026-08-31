from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from experiments.semantic.hybrid_provider import (
    HybridConfiguration,
    SemanticHybridProvider,
)
from starter.agent import Agent


def run_configuration(
    configuration_name: str,
    catalog_path: str | Path,
    artifact_path: str | Path,
    public_dataset_path: str | Path,
    gap_dataset_path: str | Path,
    contrast_path: str | Path,
    concept_path: str | Path,
    embedding_root: str | Path,
    calibration_path: str | Path,
    output_path: str | Path,
    *,
    model_name: str | None,
) -> Path:
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"hybrid matrix output exists: {output}")
    calibration = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
    if model_name is None:
        hybrid_configuration = None
    else:
        raw = calibration["models"][model_name]
        hybrid_configuration = HybridConfiguration(
            minimum_score=float(raw["minimum_score"]),
            minimum_margin=float(raw["minimum_margin"]),
            route_weight=float(raw["route_weight"]),
        )

    catalog_ids, categories, products = catalog_index(catalog_path)
    public = _run_dataset(
        catalog_path,
        artifact_path,
        public_dataset_path,
        catalog_ids,
        categories,
        products,
        concept_path,
        embedding_root,
        model_name,
        hybrid_configuration,
    )
    gap = _run_dataset(
        catalog_path,
        artifact_path,
        gap_dataset_path,
        catalog_ids,
        categories,
        products,
        concept_path,
        embedding_root,
        model_name,
        hybrid_configuration,
    )
    contrast = _run_contrast(
        contrast_path,
        concept_path,
        embedding_root,
        model_name,
        hybrid_configuration,
    )
    payload = {
        "schema_version": 1,
        "configuration_name": configuration_name,
        "mode": "disabled" if model_name is None else "hybrid",
        "model_name": model_name,
        "hybrid_configuration": (
            None if hybrid_configuration is None else {
                "minimum_score": hybrid_configuration.minimum_score,
                "minimum_margin": hybrid_configuration.minimum_margin,
                "route_weight": hybrid_configuration.route_weight,
                "concept_top_k": hybrid_configuration.concept_top_k,
                "product_limit": hybrid_configuration.product_limit,
            }
        ),
        "catalog_sha256": _sha256(Path(catalog_path)),
        "public_dataset_sha256": _sha256(Path(public_dataset_path)),
        "gap_dataset_sha256": _sha256(Path(gap_dataset_path)),
        "contrast_sha256": _sha256(Path(contrast_path)),
        "concept_sha256": _sha256(Path(concept_path)),
        "calibration_sha256": _sha256(Path(calibration_path)),
        "platform": platform.platform(),
        "python": sys.version,
        "public": public,
        "semantic_gap": gap,
        "contrast_test": contrast,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _run_dataset(
    catalog_path,
    artifact_path,
    dataset_path,
    catalog_ids,
    categories,
    products,
    concept_path,
    embedding_root,
    model_name,
    hybrid_configuration,
) -> dict[str, object]:
    samples = load_jsonl(dataset_path)
    provider = _provider(
        concept_path, embedding_root, model_name, hybrid_configuration
    )
    agent = Agent(
        catalog_path,
        artifact_path=artifact_path,
        candidate_provider=provider,
    )
    started = perf_counter()
    try:
        result = evaluate(agent, samples, catalog_ids, categories, products)
    finally:
        agent.close()
    elapsed_seconds = perf_counter() - started
    sessions = result.pop("sessions")
    return {
        **result,
        "dataset_sha256": _sha256(Path(dataset_path)),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "semantic": _provider_metrics(provider),
        "sessions": sessions,
    }


def _run_contrast(
    contrast_path,
    concept_path,
    embedding_root,
    model_name,
    hybrid_configuration,
) -> dict[str, object]:
    cases = tuple(
        json.loads(line)
        for line in Path(contrast_path).read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("split") == "test"
    )
    provider = _provider(
        concept_path, embedding_root, model_name, hybrid_configuration
    )
    if provider is None:
        return {
            "case_count": len(cases),
            "accepted_count": 0,
            "passed": True,
            "resolutions": [],
        }
    resolutions = tuple(
        {
            "case_id": str(case["case_id"]),
            "kind": str(case["kind"]),
            **provider.resolve(str(case["message"])).as_record(),
        }
        for case in cases
    )
    accepted_count = sum(bool(item["accepted"]) for item in resolutions)
    provider.close()
    return {
        "case_count": len(cases),
        "accepted_count": accepted_count,
        "passed": accepted_count == 0,
        "resolutions": resolutions,
    }


def _provider(concept_path, embedding_root, model_name, configuration):
    if model_name is None:
        return None
    return SemanticHybridProvider(
        str(concept_path),
        str(Path(embedding_root) / model_name),
        model_name,
        configuration,
    )


def _provider_metrics(provider) -> dict[str, object]:
    if provider is None:
        return {
            "resolution_count": 0,
            "accepted_count": 0,
            "reason_counts": {},
            "latency_ms_p50": 0.0,
            "latency_ms_p95": 0.0,
        }
    reason_counts: dict[str, int] = {}
    for resolution in provider.resolutions:
        reason_counts[resolution.reason] = reason_counts.get(resolution.reason, 0) + 1
    latencies = sorted(item.elapsed_ms for item in provider.resolutions)
    return {
        "resolution_count": len(provider.resolutions),
        "accepted_count": sum(item.accepted for item in provider.resolutions),
        "reason_counts": reason_counts,
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 6)
    return round(statistics.quantiles(values, n=100, method="inclusive")[
        max(0, min(99, int(fraction * 100) - 1))
    ], 6)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one disabled or semantic-hybrid end-to-end configuration"
    )
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--model", choices=("arctic-s", "bge-small", "arctic-xs", "minilm-l6"))
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--artifacts", default="data/catalog.artifacts")
    parser.add_argument("--public", default="data/public_set.jsonl")
    parser.add_argument(
        "--gap", default="experiments/semantic/generated/semantic-gap-v1.jsonl"
    )
    parser.add_argument(
        "--contrast", default="experiments/semantic/contrast.v1.jsonl"
    )
    parser.add_argument(
        "--concepts", default="experiments/semantic/generated/concepts.jsonl"
    )
    parser.add_argument(
        "--embeddings", default="experiments/semantic/generated/embeddings"
    )
    parser.add_argument(
        "--calibration", default="experiments/semantic/generated/hybrid-calibration-v3.json"
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(run_configuration(
        args.configuration,
        args.catalog,
        args.artifacts,
        args.public,
        args.gap,
        args.contrast,
        args.concepts,
        args.embeddings,
        args.calibration,
        args.output,
        model_name=args.model,
    ))


if __name__ == "__main__":
    main()
