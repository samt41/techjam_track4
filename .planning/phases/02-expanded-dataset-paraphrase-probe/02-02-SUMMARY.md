---
phase: 02-expanded-dataset-paraphrase-probe
plan: 02
subsystem: arena-reporting
tags: [reporting, measurement-rig, d-53, d-45, d-58, corpus-baselines]
requires:
  - arena/leaderboard.py (_table, _cell, CandidateEntry, _display_fingerprint)
  - arena/metrics.py (metric_summary, efficiency, technical_score, scenario_breakout)
  - arena/store.py (ArenaStoreError, BASELINES_ROOT, write_json)
provides:
  - arena.leaderboard.build_corpus_baselines
  - arena.leaderboard.render_corpus_baselines_markdown
  - arena.leaderboard.write_corpus_baselines
  - arena.leaderboard.CORPUS_BASELINES_SCHEMA_VERSION
  - arena.leaderboard.CORPUS_BASELINES_JSON_PATH
  - arena.leaderboard.CORPUS_BASELINES_MARKDOWN_PATH
  - arena.leaderboard.CORPUS_BASELINES_READING
affects:
  - plan 02-13 (operator step that generates experiments/CORPUS_BASELINES.md)
tech-stack:
  added: []
  patterns:
    - "JSON is truth, Markdown is a generated view (D-12)"
    - "Pure renderer: no I/O, no clock, mirroring render_markdown's contract"
    - "Explicit sort, never dict insertion order"
    - "Efficiency rounded at the output boundary only (T-01-16c)"
    - "Refuse at the boundary with a lowercase domain-specific ArenaStoreError"
key-files:
  created: []
  modified:
    - arena/leaderboard.py
    - tests/test_arena_leaderboard.py
decisions:
  - "An empty corpus-baselines payload is REFUSED, not rendered with _table's `_none_` fallback"
  - "Rows are keyed under a top-level `corpora` list; `baseline_fingerprint` and `adjudication` are deliberately absent"
  - "CORPUS_BASELINES_JSON_PATH built from BASELINES_ROOT, matching LEADERBOARD_JSON_PATH's idiom"
  - "CORPUS_BASELINES_READING is a module constant emitted into the payload, mirroring HOW_TO_READ"
requirements: [MEAS-10, MEAS-13]
metrics:
  duration: ~35 min across two sessions (one 429 interruption)
  tasks: 2
  commits: 2
  tests_added: 11
  tests_total: 395
  completed: 2026-09-01
---

# Phase 02 Plan 02: Corpus-Baselines Reporting Surface Summary

A separate `corpus_baselines.json` / `CORPUS_BASELINES.md` pair that reports one
candidate measured across the four Phase 2 corpora, structurally unmixable with the
leaderboard's same-corpus candidate table.

## What Was Built

`arena/leaderboard.py` gains three functions, three path/version constants and one
prose constant, added strictly as siblings — `build_leaderboard`, `render_markdown`
and `write_leaderboard` are untouched.

**`build_corpus_baselines(rows: tuple[tuple[str, CandidateEntry], ...])`** takes
`(dataset_name, entry)` pairs and refuses four ways: an empty row set, a duplicate
`dataset_name`, a duplicate `entry.fingerprint`, and a second `entry.name`. Rows are
sorted by `dataset_name` ascending (`dataset_name` is unique by the refusal above, so
it is a total order needing no further tie-break). Each row carries `dataset_name`
first, plus `run_id`, `name`, `fingerprint`, `code_revision`, `code_revision_dirty`,
`overrides`, `provenance`, `sample_count`, `hit_rate_at_10`, `mrr`, `mttc`,
`efficiency` (6-dp rounded at this output boundary, per T-01-16c), `technical_score`,
and a `scenario_breakout` list carrying each `scenario.as_record()` plus its own
`technical_score`. Top level emits `schema_version`, `candidate_name`, `corpus_count`,
`reading` and `corpora`.

**`render_corpus_baselines_markdown(payload)`** is pure — no I/O, no clock, asserted
both by `inspect.getsource` and by an AST walk over the function node. It reuses
`_table` and `_cell` verbatim and emits a `# Corpus Baselines` heading, the `reading`
prose, an eight-column per-corpus table, and a nine-column per-scenario table whose
header matches the leaderboard's scenario table with only `Candidate` → `Corpus`
changed, so a reader moving between the two reports does not relearn the columns.

**`write_corpus_baselines(payload, *, json_path, markdown_path)`** mirrors
`write_leaderboard`'s shape exactly: `write_json` for the payload, `write_text` for the
rendered Markdown, both paths returned.

**`CORPUS_BASELINES_READING`** states in the record's own words that these rows are one
candidate across four corpora, that they are therefore not comparable to each other as
candidates, that `adjudicate` refuses them by design (D-45), that neither a Holm family
nor a winner's-curse correction applies because nothing here is selected or tested, and
that the "five" in D-45/D-48 predates D-46's consolidation of the probe's three arms
into one file — D-58 corrects it to four.

## Count Correction Carried Through

There are **four** corpora, not five: `public`, `expanded_dev.v1`,
`expanded_confirm.v1`, `probe.v1`. Nothing hard-codes a row count; `corpus_count` is
`len(rows)`. Every `reading` sentence, comment and test says four, and the test asserts
`corpus_count == 4` against the rendered table's own row count, so the D-58 correction
is machine-checked rather than left to prose.

## Path Pinning (L-13 / T-02-15)

`CORPUS_BASELINES_JSON_PATH = BASELINES_ROOT / "corpus_baselines.json"` and
`CORPUS_BASELINES_MARKDOWN_PATH = Path("experiments/CORPUS_BASELINES.md")`, with the
reason commented at the definition. `.gitignore` line 9 excludes `experiments/*/` (all
directories) and line 15 re-includes `experiments/baselines/`, so the JSON is committed
because it sits in the one re-included directory and the Markdown is committed because
it sits at the top level of `experiments/` beside `LEADERBOARD.md` rather than in a
subdirectory of its own. Verified: `git check-ignore -v` exits 1 (not ignored) for both.

## Tests

`CorpusBaselinesTest` in `tests/test_arena_leaderboard.py`, 11 methods, two-sided.

Fixture: four `CandidateEntry` values sharing the name `baseline-auto-disabled`,
differing only in `dataset_sha256` (content-derived from the corpus name), which is what
mints four distinct fingerprints for one configuration and is exactly why `adjudicate`
refuses them as arms. The four real corpus names are handed over deliberately unsorted
so the builder's explicit sort is exercised rather than inherited.

Positive: ascending corpus order (with a non-vacuity assertion that the input order
differs from the output order); every row carries its own `dataset_name` and a
`technical_score` recomputed from that corpus's sessions rather than read back off the
row; the render names every corpus, contains `Holm` and `winner's-curse` in the prose,
and contains no `_none_` placeholder; the render is deterministic; the payload is
JSON-serializable with sorted keys.

Negative: duplicate `dataset_name`, duplicate `fingerprint`, a second candidate name
(asserting the message names "one candidate"), and an empty row set each raise
`ArenaStoreError`.

Separation, asserted in both directions rather than as a claim about one payload: the
corpus payload's top-level keys are exactly
`["candidate_name", "corpora", "corpus_count", "reading", "schema_version"]` with no
`adjudication` and no `baseline_fingerprint`; and the leaderboard payload does carry
both while carrying no `corpora` and no `corpus_count`.

## Verification

| Check | Result |
|---|---|
| Task 1 symbol/purity gate (`inspect` + constant paths + `build_leaderboard` untouched) | exits 0 |
| AST purity of `render_corpus_baselines_markdown` (no `datetime`/`read_text`/`write_text`) | exits 0 |
| `grep -v '^\s*#' arena/leaderboard.py \| grep -c CORPUS_BASELINES_MARKDOWN_PATH` | 2 (≥ 2 required) |
| `uv run python -m unittest tests.test_arena_leaderboard` | 52 tests, OK (was 41 — +11, ≥ 6 required) |
| `uv run python -m unittest` | 395 tests, OK (was 384) |
| `grep -c assertRaises tests/test_arena_leaderboard.py` | 7 (was 3 — +4, ≥ 3 required) |
| `grep -c corpus_count tests/test_arena_leaderboard.py` | 6, asserted value is 4 |
| `git check-ignore -v experiments/CORPUS_BASELINES.md` | exit 1 (not ignored) |
| `git check-ignore -v experiments/baselines/corpus_baselines.json` | exit 1 (not ignored) |

The Task 1 gate is genuinely two-sided: it names symbols that did not exist before the
task, so it was red against untouched source, unlike the pre-existing module test which
already passed and would have proved nothing until Task 2 landed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Mixed-candidate-name test fixture tripped the wrong guard**
- **Found during:** Task 2
- **Issue:** `test_a_second_candidate_name_is_rejected` built its fourth row under the
  corpus name `public`, which `_corpus_rows()[:3]` already contained. The duplicate
  dataset-name refusal fired first, so the mixed-name guard was never exercised and the
  message assertion failed.
- **Fix:** The fourth row now uses `expanded_dev.v1` — the one corpus name
  `_corpus_rows()[:3]` leaves unused — so dataset names and fingerprints both stay
  unique and the only thing wrong with the input is the second candidate name. Added
  two explicit set-size assertions pinning that, plus a comment recording why reusing a
  present corpus name would leave the guard unexercised. The guard itself was not
  weakened.
- **Files modified:** `tests/test_arena_leaderboard.py`
- **Commit:** 2ca45fc

### Decisions Made Inside Plan Latitude

**Empty payload: refusal, not the `_none_` fallback.** Task 2 explicitly left this
choice open. Refusal was taken because this file's entire claim is "one candidate,
measured across these corpora"; a header with an empty body would publish that claim
with no evidence under it, and `candidate_name` would be underivable. `_table`'s
`_none_` fallback remains correct for the leaderboard's adjudication section, which can
legitimately have adjudicated nothing. The choice is commented at the raise site and at
the asserting test.

**Rows keyed under `corpora`.** The plan specified the per-row and top-level fields but
not the key holding the rows. `corpora` was chosen so the payload reads as "one
candidate, these corpora" rather than borrowing the leaderboard's `candidates`.

**`CORPUS_BASELINES_JSON_PATH` built from `BASELINES_ROOT`.** The plan wrote it as a
literal `Path("experiments/baselines/corpus_baselines.json")`; using `BASELINES_ROOT /
"corpus_baselines.json"` resolves to the identical path and matches the existing
`LEADERBOARD_JSON_PATH` idiom one line above. Asserted via `.as_posix()` in the gate.

**`write_corpus_baselines` given defaults.** The plan's signature had bare keyword-only
parameters; `write_leaderboard` defaults its two paths, and the instruction was to
mirror its shape exactly, so the defaults were added. This is also what supplies the
second non-comment reference to `CORPUS_BASELINES_MARKDOWN_PATH`.

## Threat Flags

None. The plan's threat register (T-02-09, T-02-14, T-02-15) is fully mitigated by this
plan's own output, and no new security-relevant surface was introduced — this is a pure
reporting transform over already-retained records, with no network, no subprocess, no
new dependency and no untrusted input path.

## Known Stubs

None. Every symbol this plan promised is implemented and exercised. The two committed
artifacts at `experiments/baselines/corpus_baselines.json` and
`experiments/CORPUS_BASELINES.md` are deliberately not written by this plan — plan 02-13
is the operator step that generates them, which is why this plan builds the surface
against fixtures.

## Notes for Downstream Plans

- Plan 02-13 only has to call `build_corpus_baselines` then `write_corpus_baselines`;
  both destination paths default correctly and both are committed by `.gitignore`.
- The four `(dataset_name, CandidateEntry)` pairs must come from four retained records.
  `CandidateEntry` carries no digests (RESEARCH L-10), so if 02-13 needs the
  `dataset_sha256` values it must read them via `spec_from_record(run_directory)`.
- `build_corpus_baselines` refuses a second candidate name, so a future "compare two
  candidates across corpora" report is a different function, not a relaxation of this
  one.

## Self-Check: PASSED

- `arena/leaderboard.py` — FOUND
- `tests/test_arena_leaderboard.py` — FOUND
- `.planning/phases/02-expanded-dataset-paraphrase-probe/02-02-SUMMARY.md` — FOUND
- Commit `5e1b86e` — FOUND
- Commit `2ca45fc` — FOUND
