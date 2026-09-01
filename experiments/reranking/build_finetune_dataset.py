from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from evaluator.local_evaluator import coarse_category, load_jsonl, searchable_text
from experiments.reranking.rerankers import product_document
from starter.shopping_agent.local_search_backend import LocalProductSearchBackend
from starter.shopping_agent.models import RetrievalRoute
from starter.shopping_agent.search_backend import LexicalMode, SearchRequest
from starter.shopping_agent.text_normalization import normalize_text


@dataclass(frozen=True, slots=True)
class ParaphraseMapping:
    mapping_id: str
    attribute: str
    surface_text: str
    paraphrase: str
    split: str


@dataclass(frozen=True, slots=True)
class PairRow:
    query_id: str
    query: str
    document: str
    label: float
    product_id: str
    positive_product_id: str
    mapping_id: str
    surface_text: str
    paraphrase: str
    partition: str
    retrieval_rank: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_paraphrase_mappings(
    path: str | Path,
    *,
    split: str = "calibration",
) -> tuple[ParaphraseMapping, ...]:
    mappings = tuple(
        ParaphraseMapping(
            mapping_id=str(item["mapping_id"]),
            attribute=str(item["attribute"]),
            surface_text=str(item["surface_text"]),
            paraphrase=str(item["paraphrase"]),
            split=str(item["split"]),
        )
        for item in load_jsonl(path)
        if str(item.get("split")) == split
    )
    if not mappings:
        raise ValueError(f"no {split!r} paraphrase mappings found")
    identifiers = tuple(mapping.mapping_id for mapping in mappings)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("paraphrase mapping identifiers must be unique")
    return mappings


def heldout_product_ids(*dataset_paths: str | Path | None) -> frozenset[str]:
    result: set[str] = set()
    for raw_path in dataset_paths:
        if raw_path is None:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        for item in load_jsonl(path):
            result.add(str(item["ground_truth"]["parent_asin"]))
    if not result:
        raise ValueError("at least one held-out target product is required")
    return frozenset(result)


def product_partition(
    product_id: str,
    *,
    seed: int,
    validation_fraction: float,
) -> str:
    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction must be between zero and one")
    digest = hashlib.sha256(f"{seed}\0{product_id}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(2**64)
    return "validation" if bucket < validation_fraction else "train"


def ranking_training_query(mapping: ParaphraseMapping, category: str) -> str:
    return (
        "shopping request; "
        f"require category: {normalize_text(category)}; "
        f"prefer {normalize_text(mapping.attribute)}: "
        f"{normalize_text(mapping.paraphrase)}"
    )


def audit_pair_rows(
    train_rows: list[PairRow],
    validation_rows: list[PairRow],
    *,
    heldout_ids: frozenset[str],
    allowed_mapping_ids: frozenset[str],
    minimum_negatives: int,
) -> dict[str, object]:
    if minimum_negatives < 1:
        raise ValueError("minimum_negatives must be positive")
    if not train_rows or not validation_rows:
        raise ValueError("train and validation rows must both be non-empty")

    split_products: dict[str, set[str]] = {}
    split_groups: dict[str, dict[str, list[PairRow]]] = {}
    for split_name, rows in (
        ("train", train_rows),
        ("validation", validation_rows),
    ):
        products = {row.product_id for row in rows}
        leaked = products.intersection(heldout_ids)
        if leaked:
            raise ValueError(
                f"{split_name} contains held-out products: {sorted(leaked)[:3]}"
            )
        split_products[split_name] = products
        groups: dict[str, list[PairRow]] = defaultdict(list)
        for row in rows:
            if row.partition != split_name:
                raise ValueError(
                    f"row {row.query_id} declares partition {row.partition!r} "
                    f"inside {split_name!r}"
                )
            if row.mapping_id not in allowed_mapping_ids:
                raise ValueError(
                    f"row {row.query_id} uses reserved mapping {row.mapping_id!r}"
                )
            if row.label not in (0.0, 1.0):
                raise ValueError("pair labels must be binary floats")
            if not row.query.strip() or not row.document.strip():
                raise ValueError("pair text must not be empty")
            groups[row.query_id].append(row)
        split_groups[split_name] = groups

    overlap = split_products["train"].intersection(split_products["validation"])
    if overlap:
        raise ValueError(
            f"products cross train/validation partitions: {sorted(overlap)[:3]}"
        )

    group_count = 0
    negative_count = 0
    mapping_counts: Counter[str] = Counter()
    for split_name, groups in split_groups.items():
        for query_id, rows in groups.items():
            group_count += 1
            positives = [row for row in rows if row.label == 1.0]
            negatives = [row for row in rows if row.label == 0.0]
            if len(positives) != 1:
                raise ValueError(f"group {query_id} must have exactly one positive")
            if len(negatives) < minimum_negatives:
                raise ValueError(
                    f"group {query_id} has fewer than {minimum_negatives} negatives"
                )
            positive = positives[0]
            if positive.product_id != positive.positive_product_id:
                raise ValueError(f"group {query_id} positive product is inconsistent")
            normalized_document = normalize_text(positive.document)
            if normalize_text(positive.surface_text) not in normalized_document:
                raise ValueError(f"group {query_id} positive lacks its surface text")
            if normalize_text(positive.paraphrase) in normalized_document:
                raise ValueError(
                    f"group {query_id} copies the paraphrase into the positive"
                )
            if normalize_text(positive.paraphrase) not in normalize_text(positive.query):
                raise ValueError(f"group {query_id} query lacks its paraphrase")
            for row in rows:
                if row.query != positive.query:
                    raise ValueError(f"group {query_id} contains inconsistent queries")
                if row.positive_product_id != positive.product_id:
                    raise ValueError(
                        f"group {query_id} contains inconsistent positive identifiers"
                    )
            for negative in negatives:
                if negative.product_id == positive.product_id:
                    raise ValueError(f"group {query_id} labels its positive as negative")
                normalized_negative = normalize_text(negative.document)
                if normalize_text(negative.surface_text) in normalized_negative:
                    raise ValueError(
                        f"group {query_id} negative contains the positive surface"
                    )
                if normalize_text(negative.paraphrase) in normalized_negative:
                    raise ValueError(
                        f"group {query_id} negative contains the query paraphrase"
                    )
            negative_count += len(negatives)
            mapping_counts[positive.mapping_id] += 1

    return {
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "train_products": len(split_products["train"]),
        "validation_products": len(split_products["validation"]),
        "group_count": group_count,
        "negative_count": negative_count,
        "mapping_group_counts": dict(sorted(mapping_counts.items())),
        "heldout_product_count": len(heldout_ids),
    }


def build_dataset(
    *,
    catalog_path: str | Path,
    artifact_path: str | Path,
    public_path: str | Path,
    gap_path: str | Path | None,
    mapping_path: str | Path,
    output_dir: str | Path,
    seed: int,
    validation_fraction: float,
    train_groups_per_mapping: int,
    validation_groups_per_mapping: int,
    negatives_per_group: int,
) -> Path:
    if train_groups_per_mapping < 1 or validation_groups_per_mapping < 1:
        raise ValueError("group limits must be positive")
    if negatives_per_group < 2:
        raise ValueError("at least two hard negatives are required")
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"fine-tuning dataset already exists: {output}")

    mappings = load_paraphrase_mappings(mapping_path, split="calibration")
    heldout = heldout_product_ids(public_path, gap_path)
    raw_products: dict[str, dict] = {}
    product_text: dict[str, str] = {}
    product_category: dict[str, str] = {}
    anchors_by_mapping: dict[str, list[str]] = defaultdict(list)
    with Path(catalog_path).open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            product_id = str(item["parent_asin"])
            raw_products[product_id] = item
            normalized = normalize_text(searchable_text(item))
            product_text[product_id] = normalized
            category = coarse_category(
                [str(value) for value in item.get("categories") or []]
            )
            product_category[product_id] = normalize_text(category)
            if product_id in heldout:
                continue
            for mapping in mappings:
                surface = normalize_text(mapping.surface_text)
                paraphrase = normalize_text(mapping.paraphrase)
                if surface in normalized and paraphrase not in normalized:
                    anchors_by_mapping[mapping.mapping_id].append(product_id)

    category_members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for product_id, category in product_category.items():
        if product_id in heldout:
            continue
        partition = product_partition(
            product_id,
            seed=seed,
            validation_fraction=validation_fraction,
        )
        category_members[(partition, category)].append(product_id)
    for members in category_members.values():
        members.sort(key=lambda item: _stable_key(seed, "fallback", item))

    backend = LocalProductSearchBackend.open(
        catalog_path,
        artifact_path,
        lexical_mode=LexicalMode.AUTO,
    )
    rows: dict[str, list[PairRow]] = {"train": [], "validation": []}
    skipped: Counter[str] = Counter()
    try:
        for mapping in mappings:
            ordered_anchors = sorted(
                anchors_by_mapping[mapping.mapping_id],
                key=lambda item: _stable_key(seed, mapping.mapping_id, item),
            )
            limits = {
                "train": train_groups_per_mapping,
                "validation": validation_groups_per_mapping,
            }
            used = {"train": 0, "validation": 0}
            for anchor_id in ordered_anchors:
                partition = product_partition(
                    anchor_id,
                    seed=seed,
                    validation_fraction=validation_fraction,
                )
                if used[partition] >= limits[partition]:
                    continue
                anchor_records = backend.get_products((anchor_id,))
                if len(anchor_records) != 1:
                    skipped["missing_anchor_record"] += 1
                    continue
                anchor = anchor_records[0]
                document = product_document(anchor)
                query = ranking_training_query(
                    mapping,
                    product_category[anchor_id],
                )
                if normalize_text(mapping.surface_text) not in normalize_text(document):
                    # Raw list fields are concatenated with spaces during the
                    # first scan. A phrase can appear only across two adjacent
                    # field values (for example duplicated "... buckle" and
                    # "closure ...") even though the serving document keeps a
                    # separator between them. Train only on evidence visible to
                    # the actual cross-encoder input.
                    skipped["surface_missing_from_serving_document"] += 1
                    continue
                if normalize_text(mapping.paraphrase) in normalize_text(document):
                    skipped["paraphrase_in_positive"] += 1
                    continue
                negative_ids = _mine_negative_ids(
                    anchor_id=anchor_id,
                    anchor_title=anchor.title,
                    category=product_category[anchor_id],
                    partition=partition,
                    mapping=mapping,
                    backend=backend,
                    product_text=product_text,
                    product_category=product_category,
                    category_members=category_members,
                    heldout=heldout,
                    seed=seed,
                    validation_fraction=validation_fraction,
                    count=negatives_per_group,
                )
                if len(negative_ids) < negatives_per_group:
                    skipped["insufficient_negatives"] += 1
                    continue
                negative_records = backend.get_products(negative_ids)
                if len(negative_records) != len(negative_ids):
                    skipped["missing_negative_record"] += 1
                    continue
                query_id = f"{partition}:{mapping.mapping_id}:{anchor_id}"
                rows[partition].append(PairRow(
                    query_id=query_id,
                    query=query,
                    document=document,
                    label=1.0,
                    product_id=anchor_id,
                    positive_product_id=anchor_id,
                    mapping_id=mapping.mapping_id,
                    surface_text=mapping.surface_text,
                    paraphrase=mapping.paraphrase,
                    partition=partition,
                    retrieval_rank=0,
                ))
                for rank, negative in enumerate(negative_records, start=1):
                    rows[partition].append(PairRow(
                        query_id=query_id,
                        query=query,
                        document=product_document(negative),
                        label=0.0,
                        product_id=negative.parent_asin,
                        positive_product_id=anchor_id,
                        mapping_id=mapping.mapping_id,
                        surface_text=mapping.surface_text,
                        paraphrase=mapping.paraphrase,
                        partition=partition,
                        retrieval_rank=rank,
                    ))
                used[partition] += 1
                if all(used[name] >= limits[name] for name in used):
                    break
            for partition in used:
                if used[partition] < limits[partition]:
                    raise ValueError(
                        f"mapping {mapping.mapping_id} produced only "
                        f"{used[partition]}/{limits[partition]} {partition} groups"
                    )
    finally:
        backend.close()

    audit = audit_pair_rows(
        rows["train"],
        rows["validation"],
        heldout_ids=heldout,
        allowed_mapping_ids=frozenset(
            mapping.mapping_id for mapping in mappings
        ),
        minimum_negatives=negatives_per_group,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        train_path = temporary / "train.jsonl"
        validation_path = temporary / "validation.jsonl"
        _write_rows(train_path, rows["train"])
        _write_rows(validation_path, rows["validation"])
        manifest = {
            "schema_version": 1,
            "model_identifier": "cross-encoder/ms-marco-MiniLM-L6-v2",
            "seed": seed,
            "validation_fraction": validation_fraction,
            "train_groups_per_mapping": train_groups_per_mapping,
            "validation_groups_per_mapping": validation_groups_per_mapping,
            "negatives_per_group": negatives_per_group,
            "catalog_sha256": _sha256(Path(catalog_path)),
            "public_sha256": _sha256(Path(public_path)),
            "gap_sha256": (
                None
                if gap_path is None or not Path(gap_path).exists()
                else _sha256(Path(gap_path))
            ),
            "mapping_sha256": _sha256(Path(mapping_path)),
            "train_sha256": _sha256(train_path),
            "validation_sha256": _sha256(validation_path),
            "code_revision": _code_revision(),
            "mapping_ids": [mapping.mapping_id for mapping in mappings],
            "skipped": dict(sorted(skipped.items())),
            "audit": audit,
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def _mine_negative_ids(
    *,
    anchor_id: str,
    anchor_title: str,
    category: str,
    partition: str,
    mapping: ParaphraseMapping,
    backend: LocalProductSearchBackend,
    product_text: dict[str, str],
    product_category: dict[str, str],
    category_members: dict[tuple[str, str], list[str]],
    heldout: frozenset[str],
    seed: int,
    validation_fraction: float,
    count: int,
) -> tuple[str, ...]:
    result = backend.search(SearchRequest(
        route=RetrievalRoute.EXPANDED_FTS,
        lexical_terms=(category, anchor_title),
        filters=(),
        limit=100,
        work_limit=10_000,
    ))
    candidates: list[str] = []
    ranked = [hit.parent_asin for hit in result.hits]
    fallback = category_members.get((partition, category), [])
    for product_id in (*ranked, *fallback):
        if product_id in candidates:
            continue
        if not _valid_negative(
            product_id,
            anchor_id=anchor_id,
            category=category,
            partition=partition,
            mapping=mapping,
            product_text=product_text,
            product_category=product_category,
            heldout=heldout,
            seed=seed,
            validation_fraction=validation_fraction,
        ):
            continue
        candidates.append(product_id)
        if len(candidates) >= count:
            break
    return tuple(candidates)


def _valid_negative(
    product_id: str,
    *,
    anchor_id: str,
    category: str,
    partition: str,
    mapping: ParaphraseMapping,
    product_text: dict[str, str],
    product_category: dict[str, str],
    heldout: frozenset[str],
    seed: int,
    validation_fraction: float,
) -> bool:
    if product_id == anchor_id or product_id in heldout:
        return False
    if product_id not in product_text or product_category.get(product_id) != category:
        return False
    if product_partition(
        product_id,
        seed=seed,
        validation_fraction=validation_fraction,
    ) != partition:
        return False
    text = product_text[product_id]
    return (
        normalize_text(mapping.surface_text) not in text
        and normalize_text(mapping.paraphrase) not in text
    )


def _stable_key(seed: int, namespace: str, product_id: str) -> str:
    return hashlib.sha256(
        f"{seed}\0{namespace}\0{product_id}".encode()
    ).hexdigest()


def _write_rows(path: Path, rows: list[PairRow]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), sort_keys=True) + "\n")


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
        description="Build leakage-safe synthetic MiniLM-L6 reranker pairs"
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--artifacts", default="data/catalog.artifacts")
    parser.add_argument("--public", default="data/public_set.jsonl")
    parser.add_argument(
        "--gap", default="experiments/semantic/generated/semantic-gap-v1.jsonl"
    )
    parser.add_argument(
        "--mappings", default="experiments/semantic/paraphrase_map.v1.jsonl"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--train-groups-per-mapping", type=int, default=100)
    parser.add_argument("--validation-groups-per-mapping", type=int, default=25)
    parser.add_argument("--negatives-per-group", type=int, default=3)
    args = parser.parse_args()
    output = build_dataset(
        catalog_path=args.catalog,
        artifact_path=args.artifacts,
        public_path=args.public,
        gap_path=args.gap,
        mapping_path=args.mappings,
        output_dir=args.output,
        seed=args.seed,
        validation_fraction=args.validation_fraction,
        train_groups_per_mapping=args.train_groups_per_mapping,
        validation_groups_per_mapping=args.validation_groups_per_mapping,
        negatives_per_group=args.negatives_per_group,
    )
    print(output)


if __name__ == "__main__":
    main()
