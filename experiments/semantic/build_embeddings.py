from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from time import perf_counter

from experiments.semantic.artifacts import sha256_file
from experiments.semantic.encoders import (
    ENCODER_CONFIGURATIONS,
    SentenceTransformerEncoder,
)
from experiments.semantic.probe import load_concepts


def build_embedding_artifact(
    concept_path: str | Path,
    output_path: str | Path,
    model_name: str,
    *,
    batch_size: int = 128,
) -> Path:
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError("install semantic-experiment dependencies") from error
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"semantic embedding artifact exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    concepts = load_concepts(concept_path)
    configuration = ENCODER_CONFIGURATIONS[model_name]
    started = perf_counter()
    encoder = SentenceTransformerEncoder(configuration, batch_size=batch_size)
    load_seconds = perf_counter() - started
    started = perf_counter()
    surfaces = np.asarray(encoder.encode_documents(
        tuple(concept.surface_text for concept in concepts)
    ), dtype=np.float32)
    contexts = np.asarray(encoder.encode_documents(
        tuple(concept.contextual_text for concept in concepts)
    ), dtype=np.float32)
    encode_seconds = perf_counter() - started
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        np.save(temporary / "surface.npy", surfaces, allow_pickle=False)
        np.save(temporary / "contextual.npy", contexts, allow_pickle=False)
        manifest = {
            "schema_version": 1,
            "model_name": model_name,
            "model_id": configuration.model_id,
            "requested_revision": configuration.revision,
            "resolved_revision": encoder.resolved_revision,
            "concept_sha256": sha256_file(Path(concept_path)),
            "concept_count": len(concepts),
            "dimension": encoder.dimension,
            "normalization": "l2",
            "dtype": "float32",
            "load_seconds": round(load_seconds, 6),
            "encode_seconds": round(encode_seconds, 6),
            "file_sha256": {
                "surface.npy": sha256_file(temporary / "surface.npy"),
                "contextual.npy": sha256_file(temporary / "contextual.npy"),
            },
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build reusable semantic concept embedding matrices"
    )
    parser.add_argument(
        "--concepts", default="experiments/semantic/generated/concepts.jsonl"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", choices=tuple(ENCODER_CONFIGURATIONS), required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    print(build_embedding_artifact(
        args.concepts,
        args.output,
        args.model,
        batch_size=args.batch_size,
    ))


if __name__ == "__main__":
    main()
