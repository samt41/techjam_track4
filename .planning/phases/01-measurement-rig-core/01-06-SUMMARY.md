---
phase: 01-measurement-rig-core
plan: 06
subsystem: measurement
tags: [adjudication, win-rule, winners-curse, practical-floor, verdict, determinism, stdlib]

# Dependency graph
requires: ["01-04", "01-05"]
provides:
  - "`arena/adjudication.py` — the D-20 five-step ordering, the D-23 three-part win rule, and the MEAS-07 floor tested against the MEAS-08-corrected delta"
  - "`classify_verdict` — the entire four-clause verdict rule as one injectable pure function, so the rare powered-null branch is testable by injection"
  - "`Verdict` — four members, with `BELOW_SHIP_BAR` separating a detected-but-unshippable gain from a null"
  - "`AdjudicationRow` — 23 audited columns including sigma-hat, k and E[max of k] as separate fields, so the correction is re-derivable"
  - "`tests/test_arena_adjudication.py` — 25 tests in 0.66 s, including the D-01 Layer 3 controls"
affects: [01-07, 01-08, 01-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "The verdict rule lives in ONE public pure function with exactly one call site, so the degenerate branch is adjudicated by the same logic as every other row rather than by a hard-coded answer"
    - "`failed_criteria` is built by filtering the `CRITERION_ORDER` constant, never by appending as checks run, so report order is fixed by data rather than by control flow"
    - "The winner's-curse correction is applied to EVERY row at the family's k, not only to the champion"
    - "Two-tier test resample budget (`FAST_RESAMPLES=200` / `STABLE_RESAMPLES=500`) with the SE-noise-versus-fixture-margin calculation recorded in a module comment"

key-files:
  created:
    - arena/adjudication.py
    - tests/test_arena_adjudication.py
  modified: []

key-decisions:
  - "The plan's acceptance criterion 'source contains `corrected_delta >= PRACTICAL_FLOOR` and does NOT contain `delta >= PRACTICAL_FLOOR`' is literally unsatisfiable — the required substring contains the forbidden one. Read as intended (no RAW-delta form) and verified with a word-anchored grep, `grep -oE '[A-Za-z_]*delta >= PRACTICAL_FLOOR'`, which returns exactly one line: `corrected_delta >= PRACTICAL_FLOOR`"
  - "The zero-variance short-circuit states `failed_criteria` explicitly as the plan requires, even though the general path produces the identical tuple — verified by reasoning at the branch and asserted in `test_identical_candidates_are_no_difference_never_a_win`"
  - "The degenerate branch skips the permutation call entirely rather than running it and discarding the result; a permutation on two identical arms returns exactly `(R+1)/(R+1) = 1.0` by construction, so the short-circuit is exact, not an approximation"
  - "`holm_p` is forced to 1.0 on a degenerate row, which is a NO-OP: 1.0 is the largest admissible p, so Holm returns it unchanged. That is what keeps `test_holm_family_excludes_scenarios`'s identity valid even with a degenerate arm in the family"
  - "`test_argument_order_is_fixed_not_symmetric` asserts the standard errors differ rather than that the CI is not a mirror — on this fixture the percentile CI IS an exact mirror (the delta lattice has only four occupied values), so the SE is the only quantity that actually evidences a different replicate stream"
  - "Added a non-vacuity guard to the cross-process reproducibility test: two empty stdouts are also byte-identical"
  - "Left `REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` untouched — the orchestrator owns those writes after the wave merges"

patterns-established:
  - "A tripwire test is verified by deliberately mutating the implementation and observing the failure, then reverting — not by assuming the assertion is sensitive"
  - "Any assertion that could pass on empty output carries an explicit non-vacuity guard beside it"

requirements-completed: [MEAS-07, MEAS-08]

# Metrics
duration: 22min
completed: 2026-08-30
---

# Phase 01 Plan 06: Adjudication Policy Summary

**The rig can now say "no" four different ways and mean something different by each — and the one ordering error that would have let selection bias buy a shipping decision is held down by a tripwire that was verified to fail against a deliberately broken implementation, not merely assumed to be sensitive.**

## Performance

- **Duration:** ~22 min
- **Tasks:** 3
- **Files created:** 2 (no existing file modified)
- **Test suite:** 266 → 291 tests, all green in 4.17 s
- **This module:** 25 tests in **0.66 s** (budget: ≥25 methods, <15 s)

## Accomplishments

- **The floor is provably applied to the corrected delta.** `test_floor_is_applied_to_the_corrected_delta` was run against a deliberate mutation (`clears_practical_floor = bootstrap.delta >= PRACTICAL_FLOOR`) and **failed** with `AssertionError: True is not False`; the mutation was then reverted and `git diff --stat` confirmed clean. The fixture is twelve sessions at rank 2 with one promoted to rank 1: raw delta `0.0125` clears the `0.01` floor, corrected delta `0.005571` sits **44% below** it — far outside the ~3.2% SE noise at `STABLE_RESAMPLES`.
- **A detected-but-small gain cannot be summarised as "no difference".** The `_SMALL_*` fixture is calibrated to exactly `+0.006`: `holm_p = 0.004975`, `failed_criteria == ("practical_floor",)`, verdict `significant, below ship bar`. The test asserts explicitly that this is **not** `NO_DIFFERENCE`.
- **`WIN` is exactly equivalent to an empty `failed_criteria`.** `test_win_is_exactly_equivalent_to_empty_failed_criteria` sweeps 6 × 4 × 3 × 3 = 216 combinations of `holm_p`, `delta`, `mdd` and `failed_criteria` and asserts the biconditional on every one. That is the identity plan 01-09 will assert against the committed leaderboard.
- **All four verdict branches are exercised, including the one that cannot be built from session data.** `NO_DIFFERENCE` via the powered null is reached by injection in microseconds; the plan's reasoning (a ≥2.8-sigma effect that is simultaneously Holm-non-significant needs an unconstructably large family) is recorded on the method.
- **`NOT_DETECTABLE` is reachable end to end, not only by injection.** Two hundred sessions at rank 4 with exactly one moved to rank 3 gives `delta 0.000125` against `MDD 0.000361` — the null is correctly reported as uninformative.
- **The degenerate pair is provably not a win.** Identical arms give exact `0.0` for delta, both CI bounds, SE and MDD; exactly `1.0` for both p-values; `failed_criteria == ("holm_significance", "practical_floor")`; `exchange_rate_ok is True`; verdict `no difference`.
- **The exchange rate is tested in both directions on the same trade.** Two misses plus a rank promotion at n=100 gives `mttc_delta = 0.18`, so the bar is `0.0667 × 0.18 = 0.012006`. At `mrr_delta = +0.010` the trade fails (`exchange_rate_ok False`, `hr10_exchange_rate` named); at `+0.030` it clears. The failing arm fails all three criteria and reports them in `CRITERION_ORDER` order.
- **Both Layer-3 anchor controls pass.** m=10: `delta 0.011931000000000025`, `holm_p 0.007984`, `corrected == delta` exactly (k=1), `MDD 0.010563` — 13% headroom — verdict `win` with `failed_criteria == ()`. m=77: `delta 0.08521400000000001`, verdict `win`. True negative: `no difference`, `permutation_p == 1.0`, `MDD == 0.0`.
- **Determinism is verified across processes.** Two children at `PYTHONHASHSEED=0` and `1` print byte-identical 780-byte serialized adjudications, each passing `resamples=200` explicitly so neither falls back to the 10,000 default.

## Task Commits

1. **Task 1: Implement the D-20 ordering and the adjudication row** — `95052b5` (feat)
2. **Task 2: Prove the ordering, the floor, the win rule, and every verdict branch** — `4eabb95` (test)
3. **Task 3: Layer-3 adjudication controls and byte-level reproducibility** — `eb13dbe` (test)

## Verification Results

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_adjudication` | **25 tests, OK, 0.658 s** (budget: ≥25 methods, <15 s) |
| `uv run python -m unittest -v tests.test_arena_boundary` | **8 tests, OK, 0.018 s** |
| `uv run python -W error::ResourceWarning -m unittest` | **291 tests, OK, 4.173 s** (266 baseline + 25 new) |
| `arena/adjudication.py` line 1 | `from __future__ import annotations` |
| `grep -v '^\s*#' arena/adjudication.py \| grep -cE '(evaluator\|starter\.\|experiments\.)'` | **0** |
| `grep -c 'classify_verdict(' arena/adjudication.py` | **2** (definition + single call site) |
| `grep -oE '[A-Za-z_]*delta >= PRACTICAL_FLOOR'` | **`corrected_delta >= PRACTICAL_FLOOR`** only |
| Constants | `PRACTICAL_FLOOR 0.01`, `SIGNIFICANCE_ALPHA 0.05`, `EXCHANGE_RATE_PER_MTTC 0.0667`, `CRITERION_ORDER ('holm_significance', 'practical_floor', 'hr10_exchange_rate')` |
| `tuple(Verdict)` | `WIN`, `BELOW_SHIP_BAR`, `NO_DIFFERENCE`, `NOT_DETECTABLE` → `'win'`, `'significant, below ship bar'`, `'no difference'`, `'not detectable'` |
| `adjudicate(baseline, ())` | `ValueError: adjudication requires at least one candidate` |
| Candidate fingerprint equal to baseline's | `ValueError: a candidate must not share the baseline's fingerprint` |
| Candidate with a differing `sample_id` sequence | `ValueError: paired comparison requires identical sample_id ordering` (raised by `_require_paired`) |
| Floor fixture | raw `0.012500`, SE `0.012281`, `E[max of 2] 0.564190`, corrected **`0.005571`**, `clears_practical_floor False` |
| Floor tripwire under the raw-delta mutation | **FAILS** — `AssertionError: True is not False` (reverted; `git diff --stat` clean) |
| Below-ship-bar fixture | `delta 0.006000`, `holm_p 0.004975`, `failed_criteria ('practical_floor',)`, verdict `significant, below ship bar` |
| Win fixture | `delta 0.120000`, `holm_p 0.004975`, floor `True`, exchange rate `True`, `failed_criteria ()` |
| Exchange rate, underpaid | `hr -0.02`, `mrr +0.010` vs bar `0.012006` → `exchange_rate_ok False`, all three criteria named in order |
| Exchange rate, paid | `hr -0.02`, `mrr +0.030` vs bar `0.012006` → `exchange_rate_ok True`, `hr10_exchange_rate` absent |
| k=1 | `expected_max_of_k == 0.0`, `corrected_delta == delta` exactly |
| k=3 | every row `candidate_count == 3`, `correction_k == 3`, `expected_max_of_k == expected_max_of_k(3)` |
| Champion tie-break | two arms on identical sessions give an exactly equal delta; the lexicographically smaller fingerprint wins |
| m=10 anchor control | `delta 0.011931000000000025`, `holm_p 0.007984`, `MDD 0.010563`, `corrected == delta`, verdict `win`, `failed_criteria ()` |
| m=77 anchor control | `delta 0.08521400000000001`, verdict `win` |
| Anchor true negative | verdict `no difference`, `permutation_p == 1.0`, `MDD == 0.0` |
| Anchor near-null (one session rank 4→3) | `delta 0.000125`, `MDD 0.000320 > abs(delta)`, verdict not `win` |
| Synthetic near-null at n=200 | `delta 0.000125`, `MDD 0.000361`, verdict `not detectable` end to end |
| Every row's MDD | `== arena.statistics.minimum_detectable_difference(row.standard_error)` exactly, and `2.801585218112968 × SE` to 12 places |
| Cross-process determinism | `PYTHONHASHSEED=0` and `=1` children print byte-identical 780-byte output |
| `FAST_RESAMPLES` / `STABLE_RESAMPLES` | `200` / `500`; no test passes `RESAMPLE_COUNT` |
| `grep -c 'Agent' tests/test_arena_adjudication.py` | **0** |
| `grep -c 'delta == 0.011931\|delta == 0.085214'` | **0** (forbidden exact form absent) |
| `grep -cE 'run.?B\|run.?C'` | **0** (no real-run significance assertion) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree spawned at a stale base commit**

- **Found during:** startup, before any edit
- **Issue:** Worktree HEAD was `9faf85c`, an *ancestor* of the required base `5a1a2c2`, so waves 1-3 output — including `arena/statistics.py` and `arena/candidate.py`, this plan's two direct dependencies — was absent. Every task would have failed on a missing import. This is the same environmental fault 01-05 recorded.
- **Fix:** HEAD was confirmed on the `worktree-agent-*` branch with a clean tree, then `git reset --hard 5a1a2c22fff9e748f022e9245ed318da49de5b94`. No protected ref was touched and no `git update-ref` was used.
- **Verification:** `git rev-parse HEAD` returns `5a1a2c2`; `arena/statistics.py`, `arena/candidate.py` and `arena/metrics.py` all present.

**2. [Rule 1 - Bug] An acceptance criterion that no implementation can satisfy**

- **Found during:** Task 1 acceptance check
- **Issue:** The plan requires the source to contain `corrected_delta >= PRACTICAL_FLOOR` **and** to not contain `delta >= PRACTICAL_FLOOR`. The first string contains the second as a substring, so a literal `grep -c` on the second returns `1` for any conforming implementation. The criterion is unsatisfiable as written.
- **Fix:** Read as intended — the RAW-delta form is what is forbidden — and verified with a word-anchored grep, `grep -oE '[A-Za-z_]*delta >= PRACTICAL_FLOOR'`, which returns exactly one line: `corrected_delta >= PRACTICAL_FLOOR`. The invariant is genuinely enforced; only the check was defective. The behavioural tripwire (deviation-free mutation test above) is the stronger evidence and it passes.
- **Files modified:** none (check corrected, not code)

**3. [Rule 2 - Missing Critical] Non-vacuity guard on the cross-process reproducibility test**

- **Found during:** Task 3
- **Issue:** `assertEqual(child("0"), child("1"))` passes just as happily on two empty stdouts as on two real adjudications. If a future change made the child print nothing while still exiting zero, the strongest determinism assertion in the phase would silently become a no-op.
- **Fix:** `assertIn('"verdict"', first)` beside the equality. The child's real output was confirmed to be a 780-byte JSON record.
- **Files modified:** `tests/test_arena_adjudication.py`
- **Commit:** `eb13dbe`

---

**Total deviations:** 3 auto-fixed (1 blocking, 1 defective check, 1 missing critical)
**Impact on plan:** No scope creep and no acceptance criterion weakened. Deviation 1 is environmental; 2 corrects a check, not a behaviour, and the behaviour is separately proven by mutation; 3 closes a vacuous-pass hole.

## Issues Encountered

- **The plan's `test_argument_order_is_fixed_not_symmetric` premise needed sharpening.** The intended evidence was "a different replicate stream". On the small fixture the percentile CI turns out to be an *exact* mirror under swapping (`(-upper, -lower)`), because the delta lattice has only four occupied values at n=12 — so a mirror-inequality assertion would have failed against correct code. The standard errors do differ (`0.012732` forward, `0.011414` reverse), so that is what the test asserts. The seed inequality is asserted structurally beside it.
- **Correction (gap closure, plan 01-10): the degenerate short-circuit was NOT redundant with the general path.** The claim recorded here at the time was: *"The degenerate short-circuit is redundant with the general path, deliberately. Every value the plan asks the guard to set — `permutation_p 1.0`, `holm_p 1.0`, `mdd 0.0`, `corrected_delta == delta`, `clears_practical_floor False`, `failed_criteria ("holm_significance", "practical_floor")` — is exactly what the general path produces when SE is `0.0`. The guard is kept because the detectability check is not redundant: without it `abs(delta) >= mdd` reads `0 >= 0` as True."*

  **That claim was false as shipped.** It was disproven by executed reproduction against the checked-in code, on a uniform rank-2 to rank-1 promotion over 200 sessions. The guard produced `verdict = no difference` with `permutation_p = 1.0` asserted and `clears_practical_floor = False` beside a `corrected_delta` of `0.15`. The general path, on the identical fixture, produced a measured `permutation_p` of `0.0004997501249375312`, `clears_practical_floor = True`, `failed_criteria = ()` and `verdict = WIN`. The guard did not agree with the general path — it **inverted the verdict**, turning a decisive win into a null. The error in the original reasoning was treating *"the delta does not move under resampling"* as *"there is no delta"*: the bootstrap SE is zero for ANY exactly-uniform per-session improvement, not only for two identical arms, and a uniform improvement is precisely the case where the delta is large and real.

  **What plan 01-10 changed.** Degeneracy is now conditioned on the delta as well as the standard error, so a uniform improvement no longer qualifies. The short-circuit is gone; every field on every adjudication row is measured on the general path. The narrowed flag survives only as the descriptive `is_degenerate` payload field, which feeds no decision. The claim's one correct half — that two identical arms yield `no difference` — is now true **by construction rather than by assertion**, since the general path measures `permutation_p = 1.0` for them, which is what truth 8 requires.
- **The permutation p is not at its floor on the m=10 control.** At `STABLE_RESAMPLES=500` it is `0.007984` (three exceedances out of 500), not `1/501`. That is a genuine reading, not a floor artefact — worth noting because 01-05 recorded the m=77 control landing exactly on the floor at R=2000, and a reader comparing the two numbers should not conclude the m=10 result is weaker than it is.
- **`R = 10,000` remains justified by p-value-floor resolution and percentile-CI stability, not by bias correction.** Inherited from 01-05 and not restated as anything stronger anywhere in this module. Nothing here claims the resample count corrects the ~7e-7 recompute-versus-average gap.
- **No BCa, no new tie tolerance.** This module compares deltas only through a sort key (`(-delta, fingerprint)`), which resolves exact lattice ties deterministically without needing a tolerance, so `_TIE_TOLERANCE` stays private to `arena/statistics.py`.
- **`ALLOWED_OVERRIDES` was not extended**, as instructed. Every test arm uses `overrides=()` or the existing keys.

## Known Stubs

None. Every symbol in the plan's artifact table exists and is exercised: `PRACTICAL_FLOOR`, `SIGNIFICANCE_ALPHA`, `EXCHANGE_RATE_PER_MTTC`, `CRITERION_ORDER`, `Verdict`, `CandidateArm`, `AdjudicationRow`, `classify_verdict`, `adjudicate`, and all six required test classes (`OrderingTest`, `WinRuleTest`, `VerdictRuleTest`, `DegenerateTest`, `Layer3ControlTest`, `ReproducibilityTest`).

## Threat Flags

None beyond the plan's register. The module is a pure transform over frozen dataclasses — no network endpoint, credential path, filesystem write, or schema at a trust boundary. The nine register rows are mitigated as shipped:

| Threat ID | Mitigation as shipped |
|---|---|
| T-01-14 | `clears_practical_floor = corrected_delta >= PRACTICAL_FLOOR`; the raw form is absent under a word-anchored grep; the tripwire was **observed** to fail under a deliberate raw-delta mutation |
| T-01-14b | Zero-variance short-circuit at `standard_error <= ZERO_VARIANCE_TOLERANCE`, stating `failed_criteria` explicitly and reaching `NO_DIFFERENCE` through the general rule; asserted as `verdict is not Verdict.WIN` |
| T-01-14c | `failed_criteria` filtered from `CRITERION_ORDER`; the 216-combination sweep asserts win-iff-empty |
| T-01-14d | `Verdict.BELOW_SHIP_BAR` exists for exactly `holm_p < alpha` with a failed floor or exchange rate; the `+0.006` fixture asserts it is not `NO_DIFFERENCE` |
| T-01-14e | The verdict rule is an injectable pure function; the rare powered-null clause is tested by injection, so no unconstructable fixture was attempted |
| T-01-13 | `standard_error`, `candidate_count`, `correction_k` and `expected_max_of_k` are four separate `AdjudicationRow` fields, all present in `as_record()` |
| T-01-04 | `pair_seed` over both fingerprints with a per-procedure label; byte-identical serialization asserted in-process and across two `PYTHONHASHSEED` values, with a non-vacuity guard |
| T-01-15 | No `run B` / `run C` significance assertion exists; the grep criterion returns `0` |
| T-01-SC | Zero packages installed; `dataclasses` and `enum` only |

## Notes for the Orchestrator

- `REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` were deliberately **not** modified. **MEAS-07 and MEAS-08** are ready to be marked complete centrally after the merge.
- Only two files were touched, both new: `arena/adjudication.py` (351 lines) and `tests/test_arena_adjudication.py` (555 lines). Nothing owned by a sibling plan was created or edited; `tests/arena_fixtures.py` was reused unchanged.
- `arena/adjudication.py` contains zero non-comment `evaluator` / `starter.` / `experiments.` references, so 01-02's AST boundary scan passes over it — confirmed by running `tests.test_arena_boundary` directly.
- **The stale-worktree-base fault recurred** (`9faf85c` instead of `5a1a2c2`), exactly as the prompt warned and as 01-05 also hit. It is environmental and recurring, not plan-specific.

## Next Phase Readiness

- **For 01-07 (leaderboard):** `AdjudicationRow.as_record()` is the row contract — 23 keys, `verdict` already a string and `failed_criteria` already a list, so the leaderboard can serialize it directly. Print `standard_error`, `correction_k` and `expected_max_of_k` as three separate columns (01-05's instruction, now backed by three real fields); without them a reader cannot tell the correction was applied. Remember `efficiency()` is still unrounded upstream — `arena/leaderboard.py` owns the `round(..., 6)`.
- **For 01-09:** the identity to assert is `(verdict == "win") == (failed_criteria == [])` on the committed leaderboard. It is enforced in one place (`classify_verdict` clause 1) and swept over 216 combinations here, and the degenerate short-circuit was written specifically so it cannot be violated by the one branch that bypasses the general path.
- **Cost at production R:** this module's 25 tests run at R=200/500 in 0.66 s. A single-candidate adjudication at `RESAMPLE_COUNT = 10,000` over 200 sessions costs roughly 5 s (bootstrap plus permutation, both resample-then-recompute), so a five-candidate leaderboard invocation is on the order of 25 s — inside the ~60 s the VALIDATION doc budgeted.
- No blockers.

## Self-Check: PASSED

Both claimed files exist and are tracked (`arena/adjudication.py`, `tests/test_arena_adjudication.py`); all three claimed commits (`95052b5`, `4eabb95`, `eb13dbe`) are present in `git log`; `git diff --diff-filter=D 5a1a2c2 HEAD` reports no deletions; the working tree is clean.

---
*Phase: 01-measurement-rig-core*
*Completed: 2026-08-30*
