from __future__ import annotations

import argparse
from pathlib import Path

from arena.adjudication import CandidateArm, adjudicate
from arena.arena import build_candidate_spec, run_candidate
from arena.datasets.registry import (
    CORPUS_ROOT,
    REGISTRY_PATH,
    RegistryError,
    resolve_dataset,
)
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

# Printed verbatim by argparse.RawDescriptionHelpFormatter, which is why this is a
# module constant rather than an inline string. The default formatter re-wraps a
# description through textwrap.fill, and that would be free to break
# `--exploration disabled --lexical-mode auto` across two lines -- turning the one
# thing an operator is meant to copy verbatim into something that cannot be copied.
_RUN_DESCRIPTION = """\
Evaluate one candidate and publish a provenance-carrying record.

--dataset accepts a registry name from data/datasets.json (for example probe.v1) as
well as a filesystem path. A registry name is re-hashed at resolution time and refused
if the file on disk no longer matches its frozen digest (D-43, Pitfall 6); a plain path
is used as given.

L-11, and it decides whether a re-run reproduces a committed record. Reproducing the
override mapping stored by experiments/baselines/run-a requires typing

    --exploration disabled --lexical-mode auto

explicitly. An override flag left unset is OMITTED from the recorded mapping and
therefore from the fingerprint, so a flag-free invocation records {} and mints a
DIFFERENT digest while configuring a byte-identical Agent. The full reasoning is the
comment block at the top of _run() in arena/run_arena.py and is not duplicated here.
"""


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


def _resolve_dataset(value: str) -> Path:
    """Resolve a registry name or a filesystem path, on _existing_file's contract.

    The same "reject an unusable input at the boundary, with a message naming it"
    rationale as _record_directory above, extended by the one thing a bare path
    cannot express: whether the file being measured is still the file whose digest
    was frozen. registry.resolve_dataset re-hashes a registered corpus and raises
    RegistryError on drift, so a corpus that changed under a committed digest fails
    HERE, loudly, rather than producing a measurement that silently describes
    different bytes (Pitfall 6). An unregistered value falls through to a plain path
    check whose message matches _existing_file's shape, so an operator typo reads the
    same whichever door it comes through.

    The two roots are passed explicitly from this module's globals rather than left
    to resolve_dataset's own defaults, which bind at def time. Reading them at call
    time is what lets a test point the whole resolution at a temporary tree, exactly
    as _adjudicate derives its report paths from --output-root instead of taking the
    module constants.
    """
    return resolve_dataset(value, registry_path=REGISTRY_PATH, root=CORPUS_ROOT)


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    # Built by iterating the allow-list rather than by naming each flag inline, so a
    # new candidate knob cannot reach the Agent without appearing in _OVERRIDE_FLAGS.
    # An unset flag is OMITTED, and this filter is now the only rule: every override
    # flag in the run subparser defaults to None, so the recorded mapping describes the
    # INVOCATION rather than the effective configuration.
    #
    # The measured defect this replaces (01-VERIFICATION.md): --exploration defaulted
    # to "disabled" and --lexical-mode to "auto", never None, so argparse injected both
    # and the filter below omitted nothing. The default-everything configuration
    # fingerprinted 25e5f553460050d9 through the CLI, carrying
    # {"exploration": "disabled", "lexical_mode": "auto"}, and af7bdf3a928ec07f
    # programmatically, carrying {}. One configuration, two identities, in the module
    # whose entire job is to give a configuration exactly one.
    #
    # Omitting is safe rather than lossy: starter/agent.py:18-25 supplies exactly the
    # same values as its own constructor defaults (exploration="disabled",
    # lexical_mode=LexicalMode.AUTO, artifact_path=None), so an omitted override builds
    # a byte-identical Agent. Two invocations that differ only in whether the operator
    # typed a default-valued flag are the one case where two digests are the honest
    # answer -- the record says what the operator asked for.
    #
    # The rejected alternative was to canonicalise instead, filling ALLOWED_OVERRIDES
    # with the agent defaults inside candidate_overrides(). That would change a
    # COMMITTED record's derived digest: experiments/baselines/synthetic-promote-10
    # stores overrides {} beside the fingerprint
    # 6eec1db14d0cc75b9d5365410c7d3253b15da54d96bb3839c6870ecc6c0bcec3 derived from it,
    # so filling defaults would break
    # test_every_record_derives_the_fingerprint_it_stores. This argparse change touches
    # no committed record, because every record carries its own overrides mapping in
    # summary.json and is reconstructed from that.
    #
    # This is a SEMANTICS change and not only a bug fix: what an omitted flag means to
    # a fingerprint differs before and after this edit. experiments/baselines/run-a
    # stores {"exploration": "disabled", "lexical_mode": "auto"} because the pre-fix
    # CLI injected those argparse defaults; run-b stores an explicit
    # "exploration": "disabled" and run-c an explicit "lexical_mode": "auto" for the
    # same reason. All three keep deriving exactly the digest they store, and each
    # one's documented invocation typed both flags, so re-running it still mints the
    # committed digest. What a reader must NOT assume is that a future flag-free
    # invocation of the same configuration matches one of those records: it records {}
    # and mints a different digest while configuring a byte-identical Agent.
    # experiments/RUNS.md discloses that; it is not duplicated here.
    overrides = {
        flag: getattr(args, flag)
        for flag in _OVERRIDE_FLAGS
        if getattr(args, flag) is not None
    }

    try:
        catalog_path = _existing_file(args.catalog, "catalog")
        # --catalog deliberately stays on _existing_file: the catalog is the
        # organizer's file and is not registry-managed, so there is no frozen digest
        # for it to have drifted from.
        dataset_path = _resolve_dataset(args.dataset)
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
    # RegistryError is named explicitly and this tuple is NOT widened into a
    # catch-all: a drifted digest is an operator error and must read as one through
    # parser.error, while a broad catch here would swallow a guard failure into the
    # same message and make a bug indistinguishable from a typo (T-02-34). Note that
    # RegistryError subclasses RuntimeError rather than ValueError, so it is not
    # already covered by the entry above it.
    except (
        ValueError,
        FileExistsError,
        OSError,
        ArenaStoreError,
        RegistryError,
    ) as error:
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
        included_directories = tuple(
            _record_directory(value) for value in (args.include or ())
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
        # Report-only entries are loaded the same way but are NEVER built into a
        # CandidateArm, so they reach the candidate, curve and scenario tables without
        # entering adjudicate() -- and therefore without joining the Holm family or
        # changing correction_k. That separation is why the two real rows below are
        # numerically identical whether or not these are present.
        included_entries = tuple(
            entry_from_record(directory) for directory in included_directories
        )
        rows = adjudicate(baseline_arm, candidate_arms)
        payload = build_leaderboard(
            (baseline_entry, *candidate_entries, *included_entries),
            rows,
            baseline_fingerprint=baseline_entry.fingerprint,
        )
        written_json, written_markdown = write_leaderboard(
            payload,
            json_path=json_path,
            markdown_path=markdown_path,
        )
    except (ValueError, OSError, ArenaStoreError, RegistryError) as error:
        parser.error(str(error))
        return
    print(written_json)
    print(written_markdown)


def main(argv: tuple[str, ...] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run and adjudicate arena candidates",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Evaluate one candidate and publish a provenance-carrying record",
        description=_RUN_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--name", required=True)
    run_parser.add_argument("--catalog", default="data/catalog.jsonl")
    run_parser.add_argument(
        "--dataset",
        default="data/public_set.jsonl",
        help=(
            "a registry name from data/datasets.json (for example probe.v1) or a"
            " filesystem path; a registry name is re-hashed at resolution time and"
            " refused if it no longer matches its frozen digest"
        ),
    )
    # D-04, deliberately differing from experiments/run_public.py's `experiments`:
    # arena records live in their own root so the two code paths cannot collide on a
    # run id, and so the committed baseline set is one directory.
    run_parser.add_argument("--output-root", default=str(BASELINES_ROOT))
    run_parser.add_argument(
        "--exploration",
        choices=("disabled", "tail-only"),
        default=None,
    )
    run_parser.add_argument(
        "--lexical-mode",
        choices=("auto", "fts5", "fallback"),
        default=None,
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
    # Retained records that belong in the report but must NOT be tested. Two kinds
    # qualify: a rescued record whose provenance is incomplete (anchor-legacy), and a
    # deterministic validation fixture (synthetic-*). Adjudicating either would inflate
    # the Holm family, weaken the real comparisons, and -- for the fixture -- drive the
    # winner's-curse correction with a control built to win.
    adjudicate_parser.add_argument("--include", action="append", default=None)
    adjudicate_parser.add_argument("--output-root", default=str(BASELINES_ROOT))

    # argv is threaded through rather than left to sys.argv, matching every other CLI
    # in this repository (starter/shopping_agent/build_catalog_artifacts.py,
    # experiments/run_public.py). It is what lets each subcommand be driven from a
    # test without spawning a process, so a CLI path can be asserted at the same cost
    # as a function call. argv=None keeps sys.argv the default for the real entry
    # point below.
    args = parser.parse_args(argv)
    if args.command == "run":
        _run(run_parser, args)
    else:
        _adjudicate(adjudicate_parser, args)


if __name__ == "__main__":
    main()
