---
phase: 01-measurement-rig-core
plan: 03
subsystem: measurement
tags: [metrics, rounding-order, anchor, binomial, jsonl, path-containment, stdlib]

# Dependency graph
requires: ["01-01"]
provides:
  - "`arena/metrics.py` — the evaluator metric chain transcribed with its rounding ORDER intact, reproducing the MEAS-16 anchor to 6 dp from session rows alone"
  - "`arena/store.py` — canonical read/write/fingerprint/publish for `experiments/baselines/` records, with run ids that cannot escape their output root"
  - "`tests/arena_fixtures.py` — shared arena fixtures and the deterministic synthetic large-effect control"
  - "`tests/test_arena_metrics.py` — 33 tests pinning the anchor, the HR@K curve, and the per-scenario sigma"
  - "`SessionOutcome` as the typed row every later arena module reads"
affects: [01-05, 01-06, 01-07, 01-08, 01-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Evaluator metric chain transcribed, never imported (D-08); cross-agreement is the evidence (D-06)"
    - "Rounding order is load-bearing: efficiency consumes the rounded mttc and is itself returned unrounded"
    - "Per-bucket sigma from the bucket's OWN observed p (D-15), never a global p"
    - "Untrusted JSONL validated row-by-row at the boundary; `ArenaStoreError` chained and naming file + line"
    - "Path containment (`is_relative_to`) as defence in depth behind the run-id allow-list"

key-files:
  created:
    - arena/metrics.py
    - arena/store.py
    - tests/arena_fixtures.py
    - tests/test_arena_metrics.py
  modified: []

key-decisions:
  - "Added a fail-closed empty guard to `hit_rate_curve` — the plan specified one for `metric_summary` only, but the curve divides by `len(sessions)` and would raise `ZeroDivisionError` instead of a domain error"
  - "Documented the D-17 non-linearity honestly: TechnicalScore is affine in the three component means and efficiency's clamp cannot bind, so the ONLY divergence is 6 dp rounding (~6.7e-7) — the assertion holds, but the test says why rather than implying a large structural effect"
  - "Left `REQUIREMENTS.md` untouched — three wave-2 agents share it, so the orchestrator owns that write"
  - "`sha256_file` on the evaluator doubles as a standing immutability check on the scoring harness"

patterns-established:
  - "Arena fixtures live in `tests/arena_fixtures.py` (no `test_` prefix, no `TestCase`), keeping `tests/fixtures.py` reserved for catalog/artifact construction"
  - "Float comparison discipline: exact `==` only for 6-dp-rounded outputs and exact small-integer quotients; `assertAlmostEqual` everywhere a subtraction or an unrounded value is involved"

requirements-completed: [MEAS-01, MEAS-02, MEAS-03, MEAS-09, MEAS-16]

# Metrics
duration: 12min
completed: 2026-08-30
---

# Phase 01 Plan 03: Metric Chain and Baselines Store Summary

**The evaluator's metric chain now exists independently inside `arena/`, reproducing run A's `0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884` to six decimal places from the committed 200 session rows alone — with no agent constructed, no catalog, no artifact, and a 0.06 s test run instead of 190 s.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3
- **Files created:** 4 (no existing file modified)
- **Test suite:** 167 → 200 tests, all green

## Accomplishments

- **The Layer-2 reproduction anchor of D-01 holds.** Two independent code paths now agree on the same six figures. `experiments/run_public.py` stays frozen (D-06) and `metric_summary` is transcribed rather than imported (D-08), so the agreement is evidence rather than tautology. `AnchorReproductionTest` asserts the recomputed aggregates against the committed `summary.json` field by field.
- **The rounding ORDER is what makes it reproduce, and it is now pinned by test.** `efficiency` consumes the already-rounded `mttc` and is itself returned *unrounded*, exactly as `local_evaluator.py:279-280` does; the evaluator rounds it only at output (`:286`). That is why `efficiency()` legitimately returns `0.7575000000000001` while `summary.json` legitimately says `0.7575`. Both forms are asserted, and the exact-equality trap is called out in a comment so nobody "fixes" it later.
- **HR@1/@3/@5/@10 = `0.385 / 0.59 / 0.715 / 0.92`** (counts 77 / 118 / 143 / 184 of 200), derived from `best_rank` alone — no per-turn trace, which is what keeps a retained record at ~26 KB rather than ~10,400 events.
- **Every scenario row carries its own n and its own sigma.** `boundary` n=10 σ=0.094868 and `intent_override` n=30 σ=0.054772 are flagged `decision_grade=False`; `browsing` and `buying` at n=80 are flagged True.
- **The synthetic large-effect control is deterministic and analytically pinned.** File-order promotion needs no RNG. Verified: `+0.011931` at m=10 and `+0.085214` at m=77, with HR@10 and MTTC provably invariant and ΔTS = 0.30·ΔMRR — a true-positive check that costs zero evaluation time.
- **Both trust boundaries in the register are mitigated as specified.** T-01-07: `json.loads` only, explicit coercion, per-row `validate()`, `ArenaStoreError` chained and naming file + line. T-01-06: the `run_public.py` allow-list plus a resolved-path containment assertion.

## Task Commits

1. **Task 1: Transcribe the evaluator metric chain** — `5709b83` (feat)
2. **Task 2: Build the baselines store adapter** — `5ca14a5` (feat)
3. **Task 3: Shared arena fixtures and the MEAS-16 anchor test module** — `329b762` (test)

## Verification Results

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_metrics` | **33 tests, OK, 0.058 s** |
| `uv run python -W error::ResourceWarning -m unittest` | **200 tests, OK** (167 baseline + 33 new) |
| Anchor aggregates from rows alone | `200 / 0.92 / 0.524466 / 3.425 / 0.76884` — exact |
| `efficiency` on the anchor | `0.7575000000000001`; `round(...,6) == 0.7575` |
| RUNS.md 4 dp agreement | `round(mrr,4)==0.5245`, `round(ts,4)==0.7688` — after explicit rounding only |
| HR@K curve / counts | `{1:0.385, 3:0.59, 5:0.715, 10:0.92}` / `77,118,143,184` |
| Per-scenario order | `boundary, browsing, buying, intent_override` (n = 10/80/80/30) |
| Per-scenario σ | `0.094868 / 0.024367 / 0.033541 / 0.054772`; grade `F/T/T/F` |
| Promotion control | `+0.011931000000000025` (m=10), `+0.08521400000000001` (m=77) |
| `grep -cE '^(from\|import) (evaluator\|starter\|experiments\|arena)'` on `metrics.py` | **0** |
| `grep -c 'evaluator'` on non-comment `store.py` | **0** (D-08) |
| `grep -c 'Agent'` on the test module | **0** |
| `grep -c 'starter'` on `arena_fixtures.py` | **0** |
| `grep -c 'delta == 0.011931\|delta == 0.085214'` | **0** (forbidden form absent) |
| `uv run python -m unittest -v tests.arena_fixtures` | **Ran 0 tests** (discovery correctly skips it) |
| `sha256_file('evaluator/local_evaluator.py')` | `84ea8997…1b30` — matches the plan, harness unmodified |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree spawned at a stale base commit**

- **Found during:** startup, before any edit
- **Issue:** The worktree HEAD was `9faf85c`, which `git merge-base` showed to be an *ancestor* of the expected base `46a93be` — so plan 01-01's wave-1 output, including `experiments/baselines/anchor-legacy/`, was absent. Every anchor test in Task 3 would have failed on a missing file.
- **Fix:** HEAD was verified on the correct `worktree-agent-*` branch and the working tree was clean, so `git reset --hard 46a93be` moved the base forward safely. No protected ref was touched and no `git update-ref` was used.
- **Verification:** `git rev-parse HEAD` returns `46a93be`; the anchor record is present and all 200 rows load.

**2. [Rule 2 - Missing Critical] Empty-input guard added to `hit_rate_curve`**

- **Found during:** Task 1
- **Issue:** The plan specified a fail-closed empty guard for `metric_summary` but not for `hit_rate_curve`, which divides by `len(sessions)`. On an empty tuple it would raise a bare `ZeroDivisionError` — an untyped failure at the same contract boundary the `metric_summary` guard exists to protect.
- **Fix:** `raise ValueError("hit rate curve requires at least one session")`, matching the sibling function's message shape.
- **Files modified:** `arena/metrics.py`
- **Commit:** `5709b83`

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** No scope creep, no acceptance criterion changed. Deviation 1 is environmental. Deviation 2 closes a gap the plan's own convention implies.

## Issues Encountered

- **The D-17 non-linearity is smaller than the plan implies, and the test now says so.** The plan asked for a session set where the mean of per-session TechnicalScores differs from the score recomputed over the whole set. It does differ, and the assertion passes — but on investigation the gap is only ~6.7e-7, because TechnicalScore is *affine* in the three component means and `efficiency`'s `max/min` clamp can never bind (`mttc` is confined to `[1, 11]` by construction, hitting the clamp boundaries exactly and never crossing them). So 6 dp output rounding is the sole source of divergence. The assertion is kept as specified and is fully deterministic, but its comment states the real cause rather than implying a large structural effect. **This matters downstream:** anyone sizing the bootstrap should know the recompute-vs-average error is ~1e-6, not ~1e-2 — the recompute path is still correct and still required, but it is not rescuing a large bias.
- **One plan literal is off in its last digit.** The plan quotes `binomial_standard_error(0.92, 200)` as `0.01918332609325088`; the computed value is `0.019183326093250873`. They agree to `places=12`, which is the comparison the plan itself mandates, so the test passes as written. Flagged only so a future reader does not treat the plan's literal as byte-exact.
- **`experiments/RUNS.md` is not self-consistent read at face value** — as plan 01-01 also found. `0.5*0.92 + 0.3*0.5245 + 0.2*0.7575 = 0.76885`, which displays as `0.7689`, not RUNS.md's `0.7688`. Agreement is asserted only after explicit rounding of the full-precision values, and the test carries a comment explaining why the exact form is a guaranteed false failure.

## Known Stubs

None. All four files are complete and fully exercised; every exported symbol named in the plan's artifact table exists and is under test.

## Threat Flags

None beyond the plan's register. No network endpoint, credential path, or new schema at a trust boundary was introduced. The two boundaries this plan touches are both mitigated as specified: T-01-07 (`load_sessions` — `json.loads` only, explicit coercion, per-row validation, chained `ArenaStoreError` naming file and line) and T-01-06 (`resolve_run_directory` — allow-list plus resolved-path containment, tested with the allow-list deliberately widened so the containment check is proven load-bearing on its own). T-01-11 is mitigated by `AnchorReproductionTest` asserting agreement with the independently produced `summary.json`.

## Notes for the Orchestrator

- `REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` were deliberately **not** modified. Three wave-2 agents share those files; MEAS-01, MEAS-02, MEAS-03, MEAS-09 and MEAS-16 are ready to be marked complete centrally after the merge.
- Plans 01-02 and 01-04 own `arena/evaluator_bridge.py`, `tests/test_arena_boundary.py`, `arena/candidate.py` and `tests/test_arena_candidate.py`; none were created or edited here. `arena/metrics.py` and `arena/store.py` contain zero `evaluator` references, so 01-02's boundary scan will pass over them either way.

## Next Phase Readiness

- `SessionOutcome`, `metric_summary`, `technical_score` and `load_sessions` are the inputs plans 01-05 (statistics), 01-07 (leaderboard) and 01-08 (run capture) build on, all provable against real data with no evaluation run.
- **Note for 01-07:** `efficiency()` returns the unrounded value by design. `arena/leaderboard.py` must apply `round(..., 6)` itself before writing it to a file, or the published number will read `0.7575000000000001`.
- No blockers.

## Self-Check: PASSED

All four claimed files exist and are tracked; all three claimed commits (`5709b83`, `5ca14a5`, `329b762`) are present in `git log`.

---
*Phase: 01-measurement-rig-core*
*Completed: 2026-08-30*
