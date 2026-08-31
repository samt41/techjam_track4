from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from arena.metrics import SessionOutcome


BASELINES_ROOT = Path("experiments/baselines")
SESSIONS_FILENAME = "sessions.jsonl"
SUMMARY_FILENAME = "summary.json"

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")  # experiments/run_public.py:28


class ArenaStoreError(RuntimeError):
    """Raised when a baseline record cannot be read, written, or published safely."""


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError(
            "run_id must contain only letters, digits, dots, dashes, or underscores"
        )
    return run_id


def resolve_run_directory(root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    resolved_root = root.resolve()
    destination = (root / run_id).resolve()
    # The regex alone already rejects "..", a leading separator, a drive letter and an
    # NTFS alternate-data-stream ":". This containment check is defence in depth
    # (T-01-06): it keeps traversal impossible even if the allow-list is later widened
    # by someone who does not realise the id becomes a directory name.
    if not destination.is_relative_to(resolved_root):
        raise ArenaStoreError(f"run id escapes its output root: {run_id}")
    return destination


def sha256_file(path: Path) -> str:
    # An integrity and reproducibility aid for a single local user, never an
    # authenticity control (T-01-09): nothing here is signed, so a digest proves only
    # that two files are the same bytes, not who produced them.
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_sessions(path: Path, sessions: tuple[SessionOutcome, ...]) -> None:
    # Canonical form is not cosmetic: the fingerprint and byte-reproducibility
    # assertions downstream compare these files byte for byte.
    path.write_text(
        "".join(
            json.dumps(row.as_record(), sort_keys=True) + "\n" for row in sessions
        ),
        encoding="utf-8",
    )


def load_sessions(path: Path) -> tuple[SessionOutcome, ...]:
    rows: list[SessionOutcome] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        # json.loads only -- never pickle, eval or yaml (T-01-07). Identifiers are
        # normalized to strings; metric fields keep their JSON types until validate()
        # can reject incoherent rows.
        try:
            record = json.loads(line)
            outcome = SessionOutcome(
                sample_id=str(record["sample_id"]),
                scenario_type=str(record["scenario_type"]),
                hit=record["hit"],
                first_hit_turn=record["first_hit_turn"],
                best_rank=record["best_rank"],
                reciprocal_rank=record["reciprocal_rank"],
            )
            outcome.validate()
            outcome = SessionOutcome(
                sample_id=outcome.sample_id,
                scenario_type=outcome.scenario_type,
                hit=outcome.hit,
                first_hit_turn=outcome.first_hit_turn,
                best_rank=outcome.best_rank,
                reciprocal_rank=float(outcome.reciprocal_rank),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ArenaStoreError(
                f"invalid session row in {path} at line {number}: {error}"
            ) from error
        rows.append(outcome)
    return tuple(rows)


def publish(working: Path, destination: Path) -> None:
    """Move the completed working directory to its final name.

    `Path.rename` maps to `os.rename`, which on Windows raises WinError 183 when
    the destination already exists (unlike POSIX rename, which replaces). The
    run refused to overwrite an existing destination at entry, so a destination
    present now is a corpse from an earlier crashed run of the same id; clear it
    and retry rather than losing a completed 200-session evaluation at the final
    publish step.

    One caveat the original does not state: on Windows `os.replace` on a directory
    also fails with `PermissionError` when any process still holds a handle inside
    it, so the caller must close the `Agent` and any trace sink before publishing.

    A second precondition the original assumed and never held (T-01-28): this is a
    module-level public helper with no caller-enforced pre-check of its own, so it
    must not treat a directory at `destination` as a corpse merely because the
    replace failed. `run_candidate` does pre-check at `arena/arena.py:110`, but the
    committed `elapsed_seconds` values are 337-462 seconds, so a completed record
    can appear at that path inside the window between the check and this call. The
    delete therefore fires only when a directory is actually visible at
    `destination`; every other failure -- a cross-device link, an ACL denial, a
    path-too-long, an antivirus lock -- is reported by name with its cause attached
    and nothing is removed.
    """
    try:
        os.replace(working, destination)
    except OSError as error:
        if not destination.is_dir():
            raise ArenaStoreError(
                f"could not publish to {destination}: {error}"
            ) from error
        shutil.rmtree(destination)
        try:
            os.replace(working, destination)
        except OSError as retry_error:
            raise ArenaStoreError(
                f"could not publish to {destination} after clearing it: {retry_error}"
            ) from retry_error
