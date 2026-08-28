from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from time import perf_counter

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from experiments.analyze_public import (
    FailureAnalysis,
    MissReason,
    TargetProfile,
    analyze_session,
    code_revision,
)
from starter.agent import Agent
from starter.shopping_agent.belief import DEFAULT_BELIEF_CONFIGURATION
from starter.shopping_agent.clarification import QuestionModelConfiguration
from starter.shopping_agent.diagnostics import JsonlEvaluationTrace
from starter.shopping_agent.search_backend import LexicalMode


_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


class _SessionMappingAgent:
    """Wraps Agent to record reset-call order without touching the evaluator.

    The evaluator generates a random session UUID per sample in sample order,
    so recording each reset maps that UUID back to the public sample id. This
    join happens only after evaluate() returns; ground truth never enters the
    Agent.
    """

    def __init__(self, agent: Agent, sample_ids: tuple[str, ...]) -> None:
        self._agent = agent
        self._sample_ids = sample_ids
        self._reset_count = 0
        self.session_to_sample: dict[str, str] = {}

    def reset(self, session_id: str, user_profile: dict) -> None:
        if self._reset_count < len(self._sample_ids):
            self.session_to_sample[session_id] = self._sample_ids[self._reset_count]
        self._reset_count += 1
        self._agent.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        return self._agent.respond(session_id, user_message, turn, top_k)

    def close(self) -> None:
        self._agent.close()


def run_experiment(
    run_id: str,
    catalog_path: str | Path,
    dataset_path: str | Path,
    output_root: str | Path = "experiments",
    exploration: str = "tail-only",
    lexical_mode: str = "auto",
) -> Path:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError(
            "run_id must contain only letters, digits, dots, dashes, or underscores"
        )
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / run_id
    if destination.exists():
        raise FileExistsError(f"experiment run already exists: {destination}")

    with tempfile.TemporaryDirectory(prefix=f".{run_id}-", dir=root) as temporary:
        working = Path(temporary)
        trace_path = working / "retrieval_routes.jsonl"
        trace = JsonlEvaluationTrace(trace_path)
        samples = load_jsonl(dataset_path)
        catalog_ids, categories, products = catalog_index(catalog_path)
        base_agent = Agent(
            catalog_path,
            trace=trace,
            exploration=exploration,
            lexical_mode=LexicalMode(lexical_mode),
        )
        agent = _SessionMappingAgent(
            base_agent,
            tuple(str(sample["sample_id"]) for sample in samples),
        )
        started = perf_counter()
        try:
            result = evaluate(agent, samples, catalog_ids, categories, products)
        finally:
            agent.close()
        elapsed_seconds = perf_counter() - started

        sessions = tuple(result.pop("sessions"))
        events = _load_events(trace_path)
        target_profiles = _target_profiles(samples, products)
        failures = _failure_rows(sessions, events, target_profiles, agent)
        annotated_sessions = _annotate_sessions(sessions, failures)

        revision = code_revision()
        summary = {
            "run_id": run_id,
            "code_revision": revision,
            "exploration": exploration,
            "lexical_mode": lexical_mode,
            "catalog_sha256": _sha256(Path(catalog_path)),
            "dataset_sha256": _sha256(Path(dataset_path)),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "belief_configuration": DEFAULT_BELIEF_CONFIGURATION.as_dict(),
            "question_configuration": QuestionModelConfiguration.default().as_dict(),
            **result,
        }
        _write_json(working / "summary.json", summary)
        _write_jsonl(working / "sessions.jsonl", annotated_sessions)
        _write_jsonl(
            working / "failures.jsonl",
            tuple(failure.as_record() for failure in failures),
        )
        if not trace_path.exists():
            trace_path.write_text("", encoding="utf-8")
        (working / "ablation.md").write_text(
            _ablation_markdown(summary, failures),
            encoding="utf-8",
        )
        working.rename(destination)
    return destination


def _load_events(trace_path: Path) -> tuple[dict, ...]:
    if not trace_path.exists():
        return ()
    return tuple(
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _target_profiles(
    samples: list[dict],
    products: dict[str, dict],
) -> dict[str, TargetProfile]:
    profiles: dict[str, TargetProfile] = {}
    for sample in samples:
        sample_id = str(sample["sample_id"])
        target = str(sample["ground_truth"]["parent_asin"])
        product = products.get(target)
        if product is None:
            profiles[sample_id] = TargetProfile(
                parent_asin=target,
                attributes={},
                price=None,
                searchable_text="",
            )
            continue
        profiles[sample_id] = TargetProfile(
            parent_asin=target,
            attributes=_target_attributes(product),
            price=_target_price(product),
            searchable_text=_target_text(product),
        )
    return profiles


def _target_attributes(product: dict) -> dict[str, str]:
    attributes: dict[str, str] = {}
    details = product.get("details")
    if isinstance(details, dict):
        for key, value in details.items():
            if value not in (None, ""):
                attributes[str(key)] = str(value)
    return attributes


def _target_price(product: dict) -> float | None:
    price = product.get("price")
    if price in (None, ""):
        return None
    try:
        return float(price)
    except (TypeError, ValueError):
        return None


def _target_text(product: dict) -> str:
    parts: list[str] = []
    for field in ("title", "features", "description", "categories", "store"):
        value = product.get(field)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value not in (None, ""):
            parts.append(str(value))
    return " ".join(parts).strip()


def _failure_rows(
    sessions: tuple[dict, ...],
    events: tuple[dict, ...],
    target_profiles: dict[str, TargetProfile],
    agent: _SessionMappingAgent,
) -> tuple[FailureAnalysis, ...]:
    events_by_sample: dict[str, list[dict]] = {}
    for event in events:
        sample_id = agent.session_to_sample.get(str(event.get("session_id")))
        if sample_id is None:
            continue
        events_by_sample.setdefault(sample_id, []).append(event)

    failures: list[FailureAnalysis] = []
    for session in sessions:
        if session.get("hit"):
            continue
        sample_id = str(session["sample_id"])
        target = target_profiles.get(sample_id)
        if target is None:
            failures.append(FailureAnalysis(
                sample_id=sample_id,
                scenario_type=str(session.get("scenario_type", "")),
                primary_reason=MissReason.INSUFFICIENT_TARGET_METADATA,
                constraint_id=None,
                detail="no ground-truth target available",
            ))
            continue
        failure = analyze_session(
            target=target,
            trace=tuple(events_by_sample.get(sample_id, ())),
            outcome=session,
        )
        if failure is not None:
            failures.append(failure)
    return tuple(failures)


def _annotate_sessions(
    sessions: tuple[dict, ...],
    failures: tuple[FailureAnalysis, ...],
) -> tuple[dict, ...]:
    reason_by_sample = {
        failure.sample_id: failure.primary_reason.value
        for failure in failures
    }
    return tuple(
        {
            **session,
            "first_miss_reason": reason_by_sample.get(str(session["sample_id"])),
        }
        for session in sessions
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _ablation_markdown(
    summary: dict[str, object],
    failures: tuple[FailureAnalysis, ...],
) -> str:
    reason_counts: dict[str, int] = {}
    for failure in failures:
        key = failure.primary_reason.value
        reason_counts[key] = reason_counts.get(key, 0) + 1
    reason_lines = "\n".join(
        f"| `{reason}` | {count} |"
        for reason, count in sorted(reason_counts.items())
    ) or "| _none_ | 0 |"
    return (
        f"# Run {summary['run_id']}\n\n"
        f"- Configuration: exploration=`{summary['exploration']}`, "
        f"lexical_mode=`{summary['lexical_mode']}`, "
        f"revision=`{summary['code_revision']}`\n"
        f"- TechnicalScore: `{summary['recommended_technical_score']}`\n"
        f"- HitRate@10: `{summary['hit_rate_at_10']}`\n"
        f"- MRR: `{summary['mrr']}`\n"
        f"- MTTC: `{summary['mttc']}`\n"
        f"- Runtime: `{summary['elapsed_seconds']}` seconds\n\n"
        "## Miss attribution\n\n"
        "| Reason | Count |\n"
        "| --- | --- |\n"
        f"{reason_lines}\n\n"
        "Compare this run with retained rows in `experiments/RUNS.md`.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a reproducible public evaluation")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output-root", default="experiments")
    parser.add_argument(
        "--exploration",
        choices=("disabled", "tail-only"),
        default="tail-only",
    )
    parser.add_argument(
        "--lexical-mode",
        choices=("auto", "fts5", "fallback"),
        default="auto",
    )
    args = parser.parse_args()
    run_directory = run_experiment(
        run_id=args.run_id,
        catalog_path=args.catalog,
        dataset_path=args.dataset,
        output_root=args.output_root,
        exploration=args.exploration,
        lexical_mode=args.lexical_mode,
    )
    print(run_directory)


if __name__ == "__main__":
    main()
