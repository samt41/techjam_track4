from __future__ import annotations

import tempfile
from pathlib import Path
from time import perf_counter

from arena.candidate import (
    SPEC_NAME_FIELD,
    CandidateSpec,
    candidate_overrides,
    current_revision,
)
from arena.evaluator_bridge import catalog_index, evaluate, load_jsonl
from arena.metrics import SessionOutcome
from arena.store import (
    BASELINES_ROOT,
    SESSIONS_FILENAME,
    SUMMARY_FILENAME,
    ArenaStoreError,
    publish,
    resolve_run_directory,
    sha256_file,
    validate_run_id,
    write_json,
    write_sessions,
)
from starter.agent import Agent
from starter.shopping_agent.search_backend import LexicalMode


# Recorded in every published summary so a reader can tell which of the two code
# paths produced the record. D-06 keeps experiments/run_public.py frozen, so both
# paths exist simultaneously and their agreement is the validation evidence.
PROVENANCE = "arena.arena.run_candidate via `python -m arena.run_arena run`"

# Exactly the keys run_candidate writes into `summary` before the harness-result splat.
# SPEC_NAME_FIELD is taken from the imported constant rather than spelled as a literal
# so the guard and the writer cannot drift onto different field names.
_PROVENANCE_KEYS = frozenset({
    "run_id",
    "fingerprint",
    SPEC_NAME_FIELD,
    "code_revision",
    "code_revision_dirty",
    "overrides",
    "catalog_sha256",
    "dataset_sha256",
    "elapsed_seconds",
    "provenance",
    "provenance_complete",
})


class _SampleMappingAgent:
    """Wraps Agent to record reset-call order without touching the scoring harness.

    Correctness. The harness generates a random session UUID per sample in sample
    order, so recording each reset maps that UUID back to the public sample id.
    The join happens only AFTER evaluate() returns, so ground truth never enters
    the Agent -- a hard invariant of this repository, and the one whose breach
    would invalidate every score the project reports.

    Duplication. This deliberately re-implements experiments/run_public.py:31-56
    rather than importing it. Importing that module would transitively pull the
    scoring harness package into arena/ through its own top-level import, defeating
    D-08's single-seam rule and failing tests/test_arena_boundary.py. D-06 keeps
    that module byte-frozen, so the copy cannot drift underneath us. De-duplicating
    the two is a Phase 8 cleanup candidate (see also D-07), not debt to fix here.
    """

    def __init__(self, agent: Agent, sample_ids: tuple[str, ...]) -> None:
        self._agent = agent
        self._sample_ids = sample_ids
        self._reset_count = 0
        self.session_to_sample: dict[str, str] = {}

    def reset(self, session_id: str, user_profile: dict) -> None:
        # Bounds-guarded rather than indexed blindly: a harness that resets more
        # times than there are samples must not raise inside the wrapper and lose
        # an otherwise complete run.
        if self._reset_count < len(self._sample_ids):
            self.session_to_sample[session_id] = self._sample_ids[self._reset_count]
        self._reset_count += 1
        self._agent.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        return self._agent.respond(session_id, user_message, turn, top_k)

    def close(self) -> None:
        self._agent.close()


def build_candidate_spec(
    name: str,
    *,
    catalog_path: str | Path,
    dataset_path: str | Path,
    overrides: dict[str, str],
) -> CandidateSpec:
    revision, dirty = current_revision()
    spec = CandidateSpec(
        name=name,
        code_revision=revision,
        code_revision_dirty=dirty,
        overrides=candidate_overrides(overrides),
        catalog_sha256=sha256_file(Path(catalog_path)),
        dataset_sha256=sha256_file(Path(dataset_path)),
    )
    # Validated BEFORE it is used to build anything. This ordering is the whole
    # mitigation for T-01-01: an unknown or unapplied override is rejected here, so
    # a fingerprint can never describe a configuration that did not run.
    spec.validate()
    return spec


def run_candidate(
    spec: CandidateSpec,
    *,
    run_id: str,
    catalog_path: str | Path,
    dataset_path: str | Path,
    output_root: str | Path = BASELINES_ROOT,
) -> Path:
    validate_run_id(run_id)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = resolve_run_directory(root, run_id)
    if destination.exists():
        raise FileExistsError(f"arena run already exists: {destination}")

    # Under the default baseline root, the `.{run_id}-` prefix is matched by
    # .gitignore's `experiments/baselines/.*/` rule, so an interrupted run is not
    # staged and mistaken for a completed record (T-01-19).
    with tempfile.TemporaryDirectory(prefix=f".{run_id}-", dir=root) as temporary:
        working = Path(temporary)
        samples = load_jsonl(dataset_path)
        catalog_ids, categories, products = catalog_index(catalog_path)

        # Every candidate knob reaches the Agent through this one expansion and
        # nowhere else. A literal written here instead would be invisible to the
        # fingerprint, so no keyword below may be hard-coded except the two pieces
        # of arena plumbing that CandidateSpec deliberately excludes.
        agent_kwargs: dict[str, object] = dict(spec.agent_kwargs())
        if "lexical_mode" in agent_kwargs:
            agent_kwargs["lexical_mode"] = LexicalMode(agent_kwargs["lexical_mode"])
        base_agent = Agent(catalog_path=catalog_path, trace=None, **agent_kwargs)
        agent = _SampleMappingAgent(
            base_agent,
            tuple(str(sample["sample_id"]) for sample in samples),
        )

        started = perf_counter()
        try:
            result = evaluate(agent, samples, catalog_ids, categories, products)
        finally:
            # Closed here rather than after the publish, and this ordering is
            # load-bearing on Windows: os.replace on a directory raises
            # PermissionError while any process still holds a handle inside it, and
            # the Agent holds a 1 GiB memory-mapped SQLite connection. Publishing
            # first would strand a completed 200-session run at its final step.
            agent.close()
        elapsed_seconds = perf_counter() - started

        # The harness result is splatted LAST into the summary literal below, so any
        # key it returns wins over the arena-written provenance beside it.
        # Today evaluate() returns none of these and nothing collides; the guard is for
        # the day it does. The sibling writer import_legacy_results._build_summary
        # already refuses on exactly this hazard, and the asymmetry was the defect: a
        # provenance field silently overwritten by harness output produces a record
        # that lies about what produced it, and no downstream check would notice,
        # because test_published_summary_carries_the_fingerprint compares the record
        # against a spec built by the same code path. Raised BEFORE the summary is
        # constructed, and before anything is written, so the failure is a refusal
        # rather than a repaired record. Reordering the splat to first would also stop
        # the overwrite, but it would silently DROP harness output on a name clash --
        # the same class of quiet wrongness in the other direction.
        colliding = sorted(_PROVENANCE_KEYS & set(result))
        if colliding:
            raise ArenaStoreError(
                f"harness result already carries provenance keys {colliding}",
            )

        sessions = tuple(
            _session_outcome(row) for row in tuple(result.pop("sessions"))
        )
        write_sessions(working / SESSIONS_FILENAME, sessions)

        summary: dict[str, object] = {
            "run_id": run_id,
            "fingerprint": spec.fingerprint,
            # Keyed through the shared constant so the reader that rebuilds a spec
            # from this record cannot drift onto a different field and mint a second
            # fingerprint for it.
            SPEC_NAME_FIELD: spec.name,
            "code_revision": spec.code_revision,
            "code_revision_dirty": spec.code_revision_dirty,
            "overrides": dict(spec.overrides),
            "catalog_sha256": spec.catalog_sha256,
            "dataset_sha256": spec.dataset_sha256,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "provenance": PROVENANCE,
            "provenance_complete": True,
            **result,
        }
        write_json(working / SUMMARY_FILENAME, summary)

        publish(working, destination)
    return destination


def _session_outcome(row: dict) -> SessionOutcome:
    outcome = SessionOutcome(
        sample_id=str(row["sample_id"]),
        scenario_type=str(row["scenario_type"]),
        hit=row["hit"],
        first_hit_turn=row["first_hit_turn"],
        best_rank=row["best_rank"],
        reciprocal_rank=row["reciprocal_rank"],
    )
    outcome.validate()
    return SessionOutcome(
        sample_id=outcome.sample_id,
        scenario_type=outcome.scenario_type,
        hit=outcome.hit,
        first_hit_turn=outcome.first_hit_turn,
        best_rank=outcome.best_rank,
        reciprocal_rank=float(outcome.reciprocal_rank),
    )
