"""The D-43 dataset registry: `data/datasets.json` as canonical committed truth.

Three doors close here, and all three have to close together for "frozen" to mean
anything. D-43 puts the version IN the corpus name, so regenerating a corpus
produces a new filename instead of new bytes under an old one. `publish_corpus`
refuses an existing destination, because `os.replace` on a *file* overwrites
silently on Windows and would leave the committed digest describing bytes that no
longer exist. And `resolve_dataset` re-hashes the file at use time, which is what
turns a recorded number into an enforced precondition of every measurement
(Pitfall 6) -- a digest nothing checks is prose, not evidence.

The corpus-shape checks live here rather than in the row schema because they are
properties of a whole corpus and cannot be seen one row at a time: the 40/40/15/5
scenario mix (D-30), pair completeness (MEAS-11), and the three-arm cross-check
subset (D-40).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from arena.datasets.drops import dropped_constraint_ids, refused_pair_ids
from arena.datasets.schema import (
    ARMS,
    SCENARIO_MIX_TARGET,
    SCENARIO_TYPES,
    SampleRow,
    distinct_targets,
    load_corpus,
    scenario_mix,
    validate_corpus,
    write_corpus,
)
from arena.store import sha256_file, write_json


REGISTRY_PATH = Path("data/datasets.json")

# D-12: the JSON is truth and the Markdown is a generated view of it. Both are
# committed, because a view nobody can regenerate is just a second source of
# truth that drifts.
DATASETS_MARKDOWN_PATH = Path("docs/datasets.md")

CORPUS_ROOT = Path("data")

REGISTRY_SCHEMA_VERSION = 1

TARGET_SNAPSHOT_SCHEMA_VERSION = 1

# A registry name becomes a filename, so it inherits store._RUN_ID_RE's allow-list
# discipline (T-02-03) -- narrowed further, because D-43 requires the version to be
# IN the name (`probe.v1`). That narrowing is what makes regeneration produce a new
# file rather than a silent overwrite of a corpus other phases already measured
# against.
_DATASET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.v[0-9]+$")

# The organizer-supplied 200-session set. It predates D-43 entirely: it carries no
# version suffix, has no generator, no divergence log and no target snapshot, and
# its path is `data/public_set.jsonl` rather than `data/public.jsonl`. It is
# special-cased in exactly two places -- the name check and the generator-field
# check inside DatasetEntry.validate -- and nowhere else.
PUBLIC_DATASET_NAME = "public"

# The official 40/40/15/5 mix cannot be hit exactly at every corpus size: 700 probe
# pairs cannot split 15% into a whole number of pairs. The check is therefore a
# proportion within two percentage points, not an equality. Widening this is a
# measurement decision, not a convenience -- at 2,800 sessions two points is 56
# sessions.
_MIX_TOLERANCE = 0.02

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Truncated in the DISPLAY column only; the full digest is always in the JSON
# (mirrors leaderboard._display_fingerprint).
_DISPLAY_DIGEST_LENGTH = 12

# The five keys divergence.bucket_summary emits alongside `bucket`. Pinned so a
# malformed table is refused at write time rather than rendering as blank cells in
# a committed Markdown view.
_DIVERGENCE_METRIC_KEYS = (
    "mean_overlap_ratio",
    "median_overlap_ratio",
    "min_overlap_ratio",
    "n",
    "pass_count",
)

# D-34, stated in the rendered view because the view is what a reader reaches for.
DIVERGENCE_PROSE = (
    "Lexical divergence is reported per `classify_constraint` bucket and never as"
    " one aggregate (D-34): the buckets are not the same size and do not behave"
    " alike, so a single mean would imply one finding where there are six of very"
    " unequal support. At probe scale the `size` and `use_case` rows fall to n"
    " around 11 and 4 and are descriptive noise. The control arm is measured by the"
    " same code as the probe arm, and its mean overlap is the contrast a probe"
    " ratio is read against -- the probe number means nothing on its own."
)


class RegistryError(RuntimeError):
    """Raised when a registry entry cannot be read, written, or resolved safely."""


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_count(value: object, name: str, *, minimum: int) -> int:
    # bool is a subclass of int, so it must be excluded explicitly or `True` would
    # validate as a one-session corpus.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _require_digest(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if allow_empty and value == "":
        return value
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(
            f"{name} must be 64 lowercase hex characters, got {value!r}"
        )
    return value


def _require_paired_artifact(
    path: str, digest: str, count: int, *, label: str
) -> None:
    """A recorded path with no digest is the exact failure D-43 exists to prevent."""

    # T-02-43: an artifact the registry names but does not pin can drift from the
    # corpus it describes with nothing anywhere noticing, which is the same class of
    # non-evidence as an unchecked corpus digest. The three fields move together or
    # the entry is refused: all present, or all absent.
    _require_digest(digest, f"{label}_sha256", allow_empty=True)
    _require_count(count, f"{label}_pair_count", minimum=0)
    if bool(path) != bool(digest):
        raise ValueError(
            f"{label} path and digest must be recorded together:"
            f" path={path!r}, sha256={digest!r}"
        )
    if bool(path) != (count > 0):
        raise ValueError(
            f"{label} count must be positive exactly when its path is recorded:"
            f" path={path!r}, count={count}"
        )


def _require_drop_ledger(
    path: str, digest: str, constraints: int, pairs: int
) -> None:
    """A recorded shortfall with no ledger is a silent drop with a number on it.

    Deliberately NOT `_require_paired_artifact`. That helper insists the count is
    positive exactly when the path is recorded, which is right for a divergence log
    -- an empty one describes nothing. A drop ledger is the opposite case: writing
    it on every run, including the runs that dropped nothing, is what makes "this
    corpus lost nothing" a claim the artifact makes rather than an absence a reader
    has to interpret. So zero counts with a recorded ledger are legal, and the one
    combination refused is the dangerous one: a corpus stating it dropped something
    while pointing at no record of what.
    """
    _require_digest(digest, "drop_log_sha256", allow_empty=True)
    _require_count(constraints, "dropped_constraint_count", minimum=0)
    _require_count(pairs, "refused_pair_count", minimum=0)
    if bool(path) != bool(digest):
        raise ValueError(
            "drop log path and digest must be recorded together:"
            f" path={path!r}, sha256={digest!r}"
        )
    if (constraints or pairs) and not path:
        raise ValueError(
            f"the entry records {constraints} dropped constraint(s) and {pairs}"
            " refused pair(s) but names no drop ledger; a shortfall with no"
            " record of its causes is the silent drop the ledger exists to"
            " prevent"
        )


def validate_dataset_name(name: str) -> str:
    if not isinstance(name, str) or not _DATASET_NAME_RE.fullmatch(name):
        raise ValueError(
            "dataset name must be lowercase letters, digits and underscores"
            f" followed by a version suffix, e.g. probe.v1; got {name!r}"
        )
    return name


def _ensure_contained(destination: Path, root: Path, subject: str) -> Path:
    # Defence in depth, mirroring store.resolve_run_directory (T-02-03). The regex
    # already rejects "..", a leading separator, a drive letter and an NTFS
    # alternate-data-stream ":", so this cannot fire today -- it keeps traversal
    # impossible if the allow-list is later widened by someone who does not realise
    # the name becomes a filename. A corpus name is constructed by the driver and
    # must never come from model output.
    resolved_root = Path(root).resolve()
    resolved = Path(destination).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise RegistryError(f"{subject} escapes its corpus root: {destination}")
    return resolved


def resolve_corpus_path(name: str, *, root: Path = CORPUS_ROOT) -> Path:
    validate_dataset_name(name)
    return _ensure_contained(Path(root) / f"{name}.jsonl", Path(root), name)


def target_snapshot_path(corpus_name: str, *, root: Path = CORPUS_ROOT) -> Path:
    # Versioned with the corpus exactly as D-43 versions the corpus file: a snapshot
    # of one corpus's targets says nothing about the next corpus's, so a shared
    # filename would silently mix two freezes.
    validate_dataset_name(corpus_name)
    return Path(root) / f"targets.{corpus_name}.json"


def divergence_from_summary(
    summary: tuple[dict[str, object], ...],
) -> tuple[tuple[str, object], ...]:
    """Convert `divergence.bucket_summary` output into orderable registry pairs."""

    # Ordered pairs rather than dicts, matching CandidateSpec.overrides: a dict field
    # breaks frozen=True hashability and admits insertion-order variation, which is
    # how one measurement mints two committed records.
    rows: list[tuple[str, object]] = []
    for row in summary:
        bucket = _require_text(row.get("bucket"), "divergence bucket")
        metrics = tuple(
            sorted((key, value) for key, value in row.items() if key != "bucket")
        )
        rows.append((bucket, metrics))
    return tuple(sorted(rows, key=lambda pair: pair[0]))


def _validate_divergence(divergence: tuple[tuple[str, object], ...]) -> None:
    buckets = [bucket for bucket, _ in divergence]
    if len(buckets) != len(set(buckets)):
        raise ValueError("divergence table contains a duplicate bucket")
    if sorted(buckets) != buckets:
        raise ValueError("divergence table must be in sorted bucket order")
    for bucket, metrics in divergence:
        if not isinstance(metrics, tuple):
            raise ValueError(
                f"divergence bucket {bucket!r} must carry ordered metric pairs"
            )
        keys = [key for key, _ in metrics]
        if sorted(keys) != keys:
            raise ValueError(
                f"divergence bucket {bucket!r} metrics must be in sorted key order"
            )
        missing = sorted(set(_DIVERGENCE_METRIC_KEYS) - set(keys))
        if missing:
            raise ValueError(
                f"divergence bucket {bucket!r} is missing metrics: {missing}"
            )


@dataclass(frozen=True, slots=True)
class DatasetEntry:
    """One frozen corpus and the provenance of the generation that produced it.

    Every digest on this record is an integrity and reproducibility aid for a
    single local user, never an authenticity control (T-01-09, T-02-31): nothing
    here is signed, so a digest proves only that two files are the same bytes, not
    who produced them. The field list is also the disclosure whitelist -- there is
    no environment, credential or settings field, because a provenance record is
    exactly where one would leak.
    """

    name: str
    path: str
    sha256: str
    schema_version: int
    session_count: int
    distinct_target_count: int
    scenario_mix: tuple[tuple[str, int], ...]
    generator_model_alias: str
    generator_model_resolved: str
    claude_cli_version: str
    prompt_pack: tuple[tuple[str, str], ...]
    seed: int
    code_revision: str
    code_revision_dirty: bool
    frozen_commit: str
    response_log_path: str
    response_log_sha256: str
    call_count: int
    cost_usd: float
    # The per-bucket table from divergence.bucket_summary. An AGGREGATE: it cannot
    # answer "what was the overlap ratio for pair X?", which is exactly what Roadmap
    # SC3 asks for -- hence the per-pair log pinned below it.
    divergence: tuple[tuple[str, object], ...]
    divergence_log_path: str
    divergence_log_sha256: str
    divergence_pair_count: int
    target_snapshot_path: str
    target_snapshot_sha256: str
    target_snapshot_count: int
    # What the corpus LOST, alongside what it kept. A registry that recorded only
    # the survivors would let an authorised reduction read as a full corpus, and
    # the shortfall would then surface much later as an unexplained row count with
    # the rejection reasons long gone -- the failure docs/STATUS.md names under
    # AUTHORING_ATTEMPT_CAP. The ledger itself is `arena/datasets/drops.py`.
    #
    # Defaulted, because a corpus that dropped nothing genuinely has nothing to
    # record here and the organizer-supplied `public` set predates the pipeline
    # entirely. The default cannot hide a real drop: `_require_drop_ledger` refuses
    # a non-zero count with no ledger, and `check_recorded_counts` compares both
    # numbers against the ledger's own rows before an entry is written.
    drop_log_path: str = ""
    drop_log_sha256: str = ""
    dropped_constraint_count: int = 0
    refused_pair_count: int = 0

    def validate(self) -> None:
        if self.name != PUBLIC_DATASET_NAME:
            validate_dataset_name(self.name)
        _require_text(self.path, "dataset path")
        _require_digest(self.sha256, "dataset sha256")
        _require_count(self.schema_version, "schema_version", minimum=1)
        _require_count(self.session_count, "session_count", minimum=1)
        _require_count(self.distinct_target_count, "distinct_target_count", minimum=1)
        if not isinstance(self.scenario_mix, tuple):
            raise ValueError("scenario_mix must be a tuple of ordered pairs")
        names = [name for name, _ in self.scenario_mix]
        if sorted(names) != names:
            raise ValueError("scenario_mix must be in sorted scenario order")
        if len(set(names)) != len(names):
            raise ValueError("scenario_mix contains a duplicate scenario")
        for name, count in self.scenario_mix:
            _require_count(count, f"scenario_mix count for {name}", minimum=0)
        total = sum(count for _, count in self.scenario_mix)
        if total != self.session_count:
            raise ValueError(
                f"scenario_mix sums to {total} but session_count is"
                f" {self.session_count}"
            )
        # The organizer set has no generator, so its provenance fields record WHERE
        # it came from rather than being left empty -- an empty provenance field is
        # indistinguishable from one nobody filled in.
        _require_text(self.generator_model_resolved, "generator_model_resolved")
        _require_text(self.generator_model_alias, "generator_model_alias")
        _require_text(self.code_revision, "code_revision")
        _require_text(self.frozen_commit, "frozen_commit")
        if not isinstance(self.code_revision_dirty, bool):
            raise ValueError("code_revision_dirty must be a boolean")
        if not isinstance(self.prompt_pack, tuple):
            raise ValueError("prompt_pack must be a tuple of ordered pairs")
        prompt_names = [name for name, _ in self.prompt_pack]
        if sorted(prompt_names) != prompt_names:
            raise ValueError("prompt_pack must be in sorted prompt-name order")
        if len(set(prompt_names)) != len(prompt_names):
            raise ValueError("prompt_pack contains a duplicate prompt name")
        _require_count(self.seed, "seed", minimum=0)
        _require_count(self.call_count, "call_count", minimum=0)
        if isinstance(self.cost_usd, bool) or not isinstance(
            self.cost_usd, (int, float)
        ):
            raise ValueError("cost_usd must be numeric")
        if float(self.cost_usd) < 0.0:
            raise ValueError(f"cost_usd must not be negative, got {self.cost_usd}")
        _require_digest(
            self.response_log_sha256, "response_log_sha256", allow_empty=True
        )
        if bool(self.response_log_path) != bool(self.response_log_sha256):
            raise ValueError(
                "response log path and digest must be recorded together:"
                f" path={self.response_log_path!r},"
                f" sha256={self.response_log_sha256!r}"
            )
        _validate_divergence(self.divergence)
        _require_paired_artifact(
            self.divergence_log_path,
            self.divergence_log_sha256,
            self.divergence_pair_count,
            label="divergence_log",
        )
        _require_paired_artifact(
            self.target_snapshot_path,
            self.target_snapshot_sha256,
            self.target_snapshot_count,
            label="target_snapshot",
        )
        _require_drop_ledger(
            self.drop_log_path,
            self.drop_log_sha256,
            self.dropped_constraint_count,
            self.refused_pair_count,
        )

    def as_record(self) -> dict[str, object]:
        return {
            "call_count": self.call_count,
            "claude_cli_version": self.claude_cli_version,
            "code_revision": self.code_revision,
            "code_revision_dirty": self.code_revision_dirty,
            "cost_usd": float(self.cost_usd),
            "distinct_target_count": self.distinct_target_count,
            "divergence": {
                bucket: dict(metrics)  # type: ignore[arg-type]
                for bucket, metrics in self.divergence
            },
            "divergence_log_path": self.divergence_log_path,
            "divergence_log_sha256": self.divergence_log_sha256,
            "divergence_pair_count": self.divergence_pair_count,
            "drop_log_path": self.drop_log_path,
            "drop_log_sha256": self.drop_log_sha256,
            "dropped_constraint_count": self.dropped_constraint_count,
            "frozen_commit": self.frozen_commit,
            "generator_model_alias": self.generator_model_alias,
            "generator_model_resolved": self.generator_model_resolved,
            "name": self.name,
            "path": self.path,
            "prompt_pack": dict(self.prompt_pack),
            "refused_pair_count": self.refused_pair_count,
            "response_log_path": self.response_log_path,
            "response_log_sha256": self.response_log_sha256,
            "scenario_mix": dict(self.scenario_mix),
            "schema_version": self.schema_version,
            "seed": self.seed,
            "session_count": self.session_count,
            "sha256": self.sha256,
            "target_snapshot_count": self.target_snapshot_count,
            "target_snapshot_path": self.target_snapshot_path,
            "target_snapshot_sha256": self.target_snapshot_sha256,
        }


def entry_from_record(record: dict[str, object]) -> DatasetEntry:
    divergence_record = record.get("divergence", {})
    if not isinstance(divergence_record, dict):
        raise ValueError("divergence must be a json object keyed by bucket")
    divergence = tuple(
        (str(bucket), tuple(sorted(dict(metrics).items())))
        for bucket, metrics in sorted(divergence_record.items())
    )
    entry = DatasetEntry(
        name=str(record["name"]),
        path=str(record["path"]),
        sha256=str(record["sha256"]),
        schema_version=record["schema_version"],  # type: ignore[arg-type]
        session_count=record["session_count"],  # type: ignore[arg-type]
        distinct_target_count=record["distinct_target_count"],  # type: ignore[arg-type]
        scenario_mix=tuple(sorted(dict(record["scenario_mix"]).items())),  # type: ignore[arg-type]
        generator_model_alias=str(record["generator_model_alias"]),
        generator_model_resolved=str(record["generator_model_resolved"]),
        claude_cli_version=str(record.get("claude_cli_version", "")),
        prompt_pack=tuple(sorted(dict(record.get("prompt_pack", {})).items())),  # type: ignore[arg-type]
        seed=record["seed"],  # type: ignore[arg-type]
        code_revision=str(record["code_revision"]),
        code_revision_dirty=bool(record["code_revision_dirty"]),
        frozen_commit=str(record["frozen_commit"]),
        response_log_path=str(record.get("response_log_path", "")),
        response_log_sha256=str(record.get("response_log_sha256", "")),
        call_count=record.get("call_count", 0),  # type: ignore[arg-type]
        cost_usd=record.get("cost_usd", 0.0),  # type: ignore[arg-type]
        divergence=divergence,
        divergence_log_path=str(record.get("divergence_log_path", "")),
        divergence_log_sha256=str(record.get("divergence_log_sha256", "")),
        divergence_pair_count=record.get("divergence_pair_count", 0),  # type: ignore[arg-type]
        target_snapshot_path=str(record.get("target_snapshot_path", "")),
        target_snapshot_sha256=str(record.get("target_snapshot_sha256", "")),
        target_snapshot_count=record.get("target_snapshot_count", 0),  # type: ignore[arg-type]
        drop_log_path=str(record.get("drop_log_path", "")),
        drop_log_sha256=str(record.get("drop_log_sha256", "")),
        dropped_constraint_count=record.get("dropped_constraint_count", 0),  # type: ignore[arg-type]
        refused_pair_count=record.get("refused_pair_count", 0),  # type: ignore[arg-type]
    )
    entry.validate()
    return entry


def load_registry(path: Path = REGISTRY_PATH) -> tuple[DatasetEntry, ...]:
    # json.loads only -- never pickle, eval or yaml (T-02-11), mirroring
    # store.load_sessions. The entry name travels with the error because a registry
    # of four corpora is read by eye but debugged by message.
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RegistryError(f"registry {path} must be a json object")
    version = payload.get("schema_version")
    if version != REGISTRY_SCHEMA_VERSION:
        raise RegistryError(
            f"unsupported registry schema version {version!r} in {path};"
            f" expected {REGISTRY_SCHEMA_VERSION}"
        )
    records = payload.get("datasets", [])
    if not isinstance(records, list):
        raise RegistryError(f"registry {path} datasets must be a json array")
    entries: list[DatasetEntry] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise RegistryError(
                f"invalid registry entry at index {index} of {path}:"
                f" expected an object, got {type(record).__name__}"
            )
        try:
            entry = entry_from_record(record)
        except (KeyError, TypeError, ValueError) as error:
            raise RegistryError(
                f"invalid registry entry at index {index} of {path}: {error}"
            ) from error
        if entry.name in seen:
            raise RegistryError(
                f"duplicate registry entry {entry.name!r} in {path}"
            )
        seen.add(entry.name)
        entries.append(entry)
    return tuple(sorted(entries, key=lambda entry: entry.name))


def write_registry(path: Path, entries: tuple[DatasetEntry, ...]) -> None:
    for entry in entries:
        entry.validate()
    names = [entry.name for entry in entries]
    if len(set(names)) != len(names):
        raise RegistryError("registry entries contain a duplicate name")
    write_json(
        Path(path),
        {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "datasets": [
                entry.as_record()
                for entry in sorted(entries, key=lambda entry: entry.name)
            ],
        },
    )


def upsert_entry(
    entries: tuple[DatasetEntry, ...],
    entry: DatasetEntry,
    *,
    allow_refreeze: bool = False,
) -> tuple[DatasetEntry, ...]:
    entry.validate()
    existing = next(
        (candidate for candidate in entries if candidate.name == entry.name), None
    )
    if (
        existing is not None
        and existing.sha256 != entry.sha256
        and not allow_refreeze
    ):
        # Re-freezing a corpus that other phases have already measured against
        # invalidates those measurements silently: every committed baseline, paired
        # contrast and leaderboard row keyed to the old bytes keeps its number while
        # the corpus under it changes. The flag exists so that decision is typed out
        # by a caller rather than taken by an accident of ordering.
        raise RegistryError(
            f"refusing to re-freeze {entry.name}: registry records"
            f" {existing.sha256} but the new entry carries {entry.sha256};"
            " pass allow_refreeze=True to overwrite a measured corpus"
        )
    kept = [
        candidate for candidate in entries if candidate.name != entry.name
    ] + [entry]
    return tuple(sorted(kept, key=lambda candidate: candidate.name))


def resolve_entry_path(entry: DatasetEntry, *, root: Path = CORPUS_ROOT) -> Path:
    return _ensure_contained(Path(entry.path), Path(root), entry.name)


def resolve_dataset(
    value: str,
    *,
    registry_path: Path = REGISTRY_PATH,
    root: Path = CORPUS_ROOT,
) -> Path:
    """Resolve a registry name or a filesystem path, re-hashing a registered corpus.

    The re-hash is the whole point (Pitfall 6). D-43 records a digest at freeze
    time; without a check at USE time that digest describes the past, and a
    regenerated or truncated corpus would be measured against as if it were the
    frozen one. It costs milliseconds on a 2 MiB file.
    """

    registry = Path(registry_path)
    # A missing registry is not an error: `data/datasets.json` does not exist until
    # the first corpus is frozen, and every caller in the meantime is passing a
    # plain path.
    entries = load_registry(registry) if registry.is_file() else ()
    match = next((entry for entry in entries if entry.name == value), None)
    if match is not None:
        path = resolve_entry_path(match, root=root)
        if not path.is_file():
            raise RegistryError(
                f"corpus {value} is registered at {path} but the file is missing"
            )
        observed = sha256_file(path)
        if observed != match.sha256:
            raise RegistryError(
                f"corpus {value} has drifted from its frozen digest:"
                f" {registry} records {match.sha256}"
                f" but {path} hashes to {observed}"
            )
        return path
    # Matches run_arena._existing_file's message shape, so an operator typo reads
    # the same whichever door it comes through.
    path = Path(value)
    if not path.is_file():
        raise ValueError(f"dataset does not exist: {path}")
    return path


def publish_corpus(
    rows: tuple[SampleRow, ...], *, name: str, root: Path = CORPUS_ROOT
) -> Path:
    destination = resolve_corpus_path(name, root=root)
    corpus_root = Path(root)
    corpus_root.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        # D-43's filename versioning plus an explicit refusal. `os.replace` on a
        # file overwrites silently on Windows, so without this the registry would
        # keep describing bytes that no longer exist and nothing would raise.
        raise FileExistsError(f"corpus already exists: {destination}")
    with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=corpus_root) as staging:
        working = Path(staging) / destination.name
        write_corpus(working, rows)
        # Validated from the STAGED BYTES, not from the in-memory rows: this is the
        # last moment before a corpus becomes frozen and citable, and reading back
        # what was actually written also catches a serialization defect that an
        # in-memory check would miss. SampleRow.validate() is not called by the
        # constructor, so without this an invalid corpus could be published and
        # would only fail later, at the point where its digest is already committed.
        validate_corpus(load_corpus(working), corpus_name=name)
        os.replace(working, destination)
    return destination


def describe_corpus(rows: tuple[dict, ...]) -> dict[str, object]:
    """The registry-facing shape summary of a corpus. Pure."""

    by_pair: dict[str, set[str]] = {}
    arm_counts: dict[str, int] = {}
    for record in rows:
        pair_id = str(record["pair_id"])
        arm = str(record["arm"])
        by_pair.setdefault(pair_id, set()).add(arm)
        arm_counts[arm] = arm_counts.get(arm, 0) + 1
    return {
        "session_count": len(rows),
        "distinct_target_count": len(distinct_targets(rows)),
        "scenario_mix": scenario_mix(rows),
        "pair_count": len(by_pair),
        "arm_counts": tuple(sorted(arm_counts.items())),
        "cross_check_pair_count": sum(
            1 for arms in by_pair.values() if "probe_haiku" in arms
        ),
    }


def check_scenario_mix(rows: tuple[dict, ...]) -> None:
    """D-30: every scenario's share is within `_MIX_TOLERANCE` of the official mix."""

    if not rows:
        raise RegistryError("scenario mix is undefined on an empty corpus")
    counts = dict(scenario_mix(rows))
    unknown = sorted(set(counts) - set(SCENARIO_TYPES))
    if unknown:
        raise RegistryError(f"corpus carries unknown scenario types: {unknown}")
    total = len(rows)
    # Every offending scenario is named at once rather than the first one found: a
    # mix is a single allocation, so raising on the first deviation would make the
    # operator fix one share, regenerate a corpus, and rediscover the next.
    offenders = [
        f"{scenario} is {counts.get(scenario, 0) / total:.4f} of the corpus,"
        f" official mix {share:.4f}"
        for scenario, share in SCENARIO_MIX_TARGET
        if abs(counts.get(scenario, 0) / total - share) > _MIX_TOLERANCE
    ]
    if offenders:
        raise RegistryError(
            "scenario mix departs from the official 40/40/15/5 by more than"
            f" {_MIX_TOLERANCE} (D-30): " + "; ".join(offenders)
        )


def check_pairing(rows: tuple[dict, ...]) -> None:
    """MEAS-11: every probe row has exactly one control partner on the same target."""

    by_pair: dict[str, dict[str, str]] = {}
    for record in rows:
        pair_id = str(record["pair_id"])
        arm = str(record["arm"])
        if arm not in ARMS:
            raise RegistryError(
                f"pair {pair_id} carries an unknown arm {arm!r};"
                f" expected one of {list(ARMS)}"
            )
        arms = by_pair.setdefault(pair_id, {})
        if arm in arms:
            # A duplicated (pair_id, arm) would make align_on_pair_id join one
            # session against two rows, so the paired n would read correct while the
            # pairing was not.
            raise RegistryError(
                f"pair {pair_id} carries the arm {arm!r} twice"
            )
        arms[arm] = str(record["ground_truth"]["parent_asin"])
    for pair_id in sorted(by_pair):
        arms = by_pair[pair_id]
        if "control" not in arms:
            raise RegistryError(
                f"pair {pair_id} has no control row: a probe arm with no control"
                " partner silently shrinks the paired n (T-02-30)"
            )
        if len(arms) < 2:
            raise RegistryError(
                f"pair {pair_id} carries only the arm {sorted(arms)[0]!r};"
                " a pair needs at least two arms to be contrasted"
            )
        control_target = arms["control"]
        for arm in sorted(arms):
            if arm == "control":
                continue
            if arms[arm] != control_target:
                raise RegistryError(
                    f"pair {pair_id} arm {arm!r} targets {arms[arm]}"
                    f" but its control targets {control_target}"
                )


def check_recorded_counts(
    entry: DatasetEntry,
    rows: tuple[dict, ...],
    ledger: tuple[dict[str, object], ...],
    *,
    sampled_pair_count: int,
) -> None:
    """Every number the registry states must equal the rows and the ledger on disk.

    This is the invariant the `AUTHORING_ATTEMPT_CAP` note in docs/STATUS.md exists
    to protect, promoted from a warning into a check. Dropping constraints is
    admissible only because the shortfall is accounted for, and "accounted for"
    means the arithmetic closes: sessions equal rows written, targets equal
    distinct targets written, the recorded drop counts equal the ledger's own rows,
    every refused pair is absent from the corpus, and the pairs that survived plus
    the pairs that were refused equal the pairs that were sampled.

    Checked before the entry is frozen rather than in a test over the committed
    file, because a mismatch here is silent by nature -- every individual artifact
    is well-formed and only their agreement fails. The committed-corpus sweep in
    plan 02-11 then re-asserts it from the other side.
    """
    if entry.session_count != len(rows):
        raise RegistryError(
            f"{entry.name} records {entry.session_count} sessions but"
            f" {len(rows)} rows were written"
        )
    targets = distinct_targets(rows)
    if entry.distinct_target_count != len(targets):
        raise RegistryError(
            f"{entry.name} records {entry.distinct_target_count} targets but"
            f" {len(targets)} distinct targets were written"
        )
    recorded_constraints = len(dropped_constraint_ids(ledger))
    if entry.dropped_constraint_count != recorded_constraints:
        raise RegistryError(
            f"{entry.name} records {entry.dropped_constraint_count} dropped"
            f" constraint(s) but its ledger accounts for {recorded_constraints}"
        )
    refused = refused_pair_ids(ledger)
    if entry.refused_pair_count != len(refused):
        raise RegistryError(
            f"{entry.name} records {entry.refused_pair_count} refused pair(s)"
            f" but its ledger accounts for {len(refused)}"
        )
    published = {str(record["pair_id"]) for record in rows}
    resurrected = sorted(published.intersection(refused))
    if resurrected:
        # A pair cannot be both refused and published. If it is, either the
        # refusal did not take effect or the ledger is describing a different run,
        # and both read as a well-formed corpus.
        raise RegistryError(
            f"{entry.name} publishes pair(s) its drop ledger refuses:"
            f" {resurrected}"
        )
    if len(published) + len(refused) != sampled_pair_count:
        raise RegistryError(
            f"{entry.name} publishes {len(published)} pair(s) and refuses"
            f" {len(refused)}, which does not account for the"
            f" {sampled_pair_count} sampled"
        )


def check_cross_check_subset(rows: tuple[dict, ...]) -> None:
    """D-40 / MEAS-13: every `probe_haiku` pair also carries a `probe_sonnet` arm."""

    by_pair: dict[str, list[str]] = {}
    for record in rows:
        by_pair.setdefault(str(record["pair_id"]), []).append(str(record["arm"]))
    haiku = {pair for pair, arms in by_pair.items() if "probe_haiku" in arms}
    sonnet = {pair for pair, arms in by_pair.items() if "probe_sonnet" in arms}
    orphaned = sorted(haiku - sonnet)
    if orphaned:
        raise RegistryError(
            "probe_haiku pairs must be a subset of probe_sonnet pairs (D-40);"
            f" these carry no probe_sonnet arm: {orphaned}"
        )
    # SUBSET, not strict subset. Equality is a legal corpus -- it means every pair
    # was cross-checked -- and D-40 only requires that no haiku pair lacks a sonnet
    # counterpart to be contrasted against. Refusing equality would reject a fully
    # cross-checked corpus for a property that is an artefact of the 100-of-700
    # sampling rather than a correctness invariant.
    for pair in sorted(haiku):
        if len(by_pair[pair]) != 3:
            raise RegistryError(
                f"cross-check pair {pair} carries {len(by_pair[pair])} rows;"
                " a three-arm pair must carry exactly control, probe_haiku and"
                " probe_sonnet"
            )


def write_target_snapshot(
    path: Path,
    *,
    corpus_name: str,
    catalog_sha256: str,
    targets: tuple[tuple[str, str], ...],
) -> None:
    """Commit the `parent_asin` -> `searchable_text` map the D-34 sweep reads.

    Plan 02-11's corpus-wide sweep must re-derive every per-pair overlap ratio over
    the real committed corpus, and the measurement needs the target's own text. The
    only two sources are the 580 MB artifact -- which the catalog-free sign-off item
    forbids a test from opening -- and a committed snapshot, so the snapshot is
    defined here as a first-class artifact rather than left for the sweep to invent.

    Scope, and its cost: this is written for `probe.v1` ONLY. The probe is the one
    corpus carrying a corpus-wide divergence sweep; a snapshot for the 2,800
    expanded sessions would add several megabytes of committed catalog text that no
    test reads, and L-16 names repo weight as this phase's real risk. The expanded
    corpora's divergence evidence is the per-pair log, which needs no product text.

    Worth its ~1 MB even though the log already carries every ratio, for a
    second-order reason: it lets the sweep RE-DERIVE each ratio independently and
    assert it equals the recorded one. That is a two-sided check on the generator's
    own bookkeeping rather than a re-read of it.
    """

    validate_dataset_name(corpus_name)
    _require_digest(catalog_sha256, "catalog_sha256")
    if not targets:
        raise RegistryError(
            f"refusing to write an empty target snapshot for {corpus_name}"
        )
    mapping: dict[str, str] = {}
    for parent_asin, text in targets:
        _require_text(parent_asin, "target parent_asin")
        # An empty searchable_text would measure as overlap ratio 0.0, which is the
        # BEST possible divergence score -- a missing target would silently flatter
        # the probe exactly where there is no evidence at all.
        _require_text(text, f"searchable text for {parent_asin}")
        if parent_asin in mapping:
            raise RegistryError(
                f"duplicate parent_asin {parent_asin} in the target snapshot"
                f" for {corpus_name}"
            )
        mapping[parent_asin] = text
    write_json(
        Path(path),
        {
            "catalog_sha256": catalog_sha256,
            "corpus": corpus_name,
            "schema_version": TARGET_SNAPSHOT_SCHEMA_VERSION,
            "targets": mapping,
        },
    )


def load_target_snapshot(path: Path) -> tuple[int, str, tuple[tuple[str, str], ...]]:
    # json.loads only -- never pickle, eval or yaml (T-02-11).
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RegistryError(f"target snapshot {path} must be a json object")
    version = payload.get("schema_version")
    if version != TARGET_SNAPSHOT_SCHEMA_VERSION:
        raise RegistryError(
            f"unsupported target snapshot schema version {version!r} in {path};"
            f" expected {TARGET_SNAPSHOT_SCHEMA_VERSION}"
        )
    targets = payload.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise RegistryError(f"target snapshot {path} carries no targets")
    catalog_sha256 = _require_digest(
        payload.get("catalog_sha256", ""), f"catalog_sha256 in {path}"
    )
    return (
        int(version),
        catalog_sha256,
        tuple(sorted((str(key), str(value)) for key, value in targets.items())),
    )


def _cell(value: object) -> str:
    # bool before int: bool IS an int in Python, so the int arm would print True
    # as 1. Mirrors leaderboard._cell, minus the scientific-notation arm -- an
    # overlap ratio is bounded in [0, 1] and never approaches a permutation floor.
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.6f}"


def _table(
    header: tuple[str, ...],
    alignment: tuple[str, ...],
    rows: tuple[str, ...],
) -> str:
    # The `| _none_ |` fallback mirrors leaderboard._table: an empty body would emit
    # a header and separator with nothing under them, which renders as a malformed
    # table rather than as an honest "no rows".
    body = "\n".join(rows) or "| " + " | ".join(["_none_"] * len(header)) + " |"
    return (
        "| " + " | ".join(header) + " |\n"
        "| " + " | ".join(alignment) + " |\n" + body + "\n"
    )


def render_markdown(entries: tuple[DatasetEntry, ...]) -> str:
    """Render the committed view of the registry. Pure -- no I/O, no clock."""

    ordered = sorted(entries, key=lambda entry: entry.name)
    corpus_rows = tuple(
        "| "
        + " | ".join(
            (
                f"`{entry.name}`",
                _cell(entry.session_count),
                _cell(entry.distinct_target_count),
                f"`{entry.generator_model_resolved}`",
                _cell(entry.seed),
                f"`{entry.sha256[:_DISPLAY_DIGEST_LENGTH]}`",
                f"`{entry.frozen_commit[:_DISPLAY_DIGEST_LENGTH]}`",
                f"`{entry.divergence_log_path}`"
                if entry.divergence_log_path
                else "_none_",
                # The shortfall in the RENDERED view, not only in the JSON. This
                # column is the one a reader meets first, and a table that showed
                # only session counts would let an authorised reduction read as a
                # corpus that lost nothing.
                (
                    f"{entry.dropped_constraint_count} constraints,"
                    f" {entry.refused_pair_count} pairs"
                    if entry.dropped_constraint_count or entry.refused_pair_count
                    else "_none_"
                ),
            )
        )
        + " |"
        for entry in ordered
    )
    sections = [
        "# Datasets",
        "",
        "Generated from `data/datasets.json`, which is the source of truth (D-12)."
        " Edit the JSON and re-render; never edit this file by hand.",
        "",
        "The `Dropped` column is what a corpus could not author. A constraint that"
        " spent `AUTHORING_ATTEMPT_CAP` attempts without clearing the D-33/D-34/D-35"
        " gates is dropped from EVERY arm of its pair, and a pair that thereby loses"
        " a whole constraint list is refused outright. Both are itemised, with the"
        " verbatim rejection reason, in the drop ledger named by the entry's"
        " `drop_log_path`. A corpus showing `_none_` here lost nothing.",
        "",
        _table(
            (
                "Name",
                "Sessions",
                "Targets",
                "Generator (resolved)",
                "Seed",
                "sha256 (12)",
                "Frozen at",
                "Per-pair divergence log",
                "Dropped",
            ),
            ("---", "---:", "---:", "---", "---:", "---", "---", "---", "---"),
            corpus_rows,
        ),
        "",
        "## Lexical divergence by bucket",
        "",
        DIVERGENCE_PROSE,
        "",
    ]
    for entry in ordered:
        metrics = {bucket: dict(pairs) for bucket, pairs in entry.divergence}  # type: ignore[arg-type]
        bucket_rows = tuple(
            "| "
            + " | ".join(
                (
                    f"`{bucket}`",
                    _cell(metrics[bucket]["n"]),
                    _cell(metrics[bucket]["mean_overlap_ratio"]),
                    _cell(metrics[bucket]["median_overlap_ratio"]),
                    _cell(metrics[bucket]["min_overlap_ratio"]),
                    f"{_cell(metrics[bucket]['pass_count'])}/"
                    f"{_cell(metrics[bucket]['n'])}",
                )
            )
            + " |"
            for bucket, _ in entry.divergence
        )
        sections.extend(
            [
                f"### `{entry.name}`",
                "",
                _table(
                    ("Bucket", "n", "mean overlap", "median", "min", "passing"),
                    ("---", "---:", "---:", "---:", "---:", "---:"),
                    bucket_rows,
                ),
                "",
            ]
        )
    return "\n".join(sections).rstrip("\n") + "\n"
