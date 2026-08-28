"""B1 miss-classification: split retained-run misses into semantic vs precision.

Offline analysis over a retained experiment run's typed traces plus the
deterministic evaluator and the catalog artifact. No agent, no re-run, no
network. Answers the linchpin question that gates all embedding work: do any
public-set misses stem from a genuine user->catalog vocabulary gap, or are they
all extraction precision / slate-rotation artifacts?

Result on the retained 0.76 run (HEAD 1b8d88d): vocab-gap 0/48,
genuine-target-lacks 0/48. The evaluator quotes the target product's own catalog
strings verbatim, so an embedding synonym bridge recovers nothing here. The
dominant lever is intent_override slate-rotation (target shown pre-override then
rotated out), not NLP. See the design spec's "B1 RESULT" section.

Usage:
    python -m experiments.analyze_misses_b1 --run experiments/scalable-strict
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from evaluator.local_evaluator import searchable_text

_JUNK_OTHER = "those options are not quite right yet"
_MATERIAL_WORDS = frozenset({
    "cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk",
    "rayon", "fabric", "textile", "faux fur",
})
# Injected dict-key prefixes from the evaluator's _flatten_values ("key: value")
# and generic filler tokens that carry no concept.
_PREFIX_NOISE = frozenset({"material", "color", "high", "quality", "and"})
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _parse_constraint(constraint_id: str) -> dict | None:
    # t{turn}:{attribute}:{operator}:{value}:{polarity}:{ordinal}; value may
    # itself contain colons, so bind the fixed head/tail and rejoin the middle.
    parts = constraint_id.split(":")
    if len(parts) < 6:
        return None
    return {
        "turn": parts[0],
        "attribute": parts[1],
        "operator": parts[2],
        "value": ":".join(parts[3:-2]).replace("-", " "),
        "polarity": parts[-2],
    }


def _override_turn(sample_id: str, scenario_type: str) -> int:
    # Mirrors evaluator.behavior_for: override turn is the first rng draw, seeded
    # only by sample id + scenario, independent of the product.
    rng = random.Random(f"{sample_id}\0{scenario_type}")
    return rng.choice([3, 4])


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _session_to_sample(trace: list[dict], sample_ids: list[str]) -> dict[str, str]:
    # The evaluator resets sessions in dataset order, so first-appearance order of
    # session ids in the trace maps back to sample order.
    order: list[str] = []
    seen: set[str] = set()
    for event in trace:
        session_id = event.get("session_id")
        if session_id and session_id not in seen:
            seen.add(session_id)
            order.append(session_id)
    return {order[i]: sample_ids[i] for i in range(min(len(order), len(sample_ids)))}


def _target_texts(catalog_path: Path, wanted: set[str]) -> dict[str, str]:
    texts: dict[str, str] = {}
    with catalog_path.open(encoding="utf-8") as handle:
        for line in handle:
            product = json.loads(line)
            parent_asin = str(product["parent_asin"])
            if parent_asin in wanted:
                texts[parent_asin] = searchable_text(product).lower()
                if len(texts) == len(wanted):
                    break
    return texts


def analyze(run_dir: Path, catalog_path: Path, dataset_path: Path, database_path: Path) -> dict:
    samples = _load_jsonl(dataset_path)
    sample_ids = [str(sample["sample_id"]) for sample in samples]
    sid_to_target = {str(s["sample_id"]): str(s["ground_truth"]["parent_asin"]) for s in samples}
    sid_to_scenario = {str(s["sample_id"]): str(s["scenario_type"]) for s in samples}

    misses = _load_jsonl(run_dir / "failures.jsonl")
    trace = _load_jsonl(run_dir / "retrieval_routes.jsonl")
    session_to_sample = _session_to_sample(trace, sample_ids)

    interp: dict[str, list[dict]] = defaultdict(list)
    slate: dict[str, list[dict]] = defaultdict(list)
    for event in trace:
        sample_id = session_to_sample.get(event.get("session_id"))
        if not sample_id:
            continue
        if event.get("event_type") == "interpretation":
            interp[sample_id].append(event)
        elif event.get("event_type") == "slate":
            slate[sample_id].append(event)

    target_text = _target_texts(catalog_path, {sid_to_target[m["sample_id"]] for m in misses})
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)

    def attribute_df(attribute: str, value: str) -> int:
        row = connection.execute(
            "SELECT COUNT(*) FROM attributes WHERE attribute = ? AND value = ?",
            (attribute, value),
        ).fetchone()
        return row[0] if row else 0

    classes: Counter[str] = Counter()
    vocab_gap_cases: list[dict] = []
    rotation_cases: list[str] = []
    per_miss: list[dict] = []

    for miss in misses:
        sample_id = miss["sample_id"]
        scenario = miss["scenario_type"]
        target = sid_to_target[sample_id]
        text_tokens = _tokens(target_text.get(target, ""))

        events = interp.get(sample_id, [])
        final_ids = events[-1]["active_constraint_ids"] if events else []
        constraints = [c for c in (_parse_constraint(cid) for cid in final_ids) if c]

        carries_junk_other = False
        material_as_category = False
        overlong_feature = False
        target_lacks: list[tuple[str, str, int]] = []
        for constraint in constraints:
            attribute = constraint["attribute"]
            value = constraint["value"]
            if attribute == "budget":
                continue
            if attribute == "other" and value == _JUNK_OTHER:
                carries_junk_other = True
                continue
            if attribute == "category" and value in _MATERIAL_WORDS:
                material_as_category = True
                continue
            if len(value) > 40:
                overlong_feature = True
                continue
            content = [w for w in _tokens(value) if w not in _PREFIX_NOISE]
            absent = [w for w in content if w not in text_tokens]
            if content and absent:
                # A real concept the target's own text lacks would be a genuine
                # target-lacks (or, if the word is a known synonym, a vocab-gap).
                target_lacks.append((attribute, value, attribute_df(attribute, value)))

        if carries_junk_other:
            classes["junk_other_filler"] += 1
        if material_as_category:
            classes["material_as_category"] += 1
        if overlong_feature:
            classes["overlong_feature"] += 1
        if target_lacks:
            classes["target_lacks_or_vocab_gap"] += 1
            vocab_gap_cases.append({"sample_id": sample_id, "lacks": target_lacks})

        rotated_out = False
        if scenario == "intent_override":
            override = _override_turn(sample_id, scenario)
            shown_turns = [
                event["turn"]
                for event in slate.get(sample_id, [])
                if target in event["strict_product_ids"] or target in event["exploratory_product_ids"]
            ]
            counted = [turn for turn in shown_turns if turn >= override]
            if shown_turns and not counted:
                rotated_out = True
                rotation_cases.append(sample_id)
                classes["intent_override_rotated_out"] += 1

        per_miss.append({
            "sample_id": sample_id,
            "scenario_type": scenario,
            "primary_reason": miss["primary_reason"],
            "carries_junk_other": carries_junk_other,
            "material_as_category": material_as_category,
            "overlong_feature": overlong_feature,
            "target_lacks": target_lacks,
            "intent_override_rotated_out": rotated_out,
        })

    connection.close()
    return {
        "run": run_dir.name,
        "miss_count": len(misses),
        "class_counts": dict(sorted(classes.items())),
        "vocab_gap_or_target_lacks": vocab_gap_cases,
        "intent_override_rotated_out": rotation_cases,
        "per_miss": per_miss,
    }


def _format(report: dict) -> str:
    lines = [
        f"# B1 miss-classification — run `{report['run']}` ({report['miss_count']} misses)",
        "",
        "| Cause class | Count |",
        "| --- | ---: |",
    ]
    lines.extend(f"| `{name}` | {count} |" for name, count in report["class_counts"].items())
    lines.append("")
    lacks = report["vocab_gap_or_target_lacks"]
    lines.append(f"Genuine target-lacks / vocab-gap candidates: **{len(lacks)}**")
    for case in lacks:
        lines.append(f"  - {case['sample_id']}: {case['lacks']}")
    lines.append(
        f"intent_override targets shown pre-override then rotated out: "
        f"**{len(report['intent_override_rotated_out'])}**"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="B1 miss-classification over a retained run")
    parser.add_argument("--run", default="experiments/scalable-strict")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--database", default="data/catalog.artifacts/catalog.sqlite3")
    parser.add_argument("--json", action="store_true", help="emit the full JSON report")
    args = parser.parse_args()

    report = analyze(
        run_dir=Path(args.run),
        catalog_path=Path(args.catalog),
        dataset_path=Path(args.dataset),
        database_path=Path(args.database),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_format(report))


if __name__ == "__main__":
    main()
