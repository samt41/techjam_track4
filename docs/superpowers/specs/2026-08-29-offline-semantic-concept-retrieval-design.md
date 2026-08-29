# Offline Semantic Concept Retrieval — Design Specification

> Status: approved design, not implemented.
>
> Reader: an engineer adding open-vocabulary retrieval to the deterministic
> shopping agent without access to the design conversation.
>
> Post-read action: build the semantic artifacts and implement the optional
> semantic route without weakening exact matching, symbolic constraints, or the
> offline evaluator contract.

## 1. Objective

Add an offline semantic fallback that can connect previously unseen customer
language to catalog concepts. For example, a runtime clause containing `hot`
may retrieve catalog concepts such as `insulated` and `thermal` even when `hot`
does not occur in the frozen catalog.

The catalog is encoded once during artifact construction. During a conversation,
only unresolved query clauses are encoded. No hosted model, network request, API
credential, or GPU is required during evaluation.

The semantic route improves recall. It does not replace structured matching,
exact lexical retrieval, hard eligibility, or symbolic dialogue state.

## 2. Non-negotiable invariants

1. Exact structured matching remains the highest-authority signal.
2. Explicit negation, requirement, exclusion, and hedging remain symbolic.
3. A dense-vector neighbour cannot independently satisfy a hard constraint.
4. Exact aliases and approved inflections may satisfy hard constraints; learned
   semantic neighbours may not.
5. Semantic retrieval is optional. Missing or invalid semantic artifacts disable
   only the semantic route.
6. Recommendations are still produced on every turn. Asking a question does not
   replace or reduce the ten-product slate.
7. Runtime behavior is offline, bounded, deterministic up to documented numeric
   tolerance, and auditable through typed diagnostics.
8. The public evaluator is unchanged.

## 3. Encoder decision

The provisional encoder is `BAAI/bge-small-en-v1.5`.

Reasons:

- it is an English retrieval encoder;
- it produces 384-dimensional embeddings;
- it has official ONNX support;
- its MIT license permits bundling;
- its CPU footprint is compatible with one small batch per turn; and
- BGE v1.5 supports retrieval without a mandatory query instruction.

The initial comparison baselines are:

- `sentence-transformers/all-MiniLM-L6-v2`, representing lower-cost general
  sentence similarity; and
- `intfloat/e5-small-v2`, representing a prefix-conditioned small retriever.

BGE is provisional until the domain probe in section 14 is run. The encoder is
selected by measured domain recall, contrast safety, latency, and artifact size,
not by a generic leaderboard alone.

### 3.1 Runtime format

The official runtime uses an exported ONNX model on CPU. It must not require
PyTorch, Sentence Transformers, a model hub, or a network connection.

The first measured implementation uses the unquantized ONNX graph as the quality
reference. An int8 graph is accepted only if it passes the quantization gate in
section 14.

### 3.2 Text representations

Catalog concepts receive two versioned textual views:

1. a surface view, such as `insulated`; and
2. a contextual view, such as `outerwear feature: insulated`.

Query clauses receive the corresponding raw and context-enriched views when the
parser has reliable category or attribute context. All views use the same frozen
templates during artifact construction and runtime inference.

No BGE query instruction is used in the initial symmetric phrase-to-concept
comparison. An instruction-prefixed variant is an explicit ablation, not an
unrecorded runtime choice.

## 4. Catalog concept inventory

The semantic index contains concepts rather than only full product descriptions.
A concept is a normalized attribute value or a useful feature phrase connected
to the products that contain it.

Each immutable `CatalogConcept` contains:

- a stable concept identifier;
- its attribute;
- optional coarse-category scope;
- normalized surface text;
- document frequency;
- source kind;
- product ordinals; and
- zero or more approved exact aliases.

The implementation uses typed records and tuples rather than dictionaries with
open-ended keys.

### 4.1 Inventory filtering

The artifact builder removes or context-gates:

- empty and malformed values;
- values below a measured low-frequency noise cutoff;
- values whose length exceeds the feature-phrase limit;
- common conversational tokens that are not reliable catalog concepts; and
- ambiguous values without the category or attribute context needed to ground
  them.

The cutoff is derived from catalog frequency distributions and validated against
the extraction-noise regression set. It is not a list of evaluator sentences.

### 4.2 What is not encoded initially

The first revision does not encode every full product record. Concept-to-product
postings already recover products while preserving an explanation of why they
were retrieved. Full-product embeddings remain a later ablation if concept
retrieval demonstrates a measurable recall ceiling.

## 5. Offline artifact construction

The artifact builder performs the following operations once per catalog and
encoder revision:

1. derive and filter the concept inventory;
2. create surface and contextual text views;
3. batch-encode all views;
4. L2-normalize every embedding;
5. persist the vector matrix in a memory-mappable format;
6. persist typed vector-row-to-concept and concept-to-product mappings;
7. construct scoped background statistics and contrast sets;
8. write a manifest; and
9. validate the completed artifact before publishing it atomically.

The manifest records:

- catalog SHA-256;
- encoder identifier and exact revision;
- model and tokenizer file hashes;
- ONNX graph hash and numeric format;
- concept-builder version;
- text-template version;
- vector dimension and row count;
- normalization policy;
- contrast-set version; and
- artifact file hashes.

An artifact with any fingerprint mismatch is unavailable rather than partially
trusted.

## 6. Runtime clause encoding

The deterministic language layer first segments the user message into clauses
and assigns symbolic modality and polarity. Exact catalog grounding and
morphological grounding run before semantic resolution.

Only unresolved positive concept spans proceed to the encoder. Negation cues and
other operators are never embedded as a substitute for symbolic interpretation.

If a turn contains multiple unresolved clauses, all required textual views are
encoded in one batch. The batch result is restored to the original clause order
before state updates are constructed.

A bounded process-level cache may reuse embeddings for an identical tuple of:

- normalized clause;
- category context;
- attribute context;
- text-template version; and
- encoder fingerprint.

The cache affects latency only and cannot change results.

## 7. Scoped semantic search

Semantic search is performed against the narrowest reliable concept scope:

1. known attribute and category;
2. known attribute across categories;
3. known category across compatible attributes; or
4. the global filtered concept inventory.

For the current inventory, exact matrix multiplication over normalized vectors is
the reference search. An approximate-nearest-neighbour index is not introduced
until profiling proves the exact search violates the runtime budget.

Each clause produces a bounded tuple of `SemanticConceptCandidate` records with:

- concept identifier;
- scoped rank;
- raw cosine similarity;
- surface-view and contextual-view scores;
- best-score percentile and neutral margin;
- contrast-set identifier, when present;
- winning pole and competing pole scores;
- direction margin;
- axis agreement;
- stability across views; and
- an acceptance disposition.

## 8. Relative alignment and contrast sets

Raw cosine similarity is not treated as a probability and is not accepted through
a universal threshold. Confidence is based primarily on relative evidence within
the applicable semantic scope.

### 8.1 Contrast sets

A contrast set contains two or more competing semantic poles within one product
attribute or use context. Examples include:

- warming versus cooling;
- waterproof versus water-absorbing;
- formal versus casual; and
- lightweight versus heavyweight.

A pole is represented by multiple catalog-grounded prototypes rather than one
antonym. The warming pole might contain `warm`, `insulated`, `thermal`, and
`fleece-lined`; the cooling pole might contain `cooling`, `breathable`,
`ventilated`, and `moisture-wicking`.

Contrast sets may be proposed by an offline language model, but they are frozen,
typed, validated artifacts. They do not introduce a runtime LLM dependency.

### 8.2 Pole scoring

For normalized query vector `q` and the prototype vectors in pole `j`, the pole
score is a stable aggregation of its strongest prototype similarities. The
initial aggregation is the mean of the best two available prototype scores.
Single-prototype poles use that one score.

The strongest pole is `j1` and the runner-up is `j2`:

```text
direction_margin(q) = pole_score(j1, q) - pole_score(j2, q)
```

This answers which interpretation the query supports more strongly. It does not
answer whether the query is about the contrast set at all.

When a contrast set supplies paired prototypes, it also exposes several semantic
directions rather than one fragile antonym axis:

```text
axis_i = normalize(positive_prototype_i - negative_prototype_i)
alignment_i(q) = dot(q, axis_i)
```

The resolver records the median alignment, its sign agreement across prototype
pairs, and its dispersion. A stable direction requires several prototype pairs
to point the same way. This geometry classifies semantic contrast only; it never
implements the symbolic meaning of `not`.

### 8.3 Relative topicality and the unknown class

An unrelated query still has a winning pole, so direction alone is unsafe. A
large concept index also gives an unrelated query an accidental nearest
neighbour. Comparing only with the median catalog similarity is therefore a
diagnostic, not an acceptance rule.

Each contrast set includes neutral prototypes from the same attribute and
category scope. Topicality is expressed through two relative margins:

```text
direction_margin(q) = best_pole_score(q) - runner_up_pole_score(q)
neutral_margin(q) = best_pole_score(q) - strongest_neutral_score(q)
```

The resolver also records the best-score percentile, median, and median absolute
deviation across the scoped background, but these values cannot independently
accept a resolution.

Held-out positive, opposite, ambiguous, and unrelated clauses calibrate the joint
distribution of direction margin, neutral margin, axis agreement, and view
stability. This calibration creates an explicit unknown region. It may be
implemented as frozen empirical quantiles initially; a conformal prediction set
is the preferred follow-up if the probe has enough examples per contrast family.

### 8.4 Stability and disposition

The resolver also compares surface and contextual query views. A candidate is
less trustworthy when small context changes reverse the winning pole.

The final disposition has three states:

- `resolved_soft`: topical, directionally separated, and stable;
- `ambiguous`: topical but without a stable winning interpretation; or
- `ungrounded`: insufficient topical evidence.

Acceptance uses calibrated cutoffs over direction margin, neutral margin, axis
agreement, and view stability. These are relative-statistic cutoffs, not
universal cosine constants. The cutoffs are frozen in configuration after the
held-out probe.

### 8.5 Multiway alternatives

Not every attribute has a natural opposite. Materials, colors, and styles often
have several peers. The same mechanism uses the strongest and second-strongest
peer groups rather than inventing a binary antonym.

Explicit language such as `not warm` remains symbolic. The semantic resolver
grounds the positive concept `warm`; the constraint layer then applies the
exclusion operator. Relative alignment is never logical negation.

## 9. Product retrieval and ranking

A `resolved_soft` concept opens a semantic retrieval route through its
concept-to-product postings. Route evidence is weighted by its calibrated
semantic confidence, direction margin, neutral margin, view stability, and
concept rank.

An `ambiguous` clause retains multiple concept hypotheses with normalized
relative weights. Products may receive evidence from more than one hypothesis.
Products satisfying several live interpretations receive the combined evidence
and naturally rank ahead of single-interpretation products when other evidence
is equal.

Semantic route evidence is combined with structured, exact lexical,
morphological, and fallback routes through the existing auditable fusion layer.
It cannot bypass the eligibility gate.

## 10. Ambiguous slates and clarification

An ambiguous semantic interpretation never produces an empty response. The
agent returns ten recommendations whenever the catalog permits.

Slate construction follows these priorities:

1. products supported by several live interpretations;
2. products with the highest posterior expected relevance;
3. coverage of every interpretation whose posterior mass exceeds the calibrated
   coverage floor; and
4. the ordinary strict/fallback policy for remaining slots.

There is no fixed five/five split. Interpretation coverage is driven by posterior
mass and marginal slate coverage, with deterministic tie-breaking.

The agent may ask a clarification question in the same response. In the official
simulator, recommendations are scored before the next reply, and only the
structured `ask_attribute` controls what information is revealed. Therefore the
agent asks the best allowed attribute, such as `feature`; it does not assume the
simulator understands an arbitrary binary question written in the message.

The user-facing message may still explain the ambiguity. In a real interface it
could ask whether `hot` means warming or cooling, but evaluator behavior must be
based only on the documented attribute reply protocol.

## 11. Hard and soft semantic policy

The semantic route begins as soft evidence only.

The following may participate in hard query-token coverage:

- exact normalized tokens;
- approved spelling aliases; and
- approved inflectional equivalents.

The following may not independently satisfy a hard constraint:

- encoder nearest neighbours;
- LLM-proposed near-synonyms;
- broader or narrower relations;
- contrast-pole membership; and
- statistically associated terms.

A semantic interpretation can become hard only through later explicit customer
confirmation, at which point the confirmed surface phrase is stored as new
symbolic evidence rather than silently changing the original extraction.

## 12. Diagnostics and oversight

Semantic diagnostics are emitted only through the existing no-op-by-default
trace interface. They include:

- clause segmentation and encoded clause order;
- exact and morphological grounding outcomes;
- semantic scope and number of concepts searched;
- top concept identifiers and raw similarities;
- scoped median, MAD, percentile, and neutral controls;
- contrast poles and prototype support;
- direction margin, neutral margin, axis agreement, and view stability;
- acceptance disposition and reason;
- selected product postings and route contribution;
- batch size, encoder time, vector-search time, and total semantic-route time;
- model and artifact fingerprints; and
- whether semantic retrieval was disabled or degraded.

The production no-op trace must not retain embeddings or allocate diagnostic
payloads that are never emitted.

## 13. Failure and fallback behavior

Semantic retrieval is disabled for the process when any of these conditions is
detected during initialization:

- model, tokenizer, or vector artifact is missing;
- a fingerprint or dimension does not match;
- the ONNX graph cannot be loaded;
- the runtime lacks a declared CPU execution provider; or
- artifact validation fails.

A per-turn encoder failure disables only that turn's semantic route and records a
typed reason. Exact structured, lexical, morphological, ranking, clarification,
and fallback behavior continue.

No failure path downloads a model, contacts a service, or mutates evaluator
files.

## 14. Evaluation and acceptance gates

### 14.1 Domain semantic probe

Create a versioned, hand-reviewed probe containing:

- unseen customer paraphrases that map to catalog concepts;
- exact aliases and inflections;
- broader, narrower, and strength-qualified relations;
- antonym and contrast traps;
- unrelated clauses;
- deliberately ambiguous clauses;
- multi-clause messages; and
- negated and hedged clauses whose operators are checked separately.

Paraphrases used for evaluation must not also be generated into the encoder's
approved alias table. The probe measures open-vocabulary behavior rather than
memorized aliases.

Compare BGE Small v1.5, MiniLM L6 v2, and E5 Small v2 using the same concept
inventory and splits. Report concept Recall@1, Recall@5, mean reciprocal rank,
opposite-pole false resolution, unrelated-clause false resolution, ambiguity
retention, and clause-batch latency.

### 14.2 Model-selection gate

BGE remains selected only if it provides the best safe retrieval trade-off under
all of these constraints:

- no worse opposite-pole or unrelated-clause false resolution than the accepted
  baseline;
- semantic query encoding below 100 ms p95 on the documented reference CPU;
- encoder plus semantic artifacts no larger than 200 MB; and
- no public-evaluator technical-score regression when the semantic route is
  enabled.

If BGE misses a runtime or size gate, MiniLM is preferred over removing semantic
fallback entirely, provided it passes the safety gates.

### 14.3 Quantization gate

The int8 ONNX model replaces the reference model only when:

- Recall@5 drops by no more than one percentage point;
- no new opposite-pole or unrelated-clause false resolutions appear;
- batched outputs preserve accepted decisions; and
- measured p95 latency or artifact size materially improves.

### 14.4 Behavioral regression gates

The full test and evaluator pass must demonstrate:

- semantic-disabled behavior remains available and valid;
- exact and hard-constraint tests are unchanged;
- `not X` never resolves by selecting an embedding opposite;
- ambiguous clauses keep multiple interpretations in the slate;
- ten valid unique recommendations are returned whenever possible;
- batched and individual clause encoding agree within the documented numeric
  tolerance; and
- repeated runs preserve recommendation order under deterministic tie-breaking.

## 15. Dependencies and reproducibility

Python dependencies are managed with `uv`.

The intended runtime dependency set is limited to:

- NumPy for vector storage and exact matrix multiplication;
- ONNX Runtime for CPU inference; and
- the tokenizer runtime required by the frozen encoder.

Sentence Transformers, Optimum, PyTorch, and model-export utilities are build-only
dependencies. They do not belong in the evaluator runtime environment.

The repository or submission bundle contains the frozen model/tokenizer files, or
a documented setup step materializes them before offline evaluation. Runtime must
never rely on a mutable model-cache lookup. Licenses and upstream model revisions
are recorded with the artifacts.

## 16. Implementation sequence

1. Build the held-out semantic probe and contrast-set schema.
2. Benchmark the three encoder candidates without changing the agent.
3. Freeze the selected encoder, templates, and acceptance configuration.
4. Extend catalog artifact construction with concepts, vectors, mappings, and
   manifests.
5. Add batched runtime encoding behind an optional semantic provider interface.
6. Add relative alignment, multiway ambiguity, and typed diagnostics.
7. Add the semantic retrieval route as soft evidence.
8. Add ambiguity-aware slate coverage and evaluator-compatible clarification.
9. Run semantic, regression, runtime, size, and quantization gates.
10. Update the README and retained experiment table with measured results.

No implementation step may promote semantic neighbours into hard eligibility.

## 17. External references

- BGE Small v1.5 model card:
  <https://huggingface.co/BAAI/bge-small-en-v1.5>
- MiniLM L6 v2 model card:
  <https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2>
- E5 Small v2 model card:
  <https://huggingface.co/intfloat/e5-small-v2>
- Sentence Transformers ONNX and quantization guidance:
  <https://www.sbert.net/docs/sentence_transformer/usage/efficiency.html>
