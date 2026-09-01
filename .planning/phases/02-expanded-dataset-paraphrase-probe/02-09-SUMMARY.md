---
phase: 02-expanded-dataset-paraphrase-probe
plan: 09
subsystem: testing
tags: [corpus-generation, paraphrase-probe, anti-circularity, determinism, cli, argparse, sqlite]

# Dependency graph
requires:
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-03 SampleRow/IntentCard/Behavior schema, corpus_stem, validate_corpus stem check"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-04 DF-gated attribute gist, load_vocabulary, gist_for_target, prompt_payload_strings"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-05 D-33 preserves_bucket, D-34 measure, D-35 contradicts, DivergenceRecord log"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-07 AuthoringRequest/attempt_until/claude_runner/replay_runner/load_prompt"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-08 DatasetEntry registry, publish_corpus, shape checks, write_target_snapshot"
provides:
  - "arena/datasets/generate.py: the corpus generator, its gate loop, and its CLI"
  - "control_card: the evaluator's own intent_card embedded verbatim as the control arm (D-31)"
  - "override_turn_for_pair: the D-36 pair-pinned override turn, a pure function of (pair_id, scenario_type)"
  - "pair_id_for: the single corpus-namespaced pair-id minting point (D-45)"
  - "author_arm: the six-gate bounded authoring loop that retains every DivergenceReport"
  - "measure_solvability: reported for the expanded corpora, refused for the probe (D-35, L-3)"
  - "main(): the publish sequence emitting corpus, response log, divergence log, snapshot, registry, Markdown"
affects: [02-14, 02-11, 02-12, 03, 04, 05, 07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single minting point for a namespaced identifier, with the loader enforcing what the generator merely intends"
    - "Retain-the-measurement: the gate's own DivergenceReport is carried on the accepted phrase, never recomputed"
    - "Refusal duplicated at the CLI and inside the function, so bypassing the CLI does not bypass the guard"
    - "Per-arm rather than per-corpus single-resolved-model assertion"

key-files:
  created:
    - arena/datasets/generate.py
  modified:
    - docs/STATUS.md

key-decisions:
  - "The expanded corpora are UNPAIRED (D-25's own target column: 2,000 sessions over 2,000 targets), so check_pairing and check_cross_check_subset run for the probe only"
  - "The single-resolved-model refusal is scoped per arm, because the probe deliberately spends two aliases (D-40)"
  - "constraint_slots admits gist-pair reuse rather than dropping attribute-poor targets, which would skew the corpus the way D-30 exists to prevent"
  - "_OVERRIDE_TURN_LABEL was not defined; override_turn_for_pair mirrors the evaluator's string-seed idiom verbatim and a dead constant is worse than a documented absence"
  - "The attempt index rides in the review body as well as the author body, or a re-authored batch mints a duplicate request digest and the corpus becomes unreplayable"

patterns-established:
  - "Filter the candidate pool BEFORE the draw, never after: a post-draw drop leaves the corpus short of its recorded session count"
  - "Item ids handed to an authoring model are built from pair_id, never parent_asin, so the id itself leaks nothing"
  - "An out-parameter callback (observe) keeps a measurement function's return shape fixed while still letting the caller act per row"

requirements-completed: [MEAS-10, MEAS-11, MEAS-12]

# Metrics
duration: 78min
completed: 2026-09-01
---

# Phase 02 Plan 09: Corpus Generator Summary

**A deterministic corpus generator whose control arm is the evaluator's own `intent_card` verbatim, whose override turn is pinned per pair, whose every authored phrase clears six gates with its divergence measurement retained, and whose solvability check is refused for the probe at both the CLI and the function.**

## Performance

- **Duration:** ~78 min
- **Tasks:** 3 of 3
- **Files modified:** 2 (1 created, 1 modified)
- **Test suite:** 634 tests, green — before and after, with and without `claude` on PATH

## Accomplishments

- `arena/datasets/generate.py` (1,704 lines) implements the whole generation path: content-seeded stratified sampling disjoint from the public 200, corpus-namespaced pair-id minting, control-arm construction, the pair-pinned override turn, the six-gate bounded authoring loop, the asymmetric solvability check, and the CLI with its publish sequence.
- **The gate loop was exercised end-to-end offline** with a stub runner: four constraints authored, accepted, measured at overlap ratio 0.0 against a control mean of 0.75, reassembled into a valid `IntentCard`, written to a response log, and then **replayed byte-identically from that frozen log with no subprocess** (D-50).
- **Every acceptance gate was measured in both directions.** Each grep-style and introspection-style gate was proven to go red against a deliberately broken implementation and green against the real one. Details below.
- **The D-45 publish boundary was proven two-sidedly at the boundary**, not asserted from the generator's convention: a correctly stemmed corpus publishes and every written `pair_id` carries `probe_v1_`; a single injected `expanded_dev_v1_0001` row is refused with `CorpusSchemaError` naming both the offending id and the expected stem, and no corpus file is written. A corpus generated *wholly* with the wrong stem — the case a generator refactor actually produces, and the one an internally-consistent check would miss — is refused too.

## Task Commits

1. **Task 1: Target sampling, control-arm construction, pair pinning, row assembly** — `876c728` (feat)
2. **Task 2: The gated authoring loop and the asymmetric solvability check** — `3ccb68d` (feat)
3. **Task 3: `main()` — CLI, publish sequence, committed side artifacts** — `8380414` (feat)

## Files Created/Modified

- `arena/datasets/generate.py` — created. The generator: `public_target_ids`, `sample_targets`, `assign_scenarios`, `control_card`, `override_turn_for_pair`, `behavior_for_arm`, `pair_id_for`, `build_row`, `profile_for_target`, `constraint_slots`, `control_constraints`, `author_arm`, `card_from_constraints`, `divergence_records`, `is_probe_corpus`, `measure_solvability`, `corpus_plan`, `stratum_for`, `cross_check_pairs`, `main`.
- `docs/STATUS.md` — modified. New tier-1 section "Transcribed from the evaluator, not chosen", recording `_OVERRIDE_TURN_CHOICES = (3, 4)` and separating the untuned constant from the D-36 seeding decision that surrounds it.

## Verification Performed

Every gate below was run against the real implementation **and** against a deliberately broken one. The three traps this phase has seen (patching the wrong binding, structurally unreachable branches, negative tests asserting only an exception type) were checked for specifically.

| Gate | Green on real code | Red on broken code |
|---|---|---|
| `pair_id_for` is the only minting point (`:04d` count outside comments == 1) | 1 | injected a second inline `f"{stem}_{7:04d}"` → 2 |
| `build_row` does not re-prefix the stem (comment-stripped source) | passes | injected `f"{corpus_stem}_{pair_id}_{arm}"` → fires with its own message |
| `sample_id` coupling is a hard invariant | real row validates | hand-built doubly-prefixed row raises `ValueError` **naming `sample_id`**, not merely the type |
| `validate_corpus` is called with `corpus_name=` | 1 named, 0 positional | `validate_corpus(records)` → positional gate 1, named gate 0 |
| Foreign corpus stem refused at publish | 6-pair corpus publishes | 1 foreign row → `CorpusSchemaError` naming `expanded_dev_v1_0001` and `probe_v1`; no file written |
| L-3 refusal in `measure_solvability` | probe raises with the reason in the error | **scoped**: `expanded_dev.v1` gets *past* the guard and fails on the missing artifact instead |
| L-3 refusal at the CLI | `rc == 1`, sentence on stderr, before any file is opened | — |
| D-33 bucket gate | accepts a bucket-preserving phrase | `"priced under 40 dollars please"` → `bucket moved from 'material' to 'budget'` |
| D-34 divergence gate | overlap 0.0 on all four slots | `"a leather upper with a rubber sole"` → `lexical overlap 1.0000 on ['rubber', 'sole']` |
| D-35 faithfulness review | `faithful` accepts | `wrong` → refused after the 3-attempt cap, naming each item |
| Request-digest uniqueness | 6 calls over 3 attempts, all digests distinct | see deviation 1 below — this gate **caught a real defect** |
| Cross-check subset preserves the mix | 100 pairs, every scenario share within 0.02 | — |
| Determinism | stratified draw is order-independent; cross-check subset reproduces exactly | — |
| Offline / no CLI | 634 tests pass with `claude` removed from PATH; `generate` imports and refuses with none present | — |

**One gate I judged one-sided and would flag:** the plan's task-2 `<automated>` verify only introspects function source for the strings `attempt_until`, `preserves_bucket`, `contradicts`, `review`. It passes on any implementation that *mentions* those names, including one that never calls them. I did not rely on it — the behavioural proofs in the table above are what establish the gates actually fire. Plan 02-14 should assert behaviour, not source text, for this.

## Decisions Made

1. **The expanded corpora are unpaired.** D-25's table gives `expanded_dev` 2,000 sessions over **2,000 targets** — one session per target — while the probe gets 700 sessions over 300 targets. `check_pairing` and `check_cross_check_subset` both structurally require ≥2 arms under one `pair_id`, so running them over an unpaired corpus would reject every row. They are therefore called for the probe only, with the reasoning recorded on `_CORPUS_PLANS`. The expanded corpora are still *authored* (D-49 sends the 2,800 bulk-paraphrase sessions to Haiku); their statistical use is candidate-vs-candidate joined on `sample_id`, which needs no second arm.
2. **The single-resolved-model refusal is per arm, not per corpus.** The probe deliberately spends two aliases — Sonnet for the primary arm, Haiku for the D-40 cross-check — so `authoring.assert_single_resolved_model` over the whole corpus would refuse the design. What T-02-28 actually forbids is one arm silently changing generator mid-run, and `_resolved_for_alias` refuses exactly that.
3. **Gist-pair reuse is admitted rather than refused.** A control card carries up to four constraints while a thin product's gist may hold two or three. Refusing reuse dropped a realistic synthetic target outright, and attribute-poor products are not randomly distributed — so the corpus would skew toward richly described listings, which is the silent skew D-30's stratification exists to prevent. The two phrases are still forced apart by the pair-uniqueness gate.
4. **`_OVERRIDE_TURN_LABEL` was not defined.** The plan lists it as a module constant, but the same plan specifies `random.Random(f"{pair_id}\0{scenario_type}")` for `override_turn_for_pair` — the evaluator's own idiom, verbatim, which is the point. A `pair_seed` label has nowhere to go in that seed, so defining the constant would leave dead code. The stream-separation argument is preserved and documented at the function: a string seed cannot collide with the integer `pair_seed` streams.
5. **Stratum granularity: the second category value.** The first is the store-wide "Clothing, Shoes & Jewelry" on essentially every product and stratifies nothing; the last is a leaf so specific the strata would outnumber the targets and the allocation would degenerate to an unstratified draw.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Re-authoring minted duplicate request digests on the review call**
- **Found during:** Task 2, while proving the digest-uniqueness property from 02-07's carry-forward note.
- **Issue:** I threaded the attempt index into the *author* request body but not the *review* body. A re-authored batch that came back with the same phrases produced a byte-identical review request across attempts. `replay_runner` refuses a log that repeats a request digest rather than coin-flipping between records, so the corpus would have been **unreplayable** — discovered only at regeneration time, long after the calls were paid for.
- **Fix:** `_review` now takes `attempt_index` and passes it through `_request_body`, exactly as the author call does. The reasoning is commented at the call site because this is the harder of the two cases to see.
- **Files modified:** `arena/datasets/generate.py`
- **Verification:** A stub runner that fails every review now produces 6 calls over 3 attempts with **all digests distinct**; the assertion failed before the fix and passes after.
- **Committed in:** `3ccb68d`

**2. [Rule 2 — Missing critical functionality] Pair-uniqueness gate added to the accept loop**
- **Found during:** Task 2.
- **Issue:** The plan lists five gates. None of them prevents two slots of the same pair receiving the same phrase. `IntentCard.validate()` refuses a value repeated across `hard_constraints` and `soft_preferences` (because `customer_reply` discloses it once and leaves it undiscoverable through the other list), so such a pair would fail at row assembly — *after* the tokens were spent.
- **Fix:** Added as gate 5, before the review, checking both against phrases already accepted for the pair and against duplicates within the current produced batch. Which of two identical phrases wins is decided on sorted item id, so it is deterministic.
- **Files modified:** `arena/datasets/generate.py`
- **Verification:** Fired during development with `phrase duplicates one already accepted for this pair`.
- **Committed in:** `3ccb68d`

### Signature and scope adjustments

These are documented departures from the plan's literal text, each forced by a requirement stated elsewhere in the same plan.

- **`measure_solvability` gained `corpus_name`.** The plan's signature is `(rows, *, artifact_path, catalog_path)` but the same task requires the function to "refuse the probe … whenever the corpus name it is handed is a probe corpus". It cannot be handed a name it has no parameter for.
- **`measure_solvability` gained `observe`.** `--drop-unsolvable` needs per-row verdicts, and the plan pins the return to the three counts. A callback keeps the documented return shape exactly while letting the caller act per row, and keeps the drop decision at the CLI where the plan puts it.
- **`author_arm` returns `ArmAuthoring`, not `tuple[tuple[str, str], ...]`.** The plan's own text requires it to return the accepted `DivergenceReport` alongside each phrase; the annotation it gives cannot carry one. `ArmAuthoring` also carries the call log, which `main` needs for `write_response_log`.
- **`author_arm`'s first parameter is `targets: tuple[PairTarget, ...]`** — pair id, target, scenario and control card together, which is the minimum needed to build a slot and check its bucket.
- **`divergence_records` keeps `pair_id_by_target`** even though `ConstraintSlot` already carries `pair_id`. Rather than being redundant it is used as a cross-check: a disagreement raises, which catches a slot filed under the wrong pair — a defect that would satisfy `coverage()`'s count while describing another session's phrase.
- **Three CLI flags added beyond the plan's list:** `--corpus-root`, `--markdown`, and per-corpus defaults resolution. The first two are needed for the `.scratch/` smoke runs the plan's own operator note prescribes; without them a smoke run writes into `data/` and `docs/`.

---

**Total deviations:** 2 auto-fixed (1 × Rule 1, 1 × Rule 2), plus 6 signature/scope adjustments each forced by the plan's own stated requirements.
**Impact on plan:** No scope creep. Deviation 1 was a genuine correctness bug that would have made a paid-for corpus unreplayable; deviation 2 prevents a total row-assembly failure. Every signature change is strictly additive.

## Issues Encountered

- **`git checkout --` cannot revert an untracked file.** I mutated `generate.py` to prove two gates were two-sided while the file was still untracked, so the file-scoped revert the discipline prescribes was unavailable. I restored it by applying the exact inverse of both mutations and re-ran every task-1 proof plus the full suite to confirm the restoration was byte-clean. **For future waves: mutate a copy, not the file, when the file is not yet tracked.**
- **`data/catalog.jsonl` is not present in this checkout** (it is gitignored and ~61 MB), so `main()` could not be run end-to-end. Everything downstream of the catalog read was verified directly instead: the gate loop with a stub runner, the publish boundary through `publish_corpus`, the registry shape checks, and all CLI argument handling. The catalog-dependent path is an operator run and is covered by the smoke command in the module docstring.
- **`claude` is on PATH on this machine**, so a plain green suite would not have proven the offline claim. I re-ran the full 634 tests, the module import, and the task-2 proofs with `PATH` stripped of it; all pass.

## Notes for Plan 02-14

02-14 exists to prove two properties this generator claims and cannot prove about itself. Both were built to be true rather than asserted:

- **Control-arm fidelity (D-31/D-55/L-2):** `control_card` wraps `intent_card(product)` verbatim with no re-clean, re-order or repair, and a target whose evaluator card cannot be expressed as a valid `IntentCard` is **excluded from the candidate pool** rather than patched. `behavior_for_arm` returns `Behavior(scenario_type, None)` for the three non-override scenarios, whose `as_record()` emits a bare `{"scenario_type": s}` and matches `behavior_for` byte for byte. The byte-identity assertion should be **scoped to `buying`, `browsing` and `boundary`** — for `intent_override`, D-36 pins the turn from `pair_id` while the fallback draws from `sample_id`, so an unscoped test is the ~15% flaky one D-55 warns about, and only card identity is assertable there.
- **Solvability absence (D-35/L-3):** no probe-pipeline path constructs an agent or calls a backend. `SearchRequest`, `RetrievalRoute` and `LocalProductSearchBackend` are imported **inside `measure_solvability` only**, and `backend.search(...)` appears nowhere else in the module. `grep -rn "Agent\b" arena/datasets/` matches exactly one line, a comment in `schema.py:506`. The scanner must be proven to fire on a synthetic violation, per this phase's own lesson about unreachable guards.

## Next Phase Readiness

Ready. The module is importable offline with no `claude` CLI and no catalog, the full suite is green at 634, and the two committed side artifacts (`write_divergence_log`, `write_target_snapshot`) are written by the publish sequence rather than left for a later plan to invent.

Two things a reviewer should look at:
- The **unpaired expanded corpora** call (decision 1) changes what `check_pairing` covers. If the intent was in fact 1,000 paired sessions rather than 2,000 unpaired ones, that contradicts D-25's target column and should be settled before `expanded_dev.v1` is generated — it is cheap to change now and expensive after the corpus is frozen.
- **`DatasetEntry` has one `generator_model_resolved` field but the probe corpus has two generators.** The primary (Sonnet) id is recorded; the cross-check (Haiku) id lives only in the committed, digest-pinned response log. If the affinity finding needs the cross-check id in the registry, 02-08's entry shape needs a field.

## Self-Check: PASSED

- `arena/datasets/generate.py` — FOUND
- `docs/STATUS.md` — FOUND
- `.planning/phases/02-expanded-dataset-paraphrase-probe/02-09-SUMMARY.md` — FOUND
- `876c728`, `3ccb68d`, `8380414`, `b7baebc` — all FOUND in `git log`
- Working tree clean; 634 tests green on the final run.

---
*Phase: 02-expanded-dataset-paraphrase-probe*
*Completed: 2026-09-01*
