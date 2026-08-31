---
phase: 02-expanded-dataset-paraphrase-probe
plan: 10
subsystem: cli
tags: [argparse, arena, registry, sha256, mcnemar, paired-contrast, unittest]

# Dependency graph
requires:
  - phase: 02-02
    provides: "arena/leaderboard.py corpus-baselines siblings (build_corpus_baselines, render_corpus_baselines_markdown, write_corpus_baselines, CORPUS_BASELINES_* paths)"
  - phase: 02-06
    provides: "arena/paired_contrast.py -- PairedArm, arm_from_run, paired_contrast, write_paired_contrast, PairedContrastError, CONTRAST_* paths"
  - phase: 02-08
    provides: "arena/datasets/registry.py -- resolve_dataset, RegistryError, REGISTRY_PATH, CORPUS_ROOT, PUBLIC_DATASET_NAME, validate_dataset_name"
  - phase: 02-03
    provides: "arena/datasets/schema.py load_corpus, and the corpus-namespaced pair_id that makes a cross-corpus join structurally impossible"
provides:
  - "run_arena --dataset resolves a registry name as well as a path, re-hashing a registered corpus and refusing digest drift"
  - "run_arena contrast -- the D-44 paired readout as JSON truth plus a Markdown view, never routed through adjudicate"
  - "run_arena corpus-baselines -- the D-53 four-corpus table in its own artifacts, never in LEADERBOARD.md"
  - "main(argv) plus _build_parser(), so every CLI path is testable without a subprocess and the dispatch mapping is a value a test can assert over"
  - "--pair-subset {strict,shared} and --allow-cross-corpus as the two explicit narrowing/widening gates"
affects: [02-11, 02-12, 02-13]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "argparse.RawDescriptionHelpFormatter for any subparser whose description contains flags an operator must copy verbatim"
    - "command -> (subparser, handler) mapping returned from _build_parser(), replacing a two-branch if/else dispatch"
    - "module-global REGISTRY_PATH/CORPUS_ROOT read at call time inside _resolve_dataset, so a test can point resolution at a temporary tree"

key-files:
  created: []
  modified:
    - arena/run_arena.py
    - tests/test_arena_runner.py

key-decisions:
  - "Threaded REGISTRY_PATH and CORPUS_ROOT explicitly from run_arena's own module globals into registry.resolve_dataset, rather than relying on that function's def-time defaults -- it is what makes the resolution testable against a temporary registry, and it mirrors how _adjudicate derives report paths from --output-root."
  - "--catalog deliberately stays on _existing_file. The catalog is the organizer's file and is not registry-managed, so there is no frozen digest for it to have drifted from."
  - "PairedArm labels are f'{candidate_name}:{arm}' so the rendered contrast table names both the candidate and the arm it partitioned on."
  - "The contrast subcommand calls load_corpus but NOT validate_corpus. Corpus-shape enforcement belongs at publish time (registry.publish_corpus); re-running it per report would couple a reporting CLI to checks it does not own."
  - "Replaced the plan's `grep -c subprocess == 0` acceptance gate with an AST scan that is proven to fire. The grep cannot be satisfied by a correct file -- it already matched a pre-existing comment at the plan's own baseline."

patterns-established:
  - "Refusal tests assert the offending BRANCH's own message, never the exception type alone: several guards inside _contrast funnel through one parser.error, so a bare non-zero exit distinguishes nothing."
  - "Every parser.error assertion that must distinguish two layers keys on a decision id (D-45) rather than a flag name, because argparse prints a usage banner listing every flag alongside any error."
  - "A patched module attribute is paired with an explicit non-vacuity test proving the patch is what makes the behaviour occur."

requirements-completed: [MEAS-12, MEAS-13]

# Metrics
duration: 71min
completed: 2026-09-01
---

# Phase 02 Plan 10: Operator CLI Entry Points Summary

**`run_arena` gains registry-name `--dataset` resolution with digest-drift refusal, a `contrast` subcommand for the D-44 paired readout, a `corpus-baselines` subcommand for the D-53 table, and a `main(argv)` that makes all four subcommands testable without a subprocess.**

## Performance

- **Duration:** 71 min
- **Tasks:** 3
- **Files modified:** 2
- **Test suite:** 634 -> 669 tests, all passing in 6.1 s

## Accomplishments

- `--dataset` now accepts a registry name from `data/datasets.json` and re-hashes the file at resolution time, turning D-43's recorded digest into an enforced precondition of every measurement (Pitfall 6). Drift is refused through `parser.error` with both digests and the registry path in the message.
- `RegistryError` is named in every narrow exception tuple. This was the carry-forward risk from 02-08: it subclasses `RuntimeError`, not `ValueError`, so without the explicit entries a drifted digest would have escaped as an unhandled traceback rather than as the operator error it is.
- A `contrast` subcommand producing `paired_contrast.json` plus `PAIRED_CONTRAST.md` under `--output-root`, exposing no resample flag, and defaulting to the honest one-record/one-corpus shape D-46 locks.
- `--pair-subset` defaults to `strict` (refuses orphans) with `shared` as the explicit, counted narrowing; both the retained and dropped counts reach stdout, the JSON and the rendered prose.
- `--probe-record` / `--probe-corpus` are gated behind a typed `--allow-cross-corpus`, and the tests prove the structural defence (02-03's namespaced `pair_id`s) refuses the join even when the flag is typed.
- A `corpus-baselines` subcommand writing its own two artifacts, with the D-53 separation asserted as an absence of `LEADERBOARD.md` anywhere in the output tree AND as byte-identity of the committed `experiments/LEADERBOARD.md`.
- Dispatch is now a `command -> (subparser, handler)` mapping, so a fourth subcommand cannot silently fall through to `_adjudicate`.

## Task Commits

1. **Task 1: Registry-name `--dataset` resolution and a testable `main(argv)`** - `b0920db` (feat)
2. **Task 2: `contrast` and `corpus-baselines` subcommands** - `acbb875` (feat)
3. **Task 3: CLI resolution, drift refusal and subcommand wiring tests** - `ad2938e` (test)

## Files Created/Modified

- `arena/run_arena.py` - `_resolve_dataset`, `_contrast`, `_corpus_baselines`, `_build_parser`, `main(argv)`, the `contrast` and `corpus-baselines` subparsers, and `RegistryError` in all three narrow exception tuples.
- `tests/test_arena_runner.py` - `DatasetResolutionTest`, `HelpTextTest`, `ContrastCommandTest`, `PairSubsetCommandTest`, `CrossCorpusGateTest`, `CorpusBaselinesCommandTest`, `DispatchTest`, `NoProcessSpawnTest` (35 new cases).

## Verification

### Two-sided gate measurement

Every acceptance gate was measured in both directions. Nine deliberate mutations were applied to `arena/run_arena.py` one at a time, each reverted with a file-scoped `git checkout --`; all nine turn the suite red:

| Mutation | Caught by |
|---|---|
| `_resolve_dataset` -> `_existing_file` (no registry) | `test_the_run_subcommand_refuses_a_drifted_name_through_parser_error` |
| `restrict_to_shared=True` hardcoded | 4 tests, incl. `test_the_default_refuses_and_names_the_orphan_pairs` |
| D-45 gate made unreachable (`if False`) | both `..._without_the_flag_is_refused_naming_d45` cases |
| corpus-baselines markdown renamed to `LEADERBOARD.md` | `test_it_writes_its_own_artifacts_and_never_a_leaderboard` |
| `corpus-baselines` bound to `_adjudicate` | 4 tests, incl. `test_each_handler_is_a_distinct_function` |
| L-11 flag phrase removed from the run description | `test_the_run_help_states_the_flags_a_reproduction_must_type` |
| `allow_cross_corpus=True` hardcoded | `test_the_flag_is_false_unless_the_operator_types_it` |
| `allow_cross_corpus=False` hardcoded | `test_the_typed_flag_carries_a_genuinely_cross_corpus_contrast` |
| contrast writes a wrong artifact name | 3 tests, incl. `test_the_default_shape_writes_both_artifacts_under_output_root` |

The `allow_cross_corpus=True` mutation initially survived: the original `CrossCorpusGateTest` built both arms from ONE record, so their `dataset_sha256` were equal and the digest guard was vacuous whatever the flag said. Two cases were added — one recording the kwargs the handler passes to `paired_contrast`, one exercising a genuinely differing-digest cross-corpus contrast — before the gate closed.

### Regression proof for the pre-existing entry points

The plan adds subcommands to a CLI that already works, so behavioural identity of `run` and `adjudicate` was measured rather than assumed. `adjudicate` was run against the four committed baseline records at the plan's base commit `b6ba05c` and again at `ad2938e`, into two separate output roots:

- `baselines/leaderboard.json` — sha256 `8e7036f01fad4ec5...`, **identical**
- `LEADERBOARD.md` — sha256 `55a370cd6a57d47c...`, **identical**

`run` is covered by the pre-existing `FingerprintIdentityTest`, which asserts that one configuration mints one fingerprint through either entry path; it passes unchanged, which is the proof that swapping `_existing_file` for `_resolve_dataset` on the `--dataset` path did not change the digest that feeds the fingerprint.

### Plan verification block

1. `uv run python -m unittest tests.test_arena_runner -v` — 58 tests, 0.9 s, exit 0.
2. `main(('--help',))` lists `run`, `adjudicate`, `contrast`, `corpus-baselines`.
3. `grep -c "except Exception" arena/run_arena.py` is 0.
4. `uv run python -m unittest` — 669 tests, 6.1 s, exit 0 (limit was 45 s).

## Decisions Made

- **Registry roots are threaded from `run_arena`'s own globals.** `registry.resolve_dataset`'s `registry_path`/`root` defaults bind at def time, so a test cannot redirect them by patching the registry module. `_resolve_dataset` reads `REGISTRY_PATH` and `CORPUS_ROOT` from `arena.run_arena` at call time instead, which is both the lookup site a test can patch and the same "derive from an overridable root" discipline `_adjudicate` already applies to `--output-root`.
- **`RawDescriptionHelpFormatter` on the `run` and `contrast` subparsers.** argparse's default formatter re-wraps a description through `textwrap.fill`, which is free to break `--exploration disabled --lexical-mode auto` across a line. The one string an operator is meant to copy verbatim would then not be copyable. This is why the L-11 warning lives in a module constant rather than inline.
- **The contrast subcommand does not call `validate_corpus`.** Corpus-shape enforcement is a publish-time property (`registry.publish_corpus` validates from the staged bytes); running it again inside a reporting CLI would couple this module to checks it does not own and would make a report fail for reasons unrelated to the contrast.
- **Cross-corpus refusals are distinguished by decision id, not flag name.** `parser.error` prints argparse's usage banner, which lists `--allow-cross-corpus` regardless of which refusal fired. The discriminator between the CLI flag gate and the structural pair-id refusal therefore has to be the presence of `D-45` in the message.

## Deviations from Plan

### Reported gate defects (no source change made)

**1. `grep -c "except Exception" arena/run_arena.py` is 0 — one-sided against comment prose**
- **Found during:** Task 1.
- **Issue:** The gate scans source TEXT, so it cannot tell a comment from a clause. My first draft of the rationale comment explaining *why* the tuple is not widened contained the literal phrase, and the gate went red against a correct implementation.
- **Resolution:** Reworded the comment to say "not widened into a catch-all". The gate now passes and the rationale is preserved. **No behavioural change.** Worth flagging because the same trap will catch the next person who documents this invariant.

**2. `grep -c "subprocess" tests/test_arena_runner.py` is 0 — unsatisfiable on a correct file**
- **Found during:** Task 3.
- **Issue:** The pre-plan baseline count was already **1**, not 0: `tests/test_arena_runner.py:533` legitimately says "subprocess" in a comment explaining that the git call it describes is patched OUT. The gate fails on untouched source and could only be satisfied by editing an unrelated, load-bearing rationale comment in another plan's territory.
- **Resolution:** Did NOT edit the pre-existing comment. Implemented the property the gate was reaching for — that no case spawns a process — as `NoProcessSpawnTest`, an AST scan for `import subprocess` / `from subprocess import` / `subprocess.<attr>`, with a companion case proving the scanner fires on both spellings. This is strictly stronger than the grep and is itself two-sided. The absolute `grep -c` count is now 11, all of it in the guard and its own docstring.

**3. `grep -c "pair-subset|pair_subset" >= 2` and `grep -c "assertRaises|SystemExit"` delta `>= 9` — line-count proxies defeated by a shared helper**
- **Found during:** Task 3.
- **Issue:** Both gates count LINES containing a token, which undercounts a suite whose `SystemExit` assertion is factored into one `_CliCase._cli_failure` helper (13 refusal cases route through it) and whose strict-subset case deliberately OMITS the flag, that being the default under test.
- **Resolution:** Did not pad with redundant assertions. Added seven further cases that carry independent value and happen to close the counts: `--pair-subset strict` typed explicitly must behave identically to omitting it (this repository has already shipped exactly one argparse bug where a declared default and omitted behaviour diverged — see the L-11 comment block); a registered corpus whose file has vanished; an unreadable registry; an absent `--record`; an absent `--corpus`; two records naming one corpus; two candidate names in one corpus-baselines table. Final deltas: `assertRaises|SystemExit` +10, `assertIn(` +36, `pair-subset` 2, `allow-cross-corpus` 9.

### Stale planning documents confirmed, not "fixed"

Per the wave briefing, `02-RESEARCH.md:754` and `02-VALIDATION.md`'s "D-45 inverse" row assume control and probe live in separate corpora with differing `dataset_sha256`. D-46/D-25 lock the opposite. The `contrast` subcommand implements the D-46 shape (one record, one corpus, three arms) and its subparser description states plainly that the research note is stale, so a reader following it does not conclude the CLI is missing a second `--record`. **No working code was changed to match the stale documents.**

---

**Total deviations:** 0 source deviations; 3 reported gate defects, 1 of which required a comment reword.
**Impact on plan:** None on scope. All seven added test cases are inside the plan's declared `files_modified`.

## Issues Encountered

- **The `allow_cross_corpus` flag is not observable from outside the CLI in the default shape.** Because the D-45 gate refuses `--probe-record`/`--probe-corpus` whenever the flag is absent, there is no reachable invocation in which a differing digest meets an unset flag. A hardcoded `allow_cross_corpus=True` is therefore behaviourally identical from the outside. The must-have ("the CLI never sets it implicitly") is asserted as a call-argument property instead, with the recording wrapper delegating to the real `paired_contrast` so the contrast still has to succeed for the assertion to mean anything.
- **`CrossCorpusGateTest` needed the record's sessions to span both corpora.** With sessions covering only corpus A, `arm_from_run` fails first with "matched N corpus rows but no run sessions" and never reaches `align_on_pair_id` — which would have proven the wrong thing. The `_ContrastFixture._publish` helper takes an `extra_rows` argument for exactly this.

## Deferred Items

- **Owed to `docs/STATUS.md` (owned this wave by the 02-09 sibling; the orchestrator should place it):** the four new tuned constants introduced here are all CLI defaults rather than scoring knobs, and each is principled rather than fitted — `--control-arm` default `control` and `--probe-arm` default `probe_sonnet` (both are `schema.ARMS` values fixed by D-46), and `--pair-subset` default `strict` (the honest refusal, per MEAS-06). None is a magic number and none affects a score; a single line noting that `arena/run_arena.py` adds no tier-3 constants would be accurate.
- **Not owed, but worth a note for 02-11/02-12/02-13:** the exact operator commands are now stable. The contrast headline is `run_arena contrast --record <probe-run> --corpus probe.v1`, the MEAS-13 cross-check adds `--control-arm probe_sonnet --probe-arm probe_haiku --pair-subset shared`, and the D-53 table is `run_arena corpus-baselines --record public=<dir> --record expanded_dev.v1=<dir> --record expanded_confirm.v1=<dir> --record probe.v1=<dir>`. Reproducing `run-a` still requires typing `--exploration disabled --lexical-mode auto`.

## Known Stubs

None. Every symbol this plan created is wired to a real caller and exercised through `main(argv)`.

## Threat Flags

None. Every file touched is covered by the plan's existing threat register; no new network endpoint, auth path or trust boundary was introduced. `T-02-03` (path traversal via a `--dataset` or `--record` name), `T-02-07` (measuring a drifted corpus), `T-02-09` (four different-corpus rows reaching `LEADERBOARD.md`), `T-02-42` (an implicit cross-corpus contrast), `T-02-27` (a silently narrowed pair set), `T-02-33` (a reduced resample count) and `T-02-34` (a broad catch swallowing a guard failure) each have a mitigation and at least one asserting test.

## Next Phase Readiness

Ready. Plans 02-11, 02-12 and 02-13 are operator-run and every command they need now exists and is covered. Two things the orchestrator should carry forward:

- `data/datasets.json` does not exist yet, and that is correct: `resolve_dataset` treats a missing registry as "every value is a plain path", so the CLI works today and starts enforcing digests the moment the first corpus is frozen.
- The four corpus names this CLI validates are `public` (by literal) plus any `name.vN` — so `expanded_dev.v1`, `expanded_confirm.v1` and `probe.v1` are accepted, and an unversioned typo is refused with a message naming the required suffix.

## Self-Check: PASSED

- Files claimed as modified exist: `arena/run_arena.py`, `tests/test_arena_runner.py`, `.planning/phases/02-expanded-dataset-paraphrase-probe/02-10-SUMMARY.md`.
- Commits claimed exist on this branch: `b0920db`, `acbb875`, `ad2938e`, `7b3b825`.
- Working tree clean; no file outside the plan's declared `files_modified` was touched, and `STATE.md` / `ROADMAP.md` / `docs/STATUS.md` / `arena/datasets/generate.py` were not modified.

---
*Phase: 02-expanded-dataset-paraphrase-probe*
*Completed: 2026-09-01*
