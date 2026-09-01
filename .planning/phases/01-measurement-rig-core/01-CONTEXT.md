# Phase 1: Measurement Rig Core - Context

**Gathered:** 2026-08-30
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers the **measurement instrument**, not a candidate. Three
components:

1. **Arena** — a fingerprinted `CandidateSpec` is run through the unmodified
   organizer evaluator, producing per-session rows joined on `sample_id`.
2. **Leaderboard** — TechnicalScore decomposed into HR@10 / MRR / MTTC /
   Efficiency, overall and per scenario, plus an HR@1/@3/@5/@10 curve, computed
   from retained run artifacts without re-invoking the agent.
3. **Statistics engine** — paired bootstrap + paired permutation, Holm-Bonferroni,
   minimum detectable difference, the ≥0.01 TechnicalScore practical floor, and
   the winner's-curse order-statistic correction — validated before any new
   candidate exists.

**Explicitly not in this phase:** no ranking change, no efficiency change, no
semantic asset, no new evaluation sessions or paraphrase probe (Phase 2), no
candidate of any kind. The only agent configurations exercised are ones the
shipped `Agent` already accepts.

**Requirements:** MEAS-01 … MEAS-09, MEAS-14, MEAS-15, MEAS-16 (12 total).

</domain>

<decisions>
## Implementation Decisions

The user delegated all four gray areas: *"choose the clearest and most robust
and winnable solution for each question you ask yourself."* Every decision below
is Claude's call, made against the Core Value (total rubric score, not HR@10)
and the repo's hard invariants. Rationale is recorded because Phase 3/4/5 will
be adjudicated by these rules and must be able to re-derive why.

### Finding that reframes the phase (read this first)

**F-01: There is no retained per-session data on disk.** `experiments/` contains
only `RUNS.md` and three scripts. `experiments/*/` is gitignored and no run
directory exists. `RUNS.md` holds **aggregate** numbers only. The roadmap's
"retained historical run" / "retained trace data" / "two retained historical
rows" (Success Criteria 1–3, MEAS-03, MEAS-16) therefore describe data that must
be **regenerated** before it can be validated against.

**F-02: The regeneration is cheap and the data shape is already correct.**
`evaluate()` returns per-session `{sample_id, scenario_type, hit, first_hit_turn,
best_rank, reciprocal_rank}` (`evaluator/local_evaluator.py:269-276`) and
`run_public.py` already persists it to `sessions.jsonl`. Once a run exists, every
Phase 1 metric — HR@K curve, per-scenario MRR/MTTC, paired tests — is derivable
from that file alone, with the agent never re-invoked. Full run ≈ 190 s; catalog
and 580 MB artifact are already built locally.

### Baseline data provenance

- **D-01: Validate in three layers, not one.** Each layer catches a different bug
  class, and the total cost is three evaluation runs (~10 min) plus unit tests.
  - *Layer 1 — synthetic known-answer fixtures.* Hand-constructed paired vectors
    where the bootstrap CI, permutation p, Holm-adjusted p, MDD, and winner's-curse
    correction have analytically checkable answers. Catches arithmetic and
    pairing bugs. Lives in the stdlib `unittest` suite alongside `tests/fixtures.py`,
    requires no catalog download, runs in the existing 167-test suite.
  - *Layer 2 — reproduction anchor.* One real run reproduces the retained
    `RUNS.md` row and the leaderboard must report **HR@10 `0.920`, MRR `0.5245`,
    MTTC `3.425`, TechnicalScore `0.7688`**, with per-scenario HR@10 boundary
    `0.90` / browsing `0.95` / buying `0.90` / intent_override `0.90`. This is the
    literal MEAS-16 anchor and simultaneously produces the `sessions.jsonl` that
    Success Criteria 1 and 2 consume.
  - *Layer 3 — two adjudication controls.* A **known-large-effect pair** and a
    **known-near-null pair**, so the engine is proven on both a true positive and
    a true negative. A rig only validated on a real difference cannot be trusted
    to say "no difference" honestly — and saying that honestly is the entire point
    of MEAS-06.

- **D-02: The three runs, and why these three.** All are reproducible today at
  HEAD with flags `run_public.py` already accepts. Run A is an arm of both pairs,
  so three runs yield three validations.

  | Run | Flags | Role | Expected |
  |---|---|---|---|
  | A | `--lexical-mode auto --exploration disabled` | Anchor + shared baseline arm | HR@10 `0.920`, TS `0.7688` |
  | B | `--lexical-mode fallback --exploration disabled` | Large-effect arm (TF-IDF path) | ≈ HR@10 `0.75`, TS `0.599` |
  | C | `--lexical-mode auto --exploration tail-only` | Near-null arm | ≈ metric-identical to A |

  - **A vs B** (ΔTS ≈ 0.17, far above any plausible MDD) — the engine **must**
    return significant and clear the ≥0.01 floor. If it does not, the test is
    broken.
  - **A vs C** — `RUNS.md` records this ablation as metric-identical on the
    superseded engine (exploration fired on 7 of ~1,500 turns, all empty-pool,
    changed zero hits; MTTC moved `4.94` → `4.935`, i.e. one session by one turn).
    The engine must return non-significant **and** report an MDD that makes the
    null legible as "we would have seen a real effect" rather than "we were blind."

- **D-03: Do not assume run C is null — measure it.** The ablation in `RUNS.md`
  was measured at superseded HEAD `e76b3ab` (HR@10 `0.76`), not current HEAD.
  The validation is that the engine correctly adjudicates *whatever the true delta
  is*, with MDD reported alongside. If C turns out non-null at current HEAD, that
  is a finding to record, not a failure of the rig. Plans must not encode
  "expect p > 0.05" as a hard assertion for A vs C; assert instead that the
  verdict, CI, and MDD are internally consistent and reproducible.

- **D-04: Stop the evidence evaporating — commit a reduced per-candidate record.**
  The root cause of F-01 is that `.gitignore` line `experiments/*/` swallows every
  run directory. Fix it by committing a small, permanent record per candidate:
  `experiments/baselines/<run-id>/sessions.jsonl` + `summary.json`
  (200 rows ≈ 26 KB per candidate; three candidates ≈ 78 KB). Add a
  `!experiments/baselines/` negation to `.gitignore`. The bulky trace
  (`retrieval_routes.jsonl`, ~10,400 events) stays uncommitted. From this phase
  onward, "retained historical row" means a committed file, not a number in prose.

- **D-05: `experiments/RUNS.md` is not rewritten.** It carries irreplaceable prose
  evidence — the exploration ablation, the two-run byte-determinism verification,
  the forced-fallback verification, the public-ceiling miss audit. It gains a
  pointer to the new leaderboard and nothing is deleted.

### Arena & CandidateSpec

- **D-06: New `arena/` package. `experiments/run_public.py` is left byte-untouched.**
  It is the reproducer that produced the retained determinism evidence; perturbing
  it costs a re-verification run and buys nothing. Keeping both means two
  independent code paths must agree on `0.920 / 0.5245 / 3.425 / 0.7688` — which
  is *stronger* validation evidence than one path, and is itself reportable under
  Technical Execution.

- **D-07: The ~25-line session-mapping wrapper is deliberately re-implemented in
  `arena/`, not imported from `experiments/`.** This is intentional duplication,
  not debt: importing from `experiments.run_public` would transitively pull the
  evaluator import into the arena and defeat D-08. Comment the *why* at the
  duplication site, per repo convention. Its correctness property is unchanged —
  the evaluator generates session UUIDs in sample order, so recording each
  `reset` maps UUID → `sample_id`, and the join happens only **after**
  `evaluate()` returns. **Ground truth never reaches the `Agent`** (hard invariant).

- **D-08: MEAS-15 becomes a machine-checked invariant, not a promise.** Exactly one
  module — `arena/evaluator_bridge.py` — may import from `evaluator/`, and its
  entire body is the re-export of the public entry points the arena calls
  (`evaluate`, `catalog_index`, `load_jsonl`). A test walks the AST of every other
  module in `arena/` and asserts zero `evaluator` imports. This converts Success
  Criterion 5 ("no import of `evaluator.local_evaluator` internals beyond calling
  `evaluate()` as an opaque function") from prose into a failing test, and is the
  clearest possible evidence that the evaluator was never touched.
  `evaluator/local_evaluator.py` remains byte-identical to the organizer file.

- **D-09: `CandidateSpec` is a frozen slotted dataclass carrying only what is
  actually applied.** Fields: candidate `name`; `code_revision` (git SHA, via the
  existing `code_revision()` in `experiments/analyze_public.py:229`); an ordered
  `overrides` mapping passed into `Agent(...)`; and input fingerprints
  (`catalog_sha256`, `dataset_sha256`). `fingerprint` = SHA-256 over the canonical
  `json.dumps(..., sort_keys=True)` of all of it. Identical inputs → identical
  hash, twice (Success Criterion 5).

- **D-10: `overrides` is validated against an allow-list at construction; there are
  no inert fields.** `validate()` raises `ValueError` on an unknown key, matching
  the repo's dataclass-`validate()` convention. Phase 1's allow-list is exactly
  what `Agent.__init__` accepts today (`starter/agent.py:18-25`):
  `lexical_mode`, `exploration`, `artifact_path`. Belief/question/fusion knobs are
  **not** constructor-injectable yet — Phase 3 extends `Agent` and the allow-list
  together. A fingerprint must never claim to describe a configuration that was
  not applied; that failure mode silently invalidates an entire bake-off.

- **D-11: Git revision is recorded on every candidate, config-injection is preferred
  where it exists.** Some Phase 3/4 candidates genuinely are code changes rather
  than config; recording the SHA makes those attributable and reproducible instead
  of unfalsifiable. Config-injection stays preferred because it keeps candidates
  comparable within one process.

### Leaderboard artifact

- **D-12: JSON is the source of truth; Markdown is a generated view; both are
  committed.** `experiments/baselines/leaderboard.json` is what tests assert
  against and what Phase 3/4/5 append to. `experiments/LEADERBOARD.md` is
  generated from it, human- and judge-readable, and costs nothing to keep current.
  A print-only CLI was rejected: a report that exists only in a terminal cannot be
  cited by the Innovation or Technical Execution narrative.

- **D-13: Four tables, because a p-value is a property of a *pair*, not a row.**
  1. *Candidates* — name | fingerprint | HR@10 | MRR | MTTC | Efficiency | TechnicalScore
  2. *HR@K curve* — HR@1 / @3 / @5 / @10 per candidate (MEAS-02)
  3. *Per-scenario breakout* — HR@10 / MRR / MTTC per scenario, each row stating
     its bucket `n` and binomial σ (MEAS-01, MEAS-09)
  4. *Pairwise adjudication* — baseline | ΔTS | 95% CI | permutation p |
     Holm-adjusted p | MDD | k | winner's-curse-corrected ΔTS | floor verdict
     (MEAS-04 … MEAS-08)

  Folding Δ/p/MDD into table 1 would force a single implied baseline and silently
  mislead every reader who assumed a different one.

- **D-14: Sort by TechnicalScore descending, tie-broken by fingerprint.** `RUNS.md`
  is "sorted by HR@10 throughout" and `PROJECT.md` names that as actively
  misleading about the score. **HR@10 is never the sort key.** The tie-break on a
  stable key preserves the determinism invariant.

- **D-15: Per-bucket σ is computed from the observed rate, not hardcoded.** The
  `σ ≈ 0.086` / `σ ≈ 0.050` figures in MEAS-09 are illustrative; the report
  derives σ from the bucket's own `n` and observed `p`. Boundary (n=10) and Intent
  Override (n=30) rows carry an explicit "not decision-grade in isolation" flag.

### Statistics & win policy

- **D-16: The primary statistic is TechnicalScore.** It is the competition's own
  objective and the unit the ≥0.01 practical floor is denominated in. HR@10, MRR
  and MTTC are always *reported* jointly (RANK-05, CONV-03) and an HR@10
  regression is flagged as disqualifying unless the exchange-rate math clears —
  but the hypothesis test is on TechnicalScore alone. Testing three metrics
  separately would triple the family size for no gain and invite cherry-picking
  whichever term happened to move.

- **D-17: TechnicalScore is a non-linear statistic of the sample — resample
  sessions, then recompute it from scratch.** `Efficiency = clip((11 − mean(MTTC))/10, 0, 1)`
  is a function of a *mean*, not a mean of per-session values, so the score cannot
  be averaged session-wise. The bootstrap resamples `sample_id`-paired sessions
  with replacement and recomputes HR@10, MRR, MTTC and then TechnicalScore on each
  resample. This is exactly the bug the Layer-1 fixtures must catch.

- **D-18: The permutation test is paired — swap within pairs, never across
  candidates.** For each session, randomly swap its (A, B) outcome, recompute
  ΔTechnicalScore, accumulate the null. An independent-sample permutation on the
  same data would be wrong and would look plausible; the A-vs-C control is the
  tripwire that exposes it.

- **D-19: The Holm-Bonferroni family is the candidates compared against a common
  baseline in one adjudication event (k−1 comparisons) — *not* candidates × scenarios.**
  Per-scenario results are non-inferiority gates with stated bucket caveats, not
  primary hypotheses. Folding four scenarios in would inflate the family 4× and
  destroy power on the one comparison that decides anything, while adding power to
  a Boundary bucket (n=10) that can detect nothing regardless. **Per-scenario
  numbers are reported descriptively with their σ and are never Holm-corrected**,
  and the report says so in text so the omission is deliberate rather than hidden.

- **D-20: Order of operations — the practical floor is applied AFTER the
  winner's-curse correction.** This is the most consequential ordering call in the
  phase.
  1. Paired ΔTechnicalScore + 95% bootstrap CI
  2. Paired permutation p
  3. Holm-adjust across the k−1 comparisons
  4. Winner's-curse-correct the **selected champion's** Δ for having been chosen
     as the maximum of k
  5. Test the **corrected** Δ against ≥ 0.01

  Rationale: the floor asks "is this gain big enough to believe and ship?" — that
  question must be asked of the believable gain. Applying the floor to the raw Δ
  would let a candidate clear 0.01 on selection bias alone, which is precisely the
  0.022–0.030 inflation `PROJECT.md` warns about, i.e. more than the entire
  remaining recall headroom.

- **D-21: Winner's-curse correction is the order-statistic (expected-maximum)
  method.** Subtract `E[max of k draws from N(0, σ̂)]`, where σ̂ is the paired-
  difference standard error and k is the number of candidates actually compared.
  Computable from `statistics.NormalDist` (stdlib, deterministic), and **k is
  printed in the report** so the correction is auditable and re-derivable. Phase 5
  (POS-04) consumes this exact number against the ~0.005 stopping threshold.

- **D-22: MDD is reported beside every adjudication row** as the smallest true
  ΔTechnicalScore detectable at 80% power, α = 0.05, given the observed
  paired-difference SD and n. This is the mechanism that makes "no significant
  difference" visibly distinct from "we could not have detected one" (MEAS-06).

- **D-23: A "win" requires all three, jointly.** `p_holm < 0.05` **and**
  `Δ_corrected ≥ 0.01` **and** no HR@10 regression that fails the exchange-rate
  check (`ΔMRR > 0.0667 × ΔMTTC`; HR@10 is 25× more sensitive per point than
  MTTC). Any single-criterion pass is reported as *not a win*, with the failing
  criterion named.

- **D-24: Resampling is deterministic and content-seeded.** Seeds derive from the
  SHA-256 of the two candidate fingerprints — never from the clock — matching the
  repo's "randomness is always seeded from stable content" convention. Resample
  count is a recorded module constant: **10,000** for both bootstrap and
  permutation. Two runs of the adjudication on the same inputs must produce
  byte-identical verdicts.

### Claude's Discretion

The user delegated the whole set, so everything above is discretionary — but
these specifically are left open for the planner and researcher to resolve, and
the decisions above do not constrain them:

- Exact module layout inside `arena/` (file split, naming) beyond the two fixed
  points: `arena/evaluator_bridge.py` is the sole evaluator seam (D-08), and
  `CandidateSpec` validates against an allow-list (D-10).
- Bootstrap CI flavour (percentile vs BCa). Percentile is the safe default;
  BCa only if the researcher establishes it is worth the added surface at
  n = 200 with a stdlib-only implementation.
- MDD derivation detail (normal-approximation closed form vs simulation from the
  observed paired-difference distribution). Either is acceptable if the fixtures
  in D-01 Layer 1 pin the answer.
- Whether the HR@K curve is derived from `best_rank` (the rank the evaluator
  actually scored, at the first-hit turn) or additionally from per-turn slate
  trace events. **Default to `best_rank`** — it is exactly what the metric scores
  and it needs no trace file, which keeps D-04's committed record small. Any
  richer per-turn curve is a bonus, not a requirement.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Objective, priorities, and statistical premises
- `.planning/PROJECT.md` — Core Value, the headroom decomposition table, the
  "Statistical reality" block (σ ≈ 0.019 HR@10 at n=200; 3,900–15,700 paired
  sessions to detect ΔTS = 0.01; winner's-curse inflation 0.022–0.030), metric
  exchange rates, and the Key Decisions table
- `.planning/REQUIREMENTS.md` — MEAS-01 … MEAS-09, MEAS-14, MEAS-15, MEAS-16
- `.planning/ROADMAP.md` § "Phase 1: Measurement Rig Core" — the five success
  criteria this phase is verified against
- `.planning/research/SUMMARY.md` — synthesized research findings
- `.planning/research/PITFALLS.md` — the source of the statistical-honesty
  requirements; read before implementing any test
- `CLAUDE.md` — hard invariants (determinism, evaluator immutability, ground
  truth never reaching the `Agent`, stdlib-only), naming and code-style conventions

### The evaluator (read-only — never modified)
- `evaluator/local_evaluator.py:188-201` — `metric_summary`: HR@10, MRR, MTTC
- `evaluator/local_evaluator.py:269-276` — the per-session record the whole
  leaderboard is derived from
- `evaluator/local_evaluator.py:279-291` — Efficiency, TechnicalScore, and the
  per-scenario grouping
- `docs/competition_specification.md` — scoring formula and scenario mix
- `docs/submission_rules.md` — disclosure obligations

### Existing harness and history
- `experiments/run_public.py` — the frozen reproducer; source of the
  session-mapping pattern (`_SessionMappingAgent`, lines 31-56), atomic publish
  (`_publish`, lines 135-150, incl. the Windows `os.replace` note), and the
  five-file run layout. **Left untouched by this phase (D-06).**
- `experiments/analyze_public.py:229` — `code_revision()`, reused by `CandidateSpec`
- `experiments/RUNS.md` — the retained aggregate rows (MEAS-16 anchor), the
  exploration ablation, the two-run determinism verification, the forced-fallback
  verification. **Not rewritten (D-05).**
- `docs/STATUS.md` — audit of every tuned constant and the public-ceiling analysis

### Codebase structure
- `.planning/codebase/ARCHITECTURE.md` — layering, ports-and-adapters boundary
- `.planning/codebase/CONVENTIONS.md` — naming, frozen dataclasses, ordering and
  tie-break rules
- `starter/agent.py:18-25` — the `Agent.__init__` signature that bounds the
  Phase 1 `CandidateSpec` allow-list (D-10)
- `tests/fixtures.py` — fixture-builder pattern for tests that need no catalog

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Per-session record from `evaluate()`** — `{sample_id, scenario_type, hit,
  first_hit_turn, best_rank, reciprocal_rank}`. Already contains everything MEAS-01
  through MEAS-04 need: `best_rank` yields the whole HR@1/@3/@5/@10 curve,
  `reciprocal_rank` yields MRR, `first_hit_turn` yields MTTC, and `sample_id` is the
  paired-test join key.
- **`_SessionMappingAgent` (`experiments/run_public.py:31-56`)** — maps evaluator
  session UUIDs back to `sample_id` without touching the evaluator, joining only
  after `evaluate()` returns. Re-implemented in `arena/` per D-07.
- **`_publish` (`experiments/run_public.py:135-150`)** — atomic tempdir-then-rename
  publish with the Windows `WinError 183` path handled. Reuse the pattern.
- **`code_revision()` (`experiments/analyze_public.py:229`)** — git SHA for
  `CandidateSpec`.
- **`_sha256` (`experiments/run_public.py:275-280`)** — chunked file fingerprinting
  for catalog/dataset inputs.
- **`DEFAULT_BELIEF_CONFIGURATION.as_dict()` / `QuestionModelConfiguration.default().as_dict()`** —
  already serialized into `summary.json`; config is therefore already
  fingerprintable in principle, which is what makes D-09 cheap.
- **`tests/fixtures.py`** — tiny catalogs in temp dirs; the 167-test suite runs with
  no catalog download. Layer-1 statistical fixtures follow this pattern.

### Established Patterns
- **Frozen slotted dataclasses with `validate()` raising `ValueError`** — the shape
  `CandidateSpec` must take (D-09, D-10).
- **Determinism as an acceptance property** — every sort carries a stable final
  tie-break (`parent_asin` in the agent; candidate fingerprint in the leaderboard,
  D-14); randomness is content-seeded, never clock-seeded (D-24).
- **Ports-and-adapters** — `ProductSearchBackend` is the existing precedent for the
  single-seam boundary D-08 applies to the evaluator.
- **Canonical JSON serialization** — `json.dumps(..., indent=2, sort_keys=True)` for
  summaries, `sort_keys=True` per line for JSONL. Fingerprints depend on this.
- **Zero runtime dependencies** — no `numpy`/`scipy`. Bootstrap, permutation, Holm,
  MDD and the order-statistic correction are hand-rolled over `random`, `statistics`
  (incl. `NormalDist`) and `math`.
- **Comment the *why*, never the *what*** — load-bearing for D-07's deliberate
  duplication and D-20's ordering.

### Integration Points
- `arena/evaluator_bridge.py` → `evaluator.local_evaluator` — the **only** permitted
  seam, asserted by an AST test (D-08).
- `arena/` → `starter.agent.Agent(...)` — candidate construction, bounded by the
  D-10 allow-list.
- `arena/` → `experiments/baselines/` — committed per-candidate `sessions.jsonl` +
  `summary.json`, plus `leaderboard.json` (D-04, D-12).
- `experiments/LEADERBOARD.md` — generated view; `experiments/RUNS.md` gains a
  pointer to it and is otherwise unchanged (D-05).
- `.gitignore` — add `!experiments/baselines/` to escape the `experiments/*/`
  blanket ignore (D-04).
- Phase 3/4 consume `CandidateSpec` + the adjudication verdict; Phase 5 (POS-04)
  consumes the winner's-curse-corrected Δ from D-21 directly.

</code_context>

<specifics>
## Specific Ideas

- **The MEAS-16 anchor is a literal number match**, not a vibe: the leaderboard
  built from run A must report HR@10 `0.920`, MRR `0.5245`, MTTC `3.425`,
  TechnicalScore `0.7688`, with per-scenario HR@10 boundary `0.90`, browsing
  `0.95`, buying `0.90`, intent_override `0.90`. If it does not, either the rig or
  the historical row is wrong and the phase does not proceed until that is resolved.

- **Two independent code paths agreeing is the evidence, not an accident.** Keeping
  `run_public.py` frozen alongside the new `arena/` (D-06) means the anchor is
  cross-checked by construction. Say so in the Technical Execution narrative.

- **The rig must be able to say "no."** The A-vs-C control exists because a
  measurement instrument that has only ever been shown a real effect is not
  validated. MEAS-06's distinction — "no significant difference" versus "we could
  not have detected one" — is the honesty claim this whole phase is built to
  support, and it is a first-class Innovation/Technical-Execution asset, not
  bookkeeping.

- **`.gitignore` is the actual root cause of F-01.** Fixing it (D-04) is a
  two-line change that permanently stops the project's own evidence from
  evaporating between milestones.

</specifics>

<deferred>
## Deferred Ideas

- **Extending `Agent` to accept belief / question / fusion configuration overrides** —
  needed for real Phase 3 candidates, deliberately out of Phase 1 (D-10). Phase 3
  extends `Agent.__init__` and the `CandidateSpec` allow-list together, in one change.
- **De-duplicating the session-mapping wrapper between `arena/` and
  `experiments/run_public.py`** — accepted duplication for now (D-07); revisit as
  cleanup in Phase 8 if it is still worth doing.
- **Per-turn slate-trace-derived HR@K curve** — richer than the `best_rank` curve
  Phase 1 ships; only worth building if a later phase needs rank movement across
  turns rather than at the scored turn.
- **Expanded evaluation sessions and the paraphrase probe** — Phase 2 (MEAS-10 …
  MEAS-13). Phase 1 deliberately validates on the existing 200 public sessions
  only, so the instrument is trusted before the corpus changes underneath it.
- **Reducing the 580 MB / 60–90 s artifact build cost** — Phase 6 (HARD-06),
  orthogonal to the rig.

</deferred>

---

*Phase: 1-Measurement Rig Core*
*Context gathered: 2026-08-30*
