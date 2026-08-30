---
phase: 01-measurement-rig-core
plan: 02
subsystem: testing
tags: [ast, static-analysis, boundary, sha256, immutability, unittest, stdlib]

# Dependency graph
requires:
  - "01-01 (`arena/__init__.py` and `arena/import_legacy_results.py` must exist so the boundary scan cannot pass vacuously)"
provides:
  - "`arena/evaluator_bridge.py` — the sole permitted evaluator seam (D-08), re-exporting exactly `catalog_index`, `evaluate`, `load_jsonl`"
  - "`tests/test_arena_boundary.py` — MEAS-15 and ROADMAP Success Criterion 5 as continuously verified facts rather than prose"
  - "`evaluator_references(path)` — a reusable AST + string-constant scanner that any later plan can point at a new module"
  - "A SHA-256 pin on `evaluator/local_evaluator.py` asserted on every test run"
affects: [01-03, 01-04, 01-05, 01-06, 01-07, 01-08, 01-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Static-analysis test as an architectural guard — first of its kind in this repository (01-PATTERNS.md marked it 'no analog')"
    - "Detector non-vacuity is itself proven, on tempfile fixtures, so a broken detector cannot masquerade as a satisfied invariant"
    - "Import-boundary scanning covers string constants, not just import nodes, because dynamic import launders the module name through data"

key-files:
  created:
    - arena/evaluator_bridge.py
    - tests/test_arena_boundary.py
  modified: []

key-decisions:
  - "Place the real module docstring at line 1 and `from __future__ import annotations` at line 3 — the plan asked for both 'future import on line 1' and 'a module docstring', which are mutually exclusive; `experiments/analyze_misses_b1.py` is the repo precedent for docstring-first"
  - "Prove the `ast.Constant` arm is load-bearing with an in-memory mutant of the scanner rather than by editing and reverting the live test file, because two sibling executors are running this same suite concurrently"
  - "Assert `>= 1` non-bridge arena module rather than `>= 2` — the stronger form would break when a later plan legitimately removes the one-off importer, and `>= 1` already closes the vacuous-pass hole it exists to close"
  - "Scan `experiments/analyze_public.py` in the same test as the arena modules — plan 01-04 imports `code_revision` from it, so it is a transitive seam that an `arena/`-only scan would never see"

patterns-established:
  - "The bridge is a pure re-export: zero functions, zero classes, zero wrappers, asserted by AST so 'evaluate() as an opaque function' is literally true"
  - "Integrity pins read `read_bytes()`, never `read_text()`, so a line-ending change counts as a modification"
  - "Failure messages on invariant tests state the remedy and explicitly forbid the tempting wrong fix (re-pinning to make a local edit pass)"

requirements-completed: [MEAS-15]

# Metrics
duration: 9min
completed: 2026-08-30
---

# Phase 01 Plan 02: Evaluator Boundary Invariant Summary

**The strongest Technical Execution claim this project makes — "we never modified the evaluator, and the rig only ever calls `evaluate()` as an opaque function" — stops being prose and becomes eight tests that fail on a real breach, including dynamic-import evasion and a transitive breach through `experiments/analyze_public.py`.**

## Performance

- **Duration:** ~9 min
- **Tasks:** 2
- **Files modified:** 2 (2 created, 0 modified)
- **Test suite:** 167 → 175 tests, 2.542 s, all green
- **Boundary module alone:** 8 tests in 0.037 s

## Accomplishments

- **MEAS-15 is now a test, not a promise.** `tests/test_arena_boundary.py` walks every `arena/*.py` except the bridge and fails if any of them names the `evaluator` package.
- **The dynamic-import hole is closed.** A pure `ast.Import`/`ast.ImportFrom` walk passes a file containing `importlib.import_module("evaluator.local_evaluator")`. The `ast.Constant` arm catches it. This was verified by construction, not assumed — see Verification Results.
- **The detector is proven non-vacuous.** `ScannerTest` fires it on a static evasion and a dynamic evasion and confirms a clean control returns `()`, all on files inside a `tempfile.TemporaryDirectory`. The invariant therefore cannot pass because the detector is broken — the failure mode T-01-10b names.
- **The transitive path is guarded.** `test_analyze_public_does_not_reach_the_evaluator` runs the same scan on `experiments/analyze_public.py`, which plan 01-04 imports `code_revision` from. An `arena/`-only scan would be blind to a breach there.
- **The evaluator's bytes are pinned.** `EvaluatorIntegrityTest` asserts SHA-256 `84ea8997…f91b30` over `read_bytes()` on every suite run. The pin computed during planning at HEAD `b98ff27` reproduced exactly at this plan's base `46a93be` (13,836 bytes).
- **The seam is genuinely opaque.** `arena/evaluator_bridge.py` is 17 lines with zero `ast.Import` nodes, exactly one non-`__future__` `ast.ImportFrom`, and zero function or class definitions — asserted by AST, parsed rather than imported so the claim holds even if the evaluator were unimportable.
- **The guard is installed early.** Every module written by plans 01-03 through 01-09 lands underneath it, which was the scheduling reason this plan runs in wave 2 rather than late.

## Task Commits

1. **Task 1: Create the sole evaluator seam** — `4feb517` (feat)
2. **Task 2: Enforce the boundary with an AST walk, a string-constant scan, and a SHA-256 pin** — `323f04c` (test)

## Files Created/Modified

- `arena/evaluator_bridge.py` (17 lines) — module docstring naming D-08 and pointing at the enforcing test, `from __future__ import annotations`, the single import `from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl`, and `__all__`. Nothing else.
- `tests/test_arena_boundary.py` (167 lines) — `REPOSITORY_ROOT`, `EVALUATOR_SHA256`, `BRIDGE_EXPORTS`, the `evaluator_references(path)` scanner, and `ScannerTest` (3) / `ArenaImportBoundaryTest` (4) / `EvaluatorIntegrityTest` (1).

## Decisions Made

- **Docstring at line 1, future import at line 3.** The plan's Task 1 action asked for `from __future__ import annotations` as line 1 *and* a module docstring as the next element. Those cannot both hold: a string literal placed after the future import is an ordinary expression statement, leaving `arena.evaluator_bridge.__doc__` as `None` — i.e. not a docstring at all. `experiments/analyze_misses_b1.py` is the repository's precedent for a module carrying both, and it puts the docstring first. Verified: `ast.get_docstring(tree) is not None`.
- **Assert `>= 1` non-bridge module, not `>= 2`.** The plan's action text specifies "at least one"; its acceptance criteria observe that two are found in fact. Both hold today (`__init__.py`, `import_legacy_results.py`), and the assertion is written at the strength the action specifies so a later plan legitimately retiring the one-off importer does not trip an unrelated guard. The vacuous-pass hole is closed either way.
- **`AsyncFunctionDef` included in the "no definitions" assertion.** The plan says "defines no function and no class"; `ast.FunctionDef` alone would miss `async def`. Cheap completeness on an invariant test.
- **Failure messages name the forbidden fix.** The integrity test's message says re-pinning is legitimate only for a genuine organizer update and must never be done to make a local edit pass. On a test whose whole value is deterrence, the message is the mechanism.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree spawned at a stale base**

- **Found during:** startup, before any file was touched
- **Issue:** The worktree spawned at `9faf85c` ("docs: transcribe organizer briefing deck"), not the expected base `46a93be`. `git merge-base HEAD 46a93be` returned `9faf85c`, confirming HEAD did not contain the base. Building on it would have produced a branch that omits all of wave 1, including the `arena/` modules this plan's scan requires.
- **Fix:** The startup assertions ran first — HEAD was on `worktree-agent-adc16d74603890636` (correct namespace, not a protected ref) and the working tree was clean — so `git reset --hard 46a93be7c29f84cbdbf77725cc670a8ccf376a2f` was safe and was applied.
- **Verification:** `git log` shows both task commits sitting directly on `46a93be`.

### Method Substitutions (same evidence, safer procedure)

**2. Proved the `ast.Constant` arm by in-memory mutation rather than by editing the live file**

- **Criterion:** "Deleting the `ast.Constant` arm of `evaluator_references` makes `test_scan_detects_dynamic_import` FAIL; revert afterwards."
- **Why substituted:** Two sibling executors (plans 01-03 and 01-04) are running this same test suite concurrently against their own worktrees, and the plan's own rationale for the tempfile approach is that a live edit-and-revert is "unsafe while sibling plans in the same wave are running the suite". Editing the file to satisfy a criterion whose stated purpose is to avoid editing files would be self-defeating.
- **What was done instead:** The scanner source was read, the `ast.Constant` branch excised in memory, the mutant compiled and executed, and its `evaluator_references` pointed at the same two fixtures. Result: the mutant returns `()` for the dynamic-import file (so `test_scan_detects_dynamic_import` would FAIL) while still returning a hit for the static-import file. This is strictly stronger evidence than the original procedure — it shows both that the arm is necessary for the dynamic form and that it is not what catches the static form. No file on disk was modified.

**3. Demonstrated SHA-pin sensitivity on a scratch copy**

- **Criterion:** already specified as "demonstrate on a copy — never edit the real file". Followed exactly; recorded here because it is a stated acceptance criterion with a result.

---

**Total deviations:** 1 auto-fixed (blocking, environmental), 2 method substitutions with equal-or-stronger evidence
**Impact on plan:** No scope change. Every acceptance criterion in both tasks is satisfied. The one genuine judgement call — docstring position — is recorded above with its repo precedent.

## Issues Encountered

- **The SHA-256 pin is over CRLF working-tree bytes.** This repository has `core.autocrlf=true`, and `evaluator/local_evaluator.py` is checked out with all 312 line endings as CRLF. The pin `84ea8997…f91b30` is the digest of those bytes, and it reproduced exactly against the value computed during planning — so the pin is correct and stable for every checkout of this repository on this configuration. A checkout that normalized to LF would produce a different digest through no fault of the file. The failure message explicitly names line-ending normalization as a possible cause so the next reader is not misled into thinking the evaluator was edited. No action needed unless the project starts being checked out on Linux/CI.
- **`experiments/RUNS.md` / no catalog present.** Not applicable to this plan — the 8 boundary tests perform no `Agent` construction and no SQLite access, and passed in a worktree containing neither `data/catalog.jsonl` nor `data/catalog.artifacts/`.

## Verification Results

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_boundary` | **8 tests, OK, 0.037 s** |
| `uv run python -W error::ResourceWarning -m unittest` | **175 tests, OK, 2.542 s** (167 baseline + 8 new) |
| `git diff --quiet -- evaluator/` | exit **0**, asserted after each task |
| Suite runs with no catalog / no 580 MB artifact | **yes** — worktree `data/` holds only `README.md` and `public_set.jsonl` |
| `arena/evaluator_bridge.py` line count | **17** (limit 20) |
| Bridge `ast.Import` node count | **0** |
| Bridge non-`__future__` `ast.ImportFrom` | **1**, module `evaluator.local_evaluator`, names `catalog_index, evaluate, load_jsonl` |
| Bridge `FunctionDef` / `ClassDef` count | **0 / 0** |
| `ast.get_docstring(bridge)` | **not None** — a real docstring |
| `import arena.evaluator_bridge; b.__all__` | `('catalog_index', 'evaluate', 'load_jsonl')` |
| Mutant scanner (Constant arm removed) on dynamic import | **`()`** — `test_scan_detects_dynamic_import` would FAIL, arm is load-bearing |
| Mutant scanner (Constant arm removed) on static import | **hit** — arm is not what catches the static form |
| Real `evaluator/local_evaluator.py` digest vs `EVALUATOR_SHA256` | **match** (13,836 bytes) |
| Scratch copy + one appended newline vs pin | **no match** — the pin is byte-sensitive |
| Real evaluator digest after the copy demonstration | **still matches** — untouched |
| Write paths in `tests/test_arena_boundary.py` | **1**, line 55, into a `TemporaryDirectory`; none into `arena/` |
| Non-bridge arena modules found by the glob | **2** — `__init__.py`, `import_legacy_results.py` |
| `evaluator_references(experiments/analyze_public.py)` | **`()`** |

## Known Stubs

None. Both files are complete and final in their intended form; the bridge's deliberate emptiness is the specification, not an unfinished implementation.

## Threat Flags

None. No network endpoint, auth path, file-access pattern, or schema at a trust boundary was introduced — this plan only *reads* files. Every threat in the plan's register with a `mitigate` disposition is implemented: T-01-02 by `EvaluatorIntegrityTest`, T-01-02b by the three-node-kind scan, T-01-02c by `test_analyze_public_does_not_reach_the_evaluator`, T-01-10 by `test_arena_package_has_modules_to_scan`, T-01-10b by `ScannerTest`. T-01-09 and T-01-SC remain accepted as planned; zero packages were installed.

## Next Phase Readiness

- Every arena module created by plans 01-03 through 01-09 is now automatically scanned. Authors should import `evaluate`, `catalog_index` and `load_jsonl` from `arena.evaluator_bridge`, never from `evaluator.local_evaluator` directly.
- `evaluator_references(path)` is reusable: point it at any new file to extend the guard beyond `arena/`.
- Plan 01-04 may import `code_revision` from `experiments/analyze_public.py` as designed — that module is verified clean and is now continuously watched.
- Caution for a future contributor: a bare string constant whose first dotted component is exactly `"evaluator"` will trip the scan even in a comment-like docstring context. Prose such as `"see evaluator/local_evaluator.py"` does not trip it (the first dotted component is the whole phrase). This is intended strictness.
- No blockers.

## Self-Check: PASSED

Both claimed files (`arena/evaluator_bridge.py`, `tests/test_arena_boundary.py`) exist and
are tracked by `git ls-files`. All three claimed commits (`4feb517`, `323f04c`, `bd91750`)
are present in `git log`, sitting directly on the intended base `46a93be`. Working tree clean.

---
*Phase: 01-measurement-rig-core*
*Completed: 2026-08-30*
