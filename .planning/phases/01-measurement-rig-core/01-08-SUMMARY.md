---
phase: 01-measurement-rig-core
plan: 08
subsystem: measurement
tags: [runner, cli, evaluator-seam, ground-truth-isolation, atomic-publish, stdlib]

# Dependency graph
requires: ["01-02", "01-06", "01-07"]
provides:
  - "`arena/arena.py` — `run_candidate`, the end-to-end path from a validated `CandidateSpec` to an atomically published record"
  - "`build_candidate_spec` — revision, digests and overrides resolved and validated before any Agent exists"
  - "`_SampleMappingAgent` — the session-UUID to `sample_id` join, performed only after `evaluate()` returns"
  - "`arena/run_arena.py` — one CLI reaching both the evaluation path and the adjudication path"
  - "`arena.leaderboard.spec_from_record` — the single record-to-spec mapping, so an adjudication arm and its leaderboard row share one fingerprint"
  - "`tests/test_arena_runner.py` — 18 tests in 0.087 s with no Agent, no SQLite and no catalog"
affects: [01-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "The scoring harness is reached only through `arena.evaluator_bridge` and called as an opaque function; `experiments/run_public.py` is never imported, so its own top-level harness import cannot leak into `arena/`"
    - "The Agent is constructed from `spec.agent_kwargs()` expansion only — every candidate knob reaches it through one expression, so no literal can be invisible to the fingerprint"
    - "`agent.close()` sits in a `finally` that precedes `publish`, because `os.replace` on a directory raises `PermissionError` on Windows while a handle is held inside it"
    - "CLI report paths are derived from `--output-root`, so a dry run cannot rewrite the committed leaderboard artifacts"
    - "A correctness property is asserted over a recorded call log or a read-recording dict, never left as a comment"

key-files:
  created:
    - arena/arena.py
    - arena/run_arena.py
    - tests/test_arena_runner.py
  modified:
    - arena/leaderboard.py

key-decisions:
  - "Extracted `spec_from_record` in `arena/leaderboard.py` (outside this plan's declared file set) because `CandidateEntry` keeps the fingerprint but not the two digests it was computed from. Without it the CLI could not build a `CandidateArm` whose fingerprint matches the leaderboard row it is reported beside, and the adjudication table would not join to the candidate table. `entry_from_record` now delegates to the same private mapping, so one record cannot mint two fingerprints. Behavior-preserving: all 29 leaderboard tests pass unchanged"
  - "Task 1's acceptance greps `grep -c 'run_public'` and `grep -c 'evaluator'` returning 0 on non-comment lines are both unsatisfiable against Task 1's own required content. The bridge import line `from arena.evaluator_bridge import ...` necessarily contains `evaluator`, and the mandated `_SampleMappingAgent` docstring necessarily names `experiments/run_public.py:31-56` as the module it deliberately duplicates. Read as intended (no import of either) and verified by AST: `arena/arena.py` imports neither, and `tests/test_arena_boundary.py` — which is the real guard, and catches dynamic imports too — passes"
  - "CLI errors route through `parser.error`, giving exit 2 and a message naming the offending path, rather than surfacing a `FileNotFoundError` from inside `json.loads` several frames below the CLI"
  - "Overrides are built by iterating `_OVERRIDE_FLAGS` rather than naming each flag inline, and an unset flag is omitted rather than recorded as `None`, so one configuration cannot fingerprint two ways"
  - "No `retrieval_routes.jsonl`, `failures.jsonl` or `ablation.md` is written (D-04); RESEARCH assumption A6 verified every Phase 1 metric derives from `sessions.jsonl` alone, and `experiments/run_public.py` stays available when miss attribution is wanted"
  - "Left `STATE.md` and `ROADMAP.md` untouched — the orchestrator owns those writes after the wave merges"

patterns-established:
  - "A duplication that exists to protect an architectural boundary states both its correctness argument and its duplication reason in the docstring, and names the decision record that forbids the import"
  - "A mutation check is part of acceptance: the spec-fidelity test was verified to FAIL against a hard-coded override before being accepted as evidence"

requirements-completed: [MEAS-14, MEAS-15]

# Metrics
duration: 22min
completed: 2026-08-30
---

# Phase 01 Plan 08: Arena Runner and CLI Summary

**The rig is now wired end to end: a validated `CandidateSpec` runs through the unmodified organizer evaluator via the single bridge seam and publishes a provenance-carrying record atomically, with ground truth provably never reaching the Agent — proven by 18 tests that run in 0.087 s without constructing an Agent, opening SQLite, or touching the 580 MB artifact.**

## Performance

- **Duration:** ~22 min
- **Tasks:** 3
- **Tests:** 338 passing (was 320), full suite 4.3 s warning-strict
- **New tests:** 18 in 0.087 s

## What Was Built

### Task 1 — `arena/arena.py` (commit `7ee3a16`)

`run_candidate(spec, *, run_id, catalog_path, dataset_path, output_root)` performs the whole path: validate the run id, refuse an existing destination, work inside a `.{run_id}-` prefixed temporary directory covered by `.gitignore`'s `experiments/baselines/.*/` rule under the default baseline root, construct the Agent from the spec alone, run the evaluator through the bridge, convert each session row into a validated `SessionOutcome`, write `sessions.jsonl` and `summary.json`, and publish atomically.

`build_candidate_spec` resolves revision and dirtiness, computes both digests, normalises the overrides, and calls `spec.validate()` **before** returning — validation before use is what makes it impossible for a fingerprint to describe an unapplied configuration.

`_SampleMappingAgent` reproduces the shape of `experiments/run_public.py:31-56`. Its docstring carries both the correctness argument (the UUID-to-`sample_id` join happens only after `evaluate()` returns) and the duplication reason (importing that module would transitively pull the harness package into `arena/` and defeat D-08).

### Task 2 — `arena/run_arena.py` (commit `d3bca41`)

Two subcommands matching the form `01-VALIDATION.md` already records. `run` carries the eight declared flags with `choices`-bounded enumerations; `adjudicate` takes `--baseline`, repeatable `--candidate`, and `--output-root`. There is no resample-count flag — it stays a fixed module constant (D-24), so no invocation can make the rig cheap enough to be wrong.

### Task 3 — `tests/test_arena_runner.py` (commit `6f1c2ed`)

18 tests across `SampleMappingTest`, `SpecFidelityTest` and `CliTest`, all using hand-written fakes.

## Verification

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_runner` | 18 tests, 0.149 s, OK |
| `uv run python -m unittest -v tests.test_arena_boundary` | 8 tests, OK |
| `uv run python -W error::ResourceWarning -m unittest -v` | 338 tests, 4.288 s, OK, no `ResourceWarning` |
| `python -m arena.run_arena --help` / `run --help` / `adjudicate --help` | all exit 0, all flags present |
| `run --exploration bogus` | exit 2, argparse choices error |
| `adjudicate --baseline <missing>` | exit 2, `run directory does not exist: experiments\baselines\does-not-exist`, no traceback |
| `grep -c 'resamples' arena/run_arena.py` | 0 |
| `grep -v '^\s*#' arena/run_arena.py \| grep -c 'evaluator'` | 0 |
| `grep -c 'exploration=' arena/arena.py` | 0 |
| `grep -c 'catalog.jsonl' tests/test_arena_runner.py` | 0 |
| Module run from an unrelated working directory | 18 tests OK — no dependence on `data/` |
| Mutation check: hard-code `exploration="disabled"` | `test_agent_receives_exactly_the_spec_overrides` FAILS, reverted, `git diff` clean |
| `spec_from_record(d).fingerprint == entry_from_record(d).fingerprint` | True on `anchor-legacy` |

## Threat Model Coverage

| Threat ID | Mitigation as built |
|---|---|
| T-01-03 | The wrapper records only `reset` ordering. `test_ground_truth_never_reaches_the_agent` runs a fake harness that **holds** the target, then walks every recorded call argument and asserts no `ground_truth` key, no `parent_asin` key, and no occurrence of the target id |
| T-01-01 | The Agent is constructed from `spec.agent_kwargs()` only, after `spec.validate()`. The recording double accepts keyword arguments exclusively, so a positional construction would raise |
| T-01-02b | AST-verified: `arena/arena.py` imports `arena.candidate`, `arena.evaluator_bridge`, `arena.metrics`, `arena.store`, `starter.*` and stdlib — neither `run_public` nor the harness package |
| T-01-06 | `validate_run_id` plus `resolve_run_directory`; `test_invalid_run_id_refuses` covers `../escape`, `test_existing_destination_refuses` covers a re-used id |
| T-01-19 | Work happens in a `.{run_id}-` prefixed temporary directory, published with `os.replace`. `test_agent_is_closed_before_publish` records `destination.exists()` at the moment `close()` fires and asserts it is `False` |
| T-01-20 | No resample flag exists; grep returns 0 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `CandidateArm` could not be built with a fingerprint matching its leaderboard row**

- **Found during:** Task 2
- **Issue:** The plan directs the `adjudicate` subcommand to load records with `entry_from_record` and build `CandidateArm` values. `CandidateArm` requires a `CandidateSpec`, but `CandidateEntry` retains the fingerprint without the `catalog_sha256` / `dataset_sha256` it was computed from. Reconstructing a spec from the entry alone yields a **different** fingerprint, which would break the join between the adjudication table and the candidate table in the generated report.
- **Fix:** Extracted the record-to-spec mapping in `arena/leaderboard.py` as private `_spec_from_payload`, exposed it as `spec_from_record`, and made `entry_from_record` delegate to it. One authority for the mapping, so two callers cannot mint two fingerprints for one record.
- **Files modified:** `arena/leaderboard.py`
- **Verification:** All 29 existing leaderboard tests pass unchanged; `spec_from_record` and `entry_from_record` agree on `anchor-legacy`.
- **Commit:** `d3bca41`

### Acceptance Criteria Read As Intended

Two Task 1 greps are unsatisfiable against Task 1's own required content and were verified by their underlying invariant instead:

- `grep -v '^\s*#' arena/arena.py | grep -c 'run_public'` returns **1**, from the `_SampleMappingAgent` docstring that the plan's action text explicitly requires ("importing `experiments.run_public` would transitively pull..."). A docstring is not a comment line, so the `^\s*#` filter does not strip it. Removing the citation would gut the docstring's purpose — pointing a reader at the module it duplicates.
- `grep -v '^\s*#' arena/arena.py | grep -c 'evaluator'` returns **1**, from the mandated `from arena.evaluator_bridge import ...` line; the seam's own module name contains the substring.

Both real invariants hold and were verified by AST walk and by `tests/test_arena_boundary.py`, which is the authoritative guard and catches dynamic imports the greps would miss.

## Known Stubs

None. Every artifact this plan declares is wired and exercised.

## Threat Flags

None. `arena/run_arena.py` is a local operator CLI with no network surface, no credential, and no new file access outside the run root and the report paths; all paths are validated at the boundary.

## Notes for Plan 01-09

- `run_candidate` writes exactly two files per run: `sessions.jsonl` and `summary.json`.
- `summary.json` carries `fingerprint`, `candidate_name`, `code_revision`, `code_revision_dirty`, `overrides`, both digests, `elapsed_seconds`, `provenance`, `provenance_complete: true`, plus every aggregate key the evaluator returns.
- The cross-agreement check D-06 calls for is now runnable: `python -m arena.run_arena run` and `python -m experiments.run_public` are independent paths that must both produce `0.92 / 0.524466 / 3.425 / 0.76884`.
- A real `adjudicate` invocation needs two records with distinct fingerprints; `adjudicate()` refuses a candidate sharing the baseline's fingerprint.
- The CLI writes to `experiments/baselines/leaderboard.json` and `experiments/LEADERBOARD.md` at the default `--output-root`. Both are git-tracked; point `--output-root` at a temporary tree for any dry run.

## Self-Check: PASSED

- `arena/arena.py` — FOUND
- `arena/run_arena.py` — FOUND
- `tests/test_arena_runner.py` — FOUND
- `arena/leaderboard.py` — FOUND (modified)
- Commit `7ee3a16` — FOUND
- Commit `d3bca41` — FOUND
- Commit `6f1c2ed` — FOUND
