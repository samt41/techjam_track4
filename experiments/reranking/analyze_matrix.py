from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


METRICS = (
    "hit_rate_at_10",
    "mrr",
    "mttc",
    "recommended_technical_score",
)


def build_matrix(records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if not records:
        raise ValueError("reranking matrix requires at least one record")
    baseline = next(
        (record for record in records if record["mode"] == "oracle"), None
    )
    if baseline is None:
        raise ValueError("reranking matrix requires an oracle baseline")
    rows = []
    for record in records:
        row = {
            "configuration": record["configuration_name"],
            "mode": record["mode"],
            "model_name": record["model_name"],
            "model_identifier": record["model_identifier"],
            "device": record["device"],
            "candidate_pool_size": record["candidate_pool_size"],
            "fusion_weight": record["fusion_weight"],
            "public": _dataset(record["public"], baseline["public"]),
            "semantic_gap": (
                None
                if record["semantic_gap"] is None
                else _dataset(record["semantic_gap"], baseline["semantic_gap"])
            ),
        }
        rows.append(row)
    return {"schema_version": 1, "rows": rows}


def _dataset(dataset: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": {metric: dataset[metric] for metric in METRICS},
        "delta": {
            metric: round(float(dataset[metric]) - float(baseline[metric]), 6)
            for metric in METRICS
        },
        "paired": paired_outcomes(dataset["sessions"], baseline["sessions"]),
        "reranker": dataset["reranker"],
        "elapsed_seconds": dataset["elapsed_seconds"],
    }


def paired_outcomes(
    sessions: list[dict[str, Any]], baseline_sessions: list[dict[str, Any]]
) -> dict[str, int]:
    current = {str(item["sample_id"]): item for item in sessions}
    baseline = {str(item["sample_id"]): item for item in baseline_sessions}
    if current.keys() != baseline.keys():
        raise ValueError("paired reranking datasets have different sample IDs")
    result = {
        "gained_hit": 0,
        "lost_hit": 0,
        "improved_reciprocal_rank": 0,
        "worsened_reciprocal_rank": 0,
        "unchanged_reciprocal_rank": 0,
    }
    for sample_id, item in current.items():
        control = baseline[sample_id]
        if bool(item["hit"]) and not bool(control["hit"]):
            result["gained_hit"] += 1
        elif bool(control["hit"]) and not bool(item["hit"]):
            result["lost_hit"] += 1
        value = float(item["reciprocal_rank"])
        base_value = float(control["reciprocal_rank"])
        if value > base_value:
            result["improved_reciprocal_rank"] += 1
        elif value < base_value:
            result["worsened_reciprocal_rank"] += 1
        else:
            result["unchanged_reciprocal_rank"] += 1
    return result


def render_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# Cross-Encoder Recommendation Reranking Matrix",
        "",
        "The oracle row records the unchanged deterministic top ten while exposing",
        "larger candidate pools. Model rows RRF-fuse cross-encoder rank with the",
        "existing belief rank after hard eligibility filtering.",
        "",
        "## End-to-end recommendation results",
        "",
        "| Configuration | Device | Public Hit@10 | Public MRR | Public score | Δ score | "
        "Gap Hit@10 | Gap MRR | Gap score | Δ score |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in matrix["rows"]:
        public = row["public"]
        gap = row["semantic_gap"]
        lines.append(
            "| {name} | {device} | {phit:.4f} | {pmrr:.4f} | {pscore:.4f} | "
            "{pdelta:+.4f} | {ghit} | {gmrr} | {gscore} | {gdelta} |".format(
                name=row["configuration"],
                device=row["device"] or "none",
                phit=public["metrics"]["hit_rate_at_10"],
                pmrr=public["metrics"]["mrr"],
                pscore=public["metrics"]["recommended_technical_score"],
                pdelta=public["delta"]["recommended_technical_score"],
                ghit=(
                    "—" if gap is None else f"{gap['metrics']['hit_rate_at_10']:.4f}"
                ),
                gmrr="—" if gap is None else f"{gap['metrics']['mrr']:.4f}",
                gscore=(
                    "—"
                    if gap is None
                    else f"{gap['metrics']['recommended_technical_score']:.4f}"
                ),
                gdelta=(
                    "—"
                    if gap is None
                    else f"{gap['delta']['recommended_technical_score']:+.4f}"
                ),
            )
        )
    lines.extend([
        "",
        "## Paired changes and cost",
        "",
        "| Configuration | Public hits +/− | Public ranks ↑/↓ | Gap hits +/− | "
        "Gap ranks ↑/↓ | Pair count | p50/p95 ms | Public run sec |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in matrix["rows"]:
        public = row["public"]
        gap = row["semantic_gap"]
        paired = public["paired"]
        runtime = public["reranker"]
        lines.append(
            "| {name} | {gain}/{loss} | {up}/{down} | {ggain} | {gup} | "
            "{pairs} | {p50:.1f}/{p95:.1f} | {seconds:.1f} |".format(
                name=row["configuration"],
                gain=paired["gained_hit"],
                loss=paired["lost_hit"],
                up=paired["improved_reciprocal_rank"],
                down=paired["worsened_reciprocal_rank"],
                ggain=(
                    "—"
                    if gap is None
                    else f"{gap['paired']['gained_hit']}/{gap['paired']['lost_hit']}"
                ),
                gup=(
                    "—"
                    if gap is None
                    else f"{gap['paired']['improved_reciprocal_rank']}/"
                    f"{gap['paired']['worsened_reciprocal_rank']}"
                ),
                pairs=runtime["scored_pairs"],
                p50=runtime["latency_ms_p50"],
                p95=runtime["latency_ms_p95"],
                seconds=public["elapsed_seconds"],
            )
        )
    oracle = next(row for row in matrix["rows"] if row["mode"] == "oracle")
    coverage = oracle["public"]["reranker"]["session_candidate_coverage"]
    lines.extend([
        "",
        "## Candidate-pool oracle",
        "",
        "This is the fraction of public sessions whose target appeared in the",
        "deterministic eligible pool on at least one scoreable turn:",
        "",
        "| Cutoff | 10 | 25 | 50 | 100 | 200 |",
        "|---|---:|---:|---:|---:|---:|",
        "| Coverage | " + " | ".join(
            f"{coverage[str(cutoff)]:.4f}" for cutoff in (10, 25, 50, 100, 200)
        ) + " |",
        "",
        "The oracle is an upper bound only: a reranker cannot recover a target that",
        "the first-stage candidate pool does not contain.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze reranking configurations")
    parser.add_argument("inputs", nargs="+")
    parser.add_argument(
        "--json-output", default="experiments/reranking/runs/matrix.json"
    )
    parser.add_argument(
        "--markdown-output", default="experiments/reranking/MATRIX_REPORT.md"
    )
    args = parser.parse_args()
    records = tuple(
        json.loads(Path(path).read_text(encoding="utf-8")) for path in args.inputs
    )
    matrix = build_matrix(records)
    json_path = Path(args.json_output)
    markdown_path = Path(args.markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(matrix) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}))


if __name__ == "__main__":
    main()
