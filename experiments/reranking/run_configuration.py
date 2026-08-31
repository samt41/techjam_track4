from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from time import perf_counter

from evaluator.local_evaluator import (
    catalog_index,
    evaluate,
    load_jsonl,
    materialize_hidden_fields,
)
from experiments.reranking.rerankers import (
    CrossEncoderRecommendationReranker,
    RecordingRecommendationReranker,
    RerankEvent,
    latency_summary,
)
from starter.agent import Agent


class SampleMappingAgent:
    """Maps evaluator runtime UUIDs back to stable sample IDs after inference."""

    def __init__(
        self,
        agent: Agent,
        sample_ids: tuple[str, ...],
        progress_label: str | None = None,
    ) -> None:
        self.agent = agent
        self.sample_ids = sample_ids
        self.progress_label = progress_label
        self.reset_count = 0
        self.sample_by_session: dict[str, str] = {}

    def reset(self, session_id: str, profile: dict[str, object]) -> None:
        if self.reset_count >= len(self.sample_ids):
            raise ValueError("evaluator reset more sessions than expected")
        if self.progress_label is not None and self.reset_count % 25 == 0:
            print(
                f"{self.progress_label}: session "
                f"{self.reset_count + 1}/{len(self.sample_ids)}",
                flush=True,
            )
        self.sample_by_session[session_id] = self.sample_ids[self.reset_count]
        self.reset_count += 1
        self.agent.reset(session_id, profile)

    def respond(self, session_id, message, turn, top_k):
        return self.agent.respond(session_id, message, turn, top_k)

    def close(self) -> None:
        self.agent.close()


def run_configuration(
    configuration_name: str,
    model_name: str | None,
    catalog_path: str | Path,
    artifact_path: str | Path,
    public_path: str | Path,
    gap_path: str | Path | None,
    output_path: str | Path,
    *,
    candidate_pool_size: int,
    fusion_weight: float,
    batch_size: int,
    max_length: int,
    device: str | None,
) -> Path:
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"reranking output already exists: {output}")
    catalog_ids, categories, products = catalog_index(catalog_path)
    reranker = (
        RecordingRecommendationReranker(candidate_pool_size)
        if model_name is None
        else CrossEncoderRecommendationReranker(
            model_name,
            candidate_pool_size=candidate_pool_size,
            fusion_weight=fusion_weight,
            batch_size=batch_size,
            max_length=max_length,
            device=device,
        )
    )
    public = _run_dataset(
        catalog_path,
        artifact_path,
        public_path,
        catalog_ids,
        categories,
        products,
        reranker,
    )
    gap = None
    if gap_path is not None:
        gap = _run_dataset(
            catalog_path,
            artifact_path,
            gap_path,
            catalog_ids,
            categories,
            products,
            reranker,
        )
    payload = {
        "schema_version": 1,
        "configuration_name": configuration_name,
        "mode": "oracle" if model_name is None else "cross_encoder",
        "model_name": model_name,
        "model_identifier": getattr(reranker, "model_identifier", None),
        "device": getattr(reranker, "device", None),
        "candidate_pool_size": candidate_pool_size,
        "fusion_weight": None if model_name is None else fusion_weight,
        "batch_size": None if model_name is None else batch_size,
        "max_length": None if model_name is None else max_length,
        "catalog_sha256": _sha256(Path(catalog_path)),
        "public_dataset_sha256": _sha256(Path(public_path)),
        "gap_dataset_sha256": (
            None if gap_path is None else _sha256(Path(gap_path))
        ),
        "code_revision": _code_revision(),
        "platform": platform.platform(),
        "python": sys.version,
        "public": public,
        "semantic_gap": gap,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reranker.close()
    return output


def _run_dataset(
    catalog_path,
    artifact_path,
    dataset_path,
    catalog_ids,
    categories,
    products,
    reranker,
) -> dict[str, object]:
    samples = load_jsonl(dataset_path)
    print(
        f"starting {Path(dataset_path).name}: {len(samples)} sessions",
        flush=True,
    )
    event_offset = len(reranker.events)
    agent = Agent(
        catalog_path,
        artifact_path=artifact_path,
        recommendation_reranker=reranker,
    )
    mapped = SampleMappingAgent(
        agent,
        tuple(str(sample["sample_id"]) for sample in samples),
        Path(dataset_path).name,
    )
    started = perf_counter()
    try:
        result = evaluate(mapped, samples, catalog_ids, categories, products)
    finally:
        mapped.close()
    elapsed_seconds = perf_counter() - started
    # Do not close between datasets: the scorer and its safe score cache are reused.
    events = reranker.events[event_offset:]
    sessions = result.pop("sessions")
    print(
        f"finished {Path(dataset_path).name}: "
        f"{elapsed_seconds:.1f}s, {len(events)} rerank events",
        flush=True,
    )
    return {
        **result,
        "dataset_sha256": _sha256(Path(dataset_path)),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "sessions": sessions,
        "reranker": {
            **latency_summary(events),
            **candidate_pool_metrics(
                events,
                mapped.sample_by_session,
                samples,
                products,
            ),
        },
    }


def candidate_pool_metrics(
    events: list[RerankEvent],
    sample_by_session: dict[str, str],
    samples: list[dict],
    products: dict[str, dict],
) -> dict[str, object]:
    sample_records = {str(item["sample_id"]): item for item in samples}
    events_by_sample: dict[str, list[RerankEvent]] = defaultdict(list)
    for event in events:
        sample_id = sample_by_session.get(event.session_id)
        if sample_id is not None:
            events_by_sample[sample_id].append(event)

    cutoffs = (10, 25, 50, 100, 200)
    coverage = {cutoff: 0 for cutoff in cutoffs}
    reranked_top_ten = 0
    minimum_ranks: list[int] = []
    for sample_id, sample in sample_records.items():
        target = str(sample["ground_truth"]["parent_asin"])
        _, behavior = materialize_hidden_fields(sample, products)
        valid_from_turn = 1
        if str(sample["scenario_type"]) == "intent_override":
            valid_from_turn = int((behavior.get("override") or {}).get("turn", 3))
        valid_events = tuple(
            event
            for event in events_by_sample.get(sample_id, ())
            if event.turn >= valid_from_turn
        )
        ranks = [
            event.baseline_ids.index(target) + 1
            for event in valid_events
            if target in event.baseline_ids
        ]
        if ranks:
            minimum_ranks.append(min(ranks))
        for cutoff in cutoffs:
            if any(target in event.baseline_ids[:cutoff] for event in valid_events):
                coverage[cutoff] += 1
        if any(target in event.reranked_ids[:10] for event in valid_events):
            reranked_top_ten += 1

    sample_count = len(samples)
    return {
        "sample_count": sample_count,
        "mapped_event_count": sum(len(value) for value in events_by_sample.values()),
        "session_candidate_coverage": {
            str(cutoff): round(coverage[cutoff] / sample_count, 6)
            for cutoff in cutoffs
        },
        "session_reranked_top_ten_coverage": round(
            reranked_top_ten / sample_count, 6
        ),
        "minimum_candidate_rank_mean": (
            None if not minimum_ranks else round(sum(minimum_ranks) / len(minimum_ranks), 6)
        ),
        "minimum_candidate_rank_max": max(minimum_ranks, default=None),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _code_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one cross-encoder recommendation-reranking configuration"
    )
    parser.add_argument("--configuration", required=True)
    parser.add_argument(
        "--model", choices=("minilm-l4", "minilm-l6", "bge-base")
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--artifacts", default="data/catalog.artifacts")
    parser.add_argument("--public", default="data/public_set.jsonl")
    parser.add_argument(
        "--gap", default="experiments/semantic/generated/semantic-gap-v1.jsonl"
    )
    parser.add_argument("--skip-gap", action="store_true")
    parser.add_argument("--pool-size", type=int, default=100)
    parser.add_argument("--fusion-weight", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--device")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(run_configuration(
        args.configuration,
        args.model,
        args.catalog,
        args.artifacts,
        args.public,
        None if args.skip_gap else args.gap,
        args.output,
        candidate_pool_size=args.pool_size,
        fusion_weight=args.fusion_weight,
        batch_size=args.batch_size,
        max_length=args.max_length,
        device=args.device,
    ))


if __name__ == "__main__":
    main()
