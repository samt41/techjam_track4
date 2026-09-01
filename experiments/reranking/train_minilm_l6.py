from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from time import perf_counter


MODEL_IDENTIFIER = "cross-encoder/ms-marco-MiniLM-L6-v2"


def load_pair_rows(path: str | Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            required = {
                "query_id",
                "query",
                "document",
                "label",
                "product_id",
                "mapping_id",
            }
            missing = required.difference(item)
            if missing:
                raise ValueError(
                    f"{path}:{line_number} missing fields: {sorted(missing)}"
                )
            label = float(item["label"])
            if label not in (0.0, 1.0):
                raise ValueError(f"{path}:{line_number} has non-binary label")
            item["label"] = label
            rows.append(item)
    if not rows:
        raise ValueError(f"no pair rows found in {path}")
    return rows


def select_balanced_groups(
    rows: list[dict[str, object]],
    maximum_groups: int | None,
) -> list[dict[str, object]]:
    if maximum_groups is None:
        return rows
    if maximum_groups < 1:
        raise ValueError("maximum_groups must be positive")
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row["query_id"])].append(row)
    by_mapping: dict[str, deque[str]] = defaultdict(deque)
    for query_id in sorted(groups):
        mapping_ids = {str(row["mapping_id"]) for row in groups[query_id]}
        if len(mapping_ids) != 1:
            raise ValueError(f"query group {query_id} crosses mappings")
        by_mapping[next(iter(mapping_ids))].append(query_id)
    selected: list[str] = []
    mapping_order = sorted(by_mapping)
    while len(selected) < maximum_groups:
        added = False
        for mapping_id in mapping_order:
            if by_mapping[mapping_id] and len(selected) < maximum_groups:
                selected.append(by_mapping[mapping_id].popleft())
                added = True
        if not added:
            break
    selected_set = frozenset(selected)
    return [row for row in rows if str(row["query_id"]) in selected_set]


def pair_training_records(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "query": str(row["query"]),
            "document": str(row["document"]),
            "label": float(row["label"]),
        }
        for row in rows
    ]


def listwise_training_records(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row["query_id"])].append(row)
    records: list[dict[str, object]] = []
    for query_id in sorted(groups):
        group = sorted(
            groups[query_id],
            key=lambda row: (-float(row["label"]), str(row["product_id"])),
        )
        if sum(float(row["label"]) == 1.0 for row in group) != 1:
            raise ValueError(f"query group {query_id} must have one positive")
        records.append({
            "query": str(group[0]["query"]),
            "documents": [str(row["document"]) for row in group],
            "labels": [float(row["label"]) for row in group],
        })
    return records


def reranking_samples(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row["query_id"])].append(row)
    samples: list[dict[str, object]] = []
    for query_id in sorted(groups):
        group = groups[query_id]
        positive = [
            str(row["document"]) for row in group if float(row["label"]) == 1.0
        ]
        negative = [
            str(row["document"]) for row in group if float(row["label"]) == 0.0
        ]
        if len(positive) != 1 or not negative:
            raise ValueError(f"query group {query_id} is not rerankable")
        samples.append({
            "query": str(group[0]["query"]),
            "positive": positive,
            "negative": negative,
        })
    return samples


def train(
    *,
    dataset_dir: str | Path,
    output_dir: str | Path,
    loss_name: str,
    model_identifier: str,
    device: str | None,
    epochs: float,
    learning_rate: float,
    batch_size: int,
    eval_batch_size: int,
    max_length: int,
    seed: int,
    maximum_train_groups: int | None,
    maximum_validation_groups: int | None,
) -> Path:
    if loss_name not in {"bce", "lambda"}:
        raise ValueError("loss_name must be 'bce' or 'lambda'")
    if epochs <= 0.0 or learning_rate <= 0.0:
        raise ValueError("epochs and learning_rate must be positive")
    if batch_size < 1 or eval_batch_size < 1 or max_length < 8:
        raise ValueError("batch sizes and max length must be positive")
    source = Path(dataset_dir)
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"training output already exists: {output}")
    manifest_path = source / "manifest.json"
    train_path = source / "train.jsonl"
    validation_path = source / "validation.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if _sha256(train_path) != manifest["train_sha256"]:
        raise ValueError("training rows do not match their manifest hash")
    if _sha256(validation_path) != manifest["validation_sha256"]:
        raise ValueError("validation rows do not match their manifest hash")

    train_rows = select_balanced_groups(
        load_pair_rows(train_path), maximum_train_groups
    )
    validation_rows = select_balanced_groups(
        load_pair_rows(validation_path), maximum_validation_groups
    )
    random.seed(seed)
    try:
        import numpy as np
        import torch
        from datasets import Dataset
        from sentence_transformers.cross_encoder import (
            CrossEncoder,
            CrossEncoderTrainer,
            CrossEncoderTrainingArguments,
        )
        from sentence_transformers.cross_encoder.evaluation import (
            CrossEncoderRerankingEvaluator,
        )
        from sentence_transformers.cross_encoder.losses import (
            BinaryCrossEntropyLoss,
            LambdaLoss,
        )
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError("install semantic-experiment dependencies") from error
    np.random.seed(seed)
    torch.manual_seed(seed)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    started = perf_counter()
    try:
        model = CrossEncoder(
            model_identifier,
            device=device,
            max_length=max_length,
            num_labels=1,
        )
        evaluator = CrossEncoderRerankingEvaluator(
            reranking_samples(validation_rows),
            at_k=4,
            always_rerank_positives=True,
            name="synthetic-validation",
            batch_size=eval_batch_size,
            show_progress_bar=False,
            write_csv=True,
        )
        baseline_dir = temporary / "baseline-evaluation"
        baseline_dir.mkdir()
        baseline_metrics = _json_metrics(evaluator(model, output_path=baseline_dir))

        if loss_name == "bce":
            train_records = pair_training_records(train_rows)
            validation_records = pair_training_records(validation_rows)
            positive_count = sum(item["label"] == 1.0 for item in train_records)
            negative_count = len(train_records) - positive_count
            positive_weight = torch.tensor(
                negative_count / positive_count,
                dtype=torch.float32,
                device=model.device,
            )
            loss = BinaryCrossEntropyLoss(model, pos_weight=positive_weight)
        else:
            train_records = listwise_training_records(train_rows)
            validation_records = listwise_training_records(validation_rows)
            loss = LambdaLoss(model, k=4, mini_batch_size=eval_batch_size)

        training_args = CrossEncoderTrainingArguments(
            output_dir=str(temporary / "trainer"),
            num_train_epochs=epochs,
            learning_rate=learning_rate,
            warmup_steps=0.1,
            weight_decay=0.01,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=eval_batch_size,
            eval_strategy="epoch",
            save_strategy="epoch",
            logging_strategy="steps",
            logging_steps=10,
            logging_first_step=True,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            greater_is_better=False,
            save_total_limit=2,
            optim="adamw_torch",
            seed=seed,
            data_seed=seed,
            report_to="none",
            run_name=f"minilm-l6-{loss_name}",
            dataloader_num_workers=0,
            dataloader_pin_memory=False,
        )
        trainer = CrossEncoderTrainer(
            model=model,
            args=training_args,
            train_dataset=Dataset.from_list(train_records),
            eval_dataset=Dataset.from_list(validation_records),
            loss=loss,
            evaluator=evaluator,
        )
        training_result = trainer.train()
        final_dir = temporary / "final-model"
        model.save_pretrained(str(final_dir))
        final_evaluation_dir = temporary / "final-evaluation"
        final_evaluation_dir.mkdir()
        final_metrics = _json_metrics(
            evaluator(model, output_path=final_evaluation_dir)
        )
        payload = {
            "schema_version": 1,
            "model_identifier": model_identifier,
            "loss": loss_name,
            "device": str(model.device),
            "epochs": epochs,
            "learning_rate": learning_rate,
            "batch_size": batch_size,
            "eval_batch_size": eval_batch_size,
            "max_length": max_length,
            "seed": seed,
            "maximum_train_groups": maximum_train_groups,
            "maximum_validation_groups": maximum_validation_groups,
            "train_group_count": len(reranking_samples(train_rows)),
            "validation_group_count": len(reranking_samples(validation_rows)),
            "dataset_manifest_sha256": _sha256(manifest_path),
            "train_sha256": manifest["train_sha256"],
            "validation_sha256": manifest["validation_sha256"],
            "parameter_count": sum(
                parameter.numel() for parameter in model.model.parameters()
            ),
            "baseline_validation": baseline_metrics,
            "final_validation": final_metrics,
            "training_metrics": _json_metrics(training_result.metrics),
            "log_history": [_json_metrics(item) for item in trainer.state.log_history],
            "elapsed_seconds": round(perf_counter() - started, 6),
        }
        (temporary / "training-result.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def _json_metrics(values: dict) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values.items():
        if isinstance(value, bool) or value is None:
            result[str(key)] = value
        elif isinstance(value, int):
            result[str(key)] = value
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"metric {key!r} is not finite")
            result[str(key)] = round(value, 8)
        elif hasattr(value, "item"):
            item = value.item()
            if not math.isfinite(float(item)):
                raise ValueError(f"metric {key!r} is not finite")
            result[str(key)] = round(float(item), 8)
        else:
            result[str(key)] = str(value)
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fine-tune MiniLM-L6 on audited shopping reranker pairs"
    )
    parser.add_argument(
        "--dataset", default="experiments/reranking/training-data/calibration-v1"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--loss", choices=("bce", "lambda"), required=True)
    parser.add_argument("--model", default=MODEL_IDENTIFIER)
    parser.add_argument("--device")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--eval-batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument("--max-train-groups", type=int)
    parser.add_argument("--max-validation-groups", type=int)
    args = parser.parse_args()
    output = train(
        dataset_dir=args.dataset,
        output_dir=args.output,
        loss_name=args.loss,
        model_identifier=args.model,
        device=args.device,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        eval_batch_size=args.eval_batch_size,
        max_length=args.max_length,
        seed=args.seed,
        maximum_train_groups=args.max_train_groups,
        maximum_validation_groups=args.max_validation_groups,
    )
    print(output)


if __name__ == "__main__":
    main()
