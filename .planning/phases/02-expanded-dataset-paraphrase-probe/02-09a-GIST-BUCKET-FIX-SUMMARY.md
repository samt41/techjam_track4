---
phase: 02-expanded-dataset-paraphrase-probe
plan: 09a
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
    provides: "02-14 finding F-1, the coverage gap that let this ship"
provides:
  - "constraint_slots: bucket agreement now outranks gist novelty in the fallback"
  - "tests/test_datasets_slot_assignment.py: the first committed regression coverage for constraint_slots"
  - "bucket_violations: a reusable slot/gist bucket-agreement checker, proven to fire"
affects: [02-09, 02-11, 02-12, 02-13]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A satisfiability check at assignment time, because the two gates that would catch it never see each other"
    - "Non-vacuity guard as its own test: the exhaustion fixture asserts it really exhausts"
    - "A locally reproduced known-bad algorithm, committed purely so the checker can be shown to fire"

key-files:
  created:
    - tests/test_datasets_slot_assignment.py
  modified:
    - arena/datasets/generate.py

key-decisions:
  - "Bucket agreement outranks novelty: a spent same-bucket pair is at worst a repeat, a fresh cross-bucket pair cannot be authored at all"
  - "The residual 275 mismatches are a gist SUPPLY property, not an ordering one, and were measured to be exactly that rather than assumed"
  - "The last two fallback branches were kept, not deleted: use_case and budget are reachable from classify_constraint and unreachable from the gist"
  - "The anti-skew reuse policy is unchanged and now asserted, not just commented"

patterns-established:
  - "Measure a fallback reorder by emitting the real pending queue against an empty replay log: the full 1,197-constraint configuration, zero model calls, ~13 s"
  - "Prove residual failures are structural by recomputing the supply set from the source of truth, never from the output under test"

requirements-completed: []

# Metrics
duration: 35min
completed: 2026-09-01
---

# Phase 02 Plan 09a: Gist-Bucket Assignment Fix Summary

**`constraint_slots` preferred an unspent gist pair from the WRONG bucket over a spent one from the right bucket, making 393 of 1,197 probe constraints (32.8%) unsatisfiable by construction; reordering the fallback removes every mismatch the assignment can control and leaves 275 that are a measured property of the gist's supply.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 1 of 1 (corrective work on 02-09, authorised after live corpus generation surfaced the defect)
- **Files modified:** 2 (1 created, 1 modified)
- **Test suite:** 756 tests green (745 at base + 11 new), warning-strict, with no `claude` on PATH

## The Defect

Each constraint slot is paired with the gist pair its authored phrase must denote. The shipped preference order was:

1. an unspent pair in the constraint's own bucket
2. **any unspent pair, whatever its bucket**
3. a spent pair back in the right bucket
4. any pair at all

Step 2 outranked step 3, so once the bucket-matched pool was exhausted a slot received a gist describing a *different* attribute — `bucket=color` with `gist=entry_method=toothed_fastener`.

Such an item is refused by two gates that contradict each other and never see each other:

- **D-33** `preserves_bucket` requires the authored phrase to classify back into the control phrase's bucket (`color`).
- **D-35** faithfulness requires the phrase to mean the gist (a zip fastening), and the committed author prompt's rule 5 forbids inventing an attribute the pair does not state.

Naming a colour fails faithfulness. Not naming one fails the bucket gate. No phrase passes, so the item burns all three `AUTHORING_ATTEMPT_CAP` attempts and takes the run down with it.

The failure is invisible at every other layer: the slot validates, the prompt renders, the call succeeds. Only the accumulated rejection count says anything is wrong.

## The Fix

`arena/datasets/generate.py`, `constraint_slots`. Steps 2 and 3 swapped:

1. an unspent pair in the constraint's own bucket
2. **a spent pair back in the right bucket**
3. any unspent pair
4. any pair at all

The change is 4 lines of logic; the rest of the diff is the comment, rewritten to explain why bucket agreement outranks novelty and why the last two branches still have to exist.

**Anti-skew intent preserved.** The original comment justified reuse on the grounds that refusing it would drop attribute-poor targets and skew the corpus toward richly described listings — the silent skew D-30's stratification exists to prevent. That reasoning is unchanged and the new ordering asks for *more* reuse, not less. `test_an_attribute_poor_target_keeps_every_constraint` now asserts it: a one-pair gist against a four-constraint card still emits four slots.

**Determinism retained.** Every branch reads its candidates in `catalogue` order, which `gist_for_target` sorted on `(attribute, value)`, so the first match is a stable tie-break rather than an insertion-order accident. `test_assignment_is_deterministic` pins it.

**Branches 3 and 4 were kept, not deleted.** `classify_constraint` can return `use_case` and `budget`; `gist.py`'s `_GIST_ATTRIBUTES` admits neither. A slot in those buckets has no satisfiable pair anywhere in its target's catalogue, so novelty is the only remaining tie-break.

## Measurement

Measured on the real probe configuration — 300 pairs, 100 cross-check, 1,197 constraints — by emitting the pending queue against an empty response log. No model call, ~13 s per run.

```
uv run python -m arena.datasets.generate --corpus probe.v1 --pairs 300 \
    --cross-check-pairs 100 --model sonnet --prompt author_probe.md \
    --batch-size 20 --replay .scratch/empty.jsonl \
    --emit-pending .scratch/pending.jsonl --response-log .scratch/out.jsonl
```

| | mismatched | rate | avoidable | supply-limited |
|---|---|---|---|---|
| Before | 393 / 1,197 | 32.83% | 118 | 275 |
| After | 275 / 1,197 | 22.97% | **0** | 275 |

**The post-fix count is 275, not ~0, and that is stated plainly rather than dressed up.** It is not a residue of the ordering. A second measurement replayed the generator's own candidate filter and stratified draw, then for every emitted slot compared the slot's bucket against the buckets the target's gist can actually offer — computed from `gist_for_target`, never from the assignment's own output:

```
total_slots=1197  mismatched=275  unavoidable_supply=275  avoidable=0
```

All 275 are slots whose bucket has **no gist pair whatsoever** for that target — a `color` constraint on a product whose gist holds no colour, a `feature` constraint on a product whose gist holds no abstraction. The same script against the old ordering reports `mismatched=393 unavoidable_supply=275 avoidable=118`, so the supply floor is identical under both and the fix closed the entire gap between them.

That floor is also provably optimal for this function: branch 2 never consumes a pair, so a slot gets its own bucket whenever the catalogue holds one at all. Nothing the assignment can do reduces 275 further. Closing it would require changing what the *gist* supplies (02-04) or which targets are admitted to the candidate pool — a different decision, with its own D-30 skew consequences, and out of scope here.

Note the 275 are **not** automatically doomed the way the 118 were. A `feature`-bucket slot handed `material=glass` is at least coherent to write about; the D-33 gate may still refuse it, but it is not the flat contradiction that a `color` slot shown `entry_method` was.

## Regression Coverage

02-14's finding F-1 recorded that `constraint_slots` and nine sibling public symbols had **no committed regression coverage anywhere** — verified in 02-09 only by ad-hoc scripts that were never committed, which is why this shipped. `tests/test_datasets_slot_assignment.py` is the first committed coverage for `constraint_slots`: 11 tests, no catalog, no SQLite, hand-written products and inline vocabularies.

**Both directions measured, as the phase's own discipline requires.**

| | with the fix | against the old ordering |
|---|---|---|
| `tests.test_datasets_slot_assignment` | 11 passed | **4 failed**, 7 passed |

The four that fail against the defect:

- `test_a_thin_gist_still_matches_every_slot_it_can_supply` — reports both violations, `h1 bucket=material gist=color` and `s0 bucket=color gist=size`
- `test_a_bucket_the_gist_cannot_supply_still_yields_a_slot`
- `test_the_second_same_bucket_slot_reuses_rather_than_crossing_buckets` — `('color', 'black') != ('material', 'leather')`
- `test_reuse_does_not_steal_the_pair_a_later_slot_needs` — `'size' != 'color'`

Verified by `git checkout -- arena/datasets/generate.py`, running the suite, then re-applying — not by reasoning about what would happen.

**The vacuity traps this phase keeps hitting were handled explicitly:**

- **A fixture too generous to reach the branch.** This was the main risk: bucket agreement is free while unspent same-bucket pairs remain, so a comfortable gist never reaches the fallback and every assertion passes without exercising anything. `_THIN_VOCABULARY` holds three pairs against four slots, two of which compete for the single `material` pair. `test_the_fixture_really_exhausts_the_pool` fails if a future edit widens the vocabulary or shortens the card — it asserts `len(slots) > len(pairs)` *and* that some pair was actually used twice.
- **A checker that cannot fail.** `bucket_violations` returning `()` unconditionally would make every positive test pass. `DefectiveOrderingTest` reproduces the shipped-and-wrong preference order locally — a known-bad algorithm, committed solely so the checker has something it must report — and asserts it reports exactly two violations with the expected shapes.
- **A drifted fixture.** `BucketFixtureTest` asks `classify_constraint` whether each phrase really lands in the bucket this module names, and asks `gist_for_target` whether each vocabulary really supplies the pairs relied on. A classifier change would otherwise silently re-point a fixture and leave everything green over a card that no longer tests what its name says.
- **Comparison against the output under test.** `_suppliable_buckets` derives the supply set from `gist_for_target`, never from the slots — a set built from the assignment's own output would agree with it by construction.

## Deviations from Plan

None. The reorder, the comment, the coverage and the measurement were all in scope as briefed.

One thing the brief anticipated and got right: it allowed for the post-fix count not reaching ~0. It does not, and the reason is structural rather than a partial fix. Reporting 22.97% as a win without the supply decomposition would have been the wrong call; the decomposition is what makes the number interpretable.

## Constraints Honoured

- `evaluator/local_evaluator.py` untouched.
- No `data/` artifact touched. `git status` at completion lists exactly two files: `arena/datasets/generate.py` (modified) and `tests/test_datasets_slot_assignment.py` (created).
- No gate weakened, bypassed or special-cased. D-33, D-34, D-35 and the pair-uniqueness gate are byte-identical.
- All scratch work under `.scratch/` (gitignored), nothing committed.
- stdlib only, deterministic, frozen dataclasses, house style.
- Suite green with no `claude` on PATH, under `-W error::ResourceWarning`.

## Carry-Forward

1. **The probe corpus must be regenerated.** Every previously queued or answered authoring request for a mismatched item was authored against a contradictory brief. The orchestrator owns `data/responses/probe.v1.jsonl` and `data/probe.v1.jsonl`; both need to be rebuilt from this fix, not patched.
2. **Expect ~275 constraints to remain harder than the rest.** They are coherent but bucket-poor. If the run still cannot converge within `AUTHORING_ATTEMPT_CAP`, the next lever is 02-04's gist supply — widening what a target's gist offers — not this function.
3. **F-1 is only partly closed.** `constraint_slots` now has coverage. `sample_targets`, `assign_scenarios`, `control_constraints`, `author_arm`, `card_from_constraints`, `divergence_records`, `corpus_plan`, `stratum_for`, `cross_check_pairs` and `public_target_ids` still have none. F-2 (the `_request_body` attempt-digest gap) is untouched.

## Self-Check: PASSED

- `arena/datasets/generate.py` — FOUND, modified
- `tests/test_datasets_slot_assignment.py` — FOUND, created
- `.planning/phases/02-expanded-dataset-paraphrase-probe/02-09a-GIST-BUCKET-FIX-SUMMARY.md` — FOUND
- 756 tests green on the final run, warning-strict, no `claude` on PATH
- Before/after mismatch measured on the real 1,197-constraint configuration, both directions
- New tests confirmed to fail (4) against the old ordering and pass (11) against the new

---
*Phase: 02-expanded-dataset-paraphrase-probe*
*Completed: 2026-09-01*
