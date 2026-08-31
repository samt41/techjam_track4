---
phase: 01-measurement-rig-core
verified: 2026-08-31T08:42:34Z
status: passed
score: 10/10 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 2026-08-30T10:47:14Z — 7/10
  verified_at_head: 7e75151
  gaps_closed:
    - "A candidate that passes only one of the three win criteria is reported as not a win, with the failing criterion named (BLOCKER 1, D-23 exchange-rate vacuity)"
    - "The practical-significance floor is tested against the winner's-curse-corrected delta, never the raw delta (BLOCKER 2, zero-variance short-circuit)"
    - "The leaderboard report shows TechnicalScore, HR@10, MRR and MTTC as separate columns, both overall and broken out per scenario (SC1, per-scenario TechnicalScore column)"
  gaps_remaining: []
  regressions: []
  warnings_closed:
    - "arena/statistics.py — asymmetric bootstrap percentile indices (94.99% coverage)"
    - "arena/import_legacy_results.py — non-atomic write with no existence check"
    - "arena/run_arena.py — CLI flag defaults minted a second fingerprint for one configuration"
    - "arena/arena.py — unguarded **result splat over provenance keys"
    - "arena/leaderboard.py — stored fingerprint never compared to derived"
    - "arena/adjudication.py — `failures` mapping held passes, not failures (renamed to `passed`)"
    - "arena/adjudication.py — degenerate arms consumed Holm budget on a synthetic p (p now measured for every arm)"
    - ".planning/phases/01-measurement-rig-core/01-06-SUMMARY.md:153 — false 'redundant with the general path' claim, now corrected in place"
  warnings_downgraded:
    - "arena/store.py — recursive delete narrowed from any OSError to a visible directory; residual race disclosed and judged defensible (W-01)"
deferred: []
human_verification: []
---

# Phase 1: Measurement Rig Core Verification Report

**Phase Goal:** A statistically honest, evaluator-respecting measurement instrument exists and is validated against history — before any new candidate is built, so nothing downstream is judged on noise.
**Verified:** 2026-08-31T08:42:34Z at HEAD `7e75151`
**Status:** passed
**Re-verification:** Yes — after the six-plan gap-closure round (01-10 .. 01-15)

## Verdict in one paragraph

**Both blockers are genuinely closed, and I proved it by execution rather than by reading the
summaries.** I re-ran the prior report's own two reproducers against live source. The
double-regression fixture that previously returned `verdict = win` with an empty
`failed_criteria` now returns `exchange_rate_ok = False`,
`failed_criteria = ('hr10_exchange_rate',)` and `verdict = significant, below ship bar`. The
uniform rank-2→rank-1 promotion that previously returned `no difference` on a `+0.15` delta
with an asserted `permutation_p = 1.0` now returns `is_degenerate = False`, a **measured**
`permutation_p = 9.999e-05`, `clears_practical_floor = True` and `verdict = win`. The
zero-variance short-circuit is not narrowed — it is **deleted**, and every arm now takes one
path. SC1's missing per-scenario TechnicalScore column is present in the payload, in the
rendered table, and in the committed artifact for all twenty rows. All six prior warnings are
closed or defensibly downgraded, the suite is 374 tests green warning-strict, and there are
still zero debt markers anywhere in `arena/` or its tests. **10/10.**

## Independent re-execution of the two blockers

I did not accept the SUMMARY claims. Both reproducers below were executed in-process against
the checked-in code at HEAD `7e75151`.

### Blocker 1 (CR-02) — D-23 exchange rate, re-executed

```
baseline  HR/MRR/MTTC/TS = 1.00  0.333333  8.0  0.66
candidate HR/MRR/MTTC/TS = 0.97  0.323333  1.3  0.776

hit_rate_delta         = -0.030000   <- HR@10 REGRESSED
mrr_delta              = -0.010000   <- MRR REGRESSED
mttc_delta             = -6.700000   <- MTTC improved
exchange_rate_ok       = False                       (was True)
failed_criteria        = ('hr10_exchange_rate',)     (was ())
VERDICT                = significant, below ship bar (was win)
```

The fix is `abs(mttc_delta)` at `arena/adjudication.py:372`. The bar is now non-negative, so
the comparison can no longer read "MRR above some negative number".

### Blocker 2 (CR-01) — zero-variance handling, re-executed

```
baseline  = 200 sessions at rank 2;  candidate = 200 sessions at rank 1

delta                  = 0.170000
standard_error         = 0.0
is_degenerate          = False        <- zero SE is no longer conflated with zero delta
permutation_p          = 9.999e-05    <- MEASURED (was asserted 1.0)
holm_p                 = 9.999e-05
corrected_delta        = 0.170000
clears_practical_floor = True         <- was False beside a corrected_delta of 0.15
VERDICT                = win          <- was "no difference"
```

Control, two identical arms — the answer that must NOT have moved:

```
delta = 0.0, standard_error = 0.0, is_degenerate = True,
permutation_p = 1.0 (measured), holm_p = 1.0, mdd = 0.0, corrected_delta = 0.0,
clears_practical_floor = False, failed_criteria = ('holm_significance','practical_floor'),
VERDICT = no difference
```

Unchanged, and now **derived through the general rule** rather than asserted by a branch.
`arena/adjudication.py:335-394` is one path for every arm; `degenerate` at `:254-258` is
conditioned on delta AND SE and is documented as feeding no decision.

## Goal Achievement

### Observable Truths

Carried forward from the prior VERIFICATION.md's must-have set (ROADMAP SC1-SC5 merged with
the goal-critical PLAN-frontmatter truths). Failed items got full re-verification by
execution; passed items got a regression check.

| # | Truth | Source | Prior | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Report shows TS, HR@10, MRR, MTTC as separate columns, overall **and per scenario** | SC1 / MEAS-01 | ✗ partial | ✓ VERIFIED | `leaderboard.py:385` adds `technical_score` to every `scenario_breakout` row; `:545,563` renders it between MTTC and binomial sigma. Committed `LEADERBOARD.md:181-202` is a 9-column table, all 20 rows (5 candidates x 4 scenarios) populated. Payload: 20/20 rows carry the key. |
| 2 | Report includes HR@1/@3/@5/@10 curve from retained trace data alone, no agent re-invocation | SC2 / MEAS-02 | ✓ | ✓ VERIFIED | `metrics.py:139-158` reads `best_rank` only — no turn trace, no agent. Curve table at `LEADERBOARD.md:168-174` for all 5 candidates. |
| 3 | Paired bootstrap + permutation + Holm + 0.01 floor + winner's curse against two retained historical rows produces a reproducible verdict and an MDD | SC3 | ✓ | ✓ VERIFIED | Two rows (`fallback-lexical`, `exploration-tail-only`) against `baseline-auto-disabled`, R=10,000. CI, perm p, Holm p, MDD, sigma-hat, k, E[max k], corrected dTS, floor all present. Both map to the two measured findings in `RUNS.md:35-56`. **Strengthened:** the `exploration-tail-only` row's perm p and MDD are now measured, not asserted. |
| 4 | Every per-scenario verdict states bucket size and binomial SE, flagged not decision-grade | SC4 / MEAS-09 | ✓ | ✓ VERIFIED | `n` and `binomial sigma` columns plus `decision_grade`; Boundary n=10 sigma `0.094868` flagged `no`; Intent Override n=30 sigma `0.054772` flagged `no`. D-15 divergence from MEAS-09's illustrative 0.086/0.050 disclosed in HOW_TO_READ item 1 and pinned by `test_the_illustrative_sigma_is_only_ever_named_as_illustrative`. |
| 5 | `CandidateSpec` yields an identical fingerprint twice; arena imports no evaluator internals beyond opaque `evaluate()` | SC5 / MEAS-14, MEAS-15 | ✓ | ✓ VERIFIED | Two separate OS processes both produced `a7dda3f7d4ba3d1a98e5ee85286f01cab18271b90591ed6ca63368804375cd76`. `evaluator_bridge.py` is 21 lines: one from-import of exactly 3 names, `__all__` pinned, no classes or functions. Every other `evaluator` occurrence in `arena/*.py` is a comment (verified by grep over all 11 modules). |
| 6 | A candidate that passes only one of three win criteria is not a win, with the failing criterion named | 01-06, 01-10 | ✗ FAILED | ✓ VERIFIED | Re-executed above. `abs(mttc_delta)` at `:372`. Both directions covered: underpaid gain fails, paid gain passes. |
| 7 | The practical floor is tested against the winner's-curse-corrected delta, never the raw delta | 01-06, 01-10 | ✗ FAILED | ✓ VERIFIED | Re-executed above. `clears_practical_floor = corrected_delta >= PRACTICAL_FLOOR` at `:363`, unconditional, one path. `test_no_row_field_is_a_fabricated_constant` re-derives MDD, corrected delta and floor from other columns **on the same row** across a real / uniform / identical family. |
| 8 | Two candidates identical on every session are no difference, never a win | 01-06 | ✓ | ✓ VERIFIED | Control above. Also live on the committed `exploration-tail-only` row. Now derived, not asserted. |
| 9 | Two independent code paths agree on the same anchor numbers | 01-09 / MEAS-16 | ✓ | ✓ VERIFIED | Anchor `0.920 / 0.524466 / 3.425 / 0.7575 / 0.768840` reproduced; `AnchorReproductionTest` green within the 374. Committed payload matches. |
| 10 | Adjudicating the same inputs twice produces byte-identical output | 01-06 | ✓ | ✓ VERIFIED | `test_two_adjudications_serialize_identically` + `test_reproducible_across_processes` green. Seeds are SHA-256 content-derived via `pair_seed`, never clock-derived. Committed artifacts regenerate with SHA-256 unchanged. |

**Score:** 10/10 truths verified. **Gaps closed: 3. Gaps remaining: 0. Regressions: 0.**

### Required Artifacts

| Artifact | Expected | Prior | Status | Details |
| --- | --- | --- | --- | --- |
| `arena/adjudication.py` | D-20 ordering, D-23 win rule, MEAS-07 floor | ⚠️ DEFECTIVE | ✓ VERIFIED | 426 lines. Short-circuit deleted; one path per arm; `abs()` present; `failures` renamed `passed`; `is_degenerate` descriptive only. Both false verdicts re-tested and gone. |
| `arena/leaderboard.py` | JSON source of truth + rendered Markdown | ⚠️ PARTIAL | ✓ VERIFIED | 695 lines. Per-scenario `technical_score` in payload and render. **New:** `_spec_from_payload` refuses a stored-vs-derived fingerprint mismatch on the read path (`:241-246`), shared by both readers. |
| `arena/statistics.py` | Bootstrap, permutation, Holm, MDD, winner's curse | ⚠️ WARNING | ✓ VERIFIED | `percentile_indices()` now public and pure; provably symmetric and provably ≥ nominal coverage (proof below). `MINIMUM_RESAMPLES = 40` representability floor added. |
| `arena/store.py` | Read/write/publish for baselines records | ⚠️ WARNING | ✓ VERIFIED (residual W-01) | Recursive delete narrowed from any `OSError` to a visible directory, mutation-guarded by `test_a_non_directory_oserror_does_not_delete_the_destination`. |
| `arena/import_legacy_results.py` | One-off legacy migration | ⚠️ WARNING | ✓ VERIFIED | `FileExistsError` refusal at `:161-162` plus a staged, single-rename atomic publish at `:172-183`. Both tested, including the leaves-no-partial-record path. |
| `arena/run_arena.py` | CLI with run + adjudicate | ⚠️ WARNING | ✓ VERIFIED | All three override flags now `default=None`; CLI default invocation fingerprints identically to programmatic `overrides={}`, tested end-to-end through `main()` with a non-vacuity guard. |
| `arena/arena.py` | run_candidate: Agent + bridge + publish | ⚠️ WARNING | ✓ VERIFIED | `_PROVENANCE_KEYS` collision guard raises `ArenaStoreError` **before** the summary is built and before anything is written (`:177-181`). |
| `arena/evaluator_bridge.py` | Sole evaluator seam, 3 exports | ✓ | ✓ VERIFIED | 21 lines, pure re-export, `__all__` pinned. |
| `arena/metrics.py` | Metric chain with rounding order intact | ✓ | ✓ VERIFIED | Byte-unchanged since 01-03. Correctly NOT the place the per-scenario composite was added — the transcription claim that makes D-06/D-08 cross-agreement meaningful stays true. |
| `arena/candidate.py` | Fingerprinted hashable spec, allow-list | ✓ | ✓ VERIFIED | Frozen+slots, SHA-256 canonical JSON with pinned separators, `ALLOWED_OVERRIDES` enforced in `validate()`. |
| `experiments/baselines/leaderboard.json` | Machine-readable source of truth | ✓ | ✓ VERIFIED | schema_version 1, 5 candidates, 20 scenario rows all carrying `technical_score`, 2 adjudication rows at R=10,000, assumptions block now includes `holm_family_size: 2` and `holm_family_includes_degenerate_arms: true`. |
| `experiments/LEADERBOARD.md` | Human/judge-readable report | ✓ | ✓ VERIFIED | 9-column per-scenario table; HOW_TO_READ grew to seven disclosures plus verdict vocabulary. |
| `experiments/RUNS.md` | Pointer to leaderboard, prose intact | ✓ | ✓ VERIFIED | All seven historical prose sections retained below the additive pointer. New "Regenerated after the gap-closure round" block accounts for what moved. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `arena/*.py` | `evaluator.local_evaluator` | single from-import in the bridge only | ✓ WIRED | Grep over all 11 modules: one import line, all other hits are comments. AST-walk + string-constant boundary tests green; evaluator SHA-256 `84ea8997...` pinned and matching. |
| `arena/adjudication.py` | `arena/statistics.py` | bootstrap→permutation→Holm→curse→floor | ✓ WIRED | **Previously ⚠️ PARTIAL.** The permutation now runs unconditionally once per candidate (`:267-280`); no step is skipped for any arm. |
| `arena/leaderboard.py` | `arena/metrics.py` | `scenario_breakout` / `hit_rate_curve` / `technical_score` | ✓ WIRED | All three consumed; the per-bucket composite is computed at the output boundary, deliberately not inside `metrics.py`. |
| `arena/leaderboard.py` | `arena/candidate.py` | `_spec_from_payload` stored-vs-derived check | ✓ WIRED | **New link.** Both `spec_from_record` and `entry_from_record` route through it, so neither reader needs its own copy. |
| `arena/arena.py` | `arena/evaluator_bridge.py` | the only permitted seam | ✓ WIRED | `:13`; `evaluate()` called at `:154` as an opaque call. |
| `arena/arena.py` | `starter.agent.Agent` | `CandidateSpec.agent_kwargs()` | ✓ WIRED | `:143-146`; no knob hard-coded outside the spec. |
| `experiments/LEADERBOARD.md` | `experiments/baselines/leaderboard.json` | `render_markdown` over the payload | ✓ WIRED | `test_the_committed_markdown_matches_the_committed_payload` green; regeneration leaves SHA-256 unchanged. |

### Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
| --- | --- | --- | --- | --- |
| `LEADERBOARD.md` candidates table | `entries` | `entry_from_record` over 5 committed `summary.json` | Yes | ✓ FLOWING |
| `LEADERBOARD.md` curve table | `hit_rate_curve` | `best_rank` in committed `sessions.jsonl` | Yes — 200 real rows per record | ✓ FLOWING |
| `LEADERBOARD.md` scenario table | `scenario_breakout` + `technical_score` | grouped committed session rows | Yes — 20 buckets, all values in (0,1) | ✓ FLOWING |
| `LEADERBOARD.md` adjudication, `fallback-lexical` | `rows` | `adjudicate()` at R=10,000 | Yes (measured p `0.645335`) | ✓ FLOWING |
| `LEADERBOARD.md` adjudication, `exploration-tail-only` | `permutation_p`, `mdd` | `adjudicate()` general path | **Yes — now measured** (was ⚠️ STATIC) | ✓ FLOWING |

The prior report's single ⚠️ STATIC cell is resolved. The measured p is still `1.000000`, but
now because every sign-flip assignment of two identical arms ties the observed statistic —
arrived at by measurement, not by assertion.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full test suite, warning-strict | `uv run python -W error::ResourceWarning -m unittest discover -s tests` | `Ran 374 tests ... OK` (4.99s) | ✓ PASS |
| **HR@10 regression is disqualifying** | `adjudicate` on the CR-02 double regression | `significant, below ship bar`, `('hr10_exchange_rate',)` | ✓ **PASS** (was FAIL) |
| **Uniform improvement adjudicated honestly** | `adjudicate` on rank-2→rank-1 over 200 sessions | `win`, measured p `9.999e-05` | ✓ **PASS** (was FAIL) |
| Identical arms never a win | `adjudicate` on two identical arms | `no difference` | ✓ PASS |
| Fingerprint stable across processes | two separate `python -c` invocations | both `a7dda3f7d4ba...` | ✓ PASS |
| n-weighted per-scenario TS reproduces overall | recomputed on all 5 committed records | diffs `0.0`–`3.5e-07`; flat-average off by `0.006884`–`0.010316` | ✓ PASS |
| `adjudicate()` entry guards fire | empty candidates / shared fingerprint | both raise the documented `ValueError` | ✓ PASS (untested — see W-04) |
| Zero deps preserved | `cat pyproject.toml` | `dependencies = []` | ✓ PASS |
| Interrupted run cannot pose as a record | killed a `run` mid-flight | staging dir `.r1-*` left behind, removed manually | ✓ PASS (staging dir is not published as a record) |
| ~~T-01-19 staging dir is gitignored~~ | `git check-ignore` + real staging dir under `experiments/baselines/` | **NOT ignored** — `?? experiments/baselines/.r1-testprobe/` appears in `git status --porcelain` | ✗ **FAIL** — see correction below |

**Correction (orchestrator, post-verification).** This report originally recorded T-01-19 as
"confirmed incidentally" on the evidence that `git status --porcelain` stayed silent after a
killed run. That inference was wrong: the staging directory had already been removed when
status was sampled, so silence showed nothing. Measured directly, no staging path under
`experiments/baselines/` is ignored — `git check-ignore` exits 1 for `.r1-*`, `.run-*` and
`.anything`, and creating a real `experiments/baselines/.r1-testprobe/` makes it appear as
untracked. Three independent reasons: the intended pattern `experiments/.*-/` (`.gitignore:10`)
is anchored one level above `experiments/baselines/`, it requires the directory name to end in
`-` which a `tempfile` suffix never does, and `!experiments/baselines/` (`.gitignore:15`)
re-includes everything beneath it regardless. This matches finding CR/T-01-19 in `01-REVIEW.md`,
which reached the same conclusion independently. The mitigation does not exist and is carried as
open debt; it does not affect any must-have, because no success criterion depends on it.

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist in this repository and no PLAN or SUMMARY declares a
probe path. Step 7c: **SKIPPED (no probes declared or discoverable).** Verification relied on
the stdlib `unittest` suite plus the nine direct behavioral spot-checks above, of which the
two blocker reproducers were executed in-process against live source.

### Requirements Coverage

Union of `requirements:` across all 15 PLAN frontmatters = MEAS-01, 02, 03, 04, 05, 06, 07,
08, 09, 14, 15, 16 — **exactly** the 12 IDs `REQUIREMENTS.md:200-211` maps to Phase 1.
**No orphaned requirements. No plan claimed a requirement outside the phase's set.**

| Requirement | Source plans | Prior | Status | Evidence |
| --- | --- | --- | --- | --- |
| MEAS-01 | 01-03, 01-07, 01-15 | ⚠️ PARTIAL | ✓ SATISFIED | Per-scenario TechnicalScore now in payload, render and committed artifact |
| MEAS-02 | 01-03, 01-07 | ✓ | ✓ SATISFIED | HR@1/@3/@5/@10 for all 5 candidates from `best_rank` alone |
| MEAS-03 | 01-01, 01-03, 01-09, 01-12 | ✓ | ✓ SATISFIED | Per-scenario MRR/MTTC recovered from `anchor-legacy` with no agent invocation |
| MEAS-04 | 01-05, 01-11 | ✓ | ✓ SATISFIED | `_require_paired` makes an unpaired comparison inexpressible; one index vector, both arms. Interval convention corrected to Efron-Tibshirani `(R+1)` |
| MEAS-05 | 01-05 | ✓ | ✓ SATISFIED | `holm_bonferroni` with the running maximum, correctly placed; family composition now disclosed in two machine-readable assumptions keys |
| MEAS-06 | 01-05, 01-07 | ✓ | ✓ SATISFIED | MDD on every row; `NOT_DETECTABLE` vs `NO_DIFFERENCE` distinct, both live in the committed report |
| MEAS-07 | 01-06, 01-10, 01-15 | ✓ | ✓ SATISFIED | Floor tested against the corrected delta on **every** row; the branch that bypassed it is deleted |
| MEAS-08 | 01-05, 01-06 | ✓ | ✓ SATISFIED | Correction applied to every row at family k; sigma-hat, k, E[max k] as separate auditable columns |
| MEAS-09 | 01-03, 01-07 | ✓ | ✓ SATISFIED | Bucket n + own-p binomial sigma + decision-grade flag; D-15 divergence disclosed and test-pinned |
| MEAS-14 | 01-04, 01-08, 01-13, 01-14 | ✓ | ✓ SATISFIED | Cross-process fingerprint identity; allow-list rejection; **CLI/programmatic identity closed**; **stored-vs-derived drift now refused on the read path** |
| MEAS-15 | 01-02, 01-08 | ✓ | ✓ SATISFIED | Single seam, AST-enforced, evaluator byte-hash pinned |
| MEAS-16 | 01-03, 01-09, 01-12 | ✓ | ✓ SATISFIED | Anchor reproduced by two independent paths before any new candidate existed |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `arena/store.py` | 125-138 | `publish` cannot distinguish a crashed corpse from a completed record when a directory is present | ⚠️ WARNING (W-01) | Disclosed residual; see assessment below |
| `arena/adjudication.py` | 371-373 | HR@10 regression of any size forgivable once the magnitude-scaled MRR bar clears; bar → 0 as `mttc_delta` → 0 | ⚠️ WARNING (W-02) | Operator-declined scope; see assessment below |
| `arena/adjudication.py` | 371-372 | `mrr_delta > 0.0` is logically redundant; mutation-tested as pinning zero tests | ℹ️ INFO (W-03) | Disclosed at `:46-53`; partial defense-in-depth, not dead code |
| `tests/test_arena_adjudication.py` | — | Zero `assertRaises`; `adjudicate()`'s two entry guards are untested | ℹ️ INFO (W-04) | I executed both; both fire with the documented message |
| `arena/leaderboard.py` | 430 | `holm_family_includes_degenerate_arms: True` is a hard-coded policy literal, not derived | ℹ️ INFO (W-05) | Documented as standing policy at `:426-429`; would lie if the policy changed |
| `arena/statistics.py` | 212 | A zero bootstrap SE zeroes the winner's-curse correction entirely | ℹ️ INFO (W-06) | Bootstrap degeneracy, not introduced here; reachable only on exactly-uniform effects |

**Debt-marker gate: PASSED.** Zero `TBD`, `FIXME`, `XXX`, `TODO`, `HACK` or `PLACEHOLDER`
markers across `arena/` (11 modules, 2,672 lines) and the eight arena test modules (3,938
lines). No stub phrases, no empty implementations, no hardcoded-empty data paths. Every one of
the prior report's ten anti-pattern rows is either closed or downgraded — none was left open.

### Assessment of the three items I was asked to judge

**1. `arena/store.py` residual delete risk — DEFENSIBLE, does NOT block MEAS-03/MEAS-16.**

The narrowing is real and mutation-guarded: an ACL denial, a cross-device link or a
path-too-long with nothing at `destination` now raises `ArenaStoreError` with the cause
attached and removes nothing. What remains is narrower than the prior warning: `os.replace`
fails *and* a directory is visible at `destination`.

I do not read this as blocking the data-safety reading of MEAS-03/MEAS-16, and the reason is
that neither requirement is about write-path durability. MEAS-03 is "per-scenario MRR and MTTC
**recovered** from existing retained trace data without re-running the agent"; MEAS-16 is
"statistics engine **validated against** the retained historical rows before any new candidate
exists". Both are read-path claims about recovering and cross-validating history, and both are
satisfied. Plan 01-12's own declared truth — "a committed baseline record cannot be recursively
deleted by an OSError that has nothing to do with a stale destination directory" — is exactly
what the `is_dir()` narrowing delivers, and it is VERIFIED.

Three further bounds make acceptance defensible rather than lenient: the only in-repo caller
pre-checks and then owns the path for the run's duration; every baseline record is git-tracked,
so a clobber is recoverable with `git checkout`; and closing it properly needs a positive
corpse marker (a staging-provenance file, or a caller-supplied expendability assertion), which
is an architectural change the executor correctly escalated rather than took unilaterally.
**Recommendation:** carry W-01 forward as a Phase 6 (Submission Hardening) item, where
robustness work already lives. It should not gate Phase 2 or Phase 3.

**2. The redundant `mrr_delta > 0.0` clause — ACCEPTABLE, not a latent trap.**

Plan 01-10's finding is correct and I confirmed the logic: the bar
`EXCHANGE_RATE_PER_MTTC * abs(mttc_delta)` is non-negative, so `mrr_delta > bar` already
implies `mrr_delta > 0.0`. But "redundant" is not the same as "inert". If a future edit deletes
the `abs()` — the mutation that actually matters — the surviving `mrr_delta > 0.0` clause still
rejects the negative-MRR double regression that was CR-02's headline failure; only the
narrower underpaid-positive-gain case would slip through, and that case has its own dedicated
mutation guard (`test_an_mrr_gain_below_the_magnitude_bar_does_not_buy_an_hr10_regression`,
which the SUMMARY correctly identifies as the sole `abs(` guard). So the clause degrades
gracefully rather than failing silently, and keeping it is the better call.

Two small things I would tighten rather than block on. The comment's instruction "Do not read
it as a second guard" slightly understates the clause: it *is* a partial second guard against
the `abs()` mutation, which is the honest and more useful framing. And because no test pins
it, a future reader applying a dead-code rule could remove it — the comment forbids that
explicitly, which is adequate mitigation, but a one-line unit test asserting
`exchange_rate_ok is False` for `(hit_rate_delta < 0, mrr_delta < 0, mttc_delta < 0)` would
convert the prohibition into a check. Recorded as W-03 (INFO), not a gap.

**3. The n-weighting claim in `leaderboard.py` HOW_TO_READ item 5 — the REASONING is sound in
general, not merely numerically true on this data.**

I verified the argument analytically rather than by re-running the numbers. Each step holds:

- `SessionOutcome.validate()` constrains `first_hit_turn` to `[1, 10]`, and `metric_summary`
  substitutes `MAX_TURNS + 1 = 11` for a miss. So MTTC ∈ `[1, 11]` **always**, and
  `clip((11 - MTTC) / 10, 0, 1)` is the identity on that whole range including both endpoints.
  The clip is genuinely inactive, not merely inactive-in-practice.
- With the clip inactive, `TS_b = 0.5·HR_b + 0.3·MRR_b + 0.22 − 0.02·MTTC_b` is **affine** in
  the bucket's three metrics.
- HR@10, MRR and MTTC are each plain means over sessions, so each overall value is the
  n-weighted mean of its bucket values.
- `scenario_breakout` groups by `scenario_type` with every session landing in exactly one
  bucket, so the buckets are a genuine **partition** — the premise the linearity argument
  needs.
- An affine map commutes with a convex combination, and the constant `0.22` survives precisely
  because the n-weights sum to 1. Therefore `Σ(n_b/N)·TS_b = TS_overall` exactly, up to the two
  6-dp rounding steps.

Numerically confirmed on all five committed candidates: n-weighted reproduces overall to
`0.0`–`3.5e-07`; flat-averaging is off by `0.006884`–`0.010316`. The report's own stated
figures (`0.7688401` vs `0.76884`; flat `0.761956`, off by `0.006884`) are correct.

One nit, recorded for accuracy rather than as a defect: the disclosure calls the gap
"a `1e-07` discrepancy that is rounding and nothing else". The *general* rounding bound is
looser — roughly `9e-7`, since each bucket TS carries up to `5e-7` and the per-bucket metric
rounding propagates through the `0.5 / 0.3 / 0.02` coefficients — and the observed `3.5e-07`
on `synthetic-promote-10` already exceeds the anchor's `1e-07`. The qualitative claim ("rounding
and nothing else") is right and the illustrative magnitude is anchor-specific. The test asserts
`places=6`, which is the correct tolerance and not the anchor's tighter figure.

Separately, I verified the corrected percentile convention is provably right and not just
right at R=10,000. For integer `m = R + 1`, `ceil(0.975m) = m − floor(0.025m)`, so
`lower = floor(0.025m) − 1` and `upper = m − floor(0.025m) − 1` satisfy
`lower = R − 1 − upper` **identically** — the symmetry claim is an algebraic identity at every
admissible R, not a spot check. Coverage is `R + 2 − 2·floor(0.025(R+1))` order statistics,
which is ≥ `0.95R` for all R because `floor(0.025(R+1)) ≤ 0.025R + 0.025`. Both properties are
asserted in `PercentileIntervalTest`. That warning is closed on proof, not on a table.

### Disconfirmation pass

Per the Confirmation Bias Counter, three findings reported even though verification passes:

1. **A requirement only partially met in the literal sense.** MEAS-09 names
   `Boundary n=10, σ ≈ 0.086` and `Intent Override n=30, σ ≈ 0.050`; the rig prints `0.094868`
   and `0.054772`. The substance of MEAS-09 and SC4 (bucket size, binomial SE, not-decision-grade
   flag) is fully met, and the divergence is a deliberate D-15 improvement — the bucket's own
   observed `p` rather than the overall `p = 0.92` applied to a bucket `n` — disclosed in
   HOW_TO_READ item 1 and pinned by a test that forbids the report from ever presenting the
   illustrative figures as its own. Accepted, as in the prior verification, but it is a real
   divergence from the requirement text and a reader who greps MEAS-09 for `0.086` will not
   find it in the report.
2. **A gap in test coverage the passing suite hides.** `tests/test_arena_adjudication.py` — 820
   lines, the suite for the most safety-critical function in the rig — contains **zero**
   `assertRaises`. Both of `adjudicate()`'s entry guards (empty candidate tuple, candidate
   sharing the baseline's fingerprint) are therefore unpinned. The second one matters more than
   it looks: a candidate sharing the baseline's fingerprint would make `pair_seed(fp, fp, …)`
   seed a self-comparison. I executed both guards and both fire with their documented messages,
   so this is a coverage gap, not a defect. W-04.
3. **An untested error path elsewhere.** The `LexicalMode(...)` coercion at `arena/arena.py:145`
   has no test for an invalid `lexical_mode` string reaching it — `run_arena.py` constrains the
   flag with argparse `choices`, and `ALLOWED_OVERRIDES` gates the key but not the value, so a
   programmatic `overrides={"lexical_mode": "nonsense"}` raises a bare `ValueError` from the
   enum rather than a domain error at the spec boundary. Low impact (fails closed, single local
   operator), recorded rather than gated.

### Human Verification Required

**None.** Every must-have in this phase is machine-checkable and was checked
programmatically — the two blocker reproducers by in-process execution against live source, not
by reading SUMMARYs. The two `checkpoint:human-verify` gates in the phase (01-09 Task 4, 01-15
Task 4) were operator-resolved during execution; of 01-15's six review steps I independently
re-performed steps 1, 2, 3 and 4, and step 5 (byte-identical regeneration) was independently
established before this verification. No PLAN contains a deferred `<verify><human-check>` block
on an `auto` task, so there is nothing to harvest to HUMAN-UAT.md.

### Gaps Summary

**No gaps. The phase goal is achieved.**

The prior verification's judgement was that the phase "built an excellent instrument and then
mis-wired its verdict". The gap-closure round fixed the wiring, and it did so in the stronger of
the two available ways. On Blocker 2 the executor did not merely narrow the zero-variance guard
as the prior report suggested — it **deleted the branch entirely** and made the general path
handle every arm, then added `test_no_row_field_is_a_fabricated_constant`, which re-derives
each emitted column from other columns on the same row. That is a better answer than the one
the gap report asked for: it makes the class of defect (a branch asserting its own conclusion)
unrepresentable rather than fixing the one instance. On Blocker 1 the fix is one `abs()`, but
both directions are now covered by fixtures with non-vacuity guards that assert the actual
deltas before asserting the verdict, so a mis-calibrated fixture cannot pass by failing for an
unrelated reason.

Three quality signals I weigh heavily. First, the round found and corrected a **plan defect
rather than following it** — twice. Plan 01-10's mutation-check criterion named a test that
could not detect the mutation, and plan 01-15 directed a HOW_TO_READ claim that was
mathematically false; in both cases the executor kept the mandated implementation, corrected
the prose to what is true, and recorded the discrepancy. Shipping 01-15's directed wording
would have introduced a *new* false claim into a judge-facing auditability artifact in the same
commit series that corrects an old one. Second, `01-06-SUMMARY.md:153` — the SUMMARY-versus-code
divergence the prior verification existed to catch — now quotes its own former false claim
verbatim and states what changed. Third, the residual risks are disclosed **against** the
executor's interest rather than glossed: 01-12's SUMMARY has a section titled "Residual Risk
(not a deviation — flagged for the verifier)", and 01-10's comment block in
`adjudication.py:46-62` states plainly that a clause it kept is redundant and that two
strengthenings were offered and declined.

**What is not closed, and is not a gap.** W-01 (store.publish's corpse-versus-record ambiguity)
and W-02 (an HR@10 regression of any size stays forgivable once the magnitude-scaled MRR bar
clears) are both live, both disclosed in source, and both bounded. W-02 in particular is worth
Phase 3's attention: I measured a candidate regressing HR@10 by `0.100` reaching `verdict = win`
on an MRR gain of `0.567` against a bar of `0.020`, and the bar collapses toward zero as
`mttc_delta` approaches zero. That is the criterion behaving exactly as written and as the
operator chose — the MRR gain genuinely pays for the recall loss in TechnicalScore terms, and
`clears_practical_floor` and Holm significance remain independent conjuncts — but "recall
cannot be bought with speed" (CONV-03) is a narrower principle than what the rule now enforces,
which is "recall can be bought with ranking precision at a speed-scaled price". Phase 3 should
re-read D-23 with that framing in front of it before measuring its first efficiency candidate.

**Sequencing:** Phase 2 and Phase 3 are both unblocked. The hard barrier the prior verification
raised against Phase 3 — that the criterion protecting against a recall-for-speed trade was
switched off in exactly the direction Phase 3 moves — is gone, and I re-tested it in that
direction specifically.

---

_Verified: 2026-08-31T08:42:34Z at HEAD `7e75151`_
_Verifier: Claude (gsd-verifier) — re-verification after gap-closure plans 01-10 .. 01-15_
