from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from arena.adjudication import CandidateArm, adjudicate
from arena.arena import build_candidate_spec, run_candidate
from arena.datasets.registry import (
    CORPUS_ROOT,
    PUBLIC_DATASET_NAME,
    REGISTRY_PATH,
    RegistryError,
    resolve_dataset,
    validate_dataset_name,
)
from arena.datasets.schema import load_corpus
from arena.leaderboard import (
    CORPUS_BASELINES_JSON_PATH,
    CORPUS_BASELINES_MARKDOWN_PATH,
    LEADERBOARD_JSON_PATH,
    LEADERBOARD_MARKDOWN_PATH,
    build_corpus_baselines,
    build_leaderboard,
    entry_from_record,
    spec_from_record,
    write_corpus_baselines,
    write_leaderboard,
)
from arena.paired_contrast import (
    CONTRAST_JSON_PATH,
    CONTRAST_MARKDOWN_PATH,
    PairedContrastError,
    arm_from_run,
    paired_contrast,
    write_paired_contrast,
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

# One subcommand handler: it takes ITS OWN subparser so parser.error() reports the
# subcommand the operator typed rather than the top-level program.
_Handler = Callable[[argparse.ArgumentParser, argparse.Namespace], None]

# The two --pair-subset choices. Named so the flag declaration and the branch that
# reads it cannot drift apart on a string literal.
_STRICT_SUBSET = "strict"
_SHARED_SUBSET = "shared"

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

_CONTRAST_DESCRIPTION = """\
The D-44 paired control-vs-probe readout: a paired bootstrap interval, the measured
minimum detectable difference, and an exact McNemar test. It never routes through
adjudicate, and it applies neither a Holm family nor a winner's-curse correction: one
candidate partitioned into arms is a different statistical object from candidates
selected out of a pool of k, so there is no family to correct and no maximum of k to
debias.

The DEFAULT shape is ONE --record and ONE --corpus, and a reader coming from
02-RESEARCH.md:754 will expect two of each. That note is stale. D-46 puts pair_id and
arm inside the sample rows and D-25 sizes the probe as a single 700-session corpus, so
`run_arena run --dataset probe.v1` publishes ONE record carrying all three arms and this
subcommand partitions it with paired_contrast.arm_from_run.

No flag exposes the resample count, for the same reason adjudicate exposes none: a
committed report generated at a reduced count would be indistinguishable from an honest
one.
"""

_CORPUS_BASELINES_DESCRIPTION = """\
Render the D-53 per-corpus baseline table: ONE candidate measured across the four
Phase 2 corpora -- public, expanded_dev.v1, expanded_confirm.v1 and probe.v1. D-45 and
D-48 both say "five"; that wording predates D-46 folding the probe's three arms into a
single file, and D-58 corrects the count to four.

Why this is its own subcommand and NOT --include on adjudicate. These rows differ from
one another in the CORPUS rather than in the configuration, and adjudicate refuses two
arms whose dataset_sha256 disagree, by design (D-45). --include would route around that
refusal and land them in the leaderboard's candidate table regardless, and a leaderboard
whose entire premise is a same-corpus comparison is precisely where four
different-corpus rows get misread as a ranking. They therefore get their own JSON and
their own Markdown and never reach experiments/LEADERBOARD.md.

--record binds a dataset name to a run-record directory as NAME=DIRECTORY and is
repeatable. NAME must be a registry name such as probe.v1, or the literal public.
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


def _contrast(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    output_root = Path(args.output_root)
    # Derived from the output root exactly as _adjudicate derives the leaderboard
    # paths, so a dry run can point the whole report at a temporary tree rather than
    # rewriting the committed artifacts. At the default root this reproduces the two
    # module constants exactly.
    json_path = output_root / CONTRAST_JSON_PATH.name
    markdown_path = output_root.parent / CONTRAST_MARKDOWN_PATH.name

    if (args.probe_record or args.probe_corpus) and not args.allow_cross_corpus:
        # Refused before a single record is opened, so the message names the INTENT
        # rather than whichever join happened to fail first.
        #
        # This is the weaker of two defences, and saying so here is the point. Plan
        # 02-03 namespaces every pair_id as {corpus_stem}_{index:04d} and
        # validate_corpus refuses a foreign stem at LOAD, so two corpora share no
        # pair id at all and align_on_pair_id raises on every one of them whether or
        # not this flag was passed. The flag exists to make a deliberate
        # cross-corpus join legible at the CLI, not to be the thing that closes the
        # hole.
        parser.error(
            "--probe-record and --probe-corpus build a CROSS-CORPUS contrast, which"
            " joins two corpora on pair_id -- the silently bogus comparison D-45"
            " exists to prevent. Pass --allow-cross-corpus alongside them only if"
            " you intend exactly that."
        )
        return

    try:
        control_directory = _record_directory(args.record)
        control_corpus = _resolve_dataset(args.corpus)
        probe_directory = (
            _record_directory(args.probe_record)
            if args.probe_record
            else control_directory
        )
        probe_corpus = (
            _resolve_dataset(args.probe_corpus)
            if args.probe_corpus
            else control_corpus
        )
        control_entry = entry_from_record(control_directory)
        probe_entry = (
            control_entry
            if probe_directory == control_directory
            else entry_from_record(probe_directory)
        )
        control_rows = load_corpus(control_corpus)
        probe_rows = (
            control_rows
            if probe_corpus == control_corpus
            else load_corpus(probe_corpus)
        )
        # spec_from_record and never entry_from_record for the two digests (L-10):
        # CandidateEntry keeps the fingerprint but carries neither catalog_sha256 nor
        # dataset_sha256, so an arm built from an entry alone cannot supply what
        # require_comparable_arms checks and cannot reconstruct a matching spec
        # either.
        #
        # The sample_id -> pair_id -> arm mapping comes out of the resolved corpus
        # JSONL and is joined here, AFTER evaluate() has already returned. Ground
        # truth never reaches the Agent; this is a post-hoc reporting join.
        control_arm = arm_from_run(
            f"{control_entry.name}:{args.control_arm}",
            arm=args.control_arm,
            spec=spec_from_record(control_directory),
            corpus_path=control_corpus,
            corpus_rows=control_rows,
            sessions=control_entry.sessions,
        )
        probe_arm = arm_from_run(
            f"{probe_entry.name}:{args.probe_arm}",
            arm=args.probe_arm,
            spec=spec_from_record(probe_directory),
            corpus_path=probe_corpus,
            corpus_rows=probe_rows,
            sessions=probe_entry.sessions,
        )
        result = paired_contrast(
            control_arm,
            probe_arm,
            restrict_to_shared=(args.pair_subset == _SHARED_SUBSET),
            allow_cross_corpus=args.allow_cross_corpus,
        )
        written_json, written_markdown = write_paired_contrast(
            result.as_record(),
            json_path=json_path,
            markdown_path=markdown_path,
        )
    except (
        ValueError,
        OSError,
        ArenaStoreError,
        RegistryError,
        PairedContrastError,
    ) as error:
        parser.error(str(error))
        return
    # Both counts on stdout, not only inside the committed report. An operator who
    # typed --pair-subset shared has to see the drop NOW rather than discover it in a
    # file they have already cited: "100 pairs" and "100 of 300 pairs" support
    # different claims (MEAS-06).
    print(f"pairs={result.pair_count} dropped={result.dropped_pair_count}")
    print(written_json)
    print(written_markdown)


def _corpus_baselines(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    output_root = Path(args.output_root)
    json_path = output_root / CORPUS_BASELINES_JSON_PATH.name
    markdown_path = output_root.parent / CORPUS_BASELINES_MARKDOWN_PATH.name

    try:
        rows: list[tuple[str, object]] = []
        for value in args.record:
            # partition, not split("="): a Windows path can legitimately contain no
            # "=" but the NAME never can, so binding on the FIRST separator keeps a
            # directory name with an "=" in it from silently truncating the path.
            name, separator, directory = value.partition("=")
            if not separator or not name or not directory:
                raise ValueError(
                    "--record must be NAME=DIRECTORY, binding a dataset name to a"
                    f" run-record directory; got {value!r}"
                )
            if name != PUBLIC_DATASET_NAME:
                # The organizer set is the one name with no version suffix: it
                # predates D-43 entirely, so it is admitted by literal rather than by
                # widening the allow-list that makes a name safe as a filename
                # (T-02-03).
                validate_dataset_name(name)
            rows.append((name, entry_from_record(_record_directory(directory))))
        payload = build_corpus_baselines(tuple(rows))  # type: ignore[arg-type]
        written_json, written_markdown = write_corpus_baselines(
            payload,
            json_path=json_path,
            markdown_path=markdown_path,
        )
    except (ValueError, OSError, ArenaStoreError, RegistryError) as error:
        parser.error(str(error))
        return
    print(written_json)
    print(written_markdown)


def _build_parser() -> tuple[
    argparse.ArgumentParser,
    dict[str, tuple[argparse.ArgumentParser, _Handler]],
]:
    """Declare every subcommand and bind each one to its handler and its subparser.

    Separated from main() so a test can introspect the dispatch mapping directly
    rather than inferring it from four invocations, and so the handler binding is a
    value that can be asserted over instead of control flow that cannot.
    """
    parser = argparse.ArgumentParser(
        description="Run, adjudicate and contrast arena candidates",
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

    # No resample flag here either, and for the same reason (T-02-33).
    contrast_parser = subparsers.add_parser(
        "contrast",
        help="Report the D-44 paired control-vs-probe contrast for one record",
        description=_CONTRAST_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    contrast_parser.add_argument(
        "--record",
        required=True,
        help="ONE run-record directory carrying every arm to be contrasted",
    )
    contrast_parser.add_argument(
        "--corpus",
        required=True,
        help=(
            "the corpus that record was measured against, as a registry name or a"
            " filesystem path; it supplies the sample_id to pair_id and arm mapping"
        ),
    )
    contrast_parser.add_argument("--control-arm", default="control")
    contrast_parser.add_argument("--probe-arm", default="probe_sonnet")
    contrast_parser.add_argument("--output-root", default=str(BASELINES_ROOT))
    contrast_parser.add_argument(
        "--pair-subset",
        choices=(_STRICT_SUBSET, _SHARED_SUBSET),
        default=_STRICT_SUBSET,
        help=(
            "strict, the default, refuses an orphan pair. That is right for the"
            " 300-pair headline contrast, whose arms are fully matched. shared"
            " narrows to the pair ids both arms carry, which the MEAS-13"
            " generator-affinity contrast needs because it is structurally unequal by"
            " D-40's design -- 300 probe_sonnet pairs against 100 probe_haiku -- and"
            " its result then records pair_count 100 beside dropped_pair_count 200."
            " shared never hides the drop: both numbers land in the JSON, in the"
            " rendered prose and on stdout"
        ),
    )
    contrast_parser.add_argument(
        "--allow-cross-corpus",
        action="store_true",
        help=(
            "accept two arms carrying different dataset_sha256 values. Required"
            " alongside --probe-record or --probe-corpus, and the only way that shape"
            " is reachable; the CLI never sets it implicitly (D-45)"
        ),
    )
    contrast_parser.add_argument(
        "--probe-record",
        default=None,
        help="the rarer cross-corpus shape: a SECOND run-record directory",
    )
    contrast_parser.add_argument(
        "--probe-corpus",
        default=None,
        help="the rarer cross-corpus shape: a SECOND corpus name or path",
    )

    corpus_baselines_parser = subparsers.add_parser(
        "corpus-baselines",
        help="Render the D-53 one-candidate-across-four-corpora table",
        description=_CORPUS_BASELINES_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    corpus_baselines_parser.add_argument(
        "--record",
        action="append",
        required=True,
        help="NAME=DIRECTORY, repeatable; NAME is a registry name or the literal public",
    )
    corpus_baselines_parser.add_argument(
        "--output-root", default=str(BASELINES_ROOT)
    )

    # An explicit mapping rather than the two-branch if/else this replaces. Under
    # that shape every command that was not "run" fell through to _adjudicate, so a
    # third subcommand would have silently run the wrong handler against a Namespace
    # missing half the attributes it reads. A command with no entry here is a
    # KeyError at the CLI boundary, which is loud.
    handlers: dict[str, tuple[argparse.ArgumentParser, _Handler]] = {
        "run": (run_parser, _run),
        "adjudicate": (adjudicate_parser, _adjudicate),
        "contrast": (contrast_parser, _contrast),
        "corpus-baselines": (corpus_baselines_parser, _corpus_baselines),
    }
    return (parser, handlers)


def main(argv: tuple[str, ...] | None = None) -> None:
    parser, handlers = _build_parser()
    # argv is threaded through rather than left to sys.argv, matching every other CLI
    # in this repository (starter/shopping_agent/build_catalog_artifacts.py,
    # experiments/run_public.py). It is what lets each subcommand be driven from a
    # test without spawning a process, so a CLI path can be asserted at the same cost
    # as a function call. argv=None keeps sys.argv the default for the real entry
    # point below.
    args = parser.parse_args(argv)
    subparser, handler = handlers[args.command]
    handler(subparser, args)


if __name__ == "__main__":
    main()
