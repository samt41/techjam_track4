# Phase 1: Measurement Rig Core - Research

**Researched:** 2026-08-30
**Domain:** Stdlib-only resampling statistics, paired hypothesis testing, evaluation-harness architecture
**Confidence:** HIGH (every numeric claim below was executed against this repository's own data in this session)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

All of D-01 … D-24 in `.planning/phases/01-measurement-rig-core/01-CONTEXT.md` are
**LOCKED**. This research does not re-litigate any of them. Summarised for the planner:

| # | Decision |
|---|----------|
| D-01 | Validate in three layers: (1) synthetic known-answer fixtures, (2) reproduction anchor vs `RUNS.md`, (3) two adjudication controls (known-large-effect + known-near-null) |
| D-02 | Three runs: A `--lexical-mode auto --exploration disabled`; B `--lexical-mode fallback --exploration disabled`; C `--lexical-mode auto --exploration tail-only` |
| D-03 | Do not assume run C is null — measure it. Do **not** encode "expect p > 0.05" as a hard assertion |
| D-04 | Commit a reduced per-candidate record: `experiments/baselines/<run-id>/sessions.jsonl` + `summary.json`; add a `.gitignore` negation |
| D-05 | `experiments/RUNS.md` is not rewritten; it gains a pointer only |
| D-06 | New `arena/` package; `experiments/run_public.py` left byte-untouched |
| D-07 | The session-mapping wrapper is deliberately re-implemented in `arena/`, not imported |
| D-08 | Exactly one module (`arena/evaluator_bridge.py`) may import `evaluator/`; an AST test enforces it |
| D-09 | `CandidateSpec` = frozen slotted dataclass; `fingerprint` = SHA-256 over canonical `json.dumps(..., sort_keys=True)` |
| D-10 | `overrides` validated against an allow-list at construction; Phase 1 allow-list is `lexical_mode`, `exploration`, `artifact_path` |
| D-11 | Git revision recorded on every candidate; config-injection preferred where it exists |
| D-12 | `experiments/baselines/leaderboard.json` is source of truth; `experiments/LEADERBOARD.md` is a generated view; both committed |
| D-13 | Four tables: Candidates / HR@K curve / Per-scenario breakout / Pairwise adjudication |
| D-14 | Sort by TechnicalScore descending, tie-broken by fingerprint. **HR@10 is never the sort key** |
| D-15 | Per-bucket σ computed from the bucket's own observed `p` and `n`, not hardcoded |
| D-16 | Primary statistic is TechnicalScore. HR@10/MRR/MTTC reported jointly but not separately tested |
| D-17 | TechnicalScore is non-linear — resample sessions, then recompute from scratch |
| D-18 | Permutation test is paired: swap within pairs, never across candidates |
| D-19 | Holm family = candidates vs a common baseline (k−1 comparisons), **not** candidates × scenarios. Per-scenario numbers are never Holm-corrected |
| D-20 | Order: (1) Δ + CI → (2) permutation p → (3) Holm-adjust → (4) winner's-curse-correct → (5) test corrected Δ against ≥0.01 |
| D-21 | Winner's-curse correction is the order-statistic method: subtract `E[max of k draws from N(0, σ̂)]`; k printed in the report |
| D-22 | MDD reported beside every adjudication row (80% power, α=0.05) |
| D-23 | A "win" requires all three jointly: `p_holm < 0.05` AND `Δ_corrected ≥ 0.01` AND no failing HR@10 exchange-rate check |
| D-24 | Resampling deterministic and content-seeded from candidate fingerprints. Resample count = **10,000** module constant |

### Claude's Discretion (resolved in this document)

| Open item | Resolution | Section |
|-----------|-----------|---------|
| Exact `arena/` module layout | Recommended 7-module layout | Architecture Patterns |
| Bootstrap CI flavour (percentile vs BCa) | **Percentile.** BCa is disqualified — proven to crash on the degenerate case | Pattern 3 / Pitfall 4 |
| MDD derivation (closed form vs simulation) | **Normal-approximation closed form on the bootstrap SE** | Pattern 5 |
| HR@K curve from `best_rank` vs per-turn trace | **`best_rank`** — verified sufficient, exact numbers computed below | Pattern 2 |

### Deferred Ideas (OUT OF SCOPE)

- Extending `Agent` to accept belief/question/fusion overrides (Phase 3)
- De-duplicating the session-mapping wrapper (Phase 8 cleanup)
- Per-turn slate-trace-derived HR@K curve (bonus only)
- Expanded evaluation sessions and paraphrase probe (Phase 2)
- Reducing the 580 MB / 60-90 s artifact build cost (Phase 6)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEAS-01 | Leaderboard reports TechnicalScore with HR@10, MRR, MTTC broken out, overall and per scenario | Exact chain replication verified (Pattern 1); per-scenario values already computable — table in "Reproduction Anchor" |
| MEAS-02 | HR@1/@3/@5/@10 curve computed and reported for every run | Verified derivable from `best_rank` alone. Exact values: `0.385 / 0.59 / 0.715 / 0.92` |
| MEAS-03 | Per-scenario MRR and MTTC recovered without re-running the agent | **Already recoverable today** from `results.json` — see Finding F-03. Values tabulated below |
| MEAS-04 | Paired tests joined on `sample_id` (bootstrap + permutation) | Patterns 3 and 4; measured SE/MDD magnitudes in "Statistical Magnitudes" |
| MEAS-05 | Holm-Bonferroni across competing candidates | Pattern 6, with four hand-checkable fixture cases |
| MEAS-06 | MDD reported beside every leaderboard row | Pattern 5; measured MDD range 0.005-0.057 depending on candidate correlation |
| MEAS-07 | ≥0.01 TechnicalScore practical floor | Quantisation analysis: 0.01 TS = 2 best-case session flips out of 200 |
| MEAS-08 | Winner's-curse correction on a champion's gain | Pattern 7; Simpson integration verified exact to 1e-14 for k ≤ 10 |
| MEAS-09 | Per-scenario gates state bucket-size caveat | Observed σ computed: boundary 0.0949, intent_override 0.0548 — **differs from the requirement's illustrative figures for a documented reason** |
| MEAS-14 | Fingerprinted, hashable candidate spec | Pattern 8; `Agent.__init__` allow-list confirmed at `starter/agent.py:18-25` |
| MEAS-15 | Arena never imports from / modifies `evaluator/` | Pattern 9; AST checker prototyped and verified against 7 evasion forms |
| MEAS-16 | Statistics engine validated against retained historical rows | Anchor verified to full 6 dp; **RUNS.md records only 4 dp — see Pitfall 1** |
</phase_requirements>

---

## Summary

This phase is unusually well-conditioned for planning: there are no external
dependencies to select, no library APIs to verify, and no version drift risk. The
entire deliverable is stdlib arithmetic over a data shape that already exists.
The research risk is therefore concentrated entirely in **numerical method
correctness** and in **three factual errors in the upstream planning documents**
that would otherwise be encoded into acceptance criteria and fail at execution time.

The three corrections, in descending order of consequence:

1. **F-03 — the "no retained per-session data" premise (F-01) is partly wrong.**
   An untracked `results.json` at the repository root contains the **complete
   200-session record** for run A, including per-scenario MRR and MTTC. Its
   aggregates match the `RUNS.md` retained row exactly. This means the entire
   leaderboard, the HR@K curve, and MEAS-03 can be built and unit-tested
   *immediately*, before any evaluation run. D-04's remedy remains exactly right
   (the file is gitignored, carries no provenance, and could vanish), but the
   phase no longer has a hard 190-second dependency at its front.

2. **F-04 — D-02's expected value for run B is a cross-HEAD confound.** The
   `0.75 / 0.599` figure comes from the *superseded* `RUNS.md` section measured at
   HEAD `e76b3ab`, where the FTS baseline was `0.76 / 0.609233`. The true
   lexical-mode effect at that HEAD was **ΔTS ≈ 0.0102**, not 0.17. D-02's 0.17
   subtracts a current-HEAD number from a superseded-HEAD number and so measures
   the extraction fixes, not the lexical mode. Run B is very likely a *small*
   effect at current HEAD, not a large one — so the "known-large-effect" arm of
   D-01 Layer 3 has no guaranteed source. Recommended fix in "Open Questions Q1":
   apply D-03's measure-don't-assume rule to B as well, and obtain the guaranteed
   large-effect control **synthetically** from run A's own sessions at zero cost.

3. **F-05 — the rig is far more powerful than PROJECT.md implies, because of
   pairing.** PROJECT.md's "3,900-15,700 paired sessions to detect ΔTS = 0.01"
   holds only for weakly-correlated candidates. Measured on this repository's real
   200 sessions, a *realistic* ranking candidate (promote 10 sessions to rank 1)
   yields ΔTS = +0.0123 against MDD = 0.0106 — **detectable at n = 200**. The
   MEAS-07 floor and the achievable MDD are well matched, not hopeless. This is
   the number that makes MEAS-06 meaningful, and it should be stated in
   `LEADERBOARD.md`.

Beyond the corrections, the two open discretionary questions are settled by
evidence rather than preference. **BCa is disqualified**: the ΔTS bootstrap
distribution is severely lattice-valued (26 distinct values in 5,000 replicates
for a one-session change; 19% of replicates exactly tie the observed statistic),
and for genuinely identical candidates `statistics.NormalDist().inv_cdf(0.0)`
raises `StatisticsError` — BCa crashes on precisely the degenerate case D-01
Layer 1 requires as a fixture. **MDD should use the normal-approximation closed
form on the bootstrap SE** (`2.801585 × SE_boot`), which is consistent with D-17's
non-linear-statistic treatment, reuses a quantity already computed, and is exactly
unit-testable. The one item flagged as "most implementation-risky" — `E[max of k
draws from N(0, σ̂)]` — is not risky at all: composite Simpson integration over
`k·Φ(x)^(k-1)·φ(x)` on `[-9, 9]` with 2,000 panels reproduces the known closed
forms to **1e-15 in 0.6 ms**, using only `statistics.NormalDist`.

**Primary recommendation:** Build and unit-test the entire leaderboard and
statistics engine against the existing `results.json` first, with a synthetic
degradation of run A supplying an exactly-known large-effect control; treat the
three evaluation runs as provenance-attachment and cross-validation, not as
prerequisites — and do not assert a significant A-vs-B result.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Candidate declaration + fingerprinting | Domain (`arena/candidate.py`) | — | Frozen dataclass with `validate()`; no I/O, so it is trivially testable |
| Evaluator invocation | Adapter seam (`arena/evaluator_bridge.py`) | — | D-08 requires exactly one module to touch `evaluator/`; this is the ports-and-adapters precedent already set by `ProductSearchBackend` |
| Session→sample mapping | Adapter (`arena/arena.py`) | — | Wraps `Agent`; must not import `experiments.run_public` (D-07) |
| Run persistence (atomic publish) | Adapter (`arena/store.py`) | — | Filesystem concern; reuse `_publish` pattern from `run_public.py:135-150` |
| Metric computation (HR@K, MRR, MTTC, TS) | Domain (`arena/metrics.py`) | — | Pure function of a session tuple; **no evaluator import** — the chain is re-implemented and cross-validated against the anchor |
| Resampling statistics | Domain (`arena/statistics.py`) | — | Pure; only `random`, `statistics`, `math`, `hashlib` |
| Adjudication policy (D-20 ordering, D-23 win rule) | Domain (`arena/adjudication.py`) | `arena/statistics.py` | Policy is separable from arithmetic; keeps D-20's ordering testable in isolation |
| Report rendering | Presentation (`arena/leaderboard.py`) | — | JSON is source of truth, Markdown is a generated view (D-12) |
| Import-boundary enforcement | Test (`tests/test_arena_boundary.py`) | — | A property of the package, not of any module — belongs in the suite |

**Tier note.** There is no client/server/network tier in this project. The
"tiers" above are the repository's existing layering (entry → coordinator →
domain → adapter), and `arena/` sits as a *sibling* entry-layer package to
`experiments/`, never imported by `starter/`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `statistics` | stdlib (CPython 3.13.8) | `NormalDist` (`cdf`, `pdf`, `inv_cdf`), `fmean`, `pstdev`, `median` | `NormalDist.inv_cdf` is an exact Acklam/Wichura-class inverse; the only normal quantile needed. `[VERIFIED: executed in-session]` |
| `random` | stdlib | `random.Random(seed)` instances for bootstrap and permutation | Mersenne Twister; reproducible across CPython versions for a fixed integer seed. Instance-based, never module-level (D-24) |
| `hashlib` | stdlib | SHA-256 for `CandidateSpec.fingerprint` and for deriving resample seeds | Already the repo's fingerprinting primitive (`run_public.py:275-280`) |
| `math` | stdlib | `sqrt`, `isclose`, `fsum` | `math.fsum` for the Simpson accumulator avoids float drift |
| `json` | stdlib | Canonical `sort_keys=True` serialization | Fingerprints depend on canonical form (existing convention) |
| `ast` | stdlib | D-08 import-boundary test | Static analysis without executing the module — the point of the test |
| `dataclasses` | stdlib | `@dataclass(frozen=True, slots=True)` | Repo-wide convention |
| `unittest` | stdlib | Test runner | 167 existing tests; no pytest (`dependencies = []`) |
| `subprocess` | stdlib | `git rev-parse HEAD` via `code_revision()` | Existing at `experiments/analyze_public.py:229` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `collections.defaultdict` | stdlib | Per-scenario grouping | Mirrors `local_evaluator.py:281` |
| `pathlib` | stdlib | All path handling | Repo convention; keeps Windows/POSIX parity |
| `os` / `shutil` / `tempfile` | stdlib | Atomic publish | Reuse the `_publish` pattern verbatim |
| `itertools` | stdlib | Exhaustive enumeration in Layer-1 permutation fixtures | Only in tests (2^n over n ≤ 8) |
| `fractions.Fraction` | stdlib | Exact rational assertions in permutation fixtures | Optional; makes `p = 4/16` an exact assertion |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled bootstrap | `scipy.stats.bootstrap` | **Forbidden.** `pyproject.toml` has `dependencies = []`; adding scipy destroys the "zero runtime dependencies" Feasibility claim (POS-03) and the offline guarantee |
| Hand-rolled `NormalDist` quantiles | `scipy.stats.norm.ppf` | Same. `statistics.NormalDist.inv_cdf` is exact enough — verified against `z_0.975 = 1.9599639845400536` |
| Percentile CI | BCa CI | **Rejected on evidence** — see Pitfall 4. BCa's `z0` is uncomputable on the degenerate case |
| Simpson integration for `E[max_k]` | Blom approximation `Φ⁻¹((k−0.375)/(k+0.25))` | Blom errs by 2.5e-2 at k=2 vs 3.8e-15 for Simpson, at no meaningful cost saving. Keep Blom **as a test cross-check only** |
| Simpson integration | Monte-Carlo estimate of `E[max_k]` | Introduces a second RNG dependency into a correction that must be byte-deterministic. Rejected |
| Paired permutation on TS | McNemar's test on discordant sessions | McNemar tests HR@10 only, not the composite TS (D-16). Its *insight* is still valuable — see "Why pairing wins" |

**Installation:**

```bash
# None. Every dependency above ships with CPython 3.10+.
uv sync   # creates .venv from the existing lockfile (1 virtual root package)
```

**Version verification (executed 2026-08-30):**

```text
Python 3.13.8          uv 0.9.4          sqlite 3.50.4 (FTS5: OK)
```

---

## Package Legitimacy Audit

**Not applicable — this phase installs zero external packages.**

`pyproject.toml` declares `dependencies = []`, `uv.lock` contains exactly one
entry (the virtual root project itself), and CLAUDE.md makes runtime purity a
hard invariant. No registry lookup, slopcheck run, or postinstall audit is
required because no package is added.

**Planner action:** any plan task that proposes `pip install` / `uv add` of a
third-party package in this phase is out of scope and violates a hard invariant.
The correct response is to hand-roll the routine using the stdlib primitives in
the Standard Stack table.

---

## Architecture Patterns

### System Architecture Diagram

```text
                     ┌──────────────────────────────────────┐
   CandidateSpec ───▶│  arena/candidate.py                  │
   (name, revision,  │  validate() → allow-list (D-10)      │
    overrides,       │  fingerprint = sha256(canonical json)│
    input hashes)    └──────────────┬───────────────────────┘
                                    │ fingerprint
                                    ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  arena/arena.py — run one candidate                           │
   │                                                               │
   │   Agent(**overrides) ──▶ _SampleMappingAgent (D-07 dup)       │
   │                                │ records reset order          │
   │                                ▼                              │
   │            ┌───────────────────────────────────┐              │
   │            │ arena/evaluator_bridge.py  ◀══════╪══ THE ONLY   │
   │            │  re-exports: evaluate,            │   SEAM (D-08)│
   │            │   catalog_index, load_jsonl       │              │
   │            └──────────────┬────────────────────┘              │
   │                           │ opaque call                       │
   │                           ▼                                   │
   │              evaluator/local_evaluator.evaluate()             │
   │                           │                                   │
   │                           │ returns {..., sessions:[...]}     │
   │                           ▼                                   │
   │            join UUID → sample_id  (AFTER evaluate returns;    │
   │                                    ground truth never enters  │
   │                                    the Agent)                 │
   └───────────────────────────┬───────────────────────────────────┘
                               │ tuple[SessionOutcome, ...]
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   ┌─────────────────────┐          ┌──────────────────────────────┐
   │ arena/store.py      │          │ arena/metrics.py             │
   │ atomic publish      │          │ hr_at_k / mrr / mttc /       │
   │ experiments/        │          │ efficiency / technical_score │
   │  baselines/<id>/    │          │ per-scenario + binomial σ    │
   │   sessions.jsonl    │          └──────────────┬───────────────┘
   │   summary.json      │◀── reload, no re-run ───┘
   └─────────────────────┘                         │
                                                   ▼
                        ┌──────────────────────────────────────────┐
                        │ arena/statistics.py   (pure, seeded)     │
                        │  paired_bootstrap  → Δ, percentile CI, SE│
                        │  paired_permutation→ p = (c+1)/(R+1)     │
                        │  holm_bonferroni   → adjusted p (monoton)│
                        │  minimum_detectable_difference           │
                        │  expected_max_of_k → Simpson on NormalDist│
                        └──────────────┬───────────────────────────┘
                                       ▼
                        ┌──────────────────────────────────────────┐
                        │ arena/adjudication.py  (D-20 ORDERING)   │
                        │  1 Δ + CI → 2 perm p → 3 Holm            │
                        │  → 4 winner's-curse correct champion     │
                        │  → 5 corrected Δ vs ≥0.01 floor          │
                        │  → D-23 three-part win rule              │
                        └──────────────┬───────────────────────────┘
                                       ▼
                        ┌──────────────────────────────────────────┐
                        │ arena/leaderboard.py                     │
                        │  leaderboard.json  (SOURCE OF TRUTH)     │
                        │        │ render                          │
                        │        ▼                                 │
                        │  experiments/LEADERBOARD.md (view, D-12) │
                        └──────────────────────────────────────────┘
```

### Recommended Project Structure

```text
arena/
├── __init__.py            # empty, matches experiments/__init__.py
├── evaluator_bridge.py    # THE ONLY module importing evaluator/ (D-08)
├── candidate.py           # CandidateSpec: frozen+slots, validate(), fingerprint
├── metrics.py             # session→metric chain; replicates the evaluator exactly
├── statistics.py          # bootstrap / permutation / holm / mdd / expected_max_of_k
├── adjudication.py        # D-20 ordering + D-23 win rule; imports statistics only
├── store.py               # atomic publish + load of experiments/baselines/
├── leaderboard.py         # leaderboard.json ⇄ LEADERBOARD.md
├── arena.py               # run_candidate(): Agent + bridge + sample mapping
└── run_arena.py           # CLI entry (python -m arena.run_arena)

tests/
├── test_arena_metrics.py       # anchor + HR@K + per-scenario σ
├── test_arena_statistics.py    # D-01 Layer 1 known-answer fixtures
├── test_arena_adjudication.py  # D-20 ordering, D-23 win rule
├── test_arena_candidate.py     # fingerprint stability + allow-list rejection
└── test_arena_boundary.py      # D-08 AST import-boundary invariant
```

**Import direction (must hold, mirrors the repo's existing acyclic rule):**

```text
run_arena → arena → {evaluator_bridge, candidate, store, metrics}
leaderboard → {adjudication, metrics}
adjudication → statistics
metrics, statistics, candidate → stdlib only
```

`statistics.py`, `metrics.py`, `candidate.py` and `adjudication.py` import **no
project module at all**. That is what makes the Layer-1 fixtures runnable in the
existing 167-test suite with no catalog download.

> **Naming caution.** `arena/statistics.py` shadows the stdlib `statistics`
> module *within the `arena` package only* if a relative import is used. The repo
> uses absolute imports exclusively (`from arena.statistics import ...`), and
> `from __future__ import annotations` plus absolute-import semantics in Python 3
> mean `import statistics` inside `arena/statistics.py` still resolves to the
> stdlib. This is safe, but if the planner prefers zero ambiguity, name it
> `arena/resampling.py`.

---

### Pattern 1: Replicate the evaluator's metric chain exactly, including its rounding

**What:** `arena/metrics.py` re-implements the metric chain rather than importing
it (D-08 forbids importing `metric_summary`). The replication must reproduce the
evaluator's **rounding order**, not just its algebra.

**Why it matters:** `evaluate()` rounds `hit_rate_at_10`, `mrr` and `mttc` to 6 dp
*before* computing `efficiency` and `technical_score`
(`evaluator/local_evaluator.py:196-201`, then `:279-280`). Reproducing the
MEAS-16 anchor to the digit requires the same order.

**Verified in-session:** replicating this chain from `results.json`'s `sessions`
array alone reproduces the evaluator's own reported aggregates **exactly**:
`(0.92, 0.524466, 3.425)` → `efficiency 0.7575`, `technical_score 0.76884`.

```python
# Source: transcribed from evaluator/local_evaluator.py:188-201, 279-280.
# Deliberately re-implemented, not imported: arena must not import evaluator
# internals (D-08). Cross-agreement with the evaluator is the validation
# evidence (D-06), so the duplication is load-bearing, not debt.
MAX_TURNS = 10   # evaluator/local_evaluator.py:15


def metric_summary(sessions: tuple[SessionOutcome, ...]) -> MetricSummary:
    count = len(sessions)
    if count == 0:
        raise ValueError("metric summary requires at least one session")
    hit_rate = sum(1 for item in sessions if item.hit) / count
    mrr = statistics.fmean(item.reciprocal_rank for item in sessions)
    mttc = statistics.fmean(
        item.first_hit_turn if item.first_hit_turn is not None else MAX_TURNS + 1
        for item in sessions
    )
    return MetricSummary(
        sample_count=count,
        hit_rate_at_10=round(hit_rate, 6),
        mrr=round(mrr, 6),
        mttc=round(mttc, 6),
    )


def technical_score(summary: MetricSummary) -> float:
    # Efficiency is a function of the *rounded* mean, matching the evaluator.
    efficiency = max(0.0, min(1.0, (11.0 - summary.mttc) / 10.0))
    return round(
        0.50 * summary.hit_rate_at_10 + 0.30 * summary.mrr + 0.20 * efficiency,
        6,
    )
```

**Empty-bucket guard.** `metric_summary` in the evaluator returns
`{"mttc": None}` for an empty session list (`local_evaluator.py:190`), which would
make `efficiency` raise. The arena never resamples *within* a scenario bucket
(D-19 forbids per-scenario hypothesis testing), so this cannot occur in the
bootstrap — but `raise ValueError` on empty is the correct defensive contract and
matches the repo's fail-closed convention.

---

### Pattern 2: Derive the HR@K curve from `best_rank` alone

**What:** `HR@K = |{s : s.best_rank is not None and s.best_rank <= K}| / n`.

**When:** always. **Verified sufficient** — this needs only `sessions.jsonl`,
never the 10,400-event trace, which is what keeps D-04's committed record at
~26 KB per candidate.

**Verified values for run A (executed in-session):**

| K | HR@K | count |
|---|------|-------|
| 1 | 0.385 | 77/200 |
| 3 | 0.590 | 118/200 |
| 5 | 0.715 | 143/200 |
| 10 | 0.920 | 184/200 |

`best_rank` takes every value in `1..10` and never exceeds 10 (the evaluator caps
the slate at `TOP_K = 10` in `normalize_recommendations`, `local_evaluator.py:107`),
so the curve is complete and monotone by construction. `HR@10` from the curve
equals the reported `hit_rate_at_10` — a free internal consistency assertion the
planner should encode as a test.

```python
def hit_rate_curve(
    sessions: tuple[SessionOutcome, ...],
    depths: tuple[int, ...] = (1, 3, 5, 10),
) -> dict[int, float]:
    count = len(sessions)
    return {
        depth: round(
            sum(
                1 for item in sessions
                if item.best_rank is not None and item.best_rank <= depth
            ) / count,
            6,
        )
        for depth in depths
    }
```

---

### Pattern 3: Paired bootstrap — resample sample_ids once, recompute both candidates

**What:** D-17's non-linear-statistic procedure. The single most important detail
is that **one index vector is drawn per replicate and applied to both candidates**.
Drawing two independent index vectors would destroy the pairing and inflate the SE
by roughly the correlation factor — for the realistic correlated case that is a
**4-10× overstatement** of the SE, which would make every real candidate look
undetectable.

**Procedure:**
1. Join both candidates' sessions on `sample_id` into an ordered pair list.
   Assert equal length and identical `sample_id` sequence; raise otherwise.
2. For each of R = 10,000 replicates: draw `n` indices uniformly with replacement.
3. Apply **the same** index vector to candidate A and candidate B.
4. Recompute `technical_score` from scratch on each resampled set (Pattern 1).
5. Record `Δ_r = TS(A_r) − TS(B_r)`.
6. CI = the 2.5th and 97.5th **percentiles** of the sorted `Δ` vector.
   SE = `statistics.pstdev(Δ)`.

```python
def paired_bootstrap(
    baseline: tuple[SessionOutcome, ...],
    candidate: tuple[SessionOutcome, ...],
    *,
    seed: int,
    resamples: int = RESAMPLE_COUNT,   # 10_000 (D-24)
) -> BootstrapResult:
    if len(baseline) != len(candidate):
        raise ValueError("paired bootstrap requires equal-length candidates")
    rng = random.Random(seed)          # instance, never the module (D-24)
    count = len(baseline)
    deltas: list[float] = []
    for _ in range(resamples):
        # ONE index vector, applied to BOTH arms. Two independent draws would
        # silently discard the pairing and inflate the standard error.
        indices = [rng.randrange(count) for _ in range(count)]
        deltas.append(
            technical_score(metric_summary(tuple(candidate[i] for i in indices)))
            - technical_score(metric_summary(tuple(baseline[i] for i in indices)))
        )
    deltas.sort()
    return BootstrapResult(
        delta=technical_score(metric_summary(candidate))
        - technical_score(metric_summary(baseline)),
        lower=deltas[int(0.025 * resamples)],
        upper=deltas[int(0.975 * resamples) - 1],
        standard_error=statistics.pstdev(deltas),
        resamples=resamples,
    )
```

**Percentile, not BCa — settled.** See Pitfall 4. Percentile is also the only
flavour that degrades gracefully to a zero-width `[0.0, 0.0]` interval when the
two candidates are identical, which is a required Layer-1 fixture.

---

### Pattern 4: Paired permutation — sign-flip within pairs, with the (c+1)/(R+1) convention

**What:** D-18's test. For each session independently, with probability ½ swap
that session's (A, B) outcomes; recompute ΔTS on the permuted arms; accumulate the
two-sided null.

**Why `(count + 1) / (R + 1)`:** the observed (unpermuted) assignment is itself a
member of the permutation null under the exchangeability hypothesis. Including it
guarantees `p > 0` — a Monte-Carlo permutation test can never honestly report
`p = 0`, only `p ≤ 1/(R+1)`. At R = 10,000 the floor is `p = 9.999e-5`. Omitting
the `+1` produces anti-conservative p-values and, at the extreme, a literal `0.0`
that would sail through a `p < 0.05` gate on zero evidence. This is the standard
Phipson–Smyth correction and it is **not optional** for a rig whose entire purpose
is honesty.

```python
def paired_permutation(
    baseline: tuple[SessionOutcome, ...],
    candidate: tuple[SessionOutcome, ...],
    *,
    seed: int,
    resamples: int = RESAMPLE_COUNT,
) -> PermutationResult:
    rng = random.Random(seed)
    observed = (
        technical_score(metric_summary(candidate))
        - technical_score(metric_summary(baseline))
    )
    threshold = abs(observed) - 1e-12      # tolerate float noise on exact ties
    count = 0
    for _ in range(resamples):
        left: list[SessionOutcome] = []
        right: list[SessionOutcome] = []
        for index in range(len(baseline)):
            if rng.getrandbits(1):
                left.append(candidate[index])
                right.append(baseline[index])
            else:
                left.append(baseline[index])
                right.append(candidate[index])
        permuted = (
            technical_score(metric_summary(tuple(right)))
            - technical_score(metric_summary(tuple(left)))
        )
        if abs(permuted) >= threshold:
            count += 1
    # +1 in both terms: the observed assignment is itself a valid permutation,
    # so a Monte-Carlo permutation p can never be 0 (Phipson & Smyth).
    return PermutationResult(
        observed=observed,
        p_value=(count + 1) / (resamples + 1),
        resamples=resamples,
    )
```

**Layer-1 exact fixture (verified in-session).** With n = 4 and paired differences
`[0.10, 0.20, 0.30, −0.05]`, exhaustive enumeration of all 2⁴ = 16 sign
assignments gives `|stat| ≥ |observed|` in exactly **4 of 16**, so the exact
two-sided p is **4/16 = 0.25**. A test that enumerates rather than samples pins
the convention with no RNG involved.

---

### Pattern 5: MDD — normal-approximation closed form on the bootstrap SE

**Resolution of the open item.** Use the closed form, applied to the **bootstrap**
SE of ΔTechnicalScore:

```text
MDD = (z_{1-α/2} + z_{1-β}) × SE_boot(ΔTS)
    = (1.9599639845400536 + 0.8416212335729144) × SE_boot
    = 2.801585218112968 × SE_boot        (α = 0.05 two-sided, power = 80%)
```

**Why the bootstrap SE and not `sd_d / √n`:** D-17 establishes that TechnicalScore
is not a mean of per-session values, so there is no per-session "difference"
whose SD can be taken. `SE_boot` *is* the SE of the statistic actually being
tested, it is already computed by Pattern 3 at zero extra cost, and it
automatically inherits the pairing benefit.

**Why not simulation:** a simulated MDD requires an assumed effect-injection model
(which sessions improve, and by how much), which is an extra unfalsifiable
assumption; it adds a second RNG surface to a number that must be byte-reproducible;
and it is materially harder to pin with a known-answer fixture. The closed form is
one line and is exactly testable: `MDD == 2.801585218112968 × SE` for any SE.

```python
Z_ALPHA_TWO_SIDED = NormalDist().inv_cdf(0.975)   # 1.9599639845400536
Z_POWER_80 = NormalDist().inv_cdf(0.80)           # 0.8416212335729144
MDD_MULTIPLIER = Z_ALPHA_TWO_SIDED + Z_POWER_80   # 2.801585218112968


def minimum_detectable_difference(standard_error: float) -> float:
    """Smallest true delta detectable at 80% power, alpha=0.05, given this SE."""
    if standard_error < 0.0:
        raise ValueError("standard error must be non-negative")
    return MDD_MULTIPLIER * standard_error
```

**Report the MDD even when — especially when — the result is null.** That is the
entire content of MEAS-06 and the honesty claim the phase is built on.

---

### Pattern 6: Holm-Bonferroni step-down with explicit monotonicity enforcement

**Algorithm** over the k−1 comparisons against the common baseline (D-19):
1. Sort raw p-values ascending, tie-broken on a **stable key** (input index) to
   preserve the determinism invariant.
2. For the rank-`i` (0-based) p-value out of `m`, compute `(m − i) × p_i`.
3. Take a **running maximum** across the sorted sequence — this is the
   monotonicity enforcement, and it is the step most commonly omitted.
4. Clamp to `1.0`.
5. Map back to input order.

Without step 3 the adjusted p-values can decrease as raw p increases, which is
incoherent and can make a *weaker* result look stronger than a stronger one.

```python
def holm_bonferroni(p_values: tuple[float, ...]) -> tuple[float, ...]:
    total = len(p_values)
    order = sorted(range(total), key=lambda i: (p_values[i], i))  # stable tie-break
    adjusted = [0.0] * total
    running = 0.0
    for rank, index in enumerate(order):
        # Monotonicity: an adjusted p can never fall below one that precedes it.
        running = max(running, min(1.0, (total - rank) * p_values[index]))
        adjusted[index] = running
    return tuple(adjusted)
```

**Layer-1 fixtures (all verified in-session, hand-checkable):**

| Case | Raw p | Adjusted p |
|------|-------|-----------|
| textbook | `[0.01, 0.04, 0.03]` | `[0.03, 0.06, 0.06]` |
| one strong | `[0.001, 0.30, 0.40]` | `[0.003, 0.60, 0.60]` |
| exact ties | `[0.02, 0.02, 0.02]` | `[0.06, 0.06, 0.06]` |
| monotonicity bites | `[0.60, 0.01, 0.02]` | `[0.60, 0.03, 0.04]` |

The "textbook" case is the sharpest test: naive Holm gives `0.04 × 1 = 0.04` for
the third element, which the running maximum correctly raises to `0.06`. A
non-monotone implementation returns `[0.03, 0.04, 0.06]` and passes a careless test.

---

### Pattern 7: Winner's-curse correction — `E[max of k]` by Simpson integration

**This was flagged as the highest-risk item. It is not.** `E[max of k iid
N(0,1)]` has no elementary closed form for k > 5, but it has a clean integral that
composite Simpson evaluates to machine precision using only `NormalDist`:

```text
E[max_k] = ∫ x · k · Φ(x)^(k−1) · φ(x) dx
```

**Measured accuracy (executed in-session), integrating over `[-9, 9]`:**

| k | Reference | Simpson (n=2000 panels) | Error | Blom approx | Blom error |
|---|-----------|------------------------|-------|-------------|-----------|
| 2 | 0.5641895835 | 0.5641895835 | **3.8e-15** | 0.5894558 | 2.5e-02 |
| 3 | 0.8462843753 | 0.8462843753 | **6.8e-15** | 0.8694238 | 2.3e-02 |
| 5 | 1.1629644736 | 1.1629644736 | **3.1e-15** | 1.1797611 | 1.7e-02 |
| 10 | 1.5387527308 | 1.5387527308 | **1.7e-14** | 1.5466353 | 7.9e-03 |

Cost: **0.6 ms** at 2,000 panels; 5.9 ms at 20,000. Fully deterministic — no RNG.
Blom's ~2.5e-2 relative error at k=2 translates to ~5e-4 TechnicalScore at
σ̂ = 0.02, which is 5% of the entire MEAS-07 floor. Use Simpson; keep Blom only as
an independent cross-check in a test.

**Exact closed forms available as unbreakable test anchors:**
- `E[max of 2] = 1/√π = 0.5641895835477563`
- `E[max of 3] = 3/(2√π) = 0.8462843753216345`
- `E[max of 1] = 0.0`

```python
def expected_max_of_k(k: int, *, panels: int = 2000, bound: float = 9.0) -> float:
    """E[max of k iid standard normals], by composite Simpson on NormalDist.

    Deterministic (no RNG) so the correction is byte-reproducible, and exact to
    ~1e-14 for k <= 10 -- verified against the closed forms 1/sqrt(pi) (k=2) and
    3/(2*sqrt(pi)) (k=3).
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if k == 1:
        return 0.0
    if panels % 2:
        raise ValueError("Simpson's rule requires an even panel count")
    normal = NormalDist()
    width = (2.0 * bound) / panels

    def integrand(x: float) -> float:
        return x * k * (normal.cdf(x) ** (k - 1)) * normal.pdf(x)

    terms = [integrand(-bound), integrand(bound)]
    for step in range(1, panels):
        weight = 4.0 if step % 2 else 2.0
        terms.append(weight * integrand(-bound + step * width))
    return math.fsum(terms) * width / 3.0


def winners_curse_correction(standard_error: float, k: int) -> float:
    """Expected upward selection bias from taking the best of k candidates."""
    return standard_error * expected_max_of_k(k)
```

**σ̂ is the paired-difference SE, per D-21** — i.e. `SE_boot(ΔTS)` from Pattern 3,
**not** the 0.019 absolute HR@10 binomial SE quoted in PROJECT.md and PITFALLS.md.
Those are different quantities, and the distinction changes the reported number by
roughly an order of magnitude. See Pitfall 6 — this must be explained in
`LEADERBOARD.md` or Phase 5's threshold comparison will be misread.

---

### Pattern 8: `CandidateSpec` — canonical-JSON fingerprint with allow-list validation

```python
_ALLOWED_OVERRIDES = frozenset({"lexical_mode", "exploration", "artifact_path"})
# Exactly what starter/agent.py:18-25 accepts today. Phase 3 extends
# Agent.__init__ and this allow-list together, in one change (D-10) -- a
# fingerprint must never claim to describe a configuration that was not applied.


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    name: str
    code_revision: str
    overrides: tuple[tuple[str, str], ...]   # ordered pairs: hashable + canonical
    catalog_sha256: str
    dataset_sha256: str

    def validate(self) -> None:
        if not self.name:
            raise ValueError("candidate name must not be empty")
        keys = [key for key, _ in self.overrides]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate overrides contain a duplicate key")
        if sorted(keys) != keys:
            raise ValueError("candidate overrides must be in sorted key order")
        unknown = sorted(set(keys) - _ALLOWED_OVERRIDES)
        if unknown:
            raise ValueError(f"unknown candidate override keys: {unknown}")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "name": self.name,
                "code_revision": self.code_revision,
                "overrides": dict(self.overrides),
                "catalog_sha256": self.catalog_sha256,
                "dataset_sha256": self.dataset_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

**Three subtleties the planner should encode as tests:**

1. **`tuple[tuple[str, str], ...]` not `dict`** — a `dict` field breaks
   `frozen=True` hashability and admits insertion-order variation. Sorted pairs
   make the fingerprint order-independent by construction, and `validate()`
   enforces the sort so an unsorted construction fails loudly rather than
   producing a second fingerprint for the same configuration.
2. **`separators=(",", ":")`** — pins whitespace so the digest cannot drift with
   a future `indent` change.
3. **Fingerprint stability across processes** — SHA-256 over a canonical string,
   never `hash()`, which is salted per process by `PYTHONHASHSEED`.

**`code_revision()` gap (`experiments/analyze_public.py:229`).** It runs
`git rev-parse HEAD` and returns `"unknown_revision"` on failure — but it does
**not** record whether the working tree is dirty. A candidate run with uncommitted
changes records a SHA that does not describe the code that ran, silently defeating
D-11's attributability goal. Recommend the arena compute its own dirty flag
(`git status --porcelain` non-empty → append `"-dirty"` or add a
`code_revision_dirty: bool` field) **without modifying `analyze_public.py`**, which
D-06's spirit keeps stable. Verified working in-session.

**Seed derivation (D-24):**

```python
def _pair_seed(baseline: CandidateSpec, candidate: CandidateSpec, label: str) -> int:
    """Content-seeded, never clock-seeded -- two runs must agree byte for byte."""
    digest = hashlib.sha256(
        f"{baseline.fingerprint}\0{candidate.fingerprint}\0{label}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big")
```

The `label` (`"bootstrap"` / `"permutation"`) prevents the two procedures sharing
a stream. Note this seed is **not symmetric** in the two candidates — fix the
argument order to (baseline, candidate) at the call site and test that a
comparison is reproducible, not that it is order-invariant.

---

### Pattern 9: The D-08 import boundary as an AST test

**Verified against seven evasion forms in-session.** A pure `ast.Import` /
`ast.ImportFrom` walk catches static imports including aliased, function-local and
relative forms — but **misses `importlib.import_module("evaluator...")` and
`__import__("evaluator...")`**. Adding a scan of string constants closes both.

| Form | AST import walk | String-constant scan | Caught |
|------|----------------|---------------------|--------|
| `import evaluator.local_evaluator` | ✓ | — | yes |
| `from evaluator.local_evaluator import evaluate` | ✓ | — | yes |
| `import evaluator.local_evaluator as ev` | ✓ | — | yes |
| `from ..evaluator import local_evaluator` | ✓ | — | yes |
| function-local `from evaluator... import` | ✓ | — | yes |
| `importlib.import_module('evaluator...')` | ✗ | ✓ | yes |
| `__import__('evaluator...')` | ✗ | ✓ | yes |
| clean control (`from starter.agent import Agent`) | — | — | no false positive |

```python
class ArenaImportBoundaryTest(unittest.TestCase):
    """MEAS-15 / D-08 as a machine-checked invariant, not a promise."""

    def test_only_the_bridge_module_references_the_evaluator(self) -> None:
        package = Path(__file__).resolve().parent.parent / "arena"
        offenders: dict[str, list[str]] = {}
        for path in sorted(package.glob("*.py")):
            if path.name == "evaluator_bridge.py":
                continue          # the single permitted seam (D-08)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            found: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found += [
                        alias.name for alias in node.names
                        if alias.name.split(".")[0] == "evaluator"
                    ]
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module.split(".")[0] == "evaluator" or (
                        node.level and "evaluator" in module.split(".")
                    ):
                        found.append(module)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    # Closes the importlib / __import__ dynamic-import hole.
                    if node.value.split(".")[0] == "evaluator":
                        found.append(node.value)
            if found:
                offenders[path.name] = found

        self.assertEqual(offenders, {})
```

**Two companion tests the planner should add:**

- **Bridge surface is minimal.** Assert `evaluator_bridge.py`'s AST contains only
  the import of `evaluate`, `catalog_index`, `load_jsonl` and an `__all__` — i.e.
  no other name is pulled through the seam. This is what makes
  "`evaluate()` as an opaque function" (Success Criterion 5) literally true.
- **Evaluator is byte-unmodified.** Assert
  `git diff --quiet origin/tiktok/starter -- evaluator/` (or a pinned SHA-256 of
  `evaluator/local_evaluator.py`). PROJECT.md already relies on this being empty;
  pinning it as a test turns the strongest Technical Execution claim in the
  project into a continuously-verified fact. Prefer the SHA-256 form — it does not
  require the `origin/tiktok/starter` ref to be fetched.

---

### Pattern 10: Atomic publish (reuse, do not reinvent)

Copy the `_publish` pattern from `experiments/run_public.py:135-150` verbatim,
including the Windows rationale comment. `Path.rename` maps to `os.rename`, which
on Windows raises `WinError 183` when the destination exists; `os.replace` is the
cross-platform overwrite primitive.

```python
def _publish(working: Path, destination: Path) -> None:
    try:
        os.replace(working, destination)
    except OSError:
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(working, destination)
```

**One Windows caveat not covered by the original:** `os.replace` on a *directory*
fails with `PermissionError` if any process holds a handle inside it — including
an open SQLite connection or an unclosed trace file. The existing code avoids
this by closing the agent in a `finally` before publishing
(`run_public.py:94-97`). The arena must do the same.

---

### Anti-Patterns to Avoid

- **Averaging per-session TechnicalScores.** There is no such thing. Efficiency is
  a function of `mean(MTTC)`, not a mean of per-session efficiencies (D-17). Any
  code path that computes a "per-session technical score" is wrong.
- **Two independent bootstrap index vectors.** Silently discards the pairing and
  inflates the SE 4-10× for correlated candidates — turning every real Phase 3
  candidate into "not detectable."
- **Module-level `random.seed()`.** Global mutable state; a test that runs before
  yours changes your answer. Always `random.Random(seed)` instances (D-24).
- **`p = count / resamples`.** Anti-conservative; can report a literal `0.0`. Use
  `(count + 1) / (resamples + 1)`.
- **Holm without the running maximum.** Produces non-monotone adjusted p-values.
- **Applying the ≥0.01 floor to the raw Δ.** D-20 step 5 requires the *corrected*
  Δ. Applying it to the raw Δ lets a candidate clear the floor on selection bias
  alone.
- **Holm-correcting the per-scenario numbers.** D-19 forbids it. Per-scenario
  results are descriptive non-inferiority gates with stated σ, reported alongside
  an explicit sentence saying the omission is deliberate.
- **Sorting the leaderboard by HR@10.** D-14. `RUNS.md` does this and PROJECT.md
  names it as actively misleading.
- **Importing `experiments.run_public` from `arena/`.** Transitively pulls
  `evaluator.local_evaluator` (`run_public.py:13`) into the arena and defeats D-08.
  This is exactly why D-07 mandates duplication.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Normal quantile `z_{1−α/2}` | Rational approximation of `Φ⁻¹` | `statistics.NormalDist().inv_cdf(p)` | Exact to double precision; verified `z_0.975 = 1.9599639845400536` |
| Normal CDF / PDF | `0.5*(1+erf(x/√2))` by hand | `NormalDist().cdf` / `.pdf` | Same values, no sign/scale bugs |
| Atomic directory publish | `Path.rename` + existence check | The `_publish` pattern (`run_public.py:135-150`) | Windows `WinError 183` is already handled there, with the rationale documented |
| Chunked file SHA-256 | A fresh read loop | The `_sha256` pattern (`run_public.py:275-280`) | 1 MiB chunks; already proven on the 60 MB catalog |
| Git revision capture | `subprocess` invocation | `code_revision()` (`analyze_public.py:229`) | Already handles `OSError` / `CalledProcessError` → `"unknown_revision"` |
| Session UUID → `sample_id` join | A new mapping scheme | The `_SessionMappingAgent` *pattern* (`run_public.py:31-56`), **re-implemented** in `arena/` per D-07 | The correctness argument (evaluator resets in sample order; join after `evaluate()` returns) is already worked out and documented |
| Per-session metric records | A new schema | `evaluate()`'s own record (`local_evaluator.py:269-276`) | Already contains every field MEAS-01…MEAS-04 need |
| Canonical JSON | Custom serializer | `json.dumps(..., sort_keys=True, separators=(",", ":"))` | The repo's existing fingerprint convention |
| A statistics library | — | The stdlib, hand-rolled per the patterns above | Forbidden by the zero-dependency invariant; the routines are ~150 lines total |

**Key insight:** in this phase the "don't hand-roll" list is unusually short
because there is nothing to install. The real risk is the inverse — **re-inventing
patterns that already exist three files away** (`_publish`, `_sha256`,
`code_revision`, the session-mapping wrapper), each of which encodes a
hard-won platform lesson in a comment. Copy the pattern *and the comment*.

---

## Runtime State Inventory

> Included because D-04 changes a data-retention rule and F-01/F-03 turn on state
> that lives outside git. Not a rename phase, but the same class of blindness
> applies.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| **Stored data** | `results.json` at repo root — **full 200-session record for run A**, `sha`-less, gitignored at `.gitignore:8`. Contains `hit_rate_at_10 0.92`, `mrr 0.524466`, `mttc 3.425`, `efficiency 0.7575`, `recommended_technical_score 0.76884`, plus all four scenario summaries and 200 session rows | **Use it as the immediate Layer-1/Layer-2 data source**, then supersede it with a provenance-carrying `experiments/baselines/` record (D-04). Do not delete it before that record exists |
| **Live service config** | None — no external services, no network, no credentials. Verified: repo-wide grep for `os.environ`/`getenv` returns nothing (per CLAUDE.md, re-confirmed by the absence of any config module) | None |
| **OS-registered state** | None — no scheduled tasks, no daemons, no installed console scripts (`pyproject.toml` has no `[project.scripts]`) | None |
| **Secrets / env vars** | None. `.env` is gitignored at `.gitignore:7` but no `.env` file exists and nothing reads one | None |
| **Build artifacts** | `data/catalog.artifacts/catalog.sqlite3` — 581,844,992 bytes, present, gitignored at `.gitignore:12`. `data/catalog.jsonl` — 60,546,327 bytes, present, gitignored at `.gitignore:11`. Both are prerequisites for any evaluation run | **None — both already present and valid.** No rebuild needed. Verified in-session |
| **Gitignore rule (the F-01 root cause)** | `.gitignore:9` `experiments/*/` swallows every run directory; `.gitignore:10` `experiments/.*-/` covers the tempdir prefix | Add `!experiments/baselines/` **after line 10** — see Pitfall 2 for the verified ordering constraint |

---

## Statistical Magnitudes (measured on this repository's real data)

Every row below was produced in-session by resampling `results.json`'s 200 real
sessions. These are the numbers the leaderboard will actually print, and the
planner should use them to sanity-check acceptance criteria.

### Reproduction anchor — run A, full precision

| Metric | Value (6 dp) | `RUNS.md` records | Source |
|--------|-------------|-------------------|--------|
| HR@10 | `0.92` | `0.920` | `results.json` |
| MRR | `0.524466` | `0.5245` (4 dp) | `results.json` |
| MTTC | `3.425` | `3.425` | `results.json` |
| Efficiency | `0.7575` | not recorded | derived |
| **TechnicalScore** | **`0.76884`** | `0.7688` (4 dp) | `results.json` |

Per-scenario, with σ computed from each bucket's own `n` and observed `p` (D-15):

| Scenario | n | HR@10 | MRR | MTTC | binomial σ | decision-grade? |
|----------|---|-------|-----|------|-----------|-----------------|
| boundary | 10 | 0.9 | 0.404444 | 3.6 | **0.094868** | **no** |
| browsing | 80 | 0.95 | 0.527862 | 3.125 | 0.024367 | yes |
| buying | 80 | 0.9 | 0.464296 | 3.2875 | 0.033541 | yes |
| intent_override | 30 | 0.9 | 0.715873 | 4.533333 | **0.054772** | **no** |

Overall binomial σ on HR@10 at n=200: **0.019183** — confirming PROJECT.md's
`σ ≈ 0.019`.

> **MEAS-09 discrepancy, explained.** MEAS-09 quotes Boundary `σ ≈ 0.086` and
> Intent Override `σ ≈ 0.050`. Those were computed with the *overall* `p = 0.92`
> applied to the bucket `n` (`√(0.92·0.08/10) = 0.0858`, `√(0.92·0.08/30) =
> 0.0495`). D-15 mandates the bucket's *own* observed `p = 0.90`, which gives
> `0.0949` and `0.0548`. **The report will not match the requirement's
> illustrative figures, and that is correct.** The planner must state this in
> `LEADERBOARD.md` so a reader (or judge) does not read it as an arithmetic bug.

### Detection power vs candidate similarity — the number that decides the phase

Synthetic candidates built by promoting `m` already-hit sessions to rank 1
(a realistic MRR-only ranking change; 4,000 bootstrap replicates):

| m promoted | ΔTS | bootstrap SE | **MDD (80%, α=0.05)** | detectable at n=200? |
|-----------|------|-------------|----------------------|---------------------|
| 0 (identical) | 0.000000 | 0.000000 | 0.000000 | degenerate — see Pitfall 5 |
| 2 | +0.002662 | 0.001882 | 0.005273 | no |
| 5 | +0.005962 | 0.002623 | 0.007350 | no |
| **10** | **+0.012269** | **0.003779** | **0.010587** | **yes** |
| 20 | +0.022940 | 0.004908 | 0.013751 | yes |
| 40 | +0.046961 | 0.006787 | 0.019014 | yes |
| 77 (all to rank 1) | +0.087066 | 0.007961 | 0.022303 | yes |

By contrast, a *low-correlation* pair (a candidate that also drops 18% of hits)
gives bootstrap SE `0.020429` and MDD `0.057233` — **5.4× worse**. Pairing is
doing all the work.

**Implied sample sizes for MDD = 0.01:** small tweak → n ≈ 108; moderate → n ≈ 378;
large → n ≈ 994. PROJECT.md's "3,900-15,700 paired sessions" corresponds to the
*low-correlation* regime (n ≈ 6,540 by the same formula), which is the right
number for that premise but **is not the regime Phase 3/4 candidates live in**.

### ΔTechnicalScore quantisation at n = 200

| Single-session change | ΔTS |
|----------------------|-----|
| miss (turn 11) → hit at rank 1, turn 1 — **the maximum one session can move** | **0.005000** |
| rank 2 → rank 1 | 0.000750 |
| rank 4 → rank 3 | 0.000125 |
| one turn earlier, same rank | 0.000100 |

**The MEAS-07 floor of ≥0.01 TechnicalScore is therefore exactly two best-case
session flips out of 200.** That framing belongs in `LEADERBOARD.md` — it makes
the floor concrete and defensible instead of arbitrary.

### Engine runtime

10,000 paired bootstrap + 10,000 paired permutation replicates over 200 sessions:
**≈ 1.5 s per pairwise comparison** (measured: 2,000 + 2,000 took 0.3 s). No
performance concern; the full adjudication fits comfortably inside the unit-test
budget. `expected_max_of_k` adds 0.6 ms.

---

## Common Pitfalls

### Pitfall 1: The MEAS-16 anchor is recorded at 4 dp and is not exactly reproducible as written

**What goes wrong:** a plan asserts `technical_score == 0.7688` or
`mrr == 0.5245` exactly, and the test fails against the true values `0.76884` and
`0.524466`.

**Why it happens:** `RUNS.md:75` records the retained row to 4 significant
decimals as prose. The evaluator rounds to 6 (`local_evaluator.py:198-200, 287`).
The two are not the same number. Independently, `0.5 × 0.92 + 0.3 × 0.5245 +
0.2 × 0.7575 = 0.76885`, which displays as `0.7689` at 4 dp — so `RUNS.md`'s
`0.5245` and `0.7688` are not even mutually consistent if read as exact.

**How to avoid:** assert at the precision the source actually records —
`round(value, 4) == 0.5245` — **and** additionally assert the exact 6 dp values
`0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884`, which are now known from
`results.json` and become permanently pinned once D-04's committed record exists.

**Warning signs:** any acceptance criterion citing a metric to 4 dp without a
stated tolerance.

---

### Pitfall 2: The `.gitignore` negation only works in one specific form and position

**What goes wrong:** D-04's committed record is added, `git add` reports nothing,
and the evidence evaporates again — the exact failure F-01 documents.

**Why it happens:** git will not descend into an excluded directory, so a
negation targeting *files* inside an excluded directory is ignored. Ordering also
matters: the last matching pattern wins.

**Verified empirically in-session** against `experiments/*/` + `experiments/.*-/`:

| Variant | Result |
|---------|--------|
| `!experiments/baselines/` placed **after** the excludes | ✅ **works** — files tracked |
| `!experiments/baselines` (no trailing slash), after | ✅ works |
| `!experiments/baselines/` placed **before** the excludes | ❌ **silently ignored** |
| `!experiments/baselines/**` with no directory re-include | ❌ **silently ignored** |

**How to avoid:** append `!experiments/baselines/` as a new line **after**
`.gitignore:10`. Encode a verification step in the plan, not an assumption:

```bash
git check-ignore -v experiments/baselines/run-a/sessions.jsonl   # must exit 1 (not ignored)
git check-ignore -v experiments/some-run/summary.json            # must exit 0 (still ignored)
```

**Warning signs:** a plan task that edits `.gitignore` without a `git check-ignore`
verification.

---

### Pitfall 3: Unpaired bootstrap indices — the silent power destroyer

**What goes wrong:** the engine reports "no significant difference" for every
candidate and an MDD around 0.02-0.06, and the whole bake-off concludes nothing.

**Why it happens:** drawing a separate index vector per arm. The code looks
almost identical and every test on *aggregate* values still passes — only the SE
is wrong, and it is wrong in the conservative direction, so nothing crashes.

**Measured cost:** SE `0.003779` (paired) vs `0.020429` (effectively unpaired) —
MDD moves from `0.0106` to `0.0572`, i.e. from "a 10-session ranking improvement
is detectable" to "nothing this project can build is detectable."

**How to avoid:** a Layer-1 fixture asserting that two *perfectly correlated*
candidates with a constant offset produce a bootstrap CI whose width is far
smaller than the CI width of two uncorrelated candidates with the same Δ. That
assertion fails loudly under the unpaired bug and cannot be satisfied by accident.

**Warning signs:** MDD > 0.02 on candidates that differ in only a handful of
sessions.

---

### Pitfall 4: BCa is uncomputable on exactly the case D-01 requires

**What goes wrong:** the bias-corrected-and-accelerated CI raises
`StatisticsError` — or worse, returns a plausible-looking but convention-dependent
interval.

**Why it happens (verified in-session):** BCa needs
`z0 = Φ⁻¹(#{replicates < observed} / R)`.

- For **identical candidates** (the required degenerate fixture), every replicate
  equals the observed 0.0, so the proportion is `0.0`, and
  `statistics.NormalDist().inv_cdf(0.0)` raises
  `StatisticsError: p must be in the range 0.0 < p < 1.0`. **Confirmed.**
- For a **near-null** candidate (one session moved rank 4 → 3), the ΔTS bootstrap
  distribution takes only **26 distinct values across 5,000 replicates**, and
  **19.1% of replicates exactly tie the observed statistic**. `z0` computed with
  `<` gives `0.028`; with `≤` it gives `0.53` — a **19× swing** from an
  implementation detail with no principled answer.

**How to avoid:** use the **percentile** CI (D-CONTEXT names it the safe default;
this is the evidence that promotes it from default to decision). Percentile
degrades gracefully: for the identical-candidate case it returns
`(0.0, 0.0)`; for the one-session case it returned `(+0.000000, +0.000375)`.
Record the rejection reason in a code comment so a future reader does not "upgrade"
to BCa.

**Warning signs:** any bootstrap implementation calling `inv_cdf` on a proportion
that can reach 0 or 1.

---

### Pitfall 5: The degenerate identical-candidate case reports a vacuous "significant"

**What goes wrong:** with Δ = 0, SE = 0, CI = [0, 0] and MDD = 0, a naive
`abs(delta) >= mdd` check evaluates `0 >= 0` → **True**, and the rig declares a
detectable difference between a candidate and itself.

**Why it happens:** all four quantities collapse to zero simultaneously, and every
comparison operator that is "safe" for positive numbers becomes vacuous at zero.

**How to avoid:** guard explicitly. `SE == 0.0` (or `< 1e-12`) means *the two
candidates are indistinguishable on every resample* and must short-circuit to a
`NOT_DETECTABLE` verdict with `p = 1.0`, regardless of the arithmetic. Encode it
as a Layer-1 fixture: identical inputs → `p_permutation == 1.0`,
`ci == (0.0, 0.0)`, `mdd == 0.0`, verdict `"no difference"`, **never** `"win"`.
Note that this is a *plausible real outcome* for A vs C, not a hypothetical.

**Warning signs:** a verdict function with no zero-variance branch.

---

### Pitfall 6: σ̂ for the winner's curse is the paired-Δ SE, not PROJECT.md's 0.019

**What goes wrong:** the leaderboard prints a winner's-curse correction of
~0.003-0.008 while PROJECT.md and PITFALLS.md advertise 0.022-0.030, and a reader
(or Phase 5, or a judge) concludes the correction was not applied.

**Why it happens:** two different σ's are in play. PITFALLS.md's table uses
σ ≈ 0.019, the **absolute** binomial SE of HR@10 at n=200 — appropriate for
correcting an unpaired absolute score. D-21 specifies the **paired-difference**
SE of ΔTechnicalScore, which for correlated candidates measures 0.002-0.008. D-21
is methodologically correct (selection happens on the paired Δ, so the noise in
the selection statistic is the paired-Δ noise), but the resulting number is an
order of magnitude smaller.

**Concretely:** at `SE = 0.003` and k=5, the correction is
`0.003 × 1.1630 = 0.0035`; at k=10, `0.003 × 1.5388 = 0.0046`. Both are the same
order as Phase 5's ~0.005 stopping threshold (POS-04) — so this is not a cosmetic
discrepancy, it directly determines a go/no-go decision.

**How to avoid:** print **σ̂, k, and `E[max of k]` as separate audited columns**
alongside the corrected Δ (D-21 already requires k to be printed; extend it to
σ̂), and add one sentence to `LEADERBOARD.md` stating that σ̂ is the paired-Δ SE
and why it is smaller than the 0.019 figure quoted elsewhere in the planning
documents.

**Warning signs:** a correction column with no σ̂ column beside it.

---

### Pitfall 7: Run B is not the large-effect control D-02 assumes

**What goes wrong:** the plan encodes "A vs B must return significant with
ΔTS ≈ 0.17" as an acceptance criterion; the actual ΔTS lands near 0.01 and the
phase is blocked on a false failure — or worse, the rig is "fixed" until it
agrees.

**Why it happens:** `RUNS.md:56-61`'s forced-fallback measurement
(`HR@10 0.75 / TS 0.599`) sits inside the section headed **"Artifact-backed,
superseded (SQLite engine at HEAD `e76b3ab`)"**, where the FTS baseline was
`0.76 / 0.609233`. The lexical-mode effect *at that HEAD* was
`0.609233 − 0.599 = 0.0102`, and `RUNS.md:58` describes it in words as
"**near-parity** with the FTS engine." D-02's `0.17` subtracts the superseded-HEAD
B from the current-HEAD A, so it measures the extraction/matching fixes
(`e76b3ab` → `eb4e836`, worth ~0.16 TS) rather than the lexical mode.

**How to avoid:** apply D-03's measure-don't-assume rule to **run B as well as
run C**. Assert only internal consistency (verdict ⟷ CI ⟷ MDD ⟷ p all agree, and
the result reproduces byte-identically), never a specific magnitude or
significance outcome. Obtain the *guaranteed* large-effect control synthetically —
see Open Question Q1.

**Warning signs:** any acceptance criterion of the form "A vs B must be
significant."

---

### Pitfall 8: Windows `os.replace` on a directory with an open handle

**What goes wrong:** a 200-session run completes and then fails at the final
publish step with `PermissionError`.

**Why it happens:** `os.replace` on a directory requires no process to hold a
handle inside it. The `Agent` holds a memory-mapped SQLite connection (1 GiB
mmap, per the read-path pragmas) and `JsonlEvaluationTrace` holds a file handle.

**How to avoid:** close the agent in a `finally` *before* leaving the
`TemporaryDirectory` context, exactly as `run_public.py:94-97` does. Additionally,
run the suite warning-strict — `uv run python -W error::ResourceWarning -m
unittest -v` turns an unclosed handle into a test failure, which is how the
existing suite already guards this lifecycle.

**Warning signs:** a test that constructs `Agent` without `self.addCleanup(agent.close)`.

---

### Pitfall 9: `arena/statistics.py` name shadowing

**What goes wrong:** `import statistics` inside `arena/statistics.py` resolves to
itself.

**Why it happens:** only under relative-import semantics. Python 3 uses absolute
imports by default, so this is **safe** in practice — but it is a genuine
readability trap for a reviewer.

**How to avoid:** either keep the name and add a one-line comment, or name the
module `arena/resampling.py`. The planner should pick one and state it, rather
than leaving it to the implementer.

---

## Code Examples

All verified in-session against this repository's data. See Patterns 1-10 above
for the full set; the two most decision-relevant are repeated here.

### Deriving both the anchor and the HR@K curve from a retained session file

```python
# Source: verified against results.json in-session; reproduces the evaluator's
# own reported aggregates exactly (0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884).
import json
from pathlib import Path


def load_sessions(path: Path) -> tuple[SessionOutcome, ...]:
    """Read a retained per-candidate record. The agent is never re-invoked."""
    return tuple(
        SessionOutcome(
            sample_id=str(row["sample_id"]),
            scenario_type=str(row["scenario_type"]),
            hit=bool(row["hit"]),
            first_hit_turn=row["first_hit_turn"],
            best_rank=row["best_rank"],
            reciprocal_rank=float(row["reciprocal_rank"]),
        )
        for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )
```

### Per-bucket binomial standard error (D-15, MEAS-09)

```python
def binomial_standard_error(hit_rate: float, count: int) -> float:
    """sigma from the bucket's OWN observed p and n -- never hardcoded (D-15)."""
    if count <= 0:
        raise ValueError("bucket size must be positive")
    return math.sqrt(hit_rate * (1.0 - hit_rate) / count)


# Buckets below ~40 sessions cannot resolve a one-session swing from noise:
# boundary n=10 -> one session moves HR@10 by 0.10 against sigma 0.0949.
NOT_DECISION_GRADE_BELOW = 40
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Report the best-of-k score as the result | Report the order-statistic-corrected estimate with k disclosed | Long-standing in ML evaluation; adopted here via D-21 | The whole reason MEAS-08 exists |
| `p = count / R` for Monte-Carlo permutation | `p = (count + 1) / (R + 1)` | Phipson & Smyth (2010) is the canonical citation | Prevents `p = 0`; the standard convention in permutation testing |
| Independent-sample comparison of two system scores | Paired/bootstrap comparison joined on query id | Standard IR evaluation practice for decades | Measured 5.4× SE reduction on this data |
| Unadjusted multiple comparisons | Holm step-down (uniformly more powerful than Bonferroni, same FWER control) | Holm (1979) | Preserves power on the one comparison that decides anything |
| "no significant difference" reported bare | Reported together with the MDD | Standard equivalence/non-inferiority practice | The literal content of MEAS-06 |

**Not deprecated but deliberately not used here:**

- **BCa bootstrap** — theoretically preferable to percentile for skewed
  statistics, but disqualified for this statistic by lattice degeneracy (Pitfall 4).
- **McNemar's test** — correct and more powerful for the *binary* HR@10 component,
  and PITFALLS.md recommends it. D-16 tests the composite TechnicalScore, which
  McNemar cannot address. Its underlying insight (only discordant sessions carry
  information) is nonetheless the reason the paired bootstrap SE is so small, and
  is worth stating in the report. A McNemar HR@10 result would be a legitimate
  *supplementary* descriptive statistic, not a replacement for D-16.
- **Studentized / bootstrap-t CI** — needs a nested bootstrap for the variance
  estimate; ~100× the cost for no benefit on a lattice-valued statistic.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The extraction/matching fixes between `e76b3ab` and `eb4e836` benefit the TF-IDF fallback path as much as the FTS path, so run B at current HEAD will score far above `0.599` and ΔTS(A,B) will be small | Pitfall 7 | If wrong, run B *is* a large-effect control and D-02 stands as written. **Either way the mitigation (measure, don't assert) is correct**, so the risk is low — but a plan that hard-asserts either outcome is wrong |
| A2 | `results.json` was produced at or near current HEAD `eb4e836` | Finding F-03 | Its aggregates match `RUNS.md`'s retained row exactly on all six recorded figures, so a mismatch is very unlikely. Mitigation: run A regenerates the record with provenance regardless (D-04), and the anchor test then compares the two |
| A3 | `random.Random` output is stable across CPython patch versions for a fixed integer seed | Pattern 3 / D-24 | Mersenne Twister is specified and has not changed; but determinism is an *acceptance property* here, so the plan should verify byte-identical verdicts across two invocations rather than assume it |
| A4 | Reference values of `E[max of k]` for k=20 and k=50 quoted in the accuracy table are from training knowledge, not a verified source | Pattern 7 | Low — k in this project is the candidate count (3-10), where the closed forms for k=2,3 confirm Simpson to 1e-15. The k=20/50 rows should be read as indicative only |
| A5 | The competition's TechnicalScore weights (0.50/0.30/0.20) and Efficiency formula are as transcribed | Pattern 1 | None — read directly from `evaluator/local_evaluator.py:279-280`, which is the scoring authority |
| A6 | No Phase 1 module needs a per-turn trace, so the committed record can omit `retrieval_routes.jsonl` | D-04 / Pattern 2 | Low — verified that HR@K, MRR, MTTC, per-scenario breakout and every statistic derive from `sessions.jsonl` alone |

Everything else in this document was executed in-session against this
repository's own files and data.

---

## Open Questions

### Q1: D-01 Layer 3 has no guaranteed large-effect control (consequence of Pitfall 7)

- **What we know:** D-01 Layer 3 requires *both* a known-large-effect pair and a
  known-near-null pair, because "a rig only validated on a real effect cannot be
  trusted to say no." D-02 designates A-vs-B as the large-effect arm on the basis
  of ΔTS ≈ 0.17. That figure is a cross-HEAD artifact (Pitfall 7); the true
  same-HEAD lexical-mode effect was `0.0102` and `RUNS.md:58` calls it
  "near-parity."
- **What's unclear:** the actual ΔTS(A, B) at current HEAD. It is genuinely
  unknown and cheap to measure (~190 s), but it cannot be *assumed* large, and
  the D-10 allow-list (`lexical_mode`, `exploration`, `artifact_path`) offers no
  other configuration knob that reliably produces a large effect.
- **Recommendation (does not conflict with any locked decision):**
  1. Still run A, B and C exactly as D-02 specifies — they are cheap, real, and
     A remains the MEAS-16 anchor. Record whatever ΔTS(A, B) turns out to be as a
     finding, per D-03's logic extended to B.
  2. Add a **synthetic large-effect control** derived deterministically from run
     A's own `sessions.jsonl` — e.g. promote a fixed, seeded set of `m` hit
     sessions to rank 1, or demote `m` hits to misses. This costs zero evaluation
     time, has an **analytically known** ΔTS (the measured table above gives
     ΔTS = +0.0123 at m=10 and +0.0871 at m=77), and is therefore a *stronger*
     true-positive control than a real run whose true effect is unknown.
     It belongs naturally in D-01 Layer 1 (known-answer fixtures), which is where
     an exactly-known answer should live.
  3. Never assert a significance outcome for A-vs-B or A-vs-C. Assert internal
     consistency and byte-reproducibility, per D-03.
- **This is the single highest-value item for the planner to resolve** before
  writing acceptance criteria.

### Q2: Should `results.json` seed the Layer-2 anchor, or must run A precede everything?

- **What we know:** `results.json` contains the complete run-A record and
  reproduces the evaluator's aggregates exactly. It is gitignored, carries no
  `run_id`, `code_revision`, `catalog_sha256` or `dataset_sha256`, and could be
  overwritten by any bare `uv run python -m evaluator.local_evaluator`.
- **What's unclear:** only its exact provenance HEAD (see A2).
- **Recommendation:** use it immediately as the development and unit-test data
  source so the entire leaderboard and statistics engine can be built and proven
  before any 190-second run. Then run A through the arena to produce the
  provenance-carrying `experiments/baselines/` record (D-04), and make the anchor
  test assert that the arena's record and `results.json` agree on all six
  aggregates. That agreement is itself extra validation evidence in the same
  spirit as D-06's two-independent-paths argument. **Copy `results.json` to a
  scratch location before any run**, since a stray evaluator invocation overwrites
  it.

### Q3: Should the winner's-curse `k` count candidates or comparisons?

- **What we know:** D-21 says "k is the number of candidates actually compared"
  and requires k to be printed. D-19 says the Holm family is the k−1 comparisons
  against a common baseline.
- **What's unclear:** whether `expected_max_of_k` receives `k` (candidates,
  including the baseline) or `k − 1` (comparisons). The selection event is "which
  of the non-baseline candidates had the largest Δ," which argues for `k − 1`;
  D-21's wording says `k`.
- **Recommendation:** use **`k` = the number of candidates whose Δ was compared
  when choosing the champion** (i.e. `k − 1` non-baseline candidates, since the
  baseline's Δ against itself is not a selection option) — but **print both the
  candidate count and the value of k fed to the correction**, so the choice is
  auditable and Phase 5 can re-derive it. The difference is small
  (`E[max]` at k=4 vs k=5 differs by 0.134, ≈ 0.0004 TS at σ̂ = 0.003) but should
  be stated once rather than left implicit.

### Q4: Does `LEADERBOARD.md` need a stated-assumptions block?

- **What we know:** three numbers in the report will differ from figures quoted
  in `.planning/` documents, each for a good reason: per-bucket σ (Pitfall/MEAS-09
  note), the winner's-curse σ̂ (Pitfall 6), and the achievable MDD (Finding F-05).
- **Recommendation:** yes — a short "How to read this report" section covering
  those three, plus the D-19 statement that per-scenario numbers are deliberately
  not Holm-corrected. This is cheap and converts three apparent inconsistencies
  into three demonstrations of statistical care, which is directly reportable
  under Technical Execution.

---

## Environment Availability

Probed in-session on the target machine (Windows 11, PowerShell).

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| CPython ≥ 3.10 | everything | ✓ | 3.13.8 | — |
| `uv` | env management, all run commands | ✓ | 0.9.4 | — |
| SQLite with FTS5 | run A and run C (`--lexical-mode auto`) | ✓ | 3.50.4, FTS5 OK | run B (`--lexical-mode fallback`) needs no FTS5 |
| `git` (on PATH) | `code_revision()`, `.gitignore` verification | ✓ | repo at `b98ff27` | `code_revision()` returns `"unknown_revision"` |
| `data/catalog.jsonl` | all three runs | ✓ | 60,546,327 bytes | — |
| `data/catalog.artifacts/catalog.sqlite3` | all three runs | ✓ | 581,844,992 bytes | rebuild costs 60-90 s |
| `data/public_set.jsonl` | all three runs | ✓ | 88,440 bytes | — |
| `results.json` (run-A session record) | immediate Layer-1/2 development | ✓ | 200 sessions | regenerate via run A (~190 s) |
| Third-party Python packages | — | n/a | — | none needed; `dependencies = []` |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

**Cost budget for the three D-02 runs.** Run A ≈ 190 s at current HEAD. Run C
(exploration `tail-only`) should be comparable — the ablation fired on 7 of ~1,500
turns. **Run B is the uncertain one:** `--lexical-mode fallback` uses the
deterministic TF-IDF posting path rather than FTS5, and no current-HEAD runtime is
recorded for it. `RUNS.md` records the superseded-HEAD FTS runs at 747-800 s and
current-HEAD runs at ~190 s, so the scaling is not directly transferable. Budget
run B generously and treat a long runtime as expected, not as a hang.

> **Guard the anchor data.** `evaluator/local_evaluator.py:302` defaults
> `--output` to `results.json`, so any bare `uv run python -m
> evaluator.local_evaluator` overwrites the file this phase's early work depends
> on. Copy it aside as the first plan task.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `unittest` (stdlib, CPython 3.13.8) — no pytest, no plugins, no config file |
| Config file | none — default discovery via `tests/__init__.py`, `test_*.py`, `TestCase` subclasses, `test_*` methods |
| Quick run command | `uv run python -m unittest -v tests.test_arena_statistics` |
| Full suite command | `uv run python -W error::ResourceWarning -m unittest -v` (canonical, per `LOCAL_ENVIRONMENT.md:94`) |
| Existing baseline | 167 tests, a few seconds, no catalog download required |

### What "validated" means for a statistical engine

Passing tests is not sufficient. A statistics engine is validated when it is
proven on **all four** of the following, which is exactly what D-01's three layers
plus the D-03 caveat encode:

1. **Arithmetic** — each routine reproduces an analytically known answer (Layer 1).
2. **True positive** — it says "significant" on a difference known to be real
   (Layer 3 large-effect arm; see Open Question Q1 for how to guarantee one).
3. **True negative** — it says "not significant" on a difference known to be
   absent, *and* reports an MDD showing it could have seen one (Layer 3 near-null
   arm). This is the property MEAS-06 exists for and the one a rig validated only
   on real effects silently lacks.
4. **Reproducibility** — two invocations on identical inputs produce
   byte-identical verdicts (D-24).

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MEAS-01 | Metric chain reproduces the evaluator exactly; per-scenario breakout present | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ Wave 0 |
| MEAS-02 | HR@K curve = `0.385/0.59/0.715/0.92`; `HR@10 == hit_rate_at_10` | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ Wave 0 |
| MEAS-03 | Per-scenario MRR/MTTC recovered from a session file with no agent invocation | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ Wave 0 |
| MEAS-04 | Paired bootstrap and permutation join on `sample_id`; mismatched ids raise; unpaired-index bug detected | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ❌ Wave 0 |
| MEAS-05 | Holm adjusted p matches all four hand-computed fixture cases, monotone | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ❌ Wave 0 |
| MEAS-06 | `MDD == 2.801585218112968 × SE`; reported on null verdicts too | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ❌ Wave 0 |
| MEAS-07 | Floor applied to the **corrected** Δ (D-20 step 5); raw-Δ pass is rejected | unit | `uv run python -m unittest -v tests.test_arena_adjudication` | ❌ Wave 0 |
| MEAS-08 | `expected_max_of_k(2) == 1/√π`, `(3) == 3/(2√π)`, `(1) == 0.0` | unit | `uv run python -m unittest -v tests.test_arena_statistics` | ❌ Wave 0 |
| MEAS-09 | σ derived from bucket `p` and `n`; boundary → `0.094868`, intent_override → `0.054772`; both flagged not-decision-grade | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ Wave 0 |
| MEAS-14 | Identical inputs → identical fingerprint twice; unknown override key raises `ValueError` | unit | `uv run python -m unittest -v tests.test_arena_candidate` | ❌ Wave 0 |
| MEAS-15 | AST walk over `arena/*.py` (excl. bridge) finds zero `evaluator` references; bridge surface is exactly 3 names; evaluator SHA-256 unchanged | unit | `uv run python -m unittest -v tests.test_arena_boundary` | ❌ Wave 0 |
| MEAS-16 | Anchor: `0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884` at 6 dp **and** `RUNS.md`'s 4 dp values; scenario HR@10 `0.90/0.95/0.90/0.90` | unit | `uv run python -m unittest -v tests.test_arena_metrics` | ❌ Wave 0 |
| D-24 | Two adjudication runs on identical inputs → byte-identical `leaderboard.json` | unit | `uv run python -m unittest -v tests.test_arena_adjudication` | ❌ Wave 0 |
| D-04 | `git check-ignore` confirms `experiments/baselines/` tracked, other run dirs ignored | manual/script | `git check-ignore -v experiments/baselines/run-a/sessions.jsonl` (must exit 1) | ❌ Wave 0 |
| SC-3 | Full adjudication over two retained rows produces a reproducible verdict + MDD | integration | `uv run python -m arena.run_arena --adjudicate` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** the single relevant `tests.test_arena_*` module —
  sub-second, since none of them touch the catalog.
- **Per wave merge:** `uv run python -W error::ResourceWarning -m unittest -v` —
  the full 167 + new tests, a few seconds. Warning-strict is mandatory: it is the
  mechanism that catches an unclosed SQLite handle before it becomes Pitfall 8.
- **Phase gate:** full suite green, **plus** the three D-02 runs completed with
  their records committed under `experiments/baselines/`, **plus** the
  reproducibility check (adjudicate twice, `git diff --quiet` on
  `leaderboard.json`), before `/gsd-verify-work`.

> **Note on the evaluation runs.** The three runs are *not* unit tests and must
> never be wired into the suite — they need the 580 MB artifact and ~190 s each,
> which would destroy the "runs with no catalog download" property that makes the
> existing 167-test suite usable. Keep them as an explicit operator step with
> their outputs committed as evidence.

### Wave 0 Gaps

- [ ] `tests/test_arena_metrics.py` — covers MEAS-01, MEAS-02, MEAS-03, MEAS-09, MEAS-16
- [ ] `tests/test_arena_statistics.py` — covers MEAS-04, MEAS-05, MEAS-06, MEAS-08 (the D-01 Layer 1 known-answer fixtures)
- [ ] `tests/test_arena_adjudication.py` — covers MEAS-07, D-20 ordering, D-23 win rule, D-24 reproducibility
- [ ] `tests/test_arena_candidate.py` — covers MEAS-14
- [ ] `tests/test_arena_boundary.py` — covers MEAS-15 (AST walk + bridge surface + evaluator SHA-256)
- [ ] A shared arena fixture builder (session-tuple constructors and the synthetic
      degradation/promotion helpers from Open Question Q1). Follow the
      `tests/fixtures.py` pattern — module-level factory functions, **not** a
      `TestCase`, so it is excluded from discovery. Unlike `tests/fixtures.py` it
      needs no temp directory and no catalog, because every arena statistics
      module is stdlib-pure by construction.
- [ ] Framework install: **none required** — `unittest` is stdlib and the suite
      already exists.

### Layer-1 known-answer fixture specification

The planner can write these as exact assertions; every value was computed
in-session.

| Fixture | Input | Exact expected answer |
|---------|-------|----------------------|
| Degenerate bootstrap | two identical candidates | `delta == 0.0`, `ci == (0.0, 0.0)`, `se == 0.0`, `mdd == 0.0`, verdict `"no difference"` (**never** `"win"` — Pitfall 5) |
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
| Pairing preserved | perfectly correlated pair vs uncorrelated pair, same Δ | correlated CI width ≪ uncorrelated CI width (catches Pitfall 3) |
| Seed determinism | same two fingerprints, two invocations | identical `delta`, `ci`, `p`, `mdd` — byte-equal serialized output |
| Anchor | run-A session file | `0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884`; HR@K `0.385/0.59/0.715/0.92` |

---

## Security Domain

`security_enforcement: true`, `security_asvs_level: 1`. This phase builds a local,
offline, single-user analysis tool with no network surface, no authentication, no
sessions, no persistence of user data, and no untrusted input from a remote party.
Most ASVS categories are genuinely inapplicable; saying so explicitly is more
useful than manufacturing findings.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No accounts, no credentials, no auth surface anywhere in the repo |
| V3 Session Management | no | "Sessions" here are evaluation conversations, not security sessions |
| V4 Access Control | no | Single local user; no multi-tenancy |
| V5 Input Validation | **yes** | `CandidateSpec.validate()` allow-list (D-10); `run_id` charset regex; typed parsing of `sessions.jsonl` rows at the boundary before use |
| V6 Cryptography | **partial** | `hashlib.sha256` used for *fingerprinting and content-seeding only*, never for secrecy or authentication. Do not treat the fingerprint as tamper-evident |
| V7 Error Handling & Logging | **yes** | Fail closed with typed `ValueError` on contract violations (repo convention); never swallow with bare `except` |
| V12 File & Resource | **yes** | `run_id` becomes a directory name — path traversal must be blocked; file handles closed before `os.replace` |
| V14 Configuration | **yes** | Zero dependencies means zero transitive supply-chain surface — this is a genuine, claimable security property under Feasibility (POS-03) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| `run_id` / candidate name used as a path component (`../..`, absolute path, NTFS ADS `:`) | Tampering | Reuse the existing `_RUN_ID_RE = ^[a-zA-Z0-9][a-zA-Z0-9._-]*$` allow-list from `run_public.py:28`, and additionally resolve the destination and assert it is inside the output root |
| Untrusted `sessions.jsonl` deserialized into code paths | Tampering | `json.loads` only (never `pickle`, `eval`, or `yaml.load`); validate field types at the boundary before constructing the dataclass |
| Shell injection via git invocation | Tampering | `subprocess.run` with a **tuple** argv and no `shell=True` — the existing `code_revision()` already does this correctly |
| Unbounded resource use from a hostile resample count | DoS | `RESAMPLE_COUNT` is a module constant (D-24), not user input; if a CLI flag is added, bound it |
| Fingerprint collision / forgery | Spoofing | Out of threat model — the fingerprint is an integrity/reproducibility aid for a single local user, not an authenticity control. State this in a comment so nobody later relies on it as one |
| Accidental commit of the 580 MB artifact or 60 MB catalog | Information disclosure / repo bloat | Already covered by `.gitignore:11-12`. The D-04 negation must be **narrowly scoped** to `experiments/baselines/` — a broad negation could re-include large run directories |

**Highest-value security observation for this phase:** the D-04 `.gitignore`
change is the only edit that widens what gets committed. Scope it narrowly and
verify it with `git check-ignore` (Pitfall 2) rather than by inspection — a
too-broad negation would commit ~10,400-event trace files and eventually the
artifact itself.

---

## Sources

### Primary (HIGH confidence — read or executed in this session)

- `evaluator/local_evaluator.py` — `metric_summary` (`:188-201`), per-session
  record (`:269-276`), Efficiency / TechnicalScore / scenario grouping
  (`:279-293`), `evaluate` signature (`:216-222`), `catalog_index` (`:112-123`),
  `load_jsonl` (`:90-92`), `MAX_TURNS`/`TOP_K` (`:15-16`), CLI defaults (`:298-308`)
- `experiments/run_public.py` — `_SessionMappingAgent` (`:31-56`), `_publish` incl.
  the Windows `WinError 183` rationale (`:135-150`), `_sha256` (`:275-280`),
  `_write_json`/`_write_jsonl` canonical form (`:283-294`), CLI flags
  `--exploration {disabled,tail-only}` (`:333-337`) and
  `--lexical-mode {auto,fts5,fallback}` (`:338-342`), five-file layout (`:119-130`)
- `experiments/analyze_public.py:229` — `code_revision()`
- `starter/agent.py:18-25` — `Agent.__init__(catalog_path, artifact_path, lexical_mode, trace, exploration)`
- `experiments/RUNS.md` — retained row (`:75`), scenario HR@10 (`:78-79`),
  superseded-HEAD section header (`:20`), exploration ablation (`:47-54`),
  forced-fallback verification (`:56-61`), determinism verification (`:40-45`)
- `results.json` (untracked, repo root) — 200-session run-A record; all aggregates
  and per-scenario summaries
- `.gitignore` — `results.json` (`:8`), `experiments/*/` (`:9`),
  `experiments/.*-/` (`:10`), catalog/artifact (`:11-12`)
- `tests/fixtures.py`, `tests/test_evaluator.py`, `tests/test_experiment_analysis.py` — fixture-builder and TestCase patterns
- `.planning/codebase/TESTING.md` — run commands, naming, structure conventions
- `LOCAL_ENVIRONMENT.md` — FTS5 verification, artifact build, canonical
  warning-strict test command (`:94`)
- `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`,
  `.planning/research/PITFALLS.md`, `CLAUDE.md`

### Executed verifications (HIGH confidence — reproducible)

- Metric-chain replication from `results.json` sessions → exact match with the
  evaluator's reported aggregates
- HR@K curve computation from `best_rank`
- Per-scenario binomial σ
- Paired bootstrap / paired permutation over the real 200 sessions at multiple
  candidate-similarity levels; SE, CI, MDD and runtime measured
- BCa `z0` degeneracy: `NormalDist().inv_cdf(0.0)` → `StatisticsError`; lattice
  structure of the ΔTS bootstrap distribution (26 distinct values / 5,000
  replicates; 19.1% exact ties)
- `expected_max_of_k` by composite Simpson vs the closed forms for k=2,3 and
  reference values to k=10; Blom comparison; timing
- Holm-Bonferroni on four fixture cases, including the monotonicity case
- Exhaustive n=4 paired sign-flip permutation → exact `p = 4/16`
- `.gitignore` negation: four variants tested in a scratch git repository with
  `git status --porcelain -uall` and `git check-ignore -v`
- AST import-boundary checker against seven import forms plus a clean control
- Environment probe: Python 3.13.8, uv 0.9.4, SQLite 3.50.4 with FTS5, catalog
  and 580 MB artifact present, git clean at `b98ff27`

### Secondary (MEDIUM confidence)

- Phipson & Smyth `(count+1)/(R+1)` permutation convention — standard and
  widely documented; the *reason* is verified by construction (the observed
  assignment is a member of the null), not by citation in this session
- Holm (1979) step-down procedure — standard; the implementation is verified
  against hand-computed cases

### Tertiary (LOW confidence — flagged)

- Reference values of `E[max of k]` for k=20 and k=50 (Assumption A4). Not used
  in any recommendation; k in this project is 3-10, where Simpson is verified
  against exact closed forms.

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|------|-------|--------|
| Standard stack | **HIGH** | Zero external packages; every stdlib API exercised in-session on the target interpreter |
| Architecture | **HIGH** | Every line anchor read directly; `arena/` layout follows the repo's existing acyclic import discipline |
| Statistical methods | **HIGH** | Every routine implemented and validated against exact closed forms or exhaustive enumeration during this session |
| Measured magnitudes (SE, MDD, quantisation) | **HIGH** | Computed from this repository's real 200-session data, not estimated |
| Pitfalls | **HIGH** | Seven of nine were empirically reproduced (gitignore variants, BCa failure, unpaired-SE inflation, degenerate case, AST evasion, anchor precision, run-B confound) |
| Run-B expected magnitude | **MEDIUM** | The cross-HEAD confound is textually certain; the resulting current-HEAD ΔTS is an inference and must be measured (Q1) |
| `results.json` provenance | **MEDIUM** | Aggregates match the retained row on all six recorded figures, but the producing HEAD is not recorded |

**Research date:** 2026-08-30
**Valid until:** stable — no external dependency can drift. The only invalidating
events are a change to `evaluator/local_evaluator.py` (forbidden by a hard
invariant), a new HEAD that moves the MEAS-16 anchor, or `results.json` being
overwritten.
</content>
</invoke>
