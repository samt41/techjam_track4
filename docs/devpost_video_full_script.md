# Search That Remembers: expanded presenter script

Synced to the built deck: `AI-MEMORY TARGETTED PRODUCT SEARCH.pptx` (13 slides).
Slide numbers, titles, and on-screen facts below follow that file, not the earlier
storyboard in `devpost_video_storyboard.md`.

Anything in square brackets is a cue. Do not read the cue aloud.

Timing: the deck carries printed timing boxes only on slides 8 to 13
(1:22 through 2:45). Slides 1 to 7 share the 0:00 to 1:22 opening budget; the
suggested split is in each heading. This expanded script is written for a relaxed
read-through and rehearsal, so it runs longer than those boxes. For the recorded
cut, use the bracketed `[TRIM]` sentences as the first things to drop.

## Slide 1: AI-Memory Targetted Product Search (0:00-0:10)

Hi everyone. We are OpenCheliped: Samuel, Cervon, and Weichu. This is AI-Memory
Targetted Product Search.

The idea is simple: shopping search should feel like one conversation, even when
the customer adds details, rejects something, or changes their mind.

**[FLIP TO SLIDE 2]**

## Slide 2: Search that remembers. (0:10-0:21)

Three stages, and they are on the slide.

Today's starter is one-shot keywords: product details from the customer go
straight into a lexical query. We replace that with an auditable conversation.
Turns are parsed by deterministic rules against an indexed catalog, then filtered
algorithmically. The outcome is the proven next turn and a product slate we can
justify.

All of it runs over 50,000 products on CPU only, with zero online API calls. No
model tokens, no GPU, no credentials, and no vector database.

**[FLIP TO SLIDE 3]**

## Slide 3: Largely improved over BM25. (0:21-0:32)

Here is the shape of the system: shopper messages go into an AI intent ledger,
and the ledger, not the last sentence, is what selects products.

The default starter searched only the latest message. Our agent carries the
shopper's intent across turns. It is a local shopping agent that follows a
changing request instead of treating every sentence as a brand-new search.

[TRIM] Under that arrow there are real stages. A constraint extractor turns the
new message into typed facts. The preference ledger updates the active intent. A
search planner runs several local retrieval routes. An eligibility gate removes
products that break hard requirements, a candidate belief model ranks the
survivors, and a question policy decides whether a clarification would help. A
response validator checks the organizer contract, and we save seven typed trace
events per turn so any decision can be inspected.

**[FLIP TO SLIDE 4]**

## Slide 4: The end of forgetful search. (0:32-0:48)

A shopper always starts broad. "I need boots." Then adds a budget: "under 80
dollars." Then realises he does not want leather. Then changes direction
entirely: "actually, make that hiking shoes."

To a person, that is obviously one request developing over time. A naive
stateless search engine sees four separate queries. It does not retain the
budget, understand that leather is excluded, or know that hiking shoes replace
boots.

That starter reaches a public Hit Rate at 10 of 0.125, an MRR of 0.068034, and an
average 9.81 turns to the first correct result. BM25 is useful search evidence,
but by itself it is not a conversation.

**[FLIP TO SLIDE 5]**

## Slide 5: Our results (0:48-0:56)

The headline, up front.

The default starter is a stateless SQLite FTS5 BM25 search. It scores a
TechnicalScore of 0.10671. Our agentic, memory-backed product search scores
0.76884. That is a 7.21 times improvement.

**[NOTE: 7.21x is the TechnicalScore multiple. The 7.36x on slide 8 is the Hit
Rate at 10 multiple. Do not swap them.]**

**[FLIP TO SLIDE 6]**

## Slide 6: Our agent seeks meaning. (0:56-1:08)

This is the part that makes the agent feel conversational.

"Must have," "I prefer," "not," "ignore that," and "no preference" all cause
different state changes. BM25 can match the word "leather," but it cannot
distinguish required leather, preferred leather, and "not leather."

So we do not save the chat as one giant search string. We save typed constraints:
attribute, value, strength, excluded, confidence, and operator. Hard constraints
sit at confidence 0.90 or above, soft ones stay evidence, negation is scoped, and
every turn resolves to SET, REMOVE, DECLINE, or RETRACT_PROVISIONAL against a
versioned intent.

Follow the boxes. At A the customer says, "I prefer red boots," so at B we store
category equals boots and colour equals red. At C they say, "Ignore that, I need
leather boots." At D we retract the provisional colour, at E we keep the boots
category because it never conflicted, and at F we add material equals leather and
bump the intent version.

**[FLIP TO SLIDE 7]**

## Slide 7: 1 search route's not enough. (1:08-1:22)

Once the intent is clean, we search through several routes instead of trusting
one query.

Structured metadata finds exact facts. Full-text search finds useful language. A
category route protects broader recall. Those are the improved parameters on the
slide: metadata search, FTS5 categories and filters, category quality, Reciprocal
Rank Fusion at k equals 60, and a bounded set of materialised candidates. We cap
each route at 1,000 hits and materialise at most 5,000 candidates, so the CPU
work stays bounded.

Then a deterministic filter removes anything that breaks the shopper's
requirements. A product that violates a hard requirement or an explicit exclusion
cannot enter the strict ranking pool. We may allow a one-constraint near match if
the slate is short, but we never relax an exclusion.

[TRIM] What survives still needs an order. The ranker combines Bayesian log
contributions from the routes, soft preferences, and privacy-safe aggregate
profile signals; a stable softmax produces the final scores, and exact ties break
on `parent_asin` so repeated runs are deterministic. For clarification, the agent
compares posterior entropy against expected conditional entropy over up to 64
products and asks the question expected to remove the most uncertainty, while
still showing ten products.

The starter trusts one OR-based BM25 order. We keep BM25 as one retrieval signal,
fuse it with structured evidence, and check that every result is actually
eligible.

**[FLIP TO SLIDE 8]**

## Slide 8: A 7.36x leap over the starter. (1:22-1:37)

Here are the final results on the unchanged 200-session public evaluator.

The agent finds 184 of 200 targets. The starter finds 25. That is 159 additional
successful sessions.

Hit Rate at 10 goes from 12.5 percent to 92.0 percent: 79.5 points, a 636 percent
increase, 7.36 times. MRR goes from 0.068034 to 0.524466, up 670.89 percent, 7.71
times. Mean turns to first correct drops from 9.81 to 3.425, so the right product
arrives 6.385 turns sooner, a 65.09 percent reduction. TechnicalScore goes from
0.10671 to 0.76884, up 620.49 percent, 7.21 times.

Scenario Hit Rate at 10 is 0.90 Boundary, 0.95 Browsing, 0.90 Buying, and 0.90
Intent Override. The retained agent posts an efficiency of 0.7575 with zero
prompt tokens and zero completion tokens.

These are descriptive improvements over the organizer's published starter on the
same 200-session public set. Private evaluation remains the real generalization
test.

**[FLIP TO SLIDE 9]**

## Slide 9: The fixes that moved the needle. (1:37-1:49)

The largest gains came from understanding catalog structure and conversation
state, not from adding a larger model.

Hit Rate at 10 started at 0.760. Document-frequency attribute classification,
catalog-derived material vocabulary, and soft-retain on override took it to
0.915. Separator normalization took it to 0.920.

That last one is the story in the middle of the slide. One concept had two raw
forms: "material: alloy" with a space, and "material:alloy" without. NFKC,
casefold, and a separator-aware match key normalize both to the same thing. 131
concepts across 705 products used inconsistent colon spacing, and repairing it
moved one target from rank 154 to rank one.

We also rewrote slow correlated EXISTS and NOT EXISTS filters that took 263 to
293 milliseconds into posting-set IN and NOT IN filters that take 3 to 7
milliseconds. Intent Override improved from 0.20 to 0.90.

The starter indexes raw text once. Our build extracts reusable structure, and our
dialogue layer prevents a valid retrieval from being rejected by stale intent.

**[FLIP TO SLIDE 10]**

## Slide 10: Experiments we refused to oversell. (1:49-2:01)

Some ideas sounded useful and measured as useless, uncertain, or too expensive.

Every idea walked the same path on the slide: idea, same-session test,
statistical gate, then ship, reject, or defer. The gate is not casual. The
organizer's TechnicalScore is 50 percent Hit Rate at 10, 30 percent MRR, and 20
percent turn efficiency. We compare candidates on the same samples with a paired
nonparametric bootstrap and a paired permutation test, both at 10,000 replicates,
with Holm-Bonferroni correction, a minimum detectable difference, the
Phipson-Smyth p-value floor, and a winner's-curse correction. Our ship bar is a
corrected TechnicalScore gain of at least 0.01 with no unpaid recall loss.

Four verdicts came back. Rejected: always-on tail exploration changed zero
outcomes, and a popularity tie-break changed nothing because route evidence had
already separated the candidates. The tail-only ablation was delta zero,
confidence interval zero to zero, p equals 1.0, byte-identical across all 200
sessions.

Uncertain: the forced TF-IDF fallback looked 0.006110 higher in TechnicalScore,
but its 95 percent confidence interval ran from negative 0.018892 to positive
0.031311, the permutation p-value was 0.645335, the Holm-adjusted p-value was
1.0, and the minimum detectable difference was 0.035987. Verdict: not detectable.

Correctness only: keyed-feature recovery produced zero public gain, and we
retained it purely for catalog correctness and private-set robustness. Replaced:
per-value regular expressions exceeded two minutes, so precomputed indexes took
over that path.

Improving on BM25 did not mean accepting every extra retrieval idea. Only
measured, reproducible gains belonged in the shipped path.

**[FLIP TO SLIDE 11]**

## Slide 11: Test the conversation, not just the function. (2:01-2:13)

The suite verifies what changes across turns, not only whether one query returns
rows.

**[SLIDE PRINTS "745 unittest cases". THE SUITE IS NOW 756. UPDATE THE SLIDE OR
SAY "MORE THAN 745".]**

We have 756 automated tests running in about ten seconds. The four rows on the
slide are the ones that matter. Memory: "boots" then "black leather," where both
turns return ten unique items and the later results satisfy accumulated intent.
Override: "red boots" then "ignore that; leather boots," where red retracts,
boots remain, and leather becomes active. Exclusion: "boots, but not leather,"
where no leather recommendation ever appears and the exclusion is never relaxed.
Boundary: a question answered with "no preference," which must become a decline
rather than a fake product value, and the question is not repeated.

Named proofs, if you want to read the code:
`test_generic_override_retracts_color_but_preserves_boot_category`,
`test_exclusion_is_never_relaxed_even_with_zero_strict`, and
`test_declined_question_is_not_repeated`.

[TRIM] Around those we also hold an evaluator byte-integrity test, a
deterministic artifact build, a repeated fallback-order test, and a typed
turn-history cap.

The starter tests lexical retrieval. Our suite tests state transitions,
constraint safety, deterministic ordering, failure paths, statistics, and the
organizer contract.

**[FLIP TO SLIDE 12]**

## Slide 12: The unfinished frontier: time-boxed, not hidden. (2:13-2:23)

These GSD phases remain TODO because the submission deadline arrived first. They
are plans, not shipped claims, and none of them is in the score I just showed.

Phase 1, the measurement rig, is the completed foundation: 15 of 15 plans, with
the statistics rig verified 10 out of 10. Phase 2, the paraphrase probe, is 11 of
14; the 300-pair probe and 100-pair cross-check, two expanded corpora, four
baselines, and paired contrasts remain.

Phase 3 is ranking and efficiency: bounded slate feedback, frozen linear
reranking, normalized fusion, confidence-based commitment. Phase 4 is semantic
spikes: a frozen synonym asset, ONNX reranking, and runtime LLM extraction with
an offline fallback. Phase 5 is the go/no-go, gated on winner's-curse-corrected
marginal gain around 0.005 TechnicalScore.

Phase 6 is hardening: lazy build, bounded memory across 800 sessions, soft
deadlines, blocked-network proof, and artifact-size justification. Phase 7 is the
evidence-backed Innovation and Impact narrative after the probe. Phase 8 is
submission: clean reproduction, public video and links, packaged turn history,
disclosures, and the final audit.

Still deferred to version two: SPLADE term weights, dense ONNX retrieval, a
deeper profile prior, soft price proximity, and live pitch preparation. Every
future candidate must still beat both the deterministic agent we retained and the
organizer's BM25 reference.

**[FLIP TO SLIDE 13 AND SWITCH TO THE TERMINAL]**

## Slide 13: Demo - intent changes, the ranking changes. (2:23-2:45)

I will finish with a real intent-override session from the released public set,
sample `public_0003`, run with the actual agent and the organizer's normal turn
policy. The target is `B09YMTWDXJ`, a Casio men's wrist watch, AQ-800E-7A.

Turn one, the customer asks for watches, wrist watches, stainless steel band. The
agent returns ten recommendations and the target is already at rank two, but the
evaluator correctly does not count it, because the target intent is not active
yet.

Turn two, the customer says "no brand preference." That is stored as a decline,
the question is suppressed, and the target drops outside the top ten.

Turn three: "Actually, ignore my earlier preference. What I need is: Water
Resistant." Starter BM25 would just search another bag of words. Our ledger
retracts the provisional steel-band intent, keeps the compatible watches context,
activates water resistance, increments the intent version, and resets slate
suppression for that new version.

The agent reranks the same offline 50,000-product catalog and the target comes
back at rank one. Final result: hit on turn three at rank one, first hit turn
three, reciprocal rank 1.0.

That is search that remembers. The customer changes their mind, the stored intent
changes with them, and the ranking changes for a reason we can inspect.

**[STOP RECORDING WITH `RESULT: HIT on turn 3 at rank 1` STILL VISIBLE]**
