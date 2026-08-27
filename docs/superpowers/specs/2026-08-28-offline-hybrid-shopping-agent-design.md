# Offline Hybrid Shopping Agent Design

Date: 2026-08-28
Status: Approved for implementation planning

## 1. Purpose

This document defines the Track 4 shopping agent that the team will implement. It is written for an engineer joining the project without the prior design discussion. After reading it, that engineer should be able to produce a concrete implementation plan without making new product or architecture decisions.

The product is a headless, multi-turn shopping agent. It interprets a shopper's evolving requirements, recommends catalog products on every turn, and asks useful clarification questions while remaining fully functional without network access.

## 2. Success criteria

The agent must:

- implement the organizer's in-process Python `Agent` contract;
- return ten valid, unique, ranked products on every turn when the catalog permits;
- find the hidden target as early and as highly ranked as possible;
- preserve explicit requirements, exclusions, corrections, and intent overrides;
- use clarification questions only when their expected information value justifies another turn;
- run deterministically with network access disabled;
- degrade safely when optional semantic artifacts are unavailable;
- expose enough diagnostics to explain retrieval, filtering, ranking, and question-selection failures.

The initial system must improve on the frozen baseline without causing a major regression in any scenario class. Exact performance targets will be established from measured ablations rather than assumed before implementation.

## 3. Scope and constraints

### In scope

- Structured conversation state and constraint extraction.
- Deterministic lexical and metadata retrieval.
- Multiple retrieval routes with score fusion.
- Hard eligibility filtering and soft-preference ranking.
- Information-gain-based clarification.
- Controlled counterfactual exploration.
- Optional local semantic retrieval and feature normalization.
- Offline evaluation, diagnostics, and reproducible artifact construction.

### Out of scope

- A frontend, dashboard, or public HTTP API.
- Mandatory hosted LLM or embedding APIs.
- Online learning during evaluation.
- Authentication, user accounts, or persistent customer storage.
- General-purpose product ontology construction beyond what improves this catalog task.

### Environment

- Python is managed with `uv`.
- The deterministic core targets Python 3.13 and the standard library, including SQLite FTS5.
- JavaScript and TypeScript are not required. If a later visualization is approved, it will use `pnpm`.
- Optional semantic work may add NumPy, scikit-learn, Sentence Transformers, and a locally available model. These dependencies must not become necessary for the deterministic fallback.
- The final submission must not require a GPU or live network credentials.

## 4. End-user experience

On the first message, the agent immediately returns its best ten products. When another answer would materially improve the search, it also asks one focused question. On later turns, it incorporates the answer, updates the slate, and avoids repeatedly showing the same failed products.

The agent distinguishes exact matches from alternatives. It does not silently present a product that violates an explicit requirement as a match. When no exact matches are available, it explains that the tail of the list contains near matches and identifies the requirement that was relaxed.

Corrections take effect immediately. For example, "Actually, ignore leather; I need canvas" supersedes the old material constraint instead of adding a contradictory second requirement.

## 5. Architecture

Each turn follows this pipeline:

1. Interpret the message and produce typed preference updates.
2. Apply updates transactionally to the session's preference ledger.
3. Build and execute the strict retrieval routes.
4. Enforce eligibility constraints and produce a preliminary fused ranking.
5. Estimate clarification value from that candidate distribution.
6. Build and execute any justified counterfactual exploration routes.
7. Produce the final fused ranking and rotate the slate where appropriate.
8. Validate and return ten recommendations plus an optional question.
9. Emit diagnostics without affecting behavior.

Retrieval happens on every turn. Asking a question does not replace recommendation generation.

Dependencies are one-way. Language interpretation cannot rank products, ranking cannot reinterpret intent, and diagnostics cannot change outputs.

## 6. Components and contracts

### `Agent`

The organizer-facing adapter. It exposes the required `reset(...)` and `respond(...)` methods, translates contract values into domain types, and delegates a turn to `TurnCoordinator`. It contains no search policy.

### `TurnCoordinator`

Runs one complete turn in the defined order. It is the only component allowed to coordinate state updates, question selection, retrieval, ranking, response validation, and diagnostics.

### `CatalogIndex`

Owns immutable normalized product records, catalog vocabularies, metadata indexes, SQLite FTS5, and optional semantic artifacts. It is constructed once per process and contains no session state.

### `ConstraintExtractor`

Converts a user message and dialogue context into typed `PreferenceUpdate` values. It identifies the attribute, operator, polarity, strength, confidence, source turn, and referenced prior question. It never mutates the ledger.

### `PreferenceLedger`

The authoritative shopping intent for one session. It applies preference updates transactionally and retains supersession history, explicit non-preferences, weighted concepts, prior questions, and turn history.

### `QuestionValueEstimator`

Estimates the effective number of remaining possibilities and the expected information gain of each askable attribute from the preliminary strict candidate pool. It produces scored `QuestionCandidate` values but does not decide whether to ask.

### `ClarificationPolicy`

Applies turn cost, repetition, answerability, relevance, and confidence rules to the scored question candidates. It returns either no question or one `ClarificationDecision` containing an allowed attribute and customer-facing prompt.

### `RetrievalPlanner`

Creates bounded `RetrievalPlan` values for strict search, route expansion, and leave-one-constraint-out exploration. It does not execute queries or alter session intent.

### `CandidateGenerator`

Executes metadata, FTS5, fallback, and optional semantic routes. It returns typed `ProductCandidate` values with fixed route-provenance fields.

### `EligibilityGate`

Evaluates confident hard constraints and exclusions. It returns accepted candidates and typed rejection reasons. It is the final authority on whether a candidate is an exact match.

### `ProductRanker`

Fuses retrieval evidence and scores soft preferences, quality, profile compatibility, and diversity. It cannot remove or reinterpret constraints.

### `RecommendationHistory`

Tracks products shown under the current intent version. It supports slate rotation after a miss and resets when an intent override changes the target intent.

### `ResponseValidator`

Guarantees the organizer response shape, catalog-valid product identifiers, uniqueness, ordering, maximum length, and non-negative usage fields when present.

### `EvaluationTrace`

Records fixed diagnostic events and reason codes. It is replaceable by a no-op implementation for submission runs.

## 7. Domain model

Domain data uses dataclasses and enums with explicit fields rather than nested dictionaries with arbitrary keys. Core types include:

- `ProductRecord`
- `PreferenceConstraint`
- `PreferenceUpdate`
- `WeightedConcept`
- `ShoppingIntent`
- `QuestionCandidate`
- `ClarificationDecision`
- `RetrievalPlan`
- `ProductCandidate`
- `EligibilityDecision`
- `RankedRecommendation`
- `TurnResponse`

A preference constraint records:

- normalized attribute;
- comparison operator;
- canonical value;
- positive or negative polarity;
- hard or soft strength;
- extraction confidence;
- source turn and source text;
- active, removed, or superseded status.

Hard logic determines eligibility. Weighted concepts influence retrieval and ranking. Negation is represented explicitly through operators and polarity; it is not represented as a negative probability.

## 8. Constraint extraction

Extraction is deterministic-first and context-aware.

### Processing sequence

1. Classify the conversation act: initial request, constraint answer, no preference, correction, exclusion, removal, feedback, or intent override.
2. Extract raw mentions without discarding their original spans.
3. Use the previous `ask_attribute` to resolve short answers such as "canvas" or "no preference."
4. Normalize mentions against catalog-derived vocabularies for category, brand, material, color, department, size, feature, style, use case, and price.
5. Assign polarity, operator, strength, confidence, and negation scope.
6. Produce preference updates.
7. Apply additions, removals, and supersessions atomically.

### Confidence policy

- At or above 0.90: eligible to become a hard filter when the language is explicit.
- From 0.70 to below 0.90: ranking boost or penalty only.
- From 0.40 to below 0.70: weak retrieval concept or clarification evidence.
- Below 0.40: ignore or clarify.

An uncertain interpretation may influence ranking but must not become a hard filter.

Explicit signals such as "must," "only," "under $50," and "not leather" increase hardness. Signals such as "prefer," "ideally," and "something like" remain soft unless later confirmed.

The high-precision rule layer is the production foundation. Semantic parsing may be added only as a fallback for concepts the deterministic layer cannot ground. A hosted LLM may be used during development as an annotation aid, but never as a required evaluator dependency.

## 9. Feature concept normalization

Feature phrases use a deterministic alias layer followed by category-local semantic clustering.

### Offline algorithm

1. Normalize Unicode, case, whitespace, punctuation, common units, and known aliases.
2. Deduplicate feature phrases within each coarse product category.
3. Encode phrases with a small local sentence-embedding model. The reference model is `sentence-transformers/all-MiniLM-L6-v2`; it may be replaced only after a measured retrieval and packaging comparison.
4. L2-normalize embeddings.
5. Run agglomerative clustering with average linkage, cosine distance, no fixed cluster count, and an initial cosine-similarity threshold of 0.82.
6. Preserve unmatched phrases as singleton concepts.
7. Choose each cluster's medoid as its canonical representative.
8. Persist category, representative, aliases, product membership, and cohesion in `FeatureConceptIndex`.

The threshold is tuned on labelled equivalent and non-equivalent phrase pairs. Merge precision must reach at least 95%; false separation is preferable to merging unrelated requirements.

PCA is omitted unless profiling proves dimensionality reduction is necessary. UMAP is permitted only for diagnostic visualization. If agglomerative clustering becomes too slow for the phrase inventory, replace its execution strategy with cosine-thresholded fast community detection while preserving the same acceptance criteria.

Clustering occurs during artifact construction, not during conversational turns.

## 10. Clarification by expected information gain

The preliminary strict candidate pool is treated as a probability distribution. Route-fusion scores are normalized into candidate weights; calibration may use a fixed-temperature softmax selected on the development split.

For each askable attribute:

1. Partition weighted candidates into canonical value signatures, including an explicit unknown bucket.
2. Calculate current candidate entropy.
3. Calculate expected conditional entropy after each plausible answer.
4. Compute information gain as the entropy reduction.
5. Derive the effective possibility count as `2^entropy`.

Multi-valued fields use bounded canonical signatures. For feature questions, the estimator considers high-coverage binary feature concepts and may choose one as the prompt's focus while returning `feature` as the allowed structured attribute.

The final question score is:

`information_gain * answerability * catalog_coverage * intent_relevance - turn_cost`

The policy must not ask about an attribute that was answered, explicitly declined, or superseded without new evidence. It asks only when the best score exceeds a tuned threshold and another turn remains.

The first implementation uses entropy reduction. A later ablation may simulate each possible answer and use expected improvement in target probability or reciprocal rank instead.

## 11. Retrieval planning and candidate generation

The planner creates bounded routes:

1. Structured metadata retrieval for reliable fields.
2. Exact FTS5 retrieval for explicit phrases and strong concepts.
3. Expanded FTS5 retrieval using canonical aliases and weighted soft concepts.
4. Optional local semantic retrieval for sparse lexical results or exploratory requests.
5. Category-quality fallback for underspecified requests.

Each route initially contributes up to 100 candidates. The limit is configurable and tuned using route recall and latency.

Candidate lists are merged with weighted reciprocal-rank fusion because raw scores from different routes are not comparable. The initial fusion constant is 60. Route weights are configuration values with named ablations, not unexplained literals embedded in ranking code.

Structured hard constraints should be pushed into retrieval where efficient. `EligibilityGate` still rechecks every final candidate so retrieval optimizations cannot bypass policy.

## 12. Eligibility, ranking, and controlled exploration

### Strict slate

The strict path enforces all confident hard constraints and explicit exclusions. Eligible candidates are ranked using:

- lexical relevance;
- semantic relevance when available;
- hard-constraint coverage;
- soft-preference and feature-concept coverage;
- category specificity;
- aggregate user-profile compatibility;
- rating confidence;
- retrieval-route agreement;
- near-duplicate diversity.

The aggregate user profile is soft evidence only. It cannot override current explicit intent.

### Counterfactual routes

To recover from false-positive extraction, the planner creates leave-one-constraint-out plans. These plans do not modify the preference ledger.

`ConstraintReliabilityEstimator` ranks possible relaxations using:

- extraction confidence;
- whether the constraint was inferred or directly stated;
- catalog grounding and coverage;
- candidate-pool collapse caused by the constraint;
- contradiction with other preferences;
- repetition or confirmation history;
- candidate recovery when the constraint is omitted.

Only one constraint may be relaxed in a counterfactual route. Explicit exclusions, repeated requirements, and unambiguous "must" constraints receive the strongest protection.

The initial slate allocation is seven strict positions and three exploratory positions. This is dynamic: high strict confidence may use all ten positions, while an empty strict pool may allocate more positions to counterfactual candidates. Exploratory candidates remain behind stronger strict candidates and retain the exact relaxed-constraint reason.

### Slate size and rotation

The agent returns exactly ten valid unique recommendations whenever possible. Products beyond position ten provide no scoring benefit and are not returned.

Continuation to another turn is evidence that the previous slate missed. Previously shown products are therefore deprioritized in favor of unseen candidates. They may reappear when evidence changes materially or too few credible unseen products remain. Intent overrides reset this suppression because a previously shown product may become relevant to the new intent.

## 13. Reliability and fallback behavior

The deterministic core must remain available if optional components fail.

- `CatalogIndex` validates required fields and artifact fingerprints during startup.
- Missing semantic artifacts disable only the semantic route.
- FTS5 failure falls back to indexed metadata retrieval and a bounded in-memory lexical scan.
- Every route has candidate and time budgets.
- Unknown sessions initialize safely.
- Invalid or duplicate identifiers are removed before output.
- Fixed seeds and stable tie-breaking preserve reproducibility.

If strict filtering returns no candidates:

1. Retry broader candidate generation without removing hard constraints.
2. Identify contradictory or weakly grounded constraints.
3. Ask about the most suspicious relevant attribute.
4. Fill the recommendation slate from one-at-a-time counterfactual routes.
5. State that these products are near matches and identify the relaxed requirement.

The system never silently relaxes an explicit hard constraint.

## 14. Diagnostics and experiment artifacts

Each experiment run records:

- official overall and per-scenario metrics;
- first-hit turn and target rank;
- route recall and route agreement;
- target presence before and after eligibility filtering;
- candidate-pool shrinkage by constraint;
- strict and counterfactual slate composition;
- predicted question information gain and observed pool reduction;
- parser confidence and preference updates;
- per-stage latency, failures, timeouts, and fallback reasons;
- memory use and artifact sizes;
- configuration, catalog fingerprint, and code revision.

The stable run layout is:

- `experiments/<run-id>/summary.json`
- `experiments/<run-id>/sessions.jsonl`
- `experiments/<run-id>/failures.jsonl`
- `experiments/<run-id>/retrieval_routes.jsonl`
- `experiments/<run-id>/ablation.md`

Old run outputs are removed unless they are the best retained run for a meaningful class of change. A compact project-local summary records retained runs and lessons.

Diagnostics use fixed event and reason types. Arbitrary payload dictionaries are avoided where explicit typed records are practical.

## 15. Testing strategy

### Unit tests

- Normalization, negation scope, hardness, confidence, and operators.
- Add, remove, supersede, decline, and intent-override ledger updates.
- Feature-cluster threshold behavior and medoid selection.
- Entropy, effective possibility count, and information gain.
- Question repetition, relevance, answerability, and turn-cost policy.
- Reciprocal-rank fusion, eligibility, ranking, and stable tie-breaking.
- One-at-a-time constraint relaxation and protected exclusions.
- Response validity, uniqueness, and ten-item slate filling.
- Recommendation-history rotation and override reset.

### Golden dialogue tests

Golden cases cover Buying, Browsing, Intent Override, and Boundary behavior. They include paraphrases and adversarial negation rather than copying only the public simulator templates.

### Integration tests

- Run the organizer's contract tests unchanged.
- Run the complete public evaluator from a clean `uv` environment.
- Run with network access unavailable.
- Repeat identical runs and compare complete outputs.
- Exercise missing semantic index, corrupt fingerprint, FTS5 failure, empty strict pool, and malformed product data.

### Experiment protocol

Maintain a deterministic, scenario-stratified development split for tuning and a held-out split for local regression checks. Because the public set is small, report bootstrap confidence intervals and paired session-level changes. Supplement it with catalog-derived synthetic constraint and paraphrase cases, without treating synthetic performance as an official metric.

Every substantial change is compared through cumulative and removal ablations:

1. Existing strict lexical baseline.
2. Structured intent and eligibility.
3. Multi-route fusion.
4. Information-gain clarification.
5. Counterfactual exploration.
6. Optional semantic retrieval.

## 16. Acceptance gates

Implementation is ready for submission consideration only when it:

- passes all organizer tests;
- produces ten valid unique products whenever the catalog permits;
- runs deterministically without network access;
- preserves explicit hard constraints unless a near-match relaxation is disclosed;
- improves the frozen baseline overall;
- has no unexplained major regression in a scenario class;
- records why the target was missed or removed where public ground truth is available;
- documents Python, dependency, artifact, and execution requirements;
- demonstrates a complete multi-turn session.

## 17. Delivery sequence

Implementation proceeds in dependency order:

1. Reproducible baseline and diagnostic schema.
2. Typed catalog records, normalization, and indexes.
3. Constraint extraction and preference ledger.
4. Structured and FTS5 retrieval with eligibility filtering.
5. Fusion, ranking, ten-item slates, and history rotation.
6. Information-gain question selection.
7. Counterfactual exploration and disclosed near matches.
8. Feature concept artifact construction.
9. Optional local semantic retrieval.
10. Final ablations, failure testing, packaging, and documentation.

Each step must pass its tests and improve or explain its evaluation impact before the next dependent step begins.

## 18. Design decisions

- The product is headless; frontend work is deferred.
- The reliable core is deterministic and offline.
- Recommendations are generated on every turn, even when asking a question.
- Hard constraints determine eligibility; soft evidence determines rank.
- Uncertain interpretations never become hard filters.
- Clarification uses estimated information gain rather than a fixed question order.
- Feature normalization uses deterministic aliases plus category-local cosine-thresholded clustering.
- Cross-route scores use reciprocal-rank fusion.
- Every scored slate is filled to ten products when possible.
- Controlled exploration uses one-at-a-time counterfactual constraint relaxation.
- Intent overrides reset failed-slate suppression.
- Semantic retrieval is an optional enhancement, not a runtime requirement for fallback operation.
