---
phase: 01-measurement-rig-core
plan: 09
subsystem: measurement
tags: [baselines, adjudication, leaderboard, provenance, fingerprint-identity, determinism]

# Dependency graph
requires: ["01-08", "01-07", "01-06"]
provides:
  - "`experiments/baselines/run-a` — the MEAS-16 anchor, reproduced by arena/ independently of experiments/run_public.py"
  - "`experiments/baselines/run-b` — the lexical-mode ablation arm (D-02 run B)"
  - "`experiments/baselines/run-c` — the exploration ablation arm (D-02 run C)"
  - "`experiments/baselines/synthetic-promote-10` — the validation control, now a record rather than an in-process object"
  - "`experiments/LEADERBOARD.md` — the Phase 1 report over five entries and two adjudicated comparisons"
  - "`arena.candidate.SPEC_NAME_FIELD` / `spec_name_from_record` — one authority for the name that enters the hashed payload"
  - "`arena.run_arena --include` — report-only entries that do not join the Holm family"
affects: [03, 04, 05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A serialized field that feeds a hash has exactly one named authority, referenced by both the writer and every reader"
    - "Report membership and hypothesis membership are separate: an entry can appear in the tables without entering the test family"
    - "A regenerated evidence set is written to an out-of-repo output root first, so the working tree stays clean and every arm records the same revision with dirty=false"

key-files:
  created:
    - experiments/baselines/run-a/{sessions.jsonl,summary.json}
    - experiments/baselines/run-b/{sessions.jsonl,summary.json}
    - experiments/baselines/run-c/{sessions.jsonl,summary.json}
    - experiments/baselines/synthetic-promote-10/{sessions.jsonl,summary.json}
  modified:
    - experiments/baselines/leaderboard.json
    - experiments/LEADERBOARD.md
    - experiments/RUNS.md
    - arena/candidate.py
    - arena/arena.py
    - arena/leaderboard.py
    - arena/run_arena.py
    - tests/test_arena_leaderboard.py

key-decisions:
  - "Refused to adjudicate anchor-legacy and synthetic-promote-10 as arms. Both belong in the report, neither is a hypothesis: adjudicating them would inflate the Holm family to k=4, weaken the two real comparisons, and drive the winner's-curse correction with a control built to win. Added --include instead, and proved the two real rows are byte-identical with and without it"
  - "Fixed the two-fingerprint defect before regenerating, not after, so the committed baselines later phases inherit are correct on first read"
  - "Regenerated all three runs to an out-of-repo output root so the tree stayed clean throughout; all three now share revision 5a978e7 with dirty=false and differ only by their overrides"
  - "Reported the provisional and final statistics side by side rather than silently replacing them, because the first numbers were published in a checkpoint message"

requirements-completed: [MEAS-03, MEAS-16]

# Metrics
duration: ~75min
completed: 2026-08-30
---

# Phase 01 Plan 09: Three Real Candidates, Adjudicated Summary

**The rig produced its first real evidence: run A reproduces the MEAS-16 anchor to six decimal places through a code path independent of the one that created it, and the two ablations were adjudicated to reproducible verdicts — neither of which is a win, both of which are reported exactly as measured.**

## Performance

- **Duration:** ~75 min (~20 min of it evaluation compute across six full 200-session runs)
- **Tasks:** 3 (two auto, one blocking checkpoint)
- **Tests:** 339 passing, warning-strict, 6.077 s (was 338)

## The two findings, verbatim

These are the findings the operator approved, recorded here as the checkpoint task requires.

**Finding 1 — `ΔTS(A, B)`, the lexical-mode ablation** (`auto` vs forced TF-IDF `fallback`, exploration disabled in both):

| quantity | value |
|---|---|
| delta | `+0.006110` |
| 95% CI | `[-0.018886, 0.031239]` |
| permutation p | `0.645335` |
| Holm-adjusted p | `1.000000` |
| MDD | `0.035987` |
| sigma-hat | `0.012845` (k = 2, E[max k] = `0.564190`) |
| corrected delta | `-0.001137` |
| verdict | **`not detectable`** |

Does not clear the ≥0.01 corrected floor. `failed_criteria`: `holm_significance`, `practical_floor`. Run B's own aggregates were HR@10 `0.925` / TS `0.774950`, both above run A, and it sorts above run A in the candidate table; the comparison still does not resolve them apart at n=200. Per D-22 this null is uninformative and must not be read as evidence that the two lexical engines are equivalent.

**Finding 2 — `ΔTS(A, C)`, the exploration ablation** (`disabled` vs `tail-only`):

| quantity | value |
|---|---|
| delta | `0.000000` |
| 95% CI | `[0.000000, 0.000000]` |
| permutation p | `1.000000` |
| Holm-adjusted p | `1.000000` |
| MDD | `0.000000` |
| sigma-hat | `0.000000` (k = 2, E[max k] = `0.564190`) |
| corrected delta | `0.000000` |
| verdict | **`no difference`** |

Run C's 200 session outcomes are byte-identical to run A's, so the arms are degenerate and the zero-variance guard fires. This reproduces, on committed records and at current HEAD, the metric-identical exploration result `RUNS.md` had recorded only in prose.

Neither outcome was assumed in advance. Run B was expected by D-02 to be the large-effect control; it is not, which is why the synthetic fixture remains the rig's only true positive.

## What Was Built

### Task 1 — Run A and the MEAS-16 cross-validation (`93ece5e`)

Run A reproduces `0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884` exactly and agrees with `anchor-legacy` on all six aggregates and all four scenario summaries. Because `anchor-legacy` came from the evaluator's own CLI and this came through `arena/`, that agreement is the two-independent-code-paths evidence D-06 exists to produce. The `RUNS.md` retained row matches only after explicit rounding, as the plan requires: recomputing TechnicalScore from the 4 dp figures gives `0.76885`, which displays as `0.7689`.

Per-scenario values match the `RUNS.md` line exactly (MEAS-03, recovered from a committed record with no agent re-invoked): boundary `0.90 / 0.404444 / 3.6`, browsing `0.95 / 0.527862 / 3.125`, buying `0.90 / 0.464296 / 3.2875`, intent_override `0.90 / 0.715873 / 4.533333`.

### Task 2 — Runs B and C, adjudication, RUNS.md (`bdf62c0`, `d2ef208`, `a582d8e`)

Run B measured `0.925 / 0.522167 / 3.21 / 0.779 / 0.774950` in 292 s — not the 747-800 s the superseded section records, so the TF-IDF path's cost did not scale as that section implied. Run C measured identically to run A.

`experiments/RUNS.md` gained one additive section: **64 insertions, 0 deletions** against the pre-plan baseline, headings 8 → 9.

### Task 3 — Checkpoint, then the operator's three decisions (`5a978e7`, `13808a6`)

The checkpoint surfaced two defects rather than self-approving. Both were resolved on the operator's instruction, in the order they directed.

## Deviations from Plan

### Escalated to the operator rather than auto-fixed

**1. [Rule 4 - Architectural] A record's stored fingerprint appeared nowhere in the report**

- **Found during:** Task 2 acceptance
- **Issue:** `arena/arena.py` hashed the `--name` value into `fingerprint`; `arena/leaderboard.py` rebuilt the spec from `run_id`. Since `name` sits inside the hashed payload, every arena record carried two identities, and the digest in its own `summary.json` appeared in no leaderboard row. 01-08's check did not catch this because it compared the two *derived* paths to each other on `anchor-legacy` — a record that has no `candidate_name` and so cannot diverge.
- **Why escalated:** the fix changes fingerprints, which seed `pair_seed`, and therefore changes every published CI and p-value on permanent baselines.
- **Fix (operator-approved):** `SPEC_NAME_FIELD` and `spec_name_from_record()` in `arena/candidate.py` are now the single authority; writer and reader both route through them. `anchor-legacy` falls back to its run id and keeps fingerprint `b8ce1269…`.
- **Files modified:** `arena/candidate.py`, `arena/arena.py`, `arena/leaderboard.py`
- **Verification:** all three records now satisfy `stored == spec_from_record(...) == entry_from_record(...)`, pinned by a new regression test.
- **Commit:** `5a978e7`

**2. [Rule 4 - Architectural] Regenerating the leaderboard dropped the anchor and the validation control**

- **Found during:** Task 2 full-suite run
- **Issue:** plan 01-07 built the committed leaderboard in-process (baseline `anchor-legacy`, candidate `synthetic-promote-10`), so it was never CLI-reproducible. The plan's prescribed command builds from run directories only, which dropped both and failed four tests encoding ROADMAP Success Criteria 1/2/4 and threat T-01-16b.
- **Why escalated:** the alternatives were to adjudicate a provenance-incomplete rescued record and a fixture designed to win as real arms (statistically wrong), or to retire tests encoding a threat mitigation.
- **Fix (operator-approved):** added `--include` for report-only entries, and materialised `synthetic-promote-10` as a record directory. It reproduces 01-07's fingerprint `6eec1db1…`, MRR `0.564238` and TS `0.780771` exactly.
- **Files modified:** `arena/run_arena.py`; new `experiments/baselines/synthetic-promote-10/`
- **Verification:** the two adjudication rows are **byte-identical** with and without `--include`, and `correction_k` is `2` either way.
- **Commit:** `13808a6`

### Auto-fixed

**3. [Rule 1 - Bug] Run C recorded `code_revision_dirty: true`**

- **Found during:** Task 2
- **Issue:** run B's untracked record was in the tree when run C started, so run C recorded a dirty tree and was not reconstructible from its recorded revision — a lasting defect in a permanent baseline.
- **Fix:** committed run B first, then re-ran run C on a clean tree. The discarded first invocation produced a byte-identical `sessions.jsonl`, which is an independent determinism check on the runner.
- **Commit:** `d2ef208`

### Plan acceptance criteria that could not all hold

The plan's Task 2 criteria required *simultaneously* "four candidate entries (anchor-legacy, run-a, run-b, run-c)", "exactly two rows", `candidate_count == 2` and `correction_k == 2`. Under the CLI shape `entries = baseline + adjudicated candidates` those are mutually inconsistent, and 01-07's tests imply a fifth entry. Resolved as the operator directed: **five** report entries, **two** adjudicated rows, `correction_k == 2`. The reproducibility gate independently forces this reading — a hand-assembled payload would not survive re-running the documented command.

## Provisional vs final statistics

The checkpoint message published numbers computed under the old two-fingerprint identity. They were superseded, not quietly replaced. Session outcomes were byte-identical across the regeneration, so **both deltas are unchanged and both verdicts hold**; only the seed-derived quantities moved.

| quantity | provisional | final | moved? |
|---|---:|---:|---|
| `ΔTS(A,B)` delta | `0.006110` | `0.006110` | no |
| `ΔTS(A,B)` CI lower | `-0.018926` | `-0.018886` | yes |
| `ΔTS(A,B)` CI upper | `0.031082` | `0.031239` | yes |
| `ΔTS(A,B)` permutation p | `0.650235` | `0.645335` | yes |
| `ΔTS(A,B)` Holm p | `1.000000` | `1.000000` | no |
| `ΔTS(A,B)` MDD | `0.036305` | `0.035987` | yes |
| `ΔTS(A,B)` sigma-hat | `0.012959` | `0.012845` | yes |
| `ΔTS(A,B)` corrected delta | `-0.001201` | `-0.001137` | yes |
| `ΔTS(A,B)` verdict | `not detectable` | `not detectable` | no |
| `ΔTS(A,C)` every quantity | all zero, `no difference` | all zero, `no difference` | no |

That the deltas did not move is the operator's stated stop condition, satisfied: `ΔTS` is a function of the data, and the fix touched only identity.

## Fingerprint identity: before and after

| record | provisional stored | provisional derived | final (single) |
|---|---|---|---|
| run-a | `c4e594ab04a1…` | `991028f38916…` | `c23c99876ee0…` |
| run-b | `c535e65c3a19…` | `da64dc4b741e…` | `e0d73537d58b…` |
| run-c | `56c162799892…` | `fd7eab7337a0…` | `8c95a79adbf4…` |
| anchor-legacy | none stored | `b8ce126916a0…` | `b8ce126916a0…` (unchanged) |

## Verification

| Check | Result |
|---|---|
| Anchor reproduced by two independent code paths | `0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884`, all six aggregates and four scenario summaries equal to `anchor-legacy` |
| `round(mrr,4) == 0.5245`, `round(TS,4) == 0.7688` | pass (exact-equality deliberately not asserted) |
| `sessions.jsonl` line counts | 200 for run-a, run-b, run-c, synthetic-promote-10 |
| Three run fingerprints pairwise distinct | pass |
| `stored == derived` fingerprint on every record | pass, pinned by new test |
| Adjudication internal consistency | CI contains delta; MDD `== 2.801585218112968 × SE` to 12 places; `win` iff `failed_criteria` empty; `not detectable` implies `abs(delta) < MDD` |
| `corrected_delta` re-derivable as `delta − sigma-hat × E[max k]` | pass to 12 places |
| Permutation p respects Phipson-Smyth floor `9.999e-05` | pass; neither row sits at the floor |
| `--include` does not perturb adjudication | rows byte-identical with and without; `correction_k == 2` both ways |
| `git diff --numstat 115c246 -- experiments/RUNS.md` | `64  0` — zero deletions |
| `git check-ignore -q` on each `summary.json` | exits `1` (tracked) |
| Reproducibility gate | re-ran adjudication, `git diff --quiet` exits `0` |
| Determinism | run C re-run produced a byte-identical `sessions.jsonl`; all three regenerated runs byte-identical to committed |
| `uv run python -W error::ResourceWarning -m unittest` | **339 tests, 6.077 s, OK** |

## Threat Model Coverage

| Threat ID | Mitigation as built |
|---|---|
| T-01-01 | `overrides` asserted equal to the exact flags used; fingerprints pairwise distinct; the two-identity defect that let a record's declared digest go unused is closed and pinned by a test |
| T-01-15 | Both findings recorded as measured; acceptance asserts internal consistency and reproducibility, never a magnitude or a significance outcome |
| T-01-21 | `RUNS.md` edit additive only — 64 insertions, 0 deletions, headings 8 → 9 |
| T-01-04 | Adjudication re-run; `git diff --quiet` exits `0` |
| T-01-05 | `git check-ignore -q` exits `1` on all four records |
| T-01-19 | Run B budgeted generously and run in background; it took 292 s, and the atomic publish meant the discarded run C left no partial record |
| T-01-16b | The validation control keeps its `synthetic-` prefix and a provenance field naming `promote_hits_to_rank_one`, and is `provenance_complete: false`; it is reported but never adjudicated |
| T-01-03 | Unchanged; enforced structurally by 01-08's `_SampleMappingAgent` |

## Known Stubs

None.

## Threat Flags

None. No network surface, no credential, no new file access outside the baselines root and the report paths.

## Notes for Phase 3

- The champion of a two-arm family is `fallback-lexical` on raw delta, but its corrected delta is **negative** (`-0.001137`). At k=2 the winner's-curse correction is `0.564190 × sigma-hat`, and at this SE that exceeds the observed gain. This is the mechanism POS-04's ~0.005 stopping threshold will meet in Phase 5.
- The measured sigma-hat for a real A/B pair here is `0.012845` — roughly 3.5× the `0.003715` that `01-RESEARCH.md` records for the synthetic promotion pair, and above the `0.002-0.008` band `LEADERBOARD.md` states as typical. Two arms running different retrieval engines are weakly paired, so pairing recovers less. A Phase 3 candidate that changes ranking rather than the engine should pair far more tightly and see a correspondingly smaller MDD.
- The MDD for that pair is `0.035987`. No candidate producing a sub-0.036 effect against a differently-engined baseline can be resolved at n=200.
- `--include` is the mechanism for carrying retained records into later reports without enlarging the Holm family.

## Self-Check: PASSED

- `experiments/baselines/run-a/summary.json` — FOUND
- `experiments/baselines/run-b/summary.json` — FOUND
- `experiments/baselines/run-c/summary.json` — FOUND
- `experiments/baselines/synthetic-promote-10/summary.json` — FOUND
- `experiments/baselines/leaderboard.json` — FOUND
- `experiments/LEADERBOARD.md` — FOUND
- `experiments/RUNS.md` — FOUND
- Commit `93ece5e` — FOUND
- Commit `bdf62c0` — FOUND
- Commit `d2ef208` — FOUND
- Commit `a582d8e` — FOUND
- Commit `5a978e7` — FOUND
- Commit `13808a6` — FOUND
