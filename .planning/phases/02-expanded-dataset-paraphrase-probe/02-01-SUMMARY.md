---
phase: 02-expanded-dataset-paraphrase-probe
plan: 01
subsystem: testing
tags: [boundary, ast, seam, rglob, gitignore, stopwords, stdlib, unittest]

# Dependency graph
requires: []
provides:
  - "`arena/evaluator_bridge.py` re-exports eight evaluator names — `behavior_for`, `catalog_index`, `classify_constraint`, `evaluate`, `intent_card`, `load_jsonl`, `materialize_hidden_fields`, `searchable_text` — each with its *why* commented at the import (D-47)"
  - "`tests/test_arena_boundary.py::arena_modules(root)` — the single recursive, path-anchored module-collection predicate shared by the live scan and its TemporaryDirectory proofs"
  - "The D-08/MEAS-15 boundary scan now recurses into `arena/datasets/`, so every module a sibling plan adds there is guarded from the moment it is written (L-1)"
  - "`arena/datasets/` package stub — the corpus generation/freezing namespace (D-43)"
  - "`starter.shopping_agent.constraint_extractor.STOPWORDS` — public, importable by `arena/datasets/divergence.py` without reaching for a private name (D-54)"
  - "A gitignored `.scratch/` root: one repo-relative path every phase-2 operator command can pin instead of a POSIX-only `$TMPDIR`"
affects: [02-02, 02-03, 02-04, 02-05, 02-06, 02-07, 02-08, 02-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One collection predicate, two callers: the live boundary scan and its temp-dir proofs share `arena_modules(root)` so a regression cannot hide in an untested second copy"
    - "Guard changes are proven two-sided — each new assertion was re-run against a deliberately reverted helper and observed to fail"
    - "Path-anchored exemptions, never basename-anchored, once a scan is recursive"

key-files:
  created:
    - arena/datasets/__init__.py
  modified:
    - arena/evaluator_bridge.py
    - tests/test_arena_boundary.py
    - starter/shopping_agent/constraint_extractor.py
    - tests/test_constraint_extractor.py
    - .gitignore
    - docs/STATUS.md
    - CLAUDE.md

key-decisions:
  - "Write the eight-name seam as a parenthesized one-name-per-line import rather than the single line the plan quoted — CONVENTIONS.md mandates parenthesized multi-name imports at an ~88-column soft limit, and the per-name D-47 *why* only fits legibly beside its name. The AST guard is unaffected: a parenthesized `ImportFrom` is still exactly one node with the same sorted alias list"
  - "Key the boundary-breach failure map by repository-relative POSIX path, not basename — once the scan recurses, `arena/x.py` and `arena/datasets/x.py` collide and one offender would silently overwrite the other in the very message meant to name it"
  - "Assert the `arena/datasets/` reach against the *real* tree in `test_arena_package_has_modules_to_scan`, not only in a TemporaryDirectory — without it the recursion could regress to `glob` while every temp-dir proof still passed"
  - "Extend the negative nested-bridge case to also assert the top-level `arena/evaluator_bridge.py` *is* still exempt, so the test pins both halves of the exemption rather than only the half L-1 broke"
  - "Update `docs/STATUS.md` and `CLAUDE.md` alongside the rename even though neither is in the plan's `files_modified` — plan verification item 4 requires `_STOPWORDS` to be absent everywhere outside `.planning/`, and both files named it"

patterns-established:
  - "A guard widened in the same commit as the surface it guards (D-47), so the invariant is never briefly unenforced"
  - "Revert-and-observe as the acceptance evidence for a guard: a new assertion is only proven when the un-fixed implementation is seen to fail it"

requirements-completed: [MEAS-10, MEAS-11, MEAS-12]

# Metrics
duration: 25min
completed: 2026-09-01
---

# Phase 02 Plan 01: Evaluator Seam Widening and Boundary Guard Recursion Summary

**The sole `arena/` → `evaluator/` seam now re-exports eight names with a per-name rationale, and its AST guard recurses into `arena/datasets/` with a path-anchored bridge exemption — both proven by re-running the new assertions against deliberately reverted helpers — while `_STOPWORDS` becomes public `STOPWORDS` so the D-34 divergence gate need not import a private name across packages.**

## Performance

- **Duration:** ~25 min (including one API-quota interruption mid-Task-1)
- **Tasks:** 2/2
- **Test count:** 384 → 387 (+3: two scanner recursion proofs, one `STOPWORDS` contract test)

## What Was Built

### Task 1 — Eight-name seam + recursive, path-anchored guard (commit `e78873c`)

All three D-47 files moved in one commit, so the boundary invariant was never
briefly unenforced. `git show --stat e78873c` lists `arena/evaluator_bridge.py`,
`tests/test_arena_boundary.py` and `arena/datasets/__init__.py` together.

**The seam.** `arena/evaluator_bridge.py` re-exports the sorted eight. Each of the
five added names carries its *why* at the import:

| Name | Why it crosses the seam |
|---|---|
| `intent_card` | Builds the control arm verbatim from the target product, so the control is the evaluator's own card rather than a re-implementation (D-31) |
| `behavior_for` | The fallback behavior an authored control arm is compared against (D-55) |
| `classify_constraint` | The single authority on which asked attribute unlocks which constraint (D-33/F-05) |
| `materialize_hidden_fields` | Proves branch 1 fired — an authored card must come back unchanged (D-37) |
| `searchable_text` | The exact six-field concatenation the D-34 overlap gate measures against |

The docstring also carries forward `arena/metrics.py`'s transcription warning:
widening the seam must not tempt anyone to replace the transcribed metric chain
with evaluator imports, because the cross-agreement between two independent code
paths is the MEAS-16 validation evidence and importing `metric_summary` would
make that agreement a tautology.

No `FunctionDef`, `AsyncFunctionDef` or `ClassDef` was added; the seam stays a
pure re-export and the existing purity assertions still hold.

**The guard.** `_non_bridge_modules` was replaced by a module-level
`arena_modules(root: Path) -> list[Path]` that uses `rglob`, skips
`__pycache__`, and exempts `Path("arena") / "evaluator_bridge.py"` by
repository-relative path. Taking a `root` parameter is what lets the live scan
and the temp-dir proofs share one implementation — a second copy could drift
back to `glob` without failing anything.

**`.gitignore`.** A single `.scratch/` root, commented with the reason it exists:
this repository documents Windows 11 / PowerShell as its platform, where
`$TMPDIR` expands to the empty string, so `--response-log "$TMPDIR/probe.jsonl"`
silently writes to the drive root instead of failing.

### Task 2 — `_STOPWORDS` → `STOPWORDS` (commit `568ddc8`)

Renamed with its single call site (`constraint_extractor.py:109`) in the same
commit. No `_STOPWORDS = STOPWORDS` alias was added — a private name importable
across packages is exactly the precedent D-54 rejects.

The existing rationale comment was *extended*, not replaced. Two sentences were
added: the D-34 consumer (`arena/datasets/divergence.py` measures probe-phrase
content tokens after removing these words, so one list serves both the gazetteer
and the gate), and the negation caveat (the list contains `"no"` and `"not"`, so
negation is invisible to a *lexical* gate by construction — negation drift is
caught by the D-35 faithfulness review instead).

## Verification Evidence

All plan acceptance criteria were run and passed.

| Check | Result |
|---|---|
| `unittest tests.test_arena_boundary` | 10 tests, OK |
| `unittest tests.test_constraint_extractor` | 24 tests, OK |
| Full suite | 387 tests, OK (384 at phase entry, +3) |
| `grep -c rglob tests/test_arena_boundary.py` | 4 (≥ 1) |
| `grep -c 'arena_directory.glob("*.py")'` | 0 |
| `grep -v '^\s*#' arena/evaluator_bridge.py \| grep -c materialize_hidden_fields` | 2 (≥ 2) |
| `b.__all__ == (…eight sorted names…)` | exit 0 |
| `arena/datasets/__init__.py` has no `FunctionDef`/`ClassDef` | exit 0 |
| `git check-ignore -v .scratch/probe-smoke.jsonl` | exit 0 (ignored) |
| `git check-ignore -v data/datasets.json` | exit 1 (NOT ignored) |
| `grep -rn _STOPWORDS starter/ arena/ tests/ experiments/` | no matches |
| `grep -rn _STOPWORDS .` excluding `.planning/` | no matches |
| `grep -v '^\s*#' constraint_extractor.py \| grep -c STOPWORDS` | 2 (≥ 2) |
| `STOPWORDS` is a non-empty `frozenset`, holds `the`/`no`, lacks `buckle`/`dress` | exit 0 |

### Two-sided guard proofs

The plan required the recursion fix be proven in both directions rather than
merely asserted. Each new test was re-run against a deliberately reverted copy of
the helper in `.scratch/` (since removed) and observed to **fail**:

| Reverted helper | Test | Observed |
|---|---|---|
| `rglob` → `glob` | `test_scan_reaches_a_nested_module` | FAIL — nested `probe.py` not in `[]` |
| `rglob` → `glob` | `test_a_nested_bridge_named_module_is_not_exempt` | FAIL — nested bridge not in `[]` |
| `path.relative_to(root) != _BRIDGE_RELATIVE_PATH` → `path.name != _BRIDGE_MODULE_NAME` | `test_a_nested_bridge_named_module_is_not_exempt` | FAIL — basename exemption swallowed the nested bridge |

This is the property that matters: the assertions fail on the un-fixed
implementation and pass on the fixed one, so they measure the fix rather than
merely coexisting with it.

`EVALUATOR_SHA256` and `EvaluatorIntegrityTest` were not touched;
`test_evaluator_is_byte_unmodified` passes unchanged.

## Deviations from Plan

### Adjustments

**1. [Convention] Seam import written parenthesized one-per-line, not as one long line**
- **Found during:** Task 1
- **Issue:** The plan quoted the eight-name import as a single ~125-column line. `.planning/codebase/CONVENTIONS.md` mandates parenthesized one-name-per-line multi-name imports at an ~88-column soft limit, and CLAUDE.md carries the same rule.
- **Resolution:** Parenthesized form, one name per line, trailing comma. This is also what makes the D-47 per-name *why* legible — each comment sits directly above its name. The AST guard is indifferent: a parenthesized `ImportFrom` is one node with the same sorted alias list, and `test_bridge_surface_is_exactly_the_declared_names` passes.
- **Commit:** `e78873c`

**2. [Rule 2 - Correctness] Boundary-breach failure map keyed by relative path, not basename**
- **Found during:** Task 1
- **Issue:** `test_only_the_bridge_module_references_the_evaluator` built `offenders[path.name]`. Once the scan recurses, `arena/x.py` and `arena/datasets/x.py` share a basename and one offender silently overwrites the other — in the very message meant to name the breach. This defect is *created by* the recursion this task adds, so it is in scope.
- **Resolution:** Key by `path.relative_to(REPOSITORY_ROOT).as_posix()`. `test_arena_package_has_modules_to_scan` was updated to the same representation so its `arena/datasets/` assertion reads clearly.
- **Commit:** `e78873c`

**3. [Plan-required] `docs/STATUS.md` and `CLAUDE.md` updated for the rename**
- **Found during:** Task 2
- **Issue:** Plan verification item 4 requires `grep -rn "_STOPWORDS" .` (excluding `.planning/`) to return nothing, but the plan's `files_modified` lists neither file. Both named the private constant.
- **Resolution:** Updated both, each noting D-54 and the `arena/datasets/divergence.py` consumer. Without this the plan's own verification could not pass.
- **Commit:** `568ddc8`

**4. [Scope] Two-sided nested-bridge test strengthened**
- **Found during:** Task 1
- **Issue:** The plan specified `test_a_nested_bridge_named_module_is_not_exempt` assert only that the nested bridge *is* collected. That is one-sided: a helper exempting nothing at all would also pass.
- **Resolution:** The test also asserts the top-level `arena/evaluator_bridge.py` is *not* collected, pinning both halves of the exemption.
- **Commit:** `e78873c`

### Out of Scope — Deferred

**`.planning/codebase/CONVENTIONS.md:48` and `.planning/codebase/STACK.md:73` still cite `_STOPWORDS`.**
CONVENTIONS.md uses it as an example of the underscore-prefixed tuning-constant
convention, which is now false for this name. Both are inside `.planning/`, which
the plan's verification explicitly excludes, and both are generated codebase-analysis
snapshots that sibling plans in this wave may also touch — editing them here risks a
merge conflict for no verification benefit. Recorded here rather than in a shared
`deferred-items.md` for the same conflict reason. Worth folding into the next
codebase-analysis regeneration.

## Known Stubs

`arena/datasets/__init__.py` is an intentional empty package stub. It exports
nothing by design — the plan requires it so the recursive scan has a real nested
module to walk and `test_arena_package_has_modules_to_scan` is non-vacuous. The
modules that give the package its purpose (`schema.py`, `gist.py`,
`divergence.py`, `authoring.py`, `registry.py`, `generate.py`) are created by
sibling plans 02-02 through 02-08 in this phase.

## Threat Flags

None. No new network endpoint, auth path, file-access pattern, or schema at a
trust boundary was introduced. The two boundaries this plan touches
(`arena/` → `evaluator/`, and the new `arena/datasets/` subpackage) were both
already in the plan's threat register, and both `mitigate` dispositions —
T-02-12 (recursive path-anchored scan) and T-02-13 (seam stays a pure
re-export) — were implemented and machine-checked. T-02-08 remains `accept`:
`EVALUATOR_SHA256` is unchanged and its integrity test passes.

## Commits

| Task | Commit | Description |
|---|---|---|
| 1 | `e78873c` | `feat(02-01): Widen the evaluator seam to eight names and make its guard recursive` |
| 2 | `568ddc8` | `refactor(02-01): Promote _STOPWORDS to public STOPWORDS` |
