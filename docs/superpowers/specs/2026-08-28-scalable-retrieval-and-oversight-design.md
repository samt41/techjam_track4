# Scalable Retrieval and Oversight Design Amendment

Date: 2026-08-28
Status: Approved in conversation; pending written-spec review
Amends: Offline Hybrid Shopping Agent Design

## 1. Purpose

This amendment defines the next deterministic-core revision of the Track 4
shopping agent. It resolves the retrieval, intent-override, exploration,
clarification, fallback, and diagnostic gaps discovered after the first
implementation.

The intended reader is an engineer preparing and executing the implementation
plan. After reading this document, that engineer must be able to implement the
revision without deciding how strict products, intent overrides, exploratory
products, Bayesian questions, backend substitution, or diagnostic attribution
should behave.

The existing headless product boundary remains unchanged. No frontend,
middleware service, authentication system, hosted model, GPU, or live network
dependency is introduced.

## 2. Evidence motivating the amendment

The revision is based on code review, focused reproductions, catalog
benchmarks, public-set analysis, and an ablation.

### Candidate truncation

The current routes return at most 200 candidates and apply final hard
eligibility afterward. A synthetic catalog with 200 high-ranked excluded
products followed by 50 valid products returned zero recommendations, even
though ten valid products were available.

On the 50,000-product catalog:

- an FTS query returning 200 results took approximately 63 to 65 milliseconds;
- returning 1,000 took approximately 67 to 71 milliseconds;
- returning 5,000 took approximately 82 to 89 milliseconds; and
- a naive hard-eligibility pass over all 50,000 products took approximately
  163 milliseconds.

The 200-product limit is therefore a work budget, not a correct definition of
the eligible population. The design must push hard eligibility into retrieval
instead of relying on post-retrieval truncation.

### Intent overrides

The public set contains 30 Intent Override sessions. Five replace a value with
another value classified under the same attribute; 25 replace a preference
with a requirement classified under a different attribute. None reuse the same
value.

The initial category remains valid in these sessions. A complete intent wipe
would therefore discard useful evidence. The required operation is to retract
the referenced provisional preference while preserving the category anchor,
explicit exclusions, and confirmed requirements.

The current representation retained an old active constraint in every one of
the 30 public override sessions. It retained 88 of 98 pre-override active
constraints in total.

### Counterfactual exploration

The retained run executed counterfactual fallback on 53 turns across eight
sessions. All eight were Intent Override sessions. Seven of the eight sessions
still missed.

A strict-only ablation produced identical overall metrics, scenario metrics,
and all 200 session outcomes, hit turns, and target ranks. Fixed exploratory
slot reservation therefore had no measured public-set benefit. Exploration is
retained as private-set protection against false-positive extraction, but it
may fill only positions that strict products cannot fill.

## 3. Binding decisions

The following decisions supersede conflicting behavior in the original design
and first implementation:

1. Hard eligibility is applied inside the search backend before candidate
   limits.
2. The system does not materialize an entire eligible universe at large scale.
   It issues filtered Top-K requests and obtains an exact or lower-bounded total
   match count from the backend.
3. Every available strict product ranks ahead of every exploratory product.
4. There is no fixed seven-strict/three-exploratory allocation.
5. Exploratory products fill only otherwise-unused slate positions.
6. Explicit exclusions are never relaxed.
7. An explicit high-confidence hard requirement may be relaxed only when the
   exhaustive strict query has zero matches, and the relaxation is disclosed.
8. A generic intent override retracts the most recent active provisional
   preference group. It does not clear the category anchor, exclusions, or
   confirmed hard requirements.
9. Hard constraints remain deterministic eligibility rules. Probability does
   not weaken them on the strict path.
10. Bayesian belief is normalized over a bounded eligible candidate population,
    not over the full catalog.
11. Deterministic keys and indexes are built as offline artifacts and loaded at
    runtime. They are not recomputed on every turn.
12. Backend substitution is designed now, but no OpenSearch, Vespa, embedding,
    ANN, or model dependency is added to the competition runtime.
13. Diagnostics observe decisions but cannot alter them. Public ground truth is
    joined only by the experiment analyzer, never supplied to the Agent.

## 4. Search backend boundary

Dialogue, preference state, ranking policy, and response construction depend on
an abstract product-search backend rather than SQLite-specific operations.

The backend accepts fixed-field requests that contain:

- normalized lexical terms;
- positive structured filters;
- explicit exclusion filters;
- numeric ranges;
- stable route identity;
- requested result count;
- deterministic work limits; and
- requested facet attributes when needed.

It returns fixed-field results containing:

- ordered product identifiers;
- route-local scores and ranks;
- total matching product count or an explicit lower-bound indicator;
- facet counts when requested;
- fallback and truncation reasons;
- deterministic work consumed; and
- completed-route latency for diagnostics.

The backend also supports product lookup, artifact metadata, and health
inspection. Backend-specific exceptions are translated into fixed failure
reasons before reaching the coordinator.

### Local backend

The competition implementation uses SQLite FTS5 plus local structured indexes.
Structured indexes use stable integer product ordinals and immutable posting
collections. Positive filters intersect postings, exclusions subtract
postings, and numeric bounds use sorted numeric indexes. The quality order is
stored once and traversed through the filtered membership set.

Lexical search receives the same structured filters. When FTS5 is available,
SQLite performs weighted lexical retrieval. When FTS5 is unavailable, a
bounded deterministic in-memory scorer uses precomputed tokens and document
statistics. Both implementations obey the same response contract and hard
filters.

### Scaled backend

A future million- or billion-product deployment may implement the same contract
with a Lucene-derived distributed system such as OpenSearch, Solr, or Vespa.
Hard filters use keyword fields, doc values, compressed bitmaps, and numeric
indexes. Each shard returns filtered Top-K results, which are merged and
reranked globally.

Approximate vector search may later contribute candidates, but it cannot be the
authority for hard constraints. Structured filter pushdown remains mandatory.

## 5. Deterministic artifact construction

An explicit artifact-build command consumes the catalog and atomically writes
the current artifact schema. It precomputes:

- product identifier to stable ordinal mappings;
- normalized searchable fields and structured values;
- structured posting collections;
- numeric price and rating indexes;
- lexical tokens and document-frequency statistics;
- quality priors;
- catalog-derived aliases and facet statistics; and
- a manifest containing catalog hash, row count, artifact hashes, sizes, and
  build configuration.

The runtime validates the catalog and artifact hashes before serving requests.
A mismatch fails with an actionable rebuild instruction. It does not silently
rebuild during evaluation. No compatibility layer or migration path is
maintained: the build command always produces the one current artifact shape.

Catalog embeddings and ANN structures are extension points only. They are not
built by this revision. If later diagnostics justify semantic retrieval, a
separate build step will precompute product embeddings. Runtime work would then
be limited to encoding the current query and searching the prebuilt artifact.
Missing semantic artifacts must disable only the semantic route.

## 6. Intent state and override semantics

Each preference update records an evidence kind:

- `category_anchor` for the product family that remains stable across a normal
  refinement;
- `explicit_requirement` for a directly requested constraint;
- `provisional_preference` for tentative or exploratory preferences;
- `exclusion` for explicitly forbidden values; and
- `clarification_answer` for a direct answer to the agent's question.

Updates originating from the same interpreted clause share a stable preference
group identifier. The ledger keeps active state and immutable status history.

### Named correction

A named correction such as "ignore leather; use canvas" removes the named
material value and sets the replacement material. Other attributes remain
unchanged.

### Generic intent override

A generic override such as "ignore my earlier preference; what I need is X"
retracts the most recent active `provisional_preference` group, then applies X
as new explicit evidence. It preserves:

- category anchors;
- exclusions;
- confirmed hard requirements; and
- historical records of the retracted group.

If no active provisional group exists, the override does not guess which hard
requirement to remove. It applies the new evidence, advances the intent version,
and records that no referent was found.

Question suppression and failed-slate history are scoped to the intent version.
An override starts a new scope so a previously asked attribute can be useful
again. The full turn history remains available for diagnostics.

Each session retains at most ten typed turn records. A record contains the
message, dialogue act, preference updates, intent transition, selected question,
strict and exploratory slate composition, and disclosed relaxation.

The broader clause and dialogue-act parser redesign, including any decision to
add part-of-speech tooling, is deferred. This amendment changes only the
override semantics needed by the measured scenario.

## 7. Strict retrieval and slate filling

The strict query combines all active hard constraints and exclusions inside the
backend request. Soft preferences influence lexical terms and later belief
scores but do not remove products.

The coordinator requests a bounded ranking population that is larger than the
final slate. It then:

1. fuses route evidence for strictly eligible products;
2. computes candidate beliefs;
3. ranks strict products with stable tie-breaking;
4. takes up to the requested slate size; and
5. if needed, asks the backend for quality-ranked products under the same hard
   filters until the strict slate is full or the backend confirms fewer strict
   products exist.

If the backend reports at least ten strict matches, a ten-item request must
return ten valid unique strict products. A lexical candidate budget cannot
invalidate this invariant.

## 8. Counterfactual exploration

Counterfactual routes never modify the ledger. Each route omits exactly one
relaxable constraint and retains the omitted constraint identifier on every
candidate.

Relaxation priority considers:

- lower extraction confidence;
- provisional or inferred evidence before direct evidence;
- weak catalog grounding and coverage;
- strict-pool collapse attributable to the constraint;
- lack of repetition or confirmation; and
- the number and quality of candidates recovered by omission.

The allocation policy is:

- with at least ten strict products, return ten strict products and execute no
  counterfactual route;
- with one to nine strict products, retain all of them and fill only the tail by
  relaxing soft, provisional, or otherwise uncertain constraints one at a time;
- with zero strict products, try uncertain constraints first; and
- only if those routes also fail may one explicit high-confidence hard
  requirement be relaxed as a final fallback.

Explicit exclusions are never eligible. Exploratory candidates cannot rank
ahead of a strict candidate. The response names every relaxed attribute present
in the returned tail and distinguishes those products as near matches.

## 9. Bayesian candidate belief

Bayesian belief is a ranking model over the bounded strict candidate population.
It is not a replacement for hard eligibility.

For each candidate, the model records typed contributions to an unnormalized
log belief:

- calibrated lexical and route-fusion evidence;
- soft-preference match or mismatch likelihoods;
- feature evidence;
- a weak aggregate-profile prior; and
- a quality prior.

The contributions are configuration fields with named ablations. They are not
unexplained literals embedded in ranking functions. Log beliefs are normalized
with a stable softmax to produce posterior mass. Stable product identifiers
break exact ties.

Profile evidence is capped and soft. It cannot make an ineligible product
eligible or outweigh a directly stated current-session preference. Unknown
metadata contributes neutral evidence rather than an invented match.

Exploratory candidates have a separate disclosed belief calculation under the
single relaxed constraint. Their probabilities do not compete for positions
already occupied by strict products.

## 10. Bayesian clarification

Question selection uses the preliminary strict belief distribution before any
counterfactual routes or final-slate truncation.

For each askable attribute, the estimator:

1. partitions posterior mass into canonical answer buckets, including `unknown`
   and `no_preference` where relevant;
2. estimates each answer probability;
3. conditions the candidate posterior on that answer;
4. computes the answer's posterior entropy;
5. sums probability-weighted conditional entropy; and
6. subtracts it from current posterior entropy to obtain expected information
   gain.

The final decision score applies answerability, coverage, current-intent
relevance, repetition policy, remaining turns, and turn cost. All intermediate
quantities are recorded.

For deterministic single-valued metadata, this reduces to the existing bucket
entropy method. The explicit formulation also supports unknown values, noisy
answers, weak priors, and future response-likelihood calibration.

At large scale, the backend may provide facet counts over the filtered result
population. The belief layer combines those counts with the weighted bounded
candidate sample. It never constructs a billion-product probability vector.

## 11. Reliability and deterministic budgets

Normal execution is bounded by deterministic work limits such as result counts,
posting traversals, query tokens, and reranking population. These limits, not
elapsed timing, determine result order.

Wall-clock limits act as watchdogs at route boundaries. A completed route is
accepted in full; a failed route records a fixed timeout reason and activates a
deterministic fallback. A route is never truncated at an arbitrary elapsed-time
point and then partially fused, because that would make outputs machine-speed
dependent.

Startup and request failures use fixed reasons for missing artifacts, hash
mismatch, malformed catalog data, unavailable FTS5, route timeout, empty strict
pool, and fallback exhaustion. Unknown sessions and closed agents continue to
fail explicitly.

## 12. Diagnostic oversight

The runtime emits fixed-field events with separate responsibilities:

- `InterpretationTrace` records the dialogue act and typed preference updates;
- `RetrievalTrace` records route filters, total hits, returned candidates,
  deterministic work, latency, and fallback;
- `ConstraintTrace` records candidate counts before and after each constraint;
- `BeliefTrace` records retrieval, preference, profile, quality, and posterior
  contributions;
- `QuestionTrace` records current entropy, answer masses, expected entropy,
  information gain, and the policy decision;
- `SlateTrace` records ordered strict and exploratory products with relaxed
  constraint identifiers; and
- `RuntimeTrace` records stage latency, memory use, and artifact metadata.

The Agent does not know the target. The public experiment analyzer joins traces
to ground truth after evaluation and assigns one or more fixed miss reasons:

- target not retrieved;
- target rejected by a named constraint;
- target retrieved but ranked below ten;
- stale provisional evidence survived an override;
- target metadata insufficient for the requested constraint;
- route failure or timeout; and
- fallback exhausted.

Run artifacts retain the existing five-file layout. Their content additionally
records configuration, catalog fingerprint, artifact hashes and sizes, code
revision, route recall and agreement, constraint shrinkage, posterior
contributions, question calculations, slate composition, and stage resource
measurements. The ablation document contains actual comparisons rather than a
single-run description.

Diagnostics are replaceable by a no-op sink and cannot feed back into runtime
decisions.

## 13. Testing strategy

### Retrieval and backend conformance

- Reproduce the excluded-top-200 catalog and require ten strict results.
- Run the same hard-filter and Top-K contract against FTS5 and the in-memory
  lexical fallback.
- Test posting intersections, exclusions, numeric ranges, total-match counts,
  quality fill, fingerprints, stable ordering, and malformed artifacts.
- Exercise missing FTS5 without mocking domain internals.

### Intent and exploration

- Cover same-attribute named corrections and generic different-attribute
  overrides.
- Preserve category anchors while retracting the most recent provisional group.
- Verify removed evidence cannot reappear through weighted concepts.
- Reset question and slate scopes without deleting turn history.
- Return every strict product before any exploratory product.
- Relax exactly one eligible constraint per route.
- Permit explicit hard relaxation only after a confirmed zero-match strict
  query, with disclosure.
- Never relax an exclusion.

### Belief and clarification

- Verify posterior normalization and stable tie-breaking.
- Test each typed belief contribution independently and in combination.
- Prove profile caps cannot overturn stronger session evidence.
- Check expected entropy analytically for balanced, skewed, unknown, and noisy
  answer distributions.
- Verify question selection uses the preliminary strict population rather than
  the returned slate.

### Reliability and diagnostics

- Exercise missing FTS5, corrupt hashes, missing artifacts, route timeout,
  empty strict pools, and malformed products.
- Run with socket access blocked.
- Repeat full runs and compare every ordered slate and structured question.
- Require every public miss to receive a concrete target-aware analyzer reason.
- Verify traces expose preference changes, per-constraint shrinkage, belief
  contributions, question calculations, and slate provenance.

## 14. Evaluation and acceptance gates

The revision is ready for submission consideration only when:

- all organizer and project tests pass;
- ten valid unique strict products are returned whenever the backend confirms
  at least ten strict matches;
- exploratory products never displace strict products;
- explicit exclusions are never relaxed;
- explicit high-confidence hard relaxation occurs only after a zero-match
  strict query and is disclosed;
- all 200 public outputs are deterministic across repeated runs;
- overall public TechnicalScore has no material regression;
- Intent Override HitRate@10 improves from the retained 0.20;
- the full evaluator completes deterministically through the non-FTS fallback;
- every public miss is assigned an actionable diagnostic reason;
- startup, route, turn, memory, and artifact costs are reported separately; and
- no hosted service, GPU, JavaScript runtime, model, or third-party Python
  runtime dependency is required.

The current strict-only and tail-exploration configurations remain a named
ablation. Because the measured public outcomes were identical, retaining
exploration is justified only as non-displacing protection against private-set
false positives.

Any runtime increase above 20 percent on the same machine and configuration
requires profiling and an explicit benefit rationale before retention. Runtime
comparisons exclude one-time artifact construction and compare traced runs with
traced runs or untraced runs with untraced runs.

## 15. Deferred work

The following remain outside this amendment:

- broad dialogue parsing redesign or a part-of-speech dependency;
- semantic phrase clustering;
- catalog embedding construction;
- ANN retrieval;
- OpenSearch, Solr, Vespa, or another deployed search service;
- frontend or visualization work; and
- authentication or persistent customer accounts.

Semantic work receives a separate plan only after diagnostics show a material
lexical or alias recall gap. The comparison must include model size, artifact
size, build time, query latency, memory, packaging risk, and measured retrieval
benefit while preserving the deterministic fallback.

## 16. Delivery order

Implementation proceeds in dependency order:

1. fixed backend and artifact contracts;
2. deterministic artifact construction and local structured indexes;
3. strict filtered retrieval and guaranteed slate filling;
4. typed evidence kinds, turn history, and generic override semantics;
5. non-displacing counterfactual exploration;
6. Bayesian belief and clarification;
7. FTS-independent lexical fallback and watchdog behavior;
8. typed runtime traces and target-aware experiment analysis; and
9. cumulative and removal ablations, documentation, and final packaging.

Each step must pass its focused tests and retain a measured result before the
next dependent step begins.
