from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.semantic.build_gap_dataset import load_mappings
from experiments.semantic.encoders import ENCODER_CONFIGURATIONS
from experiments.semantic.hybrid_provider import (
    HybridConfiguration,
    SemanticHybridProvider,
)
from starter.shopping_agent.models import Attribute


def calibrate_models(
    concept_path: str | Path,
    embedding_root: str | Path,
    mapping_path: str | Path,
    contrast_path: str | Path,
    output_path: str | Path,
    model_names: tuple[str, ...],
) -> Path:
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"hybrid calibration exists: {output}")
    mappings = tuple(
        item for item in load_mappings(mapping_path)
        if item.split == "calibration"
    )
    contrast = tuple(
        json.loads(line)
        for line in Path(contrast_path).read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("split") == "calibration"
    )
    calibrated: dict[str, object] = {}
    for model_name in model_names:
        provider = SemanticHybridProvider(
            str(concept_path),
            str(Path(embedding_root) / model_name),
            model_name,
            HybridConfiguration(minimum_score=-1.0, minimum_margin=0.0),
        )
        expected_by_key = {
            (concept.attribute.value, concept.surface_text): concept.concept_id
            for concept in provider.concepts
        }
        positives: list[dict[str, object]] = []
        unsafe: list[dict[str, object]] = []
        for mapping in mappings:
            resolution = provider.resolve(
                mapping.paraphrase,
                Attribute(mapping.attribute),
            )
            expected = expected_by_key.get((mapping.attribute, mapping.surface_text))
            record = {
                "case_id": mapping.mapping_id,
                "expected_concept_id": expected,
                **resolution.as_record(),
            }
            if expected is not None and expected in resolution.concept_ids:
                positives.append(record)
        symbolic_blocks = 0
        for case in contrast:
            resolution = provider.resolve(str(case["message"]))
            record = {"case_id": str(case["case_id"]), **resolution.as_record()}
            if resolution.reason in {"symbolic_boundary", "generic"}:
                symbolic_blocks += 1
            else:
                unsafe.append(record)
        configuration, accepted_positive = _select_thresholds(positives, unsafe)
        calibrated[model_name] = {
            "model_id": ENCODER_CONFIGURATIONS[model_name].model_id,
            "minimum_score": configuration.minimum_score,
            "minimum_margin": configuration.minimum_margin,
            "route_weight": configuration.route_weight,
            "calibration_positive_count": len(mappings),
            "target_within_top_k_count": len(positives),
            "accepted_correct_count": accepted_positive,
            "unsafe_candidate_count": len(unsafe),
            "symbolic_block_count": symbolic_blocks,
            "positive_resolutions": positives,
            "unsafe_resolutions": unsafe,
        }
        provider.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({
            "schema_version": 1,
            "policy": "maximize correct calibration coverage with zero unsafe acceptance",
            "models": calibrated,
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _select_thresholds(
    positives: list[dict[str, object]],
    unsafe: list[dict[str, object]],
) -> tuple[HybridConfiguration, int]:
    best: tuple[int, float, float] | None = None
    for score_step in range(20, 91):
        minimum_score = score_step / 100.0
        for margin_step in range(0, 41):
            minimum_margin = margin_step / 200.0
            false_accepts = sum(
                float(item["score"]) >= minimum_score
                and float(item["margin"]) >= minimum_margin
                for item in unsafe
            )
            if false_accepts:
                continue
            accepted = sum(
                float(item["score"]) >= minimum_score
                and float(item["margin"]) >= minimum_margin
                for item in positives
            )
            candidate = (accepted, minimum_score, minimum_margin)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        raise ValueError("no safe hybrid calibration exists")
    accepted, minimum_score, minimum_margin = best
    return HybridConfiguration(
        minimum_score=minimum_score,
        minimum_margin=minimum_margin,
    ), accepted


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate semantic hybrid gates")
    parser.add_argument(
        "--concepts", default="experiments/semantic/generated/concepts.jsonl"
    )
    parser.add_argument(
        "--embeddings", default="experiments/semantic/generated/embeddings"
    )
    parser.add_argument(
        "--mappings", default="experiments/semantic/paraphrase_map.v1.jsonl"
    )
    parser.add_argument(
        "--contrast", default="experiments/semantic/contrast.v1.jsonl"
    )
    parser.add_argument(
        "--output", default="experiments/semantic/generated/hybrid-calibration.json"
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=tuple(ENCODER_CONFIGURATIONS),
        default=tuple(ENCODER_CONFIGURATIONS),
    )
    args = parser.parse_args()
    print(calibrate_models(
        args.concepts,
        args.embeddings,
        args.mappings,
        args.contrast,
        args.output,
        tuple(args.models),
    ))


if __name__ == "__main__":
    main()
