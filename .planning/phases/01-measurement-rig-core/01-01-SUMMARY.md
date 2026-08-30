---
phase: 01-measurement-rig-core
plan: 01
subsystem: testing
tags: [gitignore, provenance, measurement, jsonl, stdlib, argparse, sha256]

# Dependency graph
requires: []
provides:
  - "`experiments/baselines/` is a git-tracked evidence root; every other `experiments/` run directory and the 580 MB artifact stay ignored"
  - "`arena` package marker, the root of the measurement rig"
  - "`arena/import_legacy_results.py` — one-off migration of a provenance-free harness `results.json` into the canonical baselines record shape"
  - "`experiments/baselines/anchor-legacy/` — all 200 run-A session rows plus run-A aggregates and per-scenario MRR/MTTC, committed"
  - "Every later plan in this phase can be built and unit-proven against real data without a 190 s evaluation run"
affects: [01-02, 01-03, 01-04, 01-05, 01-06, 01-07, 01-08, 01-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Canonical JSON serialization reused verbatim from `experiments/run_public.py:283-294`"
    - "Retained measurement evidence is a committed file, never a number in prose"
    - "Provenance gaps are declared as explicit fields, never omitted"

key-files:
  created:
    - arena/__init__.py
    - arena/import_legacy_results.py
    - experiments/baselines/anchor-legacy/sessions.jsonl
    - experiments/baselines/anchor-legacy/summary.json
  modified:
    - .gitignore

key-decisions:
  - "Scope the `.gitignore` negation to `experiments/baselines/` exactly — a broader `!experiments/**` would re-include the ~10,400-event route traces and eventually the 580 MB artifact (T-01-08)"
  - "Prove the negation with `git check-ignore` exit status rather than inspection — F-01 was a silent failure, and only an exit-status assertion catches a silent failure"
  - "Write `provenance_complete: false`, `code_revision: \"unknown_revision\"`, `catalog_sha256: \"unknown\"`, `dataset_sha256: \"unknown\"` explicitly rather than omitting them, so the rescued record can never be mistaken for a fingerprinted run (D-10)"
  - "The importer depends on neither the scoring harness (D-08) nor the arena package — depending on the rig it seeds would let a rig bug silently corrupt its own validation anchor"
  - "Verify agreement with `experiments/RUNS.md` only after explicit rounding; the RUNS.md pair `0.5245` / `0.7688` is not self-consistent read as exact"

patterns-established:
  - "Baseline record shape: `sessions.jsonl` (one projected session row per line) + `summary.json` (aggregates + provenance block) per run directory"
  - "Session rows are projected onto `SESSION_FIELDS` so analysis-added keys can never leak into a retained record"
  - "Untrusted JSON at a trust boundary is validated field-by-field before anything is written; `json.loads` only, never `pickle`/`eval`/`yaml`"

requirements-completed: [MEAS-03]

# Metrics
duration: 4min
completed: 2026-08-30
---

# Phase 01 Plan 01: Measurement Evidence Rescue Summary

**A scoped `.gitignore` negation makes `experiments/baselines/` permanently git-tracked, and a stdlib-only importer migrates the untracked run-A `results.json` into a committed 200-session record carrying HR@10 `0.92` / MRR `0.524466` / MTTC `3.425` / TechnicalScore `0.76884` with its provenance gap declared.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-30T03:59:00Z
- **Completed:** 2026-08-30T04:02:48Z
- **Tasks:** 3
- **Files modified:** 5 (4 created, 1 modified)

## Accomplishments

- **F-01's root cause is closed permanently.** `.gitignore:9` `experiments/*/` had silently swallowed every run directory this project ever produced. `!experiments/baselines/` now sits after the excludes — the only position and form git honours — and the escape is proven by `git check-ignore` exit status, not by reading the file.
- **The negation did not widen the repo.** `experiments/probe-run/summary.json` and `experiments/probe-run/retrieval_routes.jsonl` still exit `0` on `git check-ignore` (matched by `experiments/*/`), and `data/catalog.artifacts/catalog.sqlite3` still exits `0` (matched by `data/*.artifacts/`). Exactly one `!experiments/` line exists.
- **The complete run-A record survives a stray evaluator invocation.** `evaluator/local_evaluator.py` defaults `--output` to `results.json`, so any bare run overwrote the only copy. All 200 session rows and the run-A aggregates are now committed under names the `.gitignore:8` bare `results.json` pattern cannot match.
- **MEAS-03 is satisfied.** Per-scenario MRR and MTTC — `boundary 0.404444 / 3.6`, `browsing 0.527862 / 3.125`, `buying 0.464296 / 3.2875`, `intent_override 0.715873 / 4.533333` — are recoverable from a committed file with the `Agent` never invoked.
- **The 190 s evaluation-run dependency is off the front of the phase.** Plans 01-02 through 01-09 can be built and unit-proven against real data immediately (RESEARCH F-03, orchestrator DIRECTIVE 1).

## Task Commits

Each task was committed atomically:

1. **Task 1: Preserve the untracked anchor data and open `experiments/baselines/` to git (D-04)** — `133e14e` (chore)
2. **Task 2: Create the `arena` package and the one-off legacy results importer** — `2ab0360` (feat)
3. **Task 3: Produce and commit the rescued run-A record** — `2c04420` (feat)

## Files Created/Modified

- `.gitignore` — adds `!experiments/baselines/` after the `experiments/*/` and `experiments/.*-/` excludes, with a comment recording both why the scope is narrow and why the position is load-bearing
- `arena/__init__.py` — package marker, one-line docstring, matching `experiments/__init__.py` in shape
- `arena/import_legacy_results.py` — stdlib-only CLI (`--results`, `--output`, `--provenance`) exposing `SESSION_FIELDS`, `import_legacy_results()`, and `main()`; validates the payload before writing, projects rows onto the six harness fields, and emits byte-canonical JSON/JSONL
- `experiments/baselines/anchor-legacy/sessions.jsonl` — 200 rows, each a JSON object with exactly the six `SESSION_FIELDS` keys
- `experiments/baselines/anchor-legacy/summary.json` — run-A aggregates, per-scenario metrics, token usage, and the seven-field provenance block

## Decisions Made

- **Single-line negation, no `!experiments/baselines/**` companion.** `01-PATTERNS.md` suggested adding both lines; `01-RESEARCH.md` Pitfall 2 empirically verified that the directory re-include alone works, and the plan's acceptance criteria forbid any second `!experiments/` line. Verified: the record files exit `1` on `git check-ignore`.
- **Provenance-key collision is a `ValueError`, not a silent overwrite.** The plan specified copying every input top-level key except `sessions` and then overlaying seven provenance fields. If the input already carried, say, `code_revision`, an overlay would silently destroy real data at exactly the trust boundary the threat model names. `_build_summary` raises instead. (Rule 2 — correctness at a trust boundary.)
- **`main() -> None`, not `-> int`.** Differs from `build_catalog_artifacts.main()`, but the plan specifies the signature and this is a one-off migration with no exit-code contract.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Source `results.json` absent from the parallel-execution worktree**

- **Found during:** Task 1 (before any edit), and again in Task 3
- **Issue:** This plan runs as a worktree-isolated executor. `results.json` is matched by `.gitignore:8`, so it is untracked and therefore does not exist in a freshly created worktree. Task 3's importer command had no input.
- **Fix:** Read the file from the main repository working tree at `C:/Users/cervo/Desktop/Code/tttj/techjam_track4/results.json` (39,067 bytes, SHA-256 `2b157db1b244cb7023e51c3b7e62a8a1be0b0620c8fd0ff0f3a90b127bb2236c` — matching the plan's stated size) and copied it into the worktree root so the plan's literal command ran unmodified. The copy is itself gitignored and never entered any commit.
- **Files modified:** none tracked
- **Verification:** SHA-256 of the worktree copy is byte-identical to the main-repo original; `git check-ignore -v results.json` exits `0`, confirming the copy cannot be committed.

**2. [Rule 2 - Missing Critical] Provenance-key collision check added to `_build_summary`**

- **Found during:** Task 2
- **Issue:** The specified construction — copy every input key except `sessions`, then set the seven provenance fields — silently overwrites a colliding input key. The input is an untrusted, provenance-free file whose whole purpose is to become this phase's validation anchor; a silent overwrite there is the same class of defect T-01-01 and D-10 exist to prevent.
- **Fix:** `_build_summary` raises `ValueError("results payload already carries provenance keys [...]")` when any of the seven provenance field names is already a top-level input key.
- **Files modified:** `arena/import_legacy_results.py`
- **Verification:** An input carrying `code_revision` raises the expected `ValueError`; the real `results.json` carries none of the seven and imports cleanly.

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** No scope creep. Deviation 1 is environmental — the plan was written for main-repo execution and dispatched to a worktree. Deviation 2 hardens a boundary the plan's own threat model already flagged. Neither changed any acceptance criterion, and all criteria pass as written.

## Issues Encountered

- **`experiments/RUNS.md` is not self-consistent read at face value.** It records MRR `0.5245` and TechnicalScore `0.7688`, but `0.50×0.92 + 0.30×0.5245 + 0.20×0.7575 = 0.76885`, which displays as `0.7689`. The plan anticipated this: agreement is asserted only after explicit rounding of the full-precision values (`round(mrr, 4) == 0.5245`, `round(technical_score, 4) == 0.7688`), both of which hold. No exact-equality assertion against RUNS.md was written.
- **Worktree base drift.** The worktree spawned at `9faf85c` rather than the expected `c153bca`. The startup check detected it, HEAD was on the correct `worktree-agent-*` branch, and the working tree was clean, so `git reset --hard c153bca` corrected the base safely.

## Verification Results

| Check | Result |
|---|---|
| `uv run python -W error::ResourceWarning -m unittest` | **167 tests, OK** — unchanged |
| `git check-ignore -q experiments/baselines/anchor-legacy/sessions.jsonl` | exit **1** (tracked) |
| `git check-ignore -q experiments/baselines/probe/summary.json` | exit **1** (tracked) |
| `git check-ignore -q experiments/probe-run/summary.json` | exit **0**, matched by `.gitignore:9 experiments/*/` |
| `git check-ignore -q experiments/probe-run/retrieval_routes.jsonl` | exit **0** (traces stay out) |
| `git check-ignore -q data/catalog.artifacts/catalog.sqlite3` | exit **0**, matched by `.gitignore:17 data/*.artifacts/` |
| `grep -c '^!experiments/' .gitignore` | **1** |
| `sessions.jsonl` row count / key set | **200** rows, each exactly the six `SESSION_FIELDS` |
| `summary.json` aggregates | `0.92` / `0.524466` / `3.425` / `0.7575` / `0.76884` — exact |
| `summary.json` per-scenario | `10/80/80/30` counts, `0.9/0.95/0.9/0.9` HR@10, MRR and MTTC all exact |
| `summary.json` provenance | `provenance_complete: false`, `code_revision: "unknown_revision"`, both digests `"unknown"` |
| `uv run python -m arena.import_legacy_results --help` | exit **0**, lists all three flags |
| Importer `ValueError` paths | count mismatch, missing `sessions`, missing field, provenance collision — all raise |
| `grep -v '^\s*#' arena/import_legacy_results.py \| grep -c 'evaluator'` | **0** (D-08) |
| `grep -v '^\s*#' arena/import_legacy_results.py \| grep -c 'from arena'` | **0** |

## Known Stubs

None. The `"unknown"` / `false` provenance values in `summary.json` are not stubs — they are the honest, deliberate declaration that run A's producing HEAD, catalog digest, and dataset digest were never recorded. Plan 01-08 supersedes this record with a fully fingerprinted `experiments/baselines/run-a`.

## Threat Flags

None. No network endpoint, auth path, or schema at a trust boundary was introduced. The two boundaries this plan touches (untracked disk → git index; `results.json` → committed record) are both in the plan's threat register and both mitigated as specified: T-01-05 and T-01-08 by the scoped negation proven with exit status, T-01-07 by `json.loads`-only parsing with pre-write field validation, T-01-01 by the explicit provenance-gap fields.

## User Setup Required

None — no external service configuration required. Note for the operator: the untracked repo-root `results.json` was backed up to the session scratchpad before any command ran, and remains byte-identical to the original.

## Next Phase Readiness

- Plans 01-02 through 01-09 can now import `arena` and compute against `experiments/baselines/anchor-legacy/` without a catalog download, an artifact build, or a 190 s evaluation run.
- `tests/test_arena_boundary.py` (plan 01-02) will scan `arena/import_legacy_results.py`; it is already clean of harness and intra-package imports.
- Plan 01-08 should write `experiments/baselines/run-a` with complete provenance and mark this record superseded — the `provenance` string already names that successor.
- No blockers.

---
*Phase: 01-measurement-rig-core*
*Completed: 2026-08-30*
