# Deterministic Offline Shopping Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic CPU-only Track 4 agent that maintains typed shopping intent, retrieves and ranks ten products every turn, asks information-gain questions, explores one-at-a-time constraint relaxations, and records actionable diagnostics.

**Architecture:** Keep `starter.agent.Agent` as the organizer adapter and place domain behavior in focused `starter.shopping_agent` modules. Each turn updates an immutable-style preference ledger, performs strict multi-route retrieval, estimates clarification value, adds bounded counterfactual candidates, validates a ten-product slate, and records typed trace events.

**Tech Stack:** Python 3.13, `uv`, standard-library dataclasses/enums, SQLite FTS5, `unittest`, JSON/JSONL. No network, GPU, JavaScript, hosted model, or third-party runtime dependency.

---

## Scope boundary

This plan implements the complete deterministic core in design sections 1–8 and 10–18. The embedding-based `FeatureConceptIndex` from section 9 is a separately gated enhancement because it introduces model artifacts and third-party dependencies. It receives its own plan only if deterministic diagnostics show a material feature-normalization recall gap.

## File map

- `pyproject.toml`: uv project metadata and Python requirement.
- `starter/agent.py`: organizer-contract adapter only.
- `starter/shopping_agent/models.py`: enums and fixed-field dataclasses shared across components.
- `starter/shopping_agent/text_normalization.py`: deterministic text and value normalization.
- `starter/shopping_agent/catalog_index.py`: immutable product records, vocabularies, metadata indexes, and FTS5.
- `starter/shopping_agent/constraint_extractor.py`: dialogue-act and constraint parsing into typed updates.
- `starter/shopping_agent/preference_ledger.py`: transactional intent state and supersession.
- `starter/shopping_agent/retrieval.py`: strict, expanded, fallback, and leave-one-out plans and candidate generation.
- `starter/shopping_agent/ranking.py`: eligibility, reciprocal-rank fusion, scoring, slate rotation, and filling.
- `starter/shopping_agent/clarification.py`: entropy, information gain, and question policy.
- `starter/shopping_agent/response.py`: response validation and customer-facing wording.
- `starter/shopping_agent/diagnostics.py`: typed trace events and optional JSONL output.
- `starter/shopping_agent/coordinator.py`: one-way per-turn orchestration.
- `experiments/run_public.py`: reusable public evaluation and run-artifact writer.
- `experiments/RUNS.md`: retained-run summary, constraints, and lessons.
- `tests/fixtures.py`: reusable temporary catalogs and profiles.
- `tests/test_models.py`: domain invariant tests.
- `tests/test_catalog_index.py`: catalog and route-query tests.
- `tests/test_constraint_extractor.py`: parsing and negation cases.
- `tests/test_preference_ledger.py`: update, decline, removal, and override cases.
- `tests/test_retrieval_ranking.py`: route fusion, filtering, ranking, exploration, and slate tests.
- `tests/test_clarification.py`: entropy and policy tests.
- `tests/test_agent.py`: contract and multi-turn integration tests.
- `tests/test_diagnostics.py`: artifact and no-op behavior tests.

## Core signatures

The tasks preserve these public boundaries:

```python
class ConstraintExtractor:
    def __init__(self, catalog_index: CatalogIndex) -> None: ...
    def extract(
        self,
        message: str,
        turn: int,
        asked_attribute: Attribute | None,
    ) -> tuple[PreferenceUpdate, ...]: ...


class PreferenceLedger:
    @property
    def intent(self) -> ShoppingIntent: ...
    def apply(self, updates: tuple[PreferenceUpdate, ...]) -> ShoppingIntent: ...


class RetrievalPlanner:
    def strict(self, intent: ShoppingIntent) -> tuple[RetrievalPlan, ...]: ...
    def counterfactuals(self, intent: ShoppingIntent) -> tuple[RetrievalPlan, ...]: ...


class CandidateGenerator:
    def execute(self, plan: RetrievalPlan) -> tuple[ProductCandidate, ...]: ...


class EligibilityGate:
    def evaluate(
        self,
        product: ProductRecord,
        constraints: tuple[PreferenceConstraint, ...],
    ) -> EligibilityDecision: ...


class ProductRanker:
    def rank(
        self,
        candidates: tuple[ProductCandidate, ...],
        intent: ShoppingIntent,
        shown_product_ids: frozenset[str],
        top_k: int,
    ) -> tuple[RankedRecommendation, ...]: ...


class QuestionValueEstimator:
    def score_candidates(
        self,
        products: tuple[ProductRecord, ...],
        weights: tuple[float, ...],
        intent: ShoppingIntent,
    ) -> tuple[QuestionCandidate, ...]: ...


class ClarificationPolicy:
    def choose(
        self,
        candidates: tuple[QuestionCandidate, ...],
        intent: ShoppingIntent,
        turn: int,
    ) -> ClarificationDecision | None: ...


class TurnCoordinator:
    def reset(self, session_id: str, profile: UserProfile) -> None: ...
    def respond(self, session_id: str, message: str, turn: int, top_k: int) -> TurnResponse: ...
```

The response invariant is exactly ten valid unique product identifiers when `top_k` is 10 and the catalog contains enough products. The offline fallback follows the same contract without semantic artifacts or credentials.

### Task 1: Establish the uv project and typed domain boundary

**Files:**
- Create: `pyproject.toml`
- Create: `starter/shopping_agent/__init__.py`
- Create: `starter/shopping_agent/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing model-invariant tests**

```python
from starter.shopping_agent.models import Attribute, PreferenceConstraint, Strength


def test_hard_constraint_requires_high_confidence(self) -> None:
    constraint = PreferenceConstraint(
        constraint_id="c1",
        attribute=Attribute.MATERIAL,
        value="leather",
        excluded=False,
        strength=Strength.HARD,
        confidence=0.89,
        source_turn=1,
        source_text="must be leather",
    )
    with self.assertRaises(ValueError):
        constraint.validate()
```

- [ ] **Step 2: Run the test and verify the missing module failure**

Run: `uv run python -m unittest tests.test_models -v`
Expected: FAIL with `ModuleNotFoundError: starter.shopping_agent`.

- [ ] **Step 3: Add project metadata and explicit domain types**

```toml
[project]
name = "techjam-track4-agent"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []
```

Define `Attribute`, `Strength`, `UpdateAction`, `RetrievalRoute`, `UserProfile`, `ProductRecord`, `PreferenceConstraint`, `PreferenceUpdate`, `ShoppingIntent`, `RouteEvidence`, `RetrievalPlan`, `ProductCandidate`, `EligibilityDecision`, `QuestionCandidate`, `ClarificationDecision`, `RankedRecommendation`, and `TurnResponse`. Each dataclass uses fixed fields and tuple collections. Constraints have stable `constraint_id` values. `PreferenceConstraint.validate()` rejects hard confidence below `0.90` and confidence outside `[0, 1]`.

- [ ] **Step 4: Run model and organizer tests**

Run: `uv run python -m unittest tests.test_models tests.test_evaluator -v`
Expected: all tests pass.

- [ ] **Step 5: Commit the domain boundary**

```powershell
git add pyproject.toml starter/shopping_agent tests/test_models.py
git commit -m "feat: define shopping agent domain model"
```

### Task 2: Build normalized catalog indexes

**Files:**
- Create: `starter/shopping_agent/text_normalization.py`
- Create: `starter/shopping_agent/catalog_index.py`
- Create: `tests/fixtures.py`
- Create: `tests/test_catalog_index.py`

- [ ] **Step 1: Write tests for normalization, product loading, fallback order, and FTS search**

```python
def test_catalog_search_prefers_title_then_features(self) -> None:
    index = CatalogIndex.from_path(write_catalog(self.temp_path, sample_products()))
    rows = index.search_fts(("winter", "boot"), limit=10)
    self.assertEqual(rows[0].parent_asin, "BOOT-1")
    self.assertEqual(len(index.quality_fallback(category="boots", limit=10)), 10)
```

- [ ] **Step 2: Verify the tests fail because `CatalogIndex` is absent**

Run: `uv run python -m unittest tests.test_catalog_index -v`
Expected: FAIL importing `starter.shopping_agent.catalog_index`.

- [ ] **Step 3: Implement normalized records and indexes**

`CatalogIndex.from_path()` must validate `parent_asin`, normalize title/categories/features/details/store/description, preserve price/rating fields, build category/material/color/brand token indexes, create the weighted FTS5 table, and compute a stable catalog fingerprint. `search_fts()` returns identifiers plus rank positions; `quality_fallback()` sorts by Wilson-style rating confidence, rating count, and stable identifier tie-break.

- [ ] **Step 4: Run focused and full tests**

Run: `uv run python -m unittest tests.test_catalog_index tests.test_evaluator -v`
Expected: all tests pass.

- [ ] **Step 5: Commit catalog indexing**

```powershell
git add starter/shopping_agent/text_normalization.py starter/shopping_agent/catalog_index.py tests/fixtures.py tests/test_catalog_index.py
git commit -m "feat: add normalized catalog indexes"
```

### Task 3: Extract constraints and maintain the preference ledger

**Files:**
- Create: `starter/shopping_agent/constraint_extractor.py`
- Create: `starter/shopping_agent/preference_ledger.py`
- Create: `tests/test_constraint_extractor.py`
- Create: `tests/test_preference_ledger.py`

- [ ] **Step 1: Write golden parsing tests**

```python
def test_negation_and_override_are_distinct_updates(self) -> None:
    updates = extractor.extract("Actually ignore leather; I need canvas", turn=3, asked_attribute=None)
    self.assertEqual([(u.action, u.value) for u in updates], [
        (UpdateAction.REMOVE, "leather"),
        (UpdateAction.SET, "canvas"),
    ])
    self.assertTrue(all(u.attribute is Attribute.MATERIAL for u in updates))
```

Cover explicit `must`, `prefer`, `not`, price bounds, short answers resolved from `asked_attribute`, and boundary replies such as “no preference.”

- [ ] **Step 2: Verify both suites fail on missing components**

Run: `uv run python -m unittest tests.test_constraint_extractor tests.test_preference_ledger -v`
Expected: import failures for the two modules.

- [ ] **Step 3: Implement deterministic extraction**

Use anchored regexes plus catalog vocabularies. Emit confidence `0.98` for explicit contextual answers and exclusions, `0.92` for exact catalog values with hard cues, `0.80` for exact values without hard cues, and `0.55` for ungrounded residual concepts. Negation scope stops at punctuation and coordinating contrast words.

- [ ] **Step 4: Implement transactional ledger updates**

`PreferenceLedger.apply(updates)` returns a new `ShoppingIntent`. `SET` supersedes active values for scalar attributes after override language, `ADD` preserves compatible multi-values, `REMOVE` deactivates matching values, and `DECLINE` records the attribute so it is not asked again. Increment `intent_version` only when active intent changes.

- [ ] **Step 5: Run parsing, ledger, and organizer tests**

Run: `uv run python -m unittest tests.test_constraint_extractor tests.test_preference_ledger tests.test_evaluator -v`
Expected: all tests pass.

- [ ] **Step 6: Commit conversational intent**

```powershell
git add starter/shopping_agent/constraint_extractor.py starter/shopping_agent/preference_ledger.py tests/test_constraint_extractor.py tests/test_preference_ledger.py
git commit -m "feat: track structured shopping intent"
```

### Task 4: Deliver the first end-to-end strict retrieval slice

**Files:**
- Create: `starter/shopping_agent/retrieval.py`
- Create: `starter/shopping_agent/ranking.py`
- Create: `starter/shopping_agent/response.py`
- Create: `starter/shopping_agent/coordinator.py`
- Modify: `starter/agent.py`
- Create: `tests/test_retrieval_ranking.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write an integration test that accumulates intent and always returns ten products**

```python
def test_agent_recommends_while_accumulating_constraint_answers(self) -> None:
    agent = Agent(catalog_path=self.catalog_path)
    agent.reset("s1", PROFILE)
    first = agent.respond("s1", "I need boots", 1, 10)
    second = agent.respond("s1", "black leather", 2, 10)
    self.assertEqual(len(first["recommendations"]), 10)
    self.assertEqual(len(second["recommendations"]), 10)
    self.assertTrue(all(is_black_leather(item["parent_asin"]) for item in second["recommendations"][:5]))
```

- [ ] **Step 2: Verify the integration test fails against the stateless baseline**

Run: `uv run python -m unittest tests.test_agent -v`
Expected: FAIL because the current agent does not accumulate or fill results.

- [ ] **Step 3: Implement strict retrieval and eligibility**

`RetrievalPlanner.strict(intent)` creates metadata, exact-FTS, expanded-FTS, and category-fallback route specifications. `CandidateGenerator.execute(plan)` returns route-ranked candidates. `EligibilityGate.evaluate(product, constraints)` rejects only active hard constraints and returns fixed rejection reasons.

- [ ] **Step 4: Implement fusion, validation, and coordination**

Use weighted reciprocal-rank fusion `sum(route_weight / (60 + rank))`. Rank strict eligible candidates first, then fill unused positions from progressively broader valid candidates. `ResponseValidator` deduplicates, validates against `CatalogIndex`, and truncates to `top_k`. Replace `starter.agent.Agent` internals with adapter delegation while preserving its public signatures.

- [ ] **Step 5: Run focused and full unit tests**

Run: `uv run python -m unittest tests.test_retrieval_ranking tests.test_agent tests.test_evaluator -v`
Expected: all tests pass.

- [ ] **Step 6: Run the public evaluator and record the strict result**

Run: `uv run python -m evaluator.local_evaluator`
Expected: valid metrics for all 200 sessions and no exceptions. Record runtime and metrics before proceeding.

- [ ] **Step 7: Commit the end-to-end slice**

```powershell
git add starter/agent.py starter/shopping_agent/retrieval.py starter/shopping_agent/ranking.py starter/shopping_agent/response.py starter/shopping_agent/coordinator.py tests/test_retrieval_ranking.py tests/test_agent.py
git commit -m "feat: add strict multi-route shopping search"
```

### Task 5: Add slate history and stable controlled diversity

**Files:**
- Modify: `starter/shopping_agent/models.py`
- Modify: `starter/shopping_agent/ranking.py`
- Modify: `starter/shopping_agent/coordinator.py`
- Modify: `tests/test_retrieval_ranking.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write failing rotation and override-reset tests**

```python
def test_failed_slate_rotates_but_override_resets_suppression(self) -> None:
    first_ids = recommend_turn("red shoes", turn=1)
    second_ids = recommend_turn("show me others", turn=2)
    self.assertFalse(set(first_ids) & set(second_ids))
    override_ids = recommend_turn("Actually I need red shoes", turn=3, override=True)
    self.assertTrue(set(first_ids) & set(override_ids))
```

- [ ] **Step 2: Verify the tests fail because recommendations repeat**

Run: `uv run python -m unittest tests.test_retrieval_ranking tests.test_agent -v`
Expected: FAIL on slate overlap and override reset.

- [ ] **Step 3: Implement `RecommendationHistory`**

Store shown identifiers keyed by `intent_version`. Deprioritize shown products behind unseen products, permit reuse only when fewer than `top_k` credible unseen products remain, and discard old suppression when override processing increments the intent version.

- [ ] **Step 4: Run tests and public evaluation**

Run: `uv run python -m unittest -v`
Expected: all tests pass.
Run: `uv run python -m evaluator.local_evaluator`
Expected: record paired overall and scenario changes; revert or adjust rotation if TechnicalScore regresses materially.

- [ ] **Step 5: Commit slate rotation**

```powershell
git add starter/shopping_agent/models.py starter/shopping_agent/ranking.py starter/shopping_agent/coordinator.py tests/test_retrieval_ranking.py tests/test_agent.py
git commit -m "feat: rotate failed recommendation slates"
```

### Task 6: Ask questions by expected information gain

**Files:**
- Create: `starter/shopping_agent/clarification.py`
- Modify: `starter/shopping_agent/coordinator.py`
- Create: `tests/test_clarification.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write failing entropy and policy tests**

```python
def test_balanced_attribute_has_more_information_than_skewed_attribute(self) -> None:
    balanced = estimator.score(Attribute.COLOR, weighted_values=(("red", .25), ("blue", .25), ("red", .25), ("blue", .25)))
    skewed = estimator.score(Attribute.MATERIAL, weighted_values=(("cotton", .25), ("cotton", .25), ("cotton", .25), ("linen", .25)))
    self.assertGreater(balanced.information_gain, skewed.information_gain)

def test_agent_recommends_ten_products_while_asking(self) -> None:
    response = respond_to_broad_request()
    self.assertEqual(len(response["recommendations"]), 10)
    self.assertIn(response["ask_attribute"], ALLOWED_ATTRIBUTES)
```

- [ ] **Step 2: Verify the clarification suite fails**

Run: `uv run python -m unittest tests.test_clarification tests.test_agent -v`
Expected: FAIL importing `clarification` or because no question is selected.

- [ ] **Step 3: Implement entropy and question scoring**

Normalize positive preliminary fusion scores to probabilities. Calculate entropy as `-sum(p * log2(p))`, conditional entropy from canonical attribute buckets including `unknown`, and effective possibilities as `2 ** entropy`. Score each attribute as `information_gain * answerability * coverage * relevance - turn_cost`.

- [ ] **Step 4: Implement the policy gate**

Reject answered, declined, repeated, irrelevant, and unavailable attributes. Ask only when the best score exceeds the configured threshold and `turn < 10`. Generate a focused natural-language prompt and retain the structured allowed attribute.

- [ ] **Step 5: Run tests and evaluator**

Run: `uv run python -m unittest -v`
Expected: all tests pass.
Run: `uv run python -m evaluator.local_evaluator`
Expected: record predicted information gain, first-hit turns, and scenario metrics.

- [ ] **Step 6: Commit information-gain questions**

```powershell
git add starter/shopping_agent/clarification.py starter/shopping_agent/coordinator.py tests/test_clarification.py tests/test_agent.py
git commit -m "feat: select clarifications by information gain"
```

### Task 7: Add one-at-a-time counterfactual exploration

**Files:**
- Modify: `starter/shopping_agent/retrieval.py`
- Modify: `starter/shopping_agent/ranking.py`
- Modify: `starter/shopping_agent/response.py`
- Modify: `starter/shopping_agent/coordinator.py`
- Modify: `tests/test_retrieval_ranking.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write failing leave-one-out tests**

```python
def test_counterfactual_plan_relaxes_exactly_one_unreliable_constraint(self) -> None:
    plans = planner.counterfactuals(intent_with_material_and_color())
    self.assertTrue(plans)
    self.assertTrue(all(len(plan.relaxed_constraint_ids) == 1 for plan in plans))
    self.assertNotIn(explicit_exclusion_id(), [p.relaxed_constraint_ids[0] for p in plans])
```

- [ ] **Step 2: Verify exploration tests fail**

Run: `uv run python -m unittest tests.test_retrieval_ranking tests.test_agent -v`
Expected: FAIL because no counterfactual plans or provenance exist.

- [ ] **Step 3: Implement constraint reliability and plan generation**

Rank relaxations by lower extraction confidence, inferred source, weak catalog coverage, strict-pool collapse, lack of confirmation, and recovered candidate count. Generate one plan per eligible constraint and retain `relaxed_constraint_id` on every resulting candidate.

- [ ] **Step 4: Implement dynamic slate allocation and disclosure**

Start with seven strict and three exploratory slots. Use all strict slots when strict confidence and diversity are high; expand exploration when the strict pool is sparse. Never place an exploratory candidate ahead of a stronger strict match. If an explicit hard constraint is crossed as an empty-pool last resort, name that requirement in the customer message.

- [ ] **Step 5: Run all tests and the public evaluator**

Run: `uv run python -m unittest -v`
Expected: all tests pass.
Run: `uv run python -m evaluator.local_evaluator`
Expected: compare strict-only and counterfactual HitRate, MRR, and MTTC before retaining the feature.

- [ ] **Step 6: Commit exploration**

```powershell
git add starter/shopping_agent/retrieval.py starter/shopping_agent/ranking.py starter/shopping_agent/response.py starter/shopping_agent/coordinator.py tests/test_retrieval_ranking.py tests/test_agent.py
git commit -m "feat: explore constraint counterfactuals"
```

### Task 8: Add typed diagnostics and reproducible experiment runs

**Files:**
- Create: `starter/shopping_agent/diagnostics.py`
- Modify: `starter/shopping_agent/coordinator.py`
- Create: `experiments/run_public.py`
- Create: `experiments/RUNS.md`
- Create: `tests/test_diagnostics.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing no-op and JSONL trace tests**

```python
def test_noop_trace_does_not_create_files(self) -> None:
    NoOpEvaluationTrace().record(route_event())
    self.assertEqual(list(self.output_path.iterdir()), [])

def test_jsonl_trace_uses_fixed_reason_fields(self) -> None:
    trace.record(route_event(reason=TraceReason.EMPTY_STRICT_POOL))
    payload = json.loads(self.trace_path.read_text(encoding="utf-8").splitlines()[0])
    self.assertEqual(payload["reason"], "empty_strict_pool")
```

- [ ] **Step 2: Verify diagnostics tests fail**

Run: `uv run python -m unittest tests.test_diagnostics -v`
Expected: FAIL importing `starter.shopping_agent.diagnostics`.

- [ ] **Step 3: Implement typed trace sinks**

Define fixed `TraceEventType`, `TraceReason`, and event dataclasses. `NoOpEvaluationTrace` returns immediately. `JsonlEvaluationTrace` writes per-session route, filtering, question, slate, latency, and fallback events without exposing mutable arbitrary payloads to domain components.

- [ ] **Step 4: Implement the reusable public experiment command**

`experiments/run_public.py` accepts `--run-id`, runs the unchanged evaluator, writes `summary.json`, `sessions.jsonl`, `failures.jsonl`, `retrieval_routes.jsonl`, and `ablation.md`, and refuses to overwrite an existing run directory. Update `experiments/RUNS.md` with the retained baseline and each accepted experiment.

- [ ] **Step 5: Run diagnostics and evaluator tests**

Run: `uv run python -m unittest -v`
Expected: all tests pass.
Run: `uv run python -m experiments.run_public --run-id deterministic-v1`
Expected: five documented artifacts and metrics for 200 sessions.

- [ ] **Step 6: Commit observability**

```powershell
git add .gitignore starter/shopping_agent/diagnostics.py starter/shopping_agent/coordinator.py experiments tests/test_diagnostics.py
git commit -m "feat: record deterministic evaluation traces"
```

### Task 9: Final deterministic-core verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `LOCAL_ENVIRONMENT.md`
- Modify: `experiments/RUNS.md`

- [ ] **Step 1: Run the complete unit suite from the uv environment**

Run: `uv run python -m unittest -v`
Expected: zero failures and zero errors.

- [ ] **Step 2: Verify determinism**

Run the public experiment twice with distinct run IDs and compare canonicalized `summary.json` and session recommendations.
Expected: identical recommendations and metrics; only run identifiers and measured timing may differ.

- [ ] **Step 3: Verify offline fallback behavior**

Run the complete evaluator with semantic configuration absent and no credentials in the environment.
Expected: 200 sessions complete without network calls, exceptions, malformed outputs, or fewer than ten recommendations where the catalog has enough products.

- [ ] **Step 4: Compare against the frozen baseline**

Expected baseline: HitRate@10 `0.125`, MRR `0.068034`, MTTC `9.81`, TechnicalScore `0.10671`. Retain the deterministic core only if the overall score improves or a measured scenario trade-off has an explicit documented rationale.

- [ ] **Step 5: Update setup, architecture, limitations, runtime, and one multi-turn example**

Document `uv sync`, the evaluator command, offline behavior, artifact layout, exact retained metrics, known failure modes, and the demonstrated conversation. Do not claim semantic retrieval or clustering is implemented.

- [ ] **Step 6: Run final diff and contract checks**

Run: `git diff --check`
Expected: no output.
Run: `uv run python -m unittest -v`
Expected: zero failures and zero errors.
Run: `uv run python -m evaluator.local_evaluator`
Expected: valid overall and per-scenario metrics.

- [ ] **Step 7: Commit deterministic-core documentation**

```powershell
git add README.md LOCAL_ENVIRONMENT.md experiments/RUNS.md
git commit -m "docs: document deterministic shopping agent"
```

## Exit gate for semantic enhancement

Create a separate semantic-enhancement plan only when retained diagnostics show that feature paraphrases are absent from strict and expanded lexical candidate pools often enough to justify the added model size, startup time, memory, and packaging risk. That plan must benchmark the approved category-local cosine-thresholded clustering against deterministic aliases and must preserve the dependency-free fallback.
