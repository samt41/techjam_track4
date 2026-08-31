---
phase: 01-measurement-rig-core
plan: 10
subsystem: arena-adjudication
tags: [statistics, verdict-rule, gap-closure, mutation-tested]
requires:
  - arena/statistics.py
  - arena/metrics.py
  - arena/candidate.py
provides:
  - "D-23 exchange-rate criterion that fires on mttc_delta < 0"
  - "fabrication-free AdjudicationRow: every field measured on one path"
  - "AdjudicationRow.is_degenerate (descriptive-only column)"
  - "written, tested WR-05 answer on Holm family membership"
affects:
  - arena/leaderboard.py
tech-stack:
  added: []
  patterns:
    - "one code path per row; no special-case branch may assert a value another column contradicts"
    - "mutation testing as the acceptance evidence for a guard clause, not grep presence"
key-files:
  created: []
  modified:
    - arena/adjudication.py
    - tests/test_arena_adjudication.py
decisions:
  - "A degenerate arm REMAINS in the Holm family and in correction_k: the family is a property of the experimental design, and shrinking it post hoc is a data-dependent family definition"
  - "is_degenerate is reported but never acted on; Pitfall 5 is handled by classify_verdict clause 4, not by a branch"
  - "mrr_delta > 0.0 is retained despite being logically redundant given abs(), as an explicit statement of intent -- documented as redundant so no reader mistakes it for a second guard"
metrics:
  duration: "~1h (wall clock spans a provider rate-limit pause)"
  completed: 2026-08-31
  tasks: 3
  commits: 3
  tests_before: 339
  tests_after: 346
---

# Phase 01 Plan 10: Adjudication Verdict Repair Summary

Repaired both reproducible false verdicts `01-VERIFICATION.md` recorded against
`arena/adjudication.py` — the sign-inverted D-23 exchange-rate criterion and the
value-fabricating zero-variance branch — and closed the two adjudication-side warnings
(WR-13, WR-05) that live in the same region of source.

## What changed

**Task 1 (`c3fbd51`) — the D-23 exchange-rate criterion.** `exchange_rate_ok` now reads
`hit_rate_delta >= 0.0 or (mrr_delta > 0.0 and mrr_delta > EXCHANGE_RATE_PER_MTTC *
abs(mttc_delta))`. Because `mttc_delta = candidate_mttc - baseline_mttc`, an MTTC
improvement is negative and the un-absoluted bar went negative with it, so a *negative*
`mrr_delta` satisfied the comparison. The local criteria mapping `failures` was renamed
`passed` (WR-13); every value it holds is `True` on a pass, so the old name inverted its
own meaning inside the function that decides every verdict. `EXCHANGE_RATE_PER_MTTC`,
`PRACTICAL_FLOOR`, `SIGNIFICANCE_ALPHA`, `CRITERION_ORDER` and `classify_verdict` are
untouched. No HR@10 regression-size floor and no size-scaled forgiveness were added —
both were explicitly declined.

**Task 2 (`655b579`) — no emitted field is a fabricated constant.** Four edits:

1. Degeneracy is now conditioned on the bootstrap delta as well as its standard error.
   Bootstrap SE is exactly zero for *any* exactly-uniform per-session improvement, so SE
   alone also captured real, large effects.
2. `paired_permutation` runs unconditionally, once per candidate. Identical arms reach
   `1.0` by Phipson-Smyth measurement — the same number the old guard asserted.
3. The `if is_degenerate:` branch is deleted. `holm_p`, the MDD, `corrected_delta`,
   `clears_practical_floor`, `exchange_rate_ok`, `passed` and `failed_criteria` are
   computed exactly once, unconditionally.
4. `AdjudicationRow.is_degenerate: bool` added immediately after `standard_error`, with
   the matching `as_record()` key. Descriptive only — it is derived from two measured
   quantities and never overrides another field. Row field count 23 → 24.

The WR-05 answer is recorded beside `holm_bonferroni(...)` and beside `correction_k`, with
all four reasons.

**Task 3 (`b94a98e`) — regression tests.** `ExchangeRateSignTest` (3 methods) and
`ZeroVarianceTest` (4 methods), 25 → 32 methods in the module, 0.95 s.

## Verification

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_adjudication` | 32 tests, OK, 0.95 s |
| `uv run python -m unittest -v tests.test_arena_boundary` | 8 tests, OK |
| `uv run python -W error::ResourceWarning -m unittest discover -s tests` | **346 tests, OK, 4.69 s** (339 baseline + 7 new) |
| `ReproducibilityTest` incl. `PYTHONHASHSEED` 0 vs 1 | 3 tests, OK |
| `ci_lower\|ci_upper` count in the test module | 1 before, 1 after — unchanged, as required |
| `grep -c 'Agent' tests/test_arena_adjudication.py` | 0 |
| `AdjudicationRow` field list | 24 fields, `is_degenerate` immediately after `standard_error` |

**Grep criteria, verified in BOTH directions** against `git show e00e747:arena/adjudication.py`.
A one-sided grep can pass on untouched source, so every gate was run against the pre-fix
file as well:

| Criterion | Pre-fix | Post-fix | Required |
|---|---|---|---|
| `abs(mttc_delta)` | 0 | 1 | 1 |
| `mrr_delta > 0.0` | 0 | 1 | 1 |
| `EXCHANGE_RATE_PER_MTTC * mttc_delta` | 1 | 0 | 0 |
| `failures` | 2 | 0 | 0 |
| `passed[` | 0 | 1 | 1 |
| `abs(result.delta) <= ZERO_VARIANCE_TOLERANCE` | 0 | 1 | 1 |
| `if degenerate[index]` | 1 | 0 | 0 |
| `if is_degenerate` | 1 | 0 | 0 |
| field assigned a literal (regex) | 3 | 0 | 0 |
| `hit_rate_delta` regression-size floor | 0 | 0 | 0 |

Every gate discriminates. All counts are over comment-stripped source (`grep -v '^\s*#'`)
where the plan specifies it.

**Behavioural checks (executed):**

- Uniform rank-2 → rank-1 over 200 sessions at `resamples=500`: `is_degenerate False`,
  `delta 0.15000000000000002`, `standard_error 0.0`, `permutation_p 0.001996007984031936`
  (exactly `1/501`), `corrected_delta 0.15000000000000002`, `clears_practical_floor True`,
  `failed_criteria ()`, `verdict win`. Pre-fix this was `no difference`.
- Identical arms: `is_degenerate True`, `permutation_p 1.0` (measured), `mdd 0.0`,
  `corrected_delta 0.0`, `clears_practical_floor False`,
  `failed_criteria ('holm_significance', 'practical_floor')`, `verdict no difference`.
  Truth 8 survives, now through the general path.
- `test_floor_is_applied_to_the_corrected_delta` still passes at `correction_k == 2`.

## Mutation testing

Three mutations were applied and reverted; `git diff --stat arena/adjudication.py` was
confirmed empty after each.

| Mutation | Tests failed |
|---|---|
| `abs(mttc_delta)` → `(mttc_delta)` | 1 — `test_an_mrr_gain_below_the_magnitude_bar_does_not_buy_an_hr10_regression` |
| remove `and abs(result.delta) <= ZERO_VARIANCE_TOLERANCE` | 1 — `test_uniform_improvement_is_not_reported_as_no_difference` |
| remove `mrr_delta > 0.0 and` | **0** |

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 1 — Bug] The plan's mutation-check acceptance criterion names the wrong test,
and the source comment it mandated asserts something false**

- **Found during:** Task 3, executing the mutation checks.
- **Issue:** The plan states that `test_double_regression_with_an_mttc_gain_is_not_a_win`
  must FAIL when `abs(` is removed, and instructs the Task 1 comment to record that "both
  new clauses are load-bearing and neither substitutes for the other." Both are false.
  The CR-02 reproducer has `mrr_delta = -0.01`, which fails `mrr_delta > 0.0` regardless
  of `abs()`, so that test cannot detect the `abs(` mutation. More substantively, because
  the bar `EXCHANGE_RATE_PER_MTTC * abs(mttc_delta)` is non-negative, `mrr_delta > bar`
  already implies `mrr_delta > 0.0` — the two clauses are not independent, and executing
  the `mrr_delta > 0.0 and` deletion failed **zero** tests.
- **Fix:** Kept the implementation exactly as the plan mandates (both clauses present, so
  the `grep -c 'mrr_delta > 0.0'` gate still returns 1) and corrected the comments to
  state what is true: `abs()` is the load-bearing change; `mrr_delta > 0.0` is logically
  redundant and retained deliberately as a statement of intent that survives a future
  change to the bar's sign convention, explicitly flagged so no reader mistakes it for a
  second guard. The same correction is recorded on
  `test_an_mrr_gain_below_the_magnitude_bar_does_not_buy_an_hr10_regression`, which is the
  sole guard for the `abs(` mutation. The substantive requirement — each blocker fix is
  mutation-verified by a named test — is met, by the correct test.
- **Files modified:** `arena/adjudication.py`, `tests/test_arena_adjudication.py`
- **Commit:** `b94a98e`

**2. [Rule 3 — Blocking] Underpaid/paid fixtures built on `_MTTC_TRADE_BASELINE` rather
than a second `turn=3` baseline**

- **Found during:** Task 3, fixture calibration.
- **Issue:** The plan suggests calibrating `_MTTC_TRADE_UNDERPAID_GAIN` and
  `_MTTC_TRADE_PAID_GAIN` "from a `turn=3` baseline", which would require a seventh
  module fixture not present in the plan's declared artifact table.
- **Fix:** Pulling 5 of 100 sessions forward from the declared `turn=8` baseline gives
  `mttc_delta = -0.32` — the identical magnitude bar of `0.021344` — so both fixtures reuse
  `_MTTC_TRADE_BASELINE` and the declared fixture list is satisfied exactly. The plan
  explicitly delegates this ("the exact rank tuple is yours to choose"; the properties are
  asserted in the tests as non-vacuity guards).
- **Files modified:** `tests/test_arena_adjudication.py`
- **Commit:** `b94a98e`

**3. [Rule 2 — Missing coverage] Added `_WIN_UNIFORM_PROMOTED`**

- **Found during:** Task 3, writing `test_no_row_field_is_a_fabricated_constant`.
- **Issue:** The plan asks that test to run "over a mixed adjudication that includes a
  degenerate arm". A family of {real effect, identical arm} omits the shape that actually
  caused CR-01 — zero SE with a non-zero delta — and all arms in one family must share the
  baseline's `sample_id` sequence, so the 200-session `_UNIFORM_*` pair cannot join a
  50-session family.
- **Fix:** Added `_WIN_UNIFORM_PROMOTED = sessions_from_ranks((1,) * 50)` so the family
  covers all three shapes.
- **Files modified:** `tests/test_arena_adjudication.py`
- **Commit:** `b94a98e`

## Known follow-ups (not in scope, not fixed)

- `AdjudicationRow.as_record()` now emits an `is_degenerate` key, so the committed
  `experiments/baselines/leaderboard.json` no longer carries every key a freshly generated
  payload would. No test regenerates the committed adjudication rows (they are read from
  disk, and `arena/leaderboard.py` selects keys by name), so the suite is unaffected and
  `test_the_committed_markdown_matches_the_committed_payload` still passes. The committed
  report should be regenerated by the operator step at R=10,000 before the phase is
  re-verified. The `exploration-tail-only` row's `permutation_p` of `1.0` and `mdd` of
  `0.0` — the one live fabricated row the verifier flagged — are now reproduced by
  measurement, so regeneration will change only the added key.
- `arena/statistics.py` percentile index arithmetic (WR, plan 01-11) is untouched by
  design; no new test asserts a `ci_lower` / `ci_upper` value, so there is no conflict.

## Threat Flags

None. No new network endpoint, credential, filesystem write, deserialization or trust
boundary was introduced; the module remains a pure transform over frozen dataclasses. All
`mitigate` dispositions in the plan's threat register (T-01-22, T-01-23, T-01-24, T-01-25,
T-01-14, T-01-14b, T-01-04) are implemented and each has a named test. T-01-SC holds:
zero packages installed, `dependencies = []` unchanged, no import outside the standard
library and `arena.*`.

## Self-Check: PASSED

- `arena/adjudication.py` — FOUND, modified
- `tests/test_arena_adjudication.py` — FOUND, modified
- Commit `c3fbd51` — FOUND
- Commit `655b579` — FOUND
- Commit `b94a98e` — FOUND

No stubs, no `TODO`/`FIXME`/`PLACEHOLDER` markers introduced. STATE.md and ROADMAP.md
deliberately not modified — worktree mode; the orchestrator owns those writes.
