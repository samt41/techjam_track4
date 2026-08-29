# Feature Research

**Domain:** Conversational shopping agent (retrieval-solved, ranking/turns open) + hackathon submission scored on a five-criterion rubric where the retrieval metric is 35% at most
**Researched:** 2026-08-29
**Confidence:** MEDIUM overall (HIGH on codebase-grounded gaps and rubric text; MEDIUM on academic CRS literature; LOW-MEDIUM on hackathon-judging behavioral claims, which are drawn from judge blog posts and organizer guides rather than controlled studies)

This file has two independent feature landscapes, because the milestone has two
customers: the automated `TechnicalScore` (part A) and human judges scoring the
other 65% of the rubric (part B). Every item below is mapped to the rubric
criterion or metric term it serves.

---

## Part A — Agent capabilities for rank-1 precision (MRR) and fast convergence (MTTC)

**Scope discipline.** This project already has session-level belief carryover
(`_SessionState` + `PreferenceLedger` with `intent_version`), multi-hypothesis
tracking (the full-population Bayesian posterior in `belief.py`), confidence-
weighted soft constraints (`constraint.confidence` as a per-contribution
weight), a partial profile-conditioned prior (`profile` contribution: term
overlap between the aggregate profile and candidate text), and
expected-posterior-entropy clarification. None of these are re-listed as
gaps. What follows is what is verifiably **not** built, read directly from
`belief.py`, `ranking.py`, `coordinator.py`, and `constraint_extractor.py`,
each tied to the specific metric term it would move.

### Table Stakes (must have — baseline competence a rank-1/turn-efficiency story requires)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Discriminative use of already-emitted negative signal | A CRS that ignores an explicit "none of these" turn is judged incomplete by the CRS literature (Lei et al., EAR/reflection-stage framing) and, mechanically, currently costs nothing here: `DialogueAct.SLATE_FEEDBACK` is already classified in `constraint_extractor.py:278` but is a dead end — no downstream consumer reads it. `already_shown` only reorders the slate (`ranking.py` sort key), it never touches the posterior. | LOW–MEDIUM | This is the single cheapest MRR lever available: the mechanism to detect the signal exists; only the belief-side consumption is missing. |
| Belief-score persistence across turns for previously-shown-and-declined items | Without this, an item that out-scored the true target on turn *N* keeps out-scoring it on turn *N+1* even after the customer implicitly rejected it, which is exactly the failure mode that keeps a target at rank 2–3 instead of rank 1. | LOW–MEDIUM | Requires storing per-`parent_asin` decline state in `_SessionState`, not just the shown-id set already stored for rotation. |
| Full-posterior commitment check before asking (not just before ranking) | Table stakes per the CRS survey literature and the CUP framework (arXiv 2604.03924): a system that always asks another question even when the posterior is already concentrated wastes turns it doesn't need to. | LOW | The population and entropy computation already exist (`PosteriorQuestionModel`, `strict_population`); only the ask/skip threshold logic (`ClarificationPolicy.choose`) needs a confidence-based short-circuit in addition to its current entropy-reduction comparison. |

### Differentiators (move MRR/MTTC beyond current numbers — competitive advantage on Technical Execution)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Negative-evidence belief update from slate rejection | Directly targets the documented gap: 184 of 200 hits sit below rank 1. A candidate shown and not chosen is *some* evidence against it, but the CRS literature (EAR reflection stage; NFCR) warns naive "rejected = negative" corrupts attribute-level learning, since rejection may mean "seen before" or "not now," not "wrong." **Recommendation:** treat rejection as a bounded, decaying demotion on the specific candidate only (never on the attributes it carries), applied strictly after the eligibility gate, and only when `DialogueAct.SLATE_FEEDBACK` fires with no accompanying constraint update — i.e. the customer said no to the *slate*, not to a *feature*. | MEDIUM | Ties to MRR, scenario-agnostic but highest-value in Browsing (40% of sessions, vague start → largest rank-1 ambiguity). |
| Confidence-based early commitment (skip a clarifying question when top-1 posterior mass is already dominant) | Directly targets MTTC. The CUP framework's commitment trigger (normalized entropy below a threshold **and** max belief probability above a threshold, or candidate set shrunk to ≤2) is a published, low-complexity pattern for exactly this trade. Every turn saved here is worth up to 0.1 Efficiency points per session at the margin. | LOW–MEDIUM | Must not regress HR@10 — gate the short-circuit behind the same strict-population computation already used for clarification, so it never fires on a false-confident but wrong top candidate; validate against the noise floor before shipping (per PROJECT.md's measurement-rig requirement). |
| Repeated-preference reinforcement (confidence boost on reaffirmed constraints) | A constraint stated once and then repeated or re-confirmed across turns is stronger evidence than one stated once — current `constraint.confidence` is set once at extraction time and does not accumulate. Small but free rank-discrimination gain in ties. | LOW | Only relevant in sessions with >3 turns; low frequency but zero risk since it only strengthens existing soft-constraint weighting, never introduces a new signal type. |
| Deeper profile-conditioned prior (beyond term overlap) | The aggregate `user_profile` (purchase-frequency, rating summary, preference tags) is currently only consumed as a lexical term-overlap bonus (`belief.py:171-182`). A profile-conditioned price-tier or category-affinity prior could break ties among evidence-sparse candidates — the case where recall is fine (target is in the population) but nothing distinguishes it from siblings. | MEDIUM | Speculative value — the profile is deliberately anonymized/thin per the competition's privacy boundary, so headroom here may be small. Spike before committing (per the project's own measurement-first discipline); do not ship on priors alone. |
| Soft price-proximity scoring within the hard boundary | Price is currently a pure hard cutoff (`ranking.py:266-273`, `<=`/`>=`/`==`); nothing distinguishes a candidate at the edge of a stated budget from one comfortably inside it. | LOW | Lower-confidence value: direction of preference (cheaper-is-better vs. mid-band-is-better) is not reliably inferable from a single boundary statement. Treat as a minor tie-breaker only, not a scored differentiator on its own. |

### Anti-Features (seem good for a "shopping agent," actively wrong for *this* task)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Slate diversification / MMR-style reranking of the top-*k* | Standard CRS/e-commerce wisdom: diversify results to avoid near-duplicates and improve engagement. | This task has exactly one hidden target per session and is scored on exact-match rank. Diversity that pushes a correct top-1 candidate down to accommodate variety directly and only hurts MRR — there is no engagement metric to trade against. | Optimize purely for posterior concentration on the true target; diversity has no scoring counterpart here. |
| Naive "rejected item = negative training sample" | Simplest possible reading of slate feedback; looks like the obvious fix for the gap identified above. | Documented in the CRS literature (EAR, NFCR) to corrupt attribute-level preference learning — rejecting an item because "I already own this" or "just browsing past it" is not the same signal as "wrong material." Applying it broadly (e.g., propagating the rejection to the item's attributes) risks demoting genuinely correct future candidates that happen to share a feature. | Scope negative evidence to the specific `parent_asin`, decaying, never propagated to attribute-level constraint weights. |
| Cross-session / persistent user modeling (bandit-style online learning across sessions) | Multi-armed-bandit CRS cold-start literature treats this as standard. | Public/private sessions are verified to have zero user overlap and zero target overlap by construction (organizer briefing). There is no second session for the same identity to learn across — this is pure wasted engineering effort. | All learning must be within-session; the existing per-session Bayesian posterior is already the right scope. |
| Runtime LLM re-ranking as the primary rank-1 mechanism | Semantic reranking is a named Innovation Direction in the spec and is the obvious "make it smarter" move. | Nondeterministic (even temperature-0 LLM inference is not reproducible in practice — verified against current literature), adds a network dependency the organizer may disable at scoring time, and costs tokens the project currently reports as zero. Runtime LLM use without a deterministic fallback risks scoring **zero**, not worse. | Tier 1 (build-time, offline, frozen asset) as already decided in PROJECT.md; a Tier 2 runtime candidate only if it ships with a deterministic fallback and is measured on both network-on/off paths. |
| Asking an extra clarifying question "to be safe" | More information feels like it can only help ranking. | Every additional turn directly costs Efficiency (`clip((11 - MTTC)/10, 0, 1)`) and, per the CRS survey and the CUP framework, users lose patience — real-world helpfulness norms argue against always-clarify. | Commitment trigger (see differentiator above): ask only when expected entropy reduction exceeds the turn-cost, not whenever ambiguity is nonzero. |

### Feature Dependencies

```
Negative-evidence belief update (slate rejection)
    └──requires──> Discriminative use of already-emitted negative signal (table stakes)
                       └──requires──> Belief-score persistence across turns (table stakes)

Confidence-based early commitment
    └──requires──> Full-posterior commitment check before asking (table stakes)
    └──shares state with──> PosteriorQuestionModel / ClarificationPolicy (existing)

Repeated-preference reinforcement ──enhances──> Negative-evidence belief update
    (both write into the same per-constraint confidence weight already
    consumed by belief.py:168; sequencing either first is safe)

Slate diversification (anti-feature) ──conflicts with──> Negative-evidence belief update
    (diversifying explicitly works against posterior concentration; do not
    combine these even experimentally)
```

### MVP Definition (Part A)

**Build first (highest points-per-effort, per PROJECT.md's own prioritization rule):**
- [ ] Discriminative slate-rejection consumption (table stakes) — the classification already exists; only the consumer is missing
- [ ] Confidence-based early commitment — cheapest MTTC lever, reuses existing entropy computation
- [ ] Negative-evidence belief update, scoped to specific `parent_asin`, decaying, never attribute-propagated — highest-value MRR differentiator, directly targets the "184 hits below rank 1" gap

**Add after validation (spike, measure against noise floor, keep only if it wins):**
- [ ] Repeated-preference confidence reinforcement
- [ ] Deeper profile-conditioned prior beyond term overlap

**Defer / only if evidence demands it:**
- [ ] Soft price-proximity scoring — low expected value, direction of preference not reliably inferable

---

## Part B — What makes a hackathon submission score well on this rubric

| Criterion | Weight |
|---|---:|
| Technical Execution | 35% |
| Innovation & Problem Insight | 20% |
| Impact & Relevance | 20% |
| Feasibility & Practicality | 15% |
| Presentation & Communication (final event only) | 10% |

**Grounding for this section.** General hackathon-judging advice (HackerEarth,
Devpost, MLH, Relativity, TAIKAI judge guides) converges on a few
non-metric-specific patterns; the strongest, most directly applicable
findings are cited per-item below. Confidence is MEDIUM: these are judge
blog posts and organizer guides, not controlled studies, but they are highly
consistent across independent sources, which raises confidence one level per
the verification protocol.

### Table Stakes (must-have submission mechanics — do not lose points to omission)

| Feature | Why Expected | Complexity | Rubric mapping |
<br>
| --- | --- | --- | --- |
| Public GitHub repo, meaningfully commented code | Judges explicitly dig into GitHub and penalize submissions that "look slick on the surface but are a lot lighter on code" underneath — the inverse (strong code, thin surface) reads well only if the code is legible. Current state: ~2.3% comment density across 4,717 lines. | LOW | Technical Execution (35%) |
| README with setup, reproduction, limitations, team contributions | Named as a required deliverable pattern across every judge guide surveyed and explicit in this competition's own Final Deliverables list. Absence reads as unfinished, regardless of underlying quality. | LOW | Technical Execution, Feasibility |
| Explicit disclosure of latency, token usage, network dependency, and fallback behavior | Required by `submission_rules.md`; also a costless way to bank Feasibility points, since "resource usage is proportionate" is literally the rubric wording and this project can state true zeros. | LOW | Feasibility & Practicality (15%) |
| Demo video ≤3 minutes, scripted before recording | Consistent, specific across Devpost and MLH guidance: most hackathons require demos under 3 minutes, and script-first is repeatedly cited as what separates confident from halting presentations. | LOW–MEDIUM | Presentation & Communication (10%) |
| One demonstrated multi-turn session artifact | Explicit organizer requirement (Final Deliverables) and currently the only unbuilt item in that list per the organizer-briefing gap audit. `Agent.turn_history()` already returns everything needed (dialogue act, extracted updates, intent version, question, slate) — this is packaging, not new engineering. | LOW | Technical Execution, Presentation |

### Differentiators (competitive advantage on the 65% that TechnicalScore does not reach)

| Feature | Value Proposition | Complexity | Rubric mapping |
|---|---|---|---|
| Lead with the public-set structural blind-spot finding as a first-class result, not a footnote | Judges distinguish problem insight from "clever engineering" by whether the team demonstrates *awareness of how others solve the same problem* and *why existing approaches fall short* — this project has a genuinely non-obvious, verified finding (the public set structurally cannot measure vocabulary generalization, because `materialize_hidden_fields` scrapes constraints verbatim from the target's own catalog text on the public path). This is exactly the kind of finding CRS papers publish as a methodology contribution. Concretely: open with "we found the benchmark measures less than it appears to" (the counterintuitive claim), then show the one-line code diff/branch (`intent_card`/`behavior` vs. `intent_card(product)`) that proves it, then show what changes when you control for it (the paraphrase probe). | LOW (the finding already exists; work is packaging + the paraphrase-probe measurement to back it) | Innovation & Problem Insight (20%) — directly answers "how do strong teams make a non-obvious finding legible": counterintuitive claim first, then the measurement that proves it, in that order. Generic advice to "tell a story" is not this; this is a specific claim-then-evidence structure. |
| Reframe zero-dependency/deterministic/auditable posture as a quantified Impact case, not a technical footnote | Judges explicitly flag backend-only submissions as at risk ("extremely back-end heavy... no UI") and recommend compensating with concrete reach/cost/sustainability claims rather than narrative. **Concrete, defensible claims this project can make:** (1) marginal cost per query is exactly $0 and does not degrade under load, unlike per-call LLM pricing, which is a real economic argument for reach at scale (e.g., "N million search sessions/month at zero incremental inference cost"); (2) no customer data leaves the host process — relevant to retailers under data-residency or privacy constraints where a third-party LLM API is a compliance blocker; (3) every ranked recommendation carries a typed, auditable log-odds breakdown, which is a concrete answer to "why was this shown" that most LLM-wrapper competitors cannot produce without separate instrumentation. **What this does NOT prove** (state honestly in the submission, since judges reward acknowledged limitations): it does not prove UX quality, does not prove it generalizes to real customer paraphrase the way an LLM would (the public-set blind spot cuts both ways — this project has *not yet measured* its own paraphrase robustness either), and does not prove market demand. Impact claims must be scoped to "cost, compliance, and auditability at scale," not "better shopping experience." | LOW–MEDIUM (framing + one slide/paragraph; the paraphrase probe from Part A's measurement rig is what makes the generalization caveat honest rather than defensive) | Impact & Relevance (20%) — turns a technical property into a reach/tangible-benefit/relevance argument, which is what the rubric explicitly asks for beyond "solving for the hackathon prompt alone." |
| Explicit "ground already held" framing for Feasibility | Rubric wording ("resource usage is proportionate... architecture holds under real-world conditions... grounded rather than speculative") maps almost one-to-one onto properties this project already has: zero deps, CPU-only, no credentials, byte-deterministic, 167 tests. Most competing submissions (likely LLM-API-wrapper agents) cannot make these claims at all. **Caveat that must be resolved before claiming this cleanly:** the 580 MB / 60-90s artifact build and the `Agent.__init__` hard failure on a missing artifact currently *undercut* "resource usage is proportionate" and "holds under real-world conditions" — these are exactly the submission-hardening items already tracked as Active in PROJECT.md. Do not claim Feasibility in the README/pitch until those are closed, or a judge who reads the repo finds a contradiction between the pitch and the code. | LOW (framing) + MEDIUM (the underlying hardening work, already scoped) | Feasibility & Practicality (15%) |
| Architecture diagram + live terminal call-and-response as the demo's visual core | Direct answer to "what does an effective demo video look like with no UI": the consistent, specific recommendation across judge/organizer guides is (a) never show bare code as the only visual, (b) generate an architecture diagram, (c) make it interactive/live rather than narrated — a live terminal session showing a real multi-turn conversation with the audit-trail scoring contributions printed alongside each recommendation is more concrete evidence of "transparent explanations" (a named Innovation Direction) than any narrated walkthrough. | LOW–MEDIUM | Presentation & Communication (10%), reinforces Innovation & Problem Insight (transparent explanations) |
| One-sentence, front-loaded counterintuitive claim in both the video and the Devpost text | Every source on presenting surprising findings to mixed technical/non-technical judges converges on the same structure: state the surprising insight in plain language first, then back it with one crisp quantifiable proof point, then connect to impact — in that order, not the reverse. For this project the natural sentence is: "This benchmark can look solved at 92% recall while still leaving 15 rubric points unclaimed, because the metric that's easy to move (recall) is nearly saturated and the ones with headroom (rank-1 precision, turns-to-convergence) were never the optimization target." | LOW | Innovation & Problem Insight, Presentation & Communication |

### Anti-Features (things that look like good hackathon strategy and are not, for this submission specifically)

| Feature | Why Requested | Why Problematic | Alternative |
|---|---|---|---|
| Building a UI to "look more like a real product" | Table-stakes instinct — most winning demos have a UI, and no-UI is flagged as a risk by judges. | Explicitly out of scope per the competition spec and PROJECT.md ("mandatory UI work" out of scope; backend track accepts a walkthrough video). Time spent here is time not spent on the 20+20+15 points that are currently near-unaddressed, and a bolted-on UI for a backend-scored track can read as scope confusion rather than polish. | Invest the same hours in the demo video's live terminal/audit-trail visualization and the Impact/Innovation framing instead. |
| Chasing HR@10 improvements as the headline technical story | It is the most familiar, most "impressive-sounding" number, and the existing `RUNS.md` is sorted by it. | PROJECT.md's own headroom decomposition shows only +0.040 points remain there, most of it documented as unrecoverable under-specification. Leading the pitch with a metric that is nearly saturated undercuts the "sharp problem understanding" the Innovation criterion rewards — it signals the team is optimizing what's easy to talk about, not what has headroom. | Lead the technical narrative with MRR/rank-1 and MTTC/turn-efficiency, which is where the real headroom and the real engineering (negative-evidence belief update, commitment trigger) lives. |
| Padding the Impact story with generic "helps online shoppers" language | Feels safe and is the default framing for any shopping-agent project. | Judges are specifically warned against hand-waved impact claims; a generic consumer-shopping-experience pitch is indistinguishable from every other team's and does not use this project's actual differentiators (cost, compliance, auditability). | Scope the impact claim narrowly and concretely to the properties this project can prove: zero marginal cost at scale, no data egress, auditable per-recommendation trail — a B2B/compliance framing, not a consumer-UX framing. |
| A long, narrated "here's our architecture" walkthrough as the whole video | Feels thorough and technically complete. | Judge guidance is consistent that unstructured technical narration without a single stable insight and without live/interactive proof is "tedious" — the exact failure mode the question asks about avoiding. Also risks exceeding the ~3 minute norm. | Structure per the differentiator above: counterintuitive claim → live proof → architecture at high level only → honest limitation → impact sentence. |

### Feature Dependencies (Part B)

```
Public-set blind-spot finding as headline Innovation claim
    └──requires──> Paraphrase probe (from Part A's measurement rig, already Active in PROJECT.md)
                       (without the probe, the claim is an assertion, not evidence)

Impact reframing (cost/compliance/auditability)
    └──requires──> Honest paraphrase-robustness caveat
                       (claiming generalization without measuring it contradicts the
                       project's own finding about the public set's blind spot)

Feasibility claim ("ground already held")
    └──requires──> Submission-hardening items already Active in PROJECT.md
                       (lazy artifact build, bounded memory, soft per-turn deadline)
                       (claiming Feasibility while Agent.__init__ still hard-fails on a
                       missing artifact is a claim the repo itself contradicts)

Demo video (live terminal + audit trail)
    └──requires──> One demonstrated multi-turn session artifact (table stakes, unbuilt)
    └──enhances──> Innovation & Problem Insight (transparent explanations)
```

### MVP Definition (Part B)

**Launch with (v1 — do these regardless of Part A engineering outcome):**
- [ ] Make the repository public — currently private, blocks every other deliverable
- [ ] Comment the code meaningfully (currently ~2.3% density) — Technical Execution is 35% and judges read the repo
- [ ] Write the README (overview, setup, reproduction, limitations, contributions) — required deliverable
- [ ] Build the one demonstrated multi-turn session artifact — required deliverable, cheapest to produce (`turn_history()` already returns everything needed)
- [ ] Script and record the demo video: counterintuitive claim → live proof → architecture (high level) → honest limitation → impact sentence, ≤3 minutes
- [ ] Write the Devpost description leading with the public-set blind-spot finding, not with HR@10

**Add after validation (v1.x — once Part A's measurement rig confirms candidates):**
- [ ] Fold the paraphrase-probe result into the Innovation narrative as the proof point
- [ ] Fold final MRR/MTTC deltas into the Technical Execution narrative

**Defer / do not build:**
- [ ] Any UI
- [ ] Any cross-session personalization or "product-market fit" framing that implies a user study that was never run

---

## Sources

**Part A (conversational recommendation / CRS literature — MEDIUM confidence, WebSearch-sourced academic surveys and papers, not independently re-verified against a primary benchmark, but internally consistent across multiple independent papers):**
- [Advances and Challenges in Conversational Recommender Systems: A Survey](https://arxiv.org/pdf/2101.09459) — naive rejected-item-as-negative-sample pitfall; attribute vs. item-level disentanglement
- [Estimation-Action-Reflection (EAR)](https://arxiv.org/pdf/2002.09102) — reflection-stage negative-sample refresh from slate rejection
- [Modeling User's Neutral Feedback in Conversational Recommendation (NFCR)](https://link.springer.com/chapter/10.1007/978-981-99-8070-3_5) — binary accept/reject is too limiting; neutral/attribute-level feedback
- [Rethinking Conversational Recommendations: Is Decision Tree All You Need?](https://arxiv.org/pdf/2208.14614) — structured rejection handling via interaction trees
- [Uncertainty as a Planning Signal (CUP framework)](https://arxiv.org/pdf/2604.03924) — explicit belief-state entropy commitment trigger (normalized entropy + max-probability threshold, or candidate-set-size floor)
- [Ask to Be Sure: Informative Interactions for Confident Multi-Turn LLM Recommendation](https://arxiv.org/html/2608.15949) — entropy-reduction reward for strategic elicitation
- MMR / accuracy-diversity tradeoff: [Elastic MMR primer](https://www.elastic.co/search-labs/blog/maximum-marginal-relevance-diversify-results), [Reconciling the accuracy-diversity trade-off](https://arxiv.org/pdf/2307.15142), [FairMatch](https://arxiv.org/pdf/2005.01148) — used to ground the diversity anti-feature finding

**Part A (codebase, HIGH confidence — read directly):**
- `starter/shopping_agent/belief.py` (constraint confidence weighting, profile term-overlap prior, quality prior)
- `starter/shopping_agent/ranking.py` (already-shown as sort key only, price as hard boundary only)
- `starter/shopping_agent/constraint_extractor.py` (`DialogueAct.SLATE_FEEDBACK` classified but unconsumed)
- `starter/shopping_agent/coordinator.py` (rejected-product trace is eligibility-gate diagnostics, not behavioral negative evidence)

**Part B (hackathon judging — MEDIUM confidence, consistent across independent judge/organizer sources):**
- [How to Win a Hackathon: 10 Tips From 500+ Events (HackerEarth)](https://www.hackerearth.com/blog/10-tips-win-hackathon)
- [How to Judge a Hackathon: 4 Criteria to Picking a Winner (Relativity)](https://www.relativity.com/blog/how-to-judge-a-hackathon-4-criteria-to-picking-a-winner/)
- [Hackathon judging: 6 criteria to pick winning projects (TAIKAI)](https://taikai.network/en/blog/hackathon-judging)
- [What Does a Good Hackathon Submission Look Like? (DEV Community)](https://dev.to/dorahacks/what-does-a-good-hackathon-submission-look-like-5398) — backend-heavy/no-UI risk, "show how things actually work"
- [How to win a hackathon: Advice from 5 seasoned judges (Devpost)](https://info.devpost.com/blog/hackathon-judging-tips) — separate demo polish from evidence/feasibility scoring
- [6 Tips for making a winning hackathon demo video (Devpost)](https://info.devpost.com/blog/6-tips-for-making-a-hackathon-demo-video) — ≤3 min, script first, architecture diagram even with no UI, interactive demo
- [Best Practices for Giving an API Demo at a Hackathon (MLH)](https://news.mlh.io/best-practices-for-giving-an-api-demo-at-a-hackathon-01-23-2023) — Twilio live-API-demo pattern for no-UI projects
- [How to Make a Presentation for a Hackathon (SlideModel)](https://slidemodel.com/hackathon-presentation/) — single stable insight, high-level architecture, evidence-first structure for surprising findings
- [How to present a successful hackathon demo (Devpost)](https://info.devpost.com/blog/how-to-present-a-successful-hackathon-demo)

**Part B (this competition, HIGH confidence — read directly from the repository's own participant-kit transcriptions):**
- `.planning/PROJECT.md` — rubric weights, headroom decomposition, Active/Out-of-Scope requirements
- `docs/competition_specification.md` — TechnicalScore scope statement, Innovation Directions, Final Deliverables
- `docs/submission_rules.md` — disclosure requirements, allowed/disallowed contents, model policy
- `docs/organizer_briefing.md` — deliverable gap audit (public repo, comments, demo session), named Innovation Directions already built vs. missing

---
*Feature research for: conversational shopping agent ranking/turn-efficiency work and hackathon rubric optimization*
*Researched: 2026-08-29*
