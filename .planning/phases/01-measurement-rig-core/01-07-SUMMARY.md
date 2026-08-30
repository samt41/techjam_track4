---
phase: 01-measurement-rig-core
plan: 07
subsystem: measurement
tags: [leaderboard, reporting, determinism, output-rounding, stated-assumptions, stdlib]

# Dependency graph
requires: ["01-06"]
provides:
  - "`arena/leaderboard.py` — the D-13 four-table payload and its pure-function Markdown view"
  - "`experiments/baselines/leaderboard.json` — the committed source of truth Phase 3/4/5 append to"
  - "`experiments/LEADERBOARD.md` — the committed judge-readable report, generated and never hand-edited"
  - "`HOW_TO_READ` — the stated-assumptions block explaining the three divergent numbers, the deliberate absence of per-scenario Holm correction, and all four verdict values"
  - "`tests/test_arena_leaderboard.py` — 29 tests in 0.074 s, including the committed-artifact assertions for ROADMAP Success Criteria 1, 2 and 4"
affects: [01-08, 01-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "The output boundary owns its rounding: `round(efficiency(summary), 6)` is applied where the evaluator applies it (`local_evaluator.py:286`), and the unrounded value never reaches a file"
    - "Two opposite float rules coexist deliberately in one module, each with a comment saying why the other does not apply, so a later reader cannot 'harmonise' them"
    - "The Markdown is a pure function of the payload — a committed test asserts the committed file equals `render_markdown(committed_payload)`, so a hand-edit fails the suite"
    - "Values below 1e-4 render in scientific notation, so a permutation p at its Phipson-Smyth floor can never print as `0.000000`"
    - "The production-scale generation is an operator command; the suite caps adjudications at `resamples=200` and reads the committed JSON for its anchor assertions"

key-files:
  created:
    - arena/leaderboard.py
    - tests/test_arena_leaderboard.py
    - experiments/baselines/leaderboard.json
    - experiments/LEADERBOARD.md
  modified: []

key-decisions:
  - "Task 1's acceptance grep `grep -v '^\\s*#' arena/leaderboard.py | grep -cE '(evaluator|starter\\.|experiments\\.)'` returning 0 is unsatisfiable against Task 1's OWN requirement that `assumptions[\"efficiency_rounding\"]` name `local_evaluator.py:286`, and against Task 2's requirement that the rendered report contain that same substring. Read as intended (no import of and no dynamic reference to the forbidden packages) and verified with an import-anchored grep returning 0 plus the AST boundary scan in `tests/test_arena_boundary.py`, which is the real guard"
  - "Added a `provenance` field to `CandidateEntry` and to each candidate object. T-01-16b names three mitigations for the synthetic-control spoofing surface and one of them is 'carries a fixture provenance field'; the plan's key list omitted it. The field is asserted by `test_the_synthetic_control_is_labelled_as_a_fixture`"
  - "`assumptions.resample_count` is derived from the adjudication rows rather than read from the constant, so a report generated at a test resample count is visible in its own payload. `RESAMPLE_COUNT` is the declared default only when there are no rows"
  - "`E[max k]` renders as `0.0` and `corrected dTS == dTS` exactly at k=1, which is correct: with one candidate no selection happened, so no winner's-curse correction is owed"
  - "Left `REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` untouched — the orchestrator owns those writes after the wave merges"

patterns-established:
  - "A generated view is kept honest by a test that re-renders the payload and compares it to the committed file, rather than by a convention that says not to edit it"
  - "A prose figure quoted from a planning document is checked against the number the report's own table prints, and the two are reconciled in the report rather than left to disagree"

requirements-completed: [MEAS-01, MEAS-02, MEAS-06, MEAS-09]

# Metrics
duration: 26min
completed: 2026-08-30
---

# Phase 01 Plan 07: Leaderboard Summary

**ROADMAP Success Criteria 1, 2 and 4 are now satisfied by a committed report built entirely from retained data with the agent never invoked — and the one number in it that a judge would most plausibly read as an inconsistency, the `0.7575` Efficiency that `arena.metrics` computes as `0.7575000000000001`, is rounded exactly where the evaluator rounds it and explained in the report itself.**

## Performance

- **Duration:** ~26 min
- **Tasks:** 3
- **Files created:** 4 (no existing file modified)
- **Test suite:** 291 → 320 tests, all green in 4.123 s
- **This module:** 29 tests in **0.074 s** (budget: ≥12 methods, <5 s)
- **Report generation:** **1.45 s** at 10,000 replicates, against a ~60 s budget

## Accomplishments

- **The report is committed, and it is a report — not a terminal.** `experiments/baselines/leaderboard.json` (174 lines) is the source of truth; `experiments/LEADERBOARD.md` (142 lines) is a generated view. Both are tracked: `git check-ignore -q experiments/baselines/leaderboard.json` exits `1`.
- **Efficiency reads `0.7575` exactly.** `repr(candidate["efficiency"]) == "0.7575"` is asserted, so a payload carrying the `0.7575000000000001` tail fails. TechnicalScore `0.76884`, HR@10 `0.92`, MRR `0.524466`, MTTC `3.425` all match the anchor digit for digit.
- **The two opposite float rules are both correct and both commented.** Efficiency is rounded at the output boundary because the evaluator rounds it there (`local_evaluator.py:286`); `binomial_standard_error` is written UNROUNDED because it is an analysis quantity asserted at `places=12`, not a figure the evaluator emits. `test_scenario_sigma_is_written_unrounded` asserts `assertNotEqual(sigma, 0.094868)` so a well-meaning harmonisation fails loudly.
- **HR@10 is provably not the sort key.** `test_highest_hit_rate_is_not_first_when_its_score_is_not` builds `wide-recall` (HR@10 `1.0`, TS `0.55`, every hit at rank 10 on turn 10) against `sharp-ranking` (HR@10 `0.8`, TS `0.80`, eight hits at rank 1 on turn 1). The entry with the strictly higher HR@10 sorts **last**. The ordering test also feeds three entries in scrambled order and asserts closed-form scores `1.00 / 0.83 / 0.68`, each hand-checkable from fixed ranks and turns.
- **The tie-break is asserted in both input orders.** Two entries with identical sessions and different names produce an equal TechnicalScore and different fingerprints; the rendered order is ascending-fingerprint whichever way they are fed in.
- **Every adjudication row is re-derivable.** The committed row prints sigma-hat `0.003725`, `k = 1`, `E[max k] = 0.0`, `corrected dTS = 0.011931`, MDD `0.010435` as separate columns. At k=1 no selection happened, so `corrected dTS == dTS` exactly — which the report shows rather than asserts.
- **The committed adjudication was generated at production scale.** `resamples == 10000` on every row is an acceptance-asserted field, so a report generated at a test resample count cannot be committed unnoticed (T-01-20). `dTS = 0.011931000000000025` reproduces 01-06's m=10 anchor control exactly; `holm_p = 0.002700`, verdict `win`, `failed criteria` empty.
- **The win-iff-empty identity is checked against the committed artifact.** `(verdict == "win") == (failed_criteria == [])` is asserted on every committed row — the identity 01-09 will assert, checked here too so a `classify_verdict` regression cannot reach a judge's copy of the report.
- **A hand-edited Markdown fails the suite.** `test_the_committed_markdown_matches_the_committed_payload` re-renders the committed payload and compares byte for byte. That is T-01-16 turned into a check rather than a convention.
- **The report is byte-reproducible.** Regenerated twice, once under `PYTHONHASHSEED=1`, `git diff --quiet -- experiments/baselines/leaderboard.json experiments/LEADERBOARD.md` exits `0` each time.
- **A permutation p can never render as zero.** Values below `1e-4` print in scientific notation. `test_a_small_probability_never_renders_as_zero` injects `1/10001` and asserts `9.9990e-05` appears and no `` `0.000000` `` does — the upstream Phipson-Smyth floor made visible rather than silently truncated.
- **The empty-adjudication path renders honestly.** A payload with no rows produces a `| _none_ |` fallback row and a `_not set_` baseline, never a header-and-separator with nothing underneath.

## Task Commits

1. **Task 1: Build the leaderboard payload — four tables, TechnicalScore-descending order** — `cb675b9` (feat)
2. **Task 2: Render the Markdown view with the stated-assumptions block** — `113d3ba` (feat)
3. **Task 3: Test the report and commit the first leaderboard built from the anchor record** — `dafd1ee` (test)

## Verification Results

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_leaderboard` | **29 tests, OK, 0.074 s** (budget: ≥12 methods, <5 s) |
| `uv run python -m unittest -v tests.test_arena_boundary` | **8 tests, OK, 0.018 s** |
| `uv run python -W error::ResourceWarning -m unittest` | **320 tests, OK, 4.123 s** (291 baseline + 29 new) |
| `arena/leaderboard.py` line 1 | `from __future__ import annotations` |
| Import-anchored boundary grep | **0** (AST boundary scan green; see Deviations) |
| `grep -c 'round(efficiency' arena/leaderboard.py` | **1** |
| `grep -c 'datetime\|time\.\|random' arena/leaderboard.py` | **0** — no clock, no RNG in the render path |
| `grep -c 'Agent' tests/test_arena_leaderboard.py` | **0** |
| `grep -c 'RESAMPLE_COUNT' tests/test_arena_leaderboard.py` | **0**; both adjudications pass `resamples=FAST_RESAMPLES` (200) |
| `LEADERBOARD_SCHEMA_VERSION` | **1** |
| Top-level payload keys | exactly `adjudication`, `assumptions`, `baseline_fingerprint`, `candidates`, `hit_rate_curve`, `scenario_breakout`, `schema_version` |
| Anchor candidate | `0.92 / 0.524466 / 3.425 / 0.7575 / 0.76884`, `repr(efficiency) == "0.7575"`, `sample_count 200` |
| Anchor HR@K curve | `{"1": 0.385, "3": 0.59, "5": 0.715, "10": 0.92}` |
| Anchor scenario breakout | n `10, 80, 80, 30`; sigma `0.09486832980505137, 0.02436698586202242, 0.03354101966249684, 0.054772255750516606` (places=12); decision-grade `false, true, true, false` |
| Committed adjudication | 1 row, `resamples 10000`, `dTS 0.011931000000000025`, `holm_p 0.0026997300269973002`, `MDD 0.010435182318398023`, sigma-hat `0.0037247420677878683`, `k 1`, `E[max k] 0.0`, `corrected == dTS`, verdict `win`, `failed_criteria []` |
| Win-iff-empty on the committed rows | holds |
| Ordering, three entries fed scrambled | `1.00, 0.83, 0.68` → `perfect, middle, worst` |
| HR@10 tripwire | `sharp-ranking` (HR `0.8`, TS `0.80`) first; `wide-recall` (HR `1.0`, TS `0.55`) last |
| Tie-break | equal scores → ascending fingerprint, asserted in both input orders |
| Markdown headings | all five present, including `## How to read this report` |
| Required substrings | `0.094868`, `0.054772`, `paired-difference`, `not Holm-corrected`, `two best-case session flips`, `local_evaluator.py:286`, `experiments/baselines/leaderboard.json`, `experiments/RUNS.md` |
| `0.086` occurrences in the render | **1**, on a line that also contains `illustrative` |
| All four `Verdict` values inside the how-to-read block | present |
| Table separator rows | 4, each containing `---:` |
| Trailing newline | exactly one |
| Empty adjudication | `| _none_ |` fallback and `_not set_` baseline |
| `git check-ignore -q experiments/baselines/leaderboard.json` | exit **1** (not ignored) |
| Regeneration reproducibility | `git diff --quiet` exit **0**, twice, including under `PYTHONHASHSEED=1` |
| Generation cost | **1.45 s** at `RESAMPLE_COUNT = 10000` (budget ~60 s) |
| Deletions since base `52fd4ed` | none |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree spawned at a stale base commit**

- **Found during:** startup, before any edit
- **Issue:** Worktree HEAD was `9faf85c`, an ancestor of the required base `52fd4ed`, so waves 1-4 output — including `arena/adjudication.py`, `arena/statistics.py` and `arena/metrics.py`, this plan's dependencies — was absent. Every task would have failed on a missing import. Six for six worktrees in this phase have hit this; 01-05 and 01-06 both recorded it.
- **Fix:** HEAD was confirmed on the `worktree-agent-*` branch with a clean tree, then `git reset --hard 52fd4ed0a447e6b3504602e892c246ca8ba3f292`. No protected ref was touched and no `git update-ref` was used.
- **Verification:** `git rev-parse HEAD` returns `52fd4ed`; all three dependency modules present.

**2. [Rule 1 - Bug] An acceptance criterion that contradicts its own task**

- **Found during:** Task 1 acceptance check
- **Issue:** Task 1 requires `grep -v '^\s*#' arena/leaderboard.py | grep -cE '(evaluator|starter\.|experiments\.)'` to return `0`, and in the same breath requires `assumptions["efficiency_rounding"]` to name `local_evaluator.py:286`. That string contains `evaluator`, so any conforming implementation returns `1`. Task 2 compounds it by requiring the *rendered report* to contain the same substring. The criterion is unsatisfiable as written, exactly like 01-06's `corrected_delta >= PRACTICAL_FLOOR` case.
- **Fix:** Read as intended — no *import of* and no *dynamic reference to* the forbidden packages — and verified two ways. `grep -v '^\s*#' arena/leaderboard.py | grep -cE '^\s*(from|import)\s+(evaluator|starter\.|experiments\.)'` returns `0`. The real guard, `tests/test_arena_boundary.py`'s AST scan (which also walks string constants to catch `importlib.import_module`), passes: `local_evaluator.py:286` splits on `.` to `local_evaluator`, which is not the `evaluator` package. The only two naive matches are the mandated prose citations, one in the payload and one in `HOW_TO_READ`.
- **Files modified:** none (check corrected, not code)

**3. [Rule 1 - Bug] A prescribed prose figure disagreed with the report's own table**

- **Found during:** Task 3, after the first production generation
- **Issue:** The plan prescribes `HOW_TO_READ` stating "the paired bootstrap SE is `0.003715`". The committed adjudication row measures `0.0037247420677878683` for that exact comparison at `R = 10,000`; `01-RESEARCH.md`'s `0.003715` was measured at a different resample count. A report whose stated purpose is to eliminate apparent inconsistencies would have shipped one on its own page.
- **Fix:** The sentence now reads "roughly `0.0037` where an effectively unpaired one is `0.025922`, a sevenfold difference", and then names `01-RESEARCH.md`'s `0.003715` explicitly as that document's figure at its own resample count, stating that the table below prints the SE actually observed. Both numbers survive; neither is presented as the other. The MDD figure the plan prescribes (`roughly 0.0104`) needed no change — the measured value is `0.010435`.
- **Files modified:** `arena/leaderboard.py`
- **Commit:** `dafd1ee`

**4. [Rule 2 - Missing Critical] The synthetic control had no provenance field**

- **Found during:** Task 1
- **Issue:** Threat T-01-16b lists three mitigations for a validation control being read as a measured candidate: a `synthetic-` name prefix, a stated convention in the report, and "carries a fixture provenance field". The plan's `CandidateEntry` field list and its candidate-object key list both omitted the third. Name prefixes are a display convention; a machine consumer reading `leaderboard.json` had nothing to key on.
- **Fix:** Added `provenance: str = ""` as `CandidateEntry`'s last field, populated by `entry_from_record` from the record's own `provenance` string and emitted as a `provenance` key on each candidate object. The synthetic arm carries "deterministic fixture derived from experiments/baselines/anchor-legacy by promote_hits_to_rank_one(sessions, 10); a validation control that proves the adjudication machinery is exercised, never an evaluation run". Asserted by `test_the_synthetic_control_is_labelled_as_a_fixture`. The top-level key set is unchanged, so the "exactly seven keys" criterion still holds.
- **Files modified:** `arena/leaderboard.py`
- **Commit:** `cb675b9`

### Scope Notes (not deviations)

- **One import beyond the plan's listed set.** `RESAMPLE_COUNT` is imported from `arena.statistics` so `assumptions.resample_count` has a declared default when the adjudication array is empty. It stays inside the `arena` package and breaches no boundary.

---

**Total deviations:** 4 auto-fixed (1 blocking, 1 defective check, 1 real inconsistency, 1 missing threat mitigation)
**Impact on plan:** No scope creep and no acceptance criterion weakened. Deviation 1 is environmental; 2 corrects a check rather than a behaviour, and the behaviour is separately proven by the AST scan; 3 fixes a genuine self-inconsistency in the shipped report; 4 closes a threat-register gap the plan's field list had dropped.

## Issues Encountered

- **The 10,000-replicate generation costs 1.45 s, not ~60 s.** 01-06 projected roughly 5 s per single-candidate adjudication at production R, and the VALIDATION doc budgeted ~60 s per generation. The measured cost for a 200-session, one-candidate adjudication at `R = 10,000` is under 1.5 s. That is worth recording because the budget shaped a design decision — keeping the generation out of the suite — and the decision is still right for a different reason: it is an *operator* step that writes committed files, and a test that rewrites tracked artifacts would be a suite that cannot be run on a dirty tree. The cost is not what justifies the separation.
- **`E[max k]` is `0.0` on the committed row and that is correct, not a stub.** With a single candidate no selection occurred, so `expected_max_of_k(1)` is `0.0` by definition and `corrected dTS == dTS` exactly. A reader scanning for evidence that the winner's-curse correction was applied will find a zero; the report prints sigma-hat and `k` beside it so the zero is legible as "k=1, nothing to correct" rather than as "correction skipped". Once 01-08 adds a second real arm the column becomes non-zero.
- **The synthetic control sorts *above* the anchor.** `synthetic-promote-10` has the higher MRR and therefore the higher TechnicalScore, so the honest TechnicalScore-descending order puts a fixture at the top of the candidate table. That is precisely why T-01-16b matters, and it is why the generated-file warning states the `synthetic-` convention above the tables rather than in a footnote.
- **Windows line endings are handled by git, not by the writer.** `write_json` and `Path.write_text` translate `\n` to CRLF on this platform, and `core.autocrlf` normalizes on staging, so `git diff --quiet` after regeneration is clean. The reproducibility gate was verified against the committed bytes, not against an in-memory string.
- **`0.003715` versus `0.0037247`** — see Deviation 3. Anyone comparing this report with `01-RESEARCH.md` should expect agreement to three significant figures, which the report now says outright.

## Known Stubs

None. Every symbol in the plan's artifact table exists and is exercised: `LEADERBOARD_SCHEMA_VERSION`, `HOW_TO_READ`, `LEADERBOARD_JSON_PATH`, `LEADERBOARD_MARKDOWN_PATH`, `CandidateEntry`, `entry_from_record`, `build_leaderboard`, `render_markdown`, `write_leaderboard`, and all three required test classes (`LeaderboardPayloadTest`, `LeaderboardOrderingTest`, `LeaderboardMarkdownTest`) plus `CommittedLeaderboardTest` for the committed-artifact assertions. Both committed artifacts are populated with real values, not placeholders.

## Threat Flags

None beyond the plan's register. The module performs two file writes to fixed, tracked paths and reads two files from a record directory; it opens no network endpoint, reads no credential, and introduces no schema at a trust boundary. The nine register rows are mitigated as shipped:

| Threat ID | Mitigation as shipped |
|---|---|
| T-01-16 | `render_markdown` is pure (no I/O, no clock, no RNG — grep-verified); the file carries a "never hand-edit" warning naming the JSON as source of truth; `test_the_committed_markdown_matches_the_committed_payload` re-renders and compares byte for byte; two regenerations leave `git diff --quiet` clean |
| T-01-16b | `synthetic-` name prefix, a `provenance` field on the entry and on the emitted candidate object (Deviation 4), and the convention stated in the generated-file warning above the tables; asserted by `test_the_synthetic_control_is_labelled_as_a_fixture` |
| T-01-16c | `round(efficiency(summary), 6)` at the payload boundary with a comment citing `local_evaluator.py:286`; asserted as `repr(efficiency) == "0.7575"` against the committed artifact |
| T-01-13 | sigma-hat, `k` and `E[max k]` are three separate columns in both the JSON and the Markdown; the assumptions block states sigma-hat is the paired-difference SE and why it is roughly an order of magnitude smaller than the 0.019 figure quoted elsewhere |
| T-01-17 | TechnicalScore descending with an ascending-fingerprint tie-break, asserted by a test in which the strictly-highest-HR@10 entry sorts last |
| T-01-05 | `git check-ignore -q experiments/baselines/leaderboard.json` exits `1`; both artifacts are tracked and committed |
| T-01-20 | The suite caps adjudications at `resamples=200` and reads the committed JSON for its anchor assertions; `resamples == 10000` is asserted on every committed row; the module runs in 0.074 s |
| T-01-18 | Accepted. The report carries aggregate metrics and per-scenario counts only — no ground truth, no catalog content, no per-session identifiers |
| T-01-SC | Zero packages installed; `dependencies = []` unchanged |

## Notes for the Orchestrator

- `REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` were deliberately **not** modified. **MEAS-01, MEAS-02, MEAS-06 and MEAS-09** are ready to be marked complete centrally after the merge.
- Four files were touched, all new: `arena/leaderboard.py` (537 lines), `tests/test_arena_leaderboard.py` (547), `experiments/LEADERBOARD.md` (142) and `experiments/baselines/leaderboard.json` (174). Nothing owned by a sibling plan was created or edited; `tests/arena_fixtures.py` was reused unchanged.
- `arena/leaderboard.py` passes 01-02's AST boundary scan — confirmed by running `tests.test_arena_boundary` directly after each of the three commits.
- **The stale-worktree-base fault recurred** (`9faf85c` instead of `52fd4ed`). Environmental and recurring, not plan-specific.
- The generation script is an operator command and was deliberately **not** committed; 01-09's `arena/run_arena.py adjudicate` is the permanent home for it. Its exact behaviour is recorded below so 01-09 can reproduce the committed bytes.

## Next Phase Readiness

- **For 01-08:** `entry_from_record(run_directory)` is the only thing a new baseline record needs — it reads `summary.json` and `sessions.jsonl`, builds the `CandidateSpec`, and fails closed on an unrecorded `code_revision_dirty`. Once `experiments/baselines/run-a/` exists, add its entry to the generation call and the report picks it up with no code change.
- **For 01-09:** to regenerate the committed bytes, build the anchor entry via `entry_from_record`, build `synthetic-promote-10` from `promote_hits_to_rank_one(anchor.sessions, 10)` with `CandidateSpec(name="synthetic-promote-10", code_revision="unknown_revision", code_revision_dirty=True, overrides=(), catalog_sha256="unknown", dataset_sha256="unknown")`, adjudicate the synthetic arm against the anchor arm at the default `RESAMPLE_COUNT`, and call `build_leaderboard((anchor, synthetic), rows, baseline_fingerprint=anchor.fingerprint)` then `write_leaderboard(payload)`. The anchor fingerprint is `b8ce126916a045dab0598fb27b4dd3638a3d9d9b61b2025855a8760c6323dc2e`; the synthetic one begins `6eec1db14d0c`. Any change to entry order, spec fields, or `HOW_TO_READ` changes the bytes.
- **For 01-09:** the win-iff-empty identity is already asserted against the committed artifact in `test_the_committed_adjudication_was_generated_at_production_scale`, so 01-09 can extend rather than establish it.
- **Rendering contract for future columns:** `_cell` is the single formatting seam — 6 dp fixed, scientific below `1e-4`, `yes`/`no` for booleans, `0.0` for exact zero. Adding a column means adding a header, an alignment entry and a `_cell` call, and nothing else.
- No blockers.

## Self-Check: PASSED

All four claimed files exist and are tracked (`arena/leaderboard.py`, `tests/test_arena_leaderboard.py`, `experiments/baselines/leaderboard.json`, `experiments/LEADERBOARD.md`); all three claimed commits (`cb675b9`, `113d3ba`, `dafd1ee`) are present in `git log 52fd4ed..HEAD`; `git diff --diff-filter=D --name-only 52fd4ed HEAD` reports no deletions; the working tree is clean.

---
*Phase: 01-measurement-rig-core*
*Completed: 2026-08-30*
