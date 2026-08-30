---
phase: 1
slug: measurement-rig-core
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-30
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `01-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `unittest` (stdlib, CPython 3.13.x) — no pytest, no plugins, no config file |
| **Config file** | none — default discovery via `tests/__init__.py`, `test_*.py`, `TestCase` subclasses, `test_*` methods |
| **Quick run command** | `uv run python -m unittest -v tests.test_arena_<module>` |
| **Full suite command** | `uv run python -W error::ResourceWarning -m unittest -v` |
| **Estimated runtime** | Quick: sub-second (no catalog). Full: a few seconds (167 existing + new). |

**Hard property to preserve:** the suite must continue to run with **no catalog
download and no 580 MB artifact**. Every new arena statistics/metrics module is
stdlib-pure by construction, so its tests need only in-memory fixtures.

---

## Sampling Rate

- **After every task commit:** the single relevant `tests.test_arena_*` module
  (sub-second — none touch the catalog).
- **After every plan wave:** `uv run python -W error::ResourceWarning -m unittest -v`.
  Warning-strict is **mandatory** — it is the mechanism that catches an unclosed
  SQLite handle before it becomes a leak (RESEARCH Pitfall 8).
- **Before `/gsd-verify-work`:** full suite green, **plus** the three D-02
  evaluation runs completed with records committed under `experiments/baselines/`,
  **plus** the reproducibility check (adjudicate twice, `git diff --quiet` on
  `leaderboard.json`).
- **Max feedback latency:** ~10 seconds for the full suite.

> **The three evaluation runs are NOT unit tests and must never be wired into the
> suite.** They need the 580 MB artifact and ~190 s each, which would destroy the
> "runs with no catalog download" property. Keep them as an explicit operator step
> with their outputs committed as evidence.

---

## Per-Task Verification Map

Task IDs are assigned by the planner; this table is the requirement-level contract
each task must map onto. The planner MUST ensure every row below is claimed by at
least one task's `<acceptance_criteria>`.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | MEAS-01 | — | N/A (offline, local) | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-02 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-03 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-04 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-05 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-06 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-07 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_adjudication` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-08 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-09 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-14 | T-01-01 (spec/fingerprint divergence) | Unknown override key raises `ValueError`; fingerprint never claims an unapplied config | unit | `uv run python -m unittest -v tests.test_arena_candidate` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-15 | T-01-02 (evaluator tamper) | Zero `evaluator` references outside the bridge; evaluator SHA-256 unchanged | unit | `uv run python -m unittest -v tests.test_arena_boundary` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | MEAS-16 | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-24 (determinism) | — | N/A | unit | `uv run python -m unittest -v tests.test_arena_adjudication` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-04 (evidence retention) | — | N/A | script | `git check-ignore -v experiments/baselines/<run>/sessions.jsonl` (must exit 1) | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SC-3 (end-to-end adjudication) | — | N/A | integration | arena adjudication CLI over two retained rows | ❌ W0 | ⬜ pending |

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

- [ ] `tests/test_arena_metrics.py` — MEAS-01, MEAS-02, MEAS-03, MEAS-09, MEAS-16
- [ ] `tests/test_arena_statistics.py` — MEAS-04, MEAS-05, MEAS-06, MEAS-08 (the D-01 Layer 1 known-answer fixtures)
- [ ] `tests/test_arena_adjudication.py` — MEAS-07, D-20 ordering, D-23 win rule, D-24 reproducibility
- [ ] `tests/test_arena_candidate.py` — MEAS-14
- [ ] `tests/test_arena_boundary.py` — MEAS-15 (AST walk + string-constant scan + bridge surface + evaluator SHA-256)
- [ ] A shared arena fixture builder — session-tuple constructors plus the synthetic
      promotion/demotion helpers (RESEARCH Q1). Follow the `tests/fixtures.py`
      pattern: module-level factory functions, **not** a `TestCase`, so it is
      excluded from discovery. Unlike `tests/fixtures.py` it needs no temp
      directory and no catalog.
- [ ] Framework install: **none required** — `unittest` is stdlib and the suite
      already exists.

---

## Layer-1 Known-Answer Fixture Specification

Every value below was computed against this repository during research. The planner
transcribes these directly into `<acceptance_criteria>` as exact assertions.

| Fixture | Input | Exact expected answer |
|---------|-------|----------------------|
| Degenerate bootstrap | two identical candidates | `delta == 0.0`, `ci == (0.0, 0.0)`, `se == 0.0`, `mdd == 0.0`, verdict `"no difference"` (**never** `"win"`) |
| Exact permutation | n=4, paired diffs `[0.10, 0.20, 0.30, −0.05]`, exhaustive 2⁴ enumeration | `p == 4/16 == 0.25` |
| Permutation floor | any input, R resamples | `p >= 1/(R+1)`; at R=10,000 → `p >= 9.999e-5`; `p` is never `0.0` |
| Holm textbook | `[0.01, 0.04, 0.03]` | `[0.03, 0.06, 0.06]` |
| Holm one-strong | `[0.001, 0.30, 0.40]` | `[0.003, 0.60, 0.60]` |
| Holm exact ties | `[0.02, 0.02, 0.02]` | `[0.06, 0.06, 0.06]` |
| Holm monotonicity | `[0.60, 0.01, 0.02]` | `[0.60, 0.03, 0.04]` |
| MDD closed form | `SE = 0.003779` | `MDD == 2.801585218112968 × 0.003779` (`≈ 0.010587`) |
| `E[max]` k=1 | k=1 | `0.0` |
| `E[max]` k=2 | k=2 | `1/math.sqrt(math.pi) == 0.5641895835477563` (`assertAlmostEqual`, places=12) |
| `E[max]` k=3 | k=3 | `3/(2*math.sqrt(math.pi)) == 0.8462843753216345` (places=12) |
| `E[max]` monotone | k=1..10 | strictly increasing in k |
| Binomial σ | `p=0.9, n=10` | `0.0948683298...` |
| Binomial σ | `p=0.9, n=30` | `0.0547722557...` |
| TS non-linearity (D-17) | a session set where mean-of-per-session-TS ≠ recomputed TS | the two differ — proves the resample-then-recompute path is live |
| Pairing preserved | perfectly correlated pair vs uncorrelated pair, same Δ | correlated CI width ≪ uncorrelated CI width |
| Seed determinism | same two fingerprints, two invocations | identical `delta`, `ci`, `p`, `mdd` — byte-equal serialized output |
| Synthetic large effect (Q1) | run-A sessions, promote m=10 hits to rank 1 | `ΔTS == +0.0123` (known); verdict significant, clears the 0.01 floor |
| Synthetic large effect (Q1) | run-A sessions, promote m=77 | `ΔTS == +0.0871` (known) |
| Anchor | run-A session file | `0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884`; HR@K `0.385/0.59/0.715/0.92` |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| The three D-02 evaluation runs (A, B, C) | MEAS-16, SC-3 | Needs the 580 MB artifact and ~190 s each; wiring into the suite would break the no-catalog property | Run each arena candidate; commit `sessions.jsonl` + `summary.json` under `experiments/baselines/<run-id>/`; confirm run A reproduces the anchor |
| `.gitignore` negation actually tracks `experiments/baselines/` | D-04 | Git ignore semantics must be observed against the real repo, not simulated | `git check-ignore -v experiments/baselines/<run>/sessions.jsonl` must exit 1 (not ignored) while another run dir stays ignored |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
