---
phase: 02-expanded-dataset-paraphrase-probe
plan: 03
subsystem: arena/datasets
tags: [schema, corpus, conformance, D-37, D-45, D-46, MEAS-10, MEAS-11]
requires:
  - arena.evaluator_bridge.materialize_hidden_fields
  - arena/datasets/__init__.py
provides:
  - arena.datasets.schema.SampleRow
  - arena.datasets.schema.IntentCard
  - arena.datasets.schema.Behavior
  - arena.datasets.schema.OverrideBehavior
  - arena.datasets.schema.SampleProfile
  - arena.datasets.schema.CorpusSchemaError
  - arena.datasets.schema.write_corpus
  - arena.datasets.schema.load_corpus
  - arena.datasets.schema.row_from_record
  - arena.datasets.schema.corpus_stem
  - arena.datasets.schema.validate_corpus
  - arena.datasets.schema.assert_authored_branch
  - arena.datasets.schema.scenario_mix
  - arena.datasets.schema.distinct_targets
  - arena.datasets.schema.PAIR_ID_RE
  - arena.datasets.schema.SCENARIO_MIX_TARGET
  - arena.datasets.schema.ARMS
  - arena.datasets.schema.DIFFICULTY_BY_SCENARIO
  - arena.datasets.schema.MAX_CONSTRAINT_LENGTH
  - tests.dataset_fixtures.synthetic_corpus
  - tests.dataset_fixtures.matched_pair
  - tests.dataset_fixtures.three_arm_pair
  - tests.dataset_fixtures.violating_row
  - tests.dataset_fixtures.fake_authoring_response
  - tests.dataset_fixtures.product
  - tests.dataset_fixtures.profile
  - tests.dataset_fixtures.pair_id
  - tests.dataset_fixtures.sample_row
affects:
  - 02-04
  - 02-05
  - 02-06
  - 02-07
  - 02-09
  - 02-11
  - 02-12
tech-stack:
  added: []
  patterns:
    - frozen slotted dataclasses with a raising validate()
    - canonical sort_keys JSONL serialization mirroring arena/store.py
    - keyword-only mandatory argument as a structural guard
    - AST source guard where a behavioural gate is unfalsifiable
key-files:
  created:
    - arena/datasets/schema.py
    - tests/dataset_fixtures.py
    - tests/test_datasets_schema.py
    - tests/test_datasets_conformance.py
  modified: []
decisions:
  - The D-45 cross-corpus refusal lives at the loader, not the id format; PAIR_ID_RE constrains one id's shape and validate_corpus's mandatory corpus_name constrains ownership
  - assert_authored_branch's is-versus-== distinction is guarded at the source by an AST test, because branch 1 returns the row's own objects and the two operators are behaviourally identical on every catalog-free input
  - Cross-check third arms are allocated by the same largest-remainder rule as the corpus itself, so adding them cannot skew the 40/40/15/5 row mix
metrics:
  duration: ~35 min
  completed: 2026-09-01
  tasks: 3
  files: 4
  tests_added: 35
  tests_total: 433
---

# Phase 2 Plan 03: Corpus Schema and D-37 Conformance Summary

Frozen validated corpus row model with a canonical JSONL serializer, plus both
D-37 authored-branch layers — a static validator that refuses a mis-namespaced
corpus at load time and a dynamic identity check that proves the evaluator's
branch 1 fired without opening the catalog.

## What Was Built

**`arena/datasets/schema.py`** (550 lines). Five frozen slotted dataclasses
(`SampleProfile`, `IntentCard`, `OverrideBehavior`, `Behavior`, `SampleRow`),
each with a `validate()` that raises `ValueError` with a lowercase specific
message, and an `as_record()` that emits the shipped six keys plus the four
authored ones. Constants carry their derivation in a comment: `MAX_CONSTRAINT_LENGTH`
is the evaluator's own `_clean_constraint` limit, and the `[2, 10]` override
window is derived from the `turn + 1 == override["turn"]` trigger running inside
`range(1, 11)` after the `turn == MAX_TURNS` break.

`Behavior.as_record()` omits the `override` key entirely when there is no
override, matching `behavior_for`'s bare `{"scenario_type": s}` exactly — an
explicit `"override": null` would be a different dict and would break the D-55
byte-identity comparison plan 02-06 depends on.

`validate_corpus(records, *, corpus_name)` is the D-45 control. It builds and
validates every row, refuses duplicate `sample_id`s, and refuses any row whose
`pair_id` does not carry its own corpus's stem. `corpus_name` is keyword-only
with no default, so the check cannot be skipped by omission at any call site.

`assert_authored_branch(record)` calls `materialize_hidden_fields(record, {})`
through the bridge and asserts the returned card and behavior are the row's own
objects by identity. `products={}` is safe because branch 1 returns before
touching it, which is what keeps the whole sweep catalog-free.

**`tests/dataset_fixtures.py`**. Matched pairs, three-arm pairs, a
scenario-proportioned `synthetic_corpus()`, twelve named violating records and a
recorded `claude -p` envelope whose `result` stays a JSON string (L-14). No
catalog dependency of any kind.

**`tests/test_datasets_schema.py`** (28 tests, 18 `assertRaises`) and
**`tests/test_datasets_conformance.py`** (7 tests).

## Verification Results

| Gate | Result |
|---|---|
| Task 1 schema surface + mandatory keyword-only `corpus_name` | pass |
| `PAIR_ID_RE` accepts 2 well-formed ids, rejects 4 malformed | pass |
| Loader stem gate accepts under `probe.v1`, refuses same rows under `expanded_dev.v1` | pass |
| `uv run python -m unittest tests.test_arena_boundary` | pass (10 tests) |
| Bridge-only import: 1 `from arena.evaluator_bridge`, 0 `from evaluator` | pass |
| All five dataclasses frozen and slotted | pass |
| Six reachable `classify_constraint` buckets covered, `budget` absent | pass |
| Probe paraphrases preserve every control bucket | pass |
| Fixture module is catalog-free (grep) | pass |
| `tests.test_datasets_schema tests.test_datasets_conformance` | pass (35 tests) |
| Full suite | pass, 433 tests in 4.9 s (budget 45 s) |

Row mix over the 45-row default corpus: boundary 2 (target 2.25), browsing 18
(18.0), buying 18 (18.0), intent_override 7 (6.75) — every bucket within one row.

### Gates measured in both directions

Per the phase's standing concern that acceptance gates pass on untouched source,
each load-bearing gate was measured against a deliberately broken implementation
and the break was then reverted:

| Break applied | Expected failure | Observed |
|---|---|---|
| Disable the `pair_id` stem refusal in `validate_corpus` | the two D-45 cases | 2 failures, exactly those cases |
| Change `is not` to `!=` in `assert_authored_branch` | the identity guard | 1 failure, the AST guard only |
| Disable the duplicate `sample_id` refusal | the duplicate case | 1 failure, exactly that case |

## Gates Found One-Sided

Three, reported as requested rather than quietly worked around.

**1. The plan's task-2 verify command cannot run as written.** It builds the
disjointness sets with `{r['pair_id'] for r in rows}` where `rows` are
`SampleRow` instances. A frozen slotted dataclass has no `__getitem__`, so that
subscript raises `TypeError` before any assertion is reached — the command
fails regardless of whether the implementation is correct. Run with `r.pair_id`
instead; every other clause is unchanged and passes.

**2. `grep -c "assertRaises" >= 13` counts text, not negative cases.** My first
implementation routed eight refusals through one shared `_refusal` helper: 18
genuine negative cases, textual count 11, gate red on a correct implementation.
The gate is also satisfiable by 13 vacuous `assertRaises(Exception)` calls that
assert nothing about the message. I inlined the helper — the cases now read
better and the count is 18 — but the metric itself measures formatting.

**3. The `is` versus `==` requirement is behaviourally unfalsifiable
catalog-free.** The plan asks for `assertIs(card, record["intent_card"])` "so a
future refactor to `==` fails here". It does not: branch 1 returns the row's own
objects, so both operators agree on every input reachable without a catalog, and
producing a case where they disagree needs branch 2 to synthesize an equal card
from a real product. Measured — rewriting `assert_authored_branch` to use `!=`
left all behavioural conformance tests green. Closed with an AST guard on the
schema source (`IdentityComparisonGuardTest`), which is itself two-sided: it
fires on a synthetic `==` version and on the live broken one.

## Deviations from Plan

### Auto-fixed / auto-added

**1. [Rule 2 - Missing critical verification] Added `IdentityComparisonGuardTest`**
- **Found during:** Task 3
- **Issue:** the plan's stated protection against an `is` → `==` refactor did not
  actually protect against it (item 3 above), leaving the D-37 identity claim
  guarded by nothing.
- **Fix:** an AST test over `arena/datasets/schema.py` asserting
  `assert_authored_branch` contains an `IsNot` comparison and no `Eq`/`NotEq`,
  plus a negative case proving the detector fires. Follows the existing
  `tests/test_arena_boundary.py` precedent of guarding at the source what cannot
  be guarded at runtime.
- **Files modified:** `tests/test_datasets_conformance.py`
- **Commit:** ad5b5b0

**2. [Rule 2 - Missing critical functionality] `sample_row` refuses `override_turn` on a non-override row**
- **Found during:** Task 2
- **Issue:** the trigger at `local_evaluator.py:259` only runs while
  `override_applied` is False, so an override turn on a buying row is silently
  inert. Accepting it would let a fixture look like it exercised an override.
- **Fix:** raise `ValueError`, mirroring `promote_hits_to_rank_one`'s refusal.
- **Commit:** 6f6427f

### Interpretation calls

- `violating_row("duplicate_sample_id")` returns a record that is **valid alone**.
  A duplicate is a corpus-level property, so the record proves the refusal only
  when passed to `validate_corpus` twice; the test asserts both directions. The
  fixture and the test both state this.
- `scenario_mix` always emits all four scenario names (zero counts included) plus
  any unexpected one observed, so the shape is fixed and an unknown scenario
  cannot be silently dropped.
- `validate_corpus` checks row validity, then the stem, then duplicates. That
  ordering is what makes the `foreign_stem` record diagnostic: it passes every
  per-row check and is refused by the stem comparison alone, which is the whole
  point of the record.

## Known Stubs

None. No placeholder values, no unwired data paths.

## Threat Flags

None. `arena/datasets/schema.py` adds no network endpoint, auth path or file
access beyond reading a corpus JSONL with `json.loads` only. The registered
mitigations T-02-02, T-02-11, T-02-16, T-02-17 and T-02-40 are all implemented
and each has at least one refusal test.

## Notes for Downstream Plans

- Import `corpus_stem()` rather than writing `name.replace(".", "_")`; plan
  02-09's `pair_id_for` is the third call site the function exists for.
- `validate_corpus` will refuse to run without `corpus_name`. Registry and
  generator call sites must thread the owning corpus name through.
- `tests/dataset_fixtures.py` exports `REPOSITORY_ROOT` and `product()` for the
  sibling test modules; `product()` carries all six `SEARCH_FIELDS` keys so
  `searchable_text` behaves as it does on real records.
- Default `synthetic_corpus()` is 20 pairs / 45 rows and requires
  `pair_count >= 6` to cover every constraint bucket.

## Self-Check: PASSED

All four created files exist on disk; all three commits are present in
`git log`. Working tree clean apart from this SUMMARY.
