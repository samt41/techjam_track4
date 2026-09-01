---
phase: 02-expanded-dataset-paraphrase-probe
plan: 11b
subsystem: arena/datasets
tags: [divergence-gate, authoring, drop-ledger, registry-provenance, scope-reduction]
requires:
  - arena/datasets/authoring.py (AUTHORING_ATTEMPT_CAP, attempt_until)
  - arena/datasets/divergence.py (D-34 measure_text)
  - arena/datasets/generate.py (author_arm, _run publish sequence)
  - arena/datasets/registry.py (DatasetEntry)
  - starter/shopping_agent/constraint_extractor.py (public STOPWORDS, D-54)
provides:
  - arena/datasets/drops.py (committed drop ledger)
  - arena.datasets.authoring.attempt_outcome / ExhaustedItem / AttemptOutcome
  - arena.datasets.divergence.carries_content
  - arena.datasets.generate.refused_pairs / surviving_positions / apply_drops / slot_item_ids / assert_arms_match_on_constraint_ids
  - arena.datasets.registry.check_recorded_counts and four drop-provenance fields
  - "--drop-log CLI flag; data/drops.{corpus}.jsonl artifact"
affects:
  - .planning/phases/02-expanded-dataset-paraphrase-probe/02-11-PLAN.md (its 300-pair / 700-session / snapshot-300 literals no longer hold)
tech-stack:
  added: []
  patterns:
    - "one loop, two doors: attempt_until raises, attempt_outcome reports"
    - "an authorised reduction is admissible only when its ledger, its stdout summary and its registry counts all close"
key-files:
  created:
    - arena/datasets/drops.py
    - tests/test_datasets_partial_corpus.py
  modified:
    - arena/datasets/divergence.py
    - arena/datasets/authoring.py
    - arena/datasets/generate.py
    - arena/datasets/registry.py
    - docs/STATUS.md
    - tests/test_datasets_divergence.py
    - tests/test_datasets_detached_authoring.py
decisions:
  - "All-stopword shared 2-grams are not lexical reuse; one content word still rejects"
  - "Cap exhaustion drops the constraint from every arm rather than failing the corpus"
  - "A pair that loses a whole hard or soft list is refused, never emitted half-formed"
  - "An item nobody authored is not droppable, and a run with a pending queue cannot publish"
  - "Surviving positions are renumbered contiguously from one shared map, so the arms cannot disagree"
metrics:
  tests_before: 772
  tests_after: 800
  duration_minutes: 95
  completed: 2026-09-01
---

# Phase 02 Plan 11b: Partial Corpus Summary

Two changes that let plan 02-11 freeze a probe corpus from the constraints that
were successfully authored: a real defect fix in the D-34 adjacency gate, and a
drop-and-record path for constraints that genuinely exhaust the attempt cap.

## What changed

### A. All-stopword shared bigrams are no longer lexical reuse

`arena/datasets/divergence.py` grew `carries_content`, and `measure_text`'s
adjacency half now ignores a shared 2-gram whose tokens are *all* stopwords. It
reads the same public `STOPWORDS` the content half already consumes (D-54), so no
second list exists to drift.

The boundary is deliberately narrow: **one content word is enough to reject.**
`rubber sole`, `snap closure`, `moisture wicking` and `with leather` all still
fail. The pinned classifier keyword counts as content here even though
`content_tokens` excludes it, because `with leather` is copied phrasing whether or
not D-33 forced the phrase to carry `leather`.

### B. Cap exhaustion drops the constraint instead of aborting the corpus

`attempt_until`'s loop moved into `attempt_outcome`, which returns each exhausted
item with its attempt count and verbatim final reason. `attempt_until` is now that
function plus a refusal and behaves exactly as before. `author_arm` takes the
reporting door and returns `DroppedConstraint` records; `_run` applies them.

The authoring loop and the row-assembly loop were split — they used to be one, and
one loop cannot express a symmetric drop, because a constraint the cross-check arm
exhausts has to leave rows the control and primary arms had already minted.

## Measured results

Every number below was measured in this worktree by replaying the committed
response log (`data/responses/probe.v1.jsonl`, 129 records, read-only from the main
checkout) under the pre-change rule, and by rebuilding the same 300-pair sample the
live run drew. The reproduction reproduced the live failure exactly —
`authoring failed after 3 attempts for 310 item(s)` — which is what makes the rest
of these figures evidence rather than estimates.

**Rejection categories across the 310 exhausted items**

| reason | count |
|---|---:|
| D-34 lexical / 2-gram overlap | 202 |
| D-35 "phrase asserts admitted vocabulary the target lacks" | 87 |
| D-35 review verdict `drifted` | 17 |
| D-33 bucket moved | 4 |

**Task A recovery, against the real 202 overlap failures: 12 recovered (5.9%).**
All twelve had an overlap ratio of exactly `0.0000` — no shared content word at all
— and failed purely on a function-word span: `with a` ×7, `it s` ×3, `to be` ×3,
`to the` ×2, and one each of `in the`, `and a`, `in a`, `that s`. No item with a
shared content token or a content-bearing span was recovered, which is the correct
bound: the exemption cannot reach them.

Those 12 are recovered **from the D-34 gate only**. Each still faces the D-35
contradiction guard, pair uniqueness and the faithfulness review, none of which
ran for them, so the corpus figures below are stated as a range.

**Corpus shape (300 sampled pairs, 1,033 constraints, mean 3.44 per pair)**

| | drop 310 (before A) | drop 298 (after A) |
|---|---:|---:|
| surviving constraints | 723 | 735 |
| mean per sampled pair | 2.41 | 2.45 |
| pairs with zero constraints | 19 | 17 |
| **viable pairs (≥1 hard and ≥1 soft)** | **213** | **217** |
| constraints on viable pairs | 626 | 639 |
| mean per viable pair | 2.94 | 2.94 |

So the corpus lands at roughly **217 of 300 pairs — about 500 of the planned 700
sessions**. 213 is the floor (if none of the twelve clear the remaining gates), 217
the ceiling. The exact number comes from the operator's next authoring run.

## Loudness: what a reader can see without re-running anything

- `data/drops.{corpus}.jsonl`, committed and written on **every** run including
  runs that dropped nothing — one row per dropped constraint (item id, pair, arm,
  target, slot, position, bucket, gist attribute and value, attempt count,
  **verbatim** final rejection reason) and one row per refused pair (which list it
  lost, which constraints emptied it, which arms it would have carried).
  Deterministic order; constraint rows before pair rows.
- stdout, unconditionally: `dropped_constraint_rows`, `dropped_constraints`,
  `refused_pairs`, `sampled_pairs`, `surviving_pairs`, `surviving_constraints`,
  `constraints_per_pair`, `drop_log`.
- `data/datasets.json`: `dropped_constraint_count`, `refused_pair_count`,
  `drop_log_path`, `drop_log_sha256`.
- `docs/datasets.md`: a `Dropped` column on the corpus table, with prose.
- `docs/STATUS.md`: the second authorised scope reduction, its measured cost and
  its bias implications, beside the existing gist-supply reduction.

`registry.check_recorded_counts` runs before the entry is frozen and refuses a
mismatch between the entry, the rows written and the ledger on disk — sessions,
targets, both drop counts, refused-vs-published disjointness, and
`published + refused == sampled`. The `--drop-unsolvable` reduction is subtracted
explicitly so one reduction cannot absorb the other's shortfall.

## What is deliberately still refused

- **An item nobody authored is not droppable.** `author_arm` raises on a
  `no phrase returned` exhaustion, and `_run` refuses to publish when the pending
  collector holds anything. On the detached path both are an unanswered queue, not
  a measured outcome; without these a request first queued on the *final* attempt
  would have been silently dropped, since there is no next attempt for the
  collector's overlap rule to stop.
- **No gate weakened.** D-33, D-34 (beyond the defect fix), D-35, publish
  validation, pair uniqueness and `check_scenario_mix` are untouched.
  `_GIST_DF_FLOOR` and `AUTHORING_ATTEMPT_CAP` are unchanged.

## Verification, measured both ways

| claim | proven fails before | proven passes after |
|---|---|---|
| all-stopword spans no longer reject | neutralised the exemption → 2 new tests fail with `('with a',) != ()` | 47 divergence tests green |
| content-bearing spans still reject | widened `carries_content` to `all(...)` → 6 tests fail (`a sturdy`, `a rubber`, `rubber sole` no longer named) | same suite green |
| the exemption reads the shared STOPWORDS | passing a narrowed set flips the verdict | — |
| the drop is symmetric across arms | made cross-check drops not propagate → the live run aborted with `pair probe_v1_0000 is not matched on constraint ids after the drop` | 24 partial-corpus tests green |
| pairs losing a list are refused | made `refused_pairs` return `()` → 7 tests fail with `intent_card soft_preferences must be a non-empty tuple` | same suite green |
| recorded counts equal reality | four `check_recorded_counts` branches asserted by **message**, not just exception type | — |
| the fixture genuinely trips the cap | ledger rows assert `attempts == AUTHORING_ATTEMPT_CAP`, and a baseline run asserts zero drops | — |

The partial-corpus fixture needed 40 pairs rather than the sibling module's 20:
at 20 pairs over 44 rows **no** pair can be refused without `check_scenario_mix`
rejecting the result. That is a real property of the drop mechanism, recorded in
the test module rather than worked around — a corpus that loses many pairs can
still be refused by the mix check, and nothing here relaxes it.

Full suite: **800 tests, green, with `claude` removed from PATH** (772 at base,
+4 divergence, +24 partial corpus). No `data/` artifact was written; the main
checkout's catalog and response log were read only, for measurement.

## Consequences for plan 02-11

1. **The committed response log will no longer replay to completion.** Recovering
   12 items changes which items are pending on attempts 2 and 3, so those batches
   carry different request digests than the log holds. The detached `--emit-pending`
   loop handles this correctly — it queues the newly diverging requests — but a
   plain `--replay` run will report a missing digest. This is expected, not a
   regression.
2. **02-11's literals need updating** when it is executed: `sessions=700`,
   `targets=300` and `snapshot_targets=300` become roughly 500 / 217 / 217, and its
   `target_snapshot_count == 300` acceptance command with them. The target snapshot
   now commits only *published* targets, so its key set still equals the corpus's
   target set exactly, which is what 02-11's sweep asserts.
3. `data/drops.probe.v1.jsonl` joins the artifacts to commit alongside the corpus,
   and is not gitignored (verified).

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 2 - Missing critical functionality] The detached path could have silently published short**

- **Found during:** task B design
- **Issue:** With cap exhaustion no longer raising, an unanswered request would
  make its items look exhausted and they would be dropped. `PendingRequestCollector`
  normally stops such a run when the next attempt's items overlap the queue, but a
  request first queued on the final attempt has no next attempt — so the corpus
  would publish short, with a ledger blaming the gates.
- **Fix:** `NO_PHRASE_REASON` is named in `authoring.py`; `author_arm` raises on it,
  and `_run` refuses to publish when `collector.pending` is non-empty. Both are
  tested.
- **Commit:** 16ac1ae

**2. [Rule 1 - Bug] The target snapshot would have named refused targets**

- **Found during:** task B
- **Issue:** The snapshot was written from the sampled targets. A refused pair
  contributes no row, so the snapshot would have described a target the corpus does
  not hold — and 02-11 asserts the snapshot's key set equals the corpus's target set.
- **Fix:** the snapshot is now built from the published rows.
- **Commit:** 16ac1ae

**3. [Rule 2 - Missing critical functionality] `--drop-unsolvable` would have broken the count check**

- **Found during:** review of `check_recorded_counts`
- **Issue:** an operator-typed solvability drop removes pairs, so
  `published + refused == sampled` would fail for a reason unrelated to the gates.
- **Fix:** the pairs it removed are counted and subtracted explicitly, so one
  reduction cannot absorb the other's shortfall.
- **Commit:** 16ac1ae

**4. [Rule 2] Reporting surface widened beyond the brief**

`docs/datasets.md` gained a `Dropped` column and prose. The brief asked for the
ledger, stdout and the registry; the rendered Markdown view is what a reader
actually opens first, and a table showing only survivors would have let the
reduction pass unnoticed there.

## Self-Check: PASSED

- `arena/datasets/drops.py` — FOUND
- `tests/test_datasets_partial_corpus.py` — FOUND
- `.planning/phases/02-expanded-dataset-paraphrase-probe/02-11b-PARTIAL-CORPUS-SUMMARY.md` — FOUND
- commit `86f893c` — FOUND
- commit `16ac1ae` — FOUND
