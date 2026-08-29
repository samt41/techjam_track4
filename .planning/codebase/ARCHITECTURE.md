<!-- refreshed: 2026-08-29 -->
# Architecture

**Analysis Date:** 2026-08-29

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                  Harness / Entry Points                      │
├──────────────────┬──────────────────┬───────────────────────┤
│ local_evaluator  │   run_public     │  build_catalog_...    │
│ `evaluator/      │ `experiments/    │ `starter/shopping_    │
│  local_evaluator │  run_public.py`  │  agent/build_catalog_ │
│  .py`            │                  │  artifacts.py`        │
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │ reset / respond  │                     │ (offline, once)
         ▼                  ▼                     │
┌─────────────────────────────────────────────────┼───────────┐
│              Organizer adapter: `Agent`         │           │
│              `starter/agent.py`                 │           │
└────────┬────────────────────────────────────────┼───────────┘
         │ TurnResponse                            │
         ▼                                         │
┌─────────────────────────────────────────────────┼───────────┐
│         Turn orchestration: `TurnCoordinator`   │           │
│         `starter/shopping_agent/coordinator.py` │           │
│                                                 │           │
│  extract → ledger → plan → retrieve → gate →    │           │
│  rank → question → tail fill → validate → trace │           │
└──┬───────┬───────┬───────┬───────┬───────┬──────┼───────────┘
   │       │       │       │       │       │      │
   ▼       ▼       ▼       ▼       ▼       ▼      │
constraint pref  retrieval ranking belief clarif  │
_extractor _ledger .py     .py    .py    ication  │
   │       │       │       │       │       │      │
   └───────┴───────┴───┬───┴───────┴───────┘      │
                       ▼                          │
┌─────────────────────────────────────────────────┼───────────┐
│  Backend port: `ProductSearchBackend` (Protocol)│           │
│  `starter/shopping_agent/search_backend.py`     │           │
│  Adapter: `LocalProductSearchBackend`           │           │
│  `starter/shopping_agent/local_search_backend.py`           │
└─────────────────────────────────────────────────┼───────────┘
                       │ read-only, mmap           │ writes
                       ▼                           ▼
┌─────────────────────────────────────────────────────────────┐
│  SQLite artifact  `data/catalog.artifacts/catalog.sqlite3`   │
│  products | attributes | products_fts | lexical_postings     │
│  + `manifest.json`   (built by `catalog_artifacts.py`)       │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `Agent` | Organizer-facing adapter; opens backend, maps dict payloads to typed models | `starter/agent.py` |
| `TurnCoordinator` | Single-turn orchestration and session state; emits all seven trace events | `starter/shopping_agent/coordinator.py` |
| `ConstraintExtractor` | Dialogue-act classification and catalog-gazetteer constraint parsing | `starter/shopping_agent/constraint_extractor.py` |
| `PreferenceLedger` | Typed constraint accumulation, correction/override/removal, intent versioning | `starter/shopping_agent/preference_ledger.py` |
| `RetrievalPlanner` | Builds the multi-route `SearchRequest` plan sharing one hard-filter tuple | `starter/shopping_agent/retrieval.py` |
| `LocalProductSearchBackend` | SQL execution: structured, FTS5, TF-IDF fallback, quality routes; product materialization + cache | `starter/shopping_agent/local_search_backend.py` |
| `EligibilityGate` | Re-checks each materialized candidate against hard constraints | `starter/shopping_agent/ranking.py` |
| `ProductRanker` | Evidence fusion, population bounding, eligibility, soft scoring, ordering | `starter/shopping_agent/ranking.py` |
| `CandidateBeliefModel` | Auditable Bayesian posterior with typed log contributions | `starter/shopping_agent/belief.py` |
| `PosteriorQuestionModel` / `ClarificationPolicy` | Expected-entropy-reduction attribute choice and ask/skip decision | `starter/shopping_agent/clarification.py` |
| `ResponseValidator` | Drops unknown/duplicate ids, caps slate, discloses relaxations | `starter/shopping_agent/response.py` |
| `CatalogArtifactBuilder` | Offline artifact build, material/keyed-feature recovery, FTS weighting, atomic publish | `starter/shopping_agent/catalog_artifacts.py` |
| `CatalogIndex` | Thin catalog-vocabulary facade over the backend (facets, value counts) | `starter/shopping_agent/catalog_index.py` |
| Diagnostics | Typed trace event records and JSONL sink | `starter/shopping_agent/diagnostics.py` |

## Pattern Overview

**Overall:** Layered deterministic pipeline behind a ports-and-adapters storage boundary. No frameworks, no runtime dependencies (`pyproject.toml` declares `dependencies = []`), standard library only at inference time.

**Key Characteristics:**
- Offline precomputation is separated from query time. Nothing in `catalog_artifacts.py` runs during a turn.
- Storage is abstracted by the `ProductSearchBackend` Protocol (`search_backend.py:212`); the agent never touches `sqlite3` directly.
- Every stage is a pure-ish transform over frozen dataclasses in `models.py`; state lives only in `_SessionState` inside the coordinator.
- Determinism is a hard invariant: all sorts carry `parent_asin` as a final tie-break, and traces are byte-comparable across runs.
- Diagnostics are a first-class output, not logging: seven fixed-schema typed events per turn.

## Layers

**Entry / adapter layer:**
- Purpose: harness integration and payload marshalling
- Location: `starter/agent.py`, `evaluator/local_evaluator.py`, `experiments/run_public.py`
- Contains: `Agent`, `_profile_from_payload`, `_SessionMappingAgent`
- Depends on: coordinator, response, diagnostics
- Used by: the organizer harness

**Orchestration layer:**
- Purpose: sequence one turn, own session state, emit traces
- Location: `starter/shopping_agent/coordinator.py`
- Contains: `TurnCoordinator`, `_SessionState`
- Depends on: every domain module
- Used by: `Agent`

**Domain layer (interpretation → retrieval → scoring):**
- Purpose: constraint understanding, retrieval planning, eligibility, ranking, questioning
- Location: `constraint_extractor.py`, `preference_ledger.py`, `retrieval.py`, `ranking.py`, `belief.py`, `clarification.py`, `response.py`
- Depends on: `models.py`, `search_backend.py` (types only), `text_normalization.py`
- Used by: the coordinator

**Storage layer:**
- Purpose: bounded SQL shortlists and product materialization
- Location: `search_backend.py` (port), `local_search_backend.py` (adapter), `catalog_index.py` (vocabulary facade)
- Depends on: `sqlite3`, the built artifact
- Used by: planner execution, ranker, validator, extractor gazetteer

**Build layer:**
- Purpose: one-off artifact construction and validation
- Location: `catalog_artifacts.py`, `build_catalog_artifacts.py`
- Used by: CLI only, never at query time

**Analysis layer:**
- Purpose: post-run miss attribution over the typed traces
- Location: `experiments/analyze_public.py`, `experiments/analyze_misses_b1.py`
- Used by: `run_public.py`

## Data Flow

### Primary Request Path — one query end to end

1. Harness calls `Agent.respond(session_id, message, turn, top_k)` (`starter/agent.py:55`), which delegates to the coordinator and wraps the result with `response_payload` (`starter/shopping_agent/response.py:62`).
2. `TurnCoordinator.respond` starts a timer, raises if closed or if `reset` was never called (`coordinator.py:119`).
3. `ConstraintExtractor.dialogue_act` classifies the message (`constraint_extractor.py:270`).
4. `ConstraintExtractor.extract` parses against the catalog gazetteer with scoped negation and typed confidence (`constraint_extractor.py:168`); price patterns via `_price_updates`, catalog phrases via `_catalog_updates`.
5. `PreferenceLedger.apply` merges the updates atomically, superseding conflicting scalars and soft-retaining overridden preferences (`preference_ledger.py:40`); it returns a `ShoppingIntent` whose `intent_version` increments only when the active set changed.
6. `InterpretationTrace` is recorded (`coordinator.py:138`).
7. `RetrievalPlanner.strict` builds the route plan (`retrieval.py:75`): one `METADATA` route per soft attribute value via `_attribute_targets`, plus `EXACT_FTS`, `EXPANDED_FTS` (through `_EXPANSIONS`), and `CATEGORY_FALLBACK`. All routes share the immutable `_hard_filters` tuple (`retrieval.py:181`).
8. Each plan runs through `execute_search_plan_traced` (`retrieval.py:299`) → `LocalProductSearchBackend.search` (`local_search_backend.py:82`), which dispatches to `_search_quality` or `_search_lexical` (FTS5 or the deterministic TF-IDF posting fallback). Each hit becomes a `ProductCandidate` carrying `RouteEvidence` weighted by `_ROUTE_WEIGHTS`. A `RetrievalTrace` is emitted per route (`coordinator.py:317`).
9. `ProductRanker.rank` (`ranking.py:73`) calls `_scored`, which fuses evidence with RRF (`score / (60.0 + rank)`) and truncates to `_POPULATION_CAP = 5_000` **before** materializing anything (`ranking.py:180`).
10. `backend.get_products` materializes the bounded ids (cached for the backend's life), and `EligibilityGate.evaluate` (`ranking.py:34`) re-checks every hard requirement and exclusion. Violators are dropped here, before ranking.
11. Survivors get `_soft_preference_score` added, and strict survivors are scored by `CandidateBeliefModel.score` (`belief.py:90`) producing per-component typed log contributions combined through `_stable_softmax`.
12. Strict items sort by `(already_shown, -posterior, -score, parent_asin)`; exploratory items sort after them (`ranking.py:96`). The `already_shown` key is what rotates the slate within an intent version.
13. `ProductRanker.strict_population` (`ranking.py:115`) re-uses the memoized `_scored` result, and `PosteriorQuestionModel.score_population` + `ClarificationPolicy.choose` pick the question from the *full* strict population, before any tail fill (`coordinator.py:173`).
14. `_fill_tail` runs only if the slate is short **and** exploration is enabled, **or** whenever the strict pool is empty (`coordinator.py:193`). It orders relaxations via `build_reliabilities` / `order_relaxations` and issues `COUNTERFACTUAL` plans that each relax exactly one non-excluded constraint.
15. `ResponseValidator.validate` drops unknown/duplicate ids and caps to `top_k` (`response.py:15`).
16. `RecommendationHistory.record` stores the shown set for the next turn's rotation; the chosen attribute is remembered in `state.last_asked_attribute` (`coordinator.py:208`).
17. Constraint, belief, question, slate, and runtime traces are emitted; `TurnRecord` is appended (last 10 kept); `TurnResponse` is returned (`coordinator.py:260`).

### Offline Build Flow

1. `python -m starter.shopping_agent.build_catalog_artifacts --catalog ... --output ...` (`build_catalog_artifacts.py:16`).
2. `_parse_catalog` / `_parse_product` normalize every text field with NFKC + casefold (`text_normalization.normalize_text`).
3. `_with_recovered_materials` applies the head-noun rule against `_material_vocabulary`; `_with_recovered_keyed_features` recovers mis-filed `color: black` style features into structured color/size/style.
4. `_build_database` writes `products`, `attributes`, `lexical_postings`, `lexical_terms`, and the `products_fts` FTS5 virtual table with the per-field weights (`catalog_artifacts.py:433`); secondary indexes are created after bulk load.
5. The manifest is validated and the directory published atomically; a mismatch raises `ArtifactValidationError`.

### Process-Start Flow

1. `LocalProductSearchBackend.open` (`local_search_backend.py:62`) opens the SQLite file read-only and memory-maps it (1 GiB map, 128 MiB page cache); it checks the catalog fingerprint and file sizes rather than re-hashing the ~575 MB database.
2. `ConstraintExtractor.__init__` builds the phrase gazetteer from `CatalogIndex` facet counts, classifying each phrase to one attribute by document frequency (`_STRUCTURED_DF_FLOOR = 2`).

**State Management:**
- All mutable state is per-session in `_SessionState` (`coordinator.py:57`): profile, `PreferenceLedger`, `RecommendationHistory`, `last_asked_attribute`, `turn_history`.
- `ProductRanker._scored_cache` is a single-entry, identity-keyed memo that deliberately retains its key objects to avoid `id()` reuse (`ranking.py:154`).

## Key Abstractions

**`ProductSearchBackend` (Protocol):**
- Purpose: the storage port — `search`, `facets`, `get_products`, `contains_product`, `catalog_fingerprint`, `close`
- Examples: `starter/shopping_agent/search_backend.py:212`, implemented by `local_search_backend.py:47`
- Pattern: structural typing; tests substitute fakes without SQLite

**`ShoppingIntent` / `PreferenceConstraint`:**
- Purpose: the versioned typed constraint set that every downstream stage reads
- Examples: `starter/shopping_agent/models.py:96`, `models.py:155`
- Pattern: frozen slotted dataclasses with `validate()`

**`RetrievalRoute` + `RouteEvidence`:**
- Purpose: attribute retrieval provenance to each candidate so fusion and traces can explain it
- Examples: `models.py:63`, `models.py:183`

**`BeliefContribution`:**
- Purpose: one auditable named log-odds term per scoring component
- Examples: `belief.py:67`, surfaced in `BeliefTrace` (`diagnostics.py:115`)

**Trace events:**
- Purpose: seven fixed-field per-turn records — interpretation, retrieval, constraint, belief, question, slate, runtime
- Examples: `diagnostics.py:21`–`diagnostics.py:195`
- Pattern: each exposes `as_record()`; sinks are `NoOpEvaluationTrace` and `JsonlEvaluationTrace`

## Entry Points

**`Agent`:**
- Location: `starter/agent.py:15`
- Triggers: the organizer harness
- Responsibilities: `reset`, `respond`, `close`, `turn_history`

**`evaluator.local_evaluator`:**
- Location: `evaluator/local_evaluator.py:298`
- Triggers: `uv run python -m evaluator.local_evaluator`
- Responsibilities: unmodified official scoring loop; never edited

**`experiments.run_public`:**
- Location: `experiments/run_public.py:327`
- Triggers: `uv run python -m experiments.run_public --run-id <id>`
- Responsibilities: traced reproducible run; atomically publishes five files under `experiments/<run-id>/`

**`starter.shopping_agent.build_catalog_artifacts`:**
- Location: `starter/shopping_agent/build_catalog_artifacts.py:16`
- Triggers: one-off CLI before any evaluation

## Architectural Constraints

- **Determinism:** byte-level reproducibility is an acceptance property. Any new sort, set iteration, or dict ordering must have an explicit deterministic tie-break (convention: `parent_asin` last).
- **Threading:** single-threaded throughout. The SQLite connection is opened read-only and is not shared across threads.
- **No runtime dependencies:** `pyproject.toml` has `dependencies = []`. Inference must remain standard-library only — no network, model server, GPU, or credential.
- **Global state:** none mutable at module level. Module constants (`_ROUTE_WEIGHTS`, `DEFAULT_BELIEF_CONFIGURATION`, `_EXPANSIONS`, `_NEUTRAL_PROFILE`) are frozen values.
- **Circular imports:** none. Import direction is strictly entry → coordinator → domain → `search_backend`/`models`/`text_normalization`.
- **Bounded per-turn work:** route limit 1,000 (`retrieval.py:70`), ranker population 5,000 (`ranking.py:31`), clarification population 64 (`clarification.py:44`), belief trace 20 (`coordinator.py:54`), rejected trace 50 (`coordinator.py:53`). Nothing may grow with conversation length.
- **Evaluator immutability:** `evaluator/local_evaluator.py` and the public labels are never modified.

## Anti-Patterns

### Retrieve-then-reject constraint mismatch

**What happens:** a canonicalized value is written into retrieval SQL but a differently-normalized form reaches `EligibilityGate._matches`, so matching products are retrieved and then discarded.
**Why it's wrong:** it silently zeroes recall for a whole scenario — this cost Intent Override 0.20 vs 0.90 Hit Rate@10.
**Do this instead:** put all normalization behind `text_normalization.match_key` (`text_normalization.py:17`) so retrieval SQL, the eligibility gate, and the belief matcher read one canonical form.

### Hand-ordered attribute priority and hand-written block lists

**What happens:** deciding which attribute a catalog phrase belongs to via a hardcoded priority list, or dropping junk with a maintained stop list.
**Why it's wrong:** it does not transfer to the private catalog and it is unmaintainable.
**Do this instead:** classify by document-frequency evidence with a small floor, treating the free-text `FEATURE` bucket as residual (`constraint_extractor.py:97`, `_STRUCTURED_DF_FLOOR`). Only the generic Snowball stop-word set is acceptable.

### Estimating the clarifying question from the final slate

**What happens:** running the question model after tail fill or on the top-`k` items.
**Why it's wrong:** the question then sees a truncated, relaxation-contaminated distribution rather than the true posterior spread.
**Do this instead:** call `ProductRanker.strict_population` before `_fill_tail`, exactly as `coordinator.py:173` does.

### Scoring before bounding

**What happens:** materializing products or running belief scoring over the full fused candidate set.
**Why it's wrong:** cost becomes unbounded in the route output.
**Do this instead:** bound by cheap evidence-only RRF first, then materialize (`ranking.py:176`).

### Identity-keyed caches that drop their keys

**What happens:** memoizing on `id(obj)` without retaining a reference.
**Why it's wrong:** CPython recycles addresses, producing a nondeterministic false cache hit across turns.
**Do this instead:** store the keyed inputs alongside the result (`ranking.py:251`).

### Modelling negation as a negative score

**What happens:** treating "not leather" as a downweight rather than symbolic state.
**Why it's wrong:** exclusions must be absolute and are never relaxed, including during counterfactual tail fill.
**Do this instead:** keep exclusion as a boolean on `PreferenceConstraint` enforced in SQL filters and in `EligibilityGate`.

## Error Handling

**Strategy:** fail fast and loudly on contract violations; degrade silently only where a deterministic fallback exists.

**Patterns:**
- Typed build/validation errors: `ArtifactBuildError`, `ArtifactValidationError` (`catalog_artifacts.py:36`).
- Dataclass `validate()` methods on every request/result type (`search_backend.py`, `models.py`) enforce invariants at construction boundaries.
- `RuntimeError` for lifecycle misuse: closed agent, `respond` before `reset` (`coordinator.py:120`).
- Graceful degradation only where deterministic: `LexicalMode.AUTO` falls back from FTS5 to the TF-IDF posting path (`local_search_backend.py:195`); `resource` import is optional on Windows (`coordinator.py:48`).
- Output defence: `ResponseValidator` removes unknown or duplicate identifiers rather than trusting upstream.

## Cross-Cutting Concerns

**Logging:** none. All observability goes through the typed `EvaluationTrace` protocol (`diagnostics.py:223`) into JSONL. Do not add `print` or `logging`.
**Validation:** `validate()` on frozen dataclasses at construction; artifact fingerprint and size validation at backend open.
**Normalization:** every text comparison funnels through `text_normalization.py` (`normalize_text`, `match_key`, `flatten_text`, `search_terms`) — the single source of matching truth.
**Authentication:** not applicable; the agent is headless, local, and credential-free by design.

---

*Architecture analysis: 2026-08-29*
