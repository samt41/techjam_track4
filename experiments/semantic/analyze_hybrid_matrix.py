from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


METRIC_NAMES = (
    "hit_rate_at_10",
    "mrr",
    "mttc",
    "recommended_technical_score",
)


def build_matrix(records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if not records:
        raise ValueError("at least one matrix record is required")
    baselines = tuple(item for item in records if item["mode"] == "disabled")
    if len(baselines) != 1:
        raise ValueError("matrix requires exactly one disabled baseline")
    baseline = baselines[0]
    _validate_compatible(records, baseline)
    ordered = (baseline, *sorted(
        (item for item in records if item is not baseline),
        key=lambda item: str(item["model_name"]),
    ))
    return {
        "schema_version": 1,
        "baseline_configuration": baseline["configuration_name"],
        "source_hashes": {
            name: baseline[name]
            for name in (
                "catalog_sha256",
                "public_dataset_sha256",
                "gap_dataset_sha256",
                "contrast_sha256",
                "concept_sha256",
                "calibration_sha256",
            )
        },
        "rows": [_matrix_row(item, baseline) for item in ordered],
    }


def _validate_compatible(
    records: tuple[dict[str, Any], ...], baseline: dict[str, Any]
) -> None:
    names = tuple(str(item["configuration_name"]) for item in records)
    if len(set(names)) != len(names):
        raise ValueError("duplicate matrix configuration")
    for record in records:
        for name in (
            "catalog_sha256",
            "public_dataset_sha256",
            "gap_dataset_sha256",
            "contrast_sha256",
            "concept_sha256",
            "calibration_sha256",
        ):
            if record[name] != baseline[name]:
                raise ValueError(f"incompatible matrix input: {name}")


def _matrix_row(record: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "configuration": record["configuration_name"],
        "mode": record["mode"],
        "model": record["model_name"],
        "hybrid_configuration": record["hybrid_configuration"],
        "public": _dataset_row(record["public"], baseline["public"]),
        "semantic_gap": _dataset_row(
            record["semantic_gap"], baseline["semantic_gap"]
        ),
        "contrast": {
            "accepted_count": record["contrast_test"]["accepted_count"],
            "case_count": record["contrast_test"]["case_count"],
            "passed": record["contrast_test"]["passed"],
        },
    }


def _dataset_row(dataset: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    metrics = {name: dataset[name] for name in METRIC_NAMES}
    deltas = {
        name: round(float(dataset[name]) - float(baseline[name]), 6)
        for name in METRIC_NAMES
    }
    return {
        "sample_count": dataset["sample_count"],
        "metrics": metrics,
        "delta": deltas,
        "paired": _paired_outcomes(dataset["sessions"], baseline["sessions"]),
        "semantic": dataset["semantic"],
        "elapsed_seconds": dataset["elapsed_seconds"],
    }


def _paired_outcomes(
    sessions: list[dict[str, Any]], baseline_sessions: list[dict[str, Any]]
) -> dict[str, int]:
    current = {str(item["sample_id"]): item for item in sessions}
    baseline = {str(item["sample_id"]): item for item in baseline_sessions}
    if current.keys() != baseline.keys():
        raise ValueError("paired datasets have different sample ids")
    counts = {
        "gained_hit": 0,
        "lost_hit": 0,
        "improved_reciprocal_rank": 0,
        "worsened_reciprocal_rank": 0,
        "unchanged_reciprocal_rank": 0,
    }
    for sample_id, item in current.items():
        control = baseline[sample_id]
        hit = bool(item["hit"])
        control_hit = bool(control["hit"])
        if hit and not control_hit:
            counts["gained_hit"] += 1
        elif control_hit and not hit:
            counts["lost_hit"] += 1
        reciprocal_rank = float(item["reciprocal_rank"])
        control_rank = float(control["reciprocal_rank"])
        if reciprocal_rank > control_rank:
            counts["improved_reciprocal_rank"] += 1
        elif reciprocal_rank < control_rank:
            counts["worsened_reciprocal_rank"] += 1
        else:
            counts["unchanged_reciprocal_rank"] += 1
    return counts


def render_markdown(matrix: dict[str, Any]) -> str:
    rows = matrix["rows"]
    lines = [
        "# Semantic Hybrid Recommendation Matrix",
        "",
        "This is an end-to-end recommendation evaluation. `disabled` is the unchanged",
        "lexical control. Hybrid rows add gated semantic candidates while retaining",
        "the existing hard-filter and ranking path.",
        "",
        "## Recommendation results",
        "",
        "| Configuration | Public Hit@10 | Public MRR | Public MTTC | "
        "Public score | Δ score | Gap Hit@10 | Gap MRR | Gap MTTC | "
        "Gap score | Δ score | Contrast traps |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        public = row["public"]
        gap = row["semantic_gap"]
        contrast = row["contrast"]
        lines.append(
            "| {configuration} | {public_hit:.4f} | {public_mrr:.4f} | "
            "{public_mttc:.3f} | {public_score:.4f} | {public_delta:+.4f} | "
            "{gap_hit:.4f} | {gap_mrr:.4f} | {gap_mttc:.3f} | "
            "{gap_score:.4f} | {gap_delta:+.4f} | "
            "{accepted}/{cases} accepted |".format(
                configuration=row["configuration"],
                public_hit=public["metrics"]["hit_rate_at_10"],
                public_mrr=public["metrics"]["mrr"],
                public_mttc=public["metrics"]["mttc"],
                public_score=public["metrics"]["recommended_technical_score"],
                public_delta=public["delta"]["recommended_technical_score"],
                gap_hit=gap["metrics"]["hit_rate_at_10"],
                gap_mrr=gap["metrics"]["mrr"],
                gap_mttc=gap["metrics"]["mttc"],
                gap_score=gap["metrics"]["recommended_technical_score"],
                gap_delta=gap["delta"]["recommended_technical_score"],
                accepted=contrast["accepted_count"],
                cases=contrast["case_count"],
            )
        )
    lines.extend([
        "",
        "## Paired session changes",
        "",
        "| Configuration | Public hits +/− | Public ranks ↑/↓ | "
        "Gap hits +/− | Gap ranks ↑/↓ | Public/Gap semantic accepts | "
        "Public/Gap p95 ms | Public/Gap run sec |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        public = row["public"]
        gap = row["semantic_gap"]
        public_paired = public["paired"]
        gap_paired = gap["paired"]
        lines.append(
            "| {configuration} | {pgain}/{ploss} | {pup}/{pdown} | "
            "{ggain}/{gloss} | {gup}/{gdown} | {paccept}/{gaccept} | "
            "{pp95:.1f}/{gp95:.1f} | {pseconds:.1f}/{gseconds:.1f} |".format(
                configuration=row["configuration"],
                pgain=public_paired["gained_hit"],
                ploss=public_paired["lost_hit"],
                pup=public_paired["improved_reciprocal_rank"],
                pdown=public_paired["worsened_reciprocal_rank"],
                ggain=gap_paired["gained_hit"],
                gloss=gap_paired["lost_hit"],
                gup=gap_paired["improved_reciprocal_rank"],
                gdown=gap_paired["worsened_reciprocal_rank"],
                paccept=public["semantic"]["accepted_count"],
                gaccept=gap["semantic"]["accepted_count"],
                pp95=public["semantic"]["latency_ms_p95"],
                gp95=gap["semantic"]["latency_ms_p95"],
                pseconds=public["elapsed_seconds"],
                gseconds=gap["elapsed_seconds"],
            )
        )
    lines.extend([
        "",
        "A gained/lost hit means the target product entered/left the top ten versus",
        "the same control session. Rank arrows count reciprocal-rank improvements",
        "and regressions, including hit changes.",
        "",
    ])
    hybrid_rows = [row for row in rows if row["mode"] == "hybrid"]
    if hybrid_rows:
        best = max(
            hybrid_rows,
            key=lambda row: row["semantic_gap"]["delta"][
                "recommended_technical_score"
            ],
        )
        no_hit_changes = all(
            row[dataset]["paired"][change] == 0
            for row in hybrid_rows
            for dataset in ("public", "semantic_gap")
            for change in ("gained_hit", "lost_hit")
        )
        all_contrast_passed = all(row["contrast"]["passed"] for row in hybrid_rows)
        lines.extend([
            "## Outcome",
            "",
            (
                "No hybrid configuration changed Hit@10 for any paired public or "
                "semantic-gap session."
                if no_hit_changes
                else "At least one hybrid configuration changed paired Hit@10 outcomes."
            ),
            (
                f"The best semantic-gap composite result was `{best['configuration']}` "
                f"at {best['semantic_gap']['delta']['recommended_technical_score']:+.4f} "
                "versus the disabled control."
            ),
            (
                "Every encoder passed the held-out contrast gate."
                if all_contrast_passed
                else "At least one encoder failed the held-out contrast gate."
            ),
            "",
        ])
        if no_hit_changes:
            lines.extend([
                "**Recommendation: do not adopt the current hybrid implementation.** "
                "Arctic-S is the only row worth carrying into another iteration, but "
                "its rank-only lift is too small to justify the extra retrieval work.",
                "",
            ])
    lines.extend([
        "## Limits of this result",
        "",
        "The gap set contains only public sessions eligible for the checked-in test",
        "paraphrases; it is not a general open-vocabulary benchmark. The held-out",
        "contrast set is a small safety gate, not proof of broad negation safety.",
        "Thresholds were frozen from the separate calibration split. Model inference",
        "uses the offline Python experiment stack rather than a production ONNX path.",
        "Concurrent runs can distort wall time, but not deterministic recommendation",
        "order or paired outcome counts.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize semantic hybrid runs")
    parser.add_argument("inputs", nargs="+")
    parser.add_argument(
        "--json-output", default="experiments/semantic/runs/hybrid-matrix.json"
    )
    parser.add_argument(
        "--markdown-output", default="experiments/semantic/HYBRID_MATRIX_REPORT.md"
    )
    args = parser.parse_args()
    records = tuple(
        json.loads(Path(path).read_text(encoding="utf-8")) for path in args.inputs
    )
    matrix = build_matrix(records)
    json_output = Path(args.json_output)
    markdown_output = Path(args.markdown_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_output.write_text(render_markdown(matrix), encoding="utf-8")
    print(json.dumps({
        "json_output": str(json_output),
        "markdown_output": str(markdown_output),
    }))


if __name__ == "__main__":
    main()
