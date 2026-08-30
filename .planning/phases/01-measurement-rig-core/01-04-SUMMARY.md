---
phase: 01-measurement-rig-core
plan: 04
subsystem: testing
tags: [candidate, fingerprint, sha256, provenance, allow-list, determinism, stdlib]

# Dependency graph
requires: ["01-01"]
provides:
  - "`arena/candidate.py` — the fingerprinted, hashable candidate declaration (MEAS-14)"
  - "`CandidateSpec.fingerprint` — SHA-256 over canonical JSON, stable across processes and PYTHONHASHSEED values"
  - "`ALLOWED_OVERRIDES` — the construction-time allow-list mirroring exactly what `Agent.__init__` accepts today (D-10)"
  - "`CandidateSpec.agent_kwargs()` — the single supported construction path that keeps fingerprint and applied configuration in lockstep"
  - "`current_revision()` / `code_revision_dirty()` — git SHA plus working-tree dirtiness, fail-closed (D-11)"
affects: [01-05, 01-06, 01-07, 01-08, 01-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Canonical-JSON-over-SHA-256 fingerprint with `separators=(\",\", \":\")` pinned, distinct from the `indent=2` retained-record form"
    - "Ordered `tuple[tuple[str, str], ...]` instead of a `dict` field so a frozen dataclass stays hashable and insertion order cannot fork the digest"
    - "Provenance capture fails closed: an unestablished tree state is recorded as dirty, never as clean"

key-files:
  created:
    - arena/candidate.py
    - tests/test_arena_candidate.py
  modified: []

key-decisions:
  - "Validate digest shape without `re` — a frozenset charset check keeps the import list to exactly the four stdlib modules the plan names, and the project's `_RE` naming convention would otherwise apply to a one-use pattern"
  - "Order `validate()` checks duplicate-before-sorted so each rejection reason is reachable: duplicate keys are trivially sorted and would otherwise be reported as an order failure"
  - "`code_revision_dirty()` catches `CalledProcessError` as well as `OSError`, and the test proves both — a non-zero `git status` exit is exactly as uninformative about tree state as a missing git binary"
  - "The `RevisionCaptureTest` SHA assertion is conditional on `!= \"unknown_revision\"` so the suite stays green in an environment with no git, matching the fallback `code_revision()` already ships"

patterns-established:
  - "Cross-process fingerprint stability is proven by two `sys.executable -c` children under differing `PYTHONHASHSEED`, which is the only assertion that distinguishes SHA-256 from the builtin `hash()`"
  - "No-inert-fields proof: `dataclasses.replace` each field in turn and assert the fingerprint moves"

requirements-completed: [MEAS-14]

# Metrics
duration: 7min
completed: 2026-08-30
---

# Phase 01 Plan 04: Candidate Fingerprinting Summary

**`CandidateSpec` is a frozen slotted dataclass whose SHA-256-over-canonical-JSON `fingerprint` is byte-identical across processes with different `PYTHONHASHSEED` values, whose `overrides` are rejected at validation unless they name exactly what the shipped `Agent` constructor accepts, and which records both the git revision and whether the working tree was dirty when it ran.**

## Performance

- **Duration:** ~7 min
- **Tasks:** 2
- **Files modified:** 2 (2 created, 0 modified)
- **Test delta:** 167 → 186 (+19)

## Accomplishments

- **A fingerprint can no longer describe a configuration that was never applied.** `ALLOWED_OVERRIDES` is `frozenset({"lexical_mode", "exploration", "artifact_path"})` — exactly the candidate-facing keyword arguments of `starter/agent.py:18-25`. `catalog_path` and `trace` are excluded as arena plumbing. An unknown key raises `ValueError` naming it, and `agent_kwargs()` is the single construction path, so the declared spec and the constructed agent cannot diverge (T-01-01).
- **ROADMAP Success Criterion 5 is proven twice over.** Two `CandidateSpec` instances from identical inputs produce an identical fingerprint, and — the stronger claim — two separate child interpreters started with `PYTHONHASHSEED=0` and `PYTHONHASHSEED=1` print byte-identical digests. The negative control was run: substituting `str(hash(payload))` makes that single test fail with `'-379689230636585928' != '-4666850355211007317'`. It is the only assertion in the module that distinguishes the two implementations.
- **No field is inert.** `test_fingerprint_changes_with_every_field` mutates each of the six fields via `dataclasses.replace` and asserts the digest moves, closing D-10's "there are no inert fields" clause with a mechanical proof rather than inspection.
- **Dirty-tree runs cannot pose as clean commits.** `code_revision()` alone records a SHA that need not describe the code that ran. `code_revision_dirty()` folds `git status --porcelain` into the fingerprint payload and returns `True` on both `OSError` and `CalledProcessError` — fail closed (T-01-11b). The git invocation uses a tuple argv with no `shell=True` (T-01-11).
- **The `arena` → `evaluator` boundary stays clean.** The module imports only `hashlib`, `json`, `subprocess`, `dataclasses`, plus `code_revision` from `experiments/analyze_public.py` — verified in this worktree to import only `subprocess`, `dataclasses` and `enum`. Neither `evaluator` nor `run_public` appears on any non-comment line.

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement `CandidateSpec` with allow-list validation and a canonical fingerprint (D-09, D-10, D-11)** — `1a14533` (feat)
2. **Task 2: Prove fingerprint stability and allow-list rejection** — `44042a7` (test)

## Files Created/Modified

- `arena/candidate.py` — `ALLOWED_OVERRIDES`; `CandidateSpec` (`@dataclass(frozen=True, slots=True)`, six fields) with `validate()`, the `fingerprint` property, `agent_kwargs()` and `as_record()`; module helpers `candidate_overrides()`, `code_revision_dirty()`, `current_revision()`; private `_is_recorded_digest()` and the `_HEX_DIGITS` / `_DIGEST_LENGTH` / `_UNKNOWN_DIGEST` constants
- `tests/test_arena_candidate.py` — 19 methods across `CandidateSpecValidationTest` (11), `CandidateFingerprintTest` (6) and `RevisionCaptureTest` (2); no `Agent`, no SQLite, no catalog

## Decisions Made

- **Digest validation without `re`.** `_is_recorded_digest` checks length and `set(value) <= _HEX_DIGITS`. The plan's action names exactly four stdlib imports; adding `re` for a single one-use pattern would also invoke the project's `_RE` compiled-regex convention for no gain. Uppercase hex is rejected, which the test pins explicitly (`"A" * 64` raises).
- **`validate()` check order is load-bearing.** Duplicate keys are checked before sort order because a duplicated key is trivially in sorted position; reversing the two would report `"must be in sorted key order"` for a duplicate and make the duplicate message unreachable.
- **`RevisionCaptureTest` tolerates a git-less environment.** The 40-hex-character assertion is guarded by `revision != "unknown_revision"`, mirroring the fallback `experiments/analyze_public.code_revision()` already ships. Asserting unconditionally would make the suite depend on a git binary that the rest of the 167-test baseline does not need.
- **Two failure modes tested for the dirty flag, not one.** The plan specified `OSError`; `subprocess.CalledProcessError` is covered in the same method via `subTest`, since `code_revision_dirty()` catches both and an untested `except` arm is an untested fail-closed guarantee.

## Deviations from Plan

None — plan executed as written. The three additions above (`CalledProcessError` in the fail-closed test, the git-less guard, the `re`-free digest check) are choices within the plan's stated action, not departures from it; each is recorded under Decisions Made.

## Issues Encountered

- **Worktree base drift.** The worktree spawned at `9faf85c`, an ancestor of the expected base `46a93be`. The startup check detected it, HEAD was on the correct `worktree-agent-*` branch and the tree was clean, so `git reset --hard 46a93be` corrected the base safely. Same class of drift as plan 01-01 reported.
- **`.venv` did not exist in the worktree** and was created by the first `uv run` (CPython 3.13.5). It is gitignored and never entered a commit.

## Verification Results

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_candidate` | **19 tests, OK**, 0.189 s (budget: 3 s) |
| `uv run python -W error::ResourceWarning -m unittest` | **186 tests, OK** (167 baseline + 19 new) |
| `arena/candidate.py` line 1 | exactly `from __future__ import annotations` |
| `grep -v '^\s*#' arena/candidate.py \| grep -c 'evaluator'` | **0** |
| `grep -v '^\s*#' arena/candidate.py \| grep -c 'run_public'` | **0** |
| `grep -c 'shell=True' arena/candidate.py` | **0** |
| `grep -c 'Agent' tests/test_arena_candidate.py` | **0** |
| `ALLOWED_OVERRIDES` | `frozenset({'lexical_mode','exploration','artifact_path'})` — exact |
| Unknown key `belief_temperature` | raises `ValueError`, message contains `belief_temperature` |
| Unsorted keys | raises, message contains `sorted key order` |
| Duplicate key / empty name / empty `code_revision` | all raise `ValueError` |
| `catalog_sha256="ZZZ"` / `"a"*63` / `"A"*64` / `""` | all raise; `"unknown"` accepted |
| Hashability | `{spec}` builds; two equal specs collapse to one element |
| `spec.agent_kwargs() == dict(spec.overrides)` | **True** |
| `code_revision_dirty()` return type | `bool`; tuple argv, no shell |
| Cross-process fingerprint, `PYTHONHASHSEED` 0 vs 1 | byte-identical |
| Negative control (`str(hash(payload))`) | that test **FAILS** as required; reverted via `git checkout -- arena/candidate.py` and re-verified |
| `tests.test_arena_boundary` | not present in this worktree — plan 01-02 owns it and runs in the same wave; `arena/candidate.py` introduces no `evaluator` reference either way |

## Known Stubs

None. Every declared export is implemented and exercised by a test.

## Threat Flags

None. No network endpoint, auth path, file-access pattern, or schema at a trust boundary was introduced beyond those already in the plan's threat register. The one subprocess invocation is a fixed tuple argv with no interpolated input and no shell.

## User Setup Required

None.

## Next Phase Readiness

- Plans 01-05 through 01-09 can import `CandidateSpec`, `candidate_overrides` and `current_revision` to declare and fingerprint arena candidates.
- Plan 01-08's fully-provenanced `experiments/baselines/run-a` can now fill the `code_revision` / `catalog_sha256` / `dataset_sha256` fields that `anchor-legacy` records as `"unknown"`, and `as_record()` is the serialization shape for the `summary.json` provenance block.
- **Phase 3 must extend `Agent.__init__` and `ALLOWED_OVERRIDES` in one change.** Belief, question and fusion knobs are not constructor-injectable today; adding a candidate knob to only one of the two reintroduces exactly the divergence D-10 exists to prevent.
- No blockers.

## Self-Check: PASSED

Both claimed files are tracked by `git ls-files`; both claimed commits (`1a14533`, `44042a7`) are present in `git log`.

---
*Phase: 01-measurement-rig-core*
*Completed: 2026-08-30*
