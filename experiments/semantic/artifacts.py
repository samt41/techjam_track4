from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from experiments.semantic.probe import load_concepts


@dataclass(frozen=True, slots=True)
class EmbeddingArtifact:
    root: Path
    model_name: str
    model_id: str
    resolved_revision: str
    concept_sha256: str
    concept_count: int
    dimension: int
    surface_vectors: object
    contextual_vectors: object


def load_embedding_artifact(
    artifact_path: str | Path,
    concept_path: str | Path,
) -> EmbeddingArtifact:
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError("install semantic-experiment dependencies") from error
    root = Path(artifact_path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported semantic embedding artifact schema")
    concept_hash = sha256_file(Path(concept_path))
    if manifest.get("concept_sha256") != concept_hash:
        raise ValueError("semantic embedding artifact concept hash mismatch")
    concepts = load_concepts(concept_path)
    surfaces = np.load(root / "surface.npy", mmap_mode="r")
    contexts = np.load(root / "contextual.npy", mmap_mode="r")
    expected_shape = (len(concepts), int(manifest["dimension"]))
    if surfaces.shape != expected_shape or contexts.shape != expected_shape:
        raise ValueError("semantic embedding matrix shape mismatch")
    if str(surfaces.dtype) != "float32" or str(contexts.dtype) != "float32":
        raise ValueError("semantic embeddings must be float32")
    for filename, expected_hash in manifest["file_sha256"].items():
        if sha256_file(root / filename) != expected_hash:
            raise ValueError(f"semantic artifact hash mismatch: {filename}")
    return EmbeddingArtifact(
        root=root,
        model_name=str(manifest["model_name"]),
        model_id=str(manifest["model_id"]),
        resolved_revision=str(manifest["resolved_revision"]),
        concept_sha256=concept_hash,
        concept_count=len(concepts),
        dimension=int(manifest["dimension"]),
        surface_vectors=surfaces,
        contextual_vectors=contexts,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
