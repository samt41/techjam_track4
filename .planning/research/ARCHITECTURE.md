# Architecture Research: Evaluation & Comparison Harness (Arena)

**Domain:** Statistical evaluation harness for comparing IR/conversational-agent candidates under a fixed, unmodifiable evaluator
**Researched:** 2026-08-29
**Confidence:** HIGH on statistical methodology and component-boundary design (established IR/NLP literature, direct reading of `evaluator/local_evaluator.py` and the existing codebase); MEDIUM on numeric sample-size assumptions (methodology is HIGH confidence, the disagreement-rate parameter that feeds it is an estimate, not yet measured); MEDIUM on generated-data validity limits (synthesized from ML-evaluation best practice, no single canonical source for this exact hazard).

## Executive framing

The existing agent is a layered deterministic pipeline behind a `ProductSearchBackend` port. That is not what this milestone builds. This milestone builds a second, orthogonal system: an **arena** that sits entirely in `experiments/`, never imports from or edits `evaluator/`, and treats `evaluate(agent, samples, ...)` as an opaque, trusted function called once per (candidate, dataset) pair. Everything the arena needs — per-session hit/rank/turn data — already comes back from that one call; the harness's job is to run it more (more candidates, more sessions, more scrutiny) and to be honest about what the numbers do and do not show.

Three things must be true of every design choice below:
1. **The evaluator is never touched.** Every extension is either (a) *data* fed into `evaluate()` — additional `samples` with `intent_card` + `behavior` — or (b) *analysis* performed on `evaluate()`'s return value after the fact.
2. **Comparisons are paired.** Every candidate sees the identical set of sessions (same `sample_id`s, same targets, same scenario mix). Paired analysis is not a nicety here; unpaired analysis on this data would be a methodological error (see Pattern 1).
3. **A "win" is a claim with a stated error rate**, not a bigger number. The 200-session noise floor is real (±0.005 HR@10 per session) and must be visible in every reported comparison, not just acknowledged once in prose.

## Standard Architecture

### System Overview

```
┌───────────────────────────────────────────────────────────────────────┐
│                    Arena Orchestration (new, this milestone)          │
│                    `experiments/arena/`                               │
│                                                                        │
│  ┌────────────────┐   ┌────────────────┐   ┌───────────────────┐     │
│  │ CandidateSpec  │   │ Dataset         │   │ StatisticalVerdict │     │
│  │ registry       │   │ registry        │   │ engine             │     │
│  │ (fingerprinted)│   │ (public/        │   │ (paired bootstrap/ │     │
│  │                │   │  expanded/      │   │  permutation,      │     │
│  │                │   │  probe)         │   │  Holm-Bonferroni)  │     │
│  └───────┬────────┘   └───────┬────────┘   └─────────┬──────────┘     │
│          │                    │                        ▲              │
│          ▼                    ▼                        │              │
│  ┌──────────────────────────────────────────┐          │              │
│  │   Arena runner: for each candidate ×      │──────────┘              │
│  │   each dataset, call evaluate() once      │                        │
│  └───────────────────┬────────────────────────┘                       │
└──────────────────────┼──────────────────────────────────────────────┘
                        │ agent, samples, catalog_ids, categories, products
                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│         FIXED, NEVER MODIFIED: `evaluator/local_evaluator.py`         │
│         `evaluate(agent, samples, ...) -> dict` with per-session      │
│         hit / first_hit_turn / reciprocal_rank / scenario_type        │
└──────────────────────┬──────────────────────────────────────────────┘
                        │ sessions: list[dict]
                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  Existing artifact layer (extend, do not replace)                     │
│  `experiments/run_public.py` (5-files-per-run) + `analyze_public.py`  │
│  summary.json / sessions.jsonl / failures.jsonl / retrieval_routes    │
│  .jsonl / ablation.md                                                  │
└──────────────────────┬──────────────────────────────────────────────┘
                        │ N run directories, one per candidate × dataset
                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  Arena artifacts (new)                                                │
│  `experiments/arena/<arena-id>/manifest.json`                         │
│  `experiments/arena/<arena-id>/leaderboard.json` (append-only)        │
│  `experiments/arena/<arena-id>/diffs/<a>-vs-<b>.jsonl`                │
└───────────────────────────────────────────────────────────────────────┘
```

The candidate axis (what varies) never touches the evaluator. The evaluator's only inputs are `agent` (a `reset`/`respond` duck-typed object) and `samples` (JSON-serializable dicts) — both are already the arena's construction surface.

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|-------------------------|
| `CandidateSpec` | Declarative, hashable description of one candidate's knobs (expansion source, extractor backend, belief config, question config, lexical mode) | Frozen dataclass + `sha256` of its canonical JSON, mirroring the existing `catalog_sha256`/`dataset_sha256` pattern in `run_public.py` |
| `CandidateFactory` | Builds an `Agent`-compatible object from a `CandidateSpec` | One function, `build_candidate(spec, artifact_path) -> Agent`, generalizing the inline `Agent(catalog_path, trace=..., exploration=..., lexical_mode=...)` call already in `run_public.py:83-88` |
| `SemanticExpansionSource` (new Protocol) | Pluggable term-expansion table | Structural-typing seam replacing the frozen `_EXPANSIONS` constant in `retrieval.py`; fake/real implementations swap like `ProductSearchBackend` already does |
| `ConstraintExtractionBackend` (new Protocol) | Pluggable constraint-extraction strategy with a mandatory deterministic fallback wrapper | Wraps today's gazetteer `ConstraintExtractor` as the fallback implementation; a Tier-2 LLM candidate implements the same Protocol and is wrapped by `FallbackConstraintExtractor(primary, fallback)` |
| Dataset registry | Named, checksummed collections of `samples` (public 200 / expanded generated / paraphrase probe) fed unmodified into `evaluate()` | JSONL files + a manifest entry recording sha256, generator seed, generator version |
| Arena runner | Executes the (candidate × dataset) matrix, one `evaluate()` call per cell, publishing existing 5-file runs plus arena-level rollups | `experiments/arena/run_arena.py`, built on top of (not replacing) `experiments/run_public.py`'s `run_experiment` |
| `StatisticalVerdict` engine | Paired bootstrap + permutation tests, Holm-Bonferroni correction, per-scenario non-inferiority check, effect-size threshold gate | Pure function over two or more `sessions.jsonl` files joined on `sample_id`; no dependency on the agent or evaluator |
| Leaderboard | Append-only ranked table with verdicts, not just scores | `experiments/arena/<arena-id>/leaderboard.json`, one row per (candidate, dataset), never mutated in place |
| Trace/session differ | Cross-candidate (not just cross-run-of-self) diff at the session level | Extends the existing byte-diff determinism check (`TESTING.md` step 5) from "same candidate twice" to "candidate A vs candidate B" |

## Recommended Project Structure

```
experiments/
├── run_public.py              # existing: single-candidate, 5-file run — UNCHANGED
├── analyze_public.py          # existing: miss attribution — UNCHANGED, reused per candidate
├── analyze_misses_b1.py       # existing — UNCHANGED
├── arena/                     # NEW — everything below is additive
│   ├── candidate_spec.py      # CandidateSpec dataclass, fingerprinting, registry of named candidates
│   ├── candidate_factory.py   # build_candidate(spec, artifact_path) -> Agent-compatible object
│   ├── datasets/
│   │   ├── generator.py       # catalog-sampling session generator (authored intent_card + behavior)
│   │   ├── probe.py           # paraphrase probe construction + lexical-overlap validator
│   │   └── registry.py        # named dataset -> path + sha256 + seed + generator_version
│   ├── stats.py                # paired bootstrap, paired permutation, Holm-Bonferroni, decision rule
│   ├── run_arena.py            # orchestrates candidate x dataset matrix; calls run_public.run_experiment per cell
│   ├── leaderboard.py          # appends verdicted rows; renders leaderboard.json + a markdown view
│   └── diff_sessions.py        # cross-candidate session-level diffing (extends determinism-diff pattern)
data/
├── public_set.jsonl           # existing 200, UNCHANGED
├── expanded_set.<seed>.jsonl  # NEW — generated sessions, checksummed, seed in filename or manifest
└── probe_set.<seed>.jsonl     # NEW — paraphrase probe, checksummed
```

### Structure Rationale

- **`experiments/arena/` is a new sibling, not a replacement.** `run_public.py` already does exactly the right thing for one candidate; the arena calls it (or its `run_experiment` function) once per candidate rather than re-implementing evaluation plumbing. This keeps the evaluator-adjacent code (`catalog_index`, `evaluate`, `load_jsonl`) imported from exactly one place.
- **`stats.py` has zero dependency on `Agent` or the evaluator.** It operates purely on `sessions.jsonl`-shaped data (list of dicts with `sample_id`, `hit`, `reciprocal_rank`, `first_hit_turn`, `scenario_type`). This means it can and should be built and unit-tested first, against the *existing* retained rows in `experiments/RUNS.md`, before any new candidate exists.
- **`datasets/generator.py` and `datasets/probe.py` are separate files** because they have different validity obligations: the generator's job is coverage and realism; the probe's job is *lexical divergence from the catalog, with everything else held constant*. Conflating them risks the probe silently inheriting the generator's vocabulary habits.
- **Dataset files live under `data/`, sibling to `public_set.jsonl`,** because they are `samples` inputs to the unmodified `evaluate()` function — never code, never evaluator input paths that need special-casing.

## Architectural Patterns

### Pattern 1: Paired comparison, never independent-sample comparison

**What:** Every statistical comparison operates on the *difference per session* between two candidates run on the identical sample set — never on the two candidates' aggregate scores treated as independent samples.

**When to use:** Always, for this project. Both candidates answer the same 200 (or 800, or N) queries; their per-session scores are correlated (easy sessions are easy for everyone, hard sessions are hard for everyone). Treating them as independent samples (e.g., an unpaired two-sample t-test on two lists of 200 scores) throws away that correlation, inflates the estimated variance, and *both* loses statistical power to detect real differences *and* can produce nonsensical results (e.g., "significant" aggregate differences driven by variance across sessions that has nothing to do with which candidate is better). This is exactly why TREC-style IR evaluation moved to paired randomization/bootstrap tests decades ago (Smucker et al.; Sakai). It is also why `sessions.jsonl` already carries `sample_id` — that field exists specifically so results can be joined and paired.

**Trade-offs:** None — there is no honest case for unpaired testing here. The only cost is remembering to join on `sample_id` before differencing, which requires both runs to be evaluated on the byte-identical dataset file.

**Example:**
```python
# stats.py — the shape every comparison takes
def paired_differences(
    baseline_sessions: list[dict],
    candidate_sessions: list[dict],
    score_fn,  # session dict -> per-session TechnicalScore-equivalent
) -> list[float]:
    baseline_by_id = {s["sample_id"]: s for s in baseline_sessions}
    candidate_by_id = {s["sample_id"]: s for s in candidate_sessions}
    assert baseline_by_id.keys() == candidate_by_id.keys(), "datasets must match exactly"
    return [
        score_fn(candidate_by_id[sid]) - score_fn(baseline_by_id[sid])
        for sid in sorted(baseline_by_id)
    ]
```

### Pattern 2: Champion-challenger tournament, not all-pairs comparison

**What:** With 3-5 candidates, structure comparisons as challenger-vs-current-champion, sequentially, rather than all `C(k,2)` pairwise comparisons.

**When to use:** Whenever the goal is "pick one winner" rather than "characterize the full ranking of all candidates" (this project's stated goal). All-pairs comparison among 5 candidates is 10 tests; a tournament against a fixed champion is at most 4. Fewer tests means a less severe multiple-comparison correction is needed for the same family-wise error rate, which means more power to detect a real 0.01-0.02 TechnicalScore difference at fixed n.

**Trade-offs:** A tournament can be order-sensitive if ties are broken by which challenger happens to be tested first. Fix this by always challenging with the currently-best measured TechnicalScore point estimate, updating the champion after each test.

### Pattern 3: Effect-size gate in addition to a p-value gate

**What:** A candidate is declared a winner only if it clears *both* a statistical-significance threshold and a minimum practically-meaningful effect size, and does not regress any individual scenario beyond a stated non-inferiority margin.

**When to use:** Always, here, because p-values alone are misleading at small-to-moderate n: with a large enough sample even a 0.002 TechnicalScore improvement becomes "significant," but 0.002 is smaller than a single session's contribution to HR@10 at n=200 and is not a decision-worthy improvement, especially given only 800 held-out sessions ever get run for real. See the concrete rule below.

## Data Flow

### Request Flow — one candidate through the arena

```
CandidateSpec (declarative)
    ↓ CandidateFactory.build_candidate(spec, artifact_path)
Agent-compatible object (reset/respond)
    ↓ (unmodified) evaluator.local_evaluator.evaluate(agent, samples, catalog_ids, categories, products)
dict: {hit_rate_at_10, mrr, mttc, efficiency, recommended_technical_score,
       scenario_metrics: {...}, sessions: [{sample_id, scenario_type, hit,
       first_hit_turn, best_rank, reciprocal_rank}, ...]}
    ↓ experiments.run_public.run_experiment() packaging (existing, reused)
experiments/<candidate>-<dataset>/{summary.json, sessions.jsonl, failures.jsonl,
                                    retrieval_routes.jsonl, ablation.md}
    ↓ arena.stats.paired_differences() joins this run's sessions.jsonl
      against the champion's sessions.jsonl on sample_id
    ↓ arena.stats.decide() applies the statistical decision rule (below)
StatisticalVerdict {p_value, ci_95, effect_size, per_scenario_deltas, verdict}
    ↓ arena.leaderboard.append_row()
experiments/arena/<arena-id>/leaderboard.json  (append-only, one row per cell)
```

### Key Data Flows

1. **Candidate isolation:** the only channel from a `CandidateSpec` to a measured score is through building a real `Agent`-compatible object and calling the unmodified `evaluate()`. There is no side channel — no candidate may read another candidate's outputs, ground truth, or trace data during its own run. This mirrors the existing `_SessionMappingAgent` discipline: ground truth never reaches the `Agent`, and the sample-id join happens only after `evaluate()` returns.
2. **Dataset provenance:** every dataset used in the arena (public / expanded / probe) is a checksummed, versioned file. The arena manifest hashes the dataset file *and* records the generator seed and generator code revision that produced it, so a leaderboard row is exactly reproducible: same candidate fingerprint + same dataset sha256 + same evaluator sha256 ⇒ byte-identical `summary.json` (excluding wall-clock and run id).
3. **Verdict flow is a pure function of two `sessions.jsonl` files**, decoupled from how those files were produced. This is what makes it possible to validate the statistics engine today, against retained historical rows in `experiments/RUNS.md`, before a second real candidate exists.

## Statistical Decision Rule for Declaring a Winner

This is the concrete answer to "how do we know a win is real," stated so it can be implemented directly in `arena/stats.py`.

**Test:** Paired **permutation (randomization) test** on the per-session `TechnicalScore`-equivalent difference, as the primary decision test, corroborated by a **paired bootstrap** (BCa, 10,000 resamples) for the confidence interval. These two are the IR-evaluation consensus choice (Smucker et al. 2007; Sakai's line of work on IR significance testing) precisely because they make no distributional assumption about per-session scores (which are bounded, skewed, and partly discrete — HR@10 is 0/1 per session) and because empirically they agree closely with the paired t-test on this kind of data, so there is no meaningful cost to preferring the assumption-free version.

Because the official metric (`TechnicalScore`) is only reported in aggregate by `evaluate()`, not per session, compute a per-session proxy directly from each session record so it can be paired and permuted:

```python
def session_technical_score(session: dict) -> float:
    hit = 1.0 if session["hit"] else 0.0
    mrr_term = session["reciprocal_rank"]
    turn = session["first_hit_turn"] if session["first_hit_turn"] is not None else 11
    efficiency = max(0.0, min(1.0, (11.0 - turn) / 10.0))
    return 0.50 * hit + 0.30 * mrr_term + 0.20 * efficiency
```
This reproduces `evaluate()`'s formula exactly at the session level (its aggregate `hit_rate_at_10`/`mrr`/`mttc` are the mean of exactly these components across sessions), so averaging this proxy over sessions reproduces `recommended_technical_score` — it is not an approximation, it is the same computation decomposed per session.

**Decision rule** (candidate `B` beats current champion `A`):

1. **Significance:** two-sided paired permutation test (10,000+ random sign-flips of the per-session differences) on `session_technical_score`, family-wise α = 0.05, corrected across the number of challengers tested against this champion in this arena round via **Holm-Bonferroni** (step-down, more powerful than plain Bonferroni for k ≤ 5 comparisons).
2. **Confidence interval:** the paired bootstrap 95% CI on the mean per-session difference must exclude zero, in the same direction as the point estimate.
3. **Practical significance floor:** the point estimate of the mean difference must be **≥ 0.01 TechnicalScore** — twice the stated single-session noise floor at n=200 (±0.005 HR@10 per session; since HR@10 alone carries weight 0.50, one session's worth of pure-HR@10 noise is ≈0.0025 TechnicalScore, so 0.01 is a 4x margin over that single-metric floor and a defensible, stateable line rather than "anything positive"). This floor exists because a statistically detectable but sub-floor difference is not a decision-worthy difference at this dataset size — see the sample-size analysis below for why.
4. **Non-inferiority per scenario:** for each of the four scenarios (buying / browsing / intent_override / boundary) reported separately by `evaluate()`, the challenger's scenario HR@10 must not be lower than the champion's by more than **0.02** (roughly one flipped session in the smallest scenario bucket — boundary is 5% of 200 ≈ 10 sessions, where one flip is already 0.10; the margin is intentionally scenario-count-aware, not a single global number — see note below). A challenger that wins in aggregate by improving buying/browsing while quietly regressing intent_override is rejected, echoing the project's own documented history where the largest real gain (intent_override 0.20 → 0.90) was invisible in aggregate.
5. **All four conditions must hold simultaneously.** Any one failing means "not yet a win" — report it as such (a candidate can be promising without being decided).

**Multiple comparisons:** apply Holm-Bonferroni to the *family* of challenger tests run in a given arena round (bounded by the champion-challenger tournament structure in Pattern 2, so the family size is at most `k − 1` for `k` candidates, not `C(k,2)`). Do not apply a correction separately per scenario within one challenger's test — the four scenario checks in step 4 are non-inferiority guards, not independent hypothesis tests competing for the same error budget.

**What sample size is needed to detect a 0.01 TechnicalScore difference?**

This must be answered honestly with the paired-test power formula, and the honest answer is uncomfortable. For a paired test, required sample size scales as:

```
n ≈ (z_(α/2) + z_β)² · σ_d² / δ²
```

with `δ = 0.01` (the target detectable difference), two-sided `α = 0.05` (`z_(α/2) = 1.96`), power 80% (`z_β = 0.84`), so `(z_(α/2)+z_β)² ≈ 7.85`.

The unknown is `σ_d²`, the variance of the *per-session paired difference*. Because HR@10 is the dominant, binary-valued component (weight 0.50), the dominant source of `σ_d` is how often the two candidates *disagree* on a session (one hits, the other misses) — this is the McNemar framing. If `p_disagree` is the fraction of sessions where the two candidates disagree on the binary hit/miss outcome:

| Assumed disagreement rate | Required n for 80% power, δ=0.01 TechnicalScore |
|---|---:|
| 5% of sessions (very similar candidates) | ≈ 3,900 |
| 10% of sessions (moderately similar, plausible near HR@10≈0.92) | ≈ 7,800 |
| 20% of sessions (substantially different candidates) | ≈ 15,700 |

*(Derivation: at the HR@10 term alone, `σ_d² ≈ p_disagree` per unit weight; scaling by the 0.50 metric weight and adding smaller contributions from MRR/efficiency differences on the same disagreeing sessions does not change the order of magnitude. These numbers are MEDIUM confidence — the formula and framing are standard [McNemar-style paired-proportion power analysis], the `p_disagree` input is an untested assumption pending real paired data from two actual candidates.)*

**The honest conclusion:** at 200 public sessions, and even at 800 held-out sessions, a true 0.01 TechnicalScore difference is very likely **undetectable at conventional power** unless the two candidates disagree on an unusually large fraction of sessions. This has three concrete consequences for the harness:

- Do not chase or report differences below ~0.01-0.02 as decided wins; report them explicitly as "inside the noise floor, more data or a bigger effect needed."
- The 800-session held-out set is the *only* run that counts as the real score, but it is a **single draw** — the arena's job is to decide *before* that draw is spent, using the expanded public-adjacent evaluation set (Section below) to get the effective n as high as budget allows, and to require a comfortably-larger-than-0.01 effect (the ≥0.01 floor above is a floor, not a target; prefer candidates that clear 0.02-0.03+ when possible, since those are detectable at n in the hundreds, not thousands).
- Report a **minimum detectable difference (MDD)** alongside every leaderboard row — Sakai's "Topic Set Size Design" framing — so a "no significant difference" result is legible as "we could not have detected anything smaller than X at this n," not silently read as "candidates are equivalent."

## Expanding the Evaluation Set Without Touching the Evaluator

`materialize_hidden_fields` in `evaluator/local_evaluator.py` (read directly, not paraphrased) is exactly two branches:

```python
def materialize_hidden_fields(sample, products):
    if "intent_card" in sample and "behavior" in sample:
        return sample["intent_card"], sample["behavior"]
    target = str(sample["ground_truth"]["parent_asin"])
    product = products[target]
    card = intent_card(product)          # scrapes title/features/details verbatim
    ...
    behavior = behavior_for(scenario, card, rng)
    return card, behavior
```

Both branches are legitimate, unmodified evaluator behavior. The arena's expanded dataset must **always take the first branch** — author `intent_card` and `behavior` explicitly on every generated sample — because the second branch is the one already shown (via the two zero-vocabulary-gap miss audits cited in `PROJECT.md`) to make the simulated customer quote the catalog's own text back at the retrieval system. That branch cannot measure vocabulary generalization; using it for new sessions would just produce more of the same easy, catalog-quoting sessions the public set already over-represents.

**Session construction pipeline (recommended):**

1. **Sample a target** `parent_asin` from the frozen 50,000-product catalog, stratified to match the stated scenario mix (40% buying / 40% browsing / 15% intent_override / 5% boundary) and, ideally, stratified further across category/price bands so the expanded set does not silently skew toward whichever categories are easiest to author cards for.
2. **Author `intent_card`** for that target: `target_category`, `hard_constraints`, `soft_preferences` — matching the schema `intent_card()` already produces, but written in customer language, not lifted from `features`/`details`. This is the step with the leakage hazard (next section).
3. **Author `behavior`** for the scenario type, matching `behavior_for()`'s schema exactly (`scenario_type`, and for `intent_override`: `turn`, `old_value`, `new_value`, `message`) — this is a pure data-shape requirement, not a hazard, since `behavior_for` itself is simple and already public.
4. **Validate solvability**: confirm the authored hard constraints are actually satisfiable by the target (spot-check or programmatic check against the product's real attributes) so the session is fair, not a session where even a perfect agent cannot win.
5. **Record generator provenance**: seed, generator code revision, and the sha256 of the resulting file — feeding the arena manifest.

**Avoiding leakage between the generator and the system under test.** The core hazard: if the same vocabulary resource that authors the intent card is also what the agent's `ConstraintExtractor` gazetteer was built from (the catalog's own attribute vocabulary, document-frequency-classified), an "independently generated" session can still trivially match, because both sides ultimately derive their vocabulary from the same 50,000-product catalog. This is not fully avoidable — there is only one catalog — but it is *mitigable*:

- **Never author a card by copying spans of the target's own `title`/`features`/`details`/`description` fields.** This is the literal, specific version of the general leakage hazard the question asks about: `intent_card(product)` in the evaluator does exactly this, and it is precisely why the public set cannot measure vocabulary generalization. A generated card must paraphrase — describe the same real attribute using different surface words — never quote.
- **Use an independent authoring path** for the paraphrase, ideally an LLM prompted with only the *coarse* category and attribute *type* (e.g., "this is a boot, material is leather, one soft preference is water resistance") rather than the raw catalog text, so the generation model is choosing words from its own general-language distribution, not echoing the catalog's phrasing back.
- **Measure, don't assume, independence**: compute token/n-gram overlap between each authored card and the target's `searchable_text` (the same fields the evaluator's own `searchable_text()` helper concatenates) programmatically, and treat high overlap as a generation defect to be re-authored, not a passing case.

**Validity limits of self-generated evaluation data — state these explicitly, not just once in a caveat paragraph:**

- **It measures agreement with the generator's model of customer language, not real customer behavior.** The 800-session held-out set is organizer-authored (presumably real human-crafted or human-reviewed customer language); a self-generated expanded set is a stand-in that lets iteration happen faster and with more statistical power, but a win on the generated set is evidence, not proof, of a win on the real held-out set.
- **Goodhart risk**: if the same generated set is used repeatedly across many candidate-tuning iterations, later candidates can overfit to whatever idiosyncratic phrasing patterns the generator (or the specific LLM/prompt used to build it) tends to produce, without that transferring to the real held-out set. Mitigate with a **three-way split discipline**, matching standard ML practice: the 200 public sessions and a *first* batch of generated sessions are the iteration/dev set (used freely, repeatedly, to guide changes); a *second*, separately-generated batch — ideally from a different prompt/seed/generation pass — is frozen and used only for the final champion-vs-challenger decision, never touched during iteration. This is the same discipline the paraphrase probe (next section) also needs, and for the same reason.
- **Solvability and fairness are the generator's responsibility, not the evaluator's.** The evaluator will happily run a session where the authored hard constraints do not actually match the target's real attributes; that produces a session no agent can win, which silently deflates every candidate's score identically (arguably harmless for *relative* comparison, but corrupts absolute-score reporting and wastes evaluation budget). Validate every generated sample before use.

## Paraphrase Probe Design

**Purpose, precisely stated:** measure whether a candidate degrades when the customer's words share no surface vocabulary with the catalog's own words, while everything else about the session — target product, scenario type, turn budget, structural difficulty — is held constant. This is the specific instrument needed because, per `PROJECT.md`'s own finding, the public set's fallback path structurally cannot produce this signal (it quotes the catalog).

**Design: matched control/probe pairs, not a standalone hard set.** For each probe target, construct *two* sessions, not one:
- **Control card**: constraints phrased close to the catalog's own vocabulary (similar to what `intent_card(product)` would produce) — same target, same scenario.
- **Probe card**: the same real attributes, same target, same scenario, but every hard constraint and soft preference rewritten with a synonym or paraphrase that shares **zero content-word overlap** (after stopword removal and normalization through the project's own `text_normalization.match_key`, so the check uses the same canonicalization the agent itself uses) with the target's `searchable_text`.

This paired construction is what answers the question's own validity concern — **"how to avoid a probe that is merely harder rather than differently distributed"** — directly: if a candidate's score drops from control to probe on the *same targets*, the drop is attributable to the lexical shift specifically, not to those targets being intrinsically harder, because the control condition already measures and absorbs the intrinsic difficulty of that particular target/scenario combination. A probe built without a matched control (just "here are 50 hard paraphrased sessions") cannot distinguish "this candidate has a vocabulary gap" from "this batch of targets happened to be hard for structural reasons" (ambiguous category, thin `details`, etc.).

**Validation that the probe measures what it claims:**
1. **Programmatic lexical-divergence check** (not eyeballing): for every probe card, compute the overlap between its normalized content tokens and the target's normalized `searchable_text` tokens; reject/rewrite any card with non-trivial overlap. Report the *achieved* divergence rate as a probe-quality metric in the arena manifest, so the probe's own validity is auditable, not asserted.
2. **Semantic-equivalence spot check**: a paraphrase is only a valid probe item if it describes the *same* real attribute. Since this project has no embedding model in its runtime stack, this check can be done with a lightweight synonym/WordNet-style lookup or, given the project's LLM access for judgment-heavy work, a small human/LLM-reviewed sample confirming the paraphrase and the original attribute mean the same thing. This is a one-time authoring-quality check, not a runtime dependency.
3. **Control-vs-probe delta on identical targets** is the metric that matters, not probe-alone accuracy. Report both: probe-alone HR@10 (context) and control-minus-probe HR@10 delta (the actual vocabulary-generalization signal).

**Prior art grounding:** this design is closest to a CheckList **invariance test (INV)** (Ribeiro et al., "Beyond Accuracy: Behavioral Testing of NLP Models with CheckList") — a perturbation that should *not* change the correct output (the target product is unchanged; only the wording changed) — as distinct from a **contrast set** (Gardner et al., "Evaluating NLP Models via Contrast Sets"), which deliberately perturbs an example so the *correct label changes*, testing decision-boundary sharpness rather than invariance. The probe here is explicitly an invariance test: a well-generalizing system should recover the same target regardless of which of the two phrasings was used, so the correct measurement is the *paired* control-vs-probe delta on matched targets, not probe accuracy as a standalone number.

## Experiment Tracking and Reproducibility — What the Arena Adds

The existing `run_public.py` five-file pattern (`summary.json`, `sessions.jsonl`, `failures.jsonl`, `retrieval_routes.jsonl`, `ablation.md`) plus the byte-diff determinism check already covers "is this one candidate's run reproducible." The arena adds the layer above that: "are these N candidates' runs *comparable*."

1. **Candidate fingerprinting**, alongside the existing `catalog_sha256`/`dataset_sha256`/`code_revision` fields already in `summary.json`: add `candidate_spec` (the full declarative knob set) and `candidate_fingerprint` (sha256 of its canonical JSON). Two runs with the same fingerprint, same dataset sha256, same evaluator sha256, and same code revision must produce byte-identical `summary.json` (modulo `elapsed_seconds`/run id) — exactly the existing determinism check, generalized from "rerun the same run_id" to "any two runs claiming the same fingerprint."
2. **Evaluator self-check baked into the manifest**: hash `evaluator/local_evaluator.py` itself (sha256) into every arena manifest. This turns "the evaluator was never modified" from a claimed invariant into a machine-checkable one — any accidental edit changes the hash and every subsequent leaderboard row visibly disagrees with prior rows' recorded evaluator hash.
3. **Per-arena manifest** (`experiments/arena/<arena-id>/manifest.json`): every candidate spec + fingerprint, every dataset name + sha256 + generator seed + generator code revision, the evaluator sha256, and the arena-level random seed (for any generator invoked during the arena itself).
4. **Append-only leaderboard**, not an overwritten summary: one JSON row per (candidate, dataset) cell, carrying the aggregate metrics, per-scenario metrics, and — critically — the `StatisticalVerdict` against whichever champion it was tested against (p-value, CI, effect size, per-scenario deltas, MDD at this n, final verdict string). This mirrors `experiments/RUNS.md`'s existing discipline of recording zero-gain and rejected results, not just wins, machine-readably.
5. **Cross-candidate session diffing**, extending the existing byte-diff-for-determinism idea from "this run vs. itself" to "champion vs. challenger": join `sessions.jsonl` on `sample_id` and emit only the rows where outcome differs (`hit`, `first_hit_turn`, or `scenario_type` — though scenario_type must never differ if the dataset matches). This is the concrete artifact that turns "candidate B has higher TechnicalScore" into "candidate B wins these 14 sessions and loses these 3, here's each one's trace" — the same trace-reading discipline `TESTING.md` already mandates for single-candidate regressions, generalized to comparisons.
6. **Seeded, recorded generation**: any new session generator must take an explicit seed (matching the existing pattern in `materialize_hidden_fields`'s fallback, which seeds `random.Random` from `f"{sample_id}\0{scenario_type}"`) and record that seed in the dataset registry — so "regenerate the expanded set" is reproducible, and so a specific generated session can always be traced back to exactly how it was produced.

## Anti-Patterns

### Anti-Pattern 1: Unpaired or aggregate-only comparison

**What people do:** compare candidate A's aggregate TechnicalScore to candidate B's aggregate TechnicalScore and declare a winner if A > B, or run a two-sample (unpaired) significance test on the two score lists.
**Why it's wrong:** discards the fact that both candidates answered the same queries, loses statistical power, and can produce a "significant" result driven by which sessions happen to be easy or hard rather than which candidate is genuinely better. See Pattern 1.
**Do this instead:** always join on `sample_id`, always test the paired per-session difference.

### Anti-Pattern 2: Chasing statistical significance with no effect-size floor

**What people do:** run the comparison on enough sessions that even a 0.001-0.003 difference becomes p < 0.05, and report it as a win.
**Why it's wrong:** at this project's scale (200 dev sessions, 800 held-out sessions, single-shot real score), a difference that small is smaller than the documented single-session noise floor and is not a decision a hackathon judge or a re-run would reproduce.
**Do this instead:** require both statistical significance *and* the ≥0.01 TechnicalScore practical-significance floor from the decision rule above.

### Anti-Pattern 3: Letting the evaluator's catalog-scrape fallback stand in for vocabulary-generalization evidence

**What people do:** expand the evaluation set by generating more `sample_id`s without `intent_card`/`behavior` fields, relying on `materialize_hidden_fields`'s fallback to auto-generate cards.
**Why it's wrong:** that fallback scrapes the target's own text, producing exactly the catalog-quoting sessions the public set is already saturated with — more of them adds sessions, not information about vocabulary generalization. This is the specific, already-diagnosed failure mode in `PROJECT.md`.
**Do this instead:** always author `intent_card` + `behavior` explicitly for new evaluation sessions, in paraphrased customer language.

### Anti-Pattern 4: A "hard" probe with no matched control

**What people do:** build a probe of deliberately paraphrased, harder-sounding sessions and report its standalone HR@10 as "generalization score."
**Why it's wrong:** cannot distinguish a vocabulary gap from the probe targets simply being intrinsically harder (thinner metadata, ambiguous category, etc.) — confounds the thing being measured with sampling variation in which targets got selected.
**Do this instead:** matched control/probe pairs on identical targets; report the control-minus-probe delta as the generalization signal, not probe-alone accuracy.

### Anti-Pattern 5: Iterating on the same generated set used for the final decision

**What people do:** generate one expanded evaluation set and use it both to guide many rounds of candidate tuning and as the basis for the final champion selection.
**Why it's wrong:** classic overfitting-to-the-dev-set — later candidates can be inadvertently selected for fitting the generator's idiosyncrasies rather than genuine improvement, and the final comparison is no longer an honest out-of-sample test.
**Do this instead:** freeze a separately-generated batch, untouched during iteration, for the final decision only — the same discipline applied to the paraphrase probe.

## Recommended Build Order

Dependencies are explicit; items at the same numbered level can proceed in parallel.

1. **Per-scenario MRR/MTTC + HR@1/3/5/10 curve extraction** from existing trace/session data (`experiments/analyze_public.py` extension). No new seams, no new candidates — pure analysis over data that already exists from every past run in `experiments/RUNS.md`. Prerequisite for any leaderboard row to be informative.
2. **`arena/stats.py`** — paired bootstrap, paired permutation, Holm-Bonferroni, the decision rule, and MDD reporting. Depends only on (1)'s per-session fields being complete; has **no dependency on new candidates existing** — build and validate it today against pairs of retained rows in `experiments/RUNS.md` (e.g., the FTS5-vs-fallback lexical-mode comparison already on record) before any new agent variant is written.
3. **`CandidateSpec` + `CandidateFactory` + fingerprinting.** Depends on nothing new beyond formalizing the constructor kwargs `run_public.py` already passes to `Agent` (`trace`, `exploration`, `lexical_mode`). Unlocks declaring and building more than one named candidate through the same `evaluate()` call.
4. **New seams for the actual candidate axes**, depends on (3) existing so a spec has somewhere to plug in:
   - `SemanticExpansionSource` Protocol, replacing the frozen `_EXPANSIONS` constant in `retrieval.py` — this is where the Tier-1 offline LLM-baked semantic asset becomes a swappable candidate.
   - `ConstraintExtractionBackend` Protocol + `FallbackConstraintExtractor` wrapper — this is where the Tier-2 runtime-LLM candidate plugs in, with its mandatory deterministic fallback enforced structurally, not by convention.
5. **Expanded evaluation-session generator** (`datasets/generator.py`), independent of (3)/(4) and can be built in parallel with them, but should be sequenced after (2) so the team knows what sample size it's aiming to produce (the sample-size analysis above should directly inform how many sessions the generator needs to produce, and in what batches, to hit a usable MDD).
6. **Paraphrase probe** (`datasets/probe.py`), depends on (5)'s catalog-sampling and schema-authoring machinery, plus the lexical-overlap validator described above. Sequenced after the generator because it reuses that machinery rather than duplicating it.
7. **Arena runner** (`run_arena.py`), the integration point — depends on (3) [multiple candidates to run], (5) and (6) [multiple datasets to run them on], and (2) [to turn raw results into a verdict]. This is genuinely the last item that can be built, since everything before it is independently useful and independently testable.
8. **Tracking/reproducibility hardening** (candidate fingerprint verification mode, evaluator-hash self-check, cross-candidate session diffing, append-only leaderboard rendering) — layered onto (7) once the arena runner produces real multi-candidate output to diff and track.

## Sources

- Smucker, Allan, Carterette, "A Comparison of Statistical Significance Tests for Information Retrieval Evaluation" (CIKM 2007) — https://dl.acm.org/doi/10.1145/1321440.1321528 — establishes paired randomization/bootstrap/t-test agreement and their preferability to Wilcoxon/sign tests for paired IR comparisons. MEDIUM-HIGH confidence (WebSearch summary of a well-known, widely-cited paper; not directly fetched).
- Sakai, "Evaluating Evaluation Metrics Based on the Bootstrap" (SIGIR 2006), and the related line of work "Statistical Reform in Information Retrieval?", "Statistical Significance, Power, and Sample Sizes: A Systematic Review of SIGIR and TOIS, 2006-2015" (2016), "Topic Set Size Design" (2016) — grounds the paired-bootstrap methodology and the minimum-detectable-difference framing used above. MEDIUM-HIGH confidence (WebSearch summary; titles and framing are consistent across multiple independent citing sources found).
- McNemar-style paired-proportions power analysis (Stata `power pairedproportions` documentation) — https://www.stata.com/manuals/pss-2powerpairedproportions.pdf — grounds the sample-size derivation for detecting small paired-proportion differences, applied here to the HR@10 component of TechnicalScore. HIGH confidence for the general method; MEDIUM for its numeric application here since the disagreement-rate input is an assumption, not measured data.
- Gardner et al., "Evaluating NLP Models via Contrast Sets" (2020) — https://aclanthology.org/2020.findings-emnlp.117/ — grounds the distinction between contrast sets (label-changing perturbations) and the invariance-style probe recommended here.
- Ribeiro et al., "Beyond Accuracy: Behavioral Testing of NLP Models with CheckList" — grounds the invariance-test (INV) framing used for the paraphrase probe's matched control/probe design.
- Direct reading, this session: `evaluator/local_evaluator.py` (full file, all 313 lines — `materialize_hidden_fields`, `intent_card`, `behavior_for`, `evaluate`, `metric_summary`), `experiments/run_public.py` (full file — the existing five-file run pattern, `_SessionMappingAgent`, determinism/publish discipline), `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/TESTING.md`. HIGH confidence — primary source, not summarized secondhand.

---
*Architecture research for: evaluation-harness and candidate-comparison design*
*Researched: 2026-08-29*
