# Search That Remembers: expanded presenter script

Anything in square brackets is a cue. Do not read the cue aloud.

## Slide 1: Search That Remembers

Hi everyone. We are Cervon, Samuel, and Weichu, and this is Search That
Remembers.

The idea is simple: shopping search should feel like one conversation, even when
the customer adds details, rejects something, or changes their mind.

Our agent searches 50,000 products locally on a CPU. It uses no runtime API calls,
model tokens, GPU, credentials, or vector database. The default BM25 starter only
searches the latest message. We keep its lexical value, but add memory for the
shopper's current intent.

**[FLIP TO SLIDE 2]**

## Slide 2: The End of Forgetful Search

Imagine a customer says, "I need boots." Then, "Under 80 dollars." Then, "Not
leather." Finally, "Actually, make that hiking shoes."

To a person, that is obviously one request developing over time. The starter sees
four separate BM25 queries. It does not retain the budget, understand that leather
is excluded, or know that hiking shoes replace boots.

That starter reaches a public Hit Rate at 10 of 0.125, an MRR of 0.068034, and an
average 9.81 turns to the first correct result. BM25 is useful search evidence, but
by itself it is not a conversation.

**[FLIP TO SLIDE 3]**

## Slide 3: The Architecture of Intent

This is the whole architecture. It looks busy, but the flow is pretty simple.

First, we work out what changed in the new message. The Constraint Extractor turns
that into typed facts, and the Preference Ledger updates the active intent. The
Search Planner runs several local retrieval routes. Then the Eligibility Gate
removes products that break hard requirements, the Candidate Belief Model ranks
the survivors, and the Question Policy decides whether a clarification would help.

The Response Validator checks the organizer contract, and we save seven typed trace
events per turn so we can inspect what happened. Instead of jumping straight from
tokens to a BM25 list, we separate understanding, eligibility, ranking, and
dialogue into stages we can test.

**[FLIP TO SLIDE 4]**

## Slide 4: The Marketplace Memory

This is the part that makes the agent feel conversational.

We do not save the chat as one giant search string. We save typed constraints with
an attribute, value, strength, exclusion flag, confidence, and operation.

If the customer says, "I prefer red boots," and later says, "Ignore that, I need
leather boots," the system removes red, keeps boots, adds leather, and starts a new
intent version. It also treats "not leather" and "no preference" as completely
different state changes.

BM25 can match the word leather, but it cannot reliably know whether leather is
wanted or forbidden. Our ledger keeps that meaning explicit, so a negative
constraint never becomes positive ranking evidence by accident.

**[FLIP TO SLIDE 5]**

## Slide 5: The Retrieval Conductor and Constraint Firewall

Once the intent is clean, we search through several routes instead of trusting one
query.

Structured metadata finds exact facts. Exact and expanded SQLite FTS5 find useful
language. A category route protects broader recall. We combine the routes using
Reciprocal Rank Fusion with k equals 60, cap each route at 1,000 hits, and
materialize at most 5,000 candidates so the CPU work stays bounded.

Then the constraint firewall checks every candidate. A product that violates a
hard requirement or explicit exclusion cannot enter the strict ranking pool. We
may use a one-constraint near match if the slate is short, but we never relax an
exclusion.

The starter trusts one OR-based BM25 order. We keep BM25 as one retrieval signal,
fuse it with structured evidence, and check that every result is actually eligible.

**[FLIP TO SLIDE 6]**

## Slide 6: The Evidence Engine

Now we have eligible products, but we still need a stable order and a useful next
question.

The ranker combines Bayesian log contributions from retrieval routes, soft
preferences, and privacy-safe aggregate profile signals. A stable softmax produces
the final scores, and exact ties use `parent_asin`, so repeated runs stay
deterministic.

For clarification, the agent compares posterior entropy and expected conditional
entropy over up to 64 products. In normal language, it asks the question expected
to remove the most uncertainty. It still shows up to ten products while asking and
does not repeat a question the customer declined.

BM25 gives a relevance order. Our system adds contribution-level reasons and an
information-gain question policy.

**[FLIP TO SLIDE 7]**

## Slide 7: Proof Before Promotion

This is how we stopped ourselves from believing every higher number. Honestly, on
only 200 public sessions, it is very easy to overreact to a tiny movement.

The organizer's TechnicalScore is 50 percent Hit Rate at 10, 30 percent MRR, and
20 percent turn efficiency. We compare candidates on the same samples using a
paired nonparametric bootstrap and paired permutation test, both with 10,000
replicates. We also use Holm-Bonferroni correction, minimum detectable difference,
the Phipson-Smyth p-value floor, and a winner's-curse correction.

Our ship bar is a corrected TechnicalScore gain of at least 0.01 without an unpaid
recall loss. The default BM25 result stays frozen as the external baseline, and our
own experiments face this stricter gate.

**[FLIP TO SLIDE 8]**

## Slide 8: A 7.36x Leap Over the Starter

Here are the final results on the unchanged 200-session public evaluator.

The default BM25 starter finds 25 targets, for a Hit Rate at 10 of 12.5 percent.
Our agent finds 184, for 92 percent. That is 159 additional successful sessions,
79.5 percentage points higher, and 7.36 times the starter result.

MRR rises from 0.068034 to 0.524466, a 670.89 percent improvement. Mean turns to
first correct drops from 9.81 to 3.425, so the right product arrives 65.09 percent
sooner. TechnicalScore rises from 0.10671 to 0.76884, a 620.49 percent increase.

Scenario Hit Rate at 10 is 0.90 for Boundary, 0.95 for Browsing, 0.90 for Buying,
and 0.90 for Intent Override. These are public development results, not a promise
about the private set. The private evaluation is still the real generalization
test.

**[FLIP TO SLIDE 9]**

## Slide 9: The Fixes That Moved the Needle

The biggest gains did not come from adding a huge model. They came from cleaning up
the catalog and handling conversation state correctly.

Attribute classification, material recovery, and better override retention moved
Hit Rate at 10 from 0.760 to 0.915. Separator normalization then moved it to 0.920.
The catalog had 131 concepts across 705 products with inconsistent colon spacing,
and fixing that moved one target from rank 154 to rank one.

We also replaced slow correlated SQL filters that took 263 to 293 milliseconds
with posting-set filters that take about 3 to 7 milliseconds. Intent Override
improved from 0.20 to 0.90, a 70-point gain.

So the improvement over BM25 came from reusable catalog structure and from not
letting stale intent reject an otherwise correct result.

**[FLIP TO SLIDE 10]**

## Slide 10: Experiments We Refused to Oversell

Some ideas sounded good and then did basically nothing. We kept those results too.

Always-on tail exploration changed zero outcomes. A popularity tie-break also
changed nothing. Keyed-feature recovery produced no public gain, although we kept
it for catalog correctness. Per-value regular-expression matching took more than
two minutes, so precomputed indexes replaced it.

The forced TF-IDF fallback looked 0.006110 higher in TechnicalScore, but its 95
percent confidence interval ran from negative 0.018892 to positive 0.031311. The
permutation p-value was 0.645335, the Holm-adjusted p-value was 1.0, and the honest
verdict was "not detectable."

Improving on BM25 did not mean adding every possible retrieval trick. It meant
measuring each one and being willing to say, "No, this did not help."

**[FLIP TO SLIDE 11]**

## Slide 11: Test the Conversation

We have 756 automated tests, and the full suite runs in about eight seconds. More
important than the count is what those tests prove.

We test memory across turns, overrides that remove only the conflicting value,
exclusions that can never be relaxed, and "no preference" replies that become a
decline instead of a fake product value.

We also test the organizer response contract, the first ten unique valid
`parent_asin` values, evaluator byte integrity, deterministic artifact builds,
stable fallback order, bounded turn history, and the statistical pipeline.

The starter BM25 tests lexical retrieval. Our suite proves that conversation state
changes safely and that the same input still produces the same ranking.

**[FLIP TO SLIDE 12]**

## Slide 12: The Unfinished Frontier

We also want to be honest about what is unfinished. These GSD phases are TODOs
because the submission deadline arrived first. None of them is included in the
score I just showed.

Phase 1, the measurement rig, is complete at 15 out of 15 plans. Phase 2, the
expanded dataset and paraphrase probe, is 11 out of 14. The remaining work includes
publishing the 300-pair probe and 100-pair cross-check, two expanded corpora, four
baselines, and paired contrasts.

Phase 3 is TODO for ranking precision and conversational efficiency. Phase 4 is
TODO for an audited synonym asset, ONNX reranking, and runtime LLM extraction with
an offline fallback. Phase 5 is the go or no-go checkpoint based on corrected
marginal gain.

Phase 6 is submission hardening: lazy artifact building, bounded memory across 800
sessions, soft deadlines, blocked-network proof, and artifact-size evidence. Phase
7 is the final Innovation and Impact narrative. Phase 8 is clean-environment
reproduction, the public video and links, disclosures, and the final audit.

We also deferred SPLADE weights, dense ONNX retrieval, a deeper profile prior, soft
price scoring, and live pitch preparation to version two. Every future candidate
still has to beat both our retained agent and the default BM25 reference.

**[FLIP TO SLIDE 13 AND SWITCH TO THE TERMINAL]**

## Slide 13: Demo - Intent Changes, Ranking Changes

I will finish with a real Intent Override session from the released public set.
This uses the actual agent and the organizer's normal turn policy.

The target is `B09YMTWDXJ`, a Casio AQ-800E-7A wristwatch. The customer first asks
for a wristwatch with a stainless steel band. The target appears at rank two, but
the evaluator correctly does not count it because the target intent is not active
yet. On turn two, it moves outside the top ten.

Now the customer says, "Actually, ignore my earlier preference. What I need is:
Water Resistant."

Starter BM25 would search another bag of words. Our preference ledger recognizes
the override, removes the stale constraint, keeps the compatible watch context,
and reranks the same offline catalog.

The target returns at rank one. The final result is a hit on turn three at rank
one. That is Search That Remembers: the customer changes their mind, the stored
intent changes with them, and the ranking changes for a reason we can inspect.

**[STOP RECORDING WITH `RESULT: HIT on turn 3 at rank 1` STILL VISIBLE]**
