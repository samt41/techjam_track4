# TechJam Track 4 — Conversational Shopping Agent

## What This Is

A multi-turn conversational shopping agent for the TechJam 2026 Conversational
E-Commerce Search Challenge (Track 4). It talks to a simulated customer, keeps
structured state about what they want, asks clarifying questions, and returns up
to ten ranked `parent_asin` values from a frozen 50,000-product Amazon
Clothing/Shoes/Jewelry catalog. A hidden target product is scored on exact match.

An agent already exists and works: deterministic, zero runtime dependencies,
stdlib + SQLite/FTS5 only, scoring HR@10 `0.920` / TechnicalScore `0.7688` on
the 200 public sessions. **This milestone is not about building an agent. It is
about winning a hackathon** — which, per the judging rubric, is a materially
different objective from maximizing the retrieval metric.

## Core Value

**Maximize total rubric score, not HitRate@10.**

Two measurements drive every prioritization call in this project:

1. **TechnicalScore is evidence feeding one criterion of five.** Technical
   Execution is 35%, and the competition specification states explicitly that
   TechnicalScore "does not represent the entire Technical Execution score." 65%
   of the outcome does not touch the retrieval metric at all.
2. **Within the metric, recall is nearly exhausted and ranking is not.** MRR and
   Efficiency are both bounded above by HR@10, so at current recall every term
   ceilings at `0.920`. See the headroom decomposition in Context. Roughly
   **0.151 points sit in ranking and speed; 0.040 sit in recall**, and the
   project's own `docs/STATUS.md` documents most of that 0.040 as unrecoverable
   under-specification.

When a tradeoff arises, prefer the change that moves more rubric points per unit
of effort — which is usually *not* the change that moves HR@10.

## Requirements

### Validated

Shipped, measured, and confirmed working in the existing codebase. These are
locked; changing them requires explicit discussion.

- ✓ Agent implements the required organizer interface (`reset`, `respond`) and
  conforms to `docs/agent_api_contract.json` — existing
- ✓ Multi-route retrieval over a prebuilt SQLite artifact: structured attribute
  routes, exact FTS5, expanded FTS5, category fallback, counterfactual
  relaxation — existing
- ✓ Deterministic TF-IDF posting fallback when FTS5 is unavailable, verified at
  near-parity (HR@10 `0.75`) on the full public set — existing
- ✓ Typed constraint extraction using a catalog-derived gazetteer classified by
  document-frequency evidence, with scoped negation — existing
- ✓ Preference ledger with supersede/retract semantics; intent override moved
  from HR@10 `0.20` to `0.90` — existing
- ✓ Bayesian belief ranking with auditable per-component log-odds contributions
  — existing
- ✓ Expected-posterior-entropy clarification question selection, computed over
  the full strict population before tail fill — existing
- ✓ Byte-level deterministic reproducibility, verified across two independent
  full runs (200 sessions, 10,419 trace events, exact match) — existing
- ✓ Zero declared runtime dependencies; fully offline; reports
  `{"prompt_tokens": 0, "completion_tokens": 0}` — existing
- ✓ Typed diagnostics: seven fixed-schema trace events per turn to JSONL —
  existing
- ✓ 167 tests (stdlib `unittest`), runnable with no catalog download — existing
- ✓ Reproducible experiment harness publishing five files per run — existing
- ✓ HR@10 `0.920`, MRR `0.5245`, MTTC `3.425`, TechnicalScore `0.7688` on all
  200 public sessions — existing
- ✓ Statistically honest measurement rig (`arena/`): paired bootstrap with an
  Efron-Tibshirani `(R+1)` percentile interval, paired permutation test,
  Holm-Bonferroni correction, a `>=0.01` TechnicalScore practical floor, and a
  winner's-curse order-statistic correction — validated in Phase 1
  (MEAS-01..09, MEAS-14..16)
- ✓ Committed leaderboard as source of truth (`experiments/baselines/leaderboard.json`
  plus the rendered `experiments/LEADERBOARD.md`), carrying TechnicalScore, HR@10,
  MRR and MTTC overall and per scenario, an HR@1/@3/@5/@10 curve from retained
  traces alone, and per-bucket binomial sigma with a decision-grade flag —
  validated in Phase 1, regenerates byte-identically
- ✓ Fingerprinted `CandidateSpec` provenance: one configuration mints one digest
  across CLI and programmatic paths, and a record's stored fingerprint is checked
  against the reader's derivation, failing closed — validated in Phase 1 (MEAS-14)
- ✓ Single evaluator seam: `arena/` calls `evaluate()` as an opaque function and
  imports no `evaluator.local_evaluator` internals, machine-checked — validated in
  Phase 1 (MEAS-15)

### Active

Hypotheses until shipped and measured.

**Measurement rig — build the instrument before trusting any comparison**

- [ ] Leaderboard reports TechnicalScore with all three terms broken out, per
      scenario, not HR@10 alone
- [ ] Per-scenario MRR and MTTC recovered from existing trace data (currently
      only per-scenario HR@10 is recorded)
- [ ] HR@1 / @3 / @5 / @10 curve reported as technical evidence
- [ ] Expanded dev session volume beyond the 200 public sessions, using the
      unmodified official evaluator. At n=200 the binomial standard error is
      **σ ≈ 0.019 HR@10**, so 0.920 and 0.940 are statistically
      indistinguishable on the public set
- [ ] Paraphrase probe: sessions carrying authored `intent_card` + `behavior`
      that describe targets in customer language rather than quoting catalog
      text — the only way to measure vocabulary generalization
- [ ] Candidate comparison is statistically honest: paired tests joined on
      `sample_id`, Holm-Bonferroni across competing candidates, a practical
      floor of ≥0.01 TechnicalScore, and a minimum-detectable-difference
      reported beside every leaderboard row so "no significant difference" is
      visibly distinct from "we could not have seen one"
- [ ] Winner's-curse correction applied before any candidate is declared the
      champion — selecting the best of k=5-10 candidates inflates apparent
      HR@10 by 0.022-0.030 through selection bias alone
- [ ] Scenario non-inferiority gates stated with their bucket-size caveat —
      Boundary is n=10 (σ ≈ 0.086) and Intent Override n=30 (σ ≈ 0.050), so a
      uniform "no regression" rule would reject good candidates on noise

**Score improvement — aimed at the terms with headroom**

- [ ] Rank-1 precision work (MRR): discriminate among already-retrieved
      candidates, where the target sits in the slate but below rank 1
- [ ] Question-quality work (MTTC): converge in fewer turns; clarification was
      never revisited after the SQLite migration despite moving 0.71 → 0.785 on
      the previous engine
- [ ] Offline LLM-generated semantic asset (Tier 1): replace the unprincipled
      six-entry `_EXPANSIONS` synonym table with real catalog-derived semantic
      coverage, baked into the artifact at build time
- [ ] Runtime LLM candidate (Tier 2) with deterministic fallback, measured on
      both the network-on and network-off paths
- [ ] Best measured candidate is selected and shipped

**Submission hardening — Feasibility and Technical Execution**

- [ ] Agent constructs successfully without a pre-built artifact (lazy,
      self-healing build) — currently `Agent.__init__` raises if the 580 MB
      artifact is absent, which fails the run at construction, not per-turn
- [ ] Artifact build cost reduced or justified; 580 MB / 60-90 s argues against
      "resource usage is proportionate"
- [ ] Bounded memory across an 800-session run (session state, turn history, and
      product cache all currently grow monotonically)
- [ ] Soft per-turn deadline that degrades to best-so-far rather than risking a
      timeout scored as a miss
- [ ] `requirements.txt` present per the recommended submission layout

**Deliverables — all five are mandatory and two were previously unknown**

- [ ] Public GitHub repository (currently **private**; history verified clean of
      organizer-only material)
- [ ] Well-structured, **commented** code covering all components (currently
      ~108 comment lines across 4,717 lines of agent code, ~2.3%)
- [ ] README: overview, setup, reproduction steps, limitations reflection, team
      contributions
- [ ] **Demo video** on YouTube, public, linked from Devpost — walkthrough
      variant (API usage, inference examples, result analysis) is accepted for
      backend/NLP tracks
- [ ] Devpost written description: problem fit, dev tools, APIs, libraries,
      datasets and assets
- [ ] Disclosure of latency, token usage, and estimated model cost

**Rubric positioning — the 65% that the metric does not touch**

- [ ] Impact & Relevance (20%): articulate value beyond the hackathon prompt —
      no per-query cost, privacy by construction, auditable recommendations
- [ ] Innovation & Problem Insight (20%): make the existing novelty legible, and
      present the public-set blind-spot discovery as a first-class finding
- [ ] Feasibility & Practicality (15%): claim the ground already held — zero
      dependencies, CPU-only, no credentials, deterministic

### Out of Scope

- **Modifying `evaluator/local_evaluator.py`** — it is byte-identical to the
  organizer's starter kit and must stay that way for reported results to be
  valid. Extending measurement happens through *data* the evaluator already
  accepts, never through code changes.
- **Catalog modification** — explicitly out of scope in the specification.
  Derived artifacts built from the catalog are not catalog modification.
- **Full-model training** — explicitly out of scope.
- **Multimodal search** — explicitly out of scope.
- **Infrastructure-heavy vector databases** — explicitly out of scope.
- **A user interface** — not required; the backend track accepts a walkthrough
  video instead.
- **Real transactions** — out of scope.
- **Shipping an agent that requires live credentials with no offline fallback** —
  `docs/submission_rules.md` reserves the right to disable network access during
  official scoring. No fallback means scoring zero, not scoring worse.
- **HR@10 as the primary optimization target** — retired on evidence. It was
  correct from 0.125 → 0.920 and stopped being correct around 0.90. Still
  reported; no longer the objective.
- **Widening the overfit phrase matchers** — the risk they were logged against
  is largely disproven (see Context). Effort here is misallocated.
- **Slate diversification / MMR-style reranking** — there is exactly one hidden
  target per session scored on exact match, so trading rank-1 concentration for
  slate variety is strictly negative for MRR.
- **Naive "rejected item = negative sample" propagated to attribute weights** —
  CRS literature (EAR, NFCR) reports this backfires. Negative evidence must stay
  bounded, decaying, and scoped to the specific `parent_asin`.
- **Cross-session or bandit personalization** — public and private sessions have
  verified zero user overlap, so nothing learned across sessions transfers.

## Context

**The competition.** Find a hidden target product as early and as highly ranked
as possible across at most 10 turns. Frozen 50,000-product catalog. 200 public
labeled sessions; 800 private sessions decide the score, with verified zero user
overlap and zero target overlap against public. Scenario mix is 40% Buying / 40%
Browsing / 15% Intent Override / 5% Boundary. Only `parent_asin` is scored, on
exact match.

**Scoring.**

```
TechnicalScore = 0.50 × HR@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency     = clip((11 - MTTC) / 10, 0, 1)
```

Reported separately for each of the four scenarios. Coverage is evidenced by
HR@K, ranking precision by MRR and top-k hit rate, conversational efficiency by
MTTC.

**Judging rubric.**

| Criterion | Weight |
|---|---:|
| Technical Execution | 35% |
| Innovation & Problem Insight | 20% |
| Impact & Relevance | 20% |
| Feasibility & Practicality | 15% |
| Presentation & Communication (final event only) | 10% |

**Headroom decomposition — why ranking beats recall.** MRR and Efficiency are
each bounded above by HR@10, so at current recall all three terms ceiling at
`0.920`, and TechnicalScore would equal `0.920` if every hit landed at rank 1 on
turn 1.

| Term | Current | Ceiling at current recall | Points available |
|---|---:|---:|---:|
| HR@10 | 0.920 | 1.000 | +0.040 |
| MRR | 0.5245 | 0.920 | **+0.119** |
| Efficiency | 0.7575 | 0.920 | +0.033 |

`experiments/RUNS.md` is sorted by HR@10 throughout, and `docs/STATUS.md`
concludes "the public ceiling is close." Both are true of recall and misleading
about the score. The miss audit that closed off further ranking work examined
*misses*; it says nothing about the 184 hits sitting below rank 1.

**Statistical reality of measuring any of this** (from `.planning/research/`,
which corrects an earlier claim in this document):

- The binomial standard error at n=200 is **σ ≈ 0.019 HR@10**, not the ±0.005
  single-session quantization step. A 95% interval on 0.920 spans roughly
  ±0.038 — so 0.920 and 0.940 are indistinguishable on the public set.
- Detecting a true 0.01 TechnicalScore difference needs roughly **3,900-15,700
  paired sessions**. Effect sizes of 0.02-0.03+ are the realistic
  detectable-and-decision-worthy range.
- Selecting the best of k=5-10 candidates inflates the winner's apparent HR@10
  by **0.022-0.030 through selection bias alone** — comparable to the entire
  remaining recall headroom. A naive bake-off manufactures its own winner.

Consequence: expanded session volume is not an optimization, it is a
precondition for the bake-off meaning anything.

**Metric exchange rates**, derived from the scoring weights:

- Any change that adds turns must clear **ΔMRR > 0.0667 × ΔMTTC** to break even
- HR@10 is **25× more sensitive per point than MTTC**, and 1.67× more than MRR

So a recall regression is the most expensive currency in this metric, and every
candidate must be judged on all three terms jointly, never one at a time.

**Correction to `.planning/codebase/CONCERNS.md`.** That document's headline risk
— that `evaluator/local_evaluator.py` is "a locally reimplemented simulator" and
that the two phrase matchers are overfit to wording the private set may rephrase
— is **mostly wrong**, verified by `git diff origin/tiktok/starter origin/master
-- evaluator/` returning empty. The evaluator is the organizer's file, unchanged.
The correct split:

- **Scaffolding phrasing is evaluator code**, emitted by `customer_reply`, so it
  is byte-identical on the private run. `_VERBOSE_DECLINE_RE` and
  `_SLATE_FEEDBACK_RE` are far safer than logged.
- **Constraint content differs.** `materialize_hidden_fields` branches: samples
  carrying `intent_card` + `behavior` use them (the private path); samples
  without one get `intent_card(product)`, which scrapes constraints verbatim
  from the target's own `features`/`details` (the public path). That is exactly
  why two miss audits found "zero vocabulary gaps" — on the public set the
  customer quotes the product. Organizer-authored private cards owe no such
  courtesy. **The public set structurally cannot measure vocabulary
  generalization.**

That first branch is also a supported extension point: supplying our own
authored cards exercises the private code path using the unmodified evaluator.

**Codebase state.** Layered deterministic pipeline behind a ports-and-adapters
storage boundary. Full analysis in `.planning/codebase/`. Design history and the
audit of every tuned constant in `docs/STATUS.md`; run history in
`experiments/RUNS.md`. A written-but-deliberately-unstarted spec for offline
semantic concept retrieval sits at
`docs/superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md`,
gated on evidence of a vocabulary gap that the public set cannot produce.

**Where the LLM fits.** The specification permits "legally accessible LLM APIs or
local models," and `docs/submission_rules.md` requires disclosure of network
need and fallback behavior. Three placements, in descending safety:

- **Tier 1 — build time, offline.** Run the LLM once over the catalog; freeze
  the output into a committed static asset. The shipped agent stays stdlib-only,
  deterministic, network-free, zero tokens. Preferred.
- **Tier 2 — runtime with deterministic fallback.** Constraint extraction is the
  high-leverage slot, since paraphrase is what the regex/gazetteer path cannot
  absorb. Network-off must cost a degradation, never a zero.
- **Tier 3 — the `message` field.** Untouched by TechnicalScore (the evaluator
  never reads it), but "transparent explanations" is a named Innovation
  Direction and a demo asset.

**Prior exploration.** No GSD spikes or sketches exist. All four git branches are
linear: `origin/tiktok/starter` is the organizer baseline (HR@10 `0.125`),
`origin/feature/deterministic-offline-agent` is an ancestor of `master` differing
only in docs, and `master`/`cervon` carry the current engine.

## Constraints

- **Evaluator immutability**: `evaluator/local_evaluator.py` is never modified —
  results reported against a modified evaluator are invalid.
- **Runtime purity**: the shipped agent is stdlib-only, offline-capable, and
  byte-deterministic. LLM contributions reach it as frozen assets, not live
  calls, unless a deterministic fallback sits underneath.
- **Network**: may be disabled during official scoring — an agent that cannot
  run without credentials scores zero.
- **Determinism**: preferred but not absolute. A non-deterministic candidate may
  be *spiked* to measure headroom; shipping one is a deliberate, evidenced
  decision, not a default.
- **Tech stack**: Python 3.10+, `uv`, CPython SQLite with FTS5 (graceful TF-IDF
  fallback verified). No GPU, no model server, no vector database.
- **Timeline**: 2+ weeks — room for a genuine multi-candidate bake-off.
- **Team**: solo. Contributions section is trivial; phases can sequence freely
  without ownership boundaries.
- **LLM access**: Cloudflare Workers AI (open-source models — GLM, DeepSeek and
  similar) for high-volume mechanical passes; Claude Opus/Sonnet subagents for
  judgment-heavy, moderate-volume work. Credentials supplied when needed.
- **Disk/compute**: ~61 MB catalog plus ~580 MB artifact, neither committed. Full
  public evaluation ~190 s on the reference machine.

## Key Decisions

| Decision | Rationale | Outcome |
|---|---|---|
| Optimize total rubric score, not HR@10 | TechnicalScore is evidence for one criterion of five; 65% of judging never touches it | — Pending |
| Target MRR and MTTC ahead of HR@10 | ~0.151 points available in ranking/speed vs ~0.040 in recall, most of which is documented unrecoverable | — Pending |
| Build the measurement rig before the bake-off | At n=200 one session is ±0.005 HR@10; candidates cannot be honestly compared inside the noise floor | — Pending |
| Extend measurement through data, never evaluator code | The evaluator is organizer-supplied and byte-identical; `materialize_hidden_fields` already accepts authored intent cards | — Pending |
| Prefer Tier 1 (offline, build-time) LLM use | Delivers semantic gain while keeping the submission deterministic, network-free, and zero-token | — Pending |
| LLM build step is separate from and not required by agent runtime; output is a committed checksummed asset | Lets us claim determinism honestly while using LLMs, and stops `Agent.__init__` acquiring a network dependency | — Pending |
| A runtime LLM candidate must carry a deterministic fallback | `submission_rules.md` reserves the right to disable network at scoring; no fallback means zero, not degraded | — Pending |
| Treat deliverables and rubric positioning as scoring work, not cleanup | Impact (20%) and Innovation (20%) are near-unaddressed while Feasibility (15%) is won but unclaimed | — Pending |
| Retire the "overfit phrase matcher" risk | Verified: the evaluator is unmodified organizer code, so its boilerplate is byte-identical on the private run | ✓ Good |
| Ship the best measured candidate, whatever it is | User directive: "if it wins, it ships" — subject to the network-fallback constraint above | — Pending |
| A hard go/no-go checkpoint gates score-improvement work | Stop once winner's-curse-corrected marginal gain falls below ~0.005 TechnicalScore and reallocate to the untouched 40%; this transition is where solo-dev time silently misallocates | — Pending |
| Paraphrase probe must be built anti-circularly | An LLM shown the target's catalog text reproduces its phrasing, measuring self-preference rather than generalization — the same defect class as the public-set blind spot, one level up. Never show catalog text in-prompt, gate on lexical overlap, freeze before iterating, cross-check with a second model family | — Pending |
| Generated semantic assets ship with an antonym/negation audit and checksum pinning | A synonym table that flips polarity on a negated attribute recreates the two silent-mismatch bugs already fixed, at a volume that defeats manual review | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-08-31 — Phase 1 complete (measurement rig core, verification
`passed` 10/10 after a six-plan gap-closure round). Immediate follow-up closed the
report-identity, duplicate-candidate, session-row validation, staging-gitignore,
mixed-resample, same-dataset, and override-value gaps raised in `01-REVIEW.md`.
Remaining Phase 1 review debt is now lower-risk cleanup around publish recovery,
legacy import hardening, duplicated evaluator digest pins, and source prose.*
