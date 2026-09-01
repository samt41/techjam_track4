---
phase: 02-expanded-dataset-paraphrase-probe
plan: 04
subsystem: arena/datasets
tags: [anti-circularity, gist, d-32, d-52, meas-12, build-time-asset]
requires:
  - arena/store.py (sha256_file, write_json)
  - arena/evaluator_bridge.py (searchable_text)
  - arena/datasets/__init__.py (plan 02-01)
  - starter/shopping_agent/catalog_index.py (CatalogIndex.value_counts)
  - data/catalog.artifacts/catalog.sqlite3 (CLI build only, never at use time)
provides:
  - arena.datasets.gist.load_vocabulary
  - arena.datasets.gist.gist_for_target
  - arena.datasets.gist.prompt_payload_strings
  - arena.datasets.gist.load_feature_abstractions
  - arena.datasets.gist.build_vocabulary
  - arena.datasets.gist.GistPair
  - arena.datasets.gist.GistVocabulary
  - arena/datasets/assets/gist_vocabulary.json
  - arena/datasets/assets/feature_abstractions.json
affects:
  - docs/STATUS.md (two tier-2 constants, one tier-3 table)
tech-stack:
  added: []
  patterns: [committed-json-asset, cli-only-build-path, frozen-slotted-dataclass, ast-boundary-scan]
key-files:
  created:
    - arena/datasets/gist.py
    - arena/datasets/assets/gist_vocabulary.json
    - arena/datasets/assets/feature_abstractions.json
    - tests/test_datasets_gist.py
  modified:
    - docs/STATUS.md
decisions:
  - "Abstract attribute names are two-word compounds, not the obvious single word: `ground_contact` over `underfoot`, `entry_method` over `fastening`, `heel_geometry` over `elevation`. A single common apparel word passes the per-row echo check but collides with unrelated product copy at corpus scale."
  - "The gist reproduces the artifact builder's material and keyed-feature recovery, but gates it on the committed DF>=10 vocabulary rather than the builder's DF>=2 floors, so recovery can only widen coverage with values the floor already admits."
  - "`GistPair.validate()` forbids `=` in either field, so the one-`=` payload guarantee holds at construction rather than at serialization."
  - "`tests/test_datasets_gist.py` declares its own module-private product helper instead of importing the sibling-owned `tests/dataset_fixtures.py`, which does not exist at this plan's base commit."
metrics:
  duration: ~50 min
  tasks: 3
  files-created: 4
  files-modified: 1
  tests-added: 30
  tests-total: 428
  completed: 2026-09-01
---

# Phase 02 Plan 04: D-32 Anti-Circularity Gist Summary

A document-frequency-gated attribute gist that is the only thing a corpus-authoring
model ever sees about a target, plus the D-52 abstraction table that closes the
measured 8% hole where a DF floor alone still admits verbatim catalog boilerplate.

## What Was Built

`arena/datasets/gist.py` (444 lines) implements two distinct anti-circularity
mechanisms, and the distinction between them is the whole design:

- **Canonical attributes** (`color`, `material`, `size`, `style`) are gated by
  `_GIST_DF_FLOOR = 10`. A value carried by at least 10 of 50,000 products is shared
  vocabulary and cannot identify one target, so it is admitted **verbatim on purpose**
  — D-32's own worked example is `material=leather`.
- **`feature`** is not gated by frequency at all. Its high-DF survivors are verbatim
  catalog boilerplate (`imported` 13,832, `machine wash` 8,899, `rubber sole` 5,616),
  so every admitted feature pair is routed through the committed 90-row abstraction
  table and the catalog string never leaves the module.

`prompt_payload_strings` is the single narrow data-flow surface, which is what lets
MEAS-12 be asserted as a property of the code rather than as prompt discipline.

Measured vocabulary: 174 admitted values — material 65, feature 55 abstract tokens,
color 24, style 19, size 11. `admitted_total=174`, `df_floor=10`, catalog
`da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`.

## Tasks

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | D-52 feature abstraction table | `ec13d45` | `arena/datasets/assets/feature_abstractions.json`, `docs/STATUS.md` |
| — | Abstract attribute naming hardening (Rule 2) | `c2bf22a` | both assets, `docs/STATUS.md` |
| 2 | `gist.py` + CLI-built vocabulary | `faf3b2d` | `arena/datasets/gist.py`, `arena/datasets/assets/gist_vocabulary.json`, `docs/STATUS.md` |
| 3 | MEAS-12 gist tests | `a6aa3c5` | `tests/test_datasets_gist.py` |

## Verification

All four plan-level verification steps pass:

1. `uv run python -m unittest tests.test_datasets_gist` — 30 tests, 0.021 s, OK.
2. `uv run python -m unittest tests.test_arena_boundary` — 10 tests, OK. `gist.py` is
   inside the recursive `arena/**` scan and imports no evaluator name directly.
3. `uv run python -m unittest` — **428 tests in 5.0 s, OK** (398 at base + 30 new).
   Also green under `-W error::ResourceWarning`.
   `grep -n "catalog.artifacts\|catalog.jsonl\|local_search_backend" tests/test_datasets_gist.py`
   returns nothing.
4. A fresh `uv run python -m arena.datasets.gist` reproduces the committed
   `gist_vocabulary.json` **byte for byte** (11,153 bytes).

Additional acceptance evidence:

- `load_vocabulary()` succeeds with `data/catalog.artifacts/` renamed away — proved by
  actually renaming it, loading 89 abstractions, then restoring it.
- `grep -v '^\s*#' arena/datasets/gist.py | grep -c "_GIST_DF_FLOOR"` = 4 (≥ 2);
  `grep -B4 "_GIST_DF_FLOOR = 10" arena/datasets/gist.py | grep -c "#"` = 4 (≥ 2).
- `grep -c "_GIST_DF_FLOOR\|_FEATURE_ABSTRACTION_DF_FLOOR" docs/STATUS.md` = 2.
- `grep -c "feature_abstractions.json" docs/STATUS.md` = 1, in the tier-3 section
  alongside `_EXPANSIONS`, naming D-52.
- `grep -c "searchable_text" tests/test_datasets_gist.py` = 2;
  `grep -c "from evaluator" ...` = 0;
  `grep -c "assertFalse\|assertRaises\|assertIn(" ...` = 16 (≥ 5).
- 90 abstraction rows, every one with the four required keys and
  `document_frequency >= 100`; the file round-trips byte-identically through
  `arena.store.write_json`.

## Two-Sided Gate Measurement

Per the verification discipline, every gate this plan ships was measured in **both**
directions — confirmed to fail against a deliberately broken version, not just to pass
against the real one.

| Gate | Broken version applied | Result |
| ---- | ---------------------- | ------ |
| Task 1 echo check | Scratch copy with `{"value": "rubber sole", "attribute": "sole_material", "token": "rubber"}` | **exit 1**, names the offending row |
| `_GIST_DF_FLOOR` in `build_vocabulary` | `count >= _GIST_DF_FLOOR` → `count >= 1` in `arena/datasets/gist.py` | **7 failures** |
| FEATURE excluded from the DF path | `_STRUCTURED_ATTRIBUTES` widened to include `Attribute.FEATURE` | **1 failure**, `'rubber sole' unexpectedly found` |
| Committed asset's feature vocabulary | `"rubber sole"` injected into `gist_vocabulary.json`'s feature list | **2 failures** |
| Clause 2 span check | Identity "abstraction" (`rubber sole` → `feature=rubber sole`) | violation reported, asserted |
| Clause 2 scoping | Same check widened to all attributes on the leather boot | violation reported on `material=leather`, asserted |
| Catalog-freedom AST scanner | Temp probe importing the SQLite backend; temp probe with an artifact path constant | scanner fires on both |
| Catalog-freedom AST scanner | Clean temp probe importing only `json` | scanner silent |

Both mutations to `arena/datasets/gist.py` were reverted with a file-scoped
`git checkout -- arena/datasets/gist.py` and the suite re-confirmed green before the
plan continued. No `git clean`, `git stash`, or blanket reset was used.

**No one-sided gate was found in this plan.** One risk the plan flagged is real and
was handled by design: a token-level clause 2 over *all* pairs is unsatisfiable,
because the positive case (`material=leather` on a leather boot) and the gate would
contradict. `ScopingCompanionTest` pins that from the other side, so a future reader
who "strengthens" clause 2 gets a red test naming the reason instead of a permanently
red MEAS-12.

The `_GIST_DF_FLOOR` measurement deserves a specific note, because it is what the
brief singled out. `test_a_product_below_the_floor_yields_an_empty_gist` alone would
still pass if the floor were deleted and the exclusion happened to come from
elsewhere. `BuildVocabularyFloorTest` therefore drives `build_vocabulary` against a
stub index with **known** counts and asserts, per value, that
`value in admitted == (count >= _GIST_DF_FLOOR)` — including a value at exactly the
floor (admitted) and one exactly below it (excluded), each shown to be present in the
source counts first. Deleting the floor turns seven tests red.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Abstract attribute names hardened against corpus-scale collision**

- **Found during:** Task 3, while reasoning about what clause 2 would do across the
  full corpus rather than the four hand-written products.
- **Issue:** Six of the abstraction table's attribute names were single common apparel
  words — `fastening`, `underfoot`, `construction`, `optics`, `substance`,
  `elevation`. Each passes the per-row echo check (none is a substring of *its own*
  source value), but each is likely to appear verbatim in an *unrelated* product's
  `searchable_text`. Clause 2 cannot distinguish that false positive from a genuine
  leak, so at corpus scale the gate would fire on correct output — a one-sided gate of
  exactly the class this project has shipped before.
- **Fix:** Renamed to two-word compounds — `entry_method`, `ground_contact`,
  `garment_build`, `lens_treatment`, `composition_class`, `heel_geometry` — and the
  two dependent tokens `glare_filtering` → `glare_reducing`, `unfiltered_glare` →
  `glare_permitting`. Rebuilt both assets; the echo check and byte-reproducibility
  both still pass. The reasoning is recorded in `docs/STATUS.md` so the naming
  constraint is not lost.
- **Files modified:** `arena/datasets/assets/feature_abstractions.json`,
  `arena/datasets/assets/gist_vocabulary.json`, `docs/STATUS.md`
- **Commit:** `c2bf22a`

**2. [Rule 3 - Blocking] Test fixture dependency on a sibling plan's file**

- **Found during:** Task 3.
- **Issue:** The task's `read_first` names `tests/dataset_fixtures.py` `product(...)`
  from plan **02-03**, a sibling running in the same wave. That file does not exist at
  this plan's base commit, and `tests/dataset_fixtures.py` is not in this plan's
  `files_modified`, so creating it would collide at merge.
- **Fix:** `tests/test_datasets_gist.py` declares a module-private `_product(...)`
  helper with the same shape. The leading underscore is deliberate so the two cannot
  collide when the shared fixture lands; a later plan can swap the import in one line.
- **Files modified:** `tests/test_datasets_gist.py`
- **Commit:** `a6aa3c5`

**3. [Rule 3 - Blocking] Catalog inputs absent from the worktree**

- **Found during:** Task 1 setup.
- **Issue:** `data/catalog.jsonl` and `data/catalog.artifacts/` are `.gitignore`d, so
  a fresh worktree has neither. Tasks 1 and 2 both need them.
- **Fix:** Created a directory junction and a hardlink from the worktree's `data/` to
  the main checkout's copies. Both paths are gitignored, so nothing entered the commit
  set; `git status --short` was clean of them throughout. Rebuilding the 580 MB
  artifact from scratch (~60-90 s) was unnecessary.
- **Files modified:** none (untracked, ignored)

### Scope Note

The plan's `files_modified` set was honoured exactly. `git diff --name-status
708edfe..HEAD` shows five paths, all declared:
`arena/datasets/gist.py`, `arena/datasets/assets/gist_vocabulary.json`,
`arena/datasets/assets/feature_abstractions.json`, `tests/test_datasets_gist.py`,
`docs/STATUS.md`. No shared orchestrator artifact (`STATE.md`, `ROADMAP.md`) was
touched. No file was deleted by any commit.

## Design Notes for Downstream Plans

- **Solvability is guaranteed by construction (D-35).** Every gist pair is derived
  from the target's own attributes, so every pair is true of the target. A
  retrieval-based solvability check downstream would measure the agent, not the
  corpus — this is commented at `gist_for_target`.
- **`use_case` and `other` are absent, not excluded.** The artifact's `attributes`
  table has zero rows for either. `_GIST_ATTRIBUTES` comments this so a future reader
  does not "restore" them.
- **`brand` and `category` are excluded** because `classify_constraint` can never
  return either, and a brand name (19,747 distinct values over 50,000 products) is a
  direct identity leak. **`budget`** is excluded because it is 0 of 798 control-card
  constraints (L-7).
- **`build_vocabulary` sorts `value_counts` explicitly** by `(-count, value)` (L-17:
  `values_for` sorts, `value_counts` does not). That explicit key is what makes the
  committed asset byte-reproducible; the ordering is asserted by
  `test_admitted_values_are_ordered_by_descending_document_frequency`.
- **The SQLite backend is imported inside `main()`, not at module scope**, so no
  downstream generator or test pulls it into its import graph.
- **One abstraction row is deliberately null** (`shaft measures approximately
  not_applicable from arch`): recorded so the table's coverage stays auditable,
  excluded from the gist because the value carries nothing recoverable. 90 rows total,
  89 admitted.

## Known Stubs

None. Every symbol this plan declares is implemented and exercised; the committed
assets are real build products, byte-reproducible from the catalog.

## Threat Flags

None. The plan's `<threat_model>` mitigations (T-02-05, T-02-18, T-02-19, T-02-20)
are all implemented and asserted. No new network endpoint, auth path, file access
pattern, or schema at a trust boundary was introduced beyond the two committed JSON
assets already in the register. No package-manager install occurred.

## Self-Check: PASSED

- All five claimed files exist on disk.
- All four claimed commits (`ec13d45`, `faf3b2d`, `c2bf22a`, `a6aa3c5`) are present in
  `git log`.
- Full suite green at 428 tests.
