from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# Deliberately importing nothing from the arena package. This is a one-off
# migration whose whole job is to seed the record the rig is later validated
# against; depending on the rig would let a rig bug quietly corrupt its own
# anchor, and the corruption would be invisible because both sides would agree.

# Exactly the per-session record keys the scoring harness emits. Projecting each
# row onto this tuple drops any analysis-added key (first_miss_reason is the one
# that exists today), so a rescued record can never carry a field the harness
# itself did not produce.
SESSION_FIELDS: tuple[str, ...] = (
    "sample_id",
    "scenario_type",
    "hit",
    "first_hit_turn",
    "best_rank",
    "reciprocal_rank",
)

_REQUIRED_AGGREGATE_FIELDS: tuple[str, ...] = (
    "sample_count",
    "hit_rate_at_10",
    "mrr",
    "mttc",
    "efficiency",
    "recommended_technical_score",
    "scenario_metrics",
    "reported_token_usage",
)

_PROVENANCE_FIELDS: tuple[str, ...] = (
    "run_id",
    "provenance",
    "provenance_complete",
    "code_revision",
    "catalog_sha256",
    "dataset_sha256",
    "source_sha256",
)

_SESSIONS_FILENAME = "sessions.jsonl"
_SUMMARY_FILENAME = "summary.json"


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


def _project_sessions(payload: dict[str, object]) -> tuple[dict[str, object], ...]:
    if "sessions" not in payload:
        raise ValueError("results payload is missing the sessions key")
    sessions = payload["sessions"]
    if not isinstance(sessions, list):
        raise ValueError("results payload sessions is not a list")
    if "sample_count" not in payload:
        raise ValueError("results payload is missing the sample_count key")
    sample_count = payload["sample_count"]
    if len(sessions) != sample_count:
        raise ValueError(
            f"session count {len(sessions)} disagrees with sample_count {sample_count}",
        )
    projected: list[dict[str, object]] = []
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            raise ValueError(f"session row {index} is not a json object")
        for field in SESSION_FIELDS:
            if field not in session:
                raise ValueError(f"session row {index} is missing field {field}")
        projected.append({field: session[field] for field in SESSION_FIELDS})
    return tuple(projected)


def _build_summary(
    payload: dict[str, object],
    results_path: Path,
    destination: Path,
    provenance: str,
) -> dict[str, object]:
    for field in _REQUIRED_AGGREGATE_FIELDS:
        if field not in payload:
            raise ValueError(f"results payload is missing the {field} key")
    colliding = sorted(set(payload) & set(_PROVENANCE_FIELDS))
    if colliding:
        raise ValueError(
            f"results payload already carries provenance keys {colliding}",
        )
    summary: dict[str, object] = {
        key: value for key, value in payload.items() if key != "sessions"
    }
    summary["run_id"] = destination.name
    summary["provenance"] = provenance
    # These three are written explicitly rather than omitted. This record is a
    # rescue of a file that carries no provenance at all, and a summary that
    # silently looked complete is exactly the "fingerprint claims a
    # configuration that was not applied" failure mode D-10 exists to prevent.
    summary["provenance_complete"] = False
    summary["code_revision"] = "unknown_revision"
    summary["catalog_sha256"] = "unknown"
    summary["dataset_sha256"] = "unknown"
    # An integrity and reproducibility aid for a single local user, never an
    # authenticity control (T-01-09): anyone who can rewrite the input can
    # rewrite this digest alongside it.
    summary["source_sha256"] = _sha256(results_path)
    return summary


def import_legacy_results(
    results_path: Path,
    destination: Path,
    *,
    provenance: str,
) -> tuple[Path, Path]:
    # json.loads only -- never pickle, eval, or a yaml loader (T-01-07). The
    # input is an untracked, provenance-free file that becomes this phase's
    # validation anchor, so every field is checked before anything is written.
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("results payload is not a json object")
    sessions = _project_sessions(payload)
    summary = _build_summary(payload, results_path, destination, provenance)
    destination.mkdir(parents=True, exist_ok=True)
    sessions_path = destination / _SESSIONS_FILENAME
    summary_path = destination / _SUMMARY_FILENAME
    _write_jsonl(sessions_path, sessions)
    _write_json(summary_path, summary)
    return sessions_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate a legacy harness results.json into a retained baseline record.",
    )
    parser.add_argument("--results", default=Path("results.json"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--provenance", required=True)
    arguments = parser.parse_args()

    sessions_path, summary_path = import_legacy_results(
        arguments.results,
        arguments.output,
        provenance=arguments.provenance,
    )
    print(f"sessions_path={sessions_path}")
    print(f"summary_path={summary_path}")
    print(f"source_sha256={_sha256(arguments.results)}")


if __name__ == "__main__":
    main()
