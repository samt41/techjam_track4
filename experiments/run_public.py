from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from time import perf_counter

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from starter.agent import Agent
from starter.shopping_agent.diagnostics import JsonlEvaluationTrace


_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def run_experiment(
    run_id: str,
    catalog_path: str | Path,
    dataset_path: str | Path,
    output_root: str | Path = "experiments",
) -> Path:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must contain only letters, digits, dots, dashes, or underscores")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / run_id
    if destination.exists():
        raise FileExistsError(f"experiment run already exists: {destination}")

    with tempfile.TemporaryDirectory(prefix=f".{run_id}-", dir=root) as temporary:
        working = Path(temporary)
        trace = JsonlEvaluationTrace(working / "retrieval_routes.jsonl")
        samples = load_jsonl(dataset_path)
        catalog_ids, categories, products = catalog_index(catalog_path)
        agent = Agent(catalog_path, trace=trace)
        started = perf_counter()
        try:
            result = evaluate(agent, samples, catalog_ids, categories, products)
        finally:
            agent.close()
        elapsed_seconds = perf_counter() - started

        sessions = tuple(result.pop("sessions"))
        summary = {
            "run_id": run_id,
            "catalog_sha256": _sha256(Path(catalog_path)),
            "dataset_sha256": _sha256(Path(dataset_path)),
            "elapsed_seconds": round(elapsed_seconds, 3),
            **result,
        }
        _write_json(working / "summary.json", summary)
        _write_jsonl(working / "sessions.jsonl", sessions)
        _write_jsonl(
            working / "failures.jsonl",
            tuple(session for session in sessions if not session["hit"]),
        )
        if not (working / "retrieval_routes.jsonl").exists():
            (working / "retrieval_routes.jsonl").write_text("", encoding="utf-8")
        (working / "ablation.md").write_text(
            _ablation_markdown(summary),
            encoding="utf-8",
        )
        working.rename(destination)
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _ablation_markdown(summary: dict[str, object]) -> str:
    return (
        f"# Run {summary['run_id']}\n\n"
        f"- TechnicalScore: `{summary['recommended_technical_score']}`\n"
        f"- HitRate@10: `{summary['hit_rate_at_10']}`\n"
        f"- MRR: `{summary['mrr']}`\n"
        f"- MTTC: `{summary['mttc']}`\n"
        f"- Runtime: `{summary['elapsed_seconds']}` seconds\n\n"
        "This run uses the deterministic core with sparse-pool counterfactual "
        "exploration. Compare it with retained rows in `experiments/RUNS.md`.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a reproducible public evaluation")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output-root", default="experiments")
    args = parser.parse_args()
    run_directory = run_experiment(
        run_id=args.run_id,
        catalog_path=args.catalog,
        dataset_path=args.dataset,
        output_root=args.output_root,
    )
    print(run_directory)


if __name__ == "__main__":
    main()
