# Phase 1: Measurement Rig Core - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-30
**Phase:** 1-Measurement Rig Core
**Areas discussed:** Baseline provenance, Arena & CandidateSpec shape, Leaderboard artifact form, Significance & win policy

**Discussion shape:** All four gray areas were presented for selection. The user
replied *"choose the clearest and most robust and winnable solution for each
question you ask yourself"* — delegating every decision to Claude. The tables
below record the options that were on the table and which was taken, so the
alternatives are not lost.

---

## Pre-discussion finding

A codebase scout before the questions established that **no run directories exist
on disk**. `experiments/` holds only `RUNS.md` and three scripts; `experiments/*/`
is gitignored; `RUNS.md` records aggregate numbers only. The roadmap's "retained
historical run" / "retained trace data" / "two retained historical rows"
(Success Criteria 1–3, MEAS-03, MEAS-16) therefore refer to data that must be
regenerated. This was surfaced to the user before any question was asked, and it
reshaped the Baseline provenance area from "which historical rows?" into "how do
we manufacture trustworthy historical rows cheaply?"

Offsetting good news, also established before the questions: `evaluate()` already
returns per-session `{sample_id, scenario_type, hit, first_hit_turn, best_rank,
reciprocal_rank}` and `run_public.py` already persists it, so once a run exists,
every Phase 1 metric is derivable without re-invoking the agent.

---

## Baseline provenance

| Option | Description | Selected |
|--------|-------------|----------|
| Known-large-effect pair only | Regenerate HEAD vs `--lexical-mode fallback` (0.920 vs 0.75). Proves the test detects a real difference. | |
| Known-null pair only | Regenerate `--exploration disabled` vs `tail-only` (measured metric-identical). Proves the test does not manufacture differences. | |
| Synthetic fixtures only | Analytically-known paired vectors in the unit suite. Fast, no evaluation runs. | |
| All three layers | Synthetic fixtures + a reproduction anchor against the retained `RUNS.md` row + both adjudication controls. Three runs total (~10 min) because one run is an arm of both pairs. | ✓ |

**Choice:** All three layers (D-01, D-02).
**Notes:** Each layer catches a different bug class — arithmetic/pairing bugs
(fixtures), engine-vs-history drift (anchor), and adjudication bugs in both
directions (controls). Three runs share run A as a common arm, so the cost is
three evaluations, not four. Two follow-on decisions came out of this area:
run C's null result is *measured, not assumed* (the `RUNS.md` ablation was
recorded on superseded HEAD `e76b3ab`, so plans must not hard-assert `p > 0.05`)
— D-03; and the root cause of the missing history is the `.gitignore` line
`experiments/*/`, fixed by committing a reduced ~26 KB per-candidate record under
`experiments/baselines/` — D-04. `experiments/RUNS.md` is not rewritten, because
its prose carries the exploration ablation, determinism verification, and miss
audit that exist nowhere else — D-05.

---

## Arena & CandidateSpec shape

| Option | Description | Selected |
|--------|-------------|----------|
| Extend `experiments/run_public.py` | Reuse its session mapping, tracing, atomic publish, and five-file layout in place. Least new code. | |
| New `arena/` package, `run_public.py` refactored to share code | Avoids duplicating the ~25-line session-mapping wrapper, but perturbs the frozen reproducer and costs a re-verification run. | |
| New `arena/` package, `run_public.py` left byte-untouched | Slight deliberate duplication; keeps two independent code paths that must agree on the anchor numbers. | ✓ |

**Choice:** New `arena/` package, `run_public.py` untouched (D-06, D-07).
**Notes:** The deciding argument was evidentiary rather than architectural — two
independent implementations agreeing on `0.920 / 0.5245 / 3.425 / 0.7688` is
stronger validation than one, and is reportable under Technical Execution.
Duplicating the session-mapping wrapper is also what keeps the evaluator import
out of `arena/`. That led to D-08: exactly one module (`arena/evaluator_bridge.py`)
may import from `evaluator/`, enforced by an AST test — turning MEAS-15 and
Success Criterion 5 from prose into a failing test.

Sub-question — how a candidate is parameterized:

| Option | Description | Selected |
|--------|-------------|----------|
| Config-injection only | Candidates differ only by constructor arguments. Clean, but cannot express a candidate that is a code change. | |
| Git-revision only | Each candidate is a commit. Honest, but makes in-process comparison impossible. | |
| Both, with an applied-only allow-list | `CandidateSpec` carries name, git SHA, an allow-listed `overrides` mapping, and input fingerprints; SHA-256 over canonical JSON is the fingerprint. | ✓ |

**Notes:** The allow-list detail (D-10) was the load-bearing part: `validate()`
raises on unknown keys, and Phase 1's list is exactly what `Agent.__init__`
accepts today (`lexical_mode`, `exploration`, `artifact_path`). Belief/question/
fusion knobs are **not** carried as inert recorded fields — a fingerprint that
describes a configuration that was never applied would silently invalidate an
entire bake-off. Phase 3 extends `Agent` and the allow-list in one change.

---

## Leaderboard artifact form

| Option | Description | Selected |
|--------|-------------|----------|
| Generated Markdown only | Matches the `RUNS.md` convention, judge-readable, committable. Awkward to assert against in tests. | |
| CLI that prints on demand | No artifact to maintain. Rejected: a report that exists only in a terminal cannot be cited by a rubric narrative. | |
| JSON source of truth + generated Markdown view, both committed | Machine-readable for tests and Phase 3/4/5 appends; human-readable for judging. | ✓ |

**Choice:** JSON + generated Markdown (D-12).
**Notes:** Table layout was decided alongside (D-13): four tables, because Δ, p,
and MDD are properties of a *pair*, not of a row — folding them into the
candidate table would force a single implied baseline and mislead anyone assuming
a different one. Sorting is by TechnicalScore descending, tie-broken by
fingerprint; **HR@10 is never the sort key** (D-14), a deliberate reversal of the
`RUNS.md` habit that `PROJECT.md` names as misleading. Per-bucket σ is computed
from the observed rate rather than hardcoded from MEAS-09's illustrative figures
(D-15).

---

## Significance & win policy

| Option | Description | Selected |
|--------|-------------|----------|
| Test HR@10, MRR, MTTC separately, then combine | Reports each term's own verdict. Triples the family size and invites cherry-picking whichever term moved. | |
| Test TechnicalScore as the single primary statistic | The competition's own objective and the unit the ≥0.01 floor is denominated in; the three terms are still always reported jointly. | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Holm family = candidates × 4 scenarios | Corrects everything uniformly. Inflates the family 4× and destroys power on the comparison that decides anything, while adding power to a Boundary bucket (n=10) that can detect nothing. | |
| Holm family = candidates vs a common baseline (k−1 comparisons) | Per-scenario results stay descriptive with stated σ and bucket caveats, never Holm-corrected — and the report says so explicitly. | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| ≥0.01 practical floor applied to the raw Δ | Simpler ordering. Lets a candidate clear the floor on selection bias alone. | |
| ≥0.01 floor applied after the winner's-curse correction | The floor asks "is this worth believing and shipping?" — so it must be asked of the believable gain. | ✓ |

**Choice:** TechnicalScore primary (D-16); Holm family = candidates only (D-19);
floor applied post-correction (D-20).
**Notes:** D-20 is flagged in CONTEXT.md as the most consequential ordering call
in the phase — `PROJECT.md` records winner's-curse inflation at 0.022–0.030,
more than the entire remaining recall headroom, so a pre-correction floor would
be cleared by selection bias alone. Three further decisions fell out of this
area: TechnicalScore is a non-linear statistic of the sample (Efficiency is a
function of *mean* MTTC), so the bootstrap resamples paired sessions and
recomputes the score from scratch rather than averaging a per-session value
(D-17); the permutation test swaps within pairs, never across candidates (D-18);
and the winner's-curse correction is the order-statistic method over
`statistics.NormalDist` with k printed in the report so Phase 5 can re-derive it
(D-21). A win requires `p_holm < 0.05` **and** `Δ_corrected ≥ 0.01` **and** no
HR@10 regression failing the exchange rate — any single-criterion pass is
reported as not-a-win with the failing criterion named (D-23). Resampling is
content-seeded from the candidate fingerprints at a fixed 10,000 resamples, so
verdicts are byte-reproducible (D-24).

---

## Claude's Discretion

The user delegated all four areas explicitly. Beyond the locked decisions, these
were left open for the researcher and planner:

- Module layout inside `arena/`, beyond the two fixed points (single evaluator
  seam; allow-list-validated `CandidateSpec`)
- Bootstrap CI flavour — percentile (safe default) vs BCa
- MDD derivation — normal-approximation closed form vs simulation
- HR@K curve source — defaults to `best_rank` (what the evaluator actually
  scores, and needs no trace file); a per-turn trace-derived curve is a bonus

## Deferred Ideas

- Extending `Agent` to accept belief / question / fusion overrides — Phase 3,
  paired with extending the `CandidateSpec` allow-list
- De-duplicating the session-mapping wrapper between `arena/` and
  `experiments/run_public.py` — Phase 8 cleanup, if still worthwhile
- Per-turn slate-trace-derived HR@K curve — only if a later phase needs rank
  movement across turns rather than at the scored turn
- Expanded sessions and the paraphrase probe — Phase 2 (MEAS-10 … MEAS-13);
  Phase 1 validates on the existing 200 sessions so the instrument is trusted
  before the corpus changes underneath it
- Artifact build cost reduction — Phase 6 (HARD-06), orthogonal to the rig
