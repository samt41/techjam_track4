---
phase: 01-measurement-rig-core
plan: 05
subsystem: measurement
tags: [statistics, bootstrap, permutation, holm, mdd, winners-curse, determinism, stdlib]

# Dependency graph
requires: ["01-03"]
provides:
  - "`arena/statistics.py` — paired bootstrap (percentile CI), paired permutation (Phipson-Smyth floor), Holm-Bonferroni with monotonicity enforcement, MDD, and the order-statistic winner's-curse correction"
  - "`exact_paired_sign_flip_p_value` — the exhaustive reference that pins the two-sided tail convention"
  - "`pair_seed` — content-derived, per-procedure RNG seeding (D-24)"
  - "`tests/test_arena_statistics.py` — 39 D-01 Layer 1 known-answer tests in 0.80 s"
affects: [01-06, 01-07, 01-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One index vector per replicate applied to BOTH arms; `_require_paired` makes an unpaired comparison impossible to express"
    - "Resample-then-recompute `technical_score(metric_summary(...))` per replicate, never an average of per-session scores (D-17)"
    - "Percentile CI, with BCa's rejection recorded in code so it is not 'upgraded' later"
    - "Content-seeded `random.Random(seed)` instances; zero `random.seed()` calls"
    - "Running maximum over the sorted sequence as Holm's monotonicity enforcement, stable input-index tie-break"

key-files:
  created:
    - arena/statistics.py
    - tests/test_arena_statistics.py
  modified: []

key-decisions:
  - "Added a `resamples >= 1` guard to both resampling routines — the plan did not specify one, but `deltas[int(0.025 * 0)]` on an empty list is an IndexError rather than a domain error at the same contract boundary `_require_paired` protects"
  - "The Pitfall 3 tripwire fixture sets `reciprocal_rank` directly rather than deriving it from `best_rank`, because a constant per-session improvement has no expression in reciprocal ranks (1/r is not closed under +0.05); the baseline deliberately alternates a strong and a weak session so its own resampling variance is non-zero — without that, an unpaired implementation would also produce a narrow interval and the tripwire would not bite"
  - "The tripwire was empirically verified to FAIL under a deliberately written two-index-vector implementation (correlated width 0.0484 vs uncorrelated 0.0494), rather than merely asserted to be sensitive"
  - "The D-17 comment in the bootstrap tripwire states the ~7e-7 magnitude honestly, inheriting 01-03's finding rather than implying a large structural effect"
  - "Left `REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` untouched — wave-3 agents share them, so the orchestrator owns those writes"

patterns-established:
  - "Statistical routines carry their rejected alternative in a comment beside the chosen one (BCa beside percentile, Blom beside Simpson), so a future reader cannot 'improve' the module back into a known failure"
  - "A timing assertion takes the best of three runs before comparing against its bound, so a loaded machine cannot flake it"

requirements-completed: [MEAS-04, MEAS-05, MEAS-06, MEAS-08]

# Metrics
duration: 18min
completed: 2026-08-30
---

# Phase 01 Plan 05: Resampling Engine Summary

**The engine that decides every Phase 3/4/5 bake-off now exists as 327 lines of stdlib numerics with 39 analytically-pinned tests behind it, running in 0.80 s — and its two silent failure modes, the unpaired bootstrap and the non-monotone Holm adjustment, each have a tripwire that was verified to fail against a deliberately broken implementation rather than merely assumed to be sensitive.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 3
- **Files created:** 2 (no existing file modified)
- **Test suite:** 227 → 266 tests, all green in 3.48 s

## Accomplishments

- **Paired resampling refuses unpaired input structurally.** `_require_paired` raises unless both arms present an identical `sample_id` sequence, so MEAS-04's join is a precondition rather than a convention. One index vector per replicate is applied to both arms, and the comment at that line records the measured cost of getting it wrong (`0.003715` paired vs `0.025922` unpaired).
- **The Pitfall 3 tripwire is proven, not assumed.** Before writing it, a deliberately unpaired two-index-vector implementation was run against the same fixture: correlated CI width `0.048` against uncorrelated `0.049`, so `width_correlated < width_uncorrelated / 3` is **False** and the test fails loudly. Under the correct paired implementation the ratio is `1.5e-15`.
- **A Monte-Carlo permutation p can never be reported as `0.0`.** The Phipson-Smyth `(c+1)/(R+1)` convention is applied, and on the m=77 control at R=2000 the p-value lands *exactly* on the floor `0.0004997501249375312 == 1/2001` — the most extreme case this data can produce sits at the floor rather than beneath it.
- **The tail convention is pinned against a hand-checkable exact answer.** `exact_paired_sign_flip_p_value((0.10, 0.20, 0.30, -0.05))` returns exactly `0.25`: only `{}`, `{-0.05}`, `{0.10, 0.20, 0.30}` and the full set out of 16 sign assignments are at least as extreme as the observed mean `0.1375`.
- **`E[max of k]` reproduces its closed forms to zero measured error.** Simpson at 2,000 panels returns `0.5641895835477563` and `0.8462843753216345` — bit-identical to `1/sqrt(pi)` and `3/(2*sqrt(pi))` — in 0.74 ms. Blom's approximation is carried only as a cross-check and the test asserts it agrees to `3e-2` while *not* agreeing to `1e-6`, so the reason it is not the implementation is an executable fact.
- **Both guaranteed outcomes hold.** True positive: the m=10 synthetic control gives `delta = 0.011931000000000025` against `MDD = 0.010065` with a CI of `(0.00525, 0.01882)` excluding zero. True negative: identical candidates give exact `0.0` for delta, both CI bounds, SE and MDD, and exactly `1.0` for the permutation p.
- **Determinism is verified, not asserted.** Two identically seeded invocations produce equal `BootstrapResult` values and byte-identical `json.dumps(..., sort_keys=True)` output. `grep -c 'random.seed('` returns `0`.

## Task Commits

1. **Task 1: Paired bootstrap and paired permutation over TechnicalScore** — `28d6ae7` (feat)
2. **Task 2: Holm-Bonferroni, MDD, and the order-statistic winner's-curse correction** — `9277ce1` (feat)
3. **Task 3: The D-01 Layer 1 known-answer fixture suite** — `8373bb3` (test)

## Verification Results

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_statistics` | **39 tests, OK, 0.798 s** (budget: ≥24 methods, <8 s) |
| `uv run python -m unittest -v tests.test_arena_boundary` | **8 tests, OK, 0.017 s** |
| `uv run python -W error::ResourceWarning -m unittest` | **266 tests, OK, 3.477 s** (227 baseline + 39 new) |
| `arena/statistics.py` line 1 | `from __future__ import annotations` |
| `grep -v '^\s*#' arena/statistics.py \| grep -cE '(evaluator\|starter\.\|experiments\.)'` | **0** |
| `grep -c 'random.seed(' arena/statistics.py` | **0** |
| `RESAMPLE_COUNT` | `10000` |
| `Z_ALPHA_TWO_SIDED` / `Z_POWER_80` / `MDD_MULTIPLIER` | `1.9599639845400536` / `0.8416212335729144` / `2.801585218112968` |
| Degenerate pair | `delta/lower/upper/se/mdd == 0.0`; `p_value == 1.0` |
| m=10 control | `delta 0.011931000000000025`, SE `0.0035929087`, MDD `0.010065`, CI `(0.005250, 0.018819)` |
| m=77 control | `delta 0.08521400000000001`, SE `0.0076388`, CI `(0.071609, 0.100205)` |
| HR@10 / MTTC across the m=10 arms | `0.92 / 3.425` both arms; MRR `0.524466 → 0.564238` |
| Permutation floor at R=2000 (m=77) | `p == 0.0004997501249375312 == 1/2001` exactly |
| `exact_paired_sign_flip_p_value((0.10,0.20,0.30,-0.05))` | `0.25` exact |
| Holm fixtures | `(0.03,0.06,0.06)` / `(0.003,0.6,0.6)` / `(0.06,0.06,0.06)` / `(0.6,0.03,0.04)` |
| `expected_max_of_k(2)` / `(3)` / `(5)` / `(10)` | `0.5641895835477563` / `0.8462843753216345` / `1.1629644736405196` / `1.5387527308351732` — **0.0 error against every reference** |
| `expected_max_of_k(10)` runtime | **0.74 ms** (bound: 10 ms) |
| Blom error at k=2..10 | `2.53e-2` down to `7.9e-3` — within `3e-2`, outside `1e-6` |
| Pairing tripwire, correct implementation | correlated width `1.1e-16`, uncorrelated `0.0729`, ratio `1.5e-15` |
| Pairing tripwire, deliberately unpaired implementation | correlated `0.0484` vs uncorrelated `0.0494` → assertion **False** (tripwire bites) |
| Near-null pair (one session rank 4→3) | `p == 1.0 > 0.05`, `MDD == 0.000367 > 0` (MEAS-06) |
| `grep -c 'Agent' tests/test_arena_statistics.py` | **0** |
| `grep -c 'delta == 0.011931\|delta == 0.085214'` | **0** (forbidden exact form absent) |
| `arena.statistics.statistics is importlib.import_module("statistics")` | **True** |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree spawned at a stale base commit**

- **Found during:** startup, before any edit
- **Issue:** Worktree HEAD was `9faf85c`, an *ancestor* of the expected base `6545e88`, so waves 1-2 output — including `arena/metrics.py`, this plan's sole dependency — was absent. Every task would have failed on a missing import.
- **Fix:** HEAD was confirmed on the `worktree-agent-*` branch with a clean tree, then `git reset --hard 6545e88`. No protected ref was touched and no `git update-ref` was used.
- **Verification:** `git rev-parse HEAD` returns `6545e88`; `arena/metrics.py` present.

**2. [Rule 2 - Missing Critical] `resamples >= 1` guard added to both resampling routines**

- **Found during:** Task 1
- **Issue:** The plan specified no lower bound on `resamples`. At `resamples=0` the delta list is empty and `deltas[int(0.025 * 0)]` raises a bare `IndexError` — an untyped failure at exactly the contract boundary `_require_paired` exists to protect. (`resamples=1` and `2` are fine: the negative upper index wraps to the single element.)
- **Fix:** `_require_resamples` raises `ValueError("resample count must be at least one")`, matching the sibling guard's message shape.
- **Files modified:** `arena/statistics.py`
- **Commit:** `28d6ae7`

**3. [Rule 1 - Bug] `grep -c 'random.seed('` returned 1 on the first draft**

- **Found during:** Task 1 acceptance check
- **Issue:** A comment reading `# instance, never random.seed() (D-24)` contained the literal the acceptance criterion greps for, so the criterion failed on a comment rather than on code. The criterion is a real invariant and the check should stay strict; the comment was the defect.
- **Fix:** reworded to `# an instance, never the module-global RNG (D-24)`.
- **Files modified:** `arena/statistics.py`
- **Commit:** `28d6ae7`

---

**Total deviations:** 3 auto-fixed (1 blocking, 1 missing critical, 1 bug)
**Impact on plan:** No scope creep, no acceptance criterion weakened. Deviation 1 is environmental; 2 closes a gap the plan's own convention implies; 3 keeps a static check honest.

## Issues Encountered

- **The plan's resample-count justification does not rest on a large D-17 non-linearity, and this SUMMARY says so explicitly** (as the upstream 01-03 finding requested). The recompute-vs-average gap is ~7e-7, because TechnicalScore is affine in the three component means and `efficiency`'s clamp cannot bind. The resample-then-recompute path is still correct and still required — a shortcut would inject that error into all 10,000 replicates — but `R = 10,000` is justified by the Monte-Carlo resolution of the p-value floor (`1/(R+1) = 9.999e-5`) and by percentile-CI stability, **not** by any bias correction. The D-17 tripwire test carries this reasoning in its comment.
- **Rounding happens before resampling, deliberately.** `technical_score` rounds to 6 dp and consumes an already-rounded `mttc`, and every replicate goes through that same chain. The alternative — resampling unrounded quantities and rounding once at the end — would produce a statistic the evaluator never computes. The consequence is that the delta distribution is lattice-valued at a 1e-6 pitch (this is also, per Pitfall 4, part of why BCa is uncomputable here), and the residual float error in the synthetic-control deltas (`0.011931000000000025`) is a direct product of subtracting two independently rounded scores. `_TIE_TOLERANCE = 1e-12` exists precisely because exact ties on that lattice are common and a bare `>=` on raw floats would drop roughly half of them.
- **`efficiency()` remains unrounded and nothing in this module rounds it.** Per the 01-03 note, `arena/leaderboard.py` (plan 01-07) must apply `round(..., 6)` before writing it out.
- **The timing assertion is min-of-three.** The plan's criterion is "under 10 ms for k=10". A single-shot `perf_counter` assertion is a flake source on a loaded Windows box, so the test takes the best of three runs. Measured best: 0.74 ms — 13× headroom either way.
- **`assertNotAlmostEqual(..., places=6)` is used for the Blom non-agreement check.** `assertNotAlmostEqual` has no `delta`/`places` conflict here, but note it asserts *rounding to 6 dp differs*, which at a 2.5e-2 error is unambiguous.

## Known Stubs

None. Every exported symbol named in the plan's artifact table exists, is exercised, and reproduces an analytically known answer. All seven required test classes are present (`PairingTest`, `BootstrapTest`, `PermutationTest`, `HolmTest`, `MinimumDetectableDifferenceTest`, `ExpectedMaximumTest`, `SeedDeterminismTest`).

## Threat Flags

None beyond the plan's register. No network endpoint, credential path, filesystem write, or new schema at a trust boundary was introduced — the module is a pure transform over frozen dataclasses. The seven register rows are mitigated as specified:

| Threat ID | Mitigation as shipped |
|---|---|
| T-01-04 | `pair_seed` SHA-256 over both fingerprints plus a procedure label; `random.Random(seed)` instances only (`grep -c 'random.seed('` = 0); `SeedDeterminismTest` asserts byte-identical serialized output |
| T-01-04b | `_require_paired` raises on any unpaired call; one index vector applied to both arms; the CI-width tripwire verified to fail under a two-vector implementation |
| T-01-04c | `(c+1)/(R+1)`; the floor asserted at `1/2001` with R pinned; the exact enumeration pins the tail convention at `0.25` |
| T-01-04d | Running maximum with a stable input-index tie-break; the `(0.60, 0.01, 0.02)` fixture fails a non-monotone implementation |
| T-01-10 | `RESAMPLE_COUNT` is a module constant with no CLI surface; a test pins it at `10_000`; the `resamples` keyword is documented as test-only |
| T-01-13 | Documented at `winners_curse_correction` with the 0.003→0.0035/0.0046 figures and the POS-04 threshold comparison |
| T-01-SC | Zero packages installed; `hashlib`, `itertools`, `math`, `random`, `statistics` only |

## Notes for the Orchestrator

- `REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` were deliberately **not** modified. MEAS-04, MEAS-05, MEAS-06 and MEAS-08 are ready to be marked complete centrally after the merge.
- Only two files were touched, both new: `arena/statistics.py` and `tests/test_arena_statistics.py`. Nothing owned by a sibling wave-3 plan was created or edited, and `tests/arena_fixtures.py` was reused unchanged as 01-03 intended.
- `arena/statistics.py` contains zero non-comment `evaluator` / `starter.` / `experiments.` references, so plan 01-02's AST boundary scan passes over it — confirmed by running `tests.test_arena_boundary` directly.

## Next Phase Readiness

- **For 01-06 (adjudication):** `BootstrapResult`, `PermutationResult`, `holm_bonferroni` and `minimum_detectable_difference` are the inputs the verdict policy consumes. Two facts the verdict function must encode are already established here: (a) the degenerate pair returns `se == 0.0`, so `abs(delta) >= mdd` evaluates `0 >= 0` → `True` and **must** be short-circuited by a `ZERO_VARIANCE_TOLERANCE` branch (Pitfall 5 — the constant is exported for exactly this); (b) `abs(delta) >= MDD` is roughly a 2.8-sigma effect whose permutation p is ~0.005, so an at-MDD-but-Holm-non-significant row is rare by construction and its fixture must be injected, not built from session data. Both are documented in code at `minimum_detectable_difference`.
- **For 01-07 (leaderboard):** print sigma-hat, `k` and `E[max of k]` as three separate audited columns — the correction is `SE * E[max of k]` and the SE is the **paired-difference** SE (0.002-0.008), an order of magnitude below the 0.019 absolute HR@10 binomial SE quoted in PROJECT.md. Without the separate columns a reader concludes the correction was not applied.
- **Cost at production R:** the m=77 permutation ran 2,000 replicates over 200 sessions in 0.126 s, so a full `RESAMPLE_COUNT = 10_000` bootstrap-plus-permutation pair costs roughly 1.5 s — an order of magnitude cheaper than the ~60 s the VALIDATION doc budgeted for a leaderboard invocation.
- No blockers.

## Self-Check: PASSED

Both claimed files exist and are tracked (`arena/statistics.py`, `tests/test_arena_statistics.py`); all three claimed commits (`28d6ae7`, `9277ce1`, `8373bb3`) are present in `git log`; the working tree is clean.

---
*Phase: 01-measurement-rig-core*
*Completed: 2026-08-30*
