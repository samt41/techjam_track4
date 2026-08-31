from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

from evaluator.local_evaluator import (
    behavior_for,
    catalog_index,
    load_jsonl,
    materialize_hidden_fields,
)
from starter.shopping_agent.text_normalization import normalize_text


@dataclass(frozen=True, slots=True)
class ParaphraseMapping:
    mapping_id: str
    split: str
    attribute: str
    surface_text: str
    paraphrase: str

    @classmethod
    def from_record(cls, record: dict[str, object]) -> ParaphraseMapping:
        item = cls(
            mapping_id=str(record["mapping_id"]),
            split=str(record["split"]),
            attribute=str(record["attribute"]),
            surface_text=normalize_text(record["surface_text"]),
            paraphrase=str(record["paraphrase"]),
        )
        if item.split not in {"calibration", "test"}:
            raise ValueError("paraphrase split must be calibration or test")
        if not item.mapping_id or not item.surface_text or not item.paraphrase:
            raise ValueError("paraphrase mapping fields must not be empty")
        return item


def load_mappings(path: str | Path) -> tuple[ParaphraseMapping, ...]:
    mappings = tuple(
        ParaphraseMapping.from_record(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    identifiers = tuple(item.mapping_id for item in mappings)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate paraphrase mapping id")
    return mappings


def build_gap_dataset(
    catalog_path: str | Path,
    dataset_path: str | Path,
    mapping_path: str | Path,
    output_path: str | Path,
    lineage_path: str | Path,
) -> tuple[Path, Path]:
    output = Path(output_path)
    lineage = Path(lineage_path)
    if output.exists() or lineage.exists():
        raise FileExistsError("gap dataset output already exists")
    mappings = tuple(
        item for item in load_mappings(mapping_path) if item.split == "test"
    )
    mapping_by_surface = {item.surface_text: item for item in mappings}
    samples = load_jsonl(dataset_path)
    _, _, products = catalog_index(catalog_path)
    derived: list[dict] = []
    replacements: list[dict[str, object]] = []
    for sample in samples:
        card, _ = materialize_hidden_fields(sample, products)
        replacement = _replace_one(card, mapping_by_surface)
        if replacement is None:
            continue
        modified_card, mapping, field_name, field_index = replacement
        seed_source = f"{sample.get('sample_id', '')}\0{sample.get('scenario_type', '')}"
        behavior = behavior_for(
            str(sample["scenario_type"]),
            modified_card,
            random.Random(seed_source),
        )
        derived.append({
            **sample,
            "intent_card": modified_card,
            "behavior": behavior,
        })
        replacements.append({
            "sample_id": str(sample["sample_id"]),
            "mapping_id": mapping.mapping_id,
            "field": field_name,
            "index": field_index,
            "surface_text": mapping.surface_text,
            "paraphrase": mapping.paraphrase,
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in derived),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "source_catalog_sha256": _sha256(Path(catalog_path)),
        "source_dataset_sha256": _sha256(Path(dataset_path)),
        "mapping_sha256": _sha256(Path(mapping_path)),
        "derived_dataset_sha256": _sha256(output),
        "source_session_count": len(samples),
        "derived_session_count": len(derived),
        "replacements": replacements,
    }
    lineage.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output, lineage


def _replace_one(
    card: dict,
    mapping_by_surface: dict[str, ParaphraseMapping],
) -> tuple[dict, ParaphraseMapping, str, int] | None:
    modified = {
        "target_category": str(card["target_category"]),
        "hard_constraints": list(card.get("hard_constraints", ())),
        "soft_preferences": list(card.get("soft_preferences", ())),
    }
    for field_name in ("hard_constraints", "soft_preferences"):
        values = modified[field_name]
        for index, raw_value in enumerate(values):
            mapping = mapping_by_surface.get(normalize_text(raw_value))
            if mapping is None:
                continue
            values[index] = mapping.paraphrase
            return modified, mapping, field_name, index
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build held-out public-session semantic-gap dataset"
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument(
        "--mappings", default="experiments/semantic/paraphrase_map.v1.jsonl"
    )
    parser.add_argument(
        "--output", default="experiments/semantic/generated/semantic-gap-v1.jsonl"
    )
    parser.add_argument(
        "--lineage", default="experiments/semantic/generated/semantic-gap-v1.lineage.json"
    )
    args = parser.parse_args()
    output, lineage = build_gap_dataset(
        args.catalog, args.dataset, args.mappings, args.output, args.lineage
    )
    print(json.dumps({"output": str(output), "lineage": str(lineage)}))


if __name__ == "__main__":
    main()
