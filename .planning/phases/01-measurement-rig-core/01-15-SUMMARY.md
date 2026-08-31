---
phase: 01-measurement-rig-core
plan: 15
subsystem: arena-reporting
tags: [leaderboard, technical-score, per-scenario, regeneration, auditability, gap-closure]
requires: ["01-10", "01-11", "01-12", "01-13", "01-14"]
provides:
  - per-scenario TechnicalScore in the leaderboard payload and rendered table
  - regenerated committed report produced by the repaired rig at R=10,000
  - re-established byte-identical regeneration property (SC3)
  - prose record reconciled with the regenerated numbers
  - corrected false claim at 01-06-SUMMARY.md:153, with its disproof attached
affects:
  - arena/leaderboard.py
  - tests/test_arena_leaderboard.py
  - experiments/baselines/leaderboard.json
  - experiments/LEADERBOARD.md
  - experiments/RUNS.md
  - .planning/phases/01-measurement-rig-core/01-06-SUMMARY.md
tech-stack:
  added: []
  patterns:
    - composite metric added at the output boundary, never inside the evaluator transcription
    - two-sided grep gate verification against unmodified source before implementing
    - disproof re-executed rather than transcribed before being written into the record
key-files:
  created:
    - .planning/phases/01-measurement-rig-core/01-15-SUMMARY.md
  modified:
    - arena/leaderboard.py
    - tests/test_arena_leaderboard.py
    - experiments/baselines/leaderboard.json
    - experiments/LEADERBOARD.md
    - experiments/RUNS.md
    - .planning/phases/01-measurement-rig-core/01-06-SUMMARY.md
decisions:
  - The per-scenario composite lives in arena/leaderboard.py, not arena/metrics.py, so the module's evaluator-transcription claim stays true
  - The rendered pairwise adjudication table stays at fourteen columns; is_degenerate is disclosed as a payload field rather than rendered
  - HOW_TO_READ states the n-weighting rule that is true, not the "no weighting combines" claim the plan directed, which is false
  - The scenario header tuple is wrapped one entry per line; at nine entries the single-line spelling exceeds the file's width
requirements-completed: [MEAS-01, MEAS-07]
metrics:
  tasks: 4
  commits: 4
  tests-added: 4
  tests-total: 374
  completed: 2026-08-31
---

# Phase 01 Plan 15: Per-Scenario TechnicalScore and Report Regeneration Summary

Closed the last SC1 gap by adding a per-scenario TechnicalScore column, then regenerated
the committed report at R=10,000 so every number it prints was produced by the repaired
rig — and corrected a disclosure the plan itself had specified incorrectly.

## What Was Built

**Task 1 — the column and the disclosures** (`bfde32d`). Every `scenario_breakout` row
gained a `technical_score` key, computed as `technical_score(scenario.summary)` at the
leaderboard's output boundary. `arena/metrics.py` was deliberately not modified: that
module is a transcription of the evaluator's own metric chain, the evaluator emits no
per-scenario composite, and adding one there would have made the transcription claim
false while burying a presentation choice inside the module whose agreement with the
evaluator is the phase's validation evidence. The "Per-scenario breakout" table widened
from eight columns to nine, `TechnicalScore` between `MTTC` and `binomial sigma`, so the
metric quartet reads in the same order as the Candidates table. Three new HOW_TO_READ
disclosures were added and the block's opening sentence was updated from "three numbers"
to seven items.

**Task 2 — regeneration** (`2f634f1`). Both artifacts regenerated from the five committed
records with the documented invocation, at the default `RESAMPLE_COUNT = 10_000`. No
evaluation was re-run, no `Agent` constructed, and nothing under
`experiments/baselines/*/` changed.

**Task 3 — prose reconciliation** (`61746f5`). `experiments/RUNS.md` pointer section
updated; nothing below the `### Historical` heading touched. `01-06-SUMMARY.md:153`
corrected with the original claim quoted and its disproof attached.

## Before / After

### `fallback-lexical` adjudication row

| Field | Before | After | Cause |
|---|---|---|---|
| `ci_lower` | `-0.01888599999999996` | `-0.01889200000000002` | plan 01-11, `(R+1)` convention |
| `ci_upper` | `0.031239000000000017` | `0.03131099999999998` | plan 01-11, `(R+1)` convention |
| `is_degenerate` | *absent* | `False` | plan 01-10, new key |
| `delta` | `0.00611000000000006` | unchanged | — |
| `standard_error` | `0.012845110588600097` | unchanged | — |
| `permutation_p` | `0.6453354664533547` | unchanged | — |
| `holm_p` | `1.0` | unchanged | — |
| `minimum_detectable_difference` | `0.0359866719500484` | unchanged | — |
| `correction_k` | `2` | unchanged | — |
| `expected_max_of_k` | `0.5641895835477563` | unchanged | — |
| `corrected_delta` | `-0.0011370775936071038` | unchanged | — |
| `clears_practical_floor` | `False` | unchanged | — |
| `failed_criteria` | `[holm_significance, practical_floor]` | unchanged | — |
| `verdict` | `not detectable` | unchanged | — |

Exactly as predicted: only the two interval bounds moved. `standard_error` draws from an
unchanged RNG stream, so every winner's-curse quantity is byte-identical.

### `exploration-tail-only` adjudication row

| Field | Before | After | Cause |
|---|---|---|---|
| `permutation_p` | `1.0` (asserted by short-circuit) | `1.0` (**measured**) | plan 01-10 |
| `minimum_detectable_difference` | `0.0` (asserted) | `0.0` (**measured**) | plan 01-10 |
| `is_degenerate` | *absent* | `True` | plan 01-10, new key |
| `delta`, `standard_error`, `holm_p`, `correction_k`, `expected_max_of_k`, `corrected_delta`, `clears_practical_floor`, `failed_criteria`, `verdict` | — | all unchanged | — |

The row the verifier flagged as fabricated now reproduces **by measurement**. Both
previously asserted fields landed on the values they had asserted, because the arm's 200
session outcomes are byte-identical to the baseline's, so every sign-flip ties the
observed statistic and the Phipson-Smyth p is exactly `1.0`. Verdict remains
`no difference`; `failed_criteria` remains `["holm_significance", "practical_floor"]`.

### `assumptions` block

| Key | Before | After | Cause |
|---|---|---|---|
| `holm_family_size` | *absent* | `2` | plan 01-14 |
| `holm_family_includes_degenerate_arms` | *absent* | `True` | plan 01-14 |
| `holm_family` | shorter prose | extended with the design-property rationale | plan 01-14 |
| `resample_count` | `10000` | unchanged | — |
| `practical_floor` | `0.01` | unchanged | — |

### Scenario breakout

All 20 rows gained `technical_score` (Task 1), each strictly in `(0.0, 1.0)`. The
coordinator's independent scalar diff against `d82504f` confirms **24 keys added, 0
removed, 3 changed** — nothing moved that this plan did not predict.

## Prose Reconciliation

Every numeral in the two `RUNS.md` findings bullets was checked against the regenerated
JSON rather than from memory:

| Quantity | JSON (6 dp) | Prose | Match |
|---|---|---|---|
| `ΔTS(A,B)` delta | `0.006110` | `+0.006110` | yes |
| `ΔTS(A,B)` CI | `[-0.018892, 0.031311]` | updated | yes |
| `ΔTS(A,B)` perm p | `0.645335` | `0.645335` | yes |
| `ΔTS(A,B)` Holm p | `1.000000` | `1.000000` | yes |
| `ΔTS(A,B)` MDD | `0.035987` | `0.035987` | yes |
| `ΔTS(A,B)` sigma-hat | `0.012845` | `0.012845` | yes |
| `ΔTS(A,B)` corrected | `-0.001137` | `-0.001137` | yes |
| `ΔTS(A,C)` all fields | `0.000000` / p `1.000000` | unchanged | yes |

Only the CI required a change. The six disclosed changes, per the plan's requirement that
there be six and not five:

1. `(R + 1)` percentile convention moved the interval bounds.
2. Removal of the zero-variance short-circuit made two asserted fields measured.
3. Adjudication rows gained `is_degenerate`.
4. `assumptions` gained `holm_family_size` and `holm_family_includes_degenerate_arms`.
5. The per-scenario table gained a TechnicalScore column.
6. Plan 01-13 changed what an **omitted** override flag means to a fingerprint.

The sixth is disclosed with the verbatim substrings `overrides = {}` and
`byte-identical Agent`, stating in order: run-a stores both flags explicitly because the
pre-fix CLI injected argparse defaults; every committed record still derives exactly the
digest it stores, so re-running each documented invocation still mints its committed
digest; and a future flag-free `run` records `overrides = {}` and mints a different digest
while configuring a byte-identical Agent, so future runs must be compared on the
`overrides` mapping rather than on the digest.

## Deviations from Plan

Both were weighed and accepted by the operator. Per the coordinator's direction, deviation
1 is recorded as a **plan defect**, not as an executor deviation from a correct
instruction.

### 1. [Plan defect] The directed HOW_TO_READ claim was mathematically false

- **Found during:** Task 1, while constructing `test_the_scenario_technical_score_is_bucket_local`.
- **What the plan directed:** that the per-scenario TechnicalScore "is NOT a decomposition
  of the overall score and the four buckets do not combine to it under any weighting,"
  on the stated ground that Efficiency is "a function of a mean rather than a mean of
  per-session values."
- **Why it is false:** every TechnicalScore term is n-weighted-linear across a partition
  of the sessions. HR@10 and MRR are means; the overall mean MTTC *is* the n-weighted mean
  of the bucket MTTCs; and `Efficiency = clip((11 - mean(MTTC)) / 10, 0, 1)` is affine in
  that mean, with its clip inactive because an achievable MTTC lies in `[1, 11]`.
- **Measured on the anchor:** n-weighted `0.7688401` against overall `0.76884` — a `1e-07`
  gap that is 6-dp rounding and nothing else. A flat average gives `0.761956`, off by
  `0.006884`. The coordinator independently confirmed across all five candidates:
  n-weighting reproduces the overall score to between `0.0` and `3.5e-07`; flat-averaging
  is off by `0.006884` to `0.010316`.
- **Resolution:** the disclosure states the true rule — combine by sample-size weighting;
  a flat average understates the score and silently gives the n=10 Boundary bucket eight
  times the influence its evidence supports. Shipping the directed wording would have
  introduced a new false claim into a judge-facing auditability artifact in the same
  commit series that corrects an old one. `test_the_scenario_technical_score_is_bucket_local`
  asserts both directions (n-weighted equality to 6 dp, flat-average inequality by more
  than `0.001`) rather than asserting rounding noise.
- **No acceptance criterion depended on the false wording.** All four required greps still
  pass: `holm_family_size`, `holm_family_includes_degenerate_arms`, `(R + 1)` and
  `payload field` are present.
- **Files:** `arena/leaderboard.py`, `tests/test_arena_leaderboard.py`. **Commit:** `bfde32d`.

### 2. [Plan defect] Task 4's "no commit before approval" criterion is unsatisfiable in worktree mode

- **The criterion:** "`git log --oneline -1 -- experiments/baselines/leaderboard.json`
  shows no commit for this plan until after approval."
- **Why unsatisfiable here:** this plan ran as a parallel executor in a git worktree.
  Uncommitted work is destroyed when the orchestrator removes the worktree, so honoring
  the criterion literally would have discarded the regenerated artifacts and Task 3's
  prose outright.
- **Resolution:** the three artifacts were committed to the throwaway per-agent branch
  `worktree-agent-a142f8add2cf538bb` with the open gate flagged in the commit message, and
  the checkpoint was returned **unresolved** for operator sign-off. The operator took the
  substance-over-letter reading: the gate governs whether the regenerated report becomes
  the committed record, and **merging** is what does that.
- **Fix for future checkpoint tasks:** scope the criterion to the **merge** rather than to
  the commit — e.g. "no merge to the integration branch until approval."

### Accepted without change

The rendered pairwise adjudication table stays at fourteen columns rather than being
widened for `is_degenerate`. Widening was the alternative and would have been mechanically
safe, since Task 2 regenerates both artifacts anyway. It was rejected because the
surrounding disclosure already routes the reader to machine-readable payload keys, the
report's header declares the JSON the source of truth, and a fifteenth column costs
legibility for an auditor who can read the field straight from the payload. Recorded in
HOW_TO_READ so it is not read as an oversight.

## Plan Gate Verification (two-sided)

Every grep gate was measured against unmodified source (`d82504f`) before implementing, per
the known hazard that this project's gates have failed in both directions:

| Gate | On unmodified source | After | Verdict |
|---|---|---|---|
| `grep -c 'technical_score(scenario.summary)'` | `0` | `1` | non-trivial, reachable |
| `grep -c 'TechnicalScore'` | `12` (plan predicted 12) | `18` (≥14) | non-trivial, reachable |
| `grep -cF 'technical_score=_cell(item["technical_score"])'` | `1` (plan predicted 1) | `2` | non-trivial, reachable |
| `grep -cF 'payload field'` | `0` | `1` | non-trivial, reachable |

All four of the plan's stated baselines were accurate — the first plan this round whose
grep gates needed no correction. The plan's warning against pinning a single-line header
spelling was well-founded: at nine entries the tuple runs to 118 characters, so it is
wrapped one entry per line.

## Verification Results

- **End of Task 1:** `FAILED (failures=1, errors=1)` — exactly the predicted tally, with
  the error being the expected `KeyError: 'technical_score'` raised inside the widened
  `scenario_rows` format by `test_the_committed_markdown_matches_the_committed_payload`,
  and the failure being
  `test_the_committed_payload_carries_a_per_scenario_technical_score`. No third
  failure. Set-based assertions were used in place of `subTest` in the committed-payload
  test so the tally reads unambiguously at the method level.
- **End of Task 2:** full suite green — 374 tests, `-W error::ResourceWarning`.
- **Byte-identical regeneration (SC3):** re-proven by SHA-256 across a second run
  (`4441bb2a…` JSON, `772c7842…` Markdown, both matching). A third run after commit left
  `git status --porcelain experiments/` silent.
- **Payload shape:** prints `5 2 20 10000 2 True`.
- **MEAS-16 anchor:** still exact — `0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884`, n=200,
  four bucket HR@10 `[0.9, 0.95, 0.9, 0.9]`.
- **Rendered table:** header reads
  `| MTTC | TechnicalScore | binomial sigma |`; 22 table lines, all 9 cells; separator's
  7th cell is `---:`.
- **`RUNS.md` containment:** 49 insertions / 6 deletions, deletions confined to lines 36
  and 50-54; the third hunk is a pure insertion, so nothing below the `### Historical`
  heading was removed. `zero-variance guard` now returns `0`.
- **Disproof re-executed, not transcribed:** before writing the `01-06-SUMMARY.md`
  correction, the uniform rank-2→rank-1 promotion over 200 sessions was reproduced against
  current code: `delta 0.15`, `standard_error 0.0`, `permutation_p 0.0004997501249375312`
  (the Phipson-Smyth floor `1/2001`), `clears_practical_floor True`, `failed_criteria ()`,
  `verdict win`, and `is_degenerate False` — confirming 01-10's narrowed condition
  correctly excludes this case. The old guard would have inverted this decisive win into a
  null.
- **Base integrity:** the worktree spawned from a stale base (merge-base `9faf85c`); reset
  to `d82504f` and all five prior plans' work verified present before any edit.

## Task Commits

| Task | Commit | Description |
|---|---|---|
| 1 | `bfde32d` | Add per-scenario TechnicalScore column and round disclosures |
| 2 | `2f634f1` | Regenerate leaderboard from the repaired rig at R=10,000 |
| 3 | `61746f5` | Reconcile prose with the regenerated report |
| 4 | — | Operator sign-off; approved after reviewing all six steps |

## Success Criteria

- [x] SC1 satisfied in full — TechnicalScore, HR@10, MRR and MTTC are separate columns
      both overall and per scenario, in the payload and the rendered report
- [x] SC3's byte-identical regeneration re-established and re-proven against the repaired rig
- [x] MEAS-16 anchor still reproduces to the digit
- [x] `RUNS.md` quotes no number the regenerated report contradicts; no historical prose deleted
- [x] Plan 01-13's fingerprint-semantics change disclosed, together with the fact that every
      committed record still derives the digest it stores
- [x] The false claim at `01-06-SUMMARY.md:153` corrected on the record, original quoted,
      disproof attached and independently re-executed

## Known Stubs

None. Every symbol in the plan's artifact table exists and is exercised.

## Threat Flags

None beyond the plan's register. No network endpoint, credential, or untrusted input was
introduced; no package was installed and `pyproject.toml` keeps `dependencies = []`. T-01-35,
T-01-36, T-01-16, T-01-20, T-01-21 and T-01-05 are all mitigated as planned — the one
adjustment being that T-01-36's mitigation states the *true* weighting rule rather than the
plan's false one, which strengthens rather than weakens it. WR-12
(`write_leaderboard`'s non-atomic two-file write) was out of scope for this round and remains
mitigated in practice by the render-identity test.

## Self-Check: PASSED

All six modified/created files exist on disk; all four commits verified present in
`git log`.
