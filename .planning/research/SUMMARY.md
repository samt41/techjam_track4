# Project Research Summary

**Project:** TechJam Track 4 — Conversational Shopping Agent (hackathon submission)
**Domain:** Reranking/clarification tuning for an already-strong deterministic IR+dialogue system, wrapped in a rubric-scored hackathon submission problem
**Researched:** 2026-08-29
**Confidence:** MEDIUM-HIGH (statistical methodology and codebase-grounded findings are HIGH; magnitude of any specific technique's gain on this already-tuned system is unmeasured and MEDIUM-LOW until spiked)

## Executive Summary

This is not a "build a shopping agent" project — the agent is built, deterministic, and scores HR@10 0.920. It is a "spend a fixed 2+ week budget for maximum rubric score" project, and the four research streams converge on one governing fact: **the bake-off this milestone is built around cannot reliably detect the improvements it is meant to find, at the sample sizes actually available.** ARCHITECTURE.md shows detecting a real 0.01 TechnicalScore difference needs ~3,900–15,700 paired sessions depending on how often two candidates disagree; PITFALLS.md shows that simply comparing k=5–10 candidates and picking the best inflates the winner's apparent HR@10 by 0.022–0.030 through winner's-curse selection bias alone — a bias comparable in size to the entire remaining recall headroom (+0.040) and a meaningful fraction of the MRR headroom (+0.119 raw / 0.30 weighted). The correct response is not to abandon the bake-off but to change what a "win" is allowed to mean: build the statistical harness (paired permutation/bootstrap tests, Holm-Bonferroni, an explicit ≥0.01 TechnicalScore practical-significance floor, per-scenario non-inferiority checks that account for tiny bucket sizes) *before* running any comparison, and require any claimed improvement to survive an independent confirmation sample (an expanded/paraphrase dataset), not just win on the same 200 sessions it was tuned against.

The recommended technical approach, once the measurement problem is handled, is a short, ranked stack of stdlib-only, build-time-frozen techniques — a hand-rolled linear reranker over engineered features, tuned score-fusion weights replacing untuned RRF k=60, and consumption of the already-classified-but-unused `SLATE_FEEDBACK` signal plus a confidence-based commitment trigger for MTTC — chosen because they touch different pipeline stages, cost no runtime dependencies, and directly target the diagnosed problem (184/200 hits sit below rank-1, not missing from the candidate set). Every one of these changes must be judged jointly against HR@10, MRR, and MTTC together, using the derived exchange rate (HR@10 is 25× more sensitive per unit than MTTC and 1.67× more sensitive than MRR; a full extra average turn needs +0.0667 absolute MRR to break even) — never against one metric in isolation, since question-policy and ranking changes move all three at once.

The largest risk to the outcome, however, is not technical at all: Impact & Relevance and Innovation & Problem Insight are 40% of the rubric combined, are currently "near-unaddressed," and the metric work this milestone is scoped around can service at most 35% of the score (Technical Execution) — and, per the winner's-curse correction, probably delivers less than its face-value headroom suggests. PITFALLS.md's recommended hard checkpoint — stop score-improvement work once corrected marginal gain falls below ~0.005 TechnicalScore, and reallocate to deliverables/narrative — should be treated as a load-bearing phase gate, not a suggestion. The paraphrase probe, which is simultaneously this project's best evidence for the Innovation narrative (the public-set structural blind spot) and its only instrument for real vocabulary-generalization measurement, carries its own circularity risk (an LLM authoring "customer language" from catalog text tends to reproduce the catalog's own phrasing) that must be mitigated by construction — never shown the target's literal catalog text in-context, overlap-measured, frozen before iteration, and ideally cross-checked with a second model family — or it produces false confidence rather than evidence.

## Key Findings

### Recommended Stack

All Tier 1 recommendations are stdlib-safe at runtime: weights/coefficients are fit offline (dev-only `scikit-learn`/pure-Python gradient descent) and baked into `ranking.py` as frozen constants, exactly matching the existing `_ROUTE_WEIGHTS` pattern. Tier 2 (ONNX cross-encoder rerank, small embedding route) is real, disclosable dependency cost (~40-50MB installed) with genuinely uncertain payoff on a system this far past the raw-BM25 regime — CheckThat!-style benchmarks suggest a small (+2.8% MRR-class), not headline, gain — spike only, never default.

**Core technologies / techniques, ranked by (expected points × confidence) / effort:**

1. **`SLATE_FEEDBACK` consumption + negative-evidence belief update** (stdlib, zero dependency) — the classification already exists in `constraint_extractor.py`; only the belief-side consumer is missing. Directly targets the documented "184/200 hits below rank 1" gap. Highest-value, lowest-cost MRR lever available. Must be scoped to the specific `parent_asin`, decaying, never attribute-propagated (CRS literature warns naive "rejected = negative" corrupts attribute-level learning).
2. **Confidence-based early commitment trigger for MTTC** (stdlib) — reuses the existing entropy/posterior computation (`PosteriorQuestionModel`); adds a skip-the-question short-circuit when top-1 posterior mass already dominates. Cheapest MTTC lever; must be gated behind the strict-population computation so it never fires on a false-confident wrong candidate.
3. **Hand-rolled frozen linear/logistic reranker over fused candidates** (stdlib at runtime, dev-only fitting) — re-orders top ~20-50 candidates on ~5-8 engineered features (fused score, hit-count/diversity, exact-match flags, price-fit, `already_shown`). This *is* learning-to-rank done within the stdlib constraint.
4. **Tuned, normalized weighted fusion replacing untuned RRF k=60** — the project has already informally abandoned RRF's "no tuning needed" premise via `_ROUTE_WEIGHTS`; formalizing this with dev-set-tuned, per-route-normalized weights has measured precedent (~3.86% NDCG@10 gain in OpenSearch's benchmark).
5. **Offline LLM-generated synonym/concept table (Tier 1 semantic asset)** — reframed from a recall tool (its original gated spec) to an MRR tool: fewer false-positive `EXPANDED_FTS` hits competing for top rank. Requires the antonym/negation audit from PITFALLS.md before freezing (a generated pair that flips truth value on a negated attribute silently reproduces the two already-fixed bug classes, at a scale too large to manually review).
6. **SPLADE-distilled term-importance weights frozen into existing TF-IDF postings** — mechanically a close fit to the existing `lexical_postings` structure; nonstandard adaptation, MEDIUM confidence on magnitude.
7. **(Spike only) ONNX cross-encoder rerank** — real dependency, real latency cost (0.2–2s/turn plausible), uncertain gain against an already-strong baseline. Only pursue if Tier 1 stack's measured ceiling clearly falls short and the cost is explicitly disclosed in the Feasibility narrative.

### Expected Features

**Must have (table stakes — Part A, agent capability):**
- Discriminative use of `SLATE_FEEDBACK` (currently a dead-end classification)
- Belief-score persistence across turns for previously-declined items
- Full-posterior commitment check before asking (not just before ranking)

**Must have (table stakes — Part B, submission mechanics):**
- Public GitHub repo (currently private — blocks every other deliverable)
- Meaningfully commented code (currently ~2.3% density)
- README with setup/reproduction/limitations/contributions
- Explicit latency/token/network/fallback disclosure
- One demonstrated multi-turn session artifact (packaging only — `turn_history()` already returns everything needed)
- Demo video ≤3 minutes, scripted, opening with a live transcript before any architecture explanation

**Should have (differentiators):**
- Negative-evidence belief update (bounded, decaying, `parent_asin`-scoped only)
- Confidence-based early commitment (MTTC)
- Repeated-preference confidence reinforcement (low-risk, low-frequency gain)
- Lead the Devpost/video narrative with the public-set structural blind-spot finding, not HR@10
- Reframe zero-dependency/deterministic/auditable posture as a quantified Impact case (cost, compliance, auditability — not consumer UX)

**Defer / spike-only:**
- Deeper profile-conditioned prior (privacy-thin profile may have little headroom)
- Soft price-proximity scoring (low expected value)
- Any Tier 2 (ONNX) route — spike with disclosed cost, not default

**Anti-features (actively wrong for this task):**
- Slate diversification / MMR reranking — this task has one hidden target scored on exact match; diversity only hurts MRR
- Naive "rejected item = negative training sample" propagated to attribute weights
- Cross-session/bandit personalization — sessions are verified non-overlapping by construction
- Runtime LLM-as-primary-reranker without a deterministic fallback
- Building a UI — explicitly out of scope; time is better spent on Impact/Innovation framing
- Chasing HR@10 as the headline technical story — it is nearly saturated and signals the team is optimizing what's easy to talk about

### Architecture Approach

Build a second, orthogonal system — an **arena** in `experiments/arena/`, never importing from or editing `evaluator/` — that treats `evaluate()` as an opaque function called once per (candidate, dataset) pair. Every comparison is **paired** (joined on `sample_id`, never independent-sample), structured as a **champion-challenger tournament** (not all-pairs, to keep the multiple-comparisons correction cheap), and gated by **both** a statistical-significance test **and** a practical-effect-size floor plus per-scenario non-inferiority checks.

**Major components:**
1. `CandidateSpec` / `CandidateFactory` — declarative, hashable, fingerprinted candidate definitions; builds an `Agent`-compatible object per spec
2. Dataset registry (public / expanded / paraphrase-probe) — checksummed, seeded, provenance-recorded; expanded/probe sessions must always take the evaluator's `intent_card`+`behavior`-supplied branch, never the catalog-scraping fallback
3. `arena/stats.py` — paired bootstrap + permutation tests, Holm-Bonferroni correction, minimum-detectable-difference (MDD) reporting; has zero dependency on new candidates and should be built/validated first, against existing retained rows in `RUNS.md`
4. Arena runner + append-only leaderboard — orchestrates the candidate×dataset matrix, records verdicts (not just scores), and diffs sessions cross-candidate

### Critical Pitfalls

1. **Winner's-curse selection bias** — a k=5-10 candidate bake-off inflates the winner's apparent HR@10 by 0.022-0.030 through selection alone, comparable to the entire remaining recall headroom. Avoid by: using the correct σ≈0.019 (binomial SE at n=200, not the ±0.005 quantization figure), running paired/McNemar tests, reporting the order-statistic-corrected estimate, and requiring reproduction on an independent confirmation sample before shipping.
2. **Ranking-layer Goodhart** — the exact recall-layer mistake (tuning to the visible 200 sessions) recurring one level up in MRR tuning. Avoid by requiring every ranking change be justified by a catalog-derived/general property, never by "this moves session #47," and revalidating against the paraphrase probe.
3. **Cross-term trade-offs evaluated one metric at a time** — MRR/MTTC/HR@10 move together on any question-policy or ranking change. Avoid by measuring all three jointly and applying the breakeven rule (ΔMRR > 0.0667·ΔMTTC) before accepting any change that touches turn count.
4. **Paraphrase-probe circularity** — an LLM authoring "customer language" from catalog text reproduces the catalog's own phrasing (self-preference/regression-to-context bias), so a "passing" probe built this way is false confidence. Avoid by never showing the target's literal catalog text in the same prompt, measuring lexical overlap as a gate, freezing before iterating, and ideally cross-checking with a second model family.
5. **Solo-dev time misallocated toward noise-bounded metric gains** — Impact/Innovation (40% combined) are near-unaddressed while metric work services at most 35% and probably delivers less once winner's-curse-corrected. Avoid with an explicit stopping rule and a hard checkpoint at the score-improvement → submission-hardening transition.

## Implications for Roadmap

### Phase 1: Measurement Rig (must come first — everything else is unverifiable without it)
**Rationale:** ARCHITECTURE.md and PITFALLS.md both independently derive that no candidate comparison is trustworthy until this exists — it has zero dependency on new candidates and can/should be validated today against retained historical rows in `RUNS.md`.
**Delivers:** Per-scenario MRR/MTTC/HR@1,3,5,10 extraction from existing trace data; `arena/stats.py` (paired bootstrap, paired permutation, Holm-Bonferroni, MDD reporting, the ≥0.01 TechnicalScore practical floor + per-scenario non-inferiority gate); `CandidateSpec`/`CandidateFactory`/fingerprinting; expanded evaluation-session generator (always using the evaluator's authored-card branch); paraphrase probe with matched control/probe pairs, built with the anti-circularity discipline (no catalog text in-context, overlap-measured, frozen, cross-generator-checked).
**Addresses:** The measurement-rig requirements already listed as Active in PROJECT.md.
**Avoids:** Pitfalls 1 (winner's-curse), 2 (per-scenario noise floors), 5 (probe circularity).

### Phase 2: Score Improvement (ranked technique stack, gated by joint metrics)
**Rationale:** Only begin once Phase 1's harness exists, so every change can be measured on all three raw metrics jointly and checked against the winner's-curse-corrected floor and the MRR/MTTC breakeven rule before being "kept."
**Delivers, in ranked order:** (1) `SLATE_FEEDBACK` consumption / negative-evidence belief update, (2) confidence-based early commitment (MTTC), (3) frozen linear reranker, (4) tuned fusion weights, (5) offline semantic asset with antonym/negation audit, (6) SPLADE-distilled postings weights, (7) ONNX cross-encoder as an explicitly disclosed spike only if 1-6 fall short.
**Uses:** STACK.md's Tier 1 set (stdlib-safe); Tier 2 only as a measured, disclosed spike.
**Implements:** `SemanticExpansionSource` and `ConstraintExtractionBackend` protocols as swappable arena candidate seams.
**Avoids:** Pitfalls 3 (cross-term trade-offs), 4 (ranking-layer Goodhart), 6 (silent asset corruption).

### Phase 3: Hard Checkpoint — Go/No-Go on Continued Score Improvement
**Rationale:** PITFALLS.md's explicit recommendation: this is a required gate, not a soft transition. Given the rubric split (35% Technical Execution serviceable by this work, 40% Impact+Innovation currently unaddressed), and given that winner's-curse correction likely erodes a third to half of the naively-reported headroom, effort must be reallocated once marginal corrected gain drops below ~0.005 TechnicalScore.
**Delivers:** An explicit decision record — stop iterating on candidates, or continue — based on corrected marginal gain, not raw score.
**Recommendation to roadmapper:** budget score-improvement work at roughly 35% of remaining effort at most; the checkpoint should trigger well before that ceiling if gains are already sub-floor.

### Phase 4: Submission Hardening (Feasibility & Technical Execution)
**Rationale:** Independent of the bake-off outcome — these are correctness/robustness gaps that undercut Feasibility claims regardless of which candidate ships.
**Delivers:** Lazy/self-healing artifact build (currently hard-fails `Agent.__init__`), bounded memory across 800-session runs, soft per-turn deadline, and — critically — a network-fallback path verified against a realistic blackhole/DROP failure mode with explicit short timeouts, not just "the exception handler exists."
**Avoids:** Pitfall 6 (network fallback assumed, not verified) and the "looks done but isn't" artifact-build/memory traps.

### Phase 5: Deliverables & Rubric Positioning (40% of the score, currently unaddressed)
**Rationale:** This is not "cleanup after the real work" — it is 40% of the total score and must be treated as first-class engineering/writing work with its own budget, started early (video script, README) rather than deferred until "the code is done."
**Delivers:** Public repo, commented code, README, demo video (live transcript first, architecture second, per Pitfall 7), Devpost writeup leading with the public-set structural blind-spot finding (not HR@10), Impact framing scoped to cost/compliance/auditability (not generic "helps shoppers"), Feasibility framing that only claims what Phase 4 has actually fixed.
**Addresses:** FEATURES.md Part B in full; directly serves Impact & Innovation & Feasibility & Presentation (85% of non-Technical-Execution weight).
**Avoids:** Pitfalls 7 (invisible strengths reading as unfinished) and 8 (time misallocated away from the untouched 65%).

### Phase Ordering Rationale

- Measurement rig must precede score improvement because the harness is the only thing that makes any comparison in Phase 2 meaningful — this is not a preference, it's a hard dependency established independently by ARCHITECTURE.md and PITFALLS.md.
- The hard checkpoint (Phase 3) is inserted as a distinct phase, not a note, because PITFALLS.md explicitly warns this transition is where solo-dev time silently misallocates; making it a phase with a go/no-go artifact forces the decision to be made rather than drifted past.
- Submission hardening (Phase 4) can run in parallel with or independent of the score-improvement bake-off, since it addresses orthogonal correctness gaps (artifact build, memory, network fallback) — the roadmapper may interleave it with Phase 2 if solo-dev sequencing benefits from a break between measurement-heavy and writing-heavy work.
- Deliverables (Phase 5) should start earlier than a naive "do it last" reading suggests — video script and README drafting should begin as soon as Phase 1's probe/blind-spot finding exists, since it is the headline Innovation narrative, not after Phase 2/3/4 complete.

### Research Flags

Needs deeper research during planning:
- **Phase 2** (score improvement) — the SPLADE-distilled-postings adaptation and the antonym/negation audit design are nonstandard/MEDIUM-confidence; ONNX cross-encoder spike (if pursued) needs local CPU latency measurement not found in any source.
- **Phase 1's paraphrase probe** — cross-generator validation methodology (which second model family, how to structure the independent-authoring prompt) needs concrete design during planning, not just the principle stated here.

Standard patterns (skip research-phase):
- **Phase 1's stats engine** — paired bootstrap/permutation/Holm-Bonferroni is well-established IR methodology (Smucker, Sakai) with a concrete formula already derived above.
- **Phase 4** (submission hardening) — lazy artifact build, bounded memory, timeout handling are standard engineering patterns, not research-dependent.
- **Phase 5** (deliverables) — README/video/Devpost structure follows well-documented, consistent hackathon-judging conventions.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | Technique-level findings verified against multiple current sources; exact numeric transfer to this system's already-strong baseline is unverified until measured |
| Features | MEDIUM (HIGH on codebase gaps) | HIGH confidence on what's unconsumed in the codebase (read directly); MEDIUM on CRS literature transfer; LOW-MEDIUM on hackathon-judging behavioral claims (judge blogs, not controlled studies) |
| Architecture | HIGH on methodology, MEDIUM on numeric inputs | Statistical methodology and component design are HIGH confidence (established IR literature + direct code reading); the disagreement-rate parameter feeding the sample-size table is an untested assumption |
| Pitfalls | MEDIUM-HIGH | Statistical derivations are exact math on the project's own stated numbers; LLM-circularity and hackathon-judging claims are grounded in cited external sources but not project-specific measurements |

**Overall confidence:** MEDIUM-HIGH — the governing constraint (statistical power problem) is derived from exact math on the project's own numbers and is not in dispute; technique-level and judging-behavior claims carry the usual literature-transfer uncertainty and should be treated as hypotheses to spike, not guaranteed gains.

### Gaps to Address

- **Real disagreement rate between candidates (`p_disagree`)** — the sample-size table in ARCHITECTURE.md is only as good as this untested assumption; measure it empirically as soon as two real candidates exist, and update the arena's sample-size targets accordingly.
- **Actual magnitude of any Tier 1 technique's gain on this specific, already-tuned system** — every stack recommendation is directionally sound but numerically unverified until spiked; treat STACK.md's ranked list as a build order, not a guaranteed-points list.
- **How much of the reported +0.151 ranking/speed headroom survives winner's-curse correction** — PITFALLS.md estimates "a third to half may evaporate" but this is itself an estimate; the measurement rig should produce a corrected figure early so Phase 3's checkpoint has real numbers to gate on.
- **Which second model family to use for the paraphrase-probe cross-generator check** — needs a concrete decision during Phase 1 planning (Cloudflare Workers AI vs. Claude subagent vs. manual authoring for a subsample).

## Corrections to PROJECT.md

- **The "±0.005 HR@10" noise floor is a quantization artifact, not a statistical noise bound.** PROJECT.md's Active section states "at n=200 one session is ±0.005 HR@10" and treats this as the resolution below which candidates can't be compared. PITFALLS.md shows this is `1/200`, i.e. the smallest possible nonzero move — it answers "what's the smallest observable change?" not "how far could a candidate's public-set score plausibly diverge from its true population score by chance?" The correct figure for that second question is the **binomial standard error, σ ≈ 0.019** (`sqrt(0.92·0.08/200)`), roughly **4× larger** than the quantization figure. Source: PITFALLS.md, Pitfall 1, direct computation from PROJECT.md's own reported HR@10=0.920, n=200.
- **A bake-off of realistic size (k=5-10 candidates) can manufacture an apparent HR@10 gain of 0.022-0.030 through winner's-curse selection bias alone**, with no real underlying improvement — a figure not previously quantified anywhere in PROJECT.md, and large enough to be mistaken for genuine progress against the stated +0.040 recall headroom or the 0.30-weighted MRR headroom. Source: PITFALLS.md, Pitfall 1, order-statistic bias table.
- **Detecting a true 0.01 TechnicalScore difference between two candidates requires roughly 3,900-15,700 paired sessions**, far beyond both the 200 public sessions and the 800 private held-out sessions PROJECT.md treats as sufficient for a "statistically honest" comparison. PROJECT.md's Active item "candidate comparison is statistically honest — a win must exceed the noise floor" should be read as achievable only for effect sizes well above 0.01 (PITFALLS.md recommends treating 0.02-0.03+ as the realistic detectable-and-decision-worthy range), not as a general guarantee at any effect size. Source: ARCHITECTURE.md, paired-test power derivation.
- **The "must not regress any scenario" gate (PROJECT.md, Active) is not statistically meaningful for the Boundary (n=10) and Intent Override (n=30) buckets** — their binomial standard errors (≈0.086 and ≈0.050 respectively) mean a single flipped session moves the bucket's HR@10 by 10 and 3.3 percentage points respectively. This gate should be stated with its bucket-size caveat, not treated as a uniform rigorous check across all four scenarios. Source: PITFALLS.md, Pitfall 1, per-scenario SE table.

## Sources

### Primary (HIGH confidence)
- Direct reading of `evaluator/local_evaluator.py`, `experiments/run_public.py`, `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/TESTING.md`, `starter/shopping_agent/{belief,ranking,constraint_extractor,coordinator}.py`
- Order statistics of the standard normal maximum (classical extreme-value tables) and binomial standard error applied directly to this project's own reported metrics

### Secondary (MEDIUM confidence)
- Smucker, Allan, Carterette, "A Comparison of Statistical Significance Tests for Information Retrieval Evaluation" (CIKM 2007)
- Sakai's line of work on IR significance testing and Topic Set Size Design
- Bruch et al. 2022 and OpenSearch's fusion benchmark (~3.86% NDCG@10 tuned-fusion-vs-RRF delta)
- Rahmani et al. (EACL 2024), Chen et al. "Learning to Clarify" (2024), CUP framework — clarifying-question value beyond entropy
- CRS literature on negative-evidence handling: EAR (arXiv 2002.09102), NFCR, CRS survey (arXiv 2101.09459)
- Self-preference bias in LLM-as-judge/generator: Xu et al. 2024 (arXiv:2410.21819), Panickssery et al., Wataoka et al.
- Hackathon judging guides: HackerEarth, Devpost, MLH, Relativity, TAIKAI

### Tertiary (LOW-MEDIUM confidence, needs validation)
- SPLADE-into-legacy-TF-IDF adaptation — mechanism sound, integration nonstandard, not benchmarked as described
- ONNX cross-encoder CPU latency on this specific workload — no authoritative CPU-specific benchmark found, community-reported only
- `p_disagree` assumption feeding the sample-size table — untested pending real paired candidate data

---
*Research completed: 2026-08-29*
*Ready for roadmap: yes*
