# Pitfalls Research

**Domain:** Competition IR/dialogue system — small public dev set (200 sessions), large held-out private set (800 sessions), composite weighted metric, solo hackathon submission
**Researched:** 2026-08-29
**Confidence:** MEDIUM-HIGH (statistical derivations are exact math; hackathon-judging and LLM-circularity claims are grounded in cited external sources; project-specific numbers are computed directly from `.planning/PROJECT.md`'s own stated weights and constants)

This document intentionally does not restate `.planning/codebase/CONCERNS.md`. Every
pitfall below is a mistake that is **still available to be made** in the current
milestone (measurement rig → score improvement → submission hardening →
deliverables), not one already made, logged, and fixed.

---

## Critical Pitfalls

### Pitfall 1: Winner's-curse selection bias in the candidate bake-off

**What goes wrong:**
The milestone plan is explicitly a multi-candidate bake-off (ranking tweaks,
Tier-1 semantic asset on/off, Tier-2 runtime LLM with/without fallback,
question-selection variants). Whichever candidate posts the best public HR@10
gets treated as "the win." With `k` candidates and no correction, the observed
best score is a biased-upward estimate of that candidate's true quality — even
if all `k` candidates are, in truth, identical. This is the same failure mode
as picking the best of many p-hacked hypotheses: the selection step itself
manufactures an apparent improvement that decays or vanishes on the private
800-session set.

**Why it happens:**
Selecting the max of several noisy measurements is not the same operation as
measuring one thing once. `E[max(X_1..X_k)] > E[X_i]` for any single `i`,
strictly, whenever the `X_i` carry independent noise — and the gap grows with
`k`. Teams intuitively treat "we tried five things and picked the best" as
free information gathering; it is not free, it has a quantifiable statistical
cost.

**Quantified for this project (n=200, per PROJECT.md's own framing):**

If per-candidate measurement noise is approximately Gaussian with SD σ, the
expected upward bias of the best-of-`k` selection is `σ · E[max of k iid
N(0,1)]`, using the standard order-statistic constants:

| k | E[max of k std. normals] |
|---:|---:|
| 2 | 0.564 |
| 3 | 0.846 |
| 5 | 1.163 |
| 10 | 1.539 |
| 15 | 1.737 |
| 20 | 1.868 |

Two candidate values of σ matter here, and the project currently conflates them:

- **σ ≈ 0.005** — the value PROJECT.md quotes ("one session is ±0.005
  HR@10"). This is actually a **quantization** argument (1/200 = 0.005), not
  a statistical noise argument. It answers "what is the smallest possible
  nonzero move?", not "how much could this move by chance?"
- **σ ≈ 0.019** — the actual binomial standard error at p≈0.92, n=200:
  `sqrt(0.92·0.08/200) ≈ 0.0192`. This is the correct order of magnitude for
  "how far could a candidate's public-set score plausibly diverge from its
  true population score."

Using the *correct* σ (0.019), the winner's-curse bias for a realistic
bake-off size is:

| k (candidates compared) | Expected upward bias in reported HR@10 |
|---:|---:|
| 3 | +0.016 |
| 5 | +0.022 |
| 10 | +0.030 |
| 20 | +0.036 |

Compare this to PROJECT.md's own headroom table: **all remaining recall
headroom is +0.040.** A bake-off of even 5-10 loosely-related candidate
configurations can produce an apparent HR@10 gain that is *almost entirely*
winner's-curse artifact — of the same order of magnitude as the entire
remaining recall budget. This risk is highest for ranking micro-tuning
(weight thresholds, tie-break rules), where candidates are minor variants of
each other and the "signal" being selected for is frequently just which
variant happens to fit the public set's 200 idiosyncratic sessions best.

**Compounding problem — per-scenario gates don't fix this, and can't at this n:**
PROJECT.md's active item "must not regress any scenario" is a reasonable
partial defense, but the four scenario buckets are small: 40/40/15/5% of 200
sessions = 80 / 80 / 30 / 10 sessions. Binomial SE at p≈0.92 per bucket:

| Scenario | n | SE(HR@10) | 1-session swing |
|---|---:|---:|---:|
| Buying | 80 | 0.030 | 0.0125 |
| Browsing | 80 | 0.030 | 0.0125 |
| Intent Override | 30 | 0.050 | 0.033 |
| Boundary | 10 | **0.086** | **0.10** |

The Boundary bucket has only 10 sessions: flipping a single session moves its
HR@10 by 10 percentage points. A "no regression on any scenario" gate is
**not statistically meaningful for Boundary, and weak for Intent Override** —
a candidate can pass the gate purely on luck in exactly the buckets least
able to detect a real regression.

**How to avoid:**
1. Stop citing "±0.005" as the noise floor for candidate comparisons; it is a
   quantization floor, not a confidence bound. Use the binomial/McNemar
   framing above for any go/no-go decision.
2. For any two candidates run on the *same* 200 sessions, use a **paired**
   test (McNemar's test on discordant sessions — only sessions where the two
   candidates' hit/miss outcome differs carry information) rather than
   treating the two HR@10 values as independent. This is usually a tighter,
   more honest bound than the independent-sample SE above, but it requires
   session-level outcome logs for both candidates, not just the aggregate
   number.
3. Report the bake-off winner's score **minus** the order-statistic bias
   for the actual `k` compared, and require the corrected estimate to still
   show a positive, useful gain before shipping.
4. Use sample splitting for the final decision: pick the leading candidate(s)
   on the public 200, then require the gain to reproduce on an independent
   sample — the paraphrase-probe sessions (once built) or a second batch if
   the organizer's evaluator is re-run against expanded dev sessions. A gain
   that only exists on the selection sample and not the confirmation sample
   is winner's curse, not a real improvement.
5. Do not treat the Boundary (n=10) or Intent Override (n=30) per-scenario
   deltas as decision-grade evidence in isolation; report them as
   directional only, and gate primarily on Buying/Browsing (n=80 each) plus
   the aggregate corrected estimate.

**Warning signs:**
- A "winning" candidate whose margin over baseline is smaller than ~0.02-0.03
  HR@10 (below the k=5..10 bias table above) is likely noise, not signal.
- A candidate that wins on the aggregate but only because it wins big on
  Boundary or Intent Override (small-n buckets) and is flat/negative
  elsewhere.
- Any bake-off writeup that reports only the winner's score and not the
  distribution of all `k` candidates' scores — this hides the selection
  step and makes the bias invisible to a reader (including a judge).

**Phase to address:** Measurement rig (build the paired/discordant-session
comparison tooling and the corrected-estimate reporting *before* running the
score-improvement bake-off — not after).

---

### Pitfall 2: Goodhart at the ranking layer — the recall mistake recurring one level up

**What goes wrong:**
The project already lived through this exact failure mode with HR@10: tracked
it past the point of usefulness, tuned phrase matchers to the public
simulator's literal wording, and only caught it via miss-audit and headroom
decomposition. The active work item "Rank-1 precision work (MRR): discriminate
among already-retrieved candidates" is the natural place for the identical
mistake to recur — this time by hand-tuning tie-break rules, RRF weights, or
belief-component thresholds specifically to move the 16 known public misses
and the specific below-rank-1 hits in the 200-session set into higher ranks,
without a catalog-derived or otherwise generalizable principle behind the
change.

**Why it happens:**
With a fixed, small, visible dev set, it is always possible to add just
enough rule surface to fit the visible cases. Because MRR contribution per
session is drawn from only 10 discrete values (1, 1/2, 1/3, ..., 1/10, 0), a
handful of targeted nudges can move several sessions from e.g. rank 3 to rank
1 and produce a visible-looking MRR jump on the public set that is pure
memorization of which 200 targets exist, not an improvement in ranking logic.

**How to avoid:**
- Every ranking change should be justified by a catalog-derived or
  structurally general property (as the project's stated policy already
  requires for extraction), not by "this moves session #47's rank from 4 to
  1." If the change cannot be stated without reference to specific public
  session IDs, it is very likely overfitting.
- Before accepting an MRR-improving change, check whether it also improves
  (or is neutral on) the not-yet-seen paraphrase-probe sessions once they
  exist. A change that only helps on public-simulator-quoted-catalog-text
  sessions and not on authored-paraphrase sessions is the ranking-layer
  version of the already-diagnosed recall-layer mistake.
- Track a "rule surface size" metric (number of new thresholds, tie-breaks,
  or special cases added) alongside MRR delta. A large rule-surface cost for
  a small, public-set-only MRR gain is a red flag.

**Warning signs:**
- New special-case code that only fires on <5 sessions in the public set.
- MRR gains that do not show up (or regress) on the paraphrase probe.
- A ranking change justified purely by "this is one of the 16 audited
  misses" rather than by a property of the belief/ranking model.

**Phase to address:** Score improvement (ranking work) — gate every MRR
change behind the same "catalog-derived, not public-set-derived" rule the
project already applies to extraction, and re-validate against the
paraphrase probe once it exists, not just the original 200.

---

### Pitfall 3: MRR / MTTC / HR@10 cross-term trade-offs made one term at a time

**What goes wrong:**
Because the milestone treats MRR and Efficiency as the terms with headroom,
there is a real risk of optimizing MRR or MTTC in isolation and only noticing
a cross-term regression after the fact — particularly because HR@10 carries
by far the largest weight (0.50) and any change to question-asking or
turn-taking logic touches all three terms simultaneously.

**Why it happens:**
Efficiency and MRR are not independent: asking one more clarifying question
typically improves rank precision (a supersede/retract event or a resolved
ambiguity should push the target higher, helping MRR) but costs a turn,
directly hurting Efficiency, and every additional turn is also an
opportunity for a mis-extracted constraint to be added — a real hazard to
HR@10 itself.

**Quantified exchange rates (from PROJECT.md's own scoring formula):**

```
TechnicalScore = 0.50·HR@10 + 0.30·MRR + 0.20·Efficiency
Efficiency = clip((11 - MTTC)/10, 0, 1)
```

Marginal contribution to TechnicalScore per unit of each raw metric (in the
unclipped, currently-operative region — MTTC=3.425 is far from both the 1
and 11 clip boundaries):

| Raw metric | d(TechnicalScore) per full unit | d(TechnicalScore) per 0.01 (1 pt) |
|---|---:|---:|
| HR@10 | 0.50 | 0.0050 |
| MRR | 0.30 | 0.0030 |
| MTTC (per turn saved) | +0.02 (since dEfficiency/dMTTC = −0.1) | — |

**Breakeven rule for "ask one more clarifying question":** if a question
change adds `ΔMTTC` average turns and changes MRR by `ΔMRR`, it is net
positive for TechnicalScore only if:

```
0.30 · ΔMRR  >  0.02 · ΔMTTC
ΔMRR  >  0.0667 · ΔMTTC
```

Concretely: adding a full extra average turn (`ΔMTTC = +1`) needs `ΔMRR ≥
+0.0667` (absolute) to break even — i.e. moving raw MRR from 0.5245 to
≈0.591, a ~12.7% relative jump, just to pay for one more turn on average.
That is a high bar; most single clarifying-question tweaks will not clear it
unless they fix a genuinely common ambiguity.

**Cross-check against HR@10:** a 1-percentage-point HR@10 regression costs
0.0050 TechnicalScore — equivalent to needing +1.67 points of raw MRR, or
+0.25 turns of MTTC improvement, just to break even. HR@10 is **25× more
sensitive per unit than MTTC** and **1.67× more sensitive than MRR**. Any
change motivated by MTTC or MRR that has *any* plausible path to reducing
recall (e.g., asking fewer questions to save turns, or cutting a
disambiguation path to simplify ranking) needs disproportionately strong
evidence that HR@10 is unaffected before it ships.

**How to avoid:**
- Measure all three terms together for every question-logic or ranking
  change, never one term "now" and the others "later." The measurement rig
  work item (per-scenario MRR/MTTC recovery from trace data) is a
  prerequisite for this, not a nice-to-have — until it exists, ΔMRR and
  ΔMTTC for a candidate change cannot even be computed.
- Apply the breakeven formula above as an explicit go/no-go gate before
  accepting any change that touches turn count.
- Treat any HR@10 regression, however small, as disqualifying unless the
  MRR/Efficiency gain clears the 25×/1.67× exchange rate with margin — small
  HR@10 regressions are the most expensive currency in this metric.

**Warning signs:**
- A change is evaluated and reported using only the metric it targeted (e.g.
  "MTTC improved from 3.4 to 3.1" without also reporting MRR and HR@10 on
  the same run).
- Clarification-question changes tested only against the current 16 known
  misses rather than the full 200-session run plus paraphrase probe.

**Phase to address:** Score improvement — build joint HR@10/MRR/MTTC
reporting per candidate (part of the measurement rig) before starting
ranking or clarification-question changes.

---

### Pitfall 4: The paraphrase probe measures the generator, not the system

**What goes wrong:**
The planned paraphrase probe (authored `intent_card` + `behavior` in
"customer language") is the project's only planned instrument for the
vocabulary-generalization question that the public simulator structurally
cannot answer (per PROJECT.md's correction to CONCERNS.md — the public
customer literally quotes the target's own catalog fields). But if the same
LLM family used to build the Tier-1 semantic asset also authors the probe
sessions, the probe risks measuring **self-consistency between two outputs
of the same model**, not generalization to real customer vocabulary. A
probe that "passes" under these conditions provides false confidence,
because both the system's semantic coverage and the probe's test cases were
drawn from the same generative distribution.

**Why it happens:**
This is a documented, general phenomenon in LLM-as-judge / LLM-as-generator
settings: **self-preference bias** — LLM evaluators (and, by direct
extension, LLM-authored test cases) systematically favor content that shares
the generating model's own style, vocabulary, and low-perplexity phrasing,
even when an independent human judge would not (Xu et al. 2024,
arXiv:2410.21819; Panickssery et al. on self-recognition driving the effect;
Wataoka et al. on perplexity as the underlying mechanism). The mechanism
generalizes beyond judging: an LLM asked to "write how a customer would
phrase this" tends to stay closer to the source material it was shown
(regression to the given context) than a genuine naive shopper would,
especially if the prompt includes the catalog fields in the same turn. That
reproduces, in miniature, the exact defect already found in the public
simulator's `intent_card`/`customer_reply` path.

**How to avoid:**
1. **Never show the LLM the target's exact catalog field text in the same
   prompt used to generate "customer language."** Provide only a semantic
   gist (attribute + value pairs abstracted from exact strings), or generate
   from a separate model turn that has forgotten the literal source text.
2. **Quantify overlap, don't assume it.** Compute a lexical/n-gram overlap
   ratio between each authored probe message and the target's raw catalog
   fields. If the median overlap resembles the public simulator's
   near-verbatim baseline, the probe has reproduced the defect it exists to
   test, and is not a valid instrument.
3. **Cross-generator check.** Author a second, smaller probe batch with a
   different model family (e.g., the open-source Cloudflare Workers AI
   model vs. the Claude subagent), or manually. If HR@10/MRR on
   probe-family-A is materially better than on probe-family-B, that gap is
   evidence of generator-affinity bias, not evidence the system generalizes.
4. **Freeze the probe before iterating on the system.** Write the probe
   set once, commit it, and do not revise probe wording after seeing which
   cases the system fails — that turns the probe into a second bake-off
   target and reintroduces Pitfall 1's selection bias, just with an even
   smaller n.
5. **Size it honestly.** A probe of n≈20-30 authored sessions has a binomial
   SE around 0.09-0.10 at p≈0.5-0.9 — comparable to or worse than the
   Boundary-scenario problem in Pitfall 1. A "probe passed" narrative built
   on that few sessions should be reported with its confidence interval,
   not as a settled finding, in any demo or writeup.

**Warning signs:**
- Probe messages that read like lightly reworded catalog copy ("a durable,
  water-resistant hiking boot in size 10" when the catalog says "waterproof
  hiking boot, size: 10").
- The probe is authored in the same conversation/session as the Tier-1
  synonym-asset generation, sharing context.
- Probe results reported as a binary "generalizes / doesn't generalize"
  claim without a sample size or confidence interval.

**Phase to address:** Measurement rig (build and freeze the probe with the
overlap-ratio check as an automated gate) — before it is used to justify any
Tier-1/Tier-2 decision in the score-improvement phase.

---

### Pitfall 5: LLM-generated Tier-1 asset silently corrupts a ranking or negation signal

**What goes wrong:**
The project already has two precedents for exactly this class of bug fixed
in the existing engine (retrieve-then-reject on canonicalized material;
colon-spacing splitting concepts across 705 products) — both were *silent*
mismatches between two representations of the same underlying fact. The
planned Tier-1 offline LLM pass (build once, freeze as a static asset,
replacing the six-entry `_EXPANSIONS` table) is a new, high-volume
opportunity for the same bug class: an LLM asked to produce catalog-derived
synonym/expansion pairs at scale can plausibly emit a pair that is actually
a near-antonym or a size/fit-inverting relation (e.g. linking a term to its
opposite along some attribute the LLM treated as "similar"), which would
silently break scoped negation or eligibility gating exactly the way the
two fixed bugs did — except at a scale (hundreds or thousands of generated
pairs) that makes manual review of every entry impractical.

**Why it happens:**
LLMs generating structured mappings at volume optimize for plausible-looking
local relationships (co-occurrence, thematic similarity) rather than for the
logical property the system actually needs preserved (that expansion never
flips truth value on a negated or mutually-exclusive attribute). Nothing in
a generation prompt like "list synonyms/related terms for catalog attribute
values" inherently prevents antonym-adjacent output ("wide" → "narrow" as a
"related fit term"), and this is exactly the kind of item a human reviewer
skimming a long generated list is likely to pass over.

**How to avoid:**
- **Automated antonym/negation audit before freezing.** For every generated
  `(source, expansion)` pair, check it against: (a) a small curated
  antonym/negation seed list for known attribute dimensions (size, fit,
  material treatment, gender, color-opposite pairs, etc.), and (b) a
  co-occurrence sanity check against the catalog itself — if `source` and
  `expansion` essentially never co-occur as compatible values on the same
  product, or occur as *mutually exclusive* variant values of the same
  attribute, flag for exclusion rather than auto-including.
- **Independent second-model review.** Have a different model family (not
  the one that generated the asset) classify a sample (or all, if volume
  allows) of generated pairs as "safe synonym" / "risky — review" /
  "likely wrong," and manually resolve the flagged subset. This mirrors the
  cross-generator check in Pitfall 4 and is cheap relative to the cost of a
  silent negation bug reaching the private run.
- **Regression test the negation path specifically against the new asset.**
  Add or extend the constraint-extractor negation tests to synthesize
  messages using every newly added expansion term in a negated context
  ("no [expansion term]") and assert the eligibility gate excludes what it
  should.
- **Freeze with provenance.** Commit the asset with a checksum, the prompt
  used, model name and version, and generation timestamp. Regenerating it
  must be a deliberate, logged, rare action — not something that happens
  incidentally on every build — otherwise the project's own verified
  byte-level-determinism claim becomes false the moment Tier 1 ships. A
  reasonable concrete check: a test asserting the shipped asset's checksum
  matches a pinned value, failing loudly (not silently regenerating) if the
  generation script is re-run without an explicit "update the pinned asset"
  step.

**Warning signs:**
- A generated expansion table with no rejected/flagged entries at all
  (implies no audit ran).
- Any expansion pair spanning attribute values that are mutually exclusive
  on real products in the catalog (e.g., near-zero co-occurrence as
  compatible values).
- The asset-generation script and the agent build script sharing a code
  path such that a normal `build_catalog_artifacts` run could silently
  regenerate (and thus potentially change) the semantic asset.

**Phase to address:** Score improvement (Tier-1 build) — the audit and
freeze-with-provenance steps must be part of the Tier-1 deliverable itself,
not a follow-up.

---

### Pitfall 6: Network-disabled fallback is assumed correct, not verified under realistic failure modes

**What goes wrong:**
`docs/submission_rules.md` reserves the right to disable network access at
scoring time, and PROJECT.md correctly treats "no fallback means scoring
zero" as an Out-of-Scope risk to avoid. But a fallback that is only tested
under "network absent entirely" (e.g., no interface, DNS immediately fails)
can behave completely differently from the organizer's actual mechanism,
which is more likely a firewall rule *blocking* outbound connections from a
host that otherwise has a working network stack. These are not the same
failure mode, and the difference is exactly where a "verified" fallback
turns out not to be.

**Why it happens:**
HTTP client libraries typically have generous default timeouts (many
default to 30-60+ seconds, or no timeout at all, for connect and/or read).
Network failure has several distinct shapes with very different timing:

| Failure mode | Typical behavior without explicit timeouts | Time to fail |
|---|---|---|
| DNS resolution failure | Fast — OS resolver returns an error | ~seconds |
| TCP connection refused (RST) | Fast — immediate OS-level error | milliseconds |
| **TCP connection dropped/blackholed (organizer firewall DROP rule)** | **Slow — client waits for its own connect timeout, often 30s+ or the OS default (~2 minutes on Linux)** | **can exceed any per-turn budget** |
| Read timeout after connect succeeds, response never arrives | Slow — waits for read timeout, same risk as above | can exceed budget |

If the code's "fallback trigger" is simply "catch the exception the HTTP
client eventually raises," and the client's connect/read timeouts are left
at their defaults, a firewall `DROP` (silent discard, the most likely
organizer mechanism for "disable network access") can stall a single Tier-2
call for tens of seconds per turn. Across 800 private sessions with multiple
turns each, this either blows a per-turn/per-session timeout budget (scored
as misses) or makes the run so slow it risks the organizer's own timeout
restrictions — a catastrophic, silent failure that "the fallback exists in
code" would not reveal in review.

**How to avoid:**
- **Set aggressive, explicit connect and read timeouts** on any Tier-2 HTTP
  client (e.g., 1-2 second connect timeout, short read timeout), well
  inside the soft per-turn deadline already planned as a submission-hardening
  item. Do not rely on library defaults.
- **Test the actual failure shape, not just absence of network.** Verify the
  fallback specifically against: (a) DNS failure, (b) connection refused,
  and (c) a blackhole/DROP condition — e.g., point the client at a
  non-routable address (such as a TEST-NET address per RFC 5737, or a
  firewall rule that drops rather than rejects) and confirm the fallback
  triggers within the configured timeout, not after a long default.
- **Measure it end-to-end**, not just unit-test the exception handler: run a
  subset of the full session suite with network actually blocked at the OS
  or container level (not just "don't call the function"), and confirm both
  (a) the agent still returns valid slates and (b) total wall-clock time per
  session stays within budget.
- **Make the fallback path a first-class, regularly-run test**, not a
  one-time manual check — since it will not be regularly exercised in normal
  development (network is presumably on), it is exactly the kind of path
  that silently rots.

**Warning signs:**
- The only evidence for "the fallback works" is that the code has a
  `try/except` around the network call, with no measured run under an
  actually-blocked network.
- No explicit timeout values set on the LLM HTTP client (i.e., using
  whatever the SDK defaults to).
- No test using a genuinely unreachable (not merely "not configured")
  endpoint.

**Phase to address:** Submission hardening — this must land alongside the
soft per-turn deadline item already planned, and specifically as an
end-to-end network-blackout run, not a unit test of the exception handler.

---

### Pitfall 7: A technically strong, invisible-strengths system reads as unfinished to a judge

**What goes wrong:**
This system's real strengths — byte-level determinism, zero token cost,
auditable log-odds ranking, offline capability — are structurally invisible
in a quick skim: there is no UI, and a walkthrough-video format for a
backend/NLP track means judges form an impression from a few minutes of
video plus however much of the repo they actually open. Grounded in
hackathon-judging research: judges specifically weight "does your video and
repo prove it works" and want to see the system *actually doing something
live*, not slides or prose describing capability, and technical screening
rounds exist specifically to filter out projects that don't visibly run —
Devpost's own judging guidance and MLH's judging plan both emphasize working,
visible proof over described capability. A submission that leads with
architecture diagrams and belief-trace math, without ever showing an actual
multi-turn conversation scrolling on screen with a visible improving/hit
result, risks scoring as "sounds impressive, unverified" rather than "proven
working" — regardless of actual code quality.

**Why it happens:**
Solo technical builders tend to explain *how* a system works (which they
find most interesting and most differentiated) rather than *show it working*
(which feels obvious and therefore gets shorter screen time than it should).
Judges, watching many submissions back-to-back in a short window, weight
what's fast to verify over what's technically deep.

**How to avoid:**
- The demo video should open with (or very early include) an actual
  end-to-end multi-turn session transcript playing out — customer message,
  agent clarifying question, ranked slate, hit — before any architecture
  explanation. "Show it working" should consume more video time than
  "explain how it works."
- Explicitly narrate the otherwise-invisible strengths on screen at the
  moment they're relevant (e.g., point at the zero `prompt_tokens` /
  `completion_tokens` in the disclosed output, the deterministic reproduction
  claim, the belief-trace breakdown for one real turn) rather than asserting
  them in prose only.
- Verify the one-command reproduction step on a genuinely clean environment
  (a fresh VM or container, not the dev machine) before recording — a judge
  who informally tries to clone and run the repo and hits the un-lazy
  580 MB artifact build failure (already flagged in CONCERNS.md as the
  single highest deliverability risk) will down-score Feasibility even
  though official scoring uses the organizer's own harness.
- Disclose the Tier-1/Tier-2 build-time LLM usage (Cloudflare Workers AI,
  Claude subagents) explicitly and clearly as **offline, build-time only,
  not required for the judge's run** — the disclosure rule (latency, token
  usage, model cost) exists precisely so a judge doesn't discover an
  undisclosed dependency and penalize the submission for it. State plainly
  that the shipped runtime path is credential-free.

**Warning signs:**
- A draft video script that spends its first minute on architecture slides
  before showing a single actual conversation turn.
- Demo instructions that were only ever run on the development machine.
- Any use of paid/external APIs during the build process that is not called
  out explicitly in the README's disclosure section.

**Phase to address:** Deliverables — write the video script and rehearse
the clean-environment reproduction before recording, not after.

---

### Pitfall 8: Solo-dev time misallocated toward noise-bounded metric gains instead of the untouched 65% of the rubric

**What goes wrong:**
Given Pitfalls 1-3, a meaningful share of the "+0.151 points available in
ranking and speed" identified in PROJECT.md's headroom table may not be
realizable at all once winner's-curse correction and cross-term trade-offs
are accounted for honestly — plausibly a third to a half of it evaporates
under correction for a bake-off of realistic size (see Pitfall 1's table:
k=5-10 bias of 0.02-0.03 against a total MRR-driven headroom of 0.119 raw ×
0.30 weight, i.e. similar order of magnitude once the MRR-equivalent
correction is applied). Meanwhile Impact & Relevance (20%) and Innovation &
Problem Insight (20%) — 40% of total judging, none of it metric-gated — are,
per PROJECT.md, "near-unaddressed." A solo developer with a fixed 2+ week
timeline who keeps refining the bake-off past the point of diminishing,
statistically-uncertain returns is trading time at a bad exchange rate.

**Why it happens:**
Metric-chasing is legible and satisfying — a number goes up, and it's the
same number the project has been improving since 0.125. Rubric criteria like
"Innovation & Problem Insight" are comparatively fuzzy to work on and easy to
defer "until the technical work is done." This is the general Goodhart
pattern (optimize the measurable proxy because it's measurable) applied to
the developer's own time allocation, not just to the model's behavior.

**How to avoid:**
- Apply a stopping rule: once a candidate's winner's-curse-corrected expected
  gain (Pitfall 1's method) falls below some threshold (e.g., 0.005
  TechnicalScore, matching the practical measurement resolution the project
  can act on), stop bake-off iteration and reallocate time to deliverables
  and rubric positioning.
- Timebox the score-improvement phase explicitly against the deliverables
  and rubric-positioning phases up front, rather than letting score
  improvement expand to fill available time by default.
- Track effort allocation against the rubric weights, not just against
  TechnicalScore: if more than ~35% of total remaining time has gone to
  score improvement and none yet to the Impact/Innovation narrative, that is
  already a misallocation relative to the 35% Technical Execution weight.

**Warning signs:**
- Multiple bake-off rounds in a row each reporting sub-0.02 HR@10/MRR deltas
  as "wins" without acknowledging Pitfall 1's correction.
- The README/report/demo script have not been drafted while ranking-tuning
  work continues.
- Innovation and Impact framing (e.g., the public-set structural blind-spot
  finding, which is itself a legitimate insight worth presenting) not yet
  written up as a first-class narrative artifact.

**Phase to address:** Cuts across all phases — but should be an explicit
checkpoint at the transition from score-improvement to submission-hardening,
with a hard go/no-go based on corrected marginal gain, not raw score.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|-----------------|
| Ship a bake-off winner based on raw (uncorrected) public HR@10/MRR delta | Fast decision, simple story | Winner's-curse-inflated result may not hold on the private 800; reported gain becomes a false claim in the writeup | Never for the final ship decision; fine only as a first-pass filter before correction |
| Author the paraphrase probe with the same LLM/context used to build Tier-1 assets | Fast to produce, coherent-sounding cases | Probe measures self-consistency, not generalization — the exact defect it exists to detect | Never; always separate generator context/model family for probe authorship |
| Regenerate the Tier-1 semantic asset casually during iteration | Fast to try variations | Breaks the byte-determinism claim and provenance chain; a regenerated asset with no diff review could introduce Pitfall 5's antonym-class bug silently | Acceptable only during exploratory spikes explicitly marked non-shippable; never for the frozen/shipped asset |
| Rely on HTTP client default timeouts for the Tier-2 network path | No extra config work | Silent multi-minute stalls under a firewall DROP condition, risking timeout-scored misses at scale | Never in the shipped fallback path |
| Defer the demo video script until code work is "done" | Keeps engineering momentum | Rehearsal and clean-environment verification get compressed into the final hours, raising the chance of an undiscovered reproduction failure | Only if a clean-environment dry run has already happened earlier |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|-------------------|
| Cloudflare Workers AI / Claude subagents (Tier-1 build) | Treating the build-time API call as a "runtime dependency" in disclosure, or conversely failing to disclose it at all | Explicitly document it as offline/build-time-only in the README's latency/token/cost disclosure; the shipped agent has zero such dependency |
| Tier-2 runtime LLM candidate | Assuming "catches exceptions" equals "has a tested fallback" | Explicit short connect/read timeouts + an end-to-end run with network actually blocked at the OS/container level, not just unit-tested |
| Organizer's official evaluator harness vs. local dev loop | Verifying reproduction only against the local `uv run` flow, never against a harness that might construct `Agent` differently (e.g., without a pre-run build step) | Test the exact construction path the harness is documented to use, including a missing-artifact scenario |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Unbounded per-run growth (`_sessions`, `turn_history`, `_product_cache`) untested at scale | Fine on 200-session dev runs; RSS climbs steadily and silently | Measure peak RSS on a full 200-session run and extrapolate 4×; bound the product cache with an LRU | 800-session private run, especially if `close()` is never called by the harness |
| No per-turn deadline | Fine when the network is available and fast; degrades to a hang under the exact conditions (blocked network) most likely at scoring time | Add and *test* a soft per-turn deadline that degrades to best-so-far | Any turn where Tier-2's network call stalls past its (currently absent) timeout |
| Treating public-set wall-clock variance (796s vs 1690s observed) as unimportant | Looks fine because both runs "complete" | Add explicit timing budgets and log per-session timing distribution, not just totals | Under organizer-imposed CPU/timeout restrictions on unfamiliar hardware |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Sending catalog attribute text to a third-party LLM API for Tier-1 generation without checking submission-rule constraints on external data transmission | Possible rule violation if the organizer restricts what may leave the local environment, even for public catalog data | Re-read `docs/submission_rules.md` specifically for any data-handling clause before the Tier-1 build; the catalog is public Amazon data but the rule should be checked, not assumed clear |
| Bundling any private evaluation artifact (already well-mitigated per CONCERNS.md) while adding *new* generated files (Tier-1 asset, probe sessions) without extending the disallowed-contents check | New files created this milestone could accidentally include organizer-adjacent material if a probe author leans on real target data incorrectly | Extend the pre-submission disallowed-contents check to cover every new file this milestone creates, not just the existing list |

## Demo / Presentation Pitfalls

(Adapted from the template's UX section — this project has no end-user UX;
the analogous audience is the judge watching the demo and reading the repo.)

| Pitfall | Judge Impact | Better Approach |
|---------|--------------|-------------------|
| Leading the video with architecture/theory before showing a working conversation | Reads as "described, not proven" — judged research shows judges weight visible, live proof heavily | Open with a real multi-turn transcript and a hit, narrate architecture after |
| Reporting TechnicalScore deltas without uncertainty (no mention of noise floor / winner's-curse correction) | An alert judge or a Q&A follow-up could puncture an overstated claim, costing credibility on Innovation/rigor | State the corrected estimate and its uncertainty explicitly — turns a potential weakness into a demonstrated-rigor strength |
| Assuming official scoring's use of the organizer harness means informal judge reproduction attempts don't matter | Judges and reviewers often do at least attempt a clone-and-run even when not required | Verify one-command reproduction on a clean environment before submission |

## "Looks Done But Isn't" Checklist

- [ ] **Byte-determinism claim:** Verified for the existing engine, but not yet re-verified after Tier-1/Tier-2 land — check that the frozen asset has a pinned checksum test and that no live-LLM code path exists on the shipped runtime unless explicitly gated behind a documented fallback.
- [ ] **"Must not regress any scenario" gate:** Looks like a rigorous acceptance criterion; isn't, for the Boundary (n=10) and Intent Override (n=30) buckets, whose binomial noise floors (≈0.086 and ≈0.050 respectively) exceed most plausible real improvements — verify any reported per-scenario regression check states the bucket size and whether the observed delta clears its noise floor.
- [ ] **Network fallback:** Looks complete because a `try/except` exists around the network call; isn't, unless tested against a blackholed/DROP connection with explicit short timeouts and measured wall-clock behavior end-to-end.
- [ ] **Paraphrase probe "generalization confirmed":** Looks like objective evidence; isn't, unless the probe was authored without the target's literal catalog text in-context, its lexical overlap with catalog fields was measured, and (ideally) a second, differently-sourced probe batch agrees.
- [ ] **Bake-off winner:** Looks like a clear improvement; isn't decision-grade until the margin is compared against the order-statistic winner's-curse correction for the number of candidates actually compared.
- [ ] **Clean reproduction:** Looks documented in the README; isn't verified until it has actually been run start-to-finish on a machine that isn't the development machine, including the artifact build step.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|-----------------|
| Shipped bake-off winner turns out to be winner's-curse noise (discovered late) | MEDIUM | Re-run the top 2-3 candidates against the paraphrase probe or an expanded dev sample; if the margin doesn't hold, revert to the prior best-known-good candidate — determinism makes this a cheap, exact rollback |
| Tier-1 asset found to contain an antonym-class error post-freeze | MEDIUM-HIGH | Because the asset is frozen with provenance (prompt, model, checksum), the fix is: audit-and-patch the specific entries, regenerate only the affected subset if possible, re-run the negation regression tests, re-freeze with a new checksum and a logged reason |
| Network fallback discovered to hang under DROP conditions close to submission | HIGH if discovered very late (touches the shipped runtime path directly) | Set explicit short timeouts immediately (cheap code change), re-run the network-blackout end-to-end test, and if time is too short to fully re-validate, ship Tier-2 disabled by default (Tier-1-only) rather than risk timeout-scored misses at scale |
| Demo video found to undersell the system after recording | LOW-MEDIUM | Re-record just the opening segment to lead with a live transcript; this is a script/edit fix, not a code fix |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| 1. Winner's-curse selection bias | Measurement rig | Bake-off report includes k, the order-statistic correction, and a confirmation-sample check before any ship decision |
| 2. Per-scenario noise floors too small to gate on | Measurement rig | Every per-scenario regression claim states bucket n and its binomial SE |
| 3. Ranking-layer Goodhart | Score improvement | Every MRR-improving change validated against paraphrase-probe sessions, not just the original 200 |
| 4. MRR/MTTC/HR@10 trade-off blindness | Score improvement | Every question-logic or ranking change reports all three raw metrics together and is checked against the 0.0667·ΔMTTC breakeven rule |
| 5. Paraphrase-probe circularity | Measurement rig | Probe authored without in-context catalog text; lexical-overlap ratio measured and reported; frozen before use |
| 6. LLM-generated Tier-1 asset corrupts a signal | Score improvement (Tier-1 build) | Antonym/negation audit run and logged; negation regression tests added for every new expansion term; asset checksummed and pinned |
| 7. Network fallback assumed, not verified | Submission hardening | End-to-end run with network blocked at OS/container level; explicit short timeouts configured and logged |
| 8. Demo/repo reads as unfinished | Deliverables | Video opens with a live transcript; clean-environment reproduction verified before recording |
| 9. Solo-dev time misallocated toward noise-bounded gains | Cuts across all phases | Explicit checkpoint at score-improvement → submission-hardening transition, gated on corrected marginal gain vs. remaining rubric-positioning work |

## Sources

- [Self-Preference Bias in LLM-as-a-Judge (arXiv:2410.21819)](https://arxiv.org/abs/2410.21819) — MEDIUM-HIGH confidence, peer-reviewed preprint; grounds Pitfall 4's circularity mechanism.
- [LLM Evaluators Recognize and Favor Their Own Generations — MATS Research](https://www.matsprogram.org/research/llm-evaluators-recognize-and-favor-their-own-generations) — MEDIUM confidence, supports the self-recognition mechanism.
- [Play Favorites: A Statistical Method to Measure Self-Bias in LLM-as-a-Judge (arXiv:2508.06709)](https://arxiv.org/pdf/2508.06709) — MEDIUM confidence, supports measurement methodology (cross-generator checks).
- [Judging Plan — MLH Hackathon Organizer Guide](https://guide.mlh.io/general-information/judging-and-submissions/judging-plan) — MEDIUM confidence, community/organizer-authored but widely used reference.
- [How to win a hackathon: Advice from 5 seasoned judges — Devpost](https://info.devpost.com/blog/hackathon-judging-tips) — MEDIUM confidence, official Devpost blog.
- [Understanding hackathon submission and judging criteria — Devpost](https://info.devpost.com/blog/understanding-hackathon-submission-and-judging-criteria) — MEDIUM confidence, official Devpost blog.
- Order statistics of the standard normal maximum (`E[max of k iid N(0,1)]`) — HIGH confidence, standard mathematical result (classical extreme-value/order-statistic tables), used directly to quantify the winner's-curse bias table in Pitfall 1.
- Binomial standard error `sqrt(p(1-p)/n)` applied to this project's own reported HR@10 (0.920) and scenario mix (40/40/15/5% of 200 sessions) — HIGH confidence, direct computation from PROJECT.md's own stated numbers.
- `.planning/PROJECT.md` — scoring formula, weights, headroom table, active work items, constraints (source of all project-specific numbers used throughout).

---
*Pitfalls research for: competition retrieval/dialogue system, small-public/large-private evaluation, solo hackathon submission*
*Researched: 2026-08-29*
