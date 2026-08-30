from __future__ import annotations

import argparse
from pathlib import Path

from arena.adjudication import CandidateArm, adjudicate
from arena.arena import build_candidate_spec, run_candidate
from arena.leaderboard import (
    LEADERBOARD_JSON_PATH,
    LEADERBOARD_MARKDOWN_PATH,
    build_leaderboard,
    entry_from_record,
    spec_from_record,
    write_leaderboard,
)
from arena.store import (
    BASELINES_ROOT,
    SESSIONS_FILENAME,
    SUMMARY_FILENAME,
    ArenaStoreError,
)


# Exactly the three keys arena.candidate.ALLOWED_OVERRIDES admits. Named here so a
# fourth flag cannot quietly become a candidate knob: a knob the Agent constructor
# does not accept would mint a fingerprint describing a configuration that was
# silently ignored, which invalidates every comparison built on it.
_OVERRIDE_FLAGS = ("exploration", "lexical_mode", "artifact_path")


def _record_directory(value: str) -> Path:
    """Reject an unusable record at the boundary, with a message naming the path.

    Without this the first failure surfaces as a FileNotFoundError from inside
    json.loads or load_sessions, several frames below the CLI, which reads as a
    crash rather than as the operator error it is.
    """
    directory = Path(value)
    if not directory.is_dir():
        raise ValueError(f"run directory does not exist: {directory}")
    for filename in (SUMMARY_FILENAME, SESSIONS_FILENAME):
        if not (directory / filename).is_file():
            raise ValueError(f"run directory is missing {filename}: {directory}")
    return directory


def _existing_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    # Built by iterating the allow-list rather than by naming each flag inline, so a
    # new candidate knob cannot reach the Agent without appearing in _OVERRIDE_FLAGS.
    # An unset flag is OMITTED rather than recorded as None: it must leave the
    # fingerprint identical to a run that never mentioned it, otherwise one
    # configuration fingerprints two ways.
    overrides = {
        flag: getattr(args, flag)
        for flag in _OVERRIDE_FLAGS
        if getattr(args, flag) is not None
    }

    try:
        catalog_path = _existing_file(args.catalog, "catalog")
        dataset_path = _existing_file(args.dataset, "dataset")
        spec = build_candidate_spec(
            args.name,
            catalog_path=catalog_path,
            dataset_path=dataset_path,
            overrides=overrides,
        )
        destination = run_candidate(
            spec,
            run_id=args.run_id,
            catalog_path=catalog_path,
            dataset_path=dataset_path,
            output_root=Path(args.output_root),
        )
    except (ValueError, FileExistsError, OSError, ArenaStoreError) as error:
        parser.error(str(error))
        return
    print(destination)


def _adjudicate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    output_root = Path(args.output_root)
    # Derived from the output root rather than taken from the module constants, so a
    # test or a dry run can point the whole report at a temporary tree instead of
    # rewriting the committed artifacts. At the default root this reproduces those
    # constants exactly.
    json_path = output_root / LEADERBOARD_JSON_PATH.name
    markdown_path = output_root.parent / LEADERBOARD_MARKDOWN_PATH.name

    try:
        baseline_directory = _record_directory(args.baseline)
        candidate_directories = tuple(
            _record_directory(value) for value in args.candidate
        )
        baseline_entry = entry_from_record(baseline_directory)
        baseline_arm = CandidateArm(
            spec=spec_from_record(baseline_directory),
            sessions=baseline_entry.sessions,
        )
        candidate_entries = tuple(
            entry_from_record(directory) for directory in candidate_directories
        )
        candidate_arms = tuple(
            CandidateArm(
                spec=spec_from_record(directory),
                sessions=entry.sessions,
            )
            for directory, entry in zip(candidate_directories, candidate_entries)
        )
        rows = adjudicate(baseline_arm, candidate_arms)
        payload = build_leaderboard(
            (baseline_entry, *candidate_entries),
            rows,
            baseline_fingerprint=baseline_entry.fingerprint,
        )
        written_json, written_markdown = write_leaderboard(
            payload,
            json_path=json_path,
            markdown_path=markdown_path,
        )
    except (ValueError, OSError, ArenaStoreError) as error:
        parser.error(str(error))
        return
    print(written_json)
    print(written_markdown)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run and adjudicate arena candidates",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Evaluate one candidate and publish a provenance-carrying record",
    )
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--name", required=True)
    run_parser.add_argument("--catalog", default="data/catalog.jsonl")
    run_parser.add_argument("--dataset", default="data/public_set.jsonl")
    # D-04, deliberately differing from experiments/run_public.py's `experiments`:
    # arena records live in their own root so the two code paths cannot collide on a
    # run id, and so the committed baseline set is one directory.
    run_parser.add_argument("--output-root", default=str(BASELINES_ROOT))
    run_parser.add_argument(
        "--exploration",
        choices=("disabled", "tail-only"),
        default="disabled",
    )
    run_parser.add_argument(
        "--lexical-mode",
        choices=("auto", "fts5", "fallback"),
        default="auto",
    )
    run_parser.add_argument("--artifact-path", default=None)

    # No flag exposes the resample count. It is a fixed module constant (D-24)
    # precisely so that no invocation can make the rig cheap enough to be wrong, and
    # a committed report generated at a reduced count would be indistinguishable from
    # an honest one (T-01-20).
    adjudicate_parser = subparsers.add_parser(
        "adjudicate",
        help="Compare retained records and regenerate the leaderboard",
    )
    adjudicate_parser.add_argument("--baseline", required=True)
    adjudicate_parser.add_argument("--candidate", action="append", required=True)
    adjudicate_parser.add_argument("--output-root", default=str(BASELINES_ROOT))

    args = parser.parse_args()
    if args.command == "run":
        _run(run_parser, args)
    else:
        _adjudicate(adjudicate_parser, args)


if __name__ == "__main__":
    main()
