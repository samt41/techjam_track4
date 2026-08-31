# Semantic Retrieval Experiment — Implementation Plan

**Date:** 2026-08-30
**Status:** Experiment complete — disabled/hybrid matrix run across four encoders
**Source design:** `docs/superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md`

**Observed decision:** Do not adopt the current hybrid. All encoders preserved
public Hit@10 and passed the small held-out contrast gate, but none produced a
new top-10 hit on the 177-session semantic-gap set. Arctic-S had the best
rank-only delta (+0.0008 technical score) and is the only sensible starting
point if the retrieval integration is redesigned. See
`experiments/semantic/HYBRID_MATRIX_REPORT.md`.

## Decision this plan is designed to make

Do not build semantic retrieval directly into the recommendation path. First
build a reproducible experiment that answers two separate questions:

1. Can a small offline encoder map genuinely unseen customer wording to the
   correct catalog concepts without resolving opposites or unrelated phrases?
2. When those concepts are introduced as low-authority retrieval evidence, do
   they improve end-to-end retrieval without reducing the current public score,
   breaking hard constraints, or exceeding the runtime and artifact budgets?

The experiment ends with a versioned `decision.json` and `REPORT.md` containing
one of three recommendations:

- `adopt`: every usefulness, safety, regression, latency, and size gate passes;
- `iterate`: the probe demonstrates value, but a named safety or operational
  gate fails; or
- `reject`: open-vocabulary lift is too small to justify integration.

No production semantic route is part of the first implementation milestone.

## Why this sequence is necessary

The current public evaluator is not evidence for semantic retrieval. Two miss
classifications found zero vocabulary gaps: the simulator copies words from the
target product's catalog record. Current misses are mostly ranking
discrimination and slate behavior. Consequently:

- the official public set remains a regression test, not the main usefulness
  test;
- usefulness is measured on a held-out, hand-reviewed paraphrase probe and a
  derived semantic-gap benchmark;
- the original `data/public_set.jsonl` and evaluator are never modified; and
- all thresholds are calibrated on a development split and evaluated once on a
  sealed test split.

The full 50,000-product `data/catalog.jsonl` has now been restored according to
`data/README.md`, and the catalog-scale shadow benchmark has run. Generated
catalog and semantic artifacts remain ignored. Unit tests still use small
synthetic catalogs and remain runnable without the private artifact.

## Non-negotiable invariants

1. `semantic_mode=disabled` remains the default and preserves current behavior.
2. Semantic neighbours are soft retrieval evidence only. They never satisfy or
   relax a hard requirement or exclusion.
3. Negation, exclusions, requirement cues, and dialogue state stay symbolic.
4. No experiment reads ground truth inside the agent. Ground truth is joined by
   the analyzer only after a run, following `experiments/run_public.py`.
5. Model downloads and PyTorch are allowed only in the experiment/build
   environment. The candidate runtime is frozen ONNX on CPU and makes no network
   calls.
6. Every result records catalog, dataset, model revision, tokenizer, code
   revision, configuration, and artifact hashes.
7. A missing or invalid semantic artifact degrades to lexical behavior rather
   than failing the turn.

## Experimental architecture

```text
catalog.jsonl
    |
    +-- concept inventory + concept-to-product postings
    |       |
    |       +-- surface view:     "insulated"
    |       +-- contextual view:  "outerwear feature: insulated"
    |
semantic probe.jsonl --------------------------+
    |                                          |
    +-- lexical/manual-expansion baseline      |
    +-- BGE / MiniLM / E5 model adapters ------+--> probe REPORT.md
                                                   + decision gate A

public evaluator messages --> shadow observer --> semantic traces only
          |                        |
          +--> unchanged agent ----+-------------> byte-identical output check
                                                   + decision gate B

derived paraphrase benchmark --> disabled vs enabled hybrid runs
                                                   |
                                                   +--> end-to-end REPORT.md
                                                        + final decision
```

Exact matrix multiplication over L2-normalized concept vectors is the reference
search. Do not add FAISS or another approximate index unless profiling shows the
exact search violates the budget.

## Stage 0 — Freeze the baseline and prerequisites

### Files

- `experiments/RUNS.md`
- `experiments/semantic/README.md` (new)
- `experiments/semantic/config.py` (new)
- `.gitignore` if generated model/run paths are not already ignored

### Work

1. Restore `data/catalog.jsonl`, build the ordinary catalog artifacts, and
   verify the catalog SHA-256 and row count.
2. Run the existing full tests.
3. Retain one current `semantic_mode=disabled` public run using the same code
   revision that will be used for the ablation. Record response/recommendation
   hashes in addition to existing metrics.
4. Define a typed `SemanticExperimentConfiguration` containing model revision,
   templates, probe version, inventory version, split seed, top-k, and calibration
   policy. Do not place thresholds in scattered module constants.
5. Add an optional dependency group such as `semantic-experiment` for
   Sentence Transformers, Transformers, PyTorch, and export tooling. Keep the
   base `[project].dependencies` unchanged in this stage.

### Verification

- `python -m unittest discover -s tests -v` exits zero.
- The retained baseline summary includes catalog, dataset, and code hashes.
- Two disabled runs yield identical per-turn recommendation order.
- Importing `starter.agent` does not import NumPy, ONNX Runtime, Transformers,
  Sentence Transformers, or PyTorch.

## Stage 1 — Build a catalog-grounded concept inventory

### Files

- `experiments/semantic/concepts.py` (new)
- `experiments/semantic/build_concepts.py` (new CLI)
- `experiments/semantic/schemas.py` (new typed records)
- `tests/test_semantic_concepts.py` (new)

### Records

Add immutable records for:

- `CatalogConcept`: stable ID, attribute, optional coarse-category scope,
  surface text, contextual text, source kind, document frequency, approved exact
  aliases, and sorted product ordinals;
- `ConceptInventoryManifest`: catalog hash, inventory-builder version, filtering
  settings, concept count, and output hashes; and
- `ContrastSet`: scope, two or more named poles, catalog-grounded prototypes,
  and neutral prototypes.

Stable concept IDs must be derived only from normalized semantic identity
(`attribute`, scope, surface text, source kind), never row order.

### Inventory policy

1. Reuse the same normalized catalog values already exposed through
   `CatalogIndex.value_counts`.
2. Include structured category, material, color, size, style, brand, and short
   recurring feature values.
3. Measure the catalog frequency distribution and write it to the build report.
   Select the low-frequency and phrase-length filters from that report rather
   than guessing them silently.
4. Exclude malformed values, generic stop words, overlong marketing sentences,
   and unscoped ambiguous values.
5. Persist deterministic JSONL metadata and concept-to-product postings. The
   probe stage may keep vectors in generated run storage; do not extend the
   production artifact manifest yet.

### Verification

- Rebuilding twice produces byte-identical inventory and manifest files.
- Every product ordinal exists in the catalog artifact.
- Every concept has at least one product and normalized non-empty text.
- Tests cover duplicate values, category scoping, ambiguous values, filtering,
  stable IDs, and catalog-hash mismatch.

## Stage 2 — Create and seal the semantic probe

### Files

- `experiments/semantic/probe/v1/calibration.jsonl` (new)
- `experiments/semantic/probe/v1/test.jsonl` (new)
- `experiments/semantic/probe/v1/README.md` (new)
- `experiments/semantic/validate_probe.py` (new CLI)
- `tests/test_semantic_probe.py` (new)

### Probe schema

Each case contains:

- stable case ID and split;
- raw customer clause;
- optional category and attribute scope;
- case kind: `positive`, `opposite_trap`, `unrelated`, `ambiguous`,
  `negated`, or `hedged`;
- acceptable concept IDs or concept groups;
- forbidden concept IDs or poles;
- expected disposition: `resolved_soft`, `ambiguous`, or `ungrounded`; and
- provenance and reviewer notes.

### Dataset requirements

Create at least 300 hand-reviewed cases:

- 140 unseen positive paraphrases;
- 50 opposite/contrast traps;
- 50 in-domain but unrelated clauses;
- 30 deliberately ambiguous clauses; and
- 30 negated or hedged clauses used to test the symbolic boundary.

Stratify across at least five useful concept families and across common catalog
categories. Split by paraphrase family, not random row, so near-duplicates cannot
cross from calibration to test. Probe paraphrases must not be inserted into the
approved alias table.

The validator must reject unknown concept IDs, duplicate clauses across splits,
empty acceptable sets for positive cases, and positive text with exact lexical
overlap to its target after stop-word removal. The last rule ensures this is a
real open-vocabulary test.

## Stage 3 — Benchmark models without changing the agent

### Files

- `experiments/semantic/encoders.py` (new)
- `experiments/semantic/search.py` (new)
- `experiments/semantic/calibration.py` (new)
- `experiments/semantic/run_probe.py` (new CLI)
- `experiments/semantic/analyze_probe.py` (new)
- `tests/test_semantic_search.py` (new)
- `tests/test_semantic_calibration.py` (new)

### Compared systems

Run the identical inventory and splits through:

1. current token matching plus `_EXPANSIONS` as the non-neural baseline;
2. `BAAI/bge-small-en-v1.5`;
3. `sentence-transformers/all-MiniLM-L6-v2`; and
4. `intfloat/e5-small-v2`.

Pin exact upstream revisions. Encode both surface and contextual concept views.
For E5, test the model-card-required prefix policy. For BGE, compare the
no-instruction symmetric phrase setting with the documented query-instruction
variant rather than assuming either wins. Record pooling and normalization
explicitly; an ONNX transformer output is not a sentence embedding until the
model-appropriate pooling and normalization are applied.

### Calibration

Use only `calibration.jsonl` to freeze:

- scope-specific minimum top-score percentile;
- winner/runner-up margin;
- winner/neutral margin;
- minimum surface/context view stability;
- ambiguity band; and
- maximum accepted concepts per clause.

Raw cosine similarity is never interpreted as probability and is never accepted
through one global threshold. Evaluate the frozen configuration once on
`test.jsonl`.

### Reported metrics

- concept Recall@1 and Recall@5;
- mean reciprocal rank;
- resolved-positive coverage;
- opposite-pole accepted-resolution count;
- unrelated accepted-resolution count;
- ambiguity retention;
- disposition confusion matrix;
- warm batch latency p50/p95 and cold-start latency;
- peak RSS; and
- downloaded model plus generated artifact size.

Include bootstrap confidence intervals for positive retrieval metrics and report
raw counts for every safety metric.

### Gate A — permission to continue to shadow mode

At least one model/configuration must satisfy all of the following on the sealed
test split:

- Recall@5 is at least 70% and at least 20 percentage points above the lexical
  baseline;
- no opposite-trap case is accepted as `resolved_soft`;
- no unrelated case is accepted as `resolved_soft`;
- at least 90% of ambiguous cases remain `ambiguous` or `ungrounded`;
- warm batched query latency is below 100 ms p95 on the documented reference
  CPU; and
- model plus generated semantic artifacts are at most 200 MB.

If no model passes, write `decision=reject` and stop. Do not implement an agent
route merely because nearest-neighbour examples look plausible.

## Stage 4 — Add experiment-only shadow mode

This stage runs only after Gate A passes. Shadow mode observes messages and logs
semantic candidates but returns the wrapped agent's response unchanged.

### Files

- `experiments/semantic/shadow_agent.py` (new wrapper)
- `experiments/semantic/clause_observer.py` (new)
- `experiments/semantic/shadow_trace.py` (new)
- `experiments/semantic/analyze_shadow.py` (new)
- `experiments/run_public.py` (add optional shadow arguments)
- `tests/test_semantic_shadow.py` (new)

### Behavior

1. Wrap `Agent` in `SemanticShadowAgent`; do not alter `TurnCoordinator` yet.
2. Observe the raw user message, mask exact catalog mentions and known control
   language, segment clauses, and mark polarity/modality symbolically.
3. Encode only unresolved positive spans. Negated and hard-requirement spans may
   be traced for analysis but cannot emit usable product evidence.
4. Resolve concepts and expand through concept-to-product postings.
5. Write a separate `semantic_shadow.jsonl` containing clause, scope, concepts,
   disposition, product candidates, timing, and artifact fingerprints.
6. Return the base agent response object without mutation.
7. Join ground truth only in `analyze_shadow.py` after evaluation.

### Verification

- With identical inputs, disabled and shadow modes produce byte-identical
  normalized response payloads and recommendation order on every turn.
- A simulated encoder exception leaves the base response unchanged.
- No shadow trace stores vectors.
- The analyzer reports semantic resolutions, abstentions, target-candidate lift,
  false-resolution review queues, and latency without exposing labels to the
  wrapper.

### Gate B — permission to build an enabled hybrid ablation

Continue only if all shadow outputs are identical to baseline, no hard or
negated span is marked usable, and the observer stays inside the runtime budget.
Because the public simulator mostly repeats catalog words, target lift is
diagnostic here and is not required to be positive.

## Stage 5 — Build a derived semantic-gap benchmark

### Files

- `experiments/semantic/paraphrase_map.v1.jsonl` (new, hand-reviewed)
- `experiments/semantic/build_gap_dataset.py` (new CLI)
- generated `experiments/generated/semantic-gap-v1.jsonl` (not committed)
- `tests/test_semantic_gap_dataset.py` (new)

### Work

1. Materialize copies of the public samples with explicit `intent_card` and
   `behavior` fields, which the existing evaluator already supports.
2. Replace selected disclosed catalog phrases with held-out paraphrases from the
   sealed mapping while preserving sample ID, target product, scenario, and all
   non-language behavior.
3. Require the replacement to remove target-bearing lexical overlap after
   normalization. Do not change `data/public_set.jsonl`.
4. Record the source dataset/catalog hashes and every replacement in a lineage
   manifest.
5. Have a reviewer approve the mapping without looking at model rankings.

This benchmark measures the counterfactual question the public set cannot:
whether the same targets remain retrievable when customers use natural synonyms
instead of catalog wording. Its score is an internal ablation, never reported as
the official public score.

## Stage 6 — Enabled hybrid ablation behind an off-by-default flag

This is the first stage allowed to affect recommendations.

### Files

- `starter/shopping_agent/semantic_provider.py` (new protocol, disabled provider,
  frozen provider)
- `starter/shopping_agent/semantic_models.py` (new immutable records and enums)
- `starter/shopping_agent/semantic_artifacts.py` (new validated sidecar loader)
- `starter/shopping_agent/models.py` (add `RetrievalRoute.SEMANTIC`)
- `starter/shopping_agent/retrieval.py` (fuse accepted semantic postings as a
  lower-authority route)
- `starter/shopping_agent/coordinator.py` (optional resolve/trace hook)
- `starter/shopping_agent/diagnostics.py` (typed semantic event)
- `starter/agent.py` (add `semantic_mode=disabled|enabled` and artifact path)
- `experiments/run_public.py` (record semantic configuration)
- focused semantic tests plus regression updates

### Integration policy

1. Load a frozen sidecar containing model/tokenizer files, normalized vectors,
   concepts, postings, calibration, and a manifest. Validate all hashes before
   enabling the route.
2. Batch unresolved clauses once per turn and search the narrowest reliable
   attribute/category scope.
3. Convert only `resolved_soft` and calibrated ambiguous hypotheses into
   `RouteEvidence`. Give the semantic route less weight than expanded FTS and
   multiply it by calibrated confidence.
4. Feed candidates through the existing hard SQL filters and `EligibilityGate`.
   Semantic evidence cannot set `exact_match`, remove a rejection, or create a
   relaxed constraint.
5. Keep ambiguity-aware slate coverage out of the first active ablation. First
   establish whether simple soft fusion adds value; add specialized slate logic
   only if traces show a measurable ambiguity failure.
6. On any load or inference failure, record a typed reason and run the ordinary
   routes unchanged.

### Ablation matrix

Run at least:

| Run | Dataset | Semantic mode | Purpose |
| --- | --- | --- | --- |
| A | original public | disabled | same-revision control |
| B | original public | enabled | official-score regression |
| C | semantic-gap-v1 | disabled | lexical counterfactual baseline |
| D | semantic-gap-v1 | enabled | semantic usefulness |

Repeat A/B recommendation hashing to confirm determinism. Report paired sample
deltas and bootstrap confidence intervals for C versus D.

### Final adoption gate

Recommend `adopt` only if all conditions hold:

- Gate A and Gate B passed;
- enabled mode has no lower public TechnicalScore, HitRate@10, or MRR than the
  same-revision disabled run;
- enabled mode improves semantic-gap HitRate@10 by at least 5 percentage points
  and its paired bootstrap confidence interval does not include zero;
- no semantic candidate bypasses a hard requirement or exclusion;
- ten unique valid recommendations remain available whenever the disabled run
  could provide them;
- repeated enabled runs preserve recommendation order within the documented
  numeric tolerance;
- per-turn semantic inference remains below 100 ms p95 on the reference CPU;
  and
- the frozen runtime bundle remains at most 200 MB.

If usefulness passes but latency/size fails, return `iterate` and perform the
int8 ONNX ablation. Accept int8 only if Recall@5 falls by no more than one point
and it introduces no new opposite or unrelated accepted resolution. If
usefulness or safety fails, return `reject` and keep the current lexical system.

## Stage 7 — Productionization only after an adoption decision

This is deliberately outside the experiment milestone. If the final decision is
`adopt`:

1. move the selected sidecar builder into catalog artifact construction;
2. split build-only and offline runtime dependency groups;
3. pin and bundle model/tokenizer/ONNX files with license attribution;
4. add full manifest/fingerprint validation and atomic publication;
5. add process-level query embedding caching;
6. consider contrast-aware slate coverage only from observed trace evidence;
7. update `LOCAL_ENVIRONMENT.md`, `README.md`, `docs/STATUS.md`, and
   `experiments/RUNS.md`; and
8. run the full test, evaluator, offline-startup, missing-artifact, corrupt-
   artifact, and deterministic-order suites.

## Suggested execution order

| Wave | Work | Stop condition |
| --- | --- | --- |
| 1 | Baseline, inventory, probe schema/data | Probe cannot be validated |
| 2 | Model adapters, search, calibration, report | Gate A fails → reject |
| 3 | Shadow wrapper and public replay | Gate B fails → iterate/reject |
| 4 | Derived gap benchmark and enabled soft route | Final gate decides |
| 5 | ONNX/int8 optimization if needed | Only for `iterate` on operations |
| 6 | Productionization | Only after explicit `adopt` approval |

The most valuable review checkpoint is immediately after Wave 2. At that point
the team will know whether embeddings solve the actual open-vocabulary problem
before paying the integration and runtime complexity costs.

## Primary references

- [BGE Small v1.5 model card](https://huggingface.co/BAAI/bge-small-en-v1.5)
- [MiniLM L6 v2 model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [E5 Small v2 model card](https://huggingface.co/intfloat/e5-small-v2)
- [Sentence Transformers inference and ONNX guidance](https://www.sbert.net/docs/sentence_transformer/usage/efficiency.html)
