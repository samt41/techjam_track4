---
phase: 01-measurement-rig-core
plan: 11
subsystem: arena-statistics
tags: [bootstrap, confidence-interval, percentile, gap-closure, MEAS-04]
requires:
  - arena/statistics.py (paired_bootstrap, _require_resamples)
provides:
  - arena/statistics.py::percentile_indices
  - arena/statistics.py::MINIMUM_RESAMPLES
affects:
  - arena/adjudication.py (BootstrapResult.lower/.upper feed every adjudication row's reported CI)
  - arena/leaderboard.py (the committed report's `95% CI` column)
tech-stack:
  added: []
  patterns: [efron-tibshirani-percentile-convention, boundary-validation, pure-auditable-helper]
key-files:
  created: []
  modified:
    - arena/statistics.py
    - tests/test_arena_statistics.py
decisions:
  - "Percentile interval indices use the Efron-Tibshirani (R+1) denominator, not R, making the two bounds mirror images and the span at-or-above nominal at every admissible resample count"
  - "MINIMUM_RESAMPLES = 40 is a representability floor, not a span floor: below R=39 a 2.5% tail cannot be expressed and the function would silently return the full replicate range"
  - "percentile_indices is public rather than private so the suite and a future auditor assert indices directly instead of inferring them from an interval"
  - "BCa remains rejected; this plan did not revisit that decision"
metrics:
  tasks: 2
  commits: 2
  tests-before: 339
  tests-after: 345
  completed: 2026-08-31
---

# Phase 01 Plan 11: Bootstrap Percentile Interval Correctness Summary

Replaced the asymmetric, sub-nominal bootstrap percentile indices in
`arena/statistics.py` with a symmetric Efron-Tibshirani `(R+1)` convention exposed as
the public pure helper `percentile_indices`, and added a `MINIMUM_RESAMPLES = 40`
representability floor that fails loudly instead of silently returning a degenerate
interval.

## What Changed

**`arena/statistics.py`**

- Added `MINIMUM_RESAMPLES = 40` beside `RESAMPLE_COUNT`, commented with *why* the
  floor sits there: a 2.5% tail is representable only when `1 / (R + 1) <= 0.025`,
  i.e. only when `R >= 39`. Below that both indices clamp to the extremes and the
  function returns the full replicate range whatever confidence was asked for — the
  failure mode that made the pre-fix "97.5th percentile" literally the *minimum*
  replicate at `R=2`.
- Added private `_LOWER_QUANTILE = 0.025` / `_UPPER_QUANTILE = 0.975` so the
  confidence level appears once rather than as four magic numbers inside an index
  expression.
- Added `percentile_indices(resamples: int) -> tuple[int, int]` — public, pure, no
  side effects. Calls `_require_resamples` first so the floor is enforced on every
  entry path. `lower = max(0, floor(0.025 * (R + 1)) - 1)`,
  `upper = min(R - 1, ceil(0.975 * (R + 1)) - 1)`. The clamps are documented as
  defensive only: above the floor neither can bind.
- Replaced `_require_resamples` so it rejects `resamples < MINIMUM_RESAMPLES` with
  `"resample count must be at least 40"`. It stays module-private and is still called
  from both `paired_bootstrap` and `paired_permutation`.
- Replaced the `lower=` / `upper=` arguments in the `BootstrapResult` construction
  with a single `percentile_indices(resamples)` call made once before construction.
  The BCa-rejection comment is untouched and still adjacent.

**`tests/test_arena_statistics.py`**

Added `PercentileIntervalTest` with six methods (five specified plus the
point-estimate containment assertion the plan asked for):

| Method | Property |
|---|---|
| `test_production_indices_are_pinned_at_ten_thousand` | `(249, 9750)` — the committed report's CI cannot move unannounced |
| `test_indices_are_symmetric_at_every_admissible_resample_count` | `lower == R - 1 - upper` over 8 counts |
| `test_nominal_coverage_is_never_below_ninety_five_percent` | span `>= 0.95 * R` over 1,161 counts, with a non-vacuity guard asserting the loop ran more than 1,000 times |
| `test_the_minimum_resample_count_yields_the_full_range` | `(0, 39)` at the floor and `(1, 77)` at `R=79`, documenting where the full-range region ends |
| `test_a_resample_count_below_the_floor_is_rejected` | `ValueError` from `percentile_indices`, `paired_bootstrap` and `paired_permutation` alike |
| `test_the_interval_contains_the_point_estimate` | `lower <= delta <= upper` at `TEST_RESAMPLES`, guarded by `standard_error > 0` so it cannot pass vacuously on a degenerate replicate distribution |

`TEST_RESAMPLES` is unchanged at 500 and the pinned `2000` in
`test_permutation_floor` is untouched. No existing test asserted the old
`"resample count must be at least one"` message and no caller anywhere in the
repository passes a resample count below 200, so no existing test needed weakening or
adjusting to accommodate the new floor.

## Numerical Impact

**Only `ci_lower` and `ci_upper` move.** `standard_error` is still
`statistics.pstdev(deltas)` over the identical replicate list, computed from an
unchanged RNG stream, so every downstream quantity derived from it is *numerically
identical*: MDD, sigma-hat, `expected_max_of_k`, `winners_curse_correction`,
`corrected_delta`, and the practical-floor verdict. `delta`, `resamples`,
`RESAMPLE_COUNT`, `ZERO_VARIANCE_TOLERANCE`, `_TIE_TOLERANCE` and `MDD_MULTIPLIER`
are all unchanged. `paired_permutation`'s p-value arithmetic was not touched.

At `R=10,000` the reported interval moves from order statistics `(250, 9749)` —
2.51% from the bottom, 97.50% from the top, spanning 9,500 replicates (94.99%) — to
`(249, 9750)`, spanning 9,502 (95.02%) with the two bounds equidistant from their
ends. The committed leaderboard's `95% CI` column will therefore be very slightly
wider on regeneration; that regeneration is a separate plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded a new comment that tripped an acceptance gate**

- **Found during:** Task 2
- **Issue:** The docstring comment I first wrote for `PercentileIntervalTest` said
  "No Agent, no SQLite, no catalog", which made
  `grep -c 'Agent' tests/test_arena_statistics.py` return `1` instead of the required
  `0`. The gate exists to prove the test module carries no retrieval-engine
  dependency, and the comment asserting that fact was itself the only match — a
  false positive on my own prose, not a real dependency.
- **Fix:** Reworded to "Nothing here touches the retrieval engine, SQLite or the
  catalog", preserving the meaning. Gate now returns `0`.
- **Files modified:** `tests/test_arena_statistics.py`
- **Commit:** `eca2359`

No other deviations. No architectural changes, no authentication gates, no package
installs.

## Verification

| Check | Result |
|---|---|
| `percentile_indices(10000), (500), (200), (40)` | `(249, 9750) (11, 488) (4, 195) (0, 39)` |
| Symmetry over `(40, 41, 97, 200, 500, 999, 2000, 10000)` | `True` |
| Coverage `>= 0.95 * r` over `range(40, 1201)` | `True` |
| `MINIMUM_RESAMPLES` | `40` |
| `percentile_indices(39)` | exits non-zero, `ValueError: resample count must be at least 40` |
| `grep -c 'int(0.025 * resamples)'` / `'int(0.975 * resamples) - 1'` (comments stripped) | `0` / `0` |
| `grep -c 'percentile_indices' arena/statistics.py` | `2` |
| `RESAMPLE_COUNT, ZERO_VARIANCE_TOLERANCE, MDD_MULTIPLIER` | `10000 1e-12 2.801585218112968` — unchanged |
| `grep -c 'Agent' tests/test_arena_statistics.py` | `0` |
| `uv run python -m unittest tests.test_arena_statistics` | 45 tests, OK (39 before) |
| `uv run python -m unittest tests.test_arena_adjudication` | 25 tests, OK |
| `uv run python -W error::ResourceWarning -m unittest discover -s tests` | 345 tests, OK (339 baseline, +6 new) |

**Mutation check executed and reverted.** Restoring
`lower = int(0.025 * resamples)` / `upper = int(0.975 * resamples) - 1` inside
`percentile_indices` failed `test_production_indices_are_pinned_at_ten_thousand`
(`(250, 9749) != (249, 9750)`), plus the symmetry, coverage and full-range tests.
After reverting, `git diff --stat -- arena/statistics.py` was empty.

## Threat Model Coverage

| Threat ID | Disposition | Status |
|---|---|---|
| T-01-26 (a "95% CI" without 95% coverage) | mitigate | Closed — `(R+1)` convention plus `test_nominal_coverage_is_never_below_ninety_five_percent` over 1,161 counts |
| T-01-27 (caller-supplied `resamples` degenerating the interval) | mitigate | Closed — `MINIMUM_RESAMPLES` enforced in `_require_resamples`, rejection asserted on all three public entry points |
| T-01-04 (non-reproducible interval) | mitigate | Unchanged — `percentile_indices` is a pure integer function of `resamples`, no RNG |
| T-01-20 (report generated at a reduced resample count) | mitigate | Strengthened — a too-cheap run now fails rather than answers |
| T-01-SC (package installs) | accept | Zero packages installed; no import added beyond the already-present `math` |

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path, file access pattern or schema change; the
only caller-supplied value remains an integer resample count, now validated at the
boundary.

## Self-Check: PASSED

- `arena/statistics.py` — FOUND, modified
- `tests/test_arena_statistics.py` — FOUND, modified
- `.planning/phases/01-measurement-rig-core/01-11-SUMMARY.md` — FOUND
- Commit `b1ed919` — FOUND
- Commit `eca2359` — FOUND
