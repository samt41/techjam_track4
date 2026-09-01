# Phase 2: Expanded Dataset & Paraphrase Probe - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-31
**Phase:** 2-expanded-dataset-paraphrase-probe
**Areas discussed:** Corpus scale & split, Card authoring & pairing, Model family split, Measurement scope

---

## Gray areas presented

| Option | Description | Selected |
|--------|-------------|----------|
| Corpus scale & split | How many generated sessions, and how they split into a freely-iterable dev batch vs a frozen confirmation batch. Cost anchor: ~0.95 s/session/candidate, so 2,000 sessions ≈ 32 min per candidate run × k candidates × Phases 3-4. Research's power math wants 3,900-15,700 paired sessions for ΔTS=0.01 — unaffordable — so this is a "how much detection power do we buy" call. | delegated |
| Card authoring & pairing | What the authoring LLM may see (deterministic attribute facets vs an LLM abstraction pass), and how the matched pair is built (reuse the evaluator's own `intent_card(product)` as the control vs a separately-authored control). Includes the trap that a solvability check run through our own retrieval would reject exactly the paraphrases that measure the gap. | delegated |
| Model family split | Which family authors the main probe vs the cross-check subset, subset size, and the forward constraint that whoever authors the probe cannot also generate the Phase 4 semantic asset. | **partially answered** |
| Measurement scope | Whether the baseline run and the control-vs-probe delta land in Phase 2 or Phase 3, plus the new pairing axis (one candidate across two corpora joined on target), the dataset registry, and the same-dataset pairing guard (WR-04). | delegated |

**User's choice:** *"Just use Claude sonnet subagents. the rest, please ask yourself and choose the best solution."*

**Notes:** One directive locked (Claude Sonnet subagents for authoring), everything
else delegated — matching the Phase 1 pattern (*"choose the clearest and most
robust and winnable solution for each question you ask yourself"*).

---

## Alternatives considered and rejected

### Corpus scale
| Option | Rejected because |
|---|---|
| ~8,000 dev sessions (MDD ≈ 0.009, aligned with the ≥0.01 practical floor) | ~2.1 h per candidate run × k candidates makes Phases 3-4 unworkable for a solo two-week build. |
| ~1,000 dev sessions (MDD ≈ 0.028) | MDD lands outside research's own 0.02-0.03 decision-worthy band, so the corpus cannot detect the effects the project would act on. |
| **2,000 dev / 800 confirm / 300 probe pairs** | **Selected (D-25, D-26, D-28).** MDD ≈ 0.020 sits exactly on the decision band; 800 mirrors the private set size; 300 pairs detects a ≈0.05 HR@10 vocabulary drop. |

### Control-arm construction
| Option | Rejected because |
|---|---|
| LLM-author a separate "catalog-vocabulary" control card | Adds authoring bias to the arm that exists to be a neutral reference, and costs budget for something the evaluator already produces. |
| Compare the authored probe against the fallback branch directly | The branch itself would then be a confound alongside the wording. |
| **Embed the evaluator's own `intent_card(product)` output as the control** | **Selected (D-31).** Holds the branch constant, reproduces the public path exactly, costs nothing, and yields a free byte-equality verification test. |

### Anti-circularity mechanism
| Option | Rejected because |
|---|---|
| Show catalog text to the LLM with a "paraphrase, don't quote" instruction plus an overlap gate | Contradicts the locked PROJECT.md decision, and relies on prompt discipline where a structural guarantee is available. |
| A first LLM pass abstracts catalog text into attribute pairs, a second isolated call writes the card | Workable, but the abstraction pass itself can carry phrasing through, and it costs an extra model call per card for no added safety. |
| **DF-gated `(attribute_type, canonical_value)` gist from the artifact's `attributes` table** | **Selected (D-32).** Raw text never enters the pipeline that reaches the model, so the guarantee is a data-flow assertion rather than a prompt audit. High-DF values are general vocabulary by definition; DF≈1 feature sentences are excluded automatically. |

### Second model family
| Option | Rejected because |
|---|---|
| Cloudflare Workers AI (GLM/DeepSeek) as the cross-check arm | A genuinely different vendor family and the methodologically strongest option, but requires credential plumbing the user's directive steers away from. Retained as an escalation trigger (D-41). |
| Skip the cross-check and report MEAS-13 as unsatisfiable under a single-vendor constraint | Abandons a stated success criterion when a partial, honestly-bounded answer is available. |
| A deterministic rule-based paraphraser as the contrast arm | Produces stilted language, so an arm-to-arm gap would confound naturalness with generator affinity. |
| **Claude Haiku 4.5, with the intra-vendor limitation disclosed and MDD-bounded** | **Selected (D-39).** Widest gap available without credentials (different generation *and* scale); the limitation is stated first-class rather than discovered in Q&A. |

### Measurement scope
| Option | Rejected because |
|---|---|
| Ship datasets only; defer all measurement to Phase 3 | Roadmap criterion 4 requires a *reported* generator-affinity gap, and Phase 7 depends only on Phase 2 for the probe's delta, n, and CI. Evidence requires a measurement. |
| Route control-vs-probe through the existing `adjudicate` | Wrong statistical object — one candidate across two corpora, not two candidates on one corpus. Holm and the winner's-curse correction are meaningless where nothing was selected from a pool of k. |
| **One baseline run per corpus + a separate `paired_contrast` readout** | **Selected (D-44, D-48).** Correct pairing axis, correct omissions, omissions stated in the report text. |

---

## Claude's Discretion

The user delegated every area except the Sonnet directive. Left explicitly open
for the researcher and planner, per CONTEXT.md § Claude's Discretion:

- Module split inside `arena/datasets/` (package location and registry path are fixed; file split is not)
- The document-frequency floor value and whether it is a fixed count or a percentile
- Authoring batch size, and whether authoring and faithfulness review share a call (they must not share *context*)
- Which stopword list backs the divergence gate — reuse of `constraint_extractor._STOPWORDS` preferred
- Where the per-bucket divergence report is rendered
- Whether `expanded_dev` is generated in one batch or several

## Deferred Ideas

- Escalating to a true third model family (Cloudflare Workers AI) — triggered only if the intra-vendor affinity gap clears its MDD
- A human-authored probe subset as a gold standard
- ~~CR-01 / CR-02 fixes from `01-REVIEW.md`~~ — superseded during this session: commit `f6c91e8` closed CR-01, CR-02, CR-03, WR-03, WR-04 and WR-05. Open review debt now begins at WR-06. See D-45.
- De-duplicating `_SampleMappingAgent` — Phase 8 cleanup (Phase 1 D-07)
- Using `expanded_confirm.v1` before Phase 5 — structurally forbidden by D-27
- A dense/embedding semantic-equivalence check for faithfulness — excluded by the runtime-purity constraint; revisit only under V2-02
