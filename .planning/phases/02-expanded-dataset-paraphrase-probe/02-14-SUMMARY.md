---
phase: 02-expanded-dataset-paraphrase-probe
plan: 14
subsystem: testing
tags: [control-fidelity, paraphrase-probe, ast-scan, anti-circularity, determinism, mutation-testing]

# Dependency graph
requires:
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-03 SampleRow/IntentCard/Behavior schema, dataset_fixtures product/pair_id/violating_row"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-09 control_card, behavior_for_arm, build_row, override_turn_for_pair, measure_solvability, main"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-02 arena/evaluator_bridge.py materialize_hidden_fields"
provides:
  - "tests/test_datasets_control_fidelity.py: the D-31/D-55 control-vs-fallback byte-identity evidence"
  - "OverrideArmFidelityTest: the honest intent_override assertion, with the D-55 flakiness MEASURED not quoted"
  - "PairPinningTest: D-36 cross-arm turn agreement plus a non-degenerate distribution"
  - "SolvabilityAbsenceTest: a scope-aware AST scan confining retrieval to one (path, function) site"
  - "retrieval_references / refusal_sites: reusable scope-tracking scanners over any module"
affects: [07, 03, 04, 05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Scope-aware AST scanning: confine a symbol by (repository-relative path, enclosing function, name), never by basename or name alone"
    - "Non-vacuity assertions as first-class tests: assert the guard still has something to guard"
    - "Measure the flakiness a decision scopes around, rather than quoting a rate in a comment"
    - "Mutation matrix as the acceptance evidence: 24 defects, every test killed by at least one"

key-files:
  created:
    - tests/test_datasets_control_fidelity.py
  modified: []

key-decisions:
  - "The plan's literal confinement (SearchRequest/LocalProductSearchBackend only in generate.py::measure_solvability) is false against the merged tree; gist.py::main legitimately opens the backend, so the allow-list is per (path, function, name) with the gist exemption pinned as unable to grow a retrieval call"
  - "D-55's '~15% flaky' is the corpus-incidence framing; conditional on an override row the pinned and fallback turns disagree 101 times in 200, which is asserted as strictly inside (0, 1) rather than as a rate"
  - "The override assertion is scoped by EXCLUDING override['turn'] and asserting old_value/new_value/message at full strength, so only the one D-36-licensed difference is tolerated"
  - "Every fixture carries its own non-vacuity guard, because the degenerate-fixture failure hit two other plans this phase"

patterns-established:
  - "Assert a duplicated refusal by SITE, not by count: a count of two is satisfied by two copies in one place"
  - "Prove a negative test is not passing on the wrong branch by asserting the branch's own sentence, never only the exception type"
  - "When a mutation cannot exist in the module under test (an unrepresentable arm-dependent draw), mutate the caller that would consume it"

requirements-completed: [MEAS-10, MEAS-11]

# Metrics
duration: 52min
completed: 2026-09-01
---

# Phase 02 Plan 14: Control-Arm Fidelity and Solvability Absence Summary

**Twenty-eight tests that turn "our control arm is the public path" into evidence by driving the evaluator's own customer simulation over both branches of `materialize_hidden_fields`, and that machine-prove the probe pipeline cannot reach retrieval — every one of them killed by at least one of twenty-four deliberate defects.**

## Performance

- **Duration:** ~52 min
- **Tasks:** 2 of 2
- **Files modified:** 1 (created)
- **Test suite:** 669 → 697, green; the new module runs in 0.10 s and twenty consecutive runs take 4.8 s total
- **`arena/datasets/generate.py` in the final diff:** unchanged

## Accomplishments

- **The D-31 comparison exists and is non-trivial.** For `buying`, `browsing` and `boundary`, over three hand-written products spanning all three shapes `intent_card` actually takes, an authored control row and a bare six-key row are pushed through `materialize_hidden_fields` and then through the evaluator's own `initial_message` / `customer_reply` for eleven turns. The transcripts, the carried `disclosed` set and the carried `boundary_used` flag are all byte-compared.
- **02-09's explicit instruction was followed.** Its executor flagged that its own task-2 gate only grepped function source for names and asked 02-14 to assert behaviour instead. Every claim here is behavioural or scope-aware-structural; the one string-presence assertion (the L-3 refusal) is paired with a behavioural proof that each refusal actually fires, is scoped, and precedes any file open.
- **The D-55 flakiness is measured rather than quoted.** 101 of 200 pairs disagree between the pinned turn and the harness's own fallback draw — see "Measurements" below.
- **Twenty-four mutations, zero survivors.** Every one of the 28 tests is killed by at least one deliberate defect. The matrix is in "Verification Performed".
- **The verification found a live conflict between the plan and the merged tree** and resolved it in the strictly-stronger direction rather than by widening the assertion — see deviation 1.

## Task Commits

1. **Task 1: D-31/D-55 scoped byte identity and D-36 pair pinning** — `78130e6` (test)
2. **Task 2: `SolvabilityAbsenceTest`** — `fee7628` (test)

## Files Created/Modified

- `tests/test_datasets_control_fidelity.py` — created, 876 lines. `ControlArmFidelityTest` (7), `OverrideArmFidelityTest` (3), `PairPinningTest` (5), `SolvabilityAbsenceTest` (13), plus the module-level scanners `retrieval_references`, `refusal_sites`, `_nodes_with_scope` and the `RetrievalReference` record.

## Measurements

**The override-turn disagreement rate, measured on this tree.** D-55 describes an unscoped byte-identity assertion as "~15% flaky". Conditional on an `intent_override` row, the pinned turn (`override_turn_for_pair`, seeded on `pair_id`) and the harness's own fallback draw (`behavior_for` seeded on `f"{sample_id}\0{scenario_type}"`) disagree **101 times in 200 pairs** — a coin flip, not 15%. The two readings reconcile: `intent_override` is 15% of the D-30 scenario mix, so ~15% is the corpus-incidence framing and ~50% is the rate conditional on an override row. Both numbers are recorded in the test's own comment so the next reader does not have to re-derive it. The assertion made is that the rate is strictly inside (0, 1), which is deterministic: a rate of 0 would mean the seeds have been collapsed and the scoping is unnecessary; a rate of 1 would mean they never agree and the weaker assertion is testing nothing.

**The override-turn distribution across 200 pair ids:** 81 threes, 119 fours. Asserted as ≥ 40 each, so a constant function fails (T-02-45).

## Verification Performed

Every test was proven to fire against at least one deliberate defect, applied by a driver that reads the file, writes the mutation, runs the module, and restores the original bytes in a `finally` block. **No mutation survived.**

| # | Mutation | File | Tests turned red |
|---|---|---|---|
| M1 | `control_card` sorts `hard_constraints` | generate.py | byte-identity, card+behavior identity, override card, override behavior |
| M2 | `control_card` re-cleans `soft_preferences` with `.title()` | generate.py | same four |
| M3 | `behavior_for_arm` takes `soft_preferences[0]` not `[-1]` | generate.py | override behavior |
| M4 | `behavior_for_arm` draws the turn from the card (arm-dependent) | generate.py | cross-arm turn agreement |
| M5 | `override_turn_for_pair` returns a constant | generate.py | distribution non-degenerate |
| M6 | `override_turn_for_pair` gains an `arm` parameter | generate.py | signature guard |
| M7 | `_OVERRIDE_TURN_CHOICES = (3, 11)` | generate.py | reachable window, distribution, override card, override behavior |
| M8 | a generator shared across calls | generate.py | reproducible-across-calls, cross-arm agreement |
| M9 | the pinning seed collapses onto the control `sample_id` | generate.py | the flakiness measurement |
| M10 | `violating_row("bare")` keeps the authored fields | dataset_fixtures.py | branch-2 guard, product-read guard, and all four identity tests |
| M11 | `_ASK_SEQUENCE` degenerates to all-`None` | the module itself | disclosure guard, comparison-can-fail guard |
| M12 | a fifth `SCENARIO_TYPES` entry | schema.py | scenario-split completeness |
| M13 | `authoring.py` imports `Agent` | authoring.py | agent-anywhere, permitted-site |
| M14 | `SearchRequest` at module scope in generate.py | generate.py | permitted-site |
| M15 | the permitted site loses its `.search` call | generate.py | confinement-not-vacuous |
| M16 | `gist.py::main` gains a `SearchRequest` | gist.py | gist exemption, permitted-site |
| M17 | the CLI refusal is deleted | generate.py | refusal sites, CLI refusal fires |
| M18 | the function refusal is deleted | generate.py | refusal sites, function refusal fires |
| M19 | the function guard fires for every corpus | generate.py | function refusal scoped |
| M20 | the CLI guard fires for every corpus | generate.py | CLI refusal scoped |
| M21 | `is_probe_corpus` returns `True` always | generate.py | classifier, both scoped tests |
| M22 | the CLI writes a file before the guard | generate.py | "before opening anything", CLI scoped |
| M23 | the scanner detects nothing | the module itself | scanner-fires, scope-separation, confinement-not-vacuous, gist exemption |
| M24 | the scanner detects everything | the module itself | scanner-passes-clean, plus six others |

M10 is the most valuable row: it is the degenerate-fixture failure two other plans shipped this phase, reproduced deliberately. With `violating_row("bare")` carrying the authored fields, both calls take branch 1 and the "byte identity" claim would be a comparison of one object with itself. `test_the_bare_record_really_takes_the_fallback_branch` is what names that, and M10 proves it is load-bearing rather than decorative.

M4 needed a different approach from the rest. The property under test — that an arm-dependent override turn is *not expressible* — cannot be broken inside `override_turn_for_pair`, because the function takes neither an `arm` nor a `sample_id`. The mutation was therefore applied to the caller, `behavior_for_arm`, which does have each arm's own card in hand.

**Restoration.** After every batch, `git status --short` showed only `tests/test_datasets_control_fidelity.py` and `git diff --stat` listed no other file — `generate.py`, `authoring.py`, `gist.py`, `schema.py` and `dataset_fixtures.py` were all restored byte-identically. The driver lives in the gitignored `.scratch/` root and was never staged.

**Acceptance gates, both directions:**

| Gate | Result |
|---|---|
| `unittest tests.test_datasets_control_fidelity -v` | 28 tests, 0.10 s |
| Twenty consecutive runs | all green, 4.8 s total |
| `grep -c "intent_override"` ≥ 2 | 17 |
| `grep -c "D-36"` ≥ 1 | 7 |
| `grep -c "forbidden for the probe corpus"` ≥ 1 | 1 |
| `grep -c "skipUnless\|skipIf\|@unittest.skip"` == 0 | 0 |
| `grep -n "catalog.artifacts\|tests.fixtures"` | no matches |
| `grep -rn "Agent\b" arena/datasets/` | one line, a comment in `schema.py:506` |
| Full suite | 697 tests, green, 6.1 s, warning-strict |

The module opens no database and reads no catalog: every product is a hand-written dict, and the two CLI invocations point every output path plus a deliberately absent catalog at a `TemporaryDirectory`, then assert nothing was written to it.

## Decisions Made

1. **The retrieval confinement is keyed by `(repository-relative path, enclosing function, name)`.** The plan asks for "only in `generate.py` and only inside `measure_solvability`", which is false against the merged tree (deviation 1). Keying on the full path rather than the basename is `tests/test_arena_boundary.py`'s own L-1 lesson: under a basename key a second file elsewhere in the tree would silently inherit the exemption.
2. **`.search`, `SearchRequest` and `RetrievalRoute` are confined more tightly than `LocalProductSearchBackend`.** Opening a backend is not the laundering instrument; asking "is this target retrievable?" is. Only `generate.py::measure_solvability` may do the latter, and a dedicated test pins that `gist.py::main` names `LocalProductSearchBackend` and nothing else.
3. **The `intent_override` behavior comparison excludes exactly one key.** `old_value`, `new_value`, `message` and `scenario_type` are asserted at full strength across the two branches; only `override["turn"]` is exempt. Asserting "the behaviors may differ" would have been untestable, and asserting nothing would have let M3 through.
4. **`initial_message`, `customer_reply` and `coarse_category` are imported from `evaluator.local_evaluator` directly, not through the bridge.** `tests/test_arena_boundary.py` pins the seam at exactly eight exports and refuses a ninth; widening it for a test's convenience is precisely what that guard exists to stop. A test module sits outside the `arena/**` scan, and `tests/test_evaluator.py` already imports the harness directly. `materialize_hidden_fields` does come through the bridge, because it is a bridge name.
5. **`profile_for_target` builds the control row's profile rather than the fixture's `profile()`.** The row that ships is built that way; using the generator's own profile keeps the comparison faithful and costs nothing, since the profile is copied verbatim onto the bare row.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking issue] The plan's literal solvability confinement is false against the merged tree**

- **Found during:** Task 2, before writing the scan.
- **Issue:** The plan specifies that `LocalProductSearchBackend` / `SearchRequest` "appear ONLY in `generate.py` and ONLY inside `measure_solvability`". `arena/datasets/gist.py:400,416` imports and opens `LocalProductSearchBackend` inside `main`. Implemented literally, `SolvabilityAbsenceTest` would have been red on arrival against correct code.
- **Assessment:** `gist.py::main` is the one-off offline vocabulary builder. It opens the backend to read catalog facets through `CatalogIndex`, issues no `SearchRequest` and calls no `.search`, so it cannot express "is this target retrievable?" and therefore cannot filter on it. It is not a defect.
- **Fix:** The allow-list is a set of `(path, function, name)` triples with `("arena/datasets/gist.py", "main", "LocalProductSearchBackend")` as a documented, narrow exemption — and `test_the_gist_exemption_cannot_grow_into_a_retrieval_call` asserts the gist module names that symbol *and no other*, so the exemption cannot widen into a retrieval call. M16 proves that test fires. The net gate is **stronger** than the plan's text, not weaker: the plan constrained two names in one function; this constrains six names plus the `.search` call across four modules, with scope resolution.
- **Files modified:** `tests/test_datasets_control_fidelity.py` only.
- **Committed in:** `fee7628`

### Scope adjustments

- **`RetrievalRoute` was added to the confined set** beyond the plan's two names. It is imported alongside the other two inside `measure_solvability` and is a retrieval type; confining it costs nothing and closes a gap the plan's list left open.
- **Four extra `SolvabilityAbsenceTest` cases beyond the plan's list** — scope separation, confinement non-vacuity, the gist exemption bound, and the corpus classifier. Each closes a way the headline assertion could have passed without measuring anything.
- **Seven `ControlArmFidelityTest` cases where the plan implies two.** The five extra are all non-vacuity guards. Given that the degenerate-fixture failure hit two separate plans this phase, they are the point rather than padding.

---

**Total deviations:** 1 auto-fixed (Rule 3), plus 3 additive scope adjustments.
**Impact on plan:** No scope creep beyond the single file. Nothing outside `tests/test_datasets_control_fidelity.py` was changed.

## Findings to Route (NOT fixed here — `generate.py` is out of this plan's `files_modified`)

**F-1 — `arena/datasets/generate.py` has no dedicated test module, and this one is not it.**
`tests/test_datasets_control_fidelity.py` is now the **only** test file in the repository that imports `arena.datasets.generate`, and it covers six of its twenty public symbols (`control_card`, `behavior_for_arm`, `build_row`, `override_turn_for_pair`, `pair_id_for`, `profile_for_target`, `is_probe_corpus`, `measure_solvability`, `main`). `sample_targets`, `assign_scenarios`, `constraint_slots`, `control_constraints`, `author_arm`, `card_from_constraints`, `divergence_records`, `corpus_plan`, `stratum_for`, `cross_check_pairs` and `public_target_ids` have **no committed regression coverage anywhere**. 02-09 verified all of them at execution time with ad-hoc scripts; none of those proofs was committed, so none of them can fail again.

**F-2 — the duplicate-request-digest bug 02-09 fixed can be re-introduced by omission, and nothing would catch it.**
02-09's carry-forward fact 2 describes a real defect: the attempt index rode in the author body but not the review body, so a re-authored batch minted a repeated digest and `replay_runner` would have refused the log — discovered only at regeneration time, after the calls were paid for. The fix is in place (`generate.py:965` and `:995` both pass `attempt=attempt_index`). But:
- `_request_body`'s `attempt` parameter is **keyword-only with a default of `None`** (`generate.py:1042-1044`). A future caller that omits it silently reverts to the buggy behaviour with no error and no type complaint.
- `tests/test_datasets_authoring.py:483` covers `replay_runner`'s refusal of a duplicated digest — the *consumer* side. Nothing covers `generate.py`'s own `_review`/`_author` pair minting distinct digests across attempts. The gate that caught the bug lives only in 02-09's execution transcript.

I judged a `_review` digest test to be outside this plan's remit: its `must_haves` and `files_modified` scope this module to control-arm fidelity and solvability absence, and 02-09 owns the authoring loop. **Recommended routing:** a small plan adding a `generate.py` authoring-loop test module that (a) drives `author_arm` with a stub runner over three attempts and asserts all six request digests distinct, and (b) either drops `_request_body`'s `attempt` default or asserts both call sites pass it. Item (b) is a one-line change to `generate.py` and would convert F-2 from a coverage gap into a structural impossibility.

Neither finding blocks this plan or any wave-5 sibling. Both are cheap now and expensive after a corpus is frozen.

## Issues Encountered

- **The plan's `read_first` line numbers for `behavior_for` were slightly off** (74-87 rather than 74-87 for the function and 154-185 for the simulator pair) — they resolved correctly, noted only so a future reader does not assume drift.
- **`grep -n "catalog.artifacts"` is a regex, not a literal**, so `.` matches any character and the phrase "catalog artifacts" in prose would also have tripped the gate. The module says "the built SQLite database" throughout to stay clear of it.

## Threat Flags

None. This plan adds one test module and no runtime surface: no network endpoint, no auth path, no file access outside a `TemporaryDirectory`, and no schema change. The three threats in the plan's register (T-02-22, T-02-44, T-02-45) are each mitigated by a named test proven to fire.

## Next Phase Readiness

Ready. The D-31 evidence Phase 7's framing rests on now exists as a committed, non-flaky test rather than a claim in a document, and the L-3 laundering path is closed by a scan that has been shown to fire, to stay silent on clean code, and to tell one function from another in the same file.

Two things a reviewer should look at: **F-1 and F-2 above**, and the `gist.py::main` exemption in `_PERMITTED_SITES`. The exemption is narrow and pinned, but it is the only place in this module where a judgement call was made about what "reaching retrieval" means, and it is the right place to disagree with me if anyone does.

## Self-Check: PASSED

- `tests/test_datasets_control_fidelity.py` — FOUND
- `.planning/phases/02-expanded-dataset-paraphrase-probe/02-14-SUMMARY.md` — FOUND
- `78130e6`, `fee7628` — both FOUND in `git log`
- `git diff` against the base lists no file other than the one created; `arena/datasets/generate.py` is unchanged
- 697 tests green on the final run

---
*Phase: 02-expanded-dataset-paraphrase-probe*
*Completed: 2026-09-01*
