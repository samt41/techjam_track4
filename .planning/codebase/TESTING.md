# Testing Patterns

**Analysis Date:** 2026-08-29

Validation happens at two levels, and both are required before a change is
kept. The unit suite proves correctness and determinism in seconds against tiny
synthetic catalogs. The evaluator harness proves the change moves — or at least
does not regress — the measured TechnicalScore on all 200 public sessions. A
change with a passing suite but no measured score is not yet validated.

## Test Framework

**Runner:**
- `unittest` from the standard library. There is no pytest, no `conftest.py`,
  no test config file, and no `[tool.*]` section in `pyproject.toml` — the
  project has zero dependencies (`dependencies = []`).
- Discovery is default: `tests/` has an `__init__.py`, modules are `test_*.py`,
  classes subclass `unittest.TestCase`, methods are `test_*`.

**Assertion Library:**
- `unittest.TestCase` assertions only. `assertEqual`, `assertAlmostEqual`,
  `assertGreater`, `assertLessEqual`, `assertIn`, `assertTrue`/`assertFalse`,
  `assertIsNotNone`, `assertRaisesRegex`.

**Run Commands:**
```powershell
uv sync                                                    # create the env
uv run python -m unittest -v                               # run all tests
uv run python -W error::ResourceWarning -m unittest -v     # warning-strict (canonical)
uv run python -m unittest -v tests.test_belief              # one module
uv run python -m unittest -v tests.test_agent.AgentIntegrationTest.test_agent_recommends_ten_products_while_asking
```

The warning-strict form in `LOCAL_ENVIRONMENT.md:94` is the canonical
verification command. `-W error::ResourceWarning` turns an unclosed SQLite
connection or file handle into a test failure, which is how the suite guards
the `Agent.close()` / backend lifecycle.

There is no coverage command, no watch mode, and no CI workflow.

## Test File Organization

**Location:**
- A single flat `tests/` directory at the repository root. Tests are never
  co-located with source.

**Naming:**
- `tests/test_<module>.py` mirroring the module under test. Two files cover a
  collaborating pair: `tests/test_retrieval_ranking.py` covers `retrieval.py`
  and `ranking.py`; `tests/test_experiment_analysis.py` covers
  `experiments/analyze_public.py`.

**Structure:**
```text
tests/
├── __init__.py                     # 1 line, enables package-style discovery
├── fixtures.py                     # shared catalog builders (NOT a test module)
├── test_agent.py                   # 14 end-to-end Agent integration tests
├── test_belief.py                  #  7
├── test_catalog_artifacts.py       # 25
├── test_catalog_index.py           #  5
├── test_clarification.py           #  8
├── test_constraint_extractor.py    # 23
├── test_diagnostics.py             #  6
├── test_evaluator.py               #  3 (evaluator contract, evaluator unmodified)
├── test_experiment_analysis.py     #  9
├── test_models.py                  #  4 (dataclass validate() contracts)
├── test_preference_ledger.py       # 15
├── test_retrieval_ranking.py       # 12
├── test_search_backend.py          # 32 (largest; SQLite/FTS5 backend)
└── test_text_normalization.py      #  4
```

167 tests total, running in a few seconds. Two organizer-only modules,
`tests/test_5core_builder.py` and `tests/test_organizer_pipeline.py`, are
git-ignored and absent from a participant checkout.

## Test Structure

**Suite Organization:**

Module-level constants and factory functions first, then one `TestCase` class,
then the `unittest.main()` guard. Every test module ends with:

```python
if __name__ == "__main__":
    unittest.main()
```

Tests follow arrange / blank line / act / blank line / assert. The act is
usually a single statement and is visually isolated:

```python
def test_agent_returns_ten_strict_products_beyond_lexical_budget(self) -> None:
    catalog_path, artifact_path = self.product_set(
        "excluded-prefix", excluded_prefix_products()
    )
    agent = Agent(catalog_path=catalog_path, artifact_path=artifact_path)
    self.addCleanup(agent.close)
    agent.reset("strict-fill", PROFILE)

    response = agent.respond("strict-fill", "I need boots, but not leather", 1, 10)

    self.assertEqual(len(response["recommendations"]), 10)
    self.assertTrue(all(
        item["parent_asin"].startswith("CANVAS-")
        for item in response["recommendations"]
    ))
```
(`tests/test_agent.py:157-177`)

**Naming:** Test names are full sentences stating the behavioural claim, not
the method called. `test_exclusion_is_never_relaxed_even_with_zero_strict`,
`test_direct_session_evidence_outranks_maximum_profile_prior`,
`test_failed_slate_rotates_but_override_resets_suppression`,
`test_extraction_does_not_compile_patterns_per_catalog_value`. Prefer a name
that would be a defensible line in `docs/STATUS.md`.

**Setup:** `setUp` creates a `tempfile.TemporaryDirectory` and immediately
registers its cleanup, then builds the default fixture artifact:

```python
def setUp(self) -> None:
    self.temporary_directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary_directory.cleanup)
    self.catalog_path, self.artifact_path = build_test_artifacts(
        Path(self.temporary_directory.name), integration_products()
    )
```
(`tests/test_agent.py:119-125`)

**Teardown:** Always `self.addCleanup(...)` registered next to the resource
that needs it — never a `tearDown` method, never a `try/finally`. Every `Agent`
gets `self.addCleanup(agent.close)` on the line after construction. This is
what keeps the suite clean under `-W error::ResourceWarning`.

Tests needing a *different* catalog than the default build their own inside the
same temporary directory via the `product_set` helper
(`tests/test_agent.py:127-134`), so a single `setUp` serves varied scenarios
with no per-class boilerplate.

## Mocking

**Framework:** `unittest.mock`. It is used exactly once in the entire suite.

```python
def test_extraction_does_not_compile_patterns_per_catalog_value(self) -> None:
    with patch(
        "starter.shopping_agent.constraint_extractor.re.compile",
        wraps=__import__("re").compile,
    ) as compile_pattern:
        self.extractor.extract("I need black leather boots", turn=1, asked_attribute=None)

    self.assertLessEqual(compile_pattern.call_count, 5)
```
(`tests/test_constraint_extractor.py:314-325`)

Note the shape: `wraps=` keeps the real behaviour and the patch is used purely
to *count* calls, asserting a performance invariant (per-value regex
compilation once made the evaluator exceed the two-minute window — recorded in
`experiments/RUNS.md`).

**What to Mock:**
- Essentially nothing. Mock only to assert a performance or call-count
  invariant that cannot be observed from the return value, and use `wraps=` so
  real behaviour is preserved.

**What NOT to Mock:**
- The SQLite backend, the artifact builder, the FTS5 index, the filesystem, or
  any collaborator inside `starter/shopping_agent/`. Build a real 12-to-250
  product catalog instead — it is fast and it exercises the real SQL.
- The `Agent` boundary. `tests/test_agent.py` drives the public `reset` /
  `respond` / `close` API end to end against a real artifact.

**Seams instead of mocks.** Where behaviour must vary, the code takes an
injected collaborator or a mode flag, and tests use the real alternative:
- `trace: EvaluationTrace | None` on `Agent` — `tests/test_diagnostics.py`
  passes a real `JsonlEvaluationTrace` writing to a temp path.
- `LexicalMode.AUTO | FTS5 | FALLBACK` on the backend — the no-FTS5 path is
  tested by genuinely building an artifact with
  `build_test_artifacts(..., fts5_enabled=False)`
  (`tests/fixtures.py:96`, used at `tests/test_search_backend.py:512`), not by
  stubbing FTS5 out.
- `_SessionMappingAgent` in `experiments/run_public.py` is a real wrapper, not
  a test double.

## Fixtures and Factories

**Location:** `tests/fixtures.py` holds only what is shared across modules.
Scenario-specific catalogs live as module-level factory functions in the test
file that uses them.

**Shared fixtures** (`tests/fixtures.py`):
- `sample_products()` — 12 boots: two distinctive (leather/black, rubber/brown)
  and ten deliberately generic filler, so a slate of 10 can always be filled.
- `excluded_prefix_products()` — 200 leather + 50 canvas, so an exclusion must
  skip past a large high-ranking prefix to fill ten. This is the recall/exclusion
  stress case.
- `write_catalog(directory, products)` — writes JSONL.
- `build_test_artifacts(directory, products, *, fts5_enabled=True)` — writes the
  catalog and runs the real `CatalogArtifactBuilder`, returning
  `(catalog_path, artifact_path)`.

**Per-module factories** encode the scenario in the parent ASIN prefix and the
index, so assertions can read structure straight off the id:

```python
def abundant_strict_products() -> list[dict[str, object]]:
    products: list[dict[str, object]] = []
    for number in range(1, 25):
        material = "leather" if number <= 12 else "synthetic"
        products.append({
            "parent_asin": f"ABUNDANT-{number:02d}",
            ...
        })
    return products
```
(`tests/test_agent.py:60-76`)

Assertions then read `item["parent_asin"].startswith("CANVAS-")` or
`int(item["parent_asin"].rsplit("-", 1)[1]) <= 12`. Name products so the
expected outcome is legible from the identifier alone; use zero-padded indices
(`f"LEATHER-{number:03d}"`) so lexical ordering matches numeric ordering.

**Unit-level factories** compose keyword-only builders bottom-up —
`product()` → `candidate()` → `belief_candidates()`, plus `_constraint()` →
`_intent()` → `soft_color_intent()` / `hard_material_intent()`
(`tests/test_belief.py:45-153`). Each test names the intent it needs rather
than assembling a `ShoppingIntent` inline.

A shared `PROFILE` constant sits at module level in both `tests/test_agent.py`
(dict form, as the organizer passes it) and `tests/test_belief.py`
(`UserProfile` form).

## Coverage

**Requirements:** None enforced. No `coverage.py`, no threshold, no report.

**View Coverage:** Not configured. Coverage is judged by whether each
behavioural invariant in `README.md` "Design invariants" and each hardcoded
value in `docs/STATUS.md` has a named test asserting it.

## Test Types

**Unit Tests:** One test module per source module, exercising the real
collaborator. `tests/test_belief.py` scores real `BeliefCandidate` tuples;
`tests/test_search_backend.py` (32 tests, the largest) drives real SQLite
queries against a built artifact.

**Integration Tests:** `tests/test_agent.py` — 14 tests through the public
`Agent` API against a real built artifact, covering multi-turn constraint
accumulation, slate rotation, intent override, clarification, decline handling,
strict/relaxed slate policy, and lifecycle errors.

**Contract Tests:** `tests/test_evaluator.py` (3 tests) pins the evaluator's
behaviour without modifying it. `tests/test_models.py` (4 tests) pins the
`validate()` contracts on the frozen dataclasses.

**E2E / measured evaluation:** Not part of `unittest`. It is the evaluator
harness below, run manually.

## Common Patterns

**Configuration override:** Unit tests define an explicit test configuration at
module level rather than depending on the shipped default, so a tuning change
does not silently rewrite unit expectations:

```python
TEST_CONFIG = BeliefConfiguration(
    route_scale=1.0, soft_match_likelihood=0.80, soft_mismatch_likelihood=0.10,
    unknown_likelihood=0.40, feature_likelihood=0.60,
    profile_cap=0.50, quality_cap=0.50, temperature=1.0,
)
```
(`tests/test_belief.py:25-34`)

**Error Testing:** Always `assertRaisesRegex` with a substring of the real
message, never bare `assertRaises`:
```python
with self.assertRaisesRegex(RuntimeError, "reset"):
    agent.respond("missing", "boots", 1, 10)

with self.assertRaisesRegex(ValueError, "strictly eligible"):
    CandidateBeliefModel(TEST_CONFIG).score(...)
```
(`tests/test_agent.py:231`, `tests/test_belief.py:168`)

**Probabilistic / numeric assertions:** Assert the invariant, not the number.
Posteriors are checked to sum to 1.0 with `assertAlmostEqual`, to lie in
`[0, 1]`, and to be *ordered* relative to one another — absolute posterior
values are never hardcoded:
```python
self.assertAlmostEqual(sum(item.posterior for item in beliefs), 1.0)
self.assertGreater(posterior_by_id["BLACK-1"], posterior_by_id["BLUE-1"])
```
Caps are asserted with an epsilon: `assertLessEqual(x, TEST_CONFIG.profile_cap + 1e-9)`.

**Determinism assertions:** Tie-breaking is asserted by feeding candidates in
reverse order and expecting the sorted result
(`test_ties_break_by_product_id`, `tests/test_belief.py:197-204`).

**Set-algebra assertions** for rotation, which reads clearly across turns:
```python
self.assertFalse(first_ids & second_ids)   # rotation excluded the shown slate
self.assertTrue(first_ids & override_ids)  # override reset the suppression
```
(`tests/test_agent.py:260-261`)

**Multi-turn tests** drive `agent.respond(session, message, turn, 10)` with an
incrementing `turn`, then assert on the accumulated `agent.turn_history(...)`.

**Async Testing:** Not applicable. The codebase is entirely synchronous.

## The Evaluator / Scoring Harness

Two commands score the agent. Both require the real 50,000-product catalog and
a prebuilt artifact.

**Prerequisites (one time):**
```powershell
# data/catalog.jsonl, decompressed from the participant-kit release
#   sha256 da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67
#   50,000 non-empty rows, 60,546,327 bytes
uv run python -m starter.shopping_agent.build_catalog_artifacts `
  --catalog data/catalog.jsonl --output data/catalog.artifacts
```
~60-90 s, ~580 MB. The builder refuses to overwrite; delete the directory to
rebuild. The unit suite needs none of this — it builds its own tiny artifacts.

**1. Organizer evaluator — the score of record:**
```powershell
uv run python -m evaluator.local_evaluator
# --catalog data/catalog.jsonl --dataset data/public_set.jsonl --output results.json
```
Runs all 200 public sessions, ~190 s wall-clock. Writes `results.json`
(git-ignored) and prints the summary minus per-session detail. `TechnicalScore
= 0.50 * HitRate@10 + 0.30 * MRR + 0.20 * efficiency`, where
`efficiency = clamp((11 - MTTC) / 10, 0, 1)`
(`evaluator/local_evaluator.py:278-281`). A session ends on a hit or after turn
10; misses are assigned turn 11 for MTTC. Only exact `parent_asin` equality
counts.

**`evaluator/local_evaluator.py` is never modified.** Results reported against
a changed evaluator or changed labels are meaningless.

**2. Instrumented experiment — the diagnostic run:**
```powershell
uv run python -m experiments.run_public --run-id <id>
# --exploration disabled|tail-only   --lexical-mode auto|fts5|fallback
```
Same evaluation, plus typed traces and miss attribution. It is atomic: all work
happens in a temp directory inside `experiments/`, published with `os.replace`
only on success (`experiments/run_public.py:77`, `135-150`). It refuses to
overwrite an existing `run_id` and validates the id against `_RUN_ID_RE`.

A successful run directory contains exactly five files:

| File | Contents |
| --- | --- |
| `summary.json` | catalog + dataset SHA-256, code revision, belief and question configuration, aggregate and per-scenario metrics, token usage, runtime |
| `sessions.jsonl` | one scored outcome per session, annotated with `first_miss_reason` |
| `failures.jsonl` | typed miss attribution per miss: `MissReason` + implicating constraint id + detail |
| `retrieval_routes.jsonl` | the seven typed trace events per turn |
| `ablation.md` | human-readable summary with a miss-reason count table |

`MissReason` (`experiments/analyze_public.py:8-16`) is the vocabulary for
explaining a failure: `target_rejected`, `target_not_retrieved`,
`target_ranked_below_ten`, `route_failure`, `fallback_exhausted`,
`stale_override_evidence`, `insufficient_target_metadata`, `unknown`. Every
miss must land in one — an unexplained miss is itself a finding.

**Ground-truth isolation.** `_SessionMappingAgent`
(`experiments/run_public.py:31-56`) records `reset` call order to map the
evaluator's random session UUIDs back to sample ids. The join runs only after
`evaluate()` returns. Do not weaken this: labels must never reach the `Agent`.

**Forced-offline verification.** `--lexical-mode fallback` runs the
deterministic TF-IDF postings path with FTS5 disabled. It scored HitRate@10
0.75 / TechnicalScore 0.599 with every miss attributed — this is the standing
proof the agent runs without FTS5 (`experiments/RUNS.md`).

## How a Change Is Validated Before It Is Kept

The workflow, in order. Skipping a step is how an unmeasured regression ships.

1. **Unit suite green, warning-strict.**
   `uv run python -W error::ResourceWarning -m unittest -v` — 167 tests, a few
   seconds. Any new behaviour gets a named test asserting the invariant, not
   the output value.
2. **Full 200-session measured run.** `uv run python -m experiments.run_public
   --run-id <descriptive-id>`. Partial or sampled evaluation is not a result.
   Every row in `experiments/RUNS.md` was measured on the full 200.
3. **Compare against the retained row.** Current retained baseline: HitRate@10
   `0.920`, MRR `0.5245`, MTTC `3.425`, TechnicalScore `0.7688`, with
   per-scenario HitRate@10 boundary `0.90` / browsing `0.95` / buying `0.90` /
   intent_override `0.90`. Check the per-scenario split, not just the
   aggregate — the largest historical gain (intent_override 0.20 → 0.90) was
   invisible in a small aggregate move.
4. **Explain the delta from the traces.** Read `failures.jsonl` and
   `ablation.md`. A gain must be attributable to a mechanism, and every
   remaining miss must carry a `MissReason`. The 0.915 → 0.920 colon-spacing
   fix was justified by tracing one target from rank 154 to rank 1.
5. **Verify determinism for anything touching ordering, iteration, or
   scoring.** Run the full set twice under different run ids and diff, ignoring
   run id, evaluator session UUIDs, and timing. All 200 outcomes including
   first-hit turn, the canonical summary, and every trace event must match
   byte for byte. Wall-clock is explicitly not a comparison axis (two
   identical-output runs measured 796 s and 1690 s).
6. **Record the row in `experiments/RUNS.md`** with the short commit SHA and a
   Decision of `Retained`, `Superseded`, or `Rejected: <reason>`. Log zero-gain
   and negative results too — the file records a popularity tie-break that
   measured no effect and a keyed-feature recovery retained at zero public
   gain for private-set robustness.
7. **Record any new constant in `docs/STATUS.md`** under its honesty tier, and
   update the metrics tables in `README.md` and `LOCAL_ENVIRONMENT.md` if the
   retained numbers moved.

**Rejection criteria.** A change is dropped if it lowers HitRate@10 on the full
set (the real quality prior was ablated 2-by-2 and dropped it by 0.040, so the
component is retained but neutralized to `0.0`), if it breaks byte-level
determinism, if it introduces a runtime dependency or network call, or if its
only gain comes from matching the public simulator's specific phrasing. The
public set is 200 sessions and final scoring is on 800 disjoint private
sessions, so a small public gain bought with evaluator-specific text is a
regression risk, not a win. A measured zero-gain change may still be kept if it
is correctness-motivated — say so explicitly in the Decision column.

---

*Testing analysis: 2026-08-29*
