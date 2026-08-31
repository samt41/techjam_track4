# Phase 2: Expanded Dataset & Paraphrase Probe - Context

**Gathered:** 2026-08-31
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers **evaluation corpora and the instrument that validates
them**, plus exactly one baseline measurement over them. No candidate, no
ranking change, no semantic asset.

Three artifacts:

1. **Expanded corpora** — generated sessions where every sample carries an
   authored `intent_card` + `behavior`, so the evaluator's first branch always
   fires and the catalog-scraping fallback never does. Split into a freely
   iterable dev batch and a separately-generated frozen confirmation batch.
2. **Paraphrase probe** — matched control/probe pairs on identical targets,
   authored anti-circularly, with programmatic lexical-divergence gates and a
   second-model cross-check arm.
3. **Dataset registry + the paired control-vs-probe analysis** — the freeze
   mechanism (name → sha256 → generator provenance) and the one new statistical
   readout the Phase 1 arena cannot currently produce.

**One baseline measurement is in scope**: the currently shipped agent
(the `run-a` configuration) evaluated on every new corpus. It is required —
Roadmap Success Criterion 4 asks for a *reported* generator-affinity gap, and
Phase 7 (which depends only on this phase) needs the probe delta with its sample
size and confidence interval. Evidence of vocabulary generalization requires a
measurement, not just a dataset.

**Explicitly not in this phase:** no new candidate of any kind; no candidate-vs-
candidate adjudication; no Innovation narrative prose (Phase 7 writes it from
this phase's numbers); no `_EXPANSIONS` or semantic-asset work (Phase 4); no
CR-01/CR-02 fixes (see D-45).

**Requirements:** MEAS-10, MEAS-11, MEAS-12, MEAS-13 (4 total).

</domain>

<decisions>
## Implementation Decisions

The user delegated every gray area with one instruction locked: **"Just use
Claude sonnet subagents. the rest, please ask yourself and choose the best
solution."** Everything below except D-38 is Claude's call, made against the
Core Value (total rubric score, not HR@10), the hard invariants in `CLAUDE.md`,
and the statistical constraints in `.planning/research/PITFALLS.md`.

**Decision numbering continues from Phase 1 (D-01 … D-24).** Phase 1's decision
IDs are cited by number in `arena/` source comments; restarting at D-01 would
make those references ambiguous.

### Findings that reframe the phase (read these first)

**F-03: The public-set blind spot is confirmed, not assumed.** All 200 samples
in `data/public_set.jsonl` carry keys `{category_bucket, difficulty_bucket,
ground_truth, sample_id, scenario_type, user_profile}` and **zero** carry
`intent_card` or `behavior`. 200/200 take `materialize_hidden_fields`'s
catalog-scraping fallback. The claim `PROJECT.md` builds the Innovation
narrative on is a measured fact about the shipped dataset.

**F-04: `intent_card["target_category"]` is never read by the evaluator.**
`initial_message` takes its category from `coarse_category(categories[target])`
— the catalog's own `categories` field — not from the card
(`evaluator/local_evaluator.py:235`). Only `hard_constraints` and
`soft_preferences` reach the simulated customer. Two consequences: authoring
effort concentrates entirely on those two lists, and the opening category phrase
is catalog vocabulary in **both** arms of every pair, so it cancels in the
paired delta. State it as a scoped limitation — the probe measures paraphrase
robustness of *constraints*, with the coarse category held fixed.

**F-05: `classify_constraint()` makes constraint wording control which question
unlocks it.** `customer_reply` only discloses a constraint when
`classify_constraint(value) == ask_attribute`
(`evaluator/local_evaluator.py:174-185`). A paraphrase that changes the bucket
changes the *disclosure mechanics*, not just the vocabulary — the probe would
then measure two effects at once. This is the single most dangerous confound in
the phase and D-33 exists to close it.

**F-06: `classify_constraint` is keyword-driven, so full lexical divergence is
impossible in two buckets.** `material` requires one of nine literal words
(`cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric`); `color`
requires one of twelve. Under D-33 those keywords are pinned, so achievable
divergence is bucket-dependent and must be reported per bucket, never as one
number. It also returns only 7 of the 10 `Attribute` values — never `category`,
`brand`, or `other` — so authored constraints can occupy at most 7 buckets.

**F-07: extra sample keys are inert.** `evaluate()` reads only `user_profile`,
`ground_truth.parent_asin`, `scenario_type`, `sample_id`, and (via
`materialize_hidden_fields`) `intent_card`/`behavior`. Unknown keys are ignored,
so pairing metadata can travel inside the sample rows without touching the
evaluator.

### Corpus scale and split discipline

- **D-25: Three corpora, sized from the decision band, not from ambition.**
  Calibrating against research's own power figure (n ≈ 7,800 paired sessions to
  detect ΔTS = 0.01 at 80% power) gives a per-session paired-difference SD of
  σ_d ≈ 0.315 TechnicalScore, hence **MDD(n) ≈ 0.882 / √n**.

  | Corpus | Sessions | Targets | MDD (ΔTS) | Run cost @0.95 s/session |
  |---|---:|---:|---:|---:|
  | `public` (existing, unchanged) | 200 | 200 | 0.062 | 3.2 min |
  | `expanded_dev` | 2,000 | 2,000 | **0.020** | 32 min |
  | `expanded_confirm` (frozen) | 800 | 800 | 0.031 | 13 min |
  | `probe` (300 pairs + 100 cross-check) | 700 | 300 | see D-28 | 11 min |

  `expanded_dev` is sized at 2,000 because research's own stated
  decision-worthy band is 0.02-0.03 TechnicalScore — MDD 0.020 means the rig can
  detect exactly the effects the project would act on, and cannot detect 0.01,
  which is then stated rather than hidden. Below ~1,500 the MDD leaves the
  decision band and the corpus stops paying for itself.

- **D-26: `expanded_confirm` is 800 sessions because the private set is 800.**
  The confirmation draw is the same size as the real one, which makes its power
  argument self-evident and gives the writeup an honest sentence rather than an
  arbitrary number. Its MDD (0.031) is deliberately weaker than `expanded_dev`'s
  — it is a directional reproduction check for the Phase 5 champion, not a second
  full adjudication.

- **D-27: Split discipline is enforced by construction, not by intent.**
  `expanded_dev` is used freely across Phases 3-4. `expanded_confirm` is
  generated from a **different seed, a different prompt revision, and a disjoint
  target sample**, and is not read until Phase 5. All target sets are mutually
  disjoint *and* disjoint from the 200 public targets, so no corpus can inherit
  another's difficulty profile and no candidate can be rewarded for fitting the
  public 200's specific targets.

- **D-28: The probe is 300 matched pairs, with a 100-pair cross-check arm.**
  300 pairs detects a control→probe drop of **≈0.05 HR@10 at 80% power**
  (McNemar, assuming ~8% discordant); the hypothesised vocabulary gap is much
  larger than that, and a smaller-than-0.05 result is a finding reported with
  its MDD, not a "no gap" claim. The cross-check arm is 100 pairs, detecting a
  family-affinity gap of **≈0.08 HR@10** — stated explicitly, because
  `PITFALLS.md` Pitfall 4 point 5 warns that a 20-30 session probe cannot
  support any claim at all.

- **D-29: If authoring throughput becomes the bottleneck, trim `expanded_dev`,
  protect the probe.** The dev corpus degrades gracefully (MDD moves along √n);
  the probe carries this phase's headline finding and is Phase 7's only
  evidence. Never trade the probe for corpus size.

- **D-30: Scenario mix matches the official 40/40/15/5 in every corpus,
  including the probe.** Per-scenario probe deltas are reported descriptively
  with their bucket σ and are never Holm-corrected — the same rule as D-15/D-19.
  Targets are additionally stratified across category and price bands so a
  corpus cannot silently skew toward whatever is easiest to author for.

### Card authoring, anti-circularity, and pairing

- **D-31: The control card *is* the evaluator's own `intent_card(product)`
  output, embedded verbatim as an authored `intent_card`.** This is the most
  consequential design call in the phase. Both arms then take the authored
  branch (`"intent_card" in sample and "behavior" in sample` → True), so the
  *branch* is held constant and only *wording* varies. The control reproduces
  exactly the phrasing the public set produces, which makes control-vs-probe
  precisely "public-set phrasing vs customer phrasing" — the claim Phase 7
  wants. It costs nothing to author and carries zero authoring bias.

  A free verification asset falls out: a control-arm session and a
  fallback-branch session on the same target must produce byte-identical
  customer behavior. That is a test proving the control arm faithfully
  reproduces the public path, and it is worth writing.

- **D-32: The authoring LLM never sees catalog text. It sees a DF-gated
  attribute gist.** The gist is a tuple of `(attribute_type, canonical_value)`
  pairs — e.g. `material=leather`, `color=black`, `size=wide`,
  `budget_band=$60-90` — drawn from the artifact's own `attributes` table,
  admitted only when the value's catalog-wide document frequency clears a floor.
  The DF floor *is* the anti-circularity mechanism: a value occurring on one
  product is that product's idiosyncratic phrasing and is excluded by
  construction, while a value occurring on thousands is general vocabulary that
  cannot leak a target's identity. `Attribute.FEATURE` values are raw feature
  sentences with DF ≈ 1 and are therefore naturally excluded — which is the
  desired behaviour, not a gap. `CatalogIndex.value_counts(attribute)` already
  computes exactly this.

  This satisfies the locked `PROJECT.md` decision ("never show catalog text
  in-prompt") *structurally* — there is no prompt-discipline instruction to
  violate, because the raw text never enters the pipeline that reaches the
  model. The check that this held is therefore a data-flow assertion, not a
  prompt audit.

- **D-33: Every probe constraint must preserve its control counterpart's
  `classify_constraint()` bucket.** Run the evaluator's own
  `classify_constraint` (through the seam) on each authored probe string and
  reject/re-author any whose bucket differs from the paired control string's.
  Without this, per F-05, the probe measures vocabulary shift *and* disclosure-
  mechanics shift, and the delta is uninterpretable. This is a hard acceptance
  gate, not a warning.

- **D-34: The lexical-divergence gate is per-constraint, bucket-aware, and
  computed with the project's own normalizer.** Using
  `text_normalization.match_key` / `search_terms` (the same canonicalization the
  agent applies) plus a stopword list, against the evaluator's own
  `searchable_text(product)`:
  - **Probe arm:** excluding the classifier-pinned keyword required by D-33/F-06,
    remaining content tokens must have **zero** overlap with the target's
    `searchable_text` tokens, and **no 2-gram** may appear verbatim.
  - **Control arm:** overlap is high by construction (it is scraped text). It is
    *measured and reported anyway*, so the contrast between arms is quantified
    rather than asserted.
  - Achieved divergence is reported **per `classify_constraint` bucket**, never
    as one aggregate, because F-06 makes material and color floor-bounded.

- **D-35: Solvability is guaranteed by construction; faithfulness is what gets
  checked.** A solvability check run through the project's own retrieval would
  reject exactly the paraphrases that measure the gap — it would launder the
  vocabulary gap out of the corpus before measurement. Instead:
  - Solvability holds structurally: the gist is *derived from* the target's own
    structured attributes (D-32), so every authored constraint is true of the
    target by construction.
  - **Faithfulness** — does the paraphrase still denote its gist pair? — is
    reviewed by a separate LLM call with **no shared context**, shown only the
    gist pair and the authored phrase, never the catalog text. Verdicts:
    `faithful` / `drifted` / `wrong`; anything but `faithful` is re-authored.
    Full coverage, not sampling, at this volume.
  - A programmatic contradiction guard rejects any authored constraint that
    asserts a DF-gated value the target does not have (e.g. "wool" on a leather
    boot).

- **D-36: `behavior` is authored explicitly for both arms, with the override
  turn pinned per *pair*.** The evaluator's fallback seeds
  `behavior_for`'s rng from `f"{sample_id}\0{scenario_type}"`; because control
  and probe necessarily carry different `sample_id`s, an unpinned
  `rng.choice([3, 4])` would give the two arms different override turns — a
  confound sitting inside the intent_override scenario. The override turn is
  therefore derived deterministically from the **pair id**, shared across arms.
  `old_value`/`new_value` come from each arm's own card, since that is the
  vocabulary under test.

- **D-37: Authored-branch conformance is verified programmatically, in two
  layers** (Success Criterion 1 says "verified programmatically, not assumed"):
  - *Static:* a schema validator asserting every row carries `intent_card` with
    non-empty `hard_constraints`/`soft_preferences` and a `behavior` with
    `scenario_type` (plus the four override keys for `intent_override`).
  - *Dynamic:* call `materialize_hidden_fields` (through the seam) on every
    generated sample and assert the returned card **is** the sample's own
    `intent_card`. That proves branch 1 fired for 100% of rows and needs no
    agent run.

### Model families and generator-affinity

- **D-38: Primary authoring is Claude Sonnet subagents (user directive).**
  No new credentials, no provider plumbing, runs inside the existing harness.

- **D-39: The cross-check arm is Claude Haiku 4.5, and the limitation is
  disclosed rather than papered over.** Haiku 4.5 is the widest gap available
  without credentials — a different generation *and* a different scale from
  Sonnet 5 — invoked with an independently-seeded prompt and no shared context.
  **Both arms are Anthropic-family**, so the cross-check bounds *model-scale and
  prompt-lineage* affinity, not *vendor-family* affinity. That is stated as a
  first-class scoped limitation with its own MDD (D-28), not buried. Per
  `PITFALLS.md` Pitfall 7 and the project's posture, an honest bound is
  Technical-Execution currency; an overstated one is a liability under Q&A.

- **D-40: The cross-check is paired on target, three arms deep.** For 100 of the
  300 probe targets there are three sessions: `control`, `probe_sonnet`,
  `probe_haiku`. The control absorbs intrinsic target difficulty, so the
  Sonnet-vs-Haiku delta on matched targets is generator affinity and nothing
  else. Comparing two differently-sampled probe batches would confound affinity
  with target selection.

- **D-41: A recorded escalation trigger, not a task.** If the intra-vendor
  affinity gap is material (i.e. clears its own MDD), that is the signal to
  spend the Cloudflare Workers AI credentials on a genuine third family before
  Phase 7 cites the finding. Recorded here so the trigger exists; not planned
  work in this phase.

- **D-42: Forward constraint on Phase 4 — the Tier-1 semantic asset must NOT be
  generated by Claude Sonnet.** `PITFALLS.md`'s technical-debt table rates
  "author the probe with the same LLM used to build Tier-1 assets" as *Never*:
  the probe would then measure self-consistency between two outputs of one
  model. Sonnet is now spent on the probe, so Phase 4's SEM-01 generator must be
  a different family (Cloudflare Workers AI open models preferred, a different
  Anthropic model at minimum).

### Measurement scope, registry, and the new pairing axis

- **D-43: A dataset registry is the freeze mechanism (MEAS-12).**
  `data/datasets.json` — committed, canonical-JSON, sibling to the corpora it
  describes — carries per corpus: name, path, `sha256`, session count, distinct
  target count, scenario mix, generator model + version, prompt revision hash,
  seed, generator code revision, and the achieved per-bucket lexical-divergence
  statistics. Corpus files are versioned in their filename
  (`data/probe.v1.jsonl`), so regenerating produces a **new file**, never a
  silent overwrite. "Frozen" means a committed checksum plus a recorded commit,
  matching D-04's rule that retained evidence is a committed file and not a
  number in prose.

- **D-44: Control-vs-probe does NOT go through `adjudicate`, and must not.**
  It is a different statistical object: **one candidate across two corpora,
  joined on `pair_id`** — not two candidates on one corpus. `adjudicate`'s Holm
  family and winner's-curse correction are meaningless here, because nothing was
  selected from a pool of k. Build a separate `paired_contrast` readout:
  - mean paired ΔTechnicalScore with a bootstrap CI (reusing the Phase 1
    resampling engine, content-seeded per D-24),
  - the McNemar discordant-pair count and Δ HR@10 for the binary component,
  - the MDD at this n, reported beside the result per MEAS-06,
  - **no Holm, no winner's-curse correction**, with the omission stated in the
    report text so it reads as deliberate.

- **D-45: The WR-04 same-corpus guard already exists — inherit it, do not
  rebuild it.** WR-04 ("nothing checks that two compared arms measured the same
  catalog and dataset") is a warning only while one corpus exists; this phase
  makes five corpora live, which turns a silent cross-corpus join into an
  available and catastrophic error.

  **Commit `f6c91e8` (2026-08-31, "Close immediate phase one review gaps") closed
  it, along with CR-01, CR-02, CR-03, WR-03, WR-05 and the invalid
  override-value path.** `adjudicate` now refuses any candidate whose
  `catalog_sha256` or `dataset_sha256` differs from the baseline's, and refuses
  duplicate candidate fingerprints; `build_leaderboard` rejects duplicate entry
  fingerprints; `SessionOutcome.validate()` checks `scenario_type`, boolean
  `hit`, and integer rank/turn fields; `CandidateSpec.validate()` checks
  override *values*. 384 tests pass. Per the resolution note now at the top of
  `01-REVIEW.md`, unresolved review debt begins at **WR-06**.

  Consequences for planning: this phase inherits the guard and must not
  re-implement it — but it **must** exercise it, since Phase 2 is the first
  point where five distinct `dataset_sha256` values exist and the guard's
  refusal path becomes reachable in practice. Add a test that a cross-corpus
  pairing is refused. Nothing in this phase's record set can trigger CR-01
  regardless: one candidate × five corpora yields five distinct fingerprints.

- **D-46: Pairing metadata rides inside the sample rows.** Each generated sample
  carries `pair_id` and `arm` (`control` | `probe_sonnet` | `probe_haiku`).
  Per F-07 the evaluator ignores unknown keys, so this costs nothing and makes
  the paired join explicit rather than reconstructed from `ground_truth`. The
  join still happens only **after** `evaluate()` returns — ground truth never
  reaches the `Agent` (hard invariant, unchanged).

- **D-47: The seam widens deliberately, and its guard test widens with it.**
  `arena/evaluator_bridge.py` currently re-exports exactly three names and
  `tests/test_arena_boundary.py` asserts that count. This phase adds
  `intent_card`, `behavior_for`, `classify_constraint`,
  `materialize_hidden_fields`, and `searchable_text` — all unmodified organizer
  functions, all called as opaque library functions. The seam and its test must
  change in **one** commit, with the *why* commented at the seam, so the D-08
  invariant stays machine-checked rather than quietly loosened. Confirm the AST
  boundary test recurses into the new `arena/datasets/` subpackage.

- **D-48: One baseline run per corpus, using the existing `run-a` spec.** Five
  records land under `experiments/baselines/`, one per corpus, each with its own
  fingerprint by virtue of `dataset_sha256`. This is the phase's measurement,
  and it is also a smoke test that every generated corpus actually runs through
  the unmodified evaluator end to end.

### Claude's Discretion

Delegated wholesale, so all of the above is discretionary — but these
specifically are left open for the researcher and planner, and nothing above
constrains them:

- Exact module split inside `arena/datasets/`. The fixed points are only: the
  package lives at `arena/datasets/`, the registry manifest is
  `data/datasets.json`, and every evaluator function arrives via
  `arena.evaluator_bridge` (D-47).
- The exact document-frequency floor in D-32, and whether it is a fixed count or
  a percentile of the attribute's value distribution. Pin it as a named module
  constant with the rationale commented, per repo convention.
- Batch size per authoring subagent call, and whether authoring and faithfulness
  review share a call or are strictly separate. They must not share *context*
  (D-35); sharing a call is a throughput question.
- The stopword list backing D-34 — reuse whatever `constraint_extractor._STOPWORDS`
  already holds if it fits, rather than introducing a second list.
- Whether the per-bucket divergence report lives in `data/datasets.json`, a
  generated Markdown view, or both. D-12's precedent (JSON is truth, Markdown is
  a generated view, both committed) is the default unless there is a reason.
- Whether `expanded_dev` is generated as one batch or several — provenance is
  per-corpus, so internal batching is an operational detail.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Objective, priorities, and statistical premises
- `.planning/PROJECT.md` — Core Value, the Key Decisions row locking
  anti-circular probe construction ("never show catalog text in-prompt, gate on
  lexical overlap, freeze before iterating, cross-check with a second model
  family"), the public-set blind-spot analysis, and the LLM-tier placement rules
- `.planning/REQUIREMENTS.md` — MEAS-10, MEAS-11, MEAS-12, MEAS-13
- `.planning/ROADMAP.md` § "Phase 2: Expanded Dataset & Paraphrase Probe" — the
  five success criteria this phase is verified against
- `CLAUDE.md` — hard invariants (evaluator immutability, ground truth never
  reaching the `Agent`, determinism, stdlib-only runtime), naming and code style

### The design sources for this phase — read both in full
- `.planning/research/ARCHITECTURE.md` § "Expanding the Evaluation Set Without
  Touching the Evaluator" and § "Paraphrase Probe Design" — the matched
  control/probe construction, the three-way split discipline, the leakage
  mitigations, and Anti-Patterns 3, 4 and 5. This is the primary source for
  D-25 … D-35.
- `.planning/research/PITFALLS.md` § Pitfall 4 ("The paraphrase probe measures
  the generator, not the system") — self-preference bias, the five avoidance
  rules, and the sample-size warning that D-28 answers. § Pitfall 1 supplies the
  MDD calibration behind D-25. The technical-debt table supplies D-42.

### The evaluator (read-only — never modified; reached only via the seam)
- `evaluator/local_evaluator.py:204-213` — `materialize_hidden_fields`, the
  two-branch function this entire phase is built around
- `evaluator/local_evaluator.py:52-71` — `intent_card()`, which D-31 calls to
  build the control arm
- `evaluator/local_evaluator.py:137-151` — `classify_constraint()`, the source
  of F-05, F-06 and the D-33 gate
- `evaluator/local_evaluator.py:154-185` — `initial_message` / `customer_reply`,
  the disclosure mechanics and the source of F-04
- `evaluator/local_evaluator.py:74-87` — `behavior_for()` and its rng seeding,
  the source of the D-36 confound
- `evaluator/local_evaluator.py:27-37` — `searchable_text()`, the exact field
  concatenation the D-34 overlap gate measures against
- `docs/competition_specification.md` — scoring formula and the 40/40/15/5
  scenario mix D-30 matches
- `docs/submission_rules.md` — disclosure obligations, including for build-time
  LLM usage

### Phase 1 output this phase extends
- `.planning/phases/01-measurement-rig-core/01-CONTEXT.md` — D-01 … D-24, all
  still binding. D-04 (committed evidence), D-08 (sole evaluator seam), D-12
  (JSON truth / Markdown view), D-24 (content-seeded resampling) are load-bearing
  here.
- `.planning/phases/01-measurement-rig-core/01-REVIEW.md` — read the
  **Resolution update** at the top first: CR-01, CR-02, CR-03, WR-03, WR-04 and
  WR-05 are closed by commit `f6c91e8`; open debt begins at WR-06 (see D-45)
- `arena/evaluator_bridge.py` — the seam D-47 widens
- `arena/candidate.py` — `CandidateSpec`, already carrying `dataset_sha256`, so
  corpus provenance is half-built
- `arena/arena.py` — `run_candidate` and the `_SampleMappingAgent` discipline
- `arena/adjudication.py`, `arena/statistics.py` — the resampling engine D-44
  reuses and the adjudicator D-44 deliberately does *not* route through
- `tests/test_arena_boundary.py` — the AST guard that must widen with D-47
- `data/public_set.jsonl` — the sample schema every generated row must match
  (F-03)

### Catalog-side inputs
- `starter/shopping_agent/catalog_artifacts.py:459-464` — the `attributes` table
  backing the D-32 gist
- `starter/shopping_agent/catalog_index.py:28` — `value_counts(attribute)`, the
  document-frequency source that makes D-32's floor computable
- `starter/shopping_agent/text_normalization.py` — `match_key`, `search_terms`,
  `normalize_text`; the canonicalization D-34 must use so the gate speaks the
  agent's own vocabulary
- `starter/shopping_agent/models.py:7-17` — the `Attribute` enum, which matches
  the evaluator's `ALLOWED_ATTRIBUTES` exactly
- `starter/shopping_agent/constraint_extractor.py` — `_STOPWORDS`, candidate
  reuse for D-34
- `.planning/codebase/CONVENTIONS.md` — frozen dataclasses, ordering and
  tie-break rules, comment-the-why
- `tests/fixtures.py`, `tests/arena_fixtures.py` — the catalog-free fixture
  pattern every new test must follow

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`evaluator.intent_card(product)`** — produces the control arm for free
  (D-31). Unmodified organizer code, reached through the seam.
- **`evaluator.classify_constraint(value)`** — doubles as the D-33 bucket gate.
  The evaluator's own classifier is the only correct authority on which question
  unlocks a constraint.
- **`evaluator.materialize_hidden_fields(sample, products)`** — a pure function,
  so D-37's dynamic branch check is a direct call, no agent run needed.
- **`CatalogIndex.value_counts(attribute)` over the `attributes` table** — the
  document-frequency signal that makes D-32's gist gate computable without new
  indexing work.
- **`text_normalization.match_key` / `search_terms`** — the D-34 overlap gate
  measures in the same normalized space the retrieval engine uses, so a "zero
  overlap" claim means zero overlap *to the agent*, not to a naive tokenizer.
- **`CandidateSpec.dataset_sha256` (`arena/candidate.py`)** — already makes one
  candidate on five corpora produce five distinct fingerprints. No change needed
  for provenance; only the registry lookup in `run_arena.py` is new.
- **`arena/store.py` `publish` / `write_json` / `sha256_file`** — atomic
  tempdir-then-rename with the Windows `os.replace` handling already solved.
- **`arena/statistics.py`** — the bootstrap/permutation engine D-44 reuses for
  the paired contrast; only the pairing key and the omitted corrections differ.

### Established Patterns
- **Single evaluator seam, AST-enforced** (D-08) — widening it is a deliberate,
  commented, same-commit change to seam and test together (D-47).
- **Committed reduced records as the unit of evidence** (D-04) — a corpus is
  "frozen" when its checksum is committed, not when someone says it is (D-43).
- **JSON is source of truth, Markdown is a generated view, both committed**
  (D-12) — the default shape for the divergence report.
- **Content-seeded randomness, never clock-seeded** (D-24) — applies to target
  sampling, batch assignment, and the D-36 override-turn derivation.
- **Frozen slotted dataclasses with `validate()` raising `ValueError`** — the
  shape the corpus schema validator and registry entries take.
- **Determinism as an acceptance property** — LLM authoring is not
  byte-reproducible, so the *frozen artifact plus its provenance record* is the
  reproducibility unit, exactly as SEM-03 prescribes for the semantic asset.

### Integration Points
- `arena/datasets/` (new subpackage) → `arena.evaluator_bridge` for every
  evaluator function; must be covered by the AST boundary test.
- `arena/datasets/` → `starter.shopping_agent.catalog_index` /
  `text_normalization` for the D-32 gist and D-34 gate. These are catalog-side
  reads, not agent invocations — no `Agent` is constructed during generation.
- `data/datasets.json` + `data/{expanded_dev,expanded_confirm,probe}.v1.jsonl` —
  new committed files. `.gitignore` already permits them: only
  `data/catalog.jsonl`, `data/*.artifacts/` and `data/releases/` are excluded.
- `arena/run_arena.py --dataset` → resolves registry names as well as paths.
- `arena/adjudication.py` → gains the D-45 same-corpus refusal.
- `arena/` → a new `paired_contrast` readout (D-44), sibling to `adjudicate`,
  not folded into it.
- Phase 3 re-validates every accepted ranking change against `probe.v1`; Phase 5
  consumes `expanded_confirm.v1` for the first time; Phase 7 cites the probe
  delta, its n, and its CI.

</code_context>

<specifics>
## Specific Ideas

- **The control arm must be provably the public path.** D-31 gives a test worth
  writing explicitly: for the same target, a control-arm sample (authored branch)
  and a bare sample (fallback branch) must drive byte-identical customer
  behavior. That test is what converts "our control reproduces the public-set
  phrasing" from a claim into evidence, and it is cheap.

- **Report divergence per bucket, and say why it is floor-bounded.** F-06 means
  a single "achieved lexical overlap" number would be quietly dishonest —
  material and color are pinned by the evaluator's own keyword classifier. The
  per-bucket table, with the pinning explained, is stronger evidence than a
  flattering aggregate and is exactly the kind of acknowledged limitation the
  judging rubric rewards.

- **The Haiku-vs-Sonnet limitation is an asset if stated first.** Both arms are
  Anthropic-family. Saying so up front, with the MDD that bounds what the
  cross-check could have detected, is the same "the rig must be able to say no"
  posture Phase 1 built (`01-CONTEXT.md` specifics). Discovering it in Q&A
  instead would cost credibility on exactly the criterion the probe exists to
  win.

- **Do not launder the gap out of the corpus.** D-35 is the phase's sharpest
  trap: the obvious "check the session is solvable" step, if implemented through
  the project's own retrieval, would delete precisely the sessions that carry the
  signal. Solvability comes from construction; only faithfulness is reviewed, and
  it is reviewed without catalog text in context.

- **`target_category` is dead weight (F-04).** Do not spend authoring effort or
  review budget on it. Populate it for schema fidelity and move on.

</specifics>

<deferred>
## Deferred Ideas

- **Escalating to a true third model family (Cloudflare Workers AI)** — triggered
  only if the intra-vendor affinity gap in D-39/D-41 clears its own MDD.
  Credentials exist on request; not planned work here.
- **A human-authored probe subset as a gold standard** — the strongest possible
  anti-affinity control, but the authoring cost is not justified until the LLM
  cross-check shows a gap worth resolving.
- **Fixing CR-01 and CR-02** (`01-REVIEW.md`) — Phase 3 gate per D-45 and
  `PROJECT.md`; they cannot fire on this phase's one-candidate × five-corpora
  record set.
- **De-duplicating `_SampleMappingAgent` between `arena/` and
  `experiments/run_public.py`** — still a Phase 8 cleanup candidate (Phase 1
  D-07), untouched here.
- **Using `expanded_confirm.v1` for anything before Phase 5** — structurally
  forbidden by D-27; if it is read during Phases 3-4 the split discipline is
  void and the confirmation claim becomes false.
- **A dense/embedding-based semantic-equivalence check for D-35 faithfulness** —
  would be stronger than LLM review, but requires a model in the stack that the
  runtime-purity constraint excludes. Revisit only if V2-02 ever lands.

</deferred>

---

*Phase: 2-Expanded Dataset & Paraphrase Probe*
*Context gathered: 2026-08-31*
