---
phase: 1
slug: measurement-rig-core
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-30
revised: 2026-08-30
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `01-RESEARCH.md` § Validation Architecture.
> **Revised** after planning: the per-task map is filled from the assigned plan and
> task IDs, the two synthetic-control figures are corrected to the deterministic
> file-order rule the plans actually pin, the adjudication command is the real
> subcommand form, and the latency budget is reconciled with the resample budgets
> settled in plans 01-05, 01-06 and 01-07.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `unittest` (stdlib, CPython 3.13.x) — no pytest, no plugins, no config file |
| **Config file** | none — default discovery via `tests/__init__.py`, `test_*.py`, `TestCase` subclasses, `test_*` methods |
| **Quick run command** | `uv run python -m unittest -v tests.test_arena_<module>` |
| **Full suite command** | `uv run python -W error::ResourceWarning -m unittest -v` |
| **Measured baseline** | 167 existing tests in **3.0 s** (measured at HEAD `b98ff27`, no catalog present) |
| **Estimated runtime** | Quick: ≤ 3 s for most arena modules, ≤ 15 s worst case (`tests.test_arena_adjudication`). Full: **≤ 45 s** budget |

**Hard property to preserve:** the suite must continue to run with **no catalog
download and no 580 MB artifact**. Every new arena statistics/metrics module is
stdlib-pure by construction, so its tests need only in-memory fixtures.

### Per-module runtime budgets

These are acceptance criteria in the owning plans, not aspirations. They exist so
the after-every-task sampling rate below stays honest.

| Module | Budget | Owning plan | Notes |
|--------|-------:|-------------|-------|
| `tests/test_arena_boundary.py` | ≤ 1 s | 01-02 T2 | AST only, no resampling |
| `tests/test_arena_metrics.py` | ≤ 2 s | 01-03 T3 | Arithmetic only |
| `tests/test_arena_candidate.py` | ≤ 3 s | 01-04 T2 | Two subprocess spawns dominate |
| `tests/test_arena_statistics.py` | ≤ 8 s | 01-05 T3 | `TEST_RESAMPLES = 500`; only `test_permutation_floor` pins `R = 2000` |
| `tests/test_arena_adjudication.py` | ≤ 15 s | 01-06 T2/T3 | `FAST_RESAMPLES = 200`, `STABLE_RESAMPLES = 500`; two subprocess spawns |
| `tests/test_arena_leaderboard.py` | ≤ 5 s | 01-07 T3 | Reads committed JSON; no adjudication above `resamples=200` |
| `tests/test_arena_runner.py` | ≤ 5 s | 01-08 T3 | Fakes only, no real `Agent` |
| **New arena total** | **≤ 39 s** | — | Plus the 3.0 s existing suite ⇒ ≤ 45 s full-suite budget |

**Why the test suite never runs at `RESAMPLE_COUNT`.** `arena/statistics.py` fixes
`RESAMPLE_COUNT = 10_000` as a module constant (D-24) and exposes no CLI flag, so
every production path runs at 10,000. The `resamples` keyword argument exists
solely so the unit suite can hold this latency budget. Two tests deliberately pin
a specific R because their expected answer is a function of R —
`test_permutation_floor` (`p >= 1/2001` at `R = 2000`) and the constant pin
`RESAMPLE_COUNT == 10_000`. Everything else asserts a structural or analytic
property that does not depend on R.

---

## Sampling Rate

- **After every task commit:** the single relevant `tests.test_arena_*` module
  (≤ 3 s for most; ≤ 15 s for `tests.test_arena_adjudication`).
- **After every plan wave:** `uv run python -W error::ResourceWarning -m unittest -v`.
  Warning-strict is **mandatory** — it is the mechanism that catches an unclosed
  SQLite handle before it becomes a leak (RESEARCH Pitfall 8).
- **Before `/gsd-verify-work`:** full suite green, **plus** the three D-02
  evaluation runs completed with records committed under `experiments/baselines/`,
  **plus** the reproducibility check — run
  `uv run python -m arena.run_arena adjudicate --baseline experiments/baselines/run-a --candidate experiments/baselines/run-b --candidate experiments/baselines/run-c`
  twice and confirm
  `git diff --quiet -- experiments/baselines/leaderboard.json experiments/LEADERBOARD.md`
  exits 0.
- **Max feedback latency:** **≤ 15 s** for the slowest single module, **≤ 45 s**
  for the full suite.

> **Neither the three evaluation runs nor the leaderboard generation is a unit
> test, and neither may be wired into the suite.** The evaluation runs need the
> 580 MB artifact and ~190 s each; the leaderboard generation runs the adjudication
> at the production 10,000 replicates and costs roughly 60 s per invocation.
> Wiring either in would destroy the "runs with no catalog download" property and
> the latency budget above. Keep both as explicit operator steps with their outputs
> committed as evidence.

---

## Per-Task Verification Map

Every row below is claimed by at least one task's `<acceptance_criteria>`. Plan and
task IDs are the assigned ones; waves are the assigned execution waves.

| Requirement | Plan · Task | Wave | Threat Ref | Secure Behavior | Test Type | Automated Command | Status |
|-------------|-------------|-----:|------------|-----------------|-----------|-------------------|--------|
| MEAS-01 | 01-03 T1, 01-03 T3 (`ScenarioBreakoutTest`) | 2 | — | N/A (offline, local) | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ⬜ pending |
| MEAS-02 | 01-03 T1, 01-03 T3 (`HitRateCurveTest`) | 2 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ⬜ pending |
| MEAS-03 | 01-01 T3, 01-03 T3, 01-09 T1 | 1, 2, 7 | — | N/A | unit + operator | `uv run python -m unittest -v tests.test_arena_metrics` | ⬜ pending |
| MEAS-04 | 01-05 T1, 01-05 T3 (`PairingTest`) | 3 | T-01-04b | Unpaired comparison raises rather than silently inflating the SE | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ⬜ pending |
| MEAS-05 | 01-05 T1, 01-05 T3 (`PermutationTest`) | 3 | T-01-04c | Phipson-Smyth floor; `p` is never `0.0` | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ⬜ pending |
| MEAS-06 | 01-05 T2/T3 (`MinimumDetectableDifferenceTest`), 01-06 T1/T2 (`VerdictRuleTest`), 01-07 T2 (`HOW_TO_READ`) | 3, 4, 5 | T-01-14d | A detected-but-small gain is `below ship bar`, never `no difference` | unit | `uv run python -m unittest -v tests.test_arena_adjudication` | ⬜ pending |
| MEAS-07 | 01-06 T1, 01-06 T2 (`OrderingTest`) | 4 | T-01-14 | Floor tested against `corrected_delta`, never the raw delta | unit | `uv run python -m unittest -v tests.test_arena_adjudication` | ⬜ pending |
| MEAS-08 | 01-05 T2, 01-05 T3 (`ExpectedMaximumTest`), 01-06 T1 | 3, 4 | T-01-13 | sigma-hat is the paired-difference bootstrap SE, printed with k and `E[max k]` | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ⬜ pending |
| MEAS-09 | 01-03 T1, 01-03 T3, 01-07 T1/T3 | 2, 5 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ⬜ pending |
| MEAS-14 | 01-04 T1, 01-04 T2 | 2 | T-01-01 (spec/fingerprint divergence) | Unknown override key raises `ValueError`; fingerprint never claims an unapplied config | unit | `uv run python -m unittest -v tests.test_arena_candidate` | ⬜ pending |
| MEAS-15 | 01-02 T1, 01-02 T2 | 2 | T-01-02 (evaluator tamper) | Zero `evaluator` references outside the bridge; evaluator SHA-256 unchanged; scanner proven non-vacuous | unit | `uv run python -m unittest -v tests.test_arena_boundary` | ⬜ pending |
| MEAS-16 | 01-03 T3 (`AnchorReproductionTest`), 01-09 T1 | 2, 7 | T-01-11 | Two independent code paths agree on all six aggregates | unit + operator | `uv run python -m unittest -v tests.test_arena_metrics` | ⬜ pending |
| D-24 (determinism) | 01-05 T3 (`SeedDeterminismTest`), 01-06 T3 (`ReproducibilityTest`), 01-09 T2 | 3, 4, 7 | T-01-04 | Content-seeded RNG only; byte-identical across two `PYTHONHASHSEED` values | unit + operator | `uv run python -m unittest -v tests.test_arena_adjudication` | ⬜ pending |
| D-04 (evidence retention) | 01-01 T1, 01-01 T3 | 1 | T-01-05, T-01-08 | Negation scoped to `experiments/baselines/` only; artifact stays ignored | script | `git check-ignore -v experiments/baselines/<run>/sessions.jsonl` (must exit 1) | ⬜ pending |
| SC-3 (end-to-end adjudication) | 01-08 T2, 01-09 T2 | 6, 7 | T-01-20 | No `--resamples` flag; production R fixed at 10,000 | integration | `uv run python -m arena.run_arena adjudicate --baseline experiments/baselines/run-a --candidate experiments/baselines/run-b --candidate experiments/baselines/run-c` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## What "validated" means for a statistical engine

Passing tests is not sufficient. The engine is validated only when proven on **all
four** of the following — this is exactly what D-01's three layers plus the D-03
caveat encode:

1. **Arithmetic** — each routine reproduces an analytically known answer (Layer 1).
2. **True positive** — it says "significant" on a difference known to be real.
   Per RESEARCH Q1, the guaranteed true positive is the **synthetic** control
   derived from run A's own sessions (analytically known ΔTS), *not* run B.
3. **True negative** — it says "not significant" on a difference known absent,
   **and** reports an MDD showing it could have seen one. This is the property
   MEAS-06 exists for and the one a rig validated only on real effects silently
   lacks.
4. **Reproducibility** — two invocations on identical inputs produce
   byte-identical verdicts (D-24).

---

## Wave 0 Requirements

`wave_0_complete: true` here means: **every test module below is claimed by a named
plan and task that creates it in the same task that first invokes it.** No task in
this phase carries a `MISSING —` automated verify, and no unclaimed scaffolding
remains. The modules themselves are written during execution, in the waves shown.

- [ ] `tests/test_arena_boundary.py` — MEAS-15 — **01-02 T2** (wave 2). AST walk +
      string-constant scan + bridge surface + evaluator SHA-256, plus a `ScannerTest`
      that proves the detector fires on both a static and a dynamic evasion using
      temporary files.
- [ ] `tests/test_arena_metrics.py` — MEAS-01, MEAS-02, MEAS-03, MEAS-09, MEAS-16 —
      **01-03 T3** (wave 2).
- [ ] `tests/test_arena_candidate.py` — MEAS-14 — **01-04 T2** (wave 2).
- [ ] `tests/test_arena_statistics.py` — MEAS-04, MEAS-05, MEAS-06, MEAS-08 (the
      D-01 Layer 1 known-answer fixtures) — **01-05 T3** (wave 3).
- [ ] `tests/test_arena_adjudication.py` — MEAS-07, D-20 ordering, D-23 win rule,
      D-24 reproducibility — **01-06 T2 and T3** (wave 4).
- [ ] `tests/test_arena_leaderboard.py` — report shape and rendering — **01-07 T3**
      (wave 5).
- [ ] `tests/test_arena_runner.py` — session mapping and spec fidelity — **01-08 T3**
      (wave 6).
- [ ] A shared arena fixture builder — `tests/arena_fixtures.py`, **01-03 T3**
      (wave 2): session-tuple constructors plus the deterministic
      `promote_hits_to_rank_one` helper (RESEARCH Q1). Follow the `tests/fixtures.py`
      pattern: module-level factory functions, **not** a `TestCase`, so it is
      excluded from discovery. Unlike `tests/fixtures.py` it needs no temp
      directory and no catalog.
- [ ] Framework install: **none required** — `unittest` is stdlib and the suite
      already exists.

---

## Layer-1 Known-Answer Fixture Specification

Every value below was computed against this repository. The planner transcribes
these directly into `<acceptance_criteria>`.

**Comparison discipline.** Where the "Exact expected answer" column says
`places=N`, an exact `==` assertion is forbidden and is a guaranteed false failure.
Two categories of value carry unavoidable residual binary float error:

- **The synthetic-control deltas**, because each is a subtraction of two
  independently 6-dp-rounded TechnicalScores. The actual computed floats are
  `0.011931000000000025` and `0.08521400000000001`.
- **`arena.metrics.efficiency`**, which is deliberately returned UNROUNDED so it
  reproduces the anchor through `technical_score`, exactly as
  `evaluator/local_evaluator.py:279-280` does. On the anchor it is
  `0.7575000000000001`. The evaluator rounds it to 6 dp only at output
  (`local_evaluator.py:286`), which is why `summary.json` and the committed
  leaderboard both legitimately read `0.7575`.

| Fixture | Input | Exact expected answer |
|---------|-------|----------------------|
| Degenerate bootstrap | two identical candidates | `delta == 0.0`, `ci == (0.0, 0.0)`, `se == 0.0`, `mdd == 0.0`, `p == 1.0`, `failed_criteria == ("holm_significance", "practical_floor")`, verdict `"no difference"` (**never** `"win"`) |
| Verdict vocabulary | `classify_verdict` injected values | exactly four members: `"win"`, `"significant, below ship bar"`, `"no difference"`, `"not detectable"`; `verdict is WIN` **iff** `failed_criteria == ()` |
| Exact permutation | n=4, paired diffs `[0.10, 0.20, 0.30, −0.05]`, exhaustive 2⁴ enumeration | `p == 4/16 == 0.25` |
| Permutation floor | any input, R resamples | `p >= 1/(R+1)`; the unit test pins `R = 2000` → `p >= 1/2001`; the production constant `RESAMPLE_COUNT == 10_000` is asserted separately (→ `p >= 9.999e-5`); `p` is never `0.0` |
| Holm textbook | `[0.01, 0.04, 0.03]` | `[0.03, 0.06, 0.06]` |
| Holm one-strong | `[0.001, 0.30, 0.40]` | `[0.003, 0.60, 0.60]` |
| Holm exact ties | `[0.02, 0.02, 0.02]` | `[0.06, 0.06, 0.06]` |
| Holm monotonicity | `[0.60, 0.01, 0.02]` | `[0.60, 0.03, 0.04]` |
| MDD closed form | `SE = 0.003779` | `MDD == 2.801585218112968 × 0.003779` (`≈ 0.010587`) |
| `E[max]` k=1 | k=1 | `0.0` |
| `E[max]` k=2 | k=2 | `1/math.sqrt(math.pi) == 0.5641895835477563` (`places=12`) |
| `E[max]` k=3 | k=3 | `3/(2*math.sqrt(math.pi)) == 0.8462843753216345` (`places=12`) |
| `E[max]` monotone | k=1..10 | strictly increasing in k |
| Binomial σ | `p=0.9, n=10` | `0.09486832980505137` (`places=12`) |
| Binomial σ | `p=0.9, n=30` | `0.054772255750516606` (`places=12`) |
| TS non-linearity (D-17) | a session set where mean-of-per-session-TS ≠ recomputed TS | the two differ — proves the resample-then-recompute path is live |
| Pairing preserved | perfectly correlated pair vs uncorrelated pair, same Δ | correlated CI width < ⅓ uncorrelated CI width (measured SEs: `0.003715` paired vs `0.025922` unpaired) |
| Seed determinism | same two fingerprints, two invocations | identical `delta`, `ci`, `p`, `mdd` — byte-equal serialized output |
| **Synthetic large effect (Q1)** | run-A sessions, **deterministic file-order** promotion of the first m=10 sessions with `best_rank > 1` to rank 1 | `ΔTS == +0.011931` (`places=9`); verdict `"win"`, clears the 0.01 corrected floor, `delta > MDD` |
| **Synthetic large effect (Q1)** | same rule, m=77 | `ΔTS == +0.085214` (`places=9`) |
| Anchor | run-A session file | `0.92 / 0.524466 / 3.425 / 0.76884` exact; `efficiency` `0.7575` at `places=12` (unrounded `0.7575000000000001`), `0.7575` exact once 6-dp rounded at output; HR@K `0.385/0.59/0.715/0.92` exact |

> **Note on the two synthetic-control rows.** `01-RESEARCH.md` and the orchestrator
> directive quote `ΔTS = +0.0123` (m=10) and `+0.0871` (m=77) from a **seeded
> random** selection. The plans pin the simpler **deterministic file-order** rule —
> promote the first `m` sessions in file order that satisfy
> `best_rank is not None and best_rank > 1` — whose exact values are the
> `0.011931` / `0.085214` recorded above, computed against the committed
> `experiments/baselines/anchor-legacy/sessions.jsonl`. Both selections agree to two
> decimal places and support the same conclusion; the file-order rule is chosen
> because it needs no RNG and is byte-stable by construction. **The values in this
> table are the authoritative ones.** An executor transcribing this table verbatim
> writes passing assertions.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| The three D-02 evaluation runs (A, B, C) | MEAS-16, SC-3 | Needs the 580 MB artifact and ~190 s each; wiring into the suite would break the no-catalog property | `uv run python -m arena.run_arena run --run-id run-a --name ... ` for each candidate; commit `sessions.jsonl` + `summary.json` under `experiments/baselines/<run-id>/`; confirm run A reproduces the anchor |
| Leaderboard generation at production scale | MEAS-06, D-24 | Runs the adjudication at `RESAMPLE_COUNT = 10_000`, roughly 60 s per invocation — an order of magnitude above the whole suite's budget | `uv run python -m arena.run_arena adjudicate --baseline ... --candidate ...`; run twice and confirm `git diff --quiet -- experiments/baselines/leaderboard.json experiments/LEADERBOARD.md` exits 0 |
| `.gitignore` negation actually tracks `experiments/baselines/` | D-04 | Git ignore semantics must be observed against the real repo, not simulated | `git check-ignore -v experiments/baselines/<run>/sessions.jsonl` must exit 1 (not ignored) while another run dir stays ignored |
| Operator acceptance of the two measured findings | D-03, SC-3 | A judgement call, not a computation — plan 01-09 T3 is a blocking `checkpoint:human-verify` | Read `experiments/LEADERBOARD.md`; confirm the four-value verdict vocabulary reads correctly and both findings are stated as measurements, not expectations |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references — no task carries a `MISSING —` verify
- [x] No watch-mode flags
- [x] Feedback latency within budget: ≤ 15 s slowest module, ≤ 45 s full suite
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved as revised (planner revision 1, 2026-08-30). Supersedes the
draft's seeded-random synthetic figures, its all-TBD task map, its illustrative
`--adjudicate` flag string, and its ~10 s full-suite latency figure.
</content>
