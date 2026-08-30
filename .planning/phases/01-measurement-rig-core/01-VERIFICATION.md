---
phase: 01-measurement-rig-core
verified: 2026-08-30T10:47:14Z
status: gaps_found
score: 7/10 must-haves verified
overrides_applied: 0
gaps:
  - truth: "A candidate that passes only one of the three win criteria is reported as not a win, with the failing criterion named"
    status: failed
    reason: "The D-23 HR@10 exchange-rate criterion is vacuous whenever MTTC improves. `EXCHANGE_RATE_PER_MTTC * mttc_delta` goes negative for mttc_delta < 0, so the test `mrr_delta > <negative>` is satisfied by a NEGATIVE mrr_delta. Independently reproduced against checked-in code: a candidate regressing HR@10 by 0.030 AND MRR by 0.010 was adjudicated `verdict = win` with `failed_criteria = ()`. The single criterion whose entire job is to stop an HR@10 regression from shipping does not fire in the direction it was written for."
    artifacts:
      - path: "arena/adjudication.py"
        issue: "Lines 295-297: `exchange_rate_ok = hit_rate_delta >= 0.0 or (mrr_delta > EXCHANGE_RATE_PER_MTTC * mttc_delta)` never requires an actual MRR gain, contradicting the constant's own docstring at lines 31-35."
      - path: "tests/test_arena_adjudication.py"
        issue: "Both exchange-rate fixtures (`_TRADE_UNDERPAID`, `_TRADE_PAID`, lines 89-93) add misses without pulling other sessions forward, so both have mttc_delta > 0. The negative-mttc_delta half of the branch has zero coverage."
    missing:
      - "Require a real MRR gain and compare magnitudes: `exchange_rate_ok = hit_rate_delta >= 0.0 or (mrr_delta > 0.0 and mrr_delta > EXCHANGE_RATE_PER_MTTC * abs(mttc_delta))`"
      - "Add an adjudication fixture with mttc_delta < 0 and an HR@10 regression, asserting the verdict is not a win"
      - "Consider scaling the forgiveness threshold with the SIZE of the HR@10 regression; today -0.10 is forgiven on identical terms to -0.005"
  - truth: "The practical-significance floor is tested against the winner's-curse-corrected delta, never the raw delta"
    status: failed
    reason: "Holds on the general path but is bypassed in the zero-variance branch, which hard-codes `clears_practical_floor = False` without testing anything. The `degenerate` guard keys off `standard_error <= 1e-12` ALONE, and bootstrap SE is zero for any exactly-uniform per-session improvement, not only for identical arms. Independently reproduced: a uniform rank-2 -> rank-1 promotion over 200 sessions yields `delta = 0.15` (15x the ship floor) with `verdict = no difference`, `permutation_p = 1.0` asserted rather than measured, and `clears_practical_floor = False` on the same row as `corrected_delta = 0.15` — an internally self-contradictory record that violates the module's own auditability contract at adjudication.py:93-95."
    artifacts:
      - path: "arena/adjudication.py"
        issue: "Lines 207-209 define degeneracy on SE alone; lines 264-277 then assert holm_p=1.0, mdd=0.0, clears_practical_floor=False and a fixed failed_criteria tuple while corrected_delta retains the real delta. Lines 214-216 short-circuit the permutation test that would have returned the Phipson-Smyth floor."
      - path: ".planning/phases/01-measurement-rig-core/01-06-SUMMARY.md"
        issue: "Line 153 claims the degenerate short-circuit 'is redundant with the general path' and that every value it sets 'is exactly what the general path produces when SE is 0.0'. Disproven: on the uniform-promotion fixture the general path yields measured permutation_p=0.0005, corrected_delta=0.15, clears_practical_floor=True, failed_criteria=() and verdict=WIN. The guard does not agree with the general path — it inverts the verdict."
    missing:
      - "Condition the guard on the delta as well as the SE: `result.standard_error <= ZERO_VARIANCE_TOLERANCE and abs(result.delta) <= ZERO_VARIANCE_TOLERANCE`"
      - "Add a regression fixture for exactly-uniform per-session improvement asserting the verdict is not NO_DIFFERENCE"
      - "Correct the 01-06-SUMMARY.md redundancy claim, which is contradicted by the code"
  - truth: "The leaderboard report shows TechnicalScore, HR@10, MRR and MTTC as separate columns, both overall and broken out per scenario"
    status: partial
    reason: "Overall is complete (HR@10, MRR, MTTC, Efficiency, TechnicalScore all present as separate columns in the Candidates table). Per scenario, HR@10, MRR and MTTC are present but TechnicalScore is absent from both the rendered table and the JSON payload. The information is complete and TechnicalScore is exactly derivable from the three printed columns, so this is a missing composite column rather than missing data."
    artifacts:
      - path: "arena/leaderboard.py"
        issue: "The scenario_breakout payload rows carry sample_count, hit_rate_at_10, mrr, mttc, binomial_standard_error and decision_grade — no technical_score key."
      - path: "experiments/LEADERBOARD.md"
        issue: "The 'Per-scenario breakout' table (lines 128-149) has no TechnicalScore column."
    missing:
      - "Add a per-scenario TechnicalScore column to the scenario_breakout payload and the rendered table, computed via technical_score(scenario.summary)"
---

# Phase 1: Measurement Rig Core Verification Report

**Phase Goal:** A statistically honest, evaluator-respecting measurement instrument exists and is validated against history — before any new candidate is built, so nothing downstream is judged on noise.
**Verified:** 2026-08-30T10:47:14Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Verdict in one paragraph

The measurement rig is real, substantial, and in most respects excellent. The statistical primitives are correct and I verified them individually; the committed leaderboard regenerates **byte-identically** from the committed records at R=10,000; the evaluator boundary is machine-enforced by AST walk plus a pinned byte hash; the MEAS-16 historical anchor genuinely cross-validates two independent code paths; 339 tests pass; there are zero debt markers and zero stubs. Four of five roadmap Success Criteria are fully met.

It nevertheless **fails its own goal**, because the goal's operative adjective is *statistically honest* and the verdict function — the single output on which every downstream decision rests — produces two reproducible false verdicts that I executed against the checked-in code, not inferred. One of them admits a candidate that regresses **both** headline retrieval metrics as a `win`, and its trigger condition (`mttc_delta < 0`) is the *designed direction of improvement* for the entire CONV workstream in Phase 3.

## Independent reproduction of the code review's claims

I was asked not to inherit `01-REVIEW.md`'s assessment. I executed each claim. Two hold exactly as described; one I judge overstated.

| Review finding | My verdict | Evidence |
| --- | --- | --- |
| CR-01 zero-variance guard | **Confirmed, severity partly overstated** | Reproduced verbatim. But the guard requires *exact* uniformity: I measured 199-of-200 uniform giving SE `0.00075853` (normal path, correct handling) versus 200-of-200 giving SE `0.0`. The review does not disclose how narrow the trigger is. Still a genuine BLOCKER — see below. |
| CR-02 exchange-rate vacuity | **Confirmed, and if anything understated** | Reproduced verbatim, same numbers. The review under-sells the blast radius: this is not an edge case, it is the main path for Phase 3. |
| CR-03 legacy-import overwrite | **Confirmed as fact, downgraded to WARNING** | The missing existence check is real and the asymmetry with `arena/arena.py:110` is real. But triggering it requires an operator to deliberately type `--output experiments/baselines/run-a` at a one-off migration CLI, and every affected record is git-tracked, so a clobber is recoverable. I do not agree this is a BLOCKER. |

### CR-01 reproducer output (executed)

```
baseline  = sessions_from_ranks((2,)*200)
candidate = sessions_from_ranks((1,)*200)

delta                  = 0.15000000000000002
standard_error         = 0.0
permutation_p          = 1.0          <- asserted, never measured
holm_p                 = 1.0
mdd                    = 0.0
corrected_delta        = 0.15000000000000002
clears_practical_floor = False        <- contradicts corrected_delta on the same row
VERDICT                = no difference
```

I then computed what the **general path** would have produced on the identical fixture, to test 01-06-SUMMARY.md's claim that the guard is "redundant with the general path":

```
permutation_p (MEASURED) = 0.0004997501249375312
holm_p                   = 0.0004997501249375312  -> significant
corrected_delta          = 0.15000000000000002
clears_practical_floor   = True
failed_criteria          = ()   =>  verdict = WIN
```

The guard is **not** redundant with the general path. It inverts the verdict, from `win` to `no difference`. The SUMMARY's claim is false.

### CR-02 reproducer output (executed)

```
baseline  HR@10/MRR/MTTC/TS = 1.00  0.333333  8.00  0.6600
candidate HR@10/MRR/MTTC/TS = 0.97  0.323333  3.89  0.7242

hit_rate_delta         = -0.030000000000000027   <- HR@10 REGRESSED
mrr_delta              = -0.010000000000000009   <- MRR REGRESSED
mttc_delta             = -4.109999999999999      <- MTTC improved, RHS goes negative
exchange_rate_ok       = True
holm_p                 = 0.0004997501249375312
clears_practical_floor = True
failed_criteria        = ()
VERDICT                = win
```

Blast radius, measured:

| MTTC improvement | `exchange_rate_ok` passes for any `mrr_delta` above |
| ---: | ---: |
| -0.5 turns | `-0.033350` |
| -1.0 turns | `-0.066700` |
| -2.0 turns | `-0.133400` |
| -4.11 turns | `-0.274137` |

A 4-turn MTTC improvement licenses an MRR regression of up to 0.274 — larger than the project's entire MRR headroom — while an HR@10 regression of arbitrary size passes unremarked. CLAUDE.md and CONV-03 both state that "a recall regression cannot be bought with speed." The rig as committed permits exactly that purchase.

## Goal Achievement

### Observable Truths

Merged from ROADMAP Success Criteria (SC1-SC5, non-negotiable contract) and goal-critical must-have truths declared in PLAN frontmatter.

| # | Truth | Source | Status | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Report shows TS, HR@10, MRR, MTTC as separate columns, overall **and per scenario** | SC1 / MEAS-01 | ✗ FAILED (partial) | Overall table has all five columns. Per-scenario table and JSON payload carry HR@10/MRR/MTTC/n/sigma but **no TechnicalScore**. Exactly derivable from printed columns, so data is complete. |
| 2 | Report includes HR@1/@3/@5/@10 curve from retained trace data alone, no agent re-invocation | SC2 / MEAS-02 | ✓ VERIFIED | `hit_rate_curve` (metrics.py:139-158) reads `best_rank` only. Curve table present for all 5 candidates. `test_curve_matches_the_anchor` passes. |
| 3 | Paired bootstrap + permutation + Holm + 0.01 floor + winner's-curse against two retained historical rows produces a reproducible verdict and an MDD | SC3 | ✓ VERIFIED | Regenerated the full payload twice in-process at R=10,000 from committed records: both agree with each other **and byte-identically with committed `leaderboard.json` and `LEADERBOARD.md`**. Two adjudication rows (`fallback-lexical`, `exploration-tail-only`) match the two measured findings in `RUNS.md:35-54`. MDD reported on both. |
| 4 | Every per-scenario verdict states bucket size and binomial standard error, flagged not decision-grade | SC4 / MEAS-09 | ✓ VERIFIED | `n` and `binomial sigma` columns present; `decision_grade` boolean; Boundary n=10 sigma `0.094868` flagged "no". Divergence from MEAS-09's illustrative 0.086/0.050 is deliberate (D-15 uses the bucket's own p) and disclosed in HOW_TO_READ item 1. |
| 5 | `CandidateSpec` yields an identical fingerprint twice; arena imports no evaluator internals beyond opaque `evaluate()` | SC5 / MEAS-14, MEAS-15 | ✓ VERIFIED | Two separate processes both produced `5ba3c0d4b07b...`. Only `evaluator_bridge.py` names the evaluator package; all other `arena/*.py` hits are line-number comments. `load_jsonl`/`catalog_index` are `evaluate()`'s own argument constructors, not internals. Enforced by AST walk + string-constant scan + pinned SHA-256. |
| 6 | A candidate that passes only one of three win criteria is reported as not a win, with the failing criterion named | 01-06 | ✗ FAILED | CR-02: a double regression is reported `win` with `failed_criteria = ()`. The exchange-rate criterion cannot fire when MTTC improves. |
| 7 | The practical-significance floor is tested against the winner's-curse-corrected delta, never the raw delta | 01-06 | ✗ FAILED | Holds on the general path; bypassed entirely in the degenerate branch, which hard-codes `False` against a `corrected_delta` of 0.15. |
| 8 | Two candidates identical on every session are reported as no difference, never as a win | 01-06 | ✓ VERIFIED | Executed: `verdict = no difference`, `failed = ('holm_significance','practical_floor')`. Also live on the committed `exploration-tail-only` row. |
| 9 | Two independent code paths agree on the same anchor numbers | 01-09 / MEAS-16 | ✓ VERIFIED | `AnchorReproductionTest` (9 tests) passes: `test_anchor_aggregates`, `test_recomputed_aggregates_agree_with_committed_summary`, `test_committed_per_scenario_metrics_agree`, `test_runs_md_four_decimal_values_after_rounding`. Anchor `0.920 / 0.524466 / 3.425 / 0.7575 / 0.76884` reproduced. |
| 10 | Adjudicating the same inputs twice produces byte-identical output | 01-06 | ✓ VERIFIED | Two in-process regenerations produced identical payload and identical Markdown. Seeds are SHA-256 content-derived via `pair_seed`, never clock-derived. |

**Score:** 7/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `arena/evaluator_bridge.py` | Sole evaluator seam, <=20 lines, 3 exports | ✓ VERIFIED | 17 lines, one from-import of exactly 3 names, pure re-export (no classes, no functions) |
| `arena/metrics.py` | Metric chain with rounding order intact | ✓ VERIFIED | All 9 exports present; rounding order reproduces the anchor to 6 dp |
| `arena/store.py` | Read/write/publish for baselines records | ✓ VERIFIED | All 8 exports present; `resolve_run_directory` traversal defence sound |
| `arena/candidate.py` | Fingerprinted hashable spec, allow-list | ✓ VERIFIED | Frozen+slots, SHA-256 canonical JSON, `ALLOWED_OVERRIDES` enforced in `validate()` |
| `arena/statistics.py` | Bootstrap, permutation, Holm, MDD, winner's curse | ✓ VERIFIED | All 12 exports present; Holm running max, Phipson-Smyth +1/+1, computed MDD multiplier all confirmed by reading |
| `arena/adjudication.py` | D-20 ordering, D-23 win rule, MEAS-07 floor | ⚠️ **DEFECTIVE** | All exports present and wired, but two branches produce false verdicts (truths 6 and 7) |
| `arena/leaderboard.py` | JSON source of truth + rendered Markdown | ⚠️ PARTIAL | All exports present and wired; per-scenario TechnicalScore column absent |
| `arena/arena.py` | run_candidate: Agent + bridge + publish | ✓ VERIFIED | Agent closed before publish (Windows handle ordering); ground truth joined only after `evaluate()` returns |
| `arena/run_arena.py` | CLI with run + adjudicate | ✓ VERIFIED | Both subcommands reachable; `--help` confirmed |
| `arena/import_legacy_results.py` | One-off legacy migration | ⚠️ WARNING | Functional; missing the existence check its sibling writer has (CR-03) |
| `experiments/baselines/leaderboard.json` | Machine-readable source of truth | ✓ VERIFIED | schema_version 1, 5 candidates, 2 adjudication rows, assumptions block |
| `experiments/LEADERBOARD.md` | Human/judge-readable report | ✓ VERIFIED | Regenerates byte-identically; HOW_TO_READ covers all four disclosed divergences |
| `experiments/RUNS.md` | Pointer to leaderboard, prose intact | ✓ VERIFIED | Additive pointer section at lines 5-67; all historical prose retained below |
| `experiments/baselines/anchor-legacy/*` | 200-session rescued record | ✓ VERIFIED | Tracked by git; loads and reproduces the anchor |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `arena/*.py` | `evaluator.local_evaluator` | single from-import in the bridge only | ✓ WIRED | AST walk + string-constant scan over all non-bridge modules returns empty |
| `arena/arena.py` | `arena/evaluator_bridge.py` | the only permitted seam | ✓ WIRED | Line 13; `evaluate()` called at line 136 as an opaque call |
| `arena/arena.py` | `starter.agent.Agent` | `CandidateSpec.agent_kwargs()` | ✓ WIRED | Line 125-128; no hard-coded knobs outside the spec |
| `arena/adjudication.py` | `arena/statistics.py` | bootstrap→permutation→Holm→curse→floor | ⚠️ PARTIAL | Order is correct, but the degenerate branch skips the permutation step (asserts p=1.0) and skips the floor test |
| `arena/leaderboard.py` | `arena/metrics.py` | `scenario_breakout` / `hit_rate_curve` | ✓ WIRED | Both consumed; curve and breakout tables render |
| `experiments/LEADERBOARD.md` | `experiments/baselines/leaderboard.json` | `render_markdown` over the payload | ✓ WIRED | Verified byte-identical regeneration |
| `experiments/RUNS.md` | `experiments/LEADERBOARD.md` | additive pointer section | ✓ WIRED | Lines 5-10 |

### Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
| --- | --- | --- | --- | --- |
| `LEADERBOARD.md` candidates table | `entries` | `entry_from_record` over `experiments/baselines/*/summary.json` | Yes — 5 real records, real aggregates | ✓ FLOWING |
| `LEADERBOARD.md` curve table | `hit_rate_curve` | `best_rank` in committed `sessions.jsonl` | Yes — 200 real session rows | ✓ FLOWING |
| `LEADERBOARD.md` scenario table | `scenario_breakout` | grouped committed session rows | Yes — 4 real scenario buckets | ✓ FLOWING |
| `LEADERBOARD.md` adjudication table | `rows` | `adjudicate()` at R=10,000 | Yes for `fallback-lexical` (measured p `0.645335`) | ✓ FLOWING |
| `LEADERBOARD.md` adjudication table | `permutation_p`, `mdd` for `exploration-tail-only` | degenerate short-circuit | **No — asserted `1.0` and `0.0`, never measured** | ⚠️ STATIC |

The `exploration-tail-only` row's answer is nonetheless correct here, because its delta is genuinely `0.0` (run-c sessions are byte-identical to run-a). `RUNS.md:47-54` discloses this honestly. The concern is the mechanism, not this row's value.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full test suite passes | `uv run python -W error::ResourceWarning -m unittest discover -s tests` | `Ran 339 tests ... OK` (5.374s) | ✓ PASS |
| Fingerprint stable across processes | two separate `uv run python -c` invocations | both `5ba3c0d4b07b3361...` | ✓ PASS |
| Committed report is reproducible | in-memory `build_leaderboard` + `render_markdown` vs committed files | payload and Markdown both `True` | ✓ PASS |
| CLI exposes run + adjudicate | `python -m arena.run_arena --help` | both subcommands listed | ✓ PASS |
| Identical arms never a win | `adjudicate` on two identical arms | `no difference` | ✓ PASS |
| Unpaired comparison is inexpressible | `paired_bootstrap` on mismatched sample_ids | `ValueError: paired comparison requires identical sample_id ordering` | ✓ PASS |
| Uniform improvement adjudicated honestly | `adjudicate` on rank-2→rank-1 over 200 sessions | `no difference` on a `+0.15` delta | ✗ **FAIL** |
| HR@10 regression is disqualifying | `adjudicate` on a double regression with MTTC gain | `win` | ✗ **FAIL** |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist in this repository and no PLAN or SUMMARY declares a probe path. Step 7c: **SKIPPED (no probes declared or discoverable)**. Verification relied on the stdlib `unittest` suite plus the eight direct behavioral spot-checks above.

### Requirements Coverage

Union of `requirements:` across all 9 PLAN frontmatters = MEAS-01, 02, 03, 04, 05, 06, 07, 08, 09, 14, 15, 16 — exactly the 12 IDs REQUIREMENTS.md maps to Phase 1. **No orphaned requirements.**

| Requirement | Source plans | Status | Evidence |
| --- | --- | --- | --- |
| MEAS-01 | 01-03, 01-07 | ⚠️ PARTIAL | Overall columns complete; per-scenario TechnicalScore absent |
| MEAS-02 | 01-03, 01-07 | ✓ SATISFIED | HR@1/@3/@5/@10 curve reported for all 5 candidates |
| MEAS-03 | 01-01, 01-03, 01-09 | ✓ SATISFIED | Per-scenario MRR/MTTC recovered from `anchor-legacy` without invoking the agent |
| MEAS-04 | 01-05 | ✓ SATISFIED | `_require_paired` makes unpaired comparison inexpressible; one index vector applied to both arms |
| MEAS-05 | 01-05 | ✓ SATISFIED | `holm_bonferroni` with the running maximum present and correctly placed |
| MEAS-06 | 01-05, 01-07 | ✓ SATISFIED | MDD column on every adjudication row; `NOT_DETECTABLE` vs `NO_DIFFERENCE` are distinct verdicts |
| MEAS-07 | 01-06 | ✓ SATISFIED | Floor tested against the corrected delta on the general path; the degenerate-branch defect is conservative and cannot manufacture a false win |
| MEAS-08 | 01-05, 01-06 | ✓ SATISFIED | Correction applied to every row at family k; sigma-hat, k, E[max k] printed as separate auditable columns |
| MEAS-09 | 01-03, 01-07 | ✓ SATISFIED | Bucket n + own-p binomial sigma + decision-grade flag; divergence from the illustrative figures disclosed |
| MEAS-14 | 01-04, 01-08 | ✓ SATISFIED | Fingerprint reproducible across processes; allow-list rejection enforced. See WR-01 warning below |
| MEAS-15 | 01-02, 01-08 | ✓ SATISFIED | Single seam, AST-enforced, evaluator byte-hash pinned |
| MEAS-16 | 01-03, 01-09 | ✓ SATISFIED | Anchor reproduced by two independent code paths before any new candidate existed |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `arena/adjudication.py` | 295-297 | Guard condition vacuous under sign inversion | 🛑 BLOCKER | HR@10 regression gate does not fire; `win` on a double regression |
| `arena/adjudication.py` | 207-209, 264-277 | Special-case branch asserting values instead of measuring them | 🛑 BLOCKER | Internally contradictory row; verdict inverted vs the general path |
| `arena/adjudication.py` | 298-307 | `failures` mapping holds passes, not failures | ⚠️ WARNING | Live foot-gun: a future `if failures[name]` read in the obvious sense inverts every verdict |
| `arena/import_legacy_results.py` | 146-150 | Non-atomic write, no existence check | ⚠️ WARNING | Can clobber a committed baseline; asymmetric with `arena/arena.py:110`. Recoverable via git |
| `arena/leaderboard.py` | 155-175 | Stored fingerprint never compared to derived | ⚠️ WARNING | A drifted reconstruction is reported under a fingerprint absent from its own `summary.json` |
| `arena/run_arena.py` | 60-64, 164-174 | Comment contradicts behaviour | ⚠️ WARNING | Default-everything fingerprints two ways. **Verified:** CLI-style `{exploration:disabled, lexical_mode:auto}` → `25e5f553460050d9`; programmatic `{}` → `af7bdf3a928ec07f`. One configuration, two identities |
| `arena/statistics.py` | 154-155 | Percentile indices wrong at small R | ⚠️ WARNING | 94.99% nominal coverage at R=10,000; silently degenerate below R≈40 |
| `arena/adjudication.py` | 212-216, 233 | Degenerate arms consume Holm budget on a synthetic p | ⚠️ WARNING | Live in the committed report: `fallback-lexical` was Holm-corrected at m=2 and k=2 because of an arm that could not have been a selection option. Conservative, but discards power |
| `arena/store.py` | 114-119 | Broad `except OSError` → `shutil.rmtree(destination)` | ⚠️ WARNING | Any OSError can trigger recursive deletion of a committed record |
| `arena/arena.py` | 151-167 | `**result` splatted last over provenance keys | ⚠️ WARNING | No collision guard; the sibling writer has one |

**Debt-marker gate:** PASSED. Zero `TBD`, `FIXME`, or `XXX` markers, and zero `TODO`, `HACK`, or `PLACEHOLDER` markers across `arena/` and the arena test modules. No stub phrases, no empty implementations. The code is genuinely substantive throughout — this phase's problem is logic, not incompleteness.

### Human Verification Required

None. Every must-have in this phase is machine-checkable and was checked programmatically. No PLAN contained a deferred `<verify><human-check>` block.

One item is escalated for **operator decision** rather than testing, in the Gaps Summary below.

### Gaps Summary

Three gaps. Two are BLOCKERs against the phase goal; one is a small completeness miss.

**The phase built an excellent instrument and then mis-wired its verdict.** Everything upstream of `adjudicate()` — the metric chain, the store, the fingerprinting, the boundary enforcement, the resampling primitives, the report renderer — verifies cleanly and often impressively. The MEAS-16 anchor validation is exactly what the phase promised: a genuine two-path cross-check performed before any new candidate existed. SC3's byte-identical regeneration is strong evidence that the pipeline is deterministic and auditable.

But the goal is not "a measurement rig exists." It is a **statistically honest** rig, built "so nothing downstream is judged on noise." The two BLOCKERs both sit in the one function that converts measurement into judgement, and both fail in the direction the phase claims to prevent.

**Gap 1 (CR-02) is the serious one, and I rate it more severe than the code review does.** The trigger is `mttc_delta < 0` — an MTTC improvement. That is precisely what CONV-01 and CONV-02 are designed to produce in Phase 3. So for the entire conversational-efficiency workstream, the criterion whose only job is to stop an HR@10 regression from shipping is switched off. Phase 3's Success Criterion 5 explicitly relies on this exact rule ("any HR@10 regression is treated as disqualifying unless the exchange-rate math clears with margin"), and CONV-03 states the principle directly ("a recall regression cannot be bought with speed"). Shipping Phase 2 on top of this is harmless; shipping Phase 3 on top of it means the first efficiency candidate that trades recall for turns gets a `win` verdict with an empty `failed_criteria` cell. This must be fixed before Phase 3 measures anything. The fix is two lines plus a fixture.

**Gap 2 (CR-01) is real but narrower than 01-REVIEW.md implies, and I say so plainly.** The review presents the zero-SE condition as arising "whenever the candidate improves every session by the same amount," which is accurate, but does not disclose that this requires *exact* uniformity across all 200 sessions. I measured the boundary: 199-of-200 uniform yields SE `0.00075853` and takes the normal path correctly. A realistic reranker will not produce a byte-exactly-uniform effect, so the practical false-negative risk on real candidates is low. I am nevertheless keeping this as a BLOCKER for two reasons that stand independently of trigger frequency. First, the emitted row is *internally self-contradictory* — `corrected_delta = 0.15` beside `clears_practical_floor = False` — which breaks the auditability contract the module states at its own lines 93-95, and auditability is the deliverable here. Second, the branch **asserts** `permutation_p` and `mdd` rather than measuring them, and one such fabricated row is live in the committed report; a rig whose published p-values are sometimes hard-coded is not one I can certify as "statistically honest." Note also that `01-06-SUMMARY.md:153`'s claim that this branch is "redundant with the general path" is demonstrably false, which is exactly the class of SUMMARY-versus-code divergence this verification exists to catch.

**Gap 3 (per-scenario TechnicalScore)** is minor. SC1 asks for four metrics as separate columns "both overall and broken out per scenario"; per-scenario carries three. The fourth is exactly derivable from the three that are printed, so no information is lost — this is a missing convenience column, roughly a five-line change.

**Where I disagree with the code review:** CR-03 is labelled BLOCKER there; I downgrade it to WARNING. Triggering it requires an operator to deliberately point a one-off migration CLI's explicit `--output` at a committed record, and because every baseline record is git-tracked, the damage is recoverable with `git checkout`. The asymmetry with `arena/arena.py:110` is a genuine and worth-fixing inconsistency, but it does not defeat the phase goal and should not gate Phase 2.

**Escalation for operator decision:** if you judge that CR-01's exact-uniformity trigger is too rare to justify a fix, the defensible middle path is to fix the *reporting* dishonesty without changing the guard's scope — stop asserting `permutation_p = 1.0` and `mdd = 0.0`, run the permutation for degenerate arms (it is cheap and returns an honest Phipson-Smyth floor), and make `clears_practical_floor` reflect the actual corrected delta. That removes the self-contradiction and the fabricated p-value while leaving the Pitfall-5 detectability guard intact. If you prefer to accept CR-01 as known debt outright, add an `overrides:` entry to this file's frontmatter with a reason and re-run verification. **CR-02 should not be overridden** — it is not an edge case and Phase 3 depends on it directly.

**Sequencing note:** Phase 2 (Expanded Dataset & Paraphrase Probe) does not consume `adjudicate()`. If you want to keep moving, Phase 2 can proceed in parallel with closing these gaps; the hard barrier is Phase 3.

---

_Verified: 2026-08-30T10:47:14Z_
_Verifier: Claude (gsd-verifier)_
