---
phase: 2
slug: expanded-dataset-paraphrase-probe
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-31
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `02-RESEARCH.md` § "Validation Architecture" (commit `35ec32d`).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `unittest` (Python standard library). No pytest, no plugins, no config file. |
| **Config file** | none — discovery is `python -m unittest` from the repository root |
| **Quick run command** | `uv run python -m unittest tests.test_datasets_<module> -v` (single module, < 2 s) |
| **Full suite command** | `uv run python -m unittest` |
| **Warning-strict variant** | `uv run python -W error::ResourceWarning -m unittest -v` |
| **Estimated runtime** | ~22 s at phase entry (384 tests, measured); budget < 45 s at phase exit |
| **Fixture pattern** | `tests/fixtures.py` (12-product temporary artifact), `tests/arena_fixtures.py` (committed record + `dataclasses.replace`). No test loads the 61 MB catalog or the 580 MB artifact. |

---

## Sampling Rate

- **After every task commit:** Run `uv run python -m unittest tests.test_datasets_<module>` (< 2 s)
- **After every plan wave:** Run `uv run python -m unittest` (full suite)
- **Before `/gsd-verify-work`:** Full suite green **plus** the five D-48 baseline records published and the `paired_contrast` report regenerated
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

Task IDs are bound at planning time. This map is requirement-keyed; the planner
MUST attach each row's automated command to the task that implements it, and the
executor MUST NOT close a task whose row is still `⬜ pending`.

| Requirement | Behavior | Threat Ref | Test Type | Automated Command | File Exists | Status |
|---|---|---|---|---|---|---|
| MEAS-10 | Static schema layer: every row carries `intent_card` with non-empty `hard_constraints`/`soft_preferences` and a `behavior` with `scenario_type` (D-37) | V5 | unit | `uv run python -m unittest tests.test_datasets_schema` | ❌ W0 | ⬜ pending |
| MEAS-10 | Dynamic layer: `materialize_hidden_fields` returns the row's own `intent_card` by identity for 100% of rows — proves branch 1 fired (D-37) | — | integration (catalog-free, `products={}`) | `uv run python -m unittest tests.test_datasets_conformance` | ❌ W0 | ⬜ pending |
| MEAS-10 | `intent_override` rows carry all four override keys; `override["turn"] ∈ [2,10]`; `behavior["scenario_type"] == row["scenario_type"]` | V5 | unit | `uv run python -m unittest tests.test_datasets_schema` | ❌ W0 | ⬜ pending |
| MEAS-10 | Scenario mix is 40/40/15/5 in every corpus (D-30) | — | unit over committed corpora | `uv run python -m unittest tests.test_datasets_registry` | ❌ W0 | ⬜ pending |
| MEAS-11 | Every probe row has exactly one `control` partner with the same `pair_id` and same `ground_truth.parent_asin` | — | unit | `uv run python -m unittest tests.test_datasets_registry` | ❌ W0 | ⬜ pending |
| MEAS-11 | `arm ∈ {control, probe_sonnet, probe_haiku}`; each `pair_id` has ≥2 arms; the 100 cross-check pairs have exactly 3 (D-40) | — | unit | `uv run python -m unittest tests.test_datasets_registry` | ❌ W0 | ⬜ pending |
| MEAS-11 | `align_on_pair_id` refuses an unmatched pair rather than silently inner-joining | V5 | unit | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ W0 | ⬜ pending |
| MEAS-11 | Control arm reproduces the public path: control row and bare row drive byte-identical customer behavior — **scoped to non-override scenarios per D-55** | — | integration, 12-product fixture | `uv run python -m unittest tests.test_datasets_control_fidelity` | ❌ W0 | ⬜ pending |
| MEAS-12 | Data-flow assertion: no string in an authoring prompt payload is a substring of `searchable_text(target)` (D-32) | V5 / prompt-injection | unit | `uv run python -m unittest tests.test_datasets_gist` | ❌ W0 | ⬜ pending |
| MEAS-12 | DF floor admits only values clearing the pinned constant; the constant is a named module-level symbol with commented rationale | — | unit | `uv run python -m unittest tests.test_datasets_gist` | ❌ W0 | ⬜ pending |
| MEAS-12 | Feature-abstraction table (D-52) maps every high-DF boilerplate value; no admitted `feature` gist value is a verbatim catalog span | V5 | unit | `uv run python -m unittest tests.test_datasets_gist` | ❌ W0 | ⬜ pending |
| MEAS-12 | D-33 bucket gate: `classify_constraint(probe) == classify_constraint(control)` for 100% of committed probe rows | — | unit over committed corpus | `uv run python -m unittest tests.test_datasets_divergence` | ❌ W0 | ⬜ pending |
| MEAS-12 | D-34 gate: zero non-pinned content-token overlap and zero shared 2-gram for 100% of committed probe rows, on the **corrected** seven-substring colour list (D-51) | — | unit over committed corpus | `uv run python -m unittest tests.test_datasets_divergence` | ❌ W0 | ⬜ pending |
| MEAS-12 | **Two-sided check:** the gate FAILS a synthetic violating row (a gate that always passes is not a gate) | — | unit, synthetic row | `uv run python -m unittest tests.test_datasets_divergence` | ❌ W0 | ⬜ pending |
| MEAS-12 | Freeze: every corpus's on-disk sha256 equals its `data/datasets.json` entry | V6 | unit | `uv run python -m unittest tests.test_datasets_registry` | ❌ W0 | ⬜ pending |
| MEAS-12 | Registry resolution refuses a corpus whose sha256 has drifted | V6 / V12 | unit, temp corpus | `uv run python -m unittest tests.test_datasets_registry` | ❌ W0 | ⬜ pending |
| MEAS-13 | The `probe_haiku` arm's 100 `pair_id`s are a subset of the `probe_sonnet` `pair_id`s (D-40) | — | unit | `uv run python -m unittest tests.test_datasets_registry` | ❌ W0 | ⬜ pending |
| MEAS-13 | Each corpus's response log records exactly one resolved model id, matching `data/datasets.json` (guards alias drift) | V7 | unit | `uv run python -m unittest tests.test_datasets_authoring` | ❌ W0 | ⬜ pending |
| MEAS-13 | Generator-affinity contrast (`probe_sonnet` vs `probe_haiku` on 100 matched targets) produces a `paired_contrast` record carrying its MDD and observed ψ | — | unit, fixture sessions | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ W0 | ⬜ pending |
| D-35 | Authoring driver argv never contains `-c`, `--continue`, `-r`, `--resume` | — | unit, argv-builder introspection | `uv run python -m unittest tests.test_datasets_authoring` | ❌ W0 | ⬜ pending |
| D-35 | Review payload key set is exactly `{gist_attribute, gist_value, phrase}` | V5 | unit | `uv run python -m unittest tests.test_datasets_authoring` | ❌ W0 | ⬜ pending |
| D-57 | Authoring driver argv contains `--setting-sources ""` and an explicit clean cwd, so the project `CLAUDE.md` never enters the authoring context | prompt-injection | unit, argv-builder introspection | `uv run python -m unittest tests.test_datasets_authoring` | ❌ W0 | ⬜ pending |
| D-44 | `paired_contrast` never calls `holm_bonferroni` or `winners_curse_correction` | — | unit, AST scan | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ W0 | ⬜ pending |
| D-44 | `mcnemar_exact` reproduces hand-checkable values: `(20,4)→0.00154`, `(18,6)→0.02266`, `(0,0)→1.0`, `(5,5)→1.0` | — | unit | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ W0 | ⬜ pending |
| D-44 | `paired_contrast` is byte-reproducible: two calls with identical inputs return identical records (D-24 content-seeding) | — | unit, `resamples=500` | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ W0 | ⬜ pending |
| D-45 | `adjudicate` refuses two arms with differing `dataset_sha256` — refusal path now reachable with five live corpora | V5 | unit | `uv run python -m unittest tests.test_arena_adjudication` | ✅ module exists; case is W0 | ⬜ pending |
| D-45 inverse | `paired_contrast` refuses two arms with the *same* `dataset_sha256`, or differing `catalog_sha256`/`code_revision`/`overrides` | V5 | unit | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ W0 | ⬜ pending |
| D-47 | Seam re-exports exactly eight names; still zero `FunctionDef`/`ClassDef`; evaluator sha256 unchanged | — | unit | `uv run python -m unittest tests.test_arena_boundary` | ✅ module exists; constants change | ⬜ pending |
| D-47 | The boundary scan **recurses** into `arena/datasets/` and fires on a nested violation (L-1) | — | unit | `uv run python -m unittest tests.test_arena_boundary` | ✅ module exists; case is W0 | ⬜ pending |
| Determinism | Replay mode reproduces each committed corpus byte-for-byte from the committed digest+result log (D-50) | — | integration | `uv run python -m unittest tests.test_datasets_authoring` | ❌ W0 | ⬜ pending |
| D-56 | Five D-48 baseline records exist, one per corpus, each with a distinct `dataset_sha256` fingerprint | — | unit over published records | `uv run python -m unittest tests.test_datasets_registry` | ❌ W0 | ⬜ pending |
| D-53 | Baseline records render in a corpus-baselines table, not intermixed with `LEADERBOARD.md` candidate rows | — | unit | `uv run python -m unittest tests.test_arena_leaderboard` | ✅ module exists; case is W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Roadmap Success Criteria → assertions

| # | Criterion | Machine-checkable assertion |
|---|-----------|------------------------------|
| 1 | Expanded sessions always take the authored branch, verified programmatically | D-37 static + dynamic tests; the dynamic one asserts *identity* (`is`), which is what proves branch 1 fired |
| 2 | Matched control/probe pairs on the same hidden target | `pair_id` completeness + `ground_truth.parent_asin` equality within a pair; `align_on_pair_id` refusal on any orphan |
| 3 | Anti-circular authoring verified; lexical-overlap ratio reported per pair as an acceptance gate | prompt data-flow substring assertion + D-34 gate over 100% of rows + a per-pair `overlap_ratio` in the registry + the two-sided gate test |
| 4 | Second model family independently authored a cross-check subset; any gap reported explicitly | resolved-model-id uniqueness per corpus + three-arm subset assertion + a `paired_contrast` record for `probe_sonnet` vs `probe_haiku` carrying MDD and observed ψ. **Scoped limitation (D-39/D-49): both arms are Anthropic-family, so this bounds model-scale and prompt-lineage affinity, not vendor-family affinity.** The limitation must appear in the generated report text, not only here. |
| 5 | Probe checksummed and frozen before Phase 3/4 measures against it | `data/datasets.json` sha256 verification test + recorded commit hash field + registry-resolution refusal on drift |

---

## Wave 0 Requirements

- [ ] `tests/dataset_fixtures.py` — tiny synthetic corpora (control/probe pairs across all four scenarios and all reachable buckets), a fake authoring runner, a recorded `claude -p` response envelope. Mirrors `tests/arena_fixtures.py`.
- [ ] `tests/test_datasets_schema.py` — MEAS-10 static layer
- [ ] `tests/test_datasets_conformance.py` — MEAS-10 dynamic layer
- [ ] `tests/test_datasets_gist.py` — MEAS-12 DF floor, data-flow assertion, D-52 abstraction table
- [ ] `tests/test_datasets_divergence.py` — MEAS-12 D-33/D-34 gates, two-sided
- [ ] `tests/test_datasets_authoring.py` — D-35 isolation, D-57 argv hygiene, provenance, replay determinism
- [ ] `tests/test_datasets_registry.py` — MEAS-11/12/13 pairing, mix, freeze, D-48 records
- [ ] `tests/test_datasets_control_fidelity.py` — D-31/D-55 control-vs-fallback byte identity
- [ ] `tests/test_arena_paired_contrast.py` — D-44
- [ ] Extend `tests/test_arena_boundary.py` — D-47 (eight names, recursive scan)
- [ ] Extend `tests/test_arena_adjudication.py` — D-45 cross-corpus refusal
- [ ] Extend `tests/test_arena_leaderboard.py` — D-53 separate baselines table
- [ ] Framework install: **none** — `unittest` is stdlib and already in use

---

## What genuinely needs the 580 MB artifact

Only two things, and both are one-off operator steps whose output is committed:

1. D-32 gist vocabulary extraction (`CatalogIndex.value_counts`, ~2.5 s once opened).
2. The five D-48 baseline evaluation runs (~104 min nominal, budget 2–3.5 h per D-56).

Everything else — schema validation, conformance, bucket gate, divergence gate,
registry, pairing, `paired_contrast`, replay — is testable against the 12-product
temporary artifact or a hand-written `products` dict. `gist.py` MUST read the
**committed** `gist_vocabulary.json` at use time and build it only under an
explicit CLI flag, so no test ever touches the database.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| LLM authoring itself produces customer-language paraphrases | MEAS-11, MEAS-12 | Requires interactive `claude` OAuth; not runnable in CI (`--bare` excludes OAuth). Output quality is gated automatically once produced. | Operator runs the authoring driver; the D-33 bucket gate, D-34 divergence gate, and D-35 faithfulness review then verify the output programmatically. Nothing is accepted on inspection alone. |
| Faithfulness review verdicts (`faithful`/`drifted`/`wrong`) | MEAS-12 | The verdict is an LLM judgment, not a computable property. | Full coverage, not sampling (D-35). Anything but `faithful` is re-authored, capped at 3 attempts per constraint, then failed loudly. The *rate* is asserted; the individual verdicts are not. |
| Five D-48 baseline runs against the real catalog | MEAS-10, MEAS-13 | Needs the 580 MB artifact and 2–3.5 h wall-clock. | Operator runs `run_arena.py` per corpus with `--exploration disabled --lexical-mode auto` (both flags required for literal `run-a` reproduction, per L-11). The published records are then asserted automatically. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45 s
- [ ] Full suite still catalog-free (no test opens `data/catalog.artifacts/`)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
