from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass

from experiments.analyze_public import code_revision

# Exactly what starter/agent.py:18-25 accepts today. `catalog_path` and `trace` are
# arena-controlled plumbing rather than candidate knobs, so they are deliberately
# absent. Phase 3 extends the Agent constructor and this set together in one change
# (D-10): a fingerprint that claims a configuration which was silently ignored
# invalidates every comparison built on it, and no downstream test would catch it.
ALLOWED_OVERRIDES = frozenset({"lexical_mode", "exploration", "artifact_path"})

# The one record field that carries CandidateSpec.name, named here so the writer and
# every reader agree on it. `fingerprint` hashes `name`, so a reader reconstructing a
# spec MUST take the name from this field and from no other. Taking it from `run_id`
# instead mints a SECOND fingerprint for a single record: the digest stored in
# summary.json then appears nowhere in the leaderboard, and a record's identity depends
# on which code path looked at it. That divergence was live between plans 01-08 and
# 01-09 and is what this constant plus spec_name_from_record() exist to prevent.
SPEC_NAME_FIELD = "candidate_name"

_HEX_DIGITS = frozenset("0123456789abcdef")
_DIGEST_LENGTH = 64
_UNKNOWN_DIGEST = "unknown"


def _is_recorded_digest(value: str) -> bool:
    if value == _UNKNOWN_DIGEST:
        return True
    return len(value) == _DIGEST_LENGTH and set(value) <= _HEX_DIGITS


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    """One declared arena candidate and the provenance of the run it describes."""

    name: str
    code_revision: str
    code_revision_dirty: bool
    # Ordered pairs, never a dict: a dict field breaks `frozen=True` hashability and
    # admits insertion-order variation, which would produce two different
    # fingerprints for one configuration. `validate()` enforces the sort so an
    # unsorted construction fails loudly instead of minting a second fingerprint.
    overrides: tuple[tuple[str, str], ...]
    catalog_sha256: str
    dataset_sha256: str

    def validate(self) -> None:
        if not self.name:
            raise ValueError("candidate name must not be empty")
        keys = [key for key, _ in self.overrides]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate overrides contain a duplicate key")
        if sorted(keys) != keys:
            raise ValueError("candidate overrides must be in sorted key order")
        unknown = sorted(set(keys) - ALLOWED_OVERRIDES)
        if unknown:
            raise ValueError(f"unknown candidate override keys: {unknown}")
        if not self.code_revision:
            raise ValueError("candidate code_revision must not be empty")
        if not _is_recorded_digest(self.catalog_sha256):
            raise ValueError(
                "candidate catalog_sha256 must be 64 lowercase hex characters"
                " or the literal 'unknown'"
            )
        if not _is_recorded_digest(self.dataset_sha256):
            raise ValueError(
                "candidate dataset_sha256 must be 64 lowercase hex characters"
                " or the literal 'unknown'"
            )

    @property
    def fingerprint(self) -> str:
        # SHA-256 over canonical JSON (D-09), never the builtin hash(), which is
        # salted per process by PYTHONHASHSEED and so cannot identify a candidate
        # across two runs. `separators` is pinned so the digest cannot drift if a
        # future edit adds `indent`; this deliberately differs from the indent=2
        # form used for retained records because this payload is hashed, never
        # written. T-01-09 accepted: the digest is an integrity and reproducibility
        # aid for a single local operator, never an authenticity control.
        payload = json.dumps(
            {
                "name": self.name,
                "code_revision": self.code_revision,
                "code_revision_dirty": self.code_revision_dirty,
                "overrides": dict(self.overrides),
                "catalog_sha256": self.catalog_sha256,
                "dataset_sha256": self.dataset_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def agent_kwargs(self) -> dict[str, str]:
        # The only supported way to build the keyword arguments handed to the
        # constructed agent. Routing construction through here is what keeps the
        # fingerprint and the configuration that actually ran in lockstep (T-01-01).
        return dict(self.overrides)

    def as_record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "code_revision": self.code_revision,
            "code_revision_dirty": self.code_revision_dirty,
            "overrides": dict(self.overrides),
            "catalog_sha256": self.catalog_sha256,
            "dataset_sha256": self.dataset_sha256,
            "fingerprint": self.fingerprint,
        }


def spec_name_from_record(record: dict[str, object], default: str) -> str:
    """The single authority for which recorded field supplies CandidateSpec.name.

    `default` is the caller's fallback for a record written before this field
    existed -- the rescued anchor-legacy record carries no candidate_name, so it
    resolves to its run id and keeps the fingerprint it already had.
    """
    value = record.get(SPEC_NAME_FIELD)
    return str(value) if value else default


def candidate_overrides(mapping: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple((key, str(mapping[key])) for key in sorted(mapping))


def code_revision_dirty() -> bool:
    try:
        result = subprocess.run(
            ("git", "status", "--porcelain"),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        # Fail closed. An unknown tree state is recorded as dirty because a clean
        # flag we could not establish would let a run with uncommitted changes
        # masquerade as the committed revision it names (T-01-11b).
        return True
    return bool(result.stdout.strip())


def current_revision() -> tuple[str, bool]:
    # code_revision() records the SHA but not whether the working tree was dirty, so
    # a run with uncommitted changes would record a revision that does not describe
    # the code that ran (D-11). The gap is closed here rather than in
    # experiments/analyze_public.py, which D-06 keeps stable.
    return (code_revision(), code_revision_dirty())
