# Scalable Retrieval and Oversight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace post-retrieval truncation with filtered backend search, correct intent overrides and non-displacing exploration, rank and ask from an auditable Bayesian belief, and produce actionable offline diagnostics without adding a runtime service or third-party dependency.

**Architecture:** Introduce a substitutable `ProductSearchBackend` boundary backed locally by prebuilt SQLite and deterministic lexical artifacts. The coordinator sends hard filters into every route, forms beliefs over a bounded strict ranking population, fills all strict positions before one-at-a-time exploration, and emits fixed typed traces that a ground-truth-aware experiment analyzer interprets after evaluation.

**Tech Stack:** Python 3.13, `uv`, standard-library dataclasses/enums/protocols, SQLite and optional FTS5, `unittest`, JSON/JSONL, deterministic local artifact files. No network, GPU, JavaScript, hosted model, embedding runtime, or third-party Python package.

---

## Scope and measured baselines

This plan implements the approved scalable-retrieval and oversight amendment.
The broad dialogue parser/POS redesign and semantic embeddings remain out of
scope.

Preserve these measured references:

- warning-strict unit suite: 55 passing tests before this revision;
- retained public result: HitRate@10 `0.785`, MRR `0.38656`, MTTC `4.43`,
  TechnicalScore `0.639868`;
- retained Intent Override HitRate@10: `0.20`;
- strict-only exploration ablation: identical outcomes, hit turns, and target
  ranks for all 200 sessions;
- untraced strict-only evaluator runtime on the current machine: `128.9`
  seconds, excluding catalog construction;
- candidate-budget reproduction: 200 excluded high-quality products followed
  by 50 valid products currently returns zero recommendations.

Do not compare traced and untraced runtime measurements. Any greater than 20
percent like-for-like slowdown requires profiling and a documented benefit
before retention.

## File map

- Create `starter/shopping_agent/search_backend.py`: fixed search/filter/facet
  types and the substitutable backend protocol.
- Create `starter/shopping_agent/catalog_artifacts.py`: manifest, atomic
  artifact construction, validation, and loaded artifact access.
- Create `starter/shopping_agent/build_catalog_artifacts.py`: explicit `uv`
  command for building the one current artifact format.
- Create `starter/shopping_agent/local_search_backend.py`: structured filtered
  search, FTS execution, quality fill, facets, and deterministic lexical
  fallback.
- Rewrite `starter/shopping_agent/catalog_index.py` during backend migration: a
  read-only normalized catalog view loaded from validated artifacts; remove
  catalog-build behavior only when all callers migrate in the same task.
- Modify `starter/shopping_agent/models.py`: evidence kinds, preference groups,
  turn records, belief contributions, and bounded session history.
- Modify `starter/shopping_agent/constraint_extractor.py`: evidence-kind and
  preference-group assignment plus generic-override updates.
- Modify `starter/shopping_agent/preference_ledger.py`: retract-provisional
  semantics, concept pruning, and version-scoped question state.
- Rewrite `starter/shopping_agent/retrieval.py`: backend requests, strict route
  execution, reliability-ordered one-at-a-time counterfactual requests.
- Rewrite `starter/shopping_agent/ranking.py`: strict fusion and belief-aware
  stable ordering without a fixed exploratory allocation.
- Create `starter/shopping_agent/belief.py`: calibrated log-belief components,
  normalization, profile cap, and posterior output.
- Rewrite `starter/shopping_agent/clarification.py`: expected conditional
  entropy from the preliminary strict belief population.
- Modify `starter/shopping_agent/coordinator.py`: corrected turn order, bounded
  history, tail-only exploration, and typed diagnostic events.
- Modify `starter/shopping_agent/response.py`: backend-based validation and
  precise relaxed-requirement disclosure.
- Modify `starter/agent.py`: artifact/backend construction while preserving the
  organizer method signatures.
- Rewrite `starter/shopping_agent/diagnostics.py`: fixed interpretation,
  retrieval, constraint, belief, question, slate, and runtime events.
- Create `experiments/analyze_public.py`: post-run session mapping and
  ground-truth-aware miss attribution.
- Modify `experiments/run_public.py`: configuration/revision/resource capture,
  actionable failures, and real ablation text.
- Modify `.gitignore`, `README.md`, `LOCAL_ENVIRONMENT.md`, and
  `experiments/RUNS.md`: artifact commands, retained results, limitations, and
  measured decisions.
- Create `tests/test_search_backend.py`, `tests/test_catalog_artifacts.py`,
  `tests/test_belief.py`, and `tests/test_experiment_analysis.py`.
- Modify existing model, catalog, extractor, ledger, retrieval/ranking,
  clarification, agent, and diagnostic tests.

## Core contracts

The new backend boundary is fixed before implementation:

```python
class ProductSearchBackend(Protocol):
    @property
    def catalog_fingerprint(self) -> str: ...

    def search(self, request: SearchRequest) -> SearchResult: ...

    def facets(self, request: FacetRequest) -> FacetResult: ...

    def get_products(self, parent_asins: tuple[str, ...]) -> tuple[ProductRecord, ...]: ...

    def contains_product(self, parent_asin: str) -> bool: ...

    def close(self) -> None: ...
```

`SearchRequest` contains lexical terms, fixed structured filters, route,
result limit, and deterministic work limit. `SearchResult` contains ordered
hits, an exact total or explicit lower-bound flag, route/fallback reason, work
consumed, and completed-route latency.

The organizer boundary remains:

```python
class Agent:
    def reset(self, session_id: str, user_profile: dict[str, object]) -> None: ...

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict[str, object]: ...
```

The artifact path is derived deterministically from the catalog path unless an
explicit path is passed for tests. Production construction never silently
builds missing artifacts. Test fixtures build artifacts explicitly.

### Task 1: Define the search backend domain contract

**Files:**
- Create: `starter/shopping_agent/search_backend.py`
- Create: `tests/test_search_backend.py`

- [ ] **Step 1: Write the failing fixed-contract tests**

Add tests proving filters and results contain no arbitrary payload dictionary,
hard filters carry their originating constraint, and exact totals cannot be
smaller than the returned hit collection:

```python
def test_search_result_requires_consistent_total_metadata(self) -> None:
    with self.assertRaises(ValueError):
        SearchResult(
            hits=(SearchHit("BOOT-1", 1.0, 1),),
            total_matches=0,
            total_relation=TotalRelation.EXACT,
            route=RetrievalRoute.EXACT_FTS,
            reason=SearchReason.COMPLETED,
            work_consumed=0,
            elapsed_ms=0.0,
        ).validate()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run python -m unittest tests.test_search_backend -v
```

Expected: import failure for the new backend module.

- [ ] **Step 3: Implement the minimal fixed types**

Define `SearchReason`, `TotalRelation`, `StructuredFilter`, `SearchRequest`,
  `SearchHit`, `SearchResult`, `FacetRequest`, `FacetBucket`, `FacetResult`, and
  `ProductSearchBackend`.

Use enums, dataclasses, tuples, and protocols. Add `.validate()` methods for
confidence, positive limits, unique product identifiers, finite scores, and
total-count consistency.

- [ ] **Step 4: Run focused and full model tests and verify GREEN**

```powershell
uv run python -m unittest tests.test_search_backend -v
uv run python -W error::ResourceWarning -m unittest -q
```

Expected: all tests pass with no resource warning.

- [ ] **Step 5: Commit the contracts**

```powershell
git add starter/shopping_agent/search_backend.py tests/test_search_backend.py
git commit -m "feat: define scalable search contract"
```

### Task 2: Build and validate deterministic catalog artifacts

**Files:**
- Create: `starter/shopping_agent/catalog_artifacts.py`
- Create: `starter/shopping_agent/build_catalog_artifacts.py`
- Create: `tests/test_catalog_artifacts.py`
- Modify: `tests/fixtures.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing atomic-build test**

The test builds artifacts from a temporary catalog, loads them, validates the
fingerprint, and proves that a mismatched catalog fails instead of rebuilding:

```python
def test_artifacts_are_atomic_and_catalog_bound(self) -> None:
    catalog_path = write_catalog(self.root, sample_products())
    artifact_path = self.root / "catalog.artifacts"
    manifest = CatalogArtifactBuilder().build(catalog_path, artifact_path)

    loaded = LoadedCatalogArtifacts.open(catalog_path, artifact_path)
    self.addCleanup(loaded.close)
    self.assertEqual(loaded.manifest.catalog_sha256, manifest.catalog_sha256)

    write_catalog(self.root, [*sample_products(), extra_product()])
    with self.assertRaisesRegex(ArtifactValidationError, "fingerprint"):
        LoadedCatalogArtifacts.open(catalog_path, artifact_path)
```

Also test refusal to overwrite an artifact directory and cleanup of a failed
temporary build.

- [ ] **Step 2: Run the artifact tests and verify RED**

```powershell
uv run python -m unittest tests.test_catalog_artifacts -v
```

Expected: missing artifact module.

- [ ] **Step 3: Implement the one current artifact shape**

Build an artifact directory containing `manifest.json` and `catalog.sqlite3`.
The database contains:

```sql
CREATE TABLE products (
    ordinal INTEGER PRIMARY KEY,
    parent_asin TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    categories_json TEXT NOT NULL,
    features_json TEXT NOT NULL,
    description TEXT NOT NULL,
    details_json TEXT NOT NULL,
    store TEXT NOT NULL,
    price REAL,
    average_rating REAL,
    rating_number INTEGER NOT NULL,
    searchable_text TEXT NOT NULL,
    quality_prior REAL NOT NULL
);
CREATE TABLE attributes (
    ordinal INTEGER NOT NULL,
    attribute TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (ordinal, attribute, value)
);
CREATE INDEX attributes_lookup ON attributes(attribute, value, ordinal);
CREATE TABLE lexical_postings (
    term TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    weighted_frequency REAL NOT NULL,
    PRIMARY KEY (term, ordinal)
);
CREATE INDEX lexical_term_lookup ON lexical_postings(term, ordinal);
CREATE TABLE lexical_terms (
    term TEXT PRIMARY KEY,
    document_frequency INTEGER NOT NULL
);
```

Create the FTS5 table when the build environment supports it and record
`fts5_built` in the manifest. Write to a sibling temporary directory, validate
every recorded hash, and rename only after success. Refuse overwrite; rebuilding
requires removing the exact ignored artifact directory explicitly.

Expose a `LoadedCatalogArtifacts` read-only view for the new backend. Leave the
existing `CatalogIndex` and Agent path unchanged in this task so the full suite
stays green. They are replaced together in Task 5; the final implementation has
no legacy catalog-build path.

- [ ] **Step 4: Add the explicit build command**

Implement:

```powershell
uv run python -m starter.shopping_agent.build_catalog_artifacts --catalog data/catalog.jsonl --output data/catalog.artifacts
```

The command prints the catalog hash, row count, artifact sizes, FTS availability,
and elapsed build time. It returns nonzero on validation or overwrite failure.

- [ ] **Step 5: Update fixtures and run focused tests**

Add `build_test_artifacts(directory, products)` so tests never depend on silent
runtime construction.

```powershell
uv run python -m unittest tests.test_catalog_artifacts -v
uv run python -W error::ResourceWarning -m unittest -q
```

Expected: artifact construction, validation, normalization, price handling,
identifier preservation, and resource closure pass, followed by the unchanged
full suite.

- [ ] **Step 6: Build the full local artifact and measure it**

```powershell
uv run python -m starter.shopping_agent.build_catalog_artifacts --catalog data/catalog.jsonl --output data/catalog.artifacts
```

Record build duration and file sizes in the run log. Do not commit generated
artifacts.

- [ ] **Step 7: Commit artifact construction**

```powershell
git add .gitignore starter/shopping_agent/catalog_artifacts.py starter/shopping_agent/build_catalog_artifacts.py tests/fixtures.py tests/test_catalog_artifacts.py
git commit -m "feat: build deterministic catalog artifacts"
```

### Task 3: Implement filtered structured search and guaranteed strict fill

**Files:**
- Create: `starter/shopping_agent/local_search_backend.py`
- Modify: `starter/shopping_agent/search_backend.py`
- Modify: `tests/test_search_backend.py`
- Modify: `tests/fixtures.py`

- [ ] **Step 1: Write the failing excluded-prefix reproduction**

Build 250 products where the 200 highest-quality products are leather and the
remaining 50 are canvas. Search with a hard leather exclusion:

```python
def test_quality_search_finds_valid_products_beyond_old_route_cap(self) -> None:
    backend = self.backend(excluded_prefix_products())
    request = SearchRequest(
        route=RetrievalRoute.CATEGORY_FALLBACK,
        lexical_terms=(),
        filters=(hard_exclusion(Attribute.MATERIAL, "leather"),),
        limit=10,
        work_limit=50_000,
    )
    result = backend.search(request)

    self.assertEqual(len(result.hits), 10)
    self.assertEqual(result.total_matches, 50)
    self.assertTrue(all(hit.parent_asin.startswith("CANVAS-") for hit in result.hits))
```

- [ ] **Step 2: Run the reproduction and verify RED**

```powershell
uv run python -m unittest tests.test_search_backend.LocalSearchBackendTest.test_quality_search_finds_valid_products_beyond_old_route_cap -v
```

Expected: missing local backend.

- [ ] **Step 3: Implement structured filter pushdown**

`LocalProductSearchBackend` compiles filters into parameterized SQL using
`EXISTS`/`NOT EXISTS` for categorical attributes and comparisons for price.
Every query uses the filter clause before `ORDER BY` and `LIMIT`. Never build
SQL from raw values.

Quality search orders by `quality_prior DESC, parent_asin ASC`. Return the exact
strict match count from a matching `COUNT(*)` query. Cache filter-count results
per immutable filter tuple within one turn only.

- [ ] **Step 4: Add intersection, exclusion, range, and facet tests one cycle at a time**

After each test fails, implement only its required branch and rerun it. Cover:

- two positive attribute filters;
- positive plus exclusion;
- upper and lower price bounds;
- unknown price rejection for a hard budget;
- exact total count;
- stable tie order;
- facet counts under the same hard filters.

- [ ] **Step 5: Run backend and catalog tests and verify GREEN**

```powershell
uv run python -m unittest tests.test_search_backend tests.test_catalog_index -v
```

- [ ] **Step 6: Commit filtered search**

```powershell
git add starter/shopping_agent/search_backend.py starter/shopping_agent/local_search_backend.py tests/fixtures.py tests/test_search_backend.py
git commit -m "feat: search within strict eligibility"
```

### Task 4: Add FTS5 and deterministic lexical fallback conformance

**Files:**
- Modify: `starter/shopping_agent/local_search_backend.py`
- Modify: `starter/shopping_agent/search_backend.py`
- Modify: `tests/test_search_backend.py`

- [ ] **Step 1: Write one backend-conformance test used by both lexical modes**

```python
def assert_lexical_contract(self, lexical_mode: LexicalMode) -> None:
    backend = self.backend(sample_products(), lexical_mode=lexical_mode)
    result = backend.search(SearchRequest(
        route=RetrievalRoute.EXACT_FTS,
        lexical_terms=("winter", "boot"),
        filters=(hard_filter(Attribute.MATERIAL, "leather"),),
        limit=10,
        work_limit=10_000,
    ))
    self.assertEqual(result.hits[0].parent_asin, "BOOT-1")
    self.assertTrue(all(self.material(hit.parent_asin) == "leather" for hit in result.hits))
```

Call it from separate FTS5 and forced-fallback tests. Forced fallback is a
public constructor option, not a mock of an internal helper.

- [ ] **Step 2: Run the forced-fallback test and verify RED**

```powershell
uv run python -m unittest tests.test_search_backend.LocalSearchBackendTest.test_fallback_lexical_contract -v
```

- [ ] **Step 3: Implement lexical modes**

Add `LexicalMode.AUTO`, `FTS5`, and `FALLBACK`.

- FTS5 joins the FTS table to structured filters before `LIMIT`.
- Fallback loads only postings for the bounded normalized query terms,
  intersects them with structured eligibility, accumulates deterministic
  TF-IDF-like scores using precomputed document frequencies, and stops at the
  deterministic posting-work limit.
- AUTO uses FTS5 when the manifest and runtime support it; otherwise it records
  `FTS5_UNAVAILABLE` and executes fallback.
- If a route exceeds its work limit, discard the route rather than fusing a
  partial result.

- [ ] **Step 4: Test automatic fallback and identical hard-filter behavior**

Cover an artifact built without FTS5, runtime FTS query failure, empty terms,
unsafe terms, work-budget exhaustion, and stable repeated fallback ordering.

- [ ] **Step 5: Run backend tests warning-strict**

```powershell
uv run python -W error::ResourceWarning -m unittest tests.test_search_backend -v
```

- [ ] **Step 6: Commit lexical fallback**

```powershell
git add starter/shopping_agent/search_backend.py starter/shopping_agent/local_search_backend.py tests/test_search_backend.py
git commit -m "feat: fall back from fts deterministically"
```

### Task 5: Migrate strict retrieval and the Agent to the backend

**Files:**
- Rewrite: `starter/shopping_agent/catalog_index.py`
- Rewrite: `starter/shopping_agent/retrieval.py`
- Rewrite: `starter/shopping_agent/ranking.py`
- Modify: `starter/shopping_agent/coordinator.py:40-278`
- Modify: `starter/shopping_agent/response.py:11-72`
- Modify: `starter/agent.py:12-62`
- Modify: `tests/test_retrieval_ranking.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_catalog_index.py`

- [ ] **Step 1: Write the failing Agent-level ten-strict invariant**

Use the excluded-prefix fixture through the public Agent interface and require
ten canvas products. Build artifacts explicitly and pass their path to Agent.

```python
def test_agent_returns_ten_strict_products_beyond_lexical_budget(self) -> None:
    agent = self.agent_for(excluded_prefix_products())
    agent.reset("strict-fill", PROFILE)
    response = agent.respond("strict-fill", "I need boots, but not leather", 1, 10)
    self.assertEqual(len(response["recommendations"]), 10)
    self.assertTrue(all(item["parent_asin"].startswith("CANVAS-") for item in response["recommendations"]))
```

- [ ] **Step 2: Run the test and verify RED against coordinator wiring**

```powershell
uv run python -m unittest tests.test_agent.AgentIntegrationTest.test_agent_returns_ten_strict_products_beyond_lexical_budget -v
```

- [ ] **Step 3: Replace route execution with backend requests**

`RetrievalPlanner.strict()` converts active hard constraints and exclusions to
one immutable filter tuple shared by metadata, exact lexical, expanded lexical,
and quality requests. `CandidateGenerator` is removed; backend results become
route evidence directly.

`ProductRanker` fuses strict route evidence, rechecks hard eligibility as a
defense, ranks with stable ties, and fills from the backend's filtered quality
route. Remove the fixed exploratory allocation from this strict slice.

Rewrite `CatalogIndex` as the normalized read-only view over
`LoadedCatalogArtifacts`, then migrate every caller in this same task. Remove
the source-catalog parser and in-memory index builder rather than retaining a
compatibility path. `ResponseValidator` uses `contains_product()` and keeps the
public payload unchanged.

`Agent` accepts optional `artifact_path` and `lexical_mode` constructor
arguments while preserving organizer `reset` and `respond` signatures. The
default artifact path is `catalog_path.with_suffix(".artifacts")`, so
`data/catalog.jsonl` resolves to `data/catalog.artifacts`.

- [ ] **Step 4: Update existing fixtures and tests to build artifacts explicitly**

Do not retain a compatibility path that rebuilds from catalog in Agent. Update
every Agent construction in tests to use the artifact fixture.

- [ ] **Step 5: Run retrieval, Agent, evaluator-contract, and full tests**

```powershell
uv run python -m unittest tests.test_catalog_index tests.test_retrieval_ranking tests.test_agent tests.test_evaluator -v
uv run python -W error::ResourceWarning -m unittest -q
```

- [ ] **Step 6: Run a 50,000-product strict-search microbenchmark**

Measure backend startup, filtered count, FTS Top-1,000, and quality-fill latency
using the same queries from the design evidence. Record results before changing
state semantics.

- [ ] **Step 7: Commit the backend migration**

```powershell
git add starter/agent.py starter/shopping_agent/catalog_index.py starter/shopping_agent/retrieval.py starter/shopping_agent/ranking.py starter/shopping_agent/coordinator.py starter/shopping_agent/response.py tests/test_catalog_index.py tests/test_retrieval_ranking.py tests/test_agent.py
git commit -m "feat: retrieve complete strict slates"
```

### Task 6: Implement evidence groups, bounded turn history, and generic overrides

**Files:**
- Modify: `starter/shopping_agent/models.py`
- Modify: `starter/shopping_agent/constraint_extractor.py:60-290`
- Modify: `starter/shopping_agent/preference_ledger.py:24-161`
- Modify: `starter/shopping_agent/coordinator.py`
- Modify: `tests/test_constraint_extractor.py`
- Modify: `tests/test_preference_ledger.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_clarification.py`
- Modify: `tests/test_retrieval_ranking.py`

- [ ] **Step 1: Write the failing different-attribute override test**

First add `EvidenceKind`, `DialogueAct`, `UpdateAction.RETRACT_PROVISIONAL`,
`ConstraintStatus.RETRACTED`, `TurnRecord`, and the required
`evidence_kind`/`preference_group_id` fields. Update existing test constructors
mechanically in the same RED cycle so no default compatibility values enter the
final model.

Allow `PreferenceUpdate.attribute` to be `None` only for
`RETRACT_PROVISIONAL`; validation rejects a missing attribute for every other
action. A retraction update carries no value and names its referent through the
most recent active provisional group in ledger state.

```python
def test_generic_override_retracts_latest_provisional_group_only(self) -> None:
    ledger = PreferenceLedger()
    ledger.apply((
        update(Attribute.CATEGORY, "boots", EvidenceKind.CATEGORY_ANCHOR, "category"),
        update(Attribute.COLOR, "black", EvidenceKind.PROVISIONAL_PREFERENCE, "initial-preference"),
    ))
    intent = ledger.apply((
        retract_provisional(group="override"),
        update(Attribute.MATERIAL, "leather", EvidenceKind.EXPLICIT_REQUIREMENT, "override"),
    ))

    self.assertEqual(
        [(item.attribute, item.value) for item in intent.active_constraints],
        [(Attribute.CATEGORY, "boots"), (Attribute.MATERIAL, "leather")],
    )
    self.assertEqual(intent.constraint_history[1].status, ConstraintStatus.RETRACTED)
```

Also add a public Agent test using the organizer's exact generic-override
sentence.

The test-local `update()` helper constructs a fixed `PreferenceUpdate` with
`SET`, `EQUALS`, soft confidence `0.80`, and the supplied evidence fields;
`retract_provisional()` constructs a `RETRACT_PROVISIONAL` update with no value
and confidence `0.98`.

- [ ] **Step 2: Run the override tests and verify RED**

```powershell
uv run python -m unittest tests.test_preference_ledger tests.test_agent -v
```

- [ ] **Step 3: Assign evidence kinds and preference groups**

Use stable group IDs derived from turn and clause ordinal. Initial catalog
category mentions become `CATEGORY_ANCHOR`; tentative feature/style text becomes
`PROVISIONAL_PREFERENCE`; must/only and override replacements become
`EXPLICIT_REQUIREMENT`; negations become `EXCLUSION`; contextual answers become
`CLARIFICATION_ANSWER`.

The generic override emits a dedicated `RETRACT_PROVISIONAL` update followed by
the replacement update. The ledger retracts only the most recent active
provisional group, prunes its weighted concepts, preserves category anchors and
hard/excluded evidence, advances `intent_version`, and starts new question and
slate scopes.

- [ ] **Step 4: Add bounded typed turn history**

Record at most ten `TurnRecord` values. Each record contains message, dialogue
act, updates, before/after version, question, strict IDs, exploratory IDs, and
relaxed IDs. History survives overrides and resets only with the session.

- [ ] **Step 5: Add edge cases one RED/GREEN cycle at a time**

Cover:

- named same-attribute correction;
- generic override with no provisional referent;
- multiple provisional groups retracting only the latest;
- preserved exclusion and hard requirement;
- removed concept never resurfacing after all active constraints disappear;
- question attribute becoming askable in the new intent version; and
- turn history capped at ten.

- [ ] **Step 6: Run parsing, ledger, Agent, and full tests**

```powershell
uv run python -m unittest tests.test_constraint_extractor tests.test_preference_ledger tests.test_agent -v
uv run python -W error::ResourceWarning -m unittest -q
```

- [ ] **Step 7: Commit corrected state semantics**

```powershell
git add starter/shopping_agent/models.py starter/shopping_agent/constraint_extractor.py starter/shopping_agent/preference_ledger.py starter/shopping_agent/coordinator.py tests/test_models.py tests/test_constraint_extractor.py tests/test_preference_ledger.py tests/test_clarification.py tests/test_retrieval_ranking.py tests/test_agent.py
git commit -m "feat: retract provisional intent on override"
```

### Task 7: Make exploration tail-only and reliability ordered

**Files:**
- Modify: `starter/shopping_agent/retrieval.py`
- Modify: `starter/shopping_agent/ranking.py`
- Modify: `starter/shopping_agent/coordinator.py`
- Modify: `starter/shopping_agent/response.py`
- Modify: `tests/test_retrieval_ranking.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Replace the old seven/three test with a failing non-displacement test**

```python
def test_nine_strict_products_keep_all_nine_positions(self) -> None:
    slate = rank_slate(strict=ranked_strict(9), exploratory=ranked_exploratory(10), top_k=10)
    self.assertEqual(sum(item.exact_match for item in slate), 9)
    self.assertEqual(sum(not item.exact_match for item in slate), 1)
    self.assertTrue(all(item.exact_match for item in slate[:9]))
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
uv run python -m unittest tests.test_retrieval_ranking.RetrievalRankingTest.test_nine_strict_products_keep_all_nine_positions -v
```

- [ ] **Step 3: Implement reliability-ordered tail fill**

Introduce `ConstraintReliability` with explicit fields for confidence,
evidence kind, catalog coverage, pool collapse, confirmation count, and
recovered count. Sort using a stable tuple; record every component.

The coordinator executes counterfactuals only when the backend confirms fewer
than `top_k` strict matches. It keeps every strict result and requests only the
number of missing positions.

- [ ] **Step 4: Add Option B tests**

Cover:

- no counterfactual call with ten strict matches;
- soft/provisional relaxation when one to nine strict matches exist;
- explicit hard constraint protected when any strict match exists;
- explicit hard constraint relaxed only after zero strict and failed uncertain
  relaxations;
- exclusion never relaxed;
- exactly one relaxed constraint per result; and
- customer message naming a hard last-resort relaxation.

- [ ] **Step 5: Run retrieval and integration tests**

```powershell
uv run python -m unittest tests.test_retrieval_ranking tests.test_agent -v
```

- [ ] **Step 6: Commit exploration policy**

```powershell
git add starter/shopping_agent/retrieval.py starter/shopping_agent/ranking.py starter/shopping_agent/coordinator.py starter/shopping_agent/response.py tests/test_retrieval_ranking.py tests/test_agent.py
git commit -m "feat: fill only unused slots with near matches"
```

### Task 8: Add auditable Bayesian candidate belief and profile priors

**Files:**
- Create: `starter/shopping_agent/belief.py`
- Modify: `starter/shopping_agent/models.py`
- Modify: `starter/shopping_agent/ranking.py`
- Modify: `starter/shopping_agent/coordinator.py`
- Create: `tests/test_belief.py`
- Modify: `tests/test_retrieval_ranking.py`

- [ ] **Step 1: Write the failing normalization and hard-boundary tests**

```python
def test_candidate_beliefs_normalize_and_explain_components(self) -> None:
    beliefs = CandidateBeliefModel(TEST_CONFIG).score(
        candidates=belief_candidates(),
        intent=soft_color_intent("black"),
        profile=PROFILE,
    )
    self.assertAlmostEqual(sum(item.posterior for item in beliefs), 1.0)
    self.assertTrue(all(item.contributions for item in beliefs))

def test_belief_model_never_receives_hard_ineligible_product(self) -> None:
    with self.assertRaisesRegex(ValueError, "strictly eligible"):
        CandidateBeliefModel(TEST_CONFIG).score(
            candidates=(hard_ineligible_candidate(),),
            intent=hard_material_intent("leather"),
            profile=PROFILE,
        )
```

- [ ] **Step 2: Run the belief tests and verify RED**

```powershell
uv run python -m unittest tests.test_belief -v
```

- [ ] **Step 3: Implement named belief configuration and stable softmax**

Define `BeliefConfiguration` fields for route scale, soft match likelihood,
soft mismatch likelihood, unknown likelihood, feature likelihood, profile cap,
quality cap, and temperature. Use the initial values only through this config
and serialize them into experiment summaries.

Define `BeliefContribution` with component, raw value, configured weight, and
weighted log contribution. Define `CandidateBelief` with product ID, ordered
contributions, total log belief, posterior, and strict-eligibility assertion.
The scorer accepts only candidates marked strictly eligible.

For each candidate, build typed `BeliefContribution` values, sum them in log
space, subtract the maximum log belief, exponentiate with `math.exp`, normalize,
and tie-break by product ID. Reject non-finite values.

Profile tags and summary terms contribute only when grounded in product text.
Clamp their combined contribution to `profile_cap`. Hard filters are absent
from the belief calculation because the backend and defense gate already
enforced them.

- [ ] **Step 4: Add profile and evidence edge tests**

Cover neutral unknown metadata, matching/mismatching soft evidence, route
agreement, quality prior, profile cap, zero total mass fallback, and stable
ties. Prove direct session evidence outranks the maximum profile prior.

- [ ] **Step 5: Integrate beliefs into strict ranking**

Rank strict candidates by posterior, then stable product ID. Retain raw route
fusion and component values in `RankedRecommendation` for diagnostics but keep
the organizer payload unchanged. Apply recommendation-history rotation as a
selection tier before posterior ordering: unseen strict products rank before
shown strict products within the current intent version, and shown products
return only when the unseen pool cannot fill the slate.

- [ ] **Step 6: Run belief, ranking, Agent, and full tests**

```powershell
uv run python -m unittest tests.test_belief tests.test_retrieval_ranking tests.test_agent -v
uv run python -W error::ResourceWarning -m unittest -q
```

- [ ] **Step 7: Commit candidate belief**

```powershell
git add starter/shopping_agent/belief.py starter/shopping_agent/models.py starter/shopping_agent/ranking.py starter/shopping_agent/coordinator.py tests/test_belief.py tests/test_retrieval_ranking.py
git commit -m "feat: rank with auditable candidate beliefs"
```

### Task 9: Select questions by expected posterior entropy reduction

**Files:**
- Rewrite: `starter/shopping_agent/clarification.py`
- Modify: `starter/shopping_agent/coordinator.py`
- Modify: `starter/shopping_agent/models.py`
- Modify: `tests/test_clarification.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write the failing preliminary-population integration test**

Construct 20 strict candidates whose top ten are all black but whose posterior
population is balanced black/blue. Require the estimator to see two color
possibilities rather than the final black-only slate.

```python
def test_question_uses_preliminary_strict_beliefs_not_final_slate(self) -> None:
    decision = choose_from_beliefs(balanced_twenty_candidates(), final_slate_size=10)
    self.assertIs(decision.attribute, Attribute.COLOR)
    self.assertGreater(decision.expected_information_gain, 0.0)
```

- [ ] **Step 2: Run the clarification tests and verify RED**

```powershell
uv run python -m unittest tests.test_clarification -v
```

- [ ] **Step 3: Implement the explicit response model**

Define `QuestionModelConfiguration` containing per-attribute answerability,
decline probability, response noise, turn cost, and decision threshold.

For each attribute:

- sum posterior mass into canonical value and unknown buckets;
- assign configured decline probability to `no_preference`, whose conditional
  posterior equals the current posterior;
- distribute remaining answer probability across value buckets;
- apply configured response noise when conditioning;
- compute current entropy, probability-weighted conditional entropy, expected
  information gain, coverage, effective possibilities, and final score.

All values enter `QuestionCandidate`; none are hidden local variables that
diagnostics cannot inspect.

- [ ] **Step 4: Move clarification before counterfactual execution**

The coordinator order becomes strict retrieval, strict belief, question
estimation, optional counterfactual tail fill, final slate, response. Asking
still accompanies recommendations.

- [ ] **Step 5: Add analytic and policy tests**

Cover balanced/skewed partitions, unknown mass, nonzero decline probability,
response noise, answered/declined/version-scoped attributes, relevance, turn
cost, final turn, deterministic tie-breaking, and effective possibility count.

- [ ] **Step 6: Run clarification, Agent, and full tests**

```powershell
uv run python -m unittest tests.test_clarification tests.test_agent -v
uv run python -W error::ResourceWarning -m unittest -q
```

- [ ] **Step 7: Commit Bayesian clarification**

```powershell
git add starter/shopping_agent/clarification.py starter/shopping_agent/coordinator.py starter/shopping_agent/models.py tests/test_clarification.py tests/test_agent.py
git commit -m "feat: ask by expected posterior information gain"
```

### Task 10: Expand fixed runtime oversight traces

**Files:**
- Rewrite: `starter/shopping_agent/diagnostics.py`
- Modify: `starter/shopping_agent/coordinator.py`
- Modify: `starter/shopping_agent/retrieval.py`
- Modify: `starter/shopping_agent/belief.py`
- Modify: `starter/shopping_agent/clarification.py`
- Modify: `tests/test_diagnostics.py`

- [ ] **Step 1: Write a failing complete-turn trace test**

Run one Agent turn with JSONL tracing and require exactly typed interpretation,
retrieval, constraint, belief, question, slate, and runtime records. Validate
their fixed key sets and shared session/turn identifiers.

```python
def test_trace_explains_complete_turn_without_arbitrary_payloads(self) -> None:
    events = traced_agent_turn("I need black boots")
    self.assertEqual(
        {event["event_type"] for event in events},
        {"interpretation", "retrieval", "constraint", "belief", "question", "slate", "runtime"},
    )
    self.assertTrue(all("payload" not in event for event in events))
```

- [ ] **Step 2: Run diagnostics tests and verify RED**

```powershell
uv run python -m unittest tests.test_diagnostics -v
```

- [ ] **Step 3: Implement separate fixed-field event dataclasses**

Create the frozen slotted dataclasses `InterpretationTrace`, `RetrievalTrace`,
`ConstraintTrace`, `BeliefTrace`, `QuestionTrace`, `SlateTrace`, and
`RuntimeTrace`, then expose their closed union as `TraceEvent`. Include:

- dialogue act, preference updates, active constraints, and intent version;
- route terms, filters, total/returned matches, work, latency, and reason;
- per-constraint before/after counts and rejected candidate IDs within the
  bounded diagnostic population;
- candidate belief contributions and posterior for the bounded ranking pool;
- current/conditional entropy, answer masses, information gain, and policy
  reason;
- strict/exploratory ordered IDs and relaxed constraint IDs; and
- startup/turn stage latency, process memory, manifest hashes, and artifact
  sizes.

Use `tracemalloc` for portable peak Python allocation. Record process RSS only
when a standard-library platform API is available; otherwise emit the fixed
`rss_unavailable` reason rather than importing a dependency.

Serialize enum values deterministically. Keep `NoOpEvaluationTrace` allocation
minimal and preserve append-failure propagation for explicit traced runs.

- [ ] **Step 4: Add fallback and Option B provenance tests**

Verify FTS fallback reason, work-budget exhaustion, zero strict match, hard
last-resort relaxation, and disclosure all appear in traces without changing
the response.

- [ ] **Step 5: Run diagnostics and full tests**

```powershell
uv run python -m unittest tests.test_diagnostics tests.test_agent -v
uv run python -W error::ResourceWarning -m unittest -q
```

- [ ] **Step 6: Commit runtime oversight**

```powershell
git add starter/shopping_agent/diagnostics.py starter/shopping_agent/coordinator.py starter/shopping_agent/retrieval.py starter/shopping_agent/belief.py starter/shopping_agent/clarification.py tests/test_diagnostics.py
git commit -m "feat: trace shopping decisions end to end"
```

### Task 11: Attribute public misses and write real experiment artifacts

**Files:**
- Create: `experiments/analyze_public.py`
- Modify: `experiments/run_public.py`
- Create: `tests/test_experiment_analysis.py`
- Modify: `tests/test_diagnostics.py`

- [ ] **Step 1: Write failing miss-attribution tests**

Create fixed traces for each reason and assert analyzer output:

```python
def test_analyzer_attributes_target_removed_by_constraint(self) -> None:
    failure = analyze_session(
        sample=target_sample("TARGET"),
        trace=trace_with_constraint_rejection("TARGET", "material-leather"),
        outcome=miss_outcome(),
    )
    self.assertIs(failure.primary_reason, MissReason.TARGET_REJECTED)
    self.assertEqual(failure.constraint_id, "material-leather")
```

Cover target not retrieved, rejected, ranked below ten, stale override evidence,
insufficient target metadata, route failure, and fallback exhaustion.

- [ ] **Step 2: Run analyzer tests and verify RED**

```powershell
uv run python -m unittest tests.test_experiment_analysis -v
```

- [ ] **Step 3: Implement post-run analysis without target leakage**

Wrap the Agent only in the experiment command to record reset-call order and map
random evaluator session IDs back to public sample IDs. Do not modify the
organizer evaluator. Join traces and ground truth only after `evaluate()`
returns.

Define fixed `MissReason` and `FailureAnalysis` types. Use target retrieval,
constraint, belief, and slate trace evidence in priority order. If the target
never entered the bounded pool, re-evaluate only its hard metadata against the
recorded constraint snapshot to distinguish rejection from retrieval miss.

- [ ] **Step 4: Upgrade the five artifacts**

- `summary.json`: metrics, configuration, catalog/artifact hashes, code revision,
  startup/evaluation timing, memory, and artifact sizes.
- `sessions.jsonl`: official outcome plus mapped runtime session and first miss
  reason.
- `failures.jsonl`: fixed `FailureAnalysis` rows rather than bare misses.
- `retrieval_routes.jsonl`: the typed runtime events.
- `ablation.md`: a table comparing named retained configurations and a concise
  per-scenario interpretation.

Continue refusing overwrite and atomically rename the completed run directory.
Add `--exploration {disabled,tail-only}` and
`--lexical-mode {auto,fts5,fallback}` to the experiment command so Task 12
commands are backed by explicit configuration rather than environment state.

- [ ] **Step 5: Test exact artifact shape and analyzer coverage**

Require every synthetic miss to have a nonempty fixed reason, code revision to
be present when Git is available, and a stable `unknown_revision` reason when
it is not.

- [ ] **Step 6: Run experiment and diagnostic tests**

```powershell
uv run python -m unittest tests.test_experiment_analysis tests.test_diagnostics -v
```

- [ ] **Step 7: Commit experiment analysis**

```powershell
git add experiments/analyze_public.py experiments/run_public.py tests/test_experiment_analysis.py tests/test_diagnostics.py
git commit -m "feat: attribute public evaluation failures"
```

### Task 12: Verify offline behavior, measure ablations, and update operations docs

**Files:**
- Modify: `README.md`
- Modify: `LOCAL_ENVIRONMENT.md`
- Modify: `experiments/RUNS.md`

- [ ] **Step 1: Run the complete warning-strict suite**

```powershell
uv run python -W error::ResourceWarning -m unittest -v
```

Expected: zero failures, errors, and resource warnings.

- [ ] **Step 2: Run the public strict-only and tail-exploration ablations**

```powershell
uv run python -m experiments.run_public --run-id scalable-strict --exploration disabled
uv run python -m experiments.run_public --run-id scalable-tail-exploration --exploration tail-only
```

Retain only the better run for the current policy class after comparison. The
comparison must include overall and scenario metrics, changed sessions, hit
turns, target ranks, runtime, and number of exploratory turns.

- [ ] **Step 3: Run the full evaluator through forced lexical fallback**

```powershell
uv run python -m experiments.run_public --run-id scalable-no-fts --lexical-mode fallback
```

Expected: 200 sessions complete with valid deterministic responses, no network
events, and a concrete miss reason for every miss.

- [ ] **Step 4: Verify determinism**

Repeat the retained configuration under a second run ID. Canonicalize only run
identifier, evaluator-generated session UUID, and measured timings. Compare:

- aggregate and scenario metrics;
- all 200 outcomes;
- all structured questions; and
- every ordered recommendation slate.

Expected: exact equality after canonicalization.

- [ ] **Step 5: Apply acceptance gates**

Require:

- TechnicalScore no material regression from `0.639868`;
- Intent Override HitRate@10 greater than `0.20`;
- ten strict recommendations in the excluded-prefix reproduction;
- no strict product displaced by exploration;
- hard relaxation only after zero strict matches;
- all public misses attributed;
- no dependency or network addition; and
- no greater than 20 percent unexplained like-for-like runtime regression.

If a gate fails, stop and diagnose before updating retained documentation.

- [ ] **Step 6: Update operational documentation**

Document:

- `uv sync`;
- artifact build and verification commands;
- evaluator and experiment commands;
- local FTS and fallback behavior;
- backend substitution boundary;
- exact retained metrics and runtime/resource measurements;
- Bayesian belief and clarification in user-facing terms;
- generic override and Option B exploration semantics;
- actionable artifact fields and miss reasons; and
- deferred parser and semantic work.

- [ ] **Step 7: Clean generated runs according to project policy**

Keep only the best run for each meaningful class: retained primary, strict-only
ablation if distinct, and forced-fallback evidence. Summarize them in the run
log; remove redundant generated directories.

- [ ] **Step 8: Run final verification after documentation changes**

```powershell
git diff --check
uv run python -W error::ResourceWarning -m unittest -v
uv run python -m evaluator.local_evaluator
```

Expected: clean diff check, all tests passing, and valid 200-session metrics.

- [ ] **Step 9: Commit final evidence and documentation**

```powershell
git add README.md LOCAL_ENVIRONMENT.md experiments/RUNS.md
git commit -m "docs: document scalable deterministic agent"
```

## Implementation stop conditions

Stop the current task rather than continuing to dependent work when:

- artifact validation is ambiguous or cannot distinguish source mismatch from
  corruption;
- structured filters cannot be applied before candidate limits;
- FTS and fallback disagree on hard eligibility;
- generic override tests cannot preserve category while retracting provisional
  evidence;
- exploration displaces a strict product;
- hard relaxation occurs with any strict match;
- posterior values become non-finite or cannot be explained by typed
  contributions;
- diagnostics require ground truth inside Agent behavior; or
- a measured acceptance gate fails without an understood cause.

Resolve the blocking dependency with focused evidence before advancing to the
next task.
