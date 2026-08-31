---
phase: 02-expanded-dataset-paraphrase-probe
plan: 05
subsystem: testing
tags: [divergence, classify-constraint, lexical-overlap, bigrams, gates, jsonl]

# Dependency graph
requires:
  - phase: 02-01
    provides: "arena/evaluator_bridge.py widened to eight names (classify_constraint, searchable_text); public STOPWORDS in constraint_extractor.py; arena/datasets/ package"
provides:
  - "D-33 bucket-preservation gate (preserves_bucket) computed through the harness's own classify_constraint via the seam"
  - "D-34 bucket-aware lexical-divergence measurement (measure_text / measure) with a token-overlap half and an adjacency half"
  - "pinned_tokens: the corrected seven-substring colour clause derivation (D-51/L-4)"
  - "The per-pair divergence log artifact type (DivergenceRecord, write/load/coverage) that satisfies the per-pair half of Roadmap SC3"
  - "contradicts: the D-35 programmatic contradiction guard"
  - "bucket_summary: per-bucket aggregation that structurally cannot report an empty bucket"
affects: [02-07, 02-09, 02-11, 02-12, 07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Transcribe-and-pin: a local copy of an external decision table is kept for derivation only, with the decision itself always delegated to the authority, and a test pinning the copy to the authority on measured cases"
    - "measure_text / measure split so a corpus sweep can re-derive committed ratios from a text snapshot without opening the 580 MB artifact"
    - "Mutation sweep as acceptance evidence: every gate is shown to fail against a deliberately broken implementation"

key-files:
  created:
    - arena/datasets/divergence.py
    - tests/test_datasets_divergence.py
  modified: []

key-decisions:
  - "Pin exactly ONE classifier keyword per phrase (the first the harness would short-circuit on), not every keyword in the matched clause -- each additional exclusion is content the phrase gets away with reusing, so minimal exclusion is the stricter gate"
  - "The 2-gram half runs over the FULL probe token sequence including stopwords and the pinned keyword, because a shared 2-gram is a verbatim span regardless of how its halves are individually classified"
  - "bucket_summary's empty-bucket skip is structural (groups built from the reports themselves) rather than a filter clause; the `if members` guard originally written was unreachable-by-construction and was removed as dead code masquerading as protection"
  - "write_divergence_log validates every record before writing, so an incoherent record cannot reach the committed log at all (T-02-41)"
  - "The module contains no attribute access named `search` anywhere -- the budget clause uses findall instead of .search -- so the D-35 solvability scanner can stay blunt and carve-out-free"
  - "_ARMS is transcribed from plan 02-03's contract with a skipUnless test that becomes a live pin the moment arena/datasets/schema.py exists"

patterns-established:
  - "Pinned-token derivation: a gate that measures reuse must first excuse whatever the measured artifact is structurally forced to carry, and excuse only that"
  - "Two-sided gate proof: each acceptance gate is run against both the real implementation and a mutated one, and a gate that cannot fail is reported rather than trusted"

requirements-completed: [MEAS-12]

# Metrics
duration: 55min
completed: 2026-09-01
---

# Phase 02 Plan 05: Divergence Gates Summary

**The D-33 bucket gate and the D-34 bucket-aware lexical-divergence measurement, both computed in the agent's own normalized token space, both proven by a 13-mutation sweep to fail when the thing they guard is broken, and both now backed by a committed per-pair record that answers Roadmap SC3.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 2 of 2
- **Files created:** 2
- **Tests:** 42 added; full suite 441 tests, all passing in 4.9 s

## Accomplishments

### `arena/datasets/divergence.py` (536 lines)

- `_CLASSIFIER_KEYWORDS` transcribes `classify_constraint`'s seven ordered clauses
  (`local_evaluator.py:138-151`) **for pinned-token derivation only**. The bucket
  decision always goes through `arena.evaluator_bridge.classify_constraint`; the copy
  never decides anything.
- The colour clause is the **seven** substrings at `:143`, one of which is the literal
  word `color`. The twelve-entry `COLOR_RE` at `:24` serves `intent_card`, and its five
  extra colour words route to `feature`, not `color` (D-51/L-4). Those five words appear
  nowhere in the module, and the test asserts both halves of that: the clause equals the
  seven, and each of the five does **not** classify as `color`.
- `pinned_tokens` walks the clauses in order and excuses the token carrying the first
  matched keyword, plus the keyword itself. `feature` pins nothing. The budget clause's
  numeric alternative pins the tokens inside its matched span.
- `ordered_tokens` / `bigrams` use `TOKEN_RE.findall(normalize_text(...))`; the overlap
  half uses `search_terms`. Both primitives are present, each for its own half (L-15).
- `measure_text` is the core; `measure` is a one-line delegation so plan 02-11's sweep can
  substitute a committed `searchable_text` snapshot for the catalog.
- `contradicts` is the D-35 guard. `bucket_summary` reports per bucket and structurally
  cannot emit a zero-n row.
- The per-pair log: `DIVERGENCE_LOG_SCHEMA_VERSION`, `DIVERGENCE_LOG_ROOT`,
  `divergence_log_path`, `DivergenceRecord`, `record_from_report`, `write_divergence_log`,
  `load_divergence_log`, `coverage`. `data/divergence.probe.v1.jsonl` is confirmed
  committable (`git check-ignore` exits non-zero).

### `tests/test_datasets_divergence.py` (42 tests, 0.02 s, no database, no catalog)

Seven classes plus an eighth (`ArmVocabularyTest`) covering the wave coupling. Every
product dict is built inline; `tests.dataset_fixtures`, `tests.fixtures`, and any backend
import are absent by construction and by acceptance check.

## Verification Performed

All plan verification steps and every acceptance criterion in both tasks pass:

| Check | Result |
|---|---|
| `uv run python -m unittest tests.test_datasets_divergence` | 42 tests, OK, 0.02 s (1 skip, see Coupling) |
| `uv run python -m unittest tests.test_arena_boundary` | 10 tests, OK |
| `uv run python -m unittest` (full suite) | **441 tests, OK, 4.9 s** |
| Twelve-colour leak grep on the module | no matches |
| `grep -c "from evaluator"` on the module | 0 |
| `TOKEN_RE.findall` and `search_terms` both used (non-comment) | 2 and 4 |
| `git check-ignore data/divergence.probe.v1.jsonl` | exits 1 (committable) |
| Line length ≤ 88 in both files | 0 violations |

### Mutation sweep (the two-sided evidence)

Each gate was run against a deliberately broken copy of the module. **13 of 13 mutations
were detected** by the test module:

| Mutation | Detected |
|---|---|
| M1 twelve-colour clause substituted (D-51/L-4) | yes |
| M2 adjacency built from de-duplicated terms (L-15) | yes |
| M3 `bucket_summary` enumerates all seven buckets (L-18) | yes |
| M4 `coverage` stops refusing duplicate keys (T-02-41) | yes |
| M5 report drops the `passes`/evidence coherence check (T-02-41) | yes |
| M6 `pinned_tokens` over-excuses every token | yes |
| M7 `preserves_bucket` always agrees (D-33) | yes |
| M8 log rows written in input order | yes |
| M9 overlap-ratio bounds unchecked | yes |
| M10 stopwords no longer removed from content | yes |
| M11 pinned keyword charged as content (bucket floor) | yes |
| M12 arm vocabulary unchecked | yes |
| M13 `load_divergence_log` drops the line number | yes |

The module was restored byte-identically after the sweep (asserted in-script).

## Gates Found One-Sided or Brittle

Reported per the verification-discipline instruction. **Two acceptance criteria in this
plan measure formatting rather than behaviour**, and both initially failed a correct
implementation:

1. **`grep -A3 "def measure(" | grep -c "measure_text"` ≥ 1.** A three-line proximity
   window. My first implementation delegated correctly but had a five-line signature and a
   load-bearing comment inside the body, so the window never reached the `return`. Fixed by
   hoisting the comment above the `def` and using Black's single-indented-parameter-line
   form. I verified the *other* direction too: a variant where `measure` builds its own
   report scores 0, so the gate is brittle but not vacuous. A reviewer should treat it as
   "the delegation is greppable", not "the delegation exists".

2. **`grep -c "passes is False\|assertFalse(.*passes"` ≥ 2 and the `assertTrue` twin.**
   These match assertion *spelling*. My first implementation used
   `self.assertIs(measured.passes, False)`, which is strictly stronger (it rejects a truthy
   non-bool that would serialize into the committed log as something other than JSON
   `true`) but scores 0 on the grep. Resolved by asserting both forms rather than
   downgrading: `assertFalse`/`assertTrue` satisfy the gate, `assertIs` keeps the strictness.

3. **`grep -c "classify_constraint(" tests/... ` ≥ 10** counts call sites as a proxy for
   "the agreement table has ≥ 10 cases". A table-driven loop over eleven cases scores 1.
   Resolved by spelling the eleven pins out one per line (which is also this repository's
   house style, per `tests/test_text_normalization.py`) and asserting that the
   `CLASSIFIER_TRAPS` tuple holds the same eleven pairs, so the two cannot drift.

4. **Verification step 3 / acceptance criterion 2 (the twelve-colour leak grep) is
   one-sided on its own** — it passes vacuously against an empty or absent file. It is
   two-sided only in combination with the positive assertion that the clause equals the
   seven substrings, which the test module now makes (`assertEqual` on the clause **and**
   `assertNotEqual(classify_constraint(...), "color")` for each of the five excluded
   words). Both halves are in `ClassifierAgreementTest`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The plan's Task 1 comment instruction contradicts its own acceptance gate**

- **Found during:** Task 1
- **Issue:** The action text asks for a comment naming five specific colour words as the
  measured consequence of D-51. Verification step 3 and acceptance criterion 2 both require
  those exact words to appear **nowhere** in the module. Following the action text verbatim
  fails the plan's own gate.
- **Fix:** Wrote the same consequence without naming the words — "for a target whose control
  colour word is one of the five that COLOR_RE matches but the colour clause does not, the
  pinned token is the literal word `color`". The five words are named in the *test* module,
  where the grep does not apply and where they are asserted **not** to reach the colour
  bucket, which is stronger than a comment.
- **Files modified:** `arena/datasets/divergence.py`, `tests/test_datasets_divergence.py`
- **Commits:** `9981b3f`, `e19e42f`

**2. [Rule 1 - Bug] The `SolvabilityAbsenceTest` scanner collides with a regex `.search`**

- **Found during:** Task 2
- **Issue:** The plan requires the AST scanner to flag "an attribute access named `search`".
  `_BUDGET_NUMERIC_RE.search(lowered)` is exactly that, so the module would have failed its
  own D-35 gate.
- **Fix:** Used `_BUDGET_NUMERIC_RE.findall` (the pattern has no capturing group, so
  `findall` yields whole matches) and commented the constraint at the call site so a future
  reader does not "fix" it back. Chose this over adding a receiver carve-out to the scanner:
  a blunt guard with one awkward call site beats a guard with a hole a backend call could
  hide in.
- **Files modified:** `arena/datasets/divergence.py`
- **Commit:** `e19e42f`

**3. [Rule 1 - Bug] `bucket_summary`'s `if members` filter was unreachable**

- **Found during:** Task 2 mutation sweep
- **Issue:** The plan asks `bucket_summary` to "skip any bucket with zero reports". I wrote
  the skip as an `if members` clause — but the groups are built by `setdefault` from the
  reports themselves, so `members` is never empty and the clause is dead code. Mutating it
  away changed nothing, i.e. it read as protection while providing none. This is precisely
  the "gate that cannot fail" hazard.
- **Fix:** Removed the clause; documented that the skip is **structural** and named the shape
  that reintroduces the bug (enumerating the seven classifier buckets and looking each one
  up). Replaced the mutation with that shape and confirmed the test catches it (M3).
- **Files modified:** `arena/datasets/divergence.py`
- **Commit:** `e19e42f`

**4. [Rule 1 - Bug] The L-15 adjacency test did not actually exercise L-15**

- **Found during:** Task 2 mutation sweep
- **Issue:** The plan's specified adjacency case (`"must have a rubber sole underneath"`
  against a leather-boot product) fails the gate on **token overlap** as well as adjacency,
  and the target text has no repeat before the shared span — so rebuilding `bigrams` from
  the de-duplicating `search_terms` left the test green (mutation M2 initially MISSED). The
  test asserted the right outcome for the wrong reason.
- **Fix:** Added `test_adjacency_survives_a_repeat_earlier_in_the_target`, which isolates the
  adjacency half exactly: target `"a sturdy boot with a rubber sole"`, phrase
  `"made with a leathery finish"`. Every content token of the phrase is absent from the
  target, so `overlapping_tokens == ()` and the **only** thing failing the gate is the shared
  span `"with a"` — a span that de-duplication destroys, because dropping the repeated `a`
  welds `with` to `rubber`. M2 is now detected.
- **Files modified:** `tests/test_datasets_divergence.py`
- **Commit:** `e19e42f`

### Additions Beyond the Plan (Rule 2)

- **`record_from_report`** — the plan lists `DivergenceRecord` but no constructor from a
  `DivergenceReport`. Flattening twelve fields by hand at every call site in 02-11/02-12 is
  where a mismatched `passes`/`overlapping_tokens` pair would be introduced. Added so the
  flattening happens once.
- **`write_divergence_log` validates before writing** — the plan places the invariant on
  `DivergenceRecord.validate()` but does not say who calls it. An unvalidated writer would
  let T-02-41's incoherent record reach the committed log. Validating at the write boundary
  is this repository's fail-closed convention.
- **`load_divergence_log` rejects a non-object line** — a bare JSON array or scalar would
  otherwise load as a "record" and blow up later, far from the malformed file.
- **`DivergenceRecord.report()`** — reconstitutes the embedded report so `validate()` and
  `as_record()` delegate to the report's own invariant rather than restating it.

## Cross-Plan Coupling (action needed at merge)

`DivergenceRecord.validate()` is specified to check `arm in schema.ARMS`, but
`arena/datasets/schema.py` is built by **plan 02-03 in this same wave** and does not exist in
this worktree. Importing it at module scope would make `divergence.py` unimportable here.

**Resolution used:** a module constant `_ARMS = ("control", "probe_haiku", "probe_sonnet")`,
transcribed from 02-03's stated contract, plus `ArmVocabularyTest`, which is
`skipUnless(importlib.util.find_spec("arena.datasets.schema") is not None)` and asserts
`_ARMS == schema.ARMS`.

**This is the one skipped test in the suite.** It activates automatically the moment 02-03
merges, so the transcription cannot outlive the wave undetected — but if 02-03 landed a
different tuple, **the merge will surface it as a test failure, not silently**. That is the
intended behaviour; do not "fix" it by editing `_ARMS` without checking which side is right.
A follow-up may replace `_ARMS` with a direct `schema.ARMS` import once both are merged.

No other module owned by a sibling plan was created, read, or edited. `arena/datasets/schema.py`
and `tests/dataset_fixtures.py` were deliberately not touched.

## Known Stubs

None. Every symbol listed in the plan's artifact contract is implemented and exercised.

## Threat Flags

None. No new network endpoint, auth path, file-access pattern, or trust-boundary schema was
introduced beyond the JSONL log the plan specifies, which is read with `json.loads` only,
validated on write, and refuses malformed and non-object lines with a path-and-line-numbered
error.

## Notes for Future Phases

- **Plan 02-07** should embed `_FEATURE_TRIGGER_SUBSTRINGS` in the authoring prompt. `feature`
  is the residual default and ~50.5% of control constraints, so most re-authoring starts from
  a feature-bucket phrase that can silently flip on `fit`, `work`, `size`, `wide`, `neck`,
  `style`, or any material substring (L-5). The gate is the backstop, not the first defence.
- **Plan 02-11** should call `coverage()` and assert it equals the committed corpus's
  constraint count — that is how Roadmap SC3's "for every probe pair" becomes machine-checked.
  It should also feed `measure_text` a committed `searchable_text` snapshot rather than
  opening the artifact; `test_measure_and_measure_text_agree` is the assertion that licenses
  the substitution.
- **Phase 7 reporting** should read probe ratios against the measured control-arm mean of
  **0.9857** (median 1.0000, n=798), and should present the per-bucket table rather than one
  number — `size` (n≈11) and `use_case` (n≈4) at probe scale are descriptive noise and the
  report must say so.

## Self-Check: PASSED

- `arena/datasets/divergence.py` — FOUND (536 lines)
- `tests/test_datasets_divergence.py` — FOUND (42 tests)
- Commit `9981b3f` — FOUND
- Commit `e19e42f` — FOUND
- Full suite: 441 tests, OK
- STATE.md / ROADMAP.md — untouched, as required in worktree mode
