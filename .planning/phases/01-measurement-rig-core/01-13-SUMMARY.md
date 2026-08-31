---
phase: 01-measurement-rig-core
plan: 13
subsystem: testing
tags: [arena, fingerprint, provenance, argparse, unittest, sqlite-free]

# Dependency graph
requires:
  - phase: 01-measurement-rig-core
    provides: "CandidateSpec fingerprinting, run_candidate's published record, the arena CLI, and tests/test_arena_runner.py's fake-agent seams"
provides:
  - "A CLI whose fingerprinted overrides describe the invocation, identically across both entry paths"
  - "A provenance-collision refusal on the published summary, symmetric with import_legacy_results._build_summary"
  - "FingerprintIdentityTest: cross-entry-path digest identity, verbatim flag recording, and collision refusal, all mutation-verified"
affects: [arena bake-off, leaderboard adjudication, phase 3 candidate knobs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Override flags record the invocation (default=None + omit-if-unset), never argparse-injected effective values"
    - "A writer that splats foreign output over its own provenance refuses on intersection before constructing the record"

key-files:
  created: []
  modified:
    - arena/run_arena.py
    - arena/arena.py
    - tests/test_arena_runner.py

key-decisions:
  - "Fixed the identity defect at argparse (default=None) rather than by canonicalising ALLOWED_OVERRIDES with agent defaults, because canonicalising would change a committed record's derived digest"
  - "The fingerprint describes the INVOCATION, not the effective configuration: typing --exploration disabled and omitting it are two honest digests for one Agent"
  - "Kept the harness-result splat last and raised on collision, rather than reordering it first, which would silently drop harness output instead of surfacing the clash"
  - "Pinned code_revision in the new tests rather than asserting the two verification-time digests, which were computed over a revision captured at that moment"

patterns-established:
  - "Mutation-verified gap closure: every new guard is proven to fail when its guard is removed, and the mutation reverted with git diff --stat confirmed clean"
  - "Grep acceptance criteria are checked in both directions; comment prose that matches a code-shaped pattern is reworded so the criterion measures code"

requirements-completed: [MEAS-14]

# Metrics
duration: 42min
completed: 2026-08-31
---

# Phase 01 Plan 13: Fingerprint Identity and Provenance Collision Summary

**One configuration now mints one fingerprint whichever entry path expressed it, and a harness result that would overwrite an arena-written provenance field is refused before anything is written**

## Performance

- **Duration:** ~42 min (including a provider rate-limit interruption between Tasks 2 and 3)
- **Tasks:** 3
- **Files modified:** 3
- **Test suite:** 344 tests, all passing (`uv run python -W error::ResourceWarning -m unittest discover -s tests`); `tests.test_arena_runner` went 18 → 23 methods

## Accomplishments

- **The MEAS-14 identity defect is closed.** `--exploration` and `--lexical-mode` defaulted to `"disabled"` and `"auto"`, never `None`, so argparse injected them into the hashed `overrides` and the module's own omit-if-unset filter never fired. The default-everything configuration fingerprinted `25e5f553460050d9` through the CLI and `af7bdf3a928ec07f` programmatically — one configuration, two identities, in the module whose job is to give a configuration exactly one. Both flags now default to `None`, so the filter is the only rule and applies to all three override flags.
- **`adjudicate`'s "a candidate must not share the baseline's fingerprint" guard is meaningful again.** Before this, two specs describing the same configuration could pass it.
- **The provenance write path refuses to lie.** `_PROVENANCE_KEYS` (11 keys, built from the imported `SPEC_NAME_FIELD` rather than a literal so the guard and the writer cannot drift) is intersected against the harness result and raises `ArenaStoreError` before the summary dict is constructed and before anything is written. The two sibling writers now refuse on the same hazard in the same way.
- **Both fixes are mutation-verified**, not just asserted: each new test was proven to fail when its guard is removed.

## Task Commits

1. **Task 1: Make the CLI record the invocation instead of injecting argparse defaults** — `5bd1e7b` (fix)
2. **Task 2: Refuse to publish a summary whose harness output collides with a provenance key** — `a99617f` (fix)
3. **Task 3: Prove one configuration yields one fingerprint across both entry paths** — `979a9db` (test)

## Files Created/Modified

- `arena/run_arena.py` — `--exploration` and `--lexical-mode` now `default=None`; `choices=` tuples untouched, so a passed value is still validated. The comment at the override construction now describes behaviour rather than intent and records the measured defect, why omitting is safe (`starter/agent.py:18-25` supplies the identical constructor defaults, so an omitted override builds a byte-identical Agent), why canonicalising was rejected, and the semantics change for readers of the committed `run-a`/`run-b`/`run-c` records.
- `arena/arena.py` — new module-level `_PROVENANCE_KEYS` frozenset beside `PROVENANCE`; `ArenaStoreError` imported from `arena.store`; the intersection check raises in `run_candidate` after `result` is available and before `write_sessions`, so a refusal writes nothing at all. The splat stays last in the summary literal.
- `tests/test_arena_runner.py` — new `FingerprintIdentityTest` with 5 methods, reusing `_AgentFactory`, `_RecordingAgent`, `_fake_evaluate`, `_sample`, `_session_row`, `_evaluation_result` and `_spec`. No catalog, no SQLite, no real `Agent`; every method uses a `tempfile.TemporaryDirectory` as `--output-root`.

## Decisions Made

- **Fixed at argparse, not at `candidate_overrides()`.** Filling `ALLOWED_OVERRIDES` with agent defaults would also produce one digest per configuration, but it would change a **committed** record's derived fingerprint: `experiments/baselines/synthetic-promote-10/summary.json` stores `overrides = {}` beside the digest derived from it, so canonicalising breaks `test_every_record_derives_the_fingerprint_it_stores` and would trip the stored-versus-derived comparison plan 01-14 adds. The argparse change touches no committed record, because every record carries its own `overrides` mapping and is reconstructed from that. Confirmed: `test_every_record_derives_the_fingerprint_it_stores` still passes.
- **The fingerprint describes the invocation.** An invocation that explicitly types `--exploration disabled` records `{"exploration": "disabled"}` and still fingerprints differently from one that omits the flag, even though both configure a byte-identical Agent. That is the intended semantics and the new tests explicitly disclaim asserting otherwise. Plan 01-15 Task 3 discloses this in `experiments/RUNS.md`; the code comment points there rather than duplicating the prose.
- **Kept the splat last.** Moving the harness result first would also stop the overwrite, but it would silently *drop* harness output on a name clash — the same class of quiet wrongness in the other direction. Raising is the only option that surfaces the clash.
- **Pinned `code_revision` in the new tests** (patching `arena.arena.current_revision`) so the two entry paths can differ on nothing except the overrides mapping under test, and so the identity assertion does not depend on a `git status` subprocess whose answer could change between the two constructions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded two `arena/arena.py` comments so the `**result` acceptance criterion measures code rather than prose**

- **Found during:** Task 2 (provenance collision guard)
- **Issue:** The plan's criterion `grep -c '\*\*result' arena/arena.py` returns `1` was measured against unmodified source, where the only match is the splat itself. The plan simultaneously instructed the guard's comment to explain that `**result` is last in the literal. Writing that comment naturally produced 3 matching lines — the criterion would have failed on a correct implementation.
- **Fix:** Reworded both comments to say "the harness-result splat" and "The harness result is splatted LAST into the summary literal below", preserving the full explanation while leaving exactly one code-level occurrence.
- **Files modified:** `arena/arena.py`
- **Verification:** `grep -n '\*\*result' arena/arena.py` returns exactly one line, `203: **result,`, still the last entry in the summary dict literal.
- **Committed in:** `a99617f` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** No behavioural change; the guard, the splat position, and the recorded rationale are all as the plan specified. No scope creep. `arena/candidate.py` was not touched, as the plan required.

## Verification

All plan verification steps executed.

**Task 1 acceptance (all measured):**

| Check | Expected | Actual |
|---|---|---|
| `grep -c 'default="disabled"'` | 0 | 0 |
| `grep -c 'default="auto"'` | 0 | 0 |
| `grep -c 'default=None'` | 4 | 4 |
| `grep -A2 -e '"--exploration",' -e '"--lexical-mode",' \| grep -c 'default=None'` | 2 | 2 |
| `grep -c 'choices=("disabled", "tail-only")'` | 1 | 1 |
| `grep -c 'choices=("auto", "fts5", "fallback")'` | 1 | 1 |
| `grep -v '^\s*#' \| grep -c 'is not None'` | 1 | 1 |
| `git diff --name-only` for the task | `arena/run_arena.py` only | matched; `arena/candidate.py` untouched |
| `run --help` | exit 0, all three flags listed | exit 0, all three listed |
| `run ... --exploration bogus` | non-zero, argparse choices error | exit 2 |

**Task 2 acceptance (all measured):** `_PROVENANCE_KEYS` count 2; `SPEC_NAME_FIELD` non-comment count 3 (≥2); `**result` count 1 and still last; `ArenaStoreError` count 2; `sorted(_PROVENANCE_KEYS)` prints exactly the 11 expected keys with `candidate_name` arriving via `SPEC_NAME_FIELD`.

**Task 3 acceptance (all measured):** `tests.test_arena_runner` 23 methods (18 pre-existing + 5 new, no reduction); `grep -cE '25e5f553460050d9|af7bdf3a928ec07f'` returns 0; `grep -c 'experiments/baselines'` returns 0; `git status --porcelain experiments/baselines/` empty after the suite ran.

**Mutation checks (both executed and reverted, `git diff --stat` confirmed clean afterwards):**

1. Restoring `--exploration`'s argparse `default="disabled"` → `test_the_cli_default_invocation_agrees_with_the_programmatic_empty_overrides` FAILS with `{'exploration': 'disabled'} != {}`, and `test_an_omitted_flag_is_absent_from_the_overrides` fails alongside it (2 failures). Reverted; `default=None` count back to 4.
2. Removing the `_PROVENANCE_KEYS` intersection check from `arena/arena.py` → `test_harness_output_colliding_with_a_provenance_key_is_refused` FAILS with `ArenaStoreError not raised`, and it is the **only** failure of the five, confirming the clean-publish mirror guard is not coupled to it. Reverted; `_PROVENANCE_KEYS` count back to 2.

**Suites:**

- `uv run python -m unittest -v tests.test_arena_runner` — 23 tests, OK
- `uv run python -m unittest -v tests.test_arena_runner tests.test_arena_boundary` — 26 tests, OK (no new evaluator reference reached `arena/`)
- `uv run python -W error::ResourceWarning -m unittest discover -s tests` — **344 tests, OK, 0 failures, 0 errors**
- `tests.test_arena_leaderboard.CommittedLeaderboardTest.test_every_record_derives_the_fingerprint_it_stores` — OK; no committed record's stored fingerprint changed

## Issues Encountered

- Execution was interrupted by a provider rate limit between Tasks 2 and 3. Tasks 1 and 2 were already committed, the working tree was clean, and Task 3 resumed without redoing any work.
- One transient false alarm while spot-checking: `test_every_record_derives_the_fingerprint_it_stores` appeared to fail when invoked with a guessed class name (`RecordTest`). Re-run under its real class, `CommittedLeaderboardTest`, it passes — and it passed in the full-suite run throughout.

## User Setup Required

None — no external service configuration required. No package was installed; `pyproject.toml` keeps `dependencies = []` and this plan adds no import outside `arena.*` and the standard library.

## Next Phase Readiness

- MEAS-14's guarantee is now a mutation-verified assertion rather than a comment. Downstream adjudication and the leaderboard's baseline-fingerprint guard can be trusted.
- **Consumed by plan 01-14:** the stored-versus-derived fingerprint comparison it adds will hold, because no committed record's `overrides` mapping changed.
- **Consumed by plan 01-15 Task 3:** `arena/run_arena.py`'s comment defers the operator-facing disclosure to `experiments/RUNS.md` — that a future flag-free invocation of a configuration matching `run-a`/`run-b`/`run-c` records `{}` and mints a different digest while configuring a byte-identical Agent. That disclosure is still owed.
- **Not addressed here, by plan:** WR-11 (`code_revision_dirty()`'s missing `cwd` and `timeout`) was not selected for this gap-closure round; the fail-closed-to-dirty behaviour stands. `ALLOWED_OVERRIDES` was deliberately not extended — D-10 reserves that for Phase 3.

## Self-Check: PASSED

- `arena/run_arena.py` — FOUND, modified
- `arena/arena.py` — FOUND, modified
- `tests/test_arena_runner.py` — FOUND, modified
- Commit `5bd1e7b` — FOUND
- Commit `a99617f` — FOUND
- Commit `979a9db` — FOUND

---
*Phase: 01-measurement-rig-core*
*Completed: 2026-08-31*
