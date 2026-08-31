---
phase: 02-expanded-dataset-paraphrase-probe
plan: 06
subsystem: arena/statistics
tags: [statistics, mcnemar, paired-contrast, d-44, d-45, meas-11, meas-13]
requires:
  - arena.statistics.paired_bootstrap
  - arena.statistics.pair_seed
  - arena.statistics.minimum_detectable_difference
  - arena.leaderboard.spec_from_record
  - arena.metrics.binomial_standard_error
  - arena.store.write_json
provides:
  - arena.paired_contrast.PairedArm
  - arena.paired_contrast.McNemarResult
  - arena.paired_contrast.PairedContrastResult
  - arena.paired_contrast.mcnemar_exact
  - arena.paired_contrast.require_comparable_arms
  - arena.paired_contrast.align_on_pair_id
  - arena.paired_contrast.restrict_to_shared_pairs
  - arena.paired_contrast.arm_from_run
  - arena.paired_contrast.sessions_by_pair
  - arena.paired_contrast.mcnemar_from_arms
  - arena.paired_contrast.paired_contrast
  - arena.paired_contrast.render_markdown
  - arena.paired_contrast.write_paired_contrast
  - arena.paired_contrast.spec_for_arm
affects:
  - plan 02-10 (the --contrast CLI that consumes these entry points)
  - plan 02-13 (writes experiments/baselines/paired_contrast.json and experiments/PAIRED_CONTRAST.md)
tech-stack:
  added: []
  patterns:
    - frozen slotted dataclasses with validate() and as_record()
    - content-seeded RNG via pair_seed on a distinct label
    - refuse-then-narrow (align_on_pair_id refuses; restrict_to_shared_pairs counts)
key-files:
  created:
    - arena/paired_contrast.py
    - tests/test_arena_paired_contrast.py
  modified:
    - tests/test_arena_adjudication.py
decisions:
  - "Sigma in the per-scenario block is anchored to the CONTROL arm's bucket hit rate, so it does not move when the probe does"
  - "control_arm and probe_arm added to the record beyond the planned field list, so the D-39/D-49 limitation is re-derivable from the JSON alone"
  - "_cell and _table are imported from arena.leaderboard rather than reproduced, to avoid a third copy of the number-formatting policy"
metrics:
  duration: ~45 minutes
  completed: 2026-09-01
  tasks: 3
  commits: 3
  tests-added: 38
  suite: 436 tests, 5.1 s
---

# Phase 02 Plan 06: Paired Contrast Readout Summary

Control-vs-probe now has its own statistical readout — bootstrap CI, exact McNemar, and
an MDD from the measured bootstrap SE — joined on `pair_id` with the Holm family and the
winner's-curse correction deliberately and visibly absent (D-44), plus the first test for
`adjudicate`'s previously unreachable cross-corpus refusal (D-45).

## What Shipped

**`arena/paired_contrast.py`** (808 lines). Frozen slotted `PairedArm`, `McNemarResult`
and `PairedContrastResult`, each with `validate()` and `as_record()`. `mcnemar_exact` is
the two-sided exact binomial test at p = 0.5 over `math.comb`. `require_comparable_arms`
is the corrected inverse of `adjudicate`'s digest guard. `align_on_pair_id` re-keys with
`dataclasses.replace` and refuses orphans; `restrict_to_shared_pairs` is the only
narrowing path and reports what it dropped. `paired_contrast` assembles the readout;
`render_markdown` is a pure view; `write_paired_contrast` mirrors `write_leaderboard`.

**`tests/test_arena_paired_contrast.py`** (707 lines, 36 tests) and a
`CrossCorpusRefusalTest` plus its positive companion in
`tests/test_arena_adjudication.py`.

## The Statistic, Verified Independently

The plan flagged that a paired test reporting significance on exchangeable data is the
failure mode to rule out, and that a statistic implemented from memory is a common source
of silent error. `mcnemar_exact` was therefore checked against a **second, independently
derived implementation** rather than only against its own output: an exact-rational
reference computing `P(|B - n/2| >= |b - n/2|)` under `B ~ Binom(n, 1/2)` by direct
enumeration in `fractions.Fraction`, which is a different definition from the
min-tail-doubling shortcut the implementation uses.

| b | c | exact rational | float | published |
|---:|---:|---|---:|---:|
| 20 | 4 | 12951/8388608 | 0.00154388 | 0.00154 |
| 19 | 5 | 55455/8388608 | 0.00661075 | 0.00661 |
| 18 | 6 | 190051/8388608 | 0.02265584 | 0.02266 |
| 17 | 7 | 536155/8388608 | 0.06391466 | 0.06391 |
| 16 | 8 | 635813/4194304 | 0.15158963 | 0.15159 |
| 14 | 10 | 2270193/4194304 | 0.54125619 | 0.54126 |

All six agree with the implementation to 1e-12 and reproduce `02-RESEARCH.md` § 7.
Additionally: `mcnemar_exact(k, k) == 1.0` was asserted for **every** k from 0 to 39, and
the end-to-end readout was exercised on a symmetric-discordance fixture (b = c = 6) and on
an identical-arm fixture (b = c = 0). Both report `p = 1.0` and `delta = 0.0`. The
exchangeable-data failure mode is ruled out by measurement, not by inspection.

## Gate Verification — Both Directions

Per the phase's history of one-sided acceptance gates, each load-bearing gate was
**mutation-tested**: a deliberately broken implementation was substituted with
`unittest.mock.patch` (no source file on disk was edited) and the gate was confirmed to
fail. All four mutations correctly failed their gate:

| Mutation | Gate that must fire | Fired? |
|---|---|---|
| `align_on_pair_id` silently inner-joins | strict default refuses the 300/100 arms | yes |
| `mcnemar_exact` drops the `min(1.0, ...)` clamp | symmetric discordance is 1.0 | yes |
| `Anthropic-family` text removed from the report | SC4 scoped-limitation assertion | yes |
| scenario breakout zero-fills absent buckets | absent scenarios produce no row | yes |

The AST no-correction scan is two-sided in the committed suite itself: the scanner is run
over `arena/adjudication.py`, which both imports and calls the two functions, and must
come back with both names. A scanner that has only ever returned an empty set is
indistinguishable from one that cannot detect anything.

**One harness defect found and fixed during this verification, worth recording.** The
first mutation run reported two gates as *not firing*. That was wrong, and the fault was
in my harness rather than in the gates: `tests/test_arena_paired_contrast.py` does
`from arena.paired_contrast import mcnemar_exact, render_markdown`, which binds those
names into the test module at import time, so patching `arena.paired_contrast.<name>`
left the test's own binding untouched. Repatching at the test module's binding site made
both mutations fail correctly. Anyone re-running this class of check must patch where the
name is *looked up*, not where it is *defined* — otherwise the mutation silently does
nothing and the gate reads as one-sided when it is not.

## The Reconciliation This Plan Had to Settle

`02-RESEARCH.md:754` and `02-VALIDATION.md`'s "D-45 inverse" row both assume control and
probe live in **two separate corpora** and therefore carry two different
`dataset_sha256` values — which would make an *equal* digest a refusal. D-46 and D-25 lock
the opposite design: one `probe.v1` corpus of 700 rows carrying `control`, `probe_sonnet`
and `probe_haiku` in its sample rows. Both arms therefore come from one `run_arena run`
and one digest, and requiring differing digests would make the phase's primary contrast
impossible to express.

Resolution, as built and as commented verbatim at the guard and asserted in `GuardTest`'s
docstring: the same-digest case **passes**, and the protective intent is carried by the
refusals that actually stop a corpus being contrasted with itself — identical `arm`
labels and intersecting `sample_id` sets. A **differing** digest still raises by default,
because a cross-corpus join on `pair_id` is exactly the silently-bogus contrast D-45
exists to prevent; `allow_cross_corpus=True` is the explicit escape hatch that makes the
refusal read as deliberate. `CrossCorpusPairIdTest` proves the structural half is what
actually closes the hole: with corpus-namespaced ids, `align_on_pair_id` raises even when
the flag was passed, because the two id sets are disjoint and there is no join to make.

## Deviations from Plan

### Auto-fixed / Auto-added

**1. [Rule 2 - Missing field] Added `control_arm` and `probe_arm` to `PairedContrastResult`**
- **Found during:** Task 2
- **Issue:** The planned field list carries `control_label` / `probe_label` but not the
  two `schema.ARMS` values. The D-39/D-49 scoped limitation is emitted precisely when the
  two arms are `probe_sonnet` and `probe_haiku`, so without the arm values in the record
  that condition would be derivable only from the rendered Markdown, and a reader of the
  JSON could not check why the caveat did or did not appear.
- **Fix:** Two extra fields, serialized in `as_record()`. The plan's own verify command
  uses `issubset`, so extra fields are compatible by construction.
- **Commit:** 719cbaf

**2. [Rule 2 - Test coverage] Added `ArmPartitionTest`, beyond the plan's class list**
- **Found during:** Task 3
- **Issue:** `arm_from_run` and `sessions_by_pair` are the D-46 entry points — one
  700-session run becomes three arms — and the plan's eleven named test classes exercise
  neither directly.
- **Fix:** Two tests covering the happy partition and the empty-partition refusal that
  names the arms actually present.
- **Commit:** 1cef6af

**3. [Judgement call] `_cell` and `_table` imported from `arena.leaderboard`**
- The plan permitted either importing them or reproducing the formatting rule. Importing
  underscore-prefixed names across a module boundary is against this repo's stated
  convention, so the choice is recorded with its rationale in a comment at the import:
  reproducing the rule would put a *third* copy of the number-formatting policy in the
  repository, and two committed reports that disagree on how a p-value prints is the
  silent divergence D-12 makes the JSON the source of truth to avoid.

**4. [Judgement call] Per-scenario sigma is anchored to the control arm**
- The plan specifies "the binomial sigma from `binomial_standard_error` at that n" without
  fixing which arm supplies `p`. D-15 mandates the bucket's own observed `p`; applied to a
  two-arm contrast that is ambiguous. Chose the **control** arm — the reference — so the
  sigma does not shift whenever the probe moves. Commented at the call site.

### Scope

No file outside the plan's declared `files_modified` was touched. No shared orchestrator
artifact (`STATE.md`, `ROADMAP.md`) was modified.

## Verification Results

| Check | Result |
|---|---|
| `unittest tests.test_arena_paired_contrast tests.test_arena_adjudication` | 74 tests, OK |
| `unittest tests.test_arena_boundary` | 10 tests, OK |
| `unittest` (full suite) | **436 tests, 5.1 s, OK** (398 at base, +38) |
| `grep "holm_bonferroni\|winners_curse_correction" arena/paired_contrast.py` | 2 matches: the `CORRECTIONS_OMITTED` tuple and the reading prose. Never an import, never a call |
| `assertRaises` in the new test module | 16 (need >= 12) |
| `restrict_to_shared` / `allow_cross_corpus` / `adjudication` | 5 / 3 / 3 |
| `resamples=` present / `resamples=10000` absent | 17 / 0 |
| `dataset_sha256` in `test_arena_adjudication.py` | 3 -> 8 |
| `arena/paired_contrast.py` line count | 808 (min 220) |

## Notes for Downstream Plans

- **Plan 02-10 (CLI):** the entry points are `spec_for_arm(run_directory)` for the digests
  (L-10 — `CandidateEntry` carries neither), `arm_from_run(...)` to partition one run into
  three arms, then `paired_contrast(control, probe, ...)`. The CLI must **not** pass
  `allow_cross_corpus` unless the operator asks for it explicitly.
- **Plan 02-13 (report):** write with `write_paired_contrast(result.as_record())`; the
  default paths are `experiments/baselines/paired_contrast.json` and
  `experiments/PAIRED_CONTRAST.md`, both chosen to sit outside what `.gitignore` excludes.
- **The 300/100 cross-check requires `restrict_to_shared=True`.** The strict default
  refuses it, by design. The retained and dropped counts both land in the record and in
  the rendered prose.

## Known Stubs

None. Every symbol this plan declares is implemented and exercised.

## Threat Flags

None. No new network endpoint, auth path, file-access pattern or trust-boundary schema
change. `write_paired_contrast` writes to two pinned repository-relative paths; all input
is already-validated in-process typed data.

## Self-Check: PASSED

- `arena/paired_contrast.py` — FOUND
- `tests/test_arena_paired_contrast.py` — FOUND
- `tests/test_arena_adjudication.py` — FOUND (modified)
- Commit `6d78268` — FOUND
- Commit `719cbaf` — FOUND
- Commit `1cef6af` — FOUND
