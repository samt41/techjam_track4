---
phase: 02-expanded-dataset-paraphrase-probe
plan: 09b
subsystem: testing
tags: [corpus-generation, paraphrase-probe, defect-fix, regression-coverage, determinism]

# Dependency graph
requires:
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-04 DF-gated attribute gist, load_vocabulary, gist_for_target"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-05 D-33 preserves_bucket, D-34 measure, D-35 contradicts"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-09 arena/datasets/generate.py, constraint_slots, author_arm"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-09a the slot/gist assignment ORDER fix, and the supply measurement that exposed this"
provides:
  - "constraint_slots: a constraint whose bucket the gist cannot supply is never emitted"
  - "authorable_pair: the symmetric per-pair card reduction every arm reads from"
  - "tests/test_datasets_slot_assignment.py: supply-omission, refusal and cross-arm coverage"
  - "unsuppliable_slots: a supply checker, proven to fire"
affects: [02-09, 02-11, 02-12, 02-13]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reduce the PAIR, not the arm: a per-arm reduction turns a wording contrast into an information contrast"
    - "Delete the branch the fix makes unreachable rather than leave it as decorative protection"
    - "Refuse at the candidate-pool filter, before the draw, so the pool is fixed before any random number"
    - "Number slot positions by emission so an omission cannot open a gap on one arm only"

key-files:
  created: []
  modified:
    - arena/datasets/generate.py
    - tests/test_datasets_slot_assignment.py
    - tests/test_datasets_detached_authoring.py

key-decisions:
  - "Zero-constraint pairs are made impossible by REFUSAL at the pool filter, not by resampling after the draw"
  - "The omission is applied to the pair so the control arm loses the constraint too; D-31's no-repair rule protects phrasing, and an asymmetric card length would break the very contrast D-31 exists for"
  - "The old third and fourth fallback branches were deleted, not kept: after the omission they cannot run, and an unreachable branch reads as protection while being unable to fail"
  - "bucket_violations became unconditional; its old suppliable-bucket exemption is now dead and would have hidden the next defect of this class"
  - "_GIST_DF_FLOOR untouched; widening gist supply was explicitly out of scope"

patterns-established:
  - "Prove a fix two-sidedly with a SURGICAL regression (restore only the removed branch) rather than a full revert, so the new API stays importable and the failure set is attributable to one property"
  - "Report the selection effect a refusal introduces, measured per stratum, rather than only the headline count"

requirements-completed: []

# Metrics
duration: 50min
completed: 2026-09-01
---

# Phase 02 Plan 09b: Gist-Supply Omission Summary

**`constraint_slots` emitted a slot for every control constraint even when the target's gist held no pair in that constraint's bucket; omitting those slots — symmetrically across every arm of the pair — takes the flatly-unsatisfiable `color`/`size` count from 141 to 0 and the total slot/gist bucket mismatch from 275 to 0, at a cost of 164 constraints and 5,977 candidate targets.**

## Performance

- **Duration:** ~50 min
- **Tasks:** 1 of 1 (second and final corrective step on 02-09, authorised by the user)
- **Files modified:** 3
- **Test suite:** 772 tests green (756 at base + 16 net new), warning-strict, with no `claude` on PATH
- **Commit:** `3add210`

## The Defect

02-09a fixed the ORDER in which a constraint slot is matched to a gist pair, and measured the result as optimal given supply (`avoidable=0`). It also measured what it could not fix: 275 of 1,197 probe constraints still carried a bucket the target's gist holds **no pair for at all**.

`_GIST_DF_FLOOR = 10` retains 24 of 1,127 catalogue colour values and 11 of 330 size values, so colour and size supply is very thin. Of the 275:

| required bucket | count | severity |
|---|---|---|
| `color`, `size` | 141 | flatly unsatisfiable |
| `material`, `style` | 61 | hard but arguable |
| `feature` (residual) + 1 `use_case` | 73 | generally workable |

The 141 are unsatisfiable by construction. To classify into `color`, the phrase must contain a colour word. The gist the author is shown (`entry_method=toothed_fastener`, say) names none, and the committed author prompt's rule 5 forbids inventing an attribute the pair does not state. Name a colour and D-35 faithfulness refuses it; do not, and D-33 `preserves_bucket` refuses it. D-33 and D-35 demand opposite things of the same item, so no phrase passes, the item consumes all three `AUTHORING_ATTEMPT_CAP` attempts, and the whole corpus run fails. That already happened once on a live run.

## The Fix

`arena/datasets/generate.py`. Three coupled changes:

**1. Omit, do not fall back.** `constraint_slots` groups the target's gist by bucket once, then emits a slot only when that bucket has supply. The old third and fourth preference branches — "any unspent pair", "any pair at all" — are **deleted**, not left in place: after the omission they cannot run, and a branch that cannot fail reads as protection while providing none. What remains is the 02-09a ordering, unchanged: an unspent same-bucket pair, else a spent same-bucket pair. For every constraint that survives, the assignment is byte-identical to 02-09a's.

**2. Reduce the pair, not the arm.** A new `authorable_pair` runs `constraint_slots` once per pair and rebuilds the card from the surviving constraints. `_run` calls it before any row or arm is built, so the control row, `control_constraints` and every `author_arm` call read the same card. Positions are numbered by **emission** rather than by index in the control card, so an omission cannot open a gap on one arm while `control_constraints`' plain `enumerate` closes it on the other — the committed divergence log keys on `(pair_id, arm, slot, position)`.

The reduction is idempotent by construction, and that is load-bearing rather than tidy: `author_arm` calls `constraint_slots` again on the card `authorable_pair` produced. It cannot remove anything further, because a constraint is dropped on a property of the target's gist, which the reduction does not touch.

**3. Refuse rather than emit an unusable card.** If a slot list would lose every constraint, `constraint_slots` raises. `_run`'s candidate-pool filter now calls `authorable_pair` — the same call the build runs — so such a target never enters the pool.

## The D-31 Tension, Resolved Deliberately

`control_card`'s own comment lists "a truncation" among the things D-31 forbids, and the reduction truncates the control card. That conflict is real and was decided rather than side-stepped.

D-31 exists so the control-vs-probe contrast means exactly "public-set phrasing vs customer phrasing". Every string the reduction retains is still the evaluator's own output, in the evaluator's own order, un-cleaned and un-repaired — `test_the_reduced_card_keeps_the_evaluator_phrasing_verbatim` pins that. What the reduction changes is card length, and it changes it **identically on every arm**.

The alternative — reduce only the arms that must be authored — leaves the control disclosing four constraints against the probe's three. The agent then has strictly less information in the probe session, and the measured delta is information content, not vocabulary. That breaks the contrast D-31 exists to protect, from the other side and far more severely than a symmetric subset does. The module docstring now states this in full, at the place a future reader will look.

## Zero-Constraint Pairs: Refused, Not Resampled

**Chosen: refuse at the candidate-pool filter, before the draw.**

`IntentCard.validate()` requires both `hard_constraints` and `soft_preferences` to be non-empty, so the binding constraint is stronger than "zero constraints" — a pair needs at least one of each. `_run` already filters the candidate pool before `sample_targets` runs, so raising inside `constraint_slots` removes such a target from the pool while it is still fully determined, before any random number is drawn.

Resampling after the draw was rejected for the reason `_run`'s own comment already gives about post-draw drops: it would make the corpus depend on which targets happened to fail, which is not reproducible. The corpus still holds exactly 300 pairs plus the 100-pair cross-check arm.

## Measurement

Emit-only, no model calls, on the real probe configuration — the brief's own command, with `--catalog` pointed at the main checkout's read-only `data/catalog.jsonl` and every output under `.scratch/`.

```
uv run python -m arena.datasets.generate --corpus probe.v1 --pairs 300 \
    --cross-check-pairs 100 --model sonnet --prompt author_probe.md \
    --batch-size 20 --replay .scratch/<d>/empty.jsonl \
    --emit-pending .scratch/<d>/pending.jsonl --response-log .scratch/<d>/out.jsonl
```

### Slot/gist bucket mismatch

| required bucket | before | after |
|---|---|---|
| **`color` + `size` (flatly unsatisfiable)** | **141** | **0** |
| `material` + `style` | 61 | 0 |
| `feature` | 72 | 0 |
| `use_case` | 1 | 0 |
| **total mismatched** | **275 / 1,197 (22.97%)** | **0 / 1,033 (0.00%)** |

**The `color`/`size` count reaches 0, and so does every other bucket.** Not a partial result: after the change no emitted slot anywhere in the corpus carries a bucket its target's gist cannot serve, because such a slot is not emitted.

### Corpus shape

| | before | after | briefed prediction |
|---|---|---|---|
| constraints (sonnet arm) | 1,197 | **1,033** | ~1,056 |
| pairs | 300 | **300** | 300 |
| per-pair distribution | {4: 297, 3: 3} | **{4: 157, 3: 119, 2: 24}** | {4: 174, 3: 110, 2: 14, 1: 2} |
| mean constraints/pair | 3.9900 | **3.4433** | ~3.52 |
| pairs touched | — | **143** | 125 |
| minimum per pair | 3 | **2** | 1 |
| pairs with an empty hard or soft list | 0 | **0** | — |

The briefed prediction and the measured result differ, and the reason is the pool refusal, which the prediction did not model. Refusing 5,977 targets changes which 300 the stratified draw selects, so this is a different sample of the same catalog rather than the same sample with constraints removed. The measured minimum of **2** rather than 1 is a direct consequence of the refusal: a pair that would fall to 1 constraint has lost a whole list and is excluded, so 1 is not reachable.

### Candidate pool

| | count |
|---|---|
| catalog products | 50,000 |
| refused: evaluator card is not a valid authored card (pre-existing) | 728 |
| refused: empty attribute gist (pre-existing) | 9,073 |
| **refused: would lose a whole constraint list (new)** | **5,977** |
| admitted | 34,222 |

The pool falls from 40,199 to 34,222, a 14.9% reduction, and 300 targets are drawn from it — a 114x oversupply, so coverage is not at risk. **The refusal is not uniform across strata, and that is the one genuine cost of this change.** Measured shares of the admitted pool against shares of the refused set:

| stratum | % of admitted | % of refused |
|---|---|---|
| `women\|under_20` | 3.12 | 10.29 |
| `luggage & travel gear\|unknown` | 0.68 | 2.93 |
| `men\|under_20` | 1.31 | 2.26 |
| `novelty & more\|under_50` | 1.15 | 0.20 |
| `westlake\|unknown` | 1.97 | 0.62 |

D-30's machinery is untouched — `_proportional_allocation` still allocates proportionally, and the emitted mix is exactly 120/120/45/15 = 40/40/15/5 — but it now allocates over a pool whose composition has shifted toward better-described listings. That is a real selection effect and is stated rather than buried. It is accepted because the alternative is a corpus that cannot be built at all: an unsatisfiable item does not degrade the run, it ends it.

### Pair matching

Measured on the real configuration by deriving each arm's ids independently:

```
constraints_sonnet=1033  constraints_control=1033  constraints_haiku=339
control_equals_sonnet=True   haiku_equals_sonnet=True   haiku_equals_control=True
pairs=300  cross_check_pairs=100  pairs_with_an_empty_list=0
scenario_mix={'boundary': 15, 'browsing': 120, 'buying': 120, 'intent_override': 45}
```

The control arm's ids come from `control_constraints`, which enumerates the pair's card directly; the authored arms' come from `constraint_slots`. They are equal for all 300 pairs, which is the property that would have broken had the reduction reached only one arm.

### Determinism

Three independent emit runs produced **byte-identical** pending queues (`cmp` clean). The one new ordering decision — which gist pair a slot takes from its bucket — reads `catalogue` order, which `gist_for_target` sorted on `(attribute, value)`.

## Regression Coverage

`tests/test_datasets_slot_assignment.py` grows from 11 tests to 27.

**Both directions measured.** The proof used a *surgical* regression rather than a full revert: the omission `continue` was replaced by the 02-09a cross-bucket fallback (`supply = available or catalogue`) with everything else, including `authorable_pair`, intact. A full revert would have made the module unimportable and the failure set unattributable.

| | with the fix | with the omission regressed |
|---|---|---|
| `tests.test_datasets_slot_assignment` | **27 passed** | **11 failed**, 16 passed |
| full suite | **772 passed** | **11 failed** — the same 11, nothing else |

The eleven that fail against the regression:

- `SupplyOmissionTest`: `test_the_fixture_really_omits_something`, `test_no_emitted_slot_carries_a_bucket_the_gist_cannot_supply`, `test_the_surviving_slots_still_get_their_own_bucket`, `test_every_fixture_emits_only_suppliable_buckets` (both subtests)
- `SlotRefusalTest`: `test_losing_every_soft_preference_refuses_the_target`, `test_losing_every_hard_constraint_refuses_the_target`, `test_the_same_card_survives_when_each_list_keeps_one`
- `AuthorablePairTest`: `test_the_fixture_really_reduces_the_card`, `test_both_arms_carry_identical_constraint_ids`, `test_a_pair_that_cannot_keep_a_whole_list_is_refused`

**The vacuity traps this phase keeps hitting, handled explicitly:**

- **A fixture too generous to reach the branch — the brief's named top risk.** `test_the_fixture_really_omits_something` asserts the fixture card declares 4 constraints, that fewer than 4 slots are emitted, and that the fixture gist genuinely cannot serve `style` or `use_case`. If a future edit widens `_THIN_VOCABULARY` or re-points a phrase, this fails first and says why. `AuthorablePairTest.test_the_fixture_really_reduces_the_card` is the same guard one level up: it asserts the reduced card is *not equal* to the declared one, so no assertion in that class can be true of an untouched card.
- **A checker that cannot fail.** `unsuppliable_slots` returning `()` unconditionally would make every omission assertion pass. `DefectiveOrderingTest.test_emitting_an_unsuppliable_slot_is_reported` hands it a hand-built `use_case` slot and asserts the exact string it must report. The pre-existing `bucket_violations` keeps its own negative test against the locally reproduced 02-09 ordering.
- **A negative test satisfied by the exception TYPE alone.** `constraint_slots` raises `GenerateError` from three places. Both refusal tests assert on the *message* (`would lose every soft_preferences` / `would lose every hard_constraints`), and `test_the_other_refusals_keep_their_own_reasons` shows the other two branches say `empty attribute gist` and `absent from the catalog` instead.
- **A refusal that is really just a too-poor fixture.** `test_the_same_card_survives_when_each_list_keeps_one` uses the *same* one-pair gist and the *same* target, with the constraints rearranged so each list retains a material — and it builds, reusing the single `material=leather` pair across both lists. The refusal is therefore a property of supply, not of the fixture.
- **A dead exemption clause.** `bucket_violations` previously exempted slots whose bucket the gist could not supply, because such a slot was emitted and necessarily carried a foreign gist. That clause is now unreachable, so it was removed rather than left as decoration.

## Deviations from Plan

**1. [Rule 3 — Blocking] `tests/test_datasets_detached_authoring.py`'s fixture catalog became 100% unadmittable.**

- **Found during:** the first full-suite run after the fix.
- **Issue:** every fixture product carried `features: ["cushioned midsole", "quick lace hardware"]`. `intent_card` puts the recovered material and colour in `hard_constraints` and the two raw features in `soft_preferences`, so the soft list was entirely `feature`-bucket. `feature` is suppliable only through the committed D-52 abstraction table (the DF floor admits nothing for it, per L-6), and neither string is a table row. Every product lost its whole soft list, the pool went to zero, and three tests failed with `the pool holds 0`.
- **Fix:** the two feature strings became `"Flexible sole"` and `"Buckle closure"`, both keys in the committed table, abstracting to `ground_contact=pliant_tread` and `entry_method=prong_strap`. They stay lexically disjoint from the module's `_PHRASES` table so the D-34 divergence gate still has something real to pass. The comment explains the requirement so the next editor does not undo it.
- **Not load-bearing on the proof:** the reworked fixture passes under both the fix and the surgical regression, so none of the 11 attributed failures come from it.
- **Files modified:** `tests/test_datasets_detached_authoring.py`
- **Commit:** `3add210`

**2. Measured numbers differ from the brief's prediction.** Reported above with the reason (the pool refusal changes the draw) rather than presented as a match.

## Constraints Honoured

- `evaluator/local_evaluator.py` untouched.
- No `data/` artifact touched. `data/catalog.jsonl` was read from the main checkout, read-only; the worktree's `data/` is untouched. `git status` at completion is clean.
- `_GIST_DF_FLOOR` unchanged at 10. `arena/datasets/gist.py` untouched.
- No gate weakened, bypassed or special-cased. D-33, D-34, D-35, the pair-uniqueness gate, `validate_corpus`, `assert_authored_branch`, `check_scenario_mix`, `check_pairing` and `check_cross_check_subset` are all byte-identical and all still run.
- 300 pairs + 100 cross-check preserved; D-30 mix measured at exactly 40/40/15/5; D-31 control arm still the evaluator's own strings; determinism byte-verified across three runs.
- All scratch work under `.scratch/` (gitignored); nothing committed. `git diff --diff-filter=D HEAD~1 HEAD` reports no deletions.
- stdlib only, frozen dataclasses, house style; no line longer than the file's existing maximum was introduced.

## Carry-Forward

1. **The probe corpus must be regenerated, again.** Every previously queued or answered authoring request predates both this change and the pool refusal, so the sampled 300 targets themselves have changed. `data/responses/probe.v1.jsonl` and `data/probe.v1.jsonl` are the orchestrator's and need a rebuild from scratch, not a patch.
2. **The corpus is 164 constraints thinner and its pool composition has shifted.** Both are measured above. If 02-11's statistics assume ~4 constraints per pair, they need the {4: 157, 3: 119, 2: 24} distribution instead.
3. **The remaining lever is 02-04's gist supply, not this function.** Every mismatch this function can remove is removed. Closing the 164-constraint gap would mean widening what a target's gist offers — which means weakening the D-32 anti-circularity mechanism, and is a different decision with its own consequences.
4. **F-1 is further closed but not shut.** `constraint_slots` and `authorable_pair` now have coverage. `sample_targets`, `assign_scenarios`, `control_constraints` (beyond the cross-arm assertion here), `author_arm`, `card_from_constraints`, `divergence_records`, `corpus_plan`, `stratum_for`, `cross_check_pairs` and `public_target_ids` still have none. F-2 is untouched.

## Self-Check: PASSED

- `arena/datasets/generate.py` — FOUND, modified
- `tests/test_datasets_slot_assignment.py` — FOUND, modified (11 -> 27 tests)
- `tests/test_datasets_detached_authoring.py` — FOUND, modified (fixture catalog)
- `.planning/phases/02-expanded-dataset-paraphrase-probe/02-09b-GIST-SUPPLY-SUMMARY.md` — FOUND
- Commit `3add210` — FOUND in `git log`
- 772 tests green on the final run, warning-strict, with no `claude` on PATH
- `color`/`size` unsatisfiable count measured at 0, from 141, on the real 300-pair configuration
- New tests confirmed to fail (11) against a surgical regression and pass (27) against the fix, by running both

---
*Phase: 02-expanded-dataset-paraphrase-probe*
*Completed: 2026-09-01*
