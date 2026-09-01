---
phase: 02-expanded-dataset-paraphrase-probe
plan: 08
subsystem: testing
tags: [registry, sha256, freeze, provenance, jsonl, markdown, determinism]

requires:
  - phase: 02-03
    provides: "corpus row schema, ARMS, canonical JSONL writer, stem-enforcing loader"
  - phase: 02-05
    provides: "divergence.bucket_summary and the per-pair divergence log this registry pins"
  - phase: 01
    provides: "arena/store.py sha256_file, write_json, name allow-list and containment discipline"
provides:
  - "arena/datasets/registry.py: DatasetEntry, load/write/upsert registry, resolve_dataset with use-time digest enforcement"
  - "publish_corpus: versioned filename, refuse-if-exists, staged-bytes validation, atomic replace"
  - "check_scenario_mix / check_pairing / check_cross_check_subset: the three corpus-shape invariants"
  - "write_target_snapshot / load_target_snapshot: the committed parent_asin to searchable_text map"
  - "render_markdown: the pure D-12 view of the JSON truth"
affects: [02-10, 02-11, 02-12, 02-13]

tech-stack:
  added: []
  patterns:
    - "Paired artifact fields: a recorded path and its digest and its count move together or the entry is refused"
    - "Use-time re-hash: a frozen digest is re-derived at resolution, not merely recorded at freeze"
    - "Refusal messages name every offender at once, not the first one found"

key-files:
  created:
    - arena/datasets/registry.py
    - tests/test_datasets_registry.py
  modified: []

key-decisions:
  - "check_cross_check_subset enforces a non-strict subset: equality is a legal fully-cross-checked corpus, and strictness would refuse it for an artefact of the 100-of-700 sampling"
  - "publish_corpus validates the STAGED BYTES via validate_corpus before os.replace, so a mis-namespaced corpus cannot become frozen and citable"
  - "The divergence table is stored as (bucket, ordered metric pairs), keeping the frozen dataclass hashable and the committed JSON insertion-order-free"
  - "resolve_dataset tolerates a missing registry file, because data/datasets.json does not exist until the first corpus is frozen in 02-11"
  - "check_scenario_mix reports every deviating scenario in one message rather than raising on the first"

patterns-established:
  - "Two-sided gate proof by source mutation: 17 registry branches each broken in turn, each producing a red test"
  - "Message-specific assertions where two branches can raise on the same input"

requirements-completed: [MEAS-11, MEAS-12, MEAS-13]

duration: 42min
completed: 2026-09-01
---

# Phase 02 Plan 08: Dataset Registry Summary

**`data/datasets.json` as canonical committed truth, with resolution-time re-hashing that turns D-43's recorded digest into an enforced precondition, plus the three corpus-shape invariants (D-30 mix, MEAS-11 pairing, D-40 three-arm subset) and a committed target snapshot that keeps the D-34 sweep catalog-free.**

## Performance

- **Duration:** ~42 min
- **Tasks:** 2
- **Files modified:** 2 created, 0 modified
- **Test suite:** 584 tests, 5.35 s, all passing (544 at base, +40 from this plan)
- **Registry module alone:** 40 tests in 0.31 s

## Accomplishments

- **Freeze is enforced, not recorded.** `resolve_dataset` re-hashes the corpus at
  use time and refuses on drift with both digests in the message. Proved from both
  sides: disabling the comparison turns the test red.
- **Three doors closed against Pitfall 6 together.** Versioned filenames
  (`_DATASET_NAME_RE` requires `.vN`), `publish_corpus`'s `FileExistsError`, and
  `upsert_entry`'s refuse-on-changed-digest unless `allow_refreeze=True`.
- **`DatasetEntry` pins every companion artifact.** The per-pair divergence log and
  the target snapshot each carry a path, a digest and a count, and `validate()`
  refuses any one of the three without the others (T-02-43).
- **The target snapshot is a first-class artifact** rather than something plan
  02-11's sweep has to invent, with the `probe.v1`-only scope decision and its
  ~1 MB cost documented in the function's own docstring.
- **Every gate is two-sided.** 17 branches were individually broken by source
  mutation and each produced a red test; one genuinely one-sided assertion was
  found and fixed (below).

## Task Commits

1. **Task 1: registry module** — `bd99695` (feat)
2. **Task 2: two-sided test module** — `f9a519d` (test)

## Files Created

- `arena/datasets/registry.py` (880 lines) — `DatasetEntry`, `load_registry`,
  `write_registry`, `upsert_entry`, `resolve_dataset`, `resolve_corpus_path`,
  `resolve_entry_path`, `publish_corpus`, `describe_corpus`, `check_scenario_mix`,
  `check_pairing`, `check_cross_check_subset`, `target_snapshot_path`,
  `write_target_snapshot`, `load_target_snapshot`, `divergence_from_summary`,
  `render_markdown`, `RegistryError`, `DIVERGENCE_PROSE`
- `tests/test_datasets_registry.py` (40 tests) — `NameGateTest`, `PublishTest`,
  `FreezeTest`, `RegistryRoundTripTest`, `ScenarioMixTest`, `PairingTest`,
  `CrossCheckSubsetTest`, `TargetSnapshotTest`, `MarkdownViewTest`

## Verification

All plan-level verification items pass:

1. `uv run python -m unittest tests.test_datasets_registry` — 40 tests, 0.31 s, OK
2. `uv run python -m unittest tests.test_arena_boundary` — 10 tests, OK (the
   recursive `arena/**` scan reaches `registry.py` and finds no evaluator reference)
3. `git check-ignore -v data/datasets.json data/probe.v1.jsonl data/responses/probe.v1.jsonl`
   exits 1 — none is ignored. Same for `data/targets.probe.v1.json` and
   `data/divergence.probe.v1.jsonl`.
4. `uv run python -m unittest` — 584 tests, 5.35 s, OK (budget was 45 s)

Task-1 acceptance greps: `is_relative_to` 1, `sha256_file` 2, `FileExistsError`
outside comments 1, module 880 lines (min 240), `render_markdown` AST-verified
free of `read_text` / `write_text` / `datetime`.

Task-2 acceptance greps: `assertRaises` 32 (min 24), `target_snapshot` 19 (min 3),
`divergence_log` 6 (min 1), skipped tests 0, `assertIn(` 20 (min 4),
`TemporaryDirectory` 19 (min 4), catalog references 0.

## Two-Sided Gate Audit

Seventeen registry branches were broken one at a time in the source and the
corresponding test re-run. Sixteen went red immediately. One did not:

**`test_a_haiku_pair_without_a_sonnet_arm_is_refused` was one-sided.** It built a
pair carrying `control` + `probe_haiku` (two rows) and asserted only that
`RegistryError` was raised. With the D-40 subset check disabled, the *three-arm
row-count* branch further down the same function raised on the same input for a
different reason, so the test stayed green against a corpus whose haiku arm had no
sonnet partner — exactly the silently-shrunk paired n that T-02-30 exists to
prevent. Fixed by asserting the subset branch's own words
(`"subset of probe_sonnet"`), which the row-count message does not contain. The
mutation now produces a red test.

This is the same trap the phase has hit repeatedly: two branches that can raise on
one input make `assertRaises` alone a type check, not a behaviour check.

The source was restored after each mutation with a file-scoped write; `git diff`
against the task-1 commit shows only the intentional `check_scenario_mix` message
change described below. No `git stash`, `git clean` or blanket reset was used.

## Decisions Made

- **`check_cross_check_subset` enforces a non-strict subset.** The plan text says
  "strict subset". The must-have and D-40 both say "subset". Strictness would make
  a fully cross-checked corpus (every pair carrying all three arms) illegal, which
  is a property of the 100-of-700 sampling rather than a correctness invariant, and
  it would also make `synthetic_corpus(n, cross_check_count=n)` unusable as a
  fixture. The refusal that matters — a `probe_haiku` pair with no `probe_sonnet`
  partner to contrast against — is enforced and proved two-sided. Documented in a
  comment at the check itself. **Flagged as a deliberate departure from the plan's
  wording.**
- **The divergence table is stored as `(bucket, ordered-metric-pairs)`.** The plan
  types it `tuple[tuple[str, object], ...]`; a nested dict would break
  `frozen=True` hashability and admit insertion-order drift into a committed file,
  which is the exact defect `CandidateSpec.overrides` documents. A converter
  (`divergence_from_summary`) takes `bucket_summary`'s output directly, and
  `_validate_divergence` refuses an unsorted, duplicated or metric-incomplete table.
- **`resolve_dataset` tolerates a missing registry file.** `data/datasets.json`
  does not exist until 02-11 freezes the first corpus, and 02-10 wires this into
  `run_arena --dataset` before then. A missing registry means every value is
  treated as a path, which is the pre-registry behaviour. Commented at the branch.
- **`response_log_path` / `response_log_sha256` obey the same paired rule** as the
  divergence log and target snapshot, though the plan only specified the rule for
  the latter two. Same failure mode, same guard.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] `publish_corpus` did not validate what it published**

- **Found during:** Task 1
- **Issue:** The plan's `publish_corpus` writes rows through `schema.write_corpus`
  and `os.replace`s them into place with no validation. `SampleRow.validate()` is
  not called by the dataclass constructor, and the D-45 pair-id stem check lives in
  `validate_corpus`, which nothing on this path called. A corpus carrying
  `expanded_dev_v1_0007` ids could therefore be published under `probe.v1`, be
  hashed into `data/datasets.json`, and only fail much later — after its digest was
  already committed and cited. This is the write path for every frozen corpus, so
  it is the last moment a defect is cheap.
- **Fix:** After staging, the file is read back with `load_corpus` and checked with
  `validate_corpus(..., corpus_name=name)` before `os.replace`. Reading back the
  staged bytes rather than checking the in-memory rows also covers a serialization
  defect.
- **Files modified:** `arena/datasets/registry.py`
- **Verification:** `PublishTest.test_publish_refuses_a_corpus_carrying_a_foreign_stem`
  publishes a corpus built with `corpus_stem="expanded_dev_v1"` under the name
  `probe.v1`, asserts the refusal, and asserts no file was left at the destination.
  Two-sided: replacing `validate_corpus(...)` with a bare `load_corpus(...)` turns
  it red.
- **Committed in:** `bd99695`

**2. [Rule 2 - Missing critical functionality] `check_scenario_mix` reported only the first offending scenario**

- **Found during:** Task 2
- **Issue:** The plan's test case is "a corpus built with 80% `buying`, and the
  message names the offending scenario and both proportions". As first written the
  check raised on the first scenario in `SCENARIO_MIX_TARGET` order that deviated,
  which for an 80%-buying corpus is `boundary` — so the message named a scenario
  the author did not change, and the plan's own acceptance case could not be
  satisfied. Beyond the test, raising on the first deviation makes an operator fix
  one share, regenerate a 2,800-session corpus, and rediscover the next.
- **Fix:** All deviating scenarios are collected and named in one message.
- **Files modified:** `arena/datasets/registry.py`
- **Verification:** `ScenarioMixTest.test_a_skewed_corpus_is_refused_with_both_proportions`
  asserts `buying`, `0.8000` and `0.4000` all appear. Two-sided: disabling the
  refusal turns it red.
- **Committed in:** `f9a519d`

---

**Total deviations:** 2 auto-fixed (both Rule 2), 1 deliberate departure from plan
wording (non-strict subset, documented above).
**Impact on plan:** Both auto-fixes are correctness requirements on the freeze path
and on a refusal message a plan acceptance case depended on. No scope creep — both
land inside `arena/datasets/registry.py`, which this plan owns.

## Issues Encountered

- The worktree spawned from the stale base `9faf85c` rather than the intended
  `7dc1ced`, as the dispatch warned. Corrected with `git reset --hard` after the
  `worktree-agent-*` namespace assertion passed.
- One one-sided test found and fixed; see the Two-Sided Gate Audit above.

## Known Stubs

None. Every symbol the plan names is implemented and exercised. The corpora,
`data/datasets.json` and `docs/datasets.md` themselves are deliberately absent —
plans 02-11, 02-12 and 02-13 create them, and this module is what they write
through.

## Threat Flags

None. No new network endpoint, auth path or trust boundary was introduced. The
file-write and name-resolution surfaces are the ones the plan's threat model
already names (T-02-03, T-02-07, T-02-11, T-02-30, T-02-31, T-02-43), and each has
a mitigation with a two-sided test.

## Deferred Items

- **`docs/STATUS.md` constant audit.** CONVENTIONS.md requires each new tuning
  constant to be recorded there under an honesty tier. This plan adds one:
  `_MIX_TOLERANCE = 0.02`. `docs/STATUS.md` is owned this wave by the sibling plan
  02-07, so editing it would collide at merge. It should be recorded by whoever
  next touches that file: *"`_MIX_TOLERANCE` (registry.py) — 0.02, two percentage
  points. Principled in kind (the 40/40/15/5 mix cannot be hit exactly at every
  corpus size), arbitrary in magnitude; at 2,800 sessions two points is 56
  sessions."*

## Next Phase Readiness

Ready for the downstream plans:

- **02-10** calls `resolve_dataset(value, registry_path=..., root=...)` from
  `run_arena --dataset`. Add `RegistryError` to the narrow `except` tuple at
  `run_arena.py:117` and `:177`; it subclasses `RuntimeError`, not `ValueError`,
  so it will not be caught by the existing members.
- **02-11 / 02-12 / 02-13** build entries with `DatasetEntry`, freeze through
  `publish_corpus`, record with `upsert_entry` + `write_registry`, and render
  `docs/datasets.md` with `render_markdown`. `describe_corpus` returns
  `session_count`, `distinct_target_count` and `scenario_mix` in exactly the shapes
  `DatasetEntry` expects. Note `divergence_from_summary` converts
  `bucket_summary`'s output into the entry's table shape.
- The `"public"` entry is admitted without a version suffix and expects
  `generator_model_alias="organizer"` / `generator_model_resolved="organizer-supplied"`.
- The D-58 correction is honoured: nothing in this module or its tests hard-codes a
  corpus count, and the deferred sweeps are described in the test module docstring
  as covering four corpora.

## Self-Check: PASSED

- `arena/datasets/registry.py` — present, 880 lines, committed in `bd99695`
- `tests/test_datasets_registry.py` — present, 621 lines, committed in `f9a519d`
- `.planning/phases/02-expanded-dataset-paraphrase-probe/02-08-SUMMARY.md` — present
- Commits `bd99695`, `f9a519d`, `157d76e` all present on
  `worktree-agent-a5f07fb3bd994233f`
- Working tree clean; `STATE.md` and `ROADMAP.md` untouched, as is
  `docs/STATUS.md` (owned by sibling plan 02-07 this wave)

---
*Phase: 02-expanded-dataset-paraphrase-probe*
*Completed: 2026-09-01*
