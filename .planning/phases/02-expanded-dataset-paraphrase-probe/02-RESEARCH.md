# Phase 2: Expanded Dataset & Paraphrase Probe - Research

**Researched:** 2026-08-31
**Domain:** Evaluation-corpus generation against a frozen third-party harness; build-time
LLM authoring with frozen-asset provenance; paired non-adjudicative statistics
**Confidence:** HIGH for everything grounded in this repository's source and in commands
run in this session. MEDIUM for LLM throughput/cost projections (extrapolated from three
measured `claude -p` calls). LOW for nothing — where a claim could not be verified it is
tagged `[ASSUMED]` and listed in the Assumptions Log.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

Copied verbatim from `.planning/phases/02-expanded-dataset-paraphrase-probe/02-CONTEXT.md`
`<decisions>`. **D-25 … D-48 are locked. This research does not relitigate them.** Where a
measurement in this document makes a decision harder, cheaper, or differently shaped than
the decision assumed, that is called out inline and in Landmines — the decision itself
stands.

- **D-25: Three corpora, sized from the decision band, not from ambition.** Calibrating
  against research's own power figure (n ≈ 7,800 paired sessions to detect ΔTS = 0.01 at
  80% power) gives a per-session paired-difference SD of σ_d ≈ 0.315 TechnicalScore, hence
  **MDD(n) ≈ 0.882 / √n**.

  | Corpus | Sessions | Targets | MDD (ΔTS) | Run cost @0.95 s/session |
  |---|---:|---:|---:|---:|
  | `public` (existing, unchanged) | 200 | 200 | 0.062 | 3.2 min |
  | `expanded_dev` | 2,000 | 2,000 | **0.020** | 32 min |
  | `expanded_confirm` (frozen) | 800 | 800 | 0.031 | 13 min |
  | `probe` (300 pairs + 100 cross-check) | 700 | 300 | see D-28 | 11 min |

  `expanded_dev` is sized at 2,000 because research's own stated decision-worthy band is
  0.02-0.03 TechnicalScore. Below ~1,500 the MDD leaves the decision band and the corpus
  stops paying for itself.
- **D-26: `expanded_confirm` is 800 sessions because the private set is 800.** Its MDD
  (0.031) is deliberately weaker than `expanded_dev`'s — a directional reproduction check
  for the Phase 5 champion, not a second full adjudication.
- **D-27: Split discipline is enforced by construction, not by intent.** `expanded_dev` is
  used freely across Phases 3-4. `expanded_confirm` is generated from a different seed, a
  different prompt revision, and a disjoint target sample, and is not read until Phase 5.
  All target sets are mutually disjoint *and* disjoint from the 200 public targets.
- **D-28: The probe is 300 matched pairs, with a 100-pair cross-check arm.** 300 pairs
  detects a control→probe drop of ≈0.05 HR@10 at 80% power (McNemar, ~8% discordant); the
  cross-check arm is 100 pairs, detecting a family-affinity gap of ≈0.08 HR@10.
- **D-29: If authoring throughput becomes the bottleneck, trim `expanded_dev`, protect the
  probe.** Never trade the probe for corpus size.
- **D-30: Scenario mix matches the official 40/40/15/5 in every corpus, including the
  probe.** Per-scenario probe deltas are descriptive, never Holm-corrected. Targets
  additionally stratified across category and price bands.
- **D-31: The control card *is* the evaluator's own `intent_card(product)` output, embedded
  verbatim as an authored `intent_card`.** Both arms then take the authored branch, so the
  *branch* is held constant and only *wording* varies. A free verification asset falls out:
  a control-arm session and a fallback-branch session on the same target must produce
  byte-identical customer behavior.
- **D-32: The authoring LLM never sees catalog text. It sees a DF-gated attribute gist.**
  A tuple of `(attribute_type, canonical_value)` pairs drawn from the artifact's own
  `attributes` table, admitted only when the value's catalog-wide document frequency clears
  a floor. The DF floor *is* the anti-circularity mechanism.
  `CatalogIndex.value_counts(attribute)` already computes exactly this.
- **D-33: Every probe constraint must preserve its control counterpart's
  `classify_constraint()` bucket.** A hard acceptance gate, not a warning.
- **D-34: The lexical-divergence gate is per-constraint, bucket-aware, and computed with
  the project's own normalizer.** Probe arm: excluding the classifier-pinned keyword,
  remaining content tokens must have **zero** overlap with the target's `searchable_text`
  tokens, and **no 2-gram** may appear verbatim. Control arm: overlap measured and reported
  anyway. Achieved divergence reported **per bucket**.
- **D-35: Solvability is guaranteed by construction; faithfulness is what gets checked.**
  A solvability check through the project's own retrieval would launder the vocabulary gap
  out of the corpus. Faithfulness is reviewed by a separate LLM call with **no shared
  context**, shown only the gist pair and the authored phrase. Verdicts
  `faithful`/`drifted`/`wrong`; anything but `faithful` is re-authored. Full coverage. A
  programmatic contradiction guard rejects any constraint asserting a DF-gated value the
  target does not have.
- **D-36: `behavior` is authored explicitly for both arms, with the override turn pinned
  per *pair*.** Derived deterministically from the pair id, shared across arms.
  `old_value`/`new_value` come from each arm's own card.
- **D-37: Authored-branch conformance is verified programmatically, in two layers.**
  *Static:* schema validator. *Dynamic:* call `materialize_hidden_fields` (through the
  seam) on every generated sample and assert the returned card **is** the sample's own
  `intent_card`.
- **D-38: Primary authoring is Claude Sonnet subagents (user directive).**
- **D-39: The cross-check arm is Claude Haiku 4.5, and the limitation is disclosed rather
  than papered over.** Both arms are Anthropic-family, so the cross-check bounds
  model-scale and prompt-lineage affinity, not vendor-family affinity.
- **D-40: The cross-check is paired on target, three arms deep.** For 100 of the 300 probe
  targets: `control`, `probe_sonnet`, `probe_haiku`.
- **D-41: A recorded escalation trigger, not a task.**
- **D-42: Forward constraint on Phase 4 — the Tier-1 semantic asset must NOT be generated
  by Claude Sonnet.**
- **D-43: A dataset registry is the freeze mechanism (MEAS-12).** `data/datasets.json` —
  committed, canonical-JSON — carries per corpus: name, path, `sha256`, session count,
  distinct target count, scenario mix, generator model + version, prompt revision hash,
  seed, generator code revision, and achieved per-bucket lexical-divergence statistics.
  Corpus files are versioned in their filename (`data/probe.v1.jsonl`).
- **D-44: Control-vs-probe does NOT go through `adjudicate`, and must not.** Build a
  separate `paired_contrast` readout: mean paired ΔTechnicalScore with a bootstrap CI
  (reusing the Phase 1 resampling engine, content-seeded per D-24); the McNemar
  discordant-pair count and ΔHR@10; the MDD at this n; **no Holm, no winner's-curse
  correction**, with the omission stated in the report text.
- **D-45: The WR-04 same-corpus guard already exists — inherit it, do not rebuild it.**
  Commit `f6c91e8` closed it. This phase must **exercise** it: add a test that a
  cross-corpus pairing is refused.
- **D-46: Pairing metadata rides inside the sample rows** — `pair_id` and `arm`
  (`control` | `probe_sonnet` | `probe_haiku`). The join happens only after `evaluate()`
  returns.
- **D-47: The seam widens deliberately, and its guard test widens with it.** Adds
  `intent_card`, `behavior_for`, `classify_constraint`, `materialize_hidden_fields`,
  `searchable_text`. Seam and test change in **one** commit, with the *why* commented at
  the seam. Confirm the AST boundary test recurses into the new `arena/datasets/`
  subpackage.
- **D-48: One baseline run per corpus, using the existing `run-a` spec.** Five records
  under `experiments/baselines/`.

### Claude's Discretion

- Exact module split inside `arena/datasets/`. Fixed points only: the package lives at
  `arena/datasets/`, the registry manifest is `data/datasets.json`, and every evaluator
  function arrives via `arena.evaluator_bridge` (D-47).
- The exact document-frequency floor in D-32, and whether it is a fixed count or a
  percentile. Pin it as a named module constant with the rationale commented.
- Batch size per authoring subagent call, and whether authoring and faithfulness review
  share a call or are strictly separate. They must not share *context* (D-35); sharing a
  call is a throughput question.
- The stopword list backing D-34 — reuse `constraint_extractor._STOPWORDS` if it fits.
- Whether the per-bucket divergence report lives in `data/datasets.json`, a generated
  Markdown view, or both. D-12's precedent is the default.
- Whether `expanded_dev` is generated as one batch or several.

### Deferred Ideas (OUT OF SCOPE)

- Escalating to a true third model family (Cloudflare Workers AI) — trigger only.
- A human-authored probe subset as a gold standard.
- Fixing CR-01 and CR-02 (`01-REVIEW.md`) — Phase 3 gate per D-45.
- De-duplicating `_SampleMappingAgent` between `arena/` and `experiments/run_public.py` —
  Phase 8.
- Using `expanded_confirm.v1` for anything before Phase 5 — structurally forbidden by D-27.
- A dense/embedding-based semantic-equivalence check for D-35 faithfulness.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEAS-10 | Expanded evaluation sessions generated from the frozen catalog, always taking the evaluator's authored-card branch | § "The Evaluator Surface" (exact branch-1 predicate at `local_evaluator.py:205`), § "Exact Sample-Row Schema" (measured key set, per-scenario `behavior` requirements), § "Validation Architecture" (V-1/V-2 static + dynamic conformance) |
| MEAS-11 | Paraphrase probe built as matched control/probe pairs — same target, two card phrasings | § "Exact Sample-Row Schema" (`pair_id`/`arm` are inert, F-07 verified), § "Statistical Readout" (pair_id re-keying recipe for `_require_paired`), § "Landmines" L-2 (D-31/D-36 conflict on byte-identity) |
| MEAS-12 | Anti-circular authoring: no literal catalog text in prompt; lexical overlap measured as an acceptance gate; probe frozen before iteration | § "Catalog-Side Inputs" (measured DF distributions; **the D-32 FEATURE assumption is only ~92% true**), § "Lexical Divergence — Measured Reality" (control-arm baseline overlap 0.9857 measured), § "Freeze Mechanism" |
| MEAS-13 | Probe cross-checked against a second model family to detect self-preference bias | § "LLM Authoring Pipeline" (measured `claude -p --model haiku` resolves to `claude-haiku-4-5-20251001`; context-isolation mechanics), § "Statistical Readout" (n=100 exact-McNemar power verified at 0.820 for ΔHR=0.08) |
</phase_requirements>

---

## Summary

This phase is entirely internals work against three frozen surfaces: the organizer
evaluator (byte-pinned, immutable), the Phase 1 arena (working, 384 tests green in 22.2 s),
and the 580 MB catalog artifact. Nothing may be installed. Almost all planning risk lives
in three places: **(1)** the exact behaviour of `classify_constraint`, which is
substring-based rather than word-boundary-based and therefore both freer and more
treacherous than CONTEXT.md's F-06 describes; **(2)** the build-time LLM authoring
pipeline, which has no in-repo precedent and whose only credential-free mechanism is
shelling out to the operator's already-authenticated `claude` CLI in `-p` headless mode;
and **(3)** four factual corrections to CONTEXT.md findings, one of which (the runtime
budget) makes the phase roughly 1.8× more expensive in wall-clock than D-25's table states.

Five CONTEXT.md claims were checked against source and measurement. **F-03, F-04, F-05 and
F-07 are confirmed exactly.** **F-06 is wrong in one detail and too pessimistic in
another**, and **D-32's rationale for excluding `Attribute.FEATURE` is ~92% true with an 8%
tail that is precisely the hazard the decision exists to prevent**. Those are stated loudly
below.

The good news is large. `claude -p --output-format json --json-schema` was exercised in
this session and works: it returns the resolved model id (`claude-sonnet-5`,
`claude-haiku-4-5-20251001`), exact token usage and USD cost per call — everything D-43
needs for provenance, with zero repo credentials. A 10-constraint authoring spike passed
the D-33 bucket-preservation gate **10/10 on both Sonnet and Haiku**, which suggests the
phase's hardest-sounding gate is not the binding constraint. The binding constraint is
throughput: ~12,800 authored constraints at ~30-50 s per 10-item call is a multi-hour,
~$100-scale serial job, and parallel process fan-out is the only lever.

**Primary recommendation:** Build `arena/datasets/` as a five-module package
(`schema.py`, `gist.py`, `divergence.py`, `authoring.py`, `registry.py`) plus a
`paired_contrast` sibling of `adjudicate` in `arena/`. Author via a committed prompt pack
driven by a `subprocess` list-argv call to `claude -p` run from a **CLAUDE.md-free working
directory**, writing every raw response to a frozen, committed response log; a deterministic
replay path reads that log so regeneration is a deliberate act and the corpus is
byte-reproducible from committed bytes. Widen the seam to eight names and convert the AST
boundary scan from `glob` to `rglob` in the same commit — it does **not** currently recurse.

---

## Architectural Responsibility Map

Adapted to this repo's layer vocabulary (`.planning/codebase/ARCHITECTURE.md`); there is no
browser/CDN tier.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Target sampling, stratification, seeding | New `arena/datasets/` (offline generation) | — | Content-seeded RNG (D-24); no agent, no evaluator involvement |
| Control-card construction (D-31) | `arena.evaluator_bridge` → `intent_card` | `arena/datasets/` | The evaluator owns the definition of "public-set phrasing"; copying it into arena code would fork it |
| Gist extraction (D-32) | Catalog/storage tier (`CatalogIndex.value_counts`) | `arena/datasets/gist.py` | The `attributes` table is the DF authority; arena only applies the floor |
| Probe-phrase authoring | Build-time external process (`claude -p`) | Frozen response log in-repo | Non-deterministic; must never be a runtime or test dependency |
| Bucket gate (D-33) | `arena.evaluator_bridge` → `classify_constraint` | `arena/datasets/` | The evaluator's own classifier is the only correct authority on disclosure mechanics |
| Divergence gate (D-34) | `starter.shopping_agent.text_normalization` + `evaluator_bridge.searchable_text` | `arena/datasets/divergence.py` | Must measure in the agent's own normalized space, against the evaluator's own field concatenation |
| Faithfulness review (D-35) | Separate build-time external process | — | Must not share context with authoring; separate OS process is the enforcement |
| Corpus freeze / registry (D-43) | `arena/store.py` (`sha256_file`, `write_json`) | `data/datasets.json` | Atomicity and Windows `os.replace` handling already solved |
| Corpus measurement (D-48) | `arena/arena.py` `run_candidate` | `arena/run_arena.py` CLI | Unchanged code path; only `--dataset` resolution is new |
| Paired contrast (D-44) | New `arena/paired_contrast.py` | `arena/statistics.py` primitives | Sibling of `adjudicate`, deliberately not folded into it |

---

## Findings F-03 … F-07: Verification Against Source

Every finding was re-derived from the working tree, not from CONTEXT.md's summary.

### F-03 — CONFIRMED exactly

Measured (`python` over `data/public_set.jsonl`, this session):

```
n= 200
key set (200/200 identical): ('category_bucket','difficulty_bucket','ground_truth',
                              'sample_id','scenario_type','user_profile')
scenario_type: buying 80, browsing 80, intent_override 30, boundary 10
category_bucket: clothing 200      difficulty_bucket: medium 90, easy 80, hard 30
distinct targets: 200 / 200 rows
```

Zero rows carry `intent_card` or `behavior`; 200/200 take the fallback at
`evaluator/local_evaluator.py:208-213`. `[VERIFIED: command run this session]`

**Additional measured fact not in F-03:** `difficulty_bucket` is perfectly collinear with
`scenario_type` — `(buying, easy) 80`, `(browsing, medium) 80`, `(intent_override, hard)
30`, `(boundary, medium) 10`. It carries no independent information. Generated corpora
should reproduce that mapping for schema fidelity (it is inert per F-07 either way) rather
than invent a difficulty model. `[VERIFIED: command run this session]`

### F-04 — CONFIRMED exactly

`evaluator/local_evaluator.py:235`:

```python
user_message = initial_message(effective_sample, coarse_category(categories.get(target, [])), disclosed)
```

`categories` is the catalog's own `categories` field, built at `local_evaluator.py:121`.
`intent_card["target_category"]` is written at `local_evaluator.py:68` and read **nowhere**
in the file. A grep for `target_category` across `evaluator/` returns exactly that one
write site. `[VERIFIED: source read]`

### F-05 — CONFIRMED exactly

`evaluator/local_evaluator.py:178-181`:

```python
matches = [
    value for value in constraints
    if value not in disclosed and (attribute == "other" or classify_constraint(value) == attribute)
][:2]
```

A constraint is disclosed only when the agent's `ask_attribute` equals its
`classify_constraint` bucket. Wording controls disclosure. `[VERIFIED: source read]`

Two mechanics F-05 does not mention that the planner needs:

- **At most two constraints per reply** (`[:2]`), and `disclosed` is a set of exact
  strings (`local_evaluator.py:184`).
- **For `scenario_type == "buying"`, `hard_constraints[0]` is disclosed in the opening
  message regardless of bucket** (`local_evaluator.py:156-159`). For `browsing` and
  `boundary` the opening is generic and no constraint leaks. For `intent_override` the
  opening speaks `behavior["override"]["old_value"]` but does **not** add it to `disclosed`
  (`local_evaluator.py:160-162`) — so it can be re-disclosed later.

### F-06 — **WRONG in one detail, and TOO PESSIMISTIC in its central claim**

> ⚠️ **Read this before planning D-33/D-34.**

**Error 1 — the color keyword count.** F-06 says color "requires one of twelve".
It requires one of **seven**, and one of the seven is the literal word `color`:

```python
# evaluator/local_evaluator.py:143
if any(word in lowered for word in ("color", "black", "white", "blue", "red", "pink", "green")):
    return "color"
```

Twelve is `COLOR_RE` at `local_evaluator.py:24`, which is used by `intent_card`
(`:57`, `:61`) — a *different* function serving a *different* purpose. The two lists are
not the same set: `COLOR_RE` also matches `brown|gray|grey|purple|yellow|orange`, none of
which route to the `color` bucket. A control card entry `"color: brown"` classifies as
`color` **only because the literal substring `color` is present**, not because `brown` is.
`[VERIFIED: source read, local_evaluator.py:24 vs :143]`

Planning consequence: for any target whose control colour is brown/gray/purple/yellow/
orange, the pinned token is `color` itself, not the colour word — which changes what D-34
must exclude from the overlap computation.

**Error 2 — "full lexical divergence is impossible in two buckets" is too strong.**
`classify_constraint` uses `in` (substring containment), **not** word-boundary regex —
unlike `MATERIAL_RE`/`COLOR_RE`, which do use `\b`. Measured behaviour
(`.venv/Scripts/python.exe`, this session):

```
  material   silky smooth to the touch          <- "silk" is a substring of "silky"
  material   a leathery finish                  <- "leather" inside "leathery"
  material   cottony soft                       <- "cotton" inside "cottony"
  material   a woolly warm layer                <- "wool" inside "woolly"
  color      blackout curtains vibe             <- "black" inside "blackout"
  color      the greenery print                 <- "green" inside "greenery"
```

Catalog-wide **token**-level document frequency for those divergence levers, measured over
all 50,000 products via `search_terms(searchable_text(product))`:

| token | products containing | share |
|---|---:|---:|
| `leathery` | 0 | 0.00% |
| `greenery` | 0 | 0.00% |
| `cottony` | 7 | 0.01% |
| `woolly` | 4 | 0.01% |
| `blackout` | 10 | 0.02% |
| `silky` | 346 | 0.69% |
| `color` | 9,366 | 18.73% |
| `black` | 8,222 | 16.44% |
| `sole` | 10,441 | 20.88% |
| `size` | 16,209 | 32.42% |
| `style` | 12,038 | 24.08% |
| `fit` | 12,125 | 24.25% |

So a `material`-bucket probe constraint reading *"I want something with a leathery
finish"* preserves the bucket **and** has zero token overlap with any of the 50,000
products' `searchable_text` — the D-34 zero-overlap target is attainable in `material`,
not floor-bounded. `[VERIFIED: command run this session, 14.8 s full-catalog scan]`

F-06's *conclusion* — report divergence per bucket, never as one number — remains correct
and should be kept. Its *reason* changes: divergence is bounded per **target**, not per
bucket, because the gate measures against that target's own tokens.

**Error 3 (F-06 is right, quantified).** `classify_constraint` returns only 7 of the 10
`Attribute` values. Reachable: `budget`, `material`, `color`, `size`, `style`, `use_case`,
`feature`. Unreachable: `category`, `brand`, `other`. Confirmed by reading
`local_evaluator.py:137-151`. `[VERIFIED: source read]`

### F-07 — CONFIRMED exactly

`evaluate()` (`local_evaluator.py:216-295`) reads from a sample only:
`sample["user_profile"]` (:228), `sample["ground_truth"]["parent_asin"]` (:229),
`sample["scenario_type"]` (:234), `sample["sample_id"]` (:270), and via
`materialize_hidden_fields`, `sample["intent_card"]` / `sample["behavior"]`.
`initial_message` and `customer_reply` read `scenario_type`, `intent_card`, `behavior`.
No other key is touched. `category_bucket` and `difficulty_bucket` are already inert in the
shipped set. `pair_id` and `arm` therefore ride free. `[VERIFIED: source read]`

One extra consumer the planner must not forget: `arena/arena.py:149` reads
`sample["sample_id"]` to build `_SampleMappingAgent`'s ordering tuple. Sample ids must be
unique within a corpus or the session→sample join silently mis-maps.

---

## 1. The Evaluator Surface This Phase Consumes

All line numbers are `evaluator/local_evaluator.py` at the current byte-pinned revision
(SHA-256 `84ea8997…f91b30`, asserted at `tests/test_arena_boundary.py:15,151-163`).

| Function | Lines | Signature | Reads | Returns | Pure? | RNG |
|---|---|---|---|---|---|---|
| `searchable_text` | 27-37 | `(product: dict) -> str` | `SEARCH_FIELDS = ("title","features","details","description","categories","store")` (:22) | Space-joined string; `dict` values flattened as `f"{key} {item}"`, `list` values stringified elementwise, scalars `str()`ed | **Yes** | none |
| `intent_card` | 52-71 | `(product: dict, limit: int = 180) -> dict` | `title`, `features`, `details`, `price`, plus `searchable_text(product)` for `MATERIAL_RE`/`COLOR_RE` | `{"target_category": str, "hard_constraints": list[str], "soft_preferences": list[str]}` | **Yes** | none |
| `behavior_for` | 74-87 | `(scenario: str, card: dict, rng: random.Random) -> dict` | `card["hard_constraints"]`, `card["soft_preferences"]` | `{"scenario_type": s}`; for `intent_override` also `{"override": {"turn","old_value","new_value","message"}}` | Yes given rng | **`rng.choice([3,4])` only on the `intent_override` branch** — the rng is untouched for all other scenarios |
| `classify_constraint` | 137-151 | `(value: str) -> str` | the string only | one of 7 buckets (see F-06 error 3) | **Yes** | none |
| `initial_message` | 154-163 | `(sample, category: str, disclosed: set[str]) -> str` | `sample["scenario_type"]`, `sample["intent_card"]["hard_constraints"]`, `sample["behavior"]["override"]["old_value"]` | opener string | **No** — mutates `disclosed` in place (:158) | none |
| `customer_reply` | 166-185 | `(sample, ask_attribute, disclosed: set[str], boundary_used: bool) -> tuple[str, bool]` | `scenario_type`, `intent_card.hard_constraints`, `intent_card.soft_preferences` | `(reply, boundary_used)` | **No** — mutates `disclosed` (:184) | none |
| `materialize_hidden_fields` | 204-213 | `(sample: dict, products: dict[str,dict]) -> tuple[dict, dict]` | branch 1: `sample["intent_card"]`, `sample["behavior"]`. branch 2: `ground_truth.parent_asin`, `products`, `sample_id`, `scenario_type` | `(card, behavior)` | **Yes** (both branches; branch 2's rng is locally constructed) | branch 2 only: `random.Random(f"{sample_id}\0{scenario_type}")` (:210-211) |
| `evaluate` | 216-295 | `(agent, samples, catalog_ids, categories, products) -> dict` | see F-07 | `{**metric_summary, efficiency, recommended_technical_score, reported_token_usage, scenario_metrics, sessions}` | **No** — drives the agent; uses `uuid.uuid4()` per session (:227) | `uuid4` for session ids only; never affects scoring |

**The branch-1 predicate is exactly** `if "intent_card" in sample and "behavior" in sample`
(`:205`). Membership only — the values are never inspected before being returned. A row
with `"intent_card": null, "behavior": null` takes branch 1 and then crashes downstream.
The D-37 static schema validator is therefore load-bearing, not belt-and-braces.

**`materialize_hidden_fields` is pure and cheap.** D-37's dynamic check is a direct call.
Note it needs a `products` mapping only on branch 2; passing `{}` is safe for branch-1 rows
and makes the D-37 dynamic check runnable **without loading the 61 MB catalog**. That is a
significant test-cost saving — assert `materialize_hidden_fields(row, {}) is
(row["intent_card"], row["behavior"])` by identity.

**Ordering of `classify_constraint`'s clauses matters** (`:138-151`), because the first
match wins:
1. `budget` — `"budget" in lowered` **or** `re.search(r"(?:\$|<=|under)\s*\d", lowered)`
2. `material` — substring of `("cotton","polyester","nylon","leather","wool","spandex","silk","rayon","fabric")`
3. `color` — substring of `("color","black","white","blue","red","pink","green")`
4. `size` — substring of `("size","sizing","width","wide","narrow")`
5. `style` — substring of `("department","style","fit","sleeve","neck")`
6. `use_case` — substring of `("hiking","running","gym","winter","outdoor","work")`
7. `feature` — residual default

Measured trap set (this session): `"good for everyday work"` → `use_case`;
`"no fitting room needed"` → `style` (`fit`); `"worksite tough"` → `use_case`;
`"something narrow-ish"` → `size`; `"my budget is tight"` → `budget`;
`"a fabric that breathes"` → `material`. Any `feature`-bucket probe phrase that happens to
contain `fit`, `work`, `size`, `wide`, `neck`, `style`, or a material substring silently
flips bucket and fails D-33. This is the single most likely re-authoring cause and the
prompt must forbid those substrings explicitly for `feature`-bucket items.

---

## 2. The Exact Sample-Row Schema

### Shipped shape (measured, 200/200 identical)

```json
{
  "category_bucket": "clothing",
  "difficulty_bucket": "easy",
  "ground_truth": {"parent_asin": "B09PYB7B6Z"},
  "sample_id": "public_0001",
  "scenario_type": "buying",
  "user_profile": {
    "average_prior_rating": 5.0,
    "preference_tags": ["fit", "comfort", "durability"],
    "purchase_frequency": "3-4 prior purchases",
    "rating_style": "usually positive",
    "summary": "Prior purchases emphasize fit, comfort, durability; ratings are usually positive."
  }
}
```

`user_profile` key set is identical across all 200 rows; `ground_truth` has exactly one
key. `sample_id` is `public_%04d`. `data/public_set.jsonl` is 88,440 bytes / 200 rows =
442.2 B/row (pretty-free, one JSON object per line). `[VERIFIED: command run this session]`

`user_profile` is consumed by `starter/agent.py:70-85` (`_profile_from_payload`), which
tolerates missing keys — but the generated corpora should carry all five for fidelity, and
`preference_tags` must be a list or it is silently dropped (`agent.py:79-83`).

### What a generated row MUST carry to take branch 1

Minimum: the six shipped keys **plus** `intent_card` and `behavior` (any values, per
`:205`). Practically, per scenario:

| `scenario_type` | `behavior` requirement | Why |
|---|---|---|
| `buying` | `{"scenario_type": "buying"}` | `intent_card["hard_constraints"]` must be non-empty or `initial_message` falls through to the generic "still exploring" opener (`:156-159`) and the buying scenario silently degrades into browsing |
| `browsing` | `{"scenario_type": "browsing"}` | generic opener (`:163`); constraints reach the agent only via `customer_reply` |
| `boundary` | `{"scenario_type": "boundary"}` | generic opener; the first `ask_attribute` gets the deflection reply and consumes `boundary_used` (`:168-169`) |
| `intent_override` | `{"scenario_type": "intent_override", "override": {"turn": int, "old_value": str, "new_value": str, "message": str}}` | **`old_value` is mandatory** — `initial_message` does `sample["behavior"]["override"]["old_value"]` with no `.get` (`:161`) and raises `KeyError` if absent. `turn`, `new_value`, `message` are read defensively at `:258-264` (`.get("turn", 3)`, `.get("new_value","")`, `.get("message", <default>)`) so their absence degrades rather than crashes |

**`override["turn"]` admissible range is 2…10.** The trigger is
`if not override_applied and turn + 1 == int(override.get("turn", 3))` at `:259`, evaluated
inside `for turn in range(1, 11)` after the `turn == MAX_TURNS: break` at `:256-257`. So
`turn` is effectively 1…9 at the trigger, and `override["turn"]` must be in `[2, 10]`. The
evaluator's own fallback uses `rng.choice([3,4])` (`:82`).

**A hit before the override fires is not counted.** `override_applied = sample["scenario_type"] != "intent_override"` (`:234`) — note it reads the **original** sample's
`scenario_type`, not `behavior["scenario_type"]`, so those two must agree or the two
mechanisms disagree. And the hit check is `if override_applied and target in ranked`
(`:252`). This is why the intent_override bucket historically scored HR@10 0.20
(`experiments/RUNS.md:146`).

**Recommended `behavior` values for the control arm, to mirror the evaluator exactly**
(`local_evaluator.py:76-86`): `old_value = soft_preferences[-1]`,
`new_value = hard_constraints[0]`,
`message = f"Actually, ignore my earlier preference. What I need is: {new_value}."`.
`new_value` is added to `disclosed` at `:263`, so it should be a string that literally
appears in the card or the disclosure bookkeeping diverges from the public path.

### Measured shape of `intent_card(product)` over the 200 public targets

Running the real `intent_card` on all 200 targets (this session):

- **200/200 produce exactly 2 hard constraints and 2 soft preferences.** The
  `cleaned[:2]` / `cleaned[2:4]` slicing at `:69-70` combined with features+details
  supplying ≥4 candidates makes 2+2 universal on this catalog.
- `classify_constraint` bucket distribution over the resulting 800 constraints:

  | bucket | count | share |
  |---|---:|---:|
  | `feature` | 404 | 50.5% |
  | `material` | 302 | 37.8% |
  | `color` | 60 | 7.5% |
  | `style` | 19 | 2.4% |
  | `size` | 11 | 1.4% |
  | `use_case` | 4 | 0.5% |
  | `budget` | **0** | 0.0% |

`[VERIFIED: command run this session]`

**`budget` never appears.** `intent_card` appends `f"budget around ${price}"` *last*
(`:62-63`), after the material insert at index 0, the colour insert at index 1, and all
flattened features/details — and only the first four survive the `[:2]`/`[2:4]` slices.
Any plan that assumes a budget-bucket probe arm is planning for a cell that D-31's control
construction cannot produce.

Planning consequence for D-33: the probe's constraint-bucket mix is **not a design choice**
— it is fixed by `intent_card` at ~50% `feature` / ~38% `material` / ~8% `color`. The
`feature` bucket (half the corpus) has **no pinned keyword at all** and is the freest for
divergence; `material` (over a third) is pinned but, per F-06 error 2, still admits
zero-overlap phrasings. The per-bucket divergence table D-34 mandates will have only four
rows with n ≥ 10 and two rows (`style` n≈19, `size` n≈11, `use_case` n≈4 scaled to probe
size) that are descriptive noise. Say so in the report rather than presenting six equal
rows.

---

## 3. The Existing Seam and Its AST Guard

### Current state

`arena/evaluator_bridge.py` is 18 lines. Its entire content is a docstring (lines 1-10, which
literally says "re-exports exactly the three names below"), `from __future__ import
annotations`, one import line, and one `__all__`:

```python
# arena/evaluator_bridge.py:14
from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
# :17
__all__ = ("catalog_index", "evaluate", "load_jsonl")
```

### What `tests/test_arena_boundary.py` actually asserts

Five distinct mechanisms, not one count:

1. **`evaluator_references(path)` (`:22-48`)** — `ast.parse` the file, walk it, and flag
   three node kinds: `ast.Import` whose top-level package is `evaluator`; `ast.ImportFrom`
   whose module's first segment is `evaluator` *or* whose relative import contains
   `evaluator`; and **`ast.Constant` string literals** whose first dotted segment is
   `evaluator` (`:42-47`) — this last arm exists to catch
   `importlib.import_module("evaluator...")` and `__import__`. Returns a sorted tuple of
   `"line N: ..."` strings.
2. **`ScannerTest` (`:51-73`)** — proves the detector itself fires, on files written into a
   `TemporaryDirectory`. Three cases: static import, dynamic import via string constant,
   clean module.
3. **`test_only_the_bridge_module_references_the_evaluator` (`:85-96`)** — runs the scanner
   over `_non_bridge_modules()`.
4. **`test_bridge_surface_is_exactly_three_names` (`:98-132`)** — **parses** the bridge (does
   not import it, so the assertion holds even when the evaluator is unimportable) and
   asserts: exactly one non-`__future__` `ImportFrom` node; its module is
   `"evaluator.local_evaluator"`; `sorted(alias.name for alias in seams[0].names) ==
   list(BRIDGE_EXPORTS)`; **zero `ClassDef`**; **zero `FunctionDef`/`AsyncFunctionDef`** —
   "the seam must stay a pure re-export".
5. **`EvaluatorIntegrityTest` (`:151-163`)** — `hashlib.sha256(path.read_bytes())` against
   the pinned `EVALUATOR_SHA256`. `read_bytes`, never `read_text`, so a line-ending change
   is a modification.

Plus `test_analyze_public_does_not_reach_the_evaluator` (`:143-148`), which extends the scan
to `experiments/analyze_public.py` because `arena/candidate.py:8` imports `code_revision`
from it.

### ⚠️ The guard does **NOT** recurse into subpackages

```python
# tests/test_arena_boundary.py:77-83
def _non_bridge_modules(self) -> list[Path]:
    arena_directory = REPOSITORY_ROOT / "arena"
    return [
        path
        for path in sorted(arena_directory.glob("*.py"))
        if path.name != _BRIDGE_MODULE_NAME
    ]
```

`glob("*.py")` is **non-recursive**. `arena/datasets/*.py` would be invisible to the D-08
boundary scan. D-47's instruction to "confirm the AST boundary test recurses into the new
`arena/datasets/` subpackage" resolves to: **it does not, and the plan must change it.**

Two sub-hazards in the fix:

- `rglob("*.py")` will pick up `arena/__pycache__/` — it contains `.pyc`, not `.py`, so it
  is harmless today, but the plan should exclude `__pycache__` defensively.
- The exemption test is `path.name != _BRIDGE_MODULE_NAME` — a **basename** comparison.
  Under `rglob`, a file at `arena/datasets/evaluator_bridge.py` would be silently exempted
  from the scan while being a second, unguarded seam. The exemption must be re-anchored on
  the path relative to the repository root
  (`path.relative_to(REPOSITORY_ROOT) != Path("arena/evaluator_bridge.py")`).

### Exactly what must change for D-47 (one commit)

| File | Change |
|---|---|
| `arena/evaluator_bridge.py:1-10` | Docstring: "exactly the three names below" → the new count, plus a commented *why* for each added name (D-47 requires the why at the seam) |
| `arena/evaluator_bridge.py:14` | `from evaluator.local_evaluator import behavior_for, catalog_index, classify_constraint, evaluate, intent_card, load_jsonl, materialize_hidden_fields, searchable_text` |
| `arena/evaluator_bridge.py:17` | `__all__` updated to the same eight, sorted |
| `tests/test_arena_boundary.py:17` | `BRIDGE_EXPORTS` updated to the eight names **in sorted order** (the test compares against `sorted(...)`) |
| `tests/test_arena_boundary.py:98` | Rename `test_bridge_surface_is_exactly_three_names` — the name becomes a lie otherwise |
| `tests/test_arena_boundary.py:77-83` | `glob` → `rglob`, `__pycache__` excluded, exemption re-anchored on relative path |
| `tests/test_arena_boundary.py` (new) | A `ScannerTest`-style case proving the recursive scan actually reaches a nested file (write a probe into `arena/datasets/` inside a `TemporaryDirectory`-rooted fixture, mirroring the existing `_scan` discipline at `:52-56`) |

Sorted eight-name tuple, for copy-paste correctness:
`("behavior_for", "catalog_index", "classify_constraint", "evaluate", "intent_card", "load_jsonl", "materialize_hidden_fields", "searchable_text")`

The zero-`FunctionDef`/zero-`ClassDef` assertions mean **no wrapper, no adapter, no
convenience helper may live in the seam.** Any normalization of evaluator output belongs in
`arena/datasets/`.

---

## 4. Reusable Phase 1 Arena Machinery

### `arena/statistics.py` — resampling primitives

| Symbol | Line | Signature | Reusable for D-44? |
|---|---|---|---|
| `RESAMPLE_COUNT` | 22 | `= 10_000` module constant, deliberately not a CLI flag (D-24) | Use as-is |
| `MINIMUM_RESAMPLES` | 36 | `= 40` | — |
| `pair_seed` | 88 | `(baseline_fingerprint: str, candidate_fingerprint: str, label: str) -> int` | **Yes, directly.** Takes plain strings, not `CandidateSpec`. Content-seeded SHA-256 (D-24). Pass the two corpora's run fingerprints and label `"paired_contrast_bootstrap"` |
| `_require_paired` | 107 | `(baseline, candidate) -> None`, raises if `sample_id` tuples differ | **Blocking — see below** |
| `percentile_indices` | 125 | `(resamples: int) -> tuple[int,int]` — Efron–Tibshirani (R+1) convention | Use as-is |
| `_delta` | 161 | `(baseline, candidate) -> float` — `technical_score(metric_summary(c)) - technical_score(metric_summary(b))`, recomputed from scratch on each resample because TechnicalScore is not a session-wise mean (D-17) | Exactly the ΔTechnicalScore D-44 wants |
| `paired_bootstrap` | 173 | `(baseline, candidate, *, seed: int, resamples: int = 10_000) -> BootstrapResult` — one index vector applied to both arms (`:191`) | **Yes**, after the re-keying below |
| `paired_permutation` | 217 | `(baseline, candidate, *, seed, resamples) -> PermutationResult` | Available; D-44 does not require a p-value from it, but it is the natural companion if one is wanted |
| `minimum_detectable_difference` | 315 | `(standard_error: float) -> float` = `2.801585218112968 * SE` | **Yes, directly** — this is D-44's MDD bullet and MEAS-06 |
| `holm_bonferroni` | 287 | — | **Deliberately NOT used** (D-44) |
| `winners_curse_correction` | 373 | — | **Deliberately NOT used** (D-44) |
| `BootstrapResult` | 56 | frozen slotted; `delta`, `lower`, `upper`, `standard_error`, `resamples`, `as_record()` | Reuse the record shape |

**McNemar does not exist anywhere.** A grep for `mcnemar|discordant|binom` across `arena/`
and `tests/` returns only `binomial_standard_error` in `arena/metrics.py:190` and its
callers. `[VERIFIED: grep run this session]`

### ⚠️ `_require_paired` will reject the control/probe arms as-is

```python
# arena/statistics.py:114-117
if len(baseline) != len(candidate) or tuple(
    item.sample_id for item in baseline
) != tuple(item.sample_id for item in candidate):
    raise ValueError("paired comparison requires identical sample_id ordering")
```

Control and probe sessions necessarily carry **different** `sample_id`s (they are different
rows in different corpora). The guard is correct and must not be weakened — MEAS-04 depends
on it. The reuse recipe is to **re-key on `pair_id` before calling**:

```python
# arena/paired_contrast.py -- sketch, not final
control_aligned = tuple(
    dataclasses.replace(outcome, sample_id=pair_id)
    for pair_id, outcome in sorted(control_by_pair.items())
)
probe_aligned = tuple(
    dataclasses.replace(outcome, sample_id=pair_id)
    for pair_id, outcome in sorted(probe_by_pair.items())
)
result = paired_bootstrap(control_aligned, probe_aligned,
                          seed=pair_seed(control_fp, probe_fp, "paired_contrast"))
```

`SessionOutcome` is `@dataclass(frozen=True, slots=True)` (`arena/metrics.py:28-29`) and
`dataclasses.replace` on it is already an established pattern in this repo
(`tests/arena_fixtures.py:89`). Sorting by `pair_id` gives the deterministic ordering
`_require_paired` then verifies as a free consistency check.

The `pair_id → SessionOutcome` map must be built from the **corpus JSONL** (which carries
`pair_id`, D-46) joined to `sessions.jsonl` on `sample_id` — the run record does not carry
`pair_id`. The join happens after `evaluate()` returns, preserving the ground-truth
invariant.

### `arena/candidate.py` — fingerprinting

`CandidateSpec` (`:41-124`) is frozen+slotted with fields `name`, `code_revision`,
`code_revision_dirty`, `overrides: tuple[tuple[str,str],...]`, `catalog_sha256`,
`dataset_sha256`. `fingerprint` (`:86-107`) is SHA-256 over canonical JSON with
`sort_keys=True, separators=(",",":")`. `validate()` (`:56-84`) enforces sorted unique
override keys, membership in `ALLOWED_OVERRIDES` (`:15`), value membership in
`ALLOWED_OVERRIDE_VALUES` (`:16-19`), and that both digests are 64 lowercase hex chars or
the literal `"unknown"` (`:35-38`).

Consequence for D-48: one candidate × five corpora → five distinct `dataset_sha256` → five
distinct fingerprints, no CR-01 duplicate-fingerprint exposure. Confirmed by construction.
`build_candidate_spec` (`arena/arena.py:93-113`) already computes `dataset_sha256` via
`sha256_file(Path(dataset_path))` — **no change needed for corpus provenance.**

### `arena/store.py` — atomicity and Windows

| Symbol | Line | Notes |
|---|---|---|
| `sha256_file(path)` | 45-53 | 1 MiB streaming blocks. Reuse verbatim for `data/datasets.json` corpus digests |
| `write_json(path, payload)` | 56-60 | `json.dumps(payload, indent=2, sort_keys=True) + "\n"`, UTF-8. **Not atomic on its own** — atomicity comes from writing into a temp dir and `publish()`ing |
| `write_sessions` | 63-71 | `json.dumps(row.as_record(), sort_keys=True) + "\n"` per row. **This is the canonical JSONL form the corpora should match** |
| `load_sessions` | 74-106 | `json.loads` only, never pickle/eval/yaml (T-01-07); each row `validate()`d; raises `ArenaStoreError` with path + line number |
| `publish(working, destination)` | 109-147 | `os.replace`, then on `OSError` **only if `destination.is_dir()`** clear and retry. Docstring (:120-122) records the Windows precondition: close the `Agent` and any trace sink first, because `os.replace` on a directory raises `PermissionError` while a handle is open |
| `validate_run_id` / `resolve_run_directory` | 24-42 | Regex allow-list plus an `is_relative_to` containment check (T-01-06) |

For corpus files the same discipline applies: write into a `tempfile.TemporaryDirectory`
under `data/`, then `os.replace` the file into place. A single-file `os.replace` **does**
overwrite on Windows (unlike directory replace), so a corpus regeneration would silently
clobber — which is exactly why D-43 versions the filename. Refuse if the destination exists.

### `arena/run_arena.py` — where registry-name resolution slots in

```python
# arena/run_arena.py:47-51
def _existing_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path

# :104-105 (inside _run)
catalog_path = _existing_file(args.catalog, "catalog")
dataset_path = _existing_file(args.dataset, "dataset")
```

`--dataset` defaults to `data/public_set.jsonl` (`:195`) and is resolved as a bare
filesystem path with no registry concept. The clean insertion point is a new
`_resolve_dataset(value)` that first tries `data/datasets.json` by name and falls back to
`_existing_file`. Registry resolution should also **verify the recorded sha256 against the
file on disk at resolution time** and refuse on mismatch — that turns D-43's freeze from a
recorded number into an enforced one, at negligible cost (`sha256_file` on a 2 MB file is
milliseconds).

Note `_OVERRIDE_FLAGS` (`:28`) and the long comment at `:56-96` about argparse defaults:
`--exploration` and `--lexical-mode` default to `None` and are **omitted** from the
overrides mapping when unset. `experiments/baselines/run-a/summary.json` stores
`{"exploration": "disabled", "lexical_mode": "auto"}` because the pre-fix CLI injected
them. **D-48 says "using the existing `run-a` spec" — to actually reproduce run-a's
override mapping, the five new invocations must type both flags explicitly.** A flag-free
invocation records `{}` and mints a different fingerprint while configuring a
byte-identical Agent. This is documented at `run_arena.py:88-96` and is a live footgun.

### D-45: where the same-corpus refusal already lives

```python
# arena/adjudication.py:204-219
for candidate in candidates:
    fingerprint = candidate.spec.fingerprint
    if fingerprint == baseline_fingerprint:
        raise ValueError("a candidate must not share the baseline's fingerprint")
    for digest_field in ("catalog_sha256", "dataset_sha256"):
        if getattr(candidate.spec, digest_field) != getattr(baseline.spec, digest_field):
            raise ValueError(
                f"{candidate.spec.name} was measured against a different {digest_field}"
            )
    candidate_fingerprints.append(fingerprint)
if len(set(candidate_fingerprints)) != len(candidate_fingerprints):
    raise ValueError("candidate fingerprints must be unique")
```

Plus `build_leaderboard`'s duplicate-entry-fingerprint refusal at
`arena/leaderboard.py:296-308`, and `_spec_from_payload`'s stored-vs-derived fingerprint
check at `arena/leaderboard.py:241-246`. **Do not rebuild any of these.** The D-45 task is
one test asserting that `adjudicate` refuses two arms whose `dataset_sha256` differ — now
constructible for real, since Phase 2 mints five distinct corpus digests.

⚠️ **`paired_contrast` needs the *inverse* guard, and it is new code.** Control and probe
arms must have **different** `dataset_sha256` (they are different corpora) but the **same**
`catalog_sha256`, the same `code_revision`, and the same `overrides`. `CandidateEntry`
(`arena/leaderboard.py:189-206`) does **not** carry the two digests — only `fingerprint`.
So `paired_contrast` must load specs via `spec_from_record(run_directory)`
(`arena/leaderboard.py:255-268`), not via `entry_from_record`.

### `arena/metrics.py`

`SessionOutcome` (`:28`), `metric_summary` (`:121`), `efficiency` (`:142`),
`technical_score` (`:156`), `hit_rate_curve` (`:168`), `binomial_standard_error` (`:190`),
`scenario_breakout` (`:200`), `NOT_DECISION_GRADE_BELOW = 40` (`:25`). All reusable
unchanged. `metric_summary` raises on an empty tuple (`:126-127`) — a paired-contrast bucket
with zero sessions must be filtered before the call, not passed through.

The transcription note at `metrics.py:8-13` is important for D-47: this chain is
**deliberately not imported from the evaluator**, because cross-agreement between two
independent code paths is the MEAS-16 validation evidence. **Widening the seam must not
tempt anyone to replace `arena/metrics.py` with evaluator imports.** Add that sentence to
the seam docstring.

---

## 5. Catalog-Side Inputs for the D-32 Gist

### `CatalogIndex.value_counts(attribute)` — exact shape and cost

```python
# starter/shopping_agent/catalog_index.py:28-41
def value_counts(self, attribute: Attribute) -> dict[str, int]:
    result = self.backend.facets(FacetRequest(
        filters=(), attributes=(attribute,), work_limit=1_000_000_000,
    ))
    return {bucket.value: bucket.count for bucket in result.buckets}
```

Returns `dict[str, int]`, value → product count. `FacetBucket` is
`(attribute, value, count)` (`search_backend.py:174-184`). Ordering is whatever the SQL
returns — **not sorted**; `values_for` sorts, `value_counts` does not. Any iteration over it
that affects output must impose an explicit sort (repo determinism convention).

`FacetRequest.validate()` (`search_backend.py:163-171`) requires non-empty unique
attributes and `work_limit >= 1`. The backend computes `required_work = total_matches *
(len(attributes) + 1)` (`local_search_backend.py:362`) = 50,000 × 2 = 100,000, far under
1e9, so the work-limit escape at `:363-371` never fires here.

**Yes, the artifact must be built.** `CatalogIndex` wraps a `ProductSearchBackend`;
`LocalProductSearchBackend.open(catalog_path, artifact_path)`
(`local_search_backend.py:61-72`) requires `data/catalog.artifacts/catalog.sqlite3`
(581,844,992 bytes on disk, present). Measured this session:

- backend open: **0.166 s**
- `value_counts` per attribute: **0.00 s – 1.54 s** (`feature` is the slow one)
- all ten attributes: **~2.5 s total**

`[VERIFIED: command run this session]`

So the gist extraction is cheap **once the artifact exists**. Building it from scratch is
~60-90 s / ~580 MB (CLAUDE.md, `LOCAL_ENVIRONMENT.md`). The artifact is `.gitignore`d
(`data/*.artifacts/`), so the D-32 gist step is an **operator-machine dependency**, not a
CI-runnable one. Design accordingly: the gist should be **extracted once into a committed
intermediate** (e.g. `arena/datasets/assets/gist_vocabulary.json`) so that downstream tests
and re-authoring do not need the 580 MB database.

### Measured DF distributions per attribute (full 50,000-product artifact)

| Attribute | distinct values | ≥2 | ≥5 | ≥10 | ≥25 | ≥50 | ≥100 | ≥500 | top values |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `category` | 863 | 708 | 602 | 504 | 378 | 271 | 198 | 61 | clothing/shoes/jewelry 49,990; women 29,435; clothing 20,523 |
| `material` | 434 | 118 | 72 | 65 | 57 | 47 | 36 | 15 | polyester 9,279; cotton 7,812; leather 4,818; spandex 4,617 |
| `color` | 1,127 | 117 | 32 | 24 | 13 | 7 | **2** | 0 | black 440; silver 160; white 91; blue 73 |
| `size` | 330 | 73 | 27 | 11 | 5 | 4 | 1 | 0 | one size 141; medium 90; large 88 |
| `style` | 844 | 136 | 43 | 19 | 8 | 3 | 1 | 0 | modern 149; classic 91; casual 57 |
| `brand` | 19,747 | 6,093 | 1,575 | 600 | 189 | 86 | 24 | 1 | nike 565; adidas 438; skechers 375 |
| `budget` | 2,528 | 831 | 273 | 135 | 54 | 31 | 22 | 0 | 19.99 → 429; 9.99 → 308 (raw price strings) |
| `feature` | 136,232 | 11,522 | 2,030 | 904 | 371 | 179 | 90 | 18 | imported 13,832; machine wash 8,899; pull on closure 7,126; rubber sole 5,616 |
| `use_case` | **0** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — |
| `other` | **0** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — |

`[VERIFIED: command run this session against data/catalog.artifacts/catalog.sqlite3]`

### ⚠️ Two corrections to D-32's stated rationale

**(a) `use_case` and `other` have ZERO rows in the `attributes` table.** The gist can draw
from eight attributes, never ten. Meanwhile `classify_constraint` *can* return `use_case`
(the `hiking|running|gym|winter|outdoor|work` clause) — so the gist can never supply a
`use_case` pair even though the bucket exists downstream. Not a problem (the control cards
only produce 4 `use_case` constraints in 800), but the plan must not assume a ten-way gist.

**(b) D-32's claim that `Attribute.FEATURE` values "are raw feature sentences with DF ≈ 1
and are therefore naturally excluded" is ~92% true and the 8% tail is the exact hazard.**
136,232 distinct feature values; 11,522 (8.5%) have DF ≥ 2; 904 have DF ≥ 10; 90 have
DF ≥ 100. And the surviving high-DF values are **verbatim catalog boilerplate**:
`imported`, `machine wash`, `pull on closure`, `rubber sole`, `hand wash only`,
`100% cotton`, `100% leather`, `zipper closure`. A DF floor set anywhere at or below ~100
therefore admits into the authoring prompt literal spans of the target's own catalog text —
which is precisely what `PROJECT.md`'s locked decision ("never show catalog text
in-prompt") forbids, and precisely what the `feature` bucket (50.5% of all control
constraints, measured) will be full of.

The DF floor alone is **not** a sufficient anti-circularity mechanism for the `feature`
attribute. Options the planner must choose between (all consistent with D-32's spirit):

1. **Exclude `Attribute.FEATURE` from the gist entirely** and give the LLM only the
   *paired control constraint's classify bucket* plus a coarse semantic tag for feature
   items — i.e. treat feature items as "author a plausible customer requirement in the
   `feature` bucket" with no value string at all. Loses faithfulness anchoring.
2. **Admit feature values only in a DF *band*** — high enough to be general vocabulary,
   but the prompt shows a **normalized abstraction** rather than the string (e.g.
   `rubber sole` → `sole_material=rubber`, `machine wash` → `care=machine_washable`). This
   needs a small hand-maintained mapping over the ~90 DF≥100 feature values, which is a
   bounded, one-off, reviewable table.
3. **Admit the string but treat its own tokens as pinned** in D-34, exactly as the material
   keyword is — so the divergence gate measures the probe against the target's tokens
   *minus* the gist tokens the LLM was legitimately handed. Cheapest; weakest.

Option 2 is recommended: it is the only one that keeps the D-32 claim ("raw text never
enters the pipeline that reaches the model") literally true while preserving faithfulness
anchoring, and the 90-entry table is small enough to hand-review. Whichever is chosen, the
**data-flow assertion D-32 promises** must be written as a test: assert that no string
present in the prompt payload appears as a substring of the target's `searchable_text`.

### `Attribute` enum vs the evaluator's `ALLOWED_ATTRIBUTES` vs `classify_constraint`

| Value | `Attribute` (`models.py:7-17`) | `ALLOWED_ATTRIBUTES` (`local_evaluator.py:17-20`) | `classify_constraint` can return | `attributes` table has rows |
|---|:--:|:--:|:--:|:--:|
| `category` | ✓ | ✓ | ✗ | ✓ (863) |
| `material` | ✓ | ✓ | ✓ | ✓ (434) |
| `color` | ✓ | ✓ | ✓ | ✓ (1,127) |
| `size` | ✓ | ✓ | ✓ | ✓ (330) |
| `style` | ✓ | ✓ | ✓ | ✓ (844) |
| `brand` | ✓ | ✓ | ✗ | ✓ (19,747) |
| `budget` | ✓ | ✓ | ✓ | ✓ (2,528) |
| `feature` | ✓ | ✓ | ✓ | ✓ (136,232) |
| `use_case` | ✓ | ✓ | ✓ | **✗ (0)** |
| `other` | ✓ | ✓ | ✗ | **✗ (0)** |

The two ten-member sets match exactly, as CONTEXT.md states. The two *reachable* subsets do
not. `[VERIFIED: source read + command run this session]`

`ALLOWED_ATTRIBUTES` matters at `local_evaluator.py:172-173`: an `ask_attribute` outside the
set is coerced to `"other"`, and `"other"` matches **every** undisclosed constraint
(`:180`). An agent that returns garbage in `ask_attribute` therefore gets a free
two-constraint disclosure. Not this phase's problem, but worth knowing when reading probe
traces.

### `text_normalization` — the D-34 canonicalization

```python
# starter/shopping_agent/text_normalization.py
TOKEN_RE = re.compile(r"[a-z0-9]+")                                    # :8
def normalize_text(value): NFKC → casefold → collapse whitespace       # :12-14
def match_key(value): PUNCT_SPACING_RE.sub(r"\1", value)               # :17-30
def search_terms(value): tuple(dict.fromkeys(TOKEN_RE.findall(normalize_text(value))))  # :46-47
```

`search_terms` is the right primitive for D-34: it returns an **order-preserving deduped
tuple** of lowercase alphanumeric tokens, which is exactly the agent's own retrieval
vocabulary. Note it deduplicates — so token *counts* are unavailable, only set membership.
That is fine for a zero-overlap gate.

⚠️ `match_key` is **not** a tokenizer. It only collapses whitespace around `: , /`
(`PUNCT_SPACING_RE` at `:9`) and does **not** lowercase or NFKC-normalize. D-34's phrasing
("using `match_key` / `search_terms`") should resolve, in the plan, to: **`search_terms` for
the token sets, `match_key` only if literal substring comparison of attribute values is
needed.** Using `match_key` where `search_terms` is meant would produce case-sensitive
comparisons.

For the "no verbatim 2-gram" half of D-34, `search_terms`' dedup destroys adjacency, so the
2-gram check needs `TOKEN_RE.findall(normalize_text(x))` directly (undeduped) and
`zip(toks, toks[1:])`. Small but easy to get wrong.

### `constraint_extractor._STOPWORDS` — suitable for reuse as-is

`starter/shopping_agent/constraint_extractor.py:79-94`. 127 entries, standard
Snowball/NLTK English stop words. The comment at `:75-78` states the design intent
explicitly: *"a generic list suppresses them without any evaluator- or catalog-specific
tuning. It contains no garment vocabulary (a catalog-derived stop list would wrongly drop
'buckle'/'dress')."*

**Verdict: reuse as-is, no second list.** Two caveats for the plan:

- It is a module-private name (`_STOPWORDS`). Importing a private across packages is a
  convention breach in this repo. Either promote it to `STOPWORDS` in the same commit (a
  one-line rename with a comment, all call sites are in the same module — grep confirms
  usage only at `:109`), or re-export it. Promoting is cleaner and keeps one list.
- It contains `"other"`, `"no"`, `"not"`, `"own"`, `"can"`, `"will"`, `"just"`, `"don"`,
  `"s"`, `"t"`. Removing `"no"`/`"not"` from probe-phrase content tokens is correct for a
  *lexical* overlap gate but means a probe phrase like *"no laces or buttons"* (measured
  Sonnet output) has content tokens `{laces, buttons}` — the negation is invisible to the
  gate. The **faithfulness** review (D-35) is where negation drift must be caught, not the
  divergence gate. Say so in the prompt.

---

## 6. The LLM Authoring Pipeline — the Phase's Biggest Unknown

### Ground truth about credentials in this repo

`CLAUDE.md` (§ Configuration) states, and a repo-wide grep confirms, that **no environment
variable is read anywhere** in `starter/`, `evaluator/`, or `experiments/`. There is no
`.env`, no API key, no provider plumbing. That is a hard property of the *shipped agent* and
must stay true.

But this is **build-time** authoring, and the constraint is different. Two facts measured
this session:

1. **`claude` (Claude Code CLI) is on PATH**: `/c/nvm4w/nodejs/claude`, version
   `2.1.247`. `[VERIFIED: command run this session]`
2. **`claude -p` headless mode works, authenticated by the operator's existing session, with
   no repo credential.** Verified end to end.

### Option analysis

| Option | Feasible? | Verdict |
|---|---|---|
| **(a) The Claude Code harness itself authors** — a plan task where the executor agent writes the JSONL directly | Feasible for the 300-pair probe (~1,200 constraints) spread across several tasks. **Infeasible for `expanded_dev` + `expanded_confirm` (~11,200 constraints).** | Rejected as the primary mechanism: no per-item provenance record, no seed, no prompt-revision hash, non-replayable, and the volume exceeds any reasonable task context. Would fail D-43 outright |
| **(b) Committed prompt pack + driver script shelling `claude -p`, with the raw response log committed as a frozen asset, and a deterministic replay path** | **Yes — verified working** | **Recommended.** Satisfies D-43 provenance exactly, makes regeneration deliberate, and matches the SEM-03 pattern CONTEXT.md's `<code_context>` already names as the precedent |
| **(c) Direct HTTPS to the Anthropic API from a Python script** | Requires an API key in the repo environment. There is none, and adding one contradicts the project's own posture | Rejected |
| **(d) Cloudflare Workers AI** | Credentials exist on request, but D-38 locks Sonnet as primary and D-41 makes Workers AI a *trigger*, not planned work | Out of scope this phase |

### Verified mechanics of option (b)

```bash
echo "$PROMPT" | claude -p \
  --model sonnet \
  --output-format json \
  --json-schema "$SCHEMA_INLINE_JSON"
```

**Measured, this session — three real calls:**

| Call | Model | Items | Wall | Cost USD | in tok | out tok | cache create | cache read |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| smoke ("PONG") | haiku | — | 3.3 s | 0.0774 | 9 | 148 | 38,327 | 0 |
| 10-constraint authoring, schema | haiku | 10 | 24.3 s | 0.0236 | 19 | 2,354 | 2,046 | 77,566 |
| 10-constraint authoring, schema | sonnet | 10 | 49.3 s | 0.2665 | 2 | 4,894 | 54,395 | 0 |
| smoke, clean cwd + `--setting-sources ""` | haiku | — | 1.8 s | 0.0166 | 9 | 46 | 6,686 | 20,336 |

`modelUsage` in the JSON response carries the **resolved model id**:
`claude-haiku-4-5-20251001` and `claude-sonnet-5`. `[VERIFIED: commands run this session]`

**Provenance for D-43 falls straight out of the response envelope.** Per call the JSON
carries `session_id`, `total_cost_usd`, `duration_ms`, `usage.{input_tokens,
output_tokens, cache_creation_input_tokens, cache_read_input_tokens}`, `modelUsage.<id>`,
`num_turns`, `subtype`, `is_error`, `permission_denials`. Record `modelUsage`'s key (the
resolved id) — **never the alias** `sonnet`/`haiku`, which is a floating pointer.

⚠️ **Sonnet resolves to `claude-sonnet-5` with no date suffix**, while Haiku resolves to
`claude-haiku-4-5-20251001`. The Sonnet pin is therefore weaker. The registry should record
both the alias used, the resolved id, and the `claude --version` (`2.1.247`) so a reader can
reconstruct what actually ran. `[VERIFIED: commands run this session]`

### ⚠️ Context contamination: `claude -p` loads `./CLAUDE.md` by default

The 38,327 cache-creation tokens on a nine-token prompt is the Claude Code system prompt
**plus this project's 24.8 KB `CLAUDE.md`**. That file describes the paraphrase probe, the
Innovation narrative, and the anti-circularity goal. Feeding it to the authoring model is
(i) expensive and (ii) a self-preference hazard of exactly the kind Pitfall 4 warns about —
the author would know what the probe is for.

Measured mitigation: running from a scratch directory with no `CLAUDE.md`, with
`--setting-sources ""`, cut the prefix from 38,327 creation tokens to 6,686 creation +
20,336 read, and the cost of the identical trivial prompt from $0.0774 to $0.0166.
`[VERIFIED: command run this session]`

**Requirement for the plan:** the authoring driver must set the subprocess `cwd` to a
temporary directory containing no `CLAUDE.md`, and pass `--setting-sources ""`. `--bare` is
a stronger isolation (it explicitly skips CLAUDE.md auto-discovery) but its help text states
*"Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth and
keychain are never read)"* — so `--bare` will **not** work with the operator's OAuth login.
Do not plan on `--bare`. `[CITED: claude --help, this session]`

### Measured failure modes

1. **`--json-schema` takes inline JSON, not a file path.** Passing a path produced
   `Error: --json-schema is not valid JSON: JSON Parse error: Unexpected identifier "C"`
   (the Windows drive letter). Must be `--json-schema "$(cat schema.json)"`.
2. **`--max-turns 1` + `--json-schema` fails with `subtype: "error_max_turns"`** and
   `result: null`, after burning 8,422 output tokens and $0.046. Structured output needs
   ≥2 turns. Do not set `--max-turns 1`.
3. **A positional prompt argument alongside `--allowedTools ""` errored** with
   *"Input must be provided either through stdin or as a prompt argument when using
   --print"*. Feed the prompt on **stdin**.
4. **`result` is a JSON *string*** even under `--json-schema`, so the driver must
   `json.loads(response["result"])` after `json.loads(stdout)`. Two levels.
5. **`is_error: true` with exit code 0** is possible (case 2 above). The driver must branch
   on `payload["is_error"]` and `payload["subtype"] == "success"`, never on returncode alone.
6. **Thinking tokens dominate output cost.** Haiku's smoke call was 139 thinking of 148
   output tokens; the 10-item call was 8,256 thinking tokens in the failed variant. Any
   throughput plan that ignores thinking-token cost will be off by an order of magnitude.
7. **Prompt caching is cross-process within the ephemeral window.** Call 2 read 77,566
   cached tokens created by call 1 in a different process. Batching calls close together in
   time is a real ~10× input-cost saving; a slow, spread-out job pays full price repeatedly.

All `[VERIFIED: commands run this session]`.

### Throughput and cost projection

Authored constraint volume, assuming 4 constraints per card (measured universal for the
control arm, § 2) and controls being free per D-31:

| Corpus | Sessions needing authored phrasing | Constraints |
|---|---:|---:|
| `expanded_dev` | 2,000 | 8,000 |
| `expanded_confirm` | 800 | 3,200 |
| `probe` — `probe_sonnet` arm | 300 | 1,200 |
| `probe` — `probe_haiku` arm | 100 | 400 |
| `probe` — `control` arm | 300 | **0** (D-31) |
| **Total** | | **12,800** |
| D-35 faithfulness reviews (full coverage, separate call) | | **12,800** |

At the measured Sonnet rate (10 items / 49.3 s / 4,894 output tokens):

- **Serial wall-clock:** 1,280 authoring calls × ~49 s ≈ **17.5 hours**, plus a similar
  order for review. Not viable serially.
- **Cost:** output ≈ 6.3 M tokens. At the measured $0.2665/10-items with a cold cache the
  naive figure is ~$340; with warm caching the input term collapses and the realistic figure
  is **$100-160 for authoring**, plus a cheaper review pass (Haiku, short outputs).
  `[ASSUMED — extrapolated from three calls; see Assumptions Log A1]`
- **Mitigations, in order of leverage:**
  1. **Parallel process fan-out.** N concurrent `claude -p` subprocesses. At N=8 the
     authoring pass is ~2.2 h. This is the single biggest lever.
  2. **Larger batches per call.** 10 → 40 items amortises the ~27 k-token prefix 4×.
     Latency per call rises roughly with output tokens, so total time improves less than
     cost does.
  3. **Haiku for `expanded_dev`/`expanded_confirm`, Sonnet reserved for the probe.**
     D-38 locks *"primary authoring is Claude Sonnet"*; the probe is what the phase's
     headline finding rests on. **This is a decision for the planner to surface, not for
     research to make** — it is arguably within D-38's letter (Sonnet remains the primary
     author, of the artifact that matters) and arguably not. Flag it explicitly.
  4. **D-29 is the escape hatch**: trim `expanded_dev`, protect the probe. Halving
     `expanded_dev` to 1,000 moves its MDD from 0.020 to 0.028 — still inside the stated
     0.02-0.03 decision band — and removes 4,000 constraints (31% of the total).

### Enforcing "no shared context" between authoring and review (D-35)

Machine-checkable enforcement, in descending strength:

1. **Separate OS process, fresh session.** Each review is its own `claude -p` invocation
   with a fresh `--session-id` (a UUID derived content-seeded from the item id, so it is
   reproducible). **Never** `-c/--continue`, **never** `-r/--resume`. Assertable: a test
   that greps the driver's argv builder and fails if `--continue`, `--resume`, `-c`, or
   `-r` appear.
2. **Payload minimality.** The review request payload is a frozen dataclass whose field set
   is exactly `{gist_attribute, gist_value, phrase}`. Assertable: a test that
   `set(review_payload_dict) == {"gist_attribute","gist_value","phrase"}` and that
   `searchable_text(target)` shares no ≥4-token span with the serialized payload.
3. **Different system prompt.** `--system-prompt` (or `--append-system-prompt`) for the
   reviewer, distinct from the author's, committed as a separate file in the prompt pack
   with its own revision hash.
4. **Different model is permitted but not required** — D-35 says no shared context, not a
   different family. Using Haiku for review is cheaper and adds an independence margin;
   D-39 already spends Haiku on the cross-check arm, so this does not conflict.

**Sharing a call between authoring and review is forbidden** by D-35's "no shared context",
regardless of throughput. The discretion note in CONTEXT.md ("sharing a call is a throughput
question") is best read as: batching *many review items* into one call is fine; batching an
*author step and its own review* into one call is not.

### The determinism question (CLAUDE.md invariant)

CLAUDE.md's hard invariant is *"Output must be byte-reproducible across runs"* — scoped to
the **agent**, and this phase touches no agent code. But the corpora feed everything
downstream, so "reproducible" must still mean something. The honest formulation, matching
CONTEXT.md's `<code_context>` note and SEM-03:

> **LLM authoring is not byte-reproducible. The reproducibility unit is the frozen artifact
> plus its provenance record.** Everything *around* the LLM call is byte-reproducible:
> target sampling (content-seeded, D-24), gist extraction (a pure function of the artifact),
> the bucket gate, the divergence gate, the schema validator, the pair-id override-turn
> derivation, and the corpus serialization.

Concretely, commit **three** things so a reader can re-derive the corpus without an LLM:
1. the prompt pack (system prompt + template + revision hash),
2. the **raw response log** (one JSONL line per `claude -p` call: request payload digest,
   full response envelope, resolved model id, usage, cost),
3. the corpus JSONL.

Then add a **replay test**: re-running the generator in `--replay <log>` mode must produce
the committed corpus byte-for-byte. That converts an unverifiable claim into a green test,
and is the only form of determinism available here.

---

## 7. Statistical Readout for D-44 `paired_contrast`

### What already exists and how it is reused

| D-44 bullet | Existing primitive | Change needed |
|---|---|---|
| Mean paired ΔTechnicalScore with bootstrap CI | `paired_bootstrap` (`statistics.py:173`) | **Re-key `sample_id` → `pair_id` before the call** (see §4). Otherwise unchanged, including `RESAMPLE_COUNT = 10_000` |
| Content-seeded resampling (D-24) | `pair_seed` (`statistics.py:88`) | None — takes plain strings. Pass `(control_run_fingerprint, probe_run_fingerprint, "paired_contrast_bootstrap")` |
| MDD at this n | `minimum_detectable_difference` (`statistics.py:315`) | None. Feed it `BootstrapResult.standard_error` |
| McNemar discordant count + ΔHR@10 | **Does not exist** | New ~30-line pure function |
| No Holm, no winner's-curse | `holm_bonferroni`, `winners_curse_correction` simply not called | Must be **stated in the report text** so the omission reads as deliberate (D-44) |

### Genuinely new code

1. `arena/paired_contrast.py`:
   - `PairedArm` — frozen slotted `(spec: CandidateSpec, corpus_path: Path, sessions:
     tuple[SessionOutcome, ...], pair_ids: tuple[str, ...])`.
   - `_require_same_candidate_different_corpus(control, probe)` — the **inverse** of D-45's
     guard: same `catalog_sha256`, same `code_revision`, same `overrides`, **different**
     `dataset_sha256`. Raise `ValueError` otherwise.
   - `align_on_pair_id(control, probe) -> tuple[tuple[SessionOutcome,...], tuple[SessionOutcome,...]]`
     — the re-keying, with a refusal on any unmatched `pair_id` on either side.
   - `mcnemar_exact(b: int, c: int) -> float` and `McNemarResult`.
   - `paired_contrast(...) -> PairedContrastResult` with `as_record()`.
2. A Markdown view generator, per D-12 (JSON is truth, Markdown is a generated view).
3. A `--contrast` subcommand on `arena/run_arena.py`, or a separate `python -m
   arena.paired_contrast` entry point. Given `run_arena.py`'s existing two-subcommand shape
   (`run`, `adjudicate`), a third subcommand is the consistent choice.

### McNemar variant: exact binomial, and why

At n = 300 pairs with the assumed ψ ≈ 8% discordance, the discordant count is **b + c ≈ 24**.
The conventional threshold for the normal/chi-square approximation is b + c ≥ 25. **24 sits
below it**, so the continuity-corrected chi-square (Edwards' correction) is the wrong tool
— it is known to be conservative and its calibration at b+c < 25 is exactly where it is
least trustworthy.

**Use the exact two-sided binomial test with p = 0.5**, which is stdlib-computable in a
dozen lines with `math.comb` and requires no approximation, no continuity fudge, and no
`scipy`:

```python
from math import comb

def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: P(|B - n/2| >= |b - n/2|) under B ~ Binom(n, 0.5)."""
    n = b + c
    if n == 0:
        return 1.0                       # no discordant pairs: no evidence either way
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2.0 * tail)
```

Verified outputs at n = 300 pairs (this session):

| b | c | b+c | ΔHR@10 = (b−c)/300 | exact two-sided p |
|---:|---:|---:|---:|---:|
| 20 | 4 | 24 | 0.0533 | 0.00154 |
| 19 | 5 | 24 | 0.0467 | 0.00661 |
| 18 | 6 | 24 | 0.0400 | 0.02266 |
| 17 | 7 | 24 | 0.0333 | 0.06391 |
| 16 | 8 | 24 | 0.0267 | 0.15159 |
| 14 | 10 | 24 | 0.0133 | 0.54126 |

The `min(1.0, 2*tail)` clamp matters: at b = c the doubled tail exceeds 1. The `n == 0`
branch matters too — if the probe produces zero discordant pairs the function must return
1.0, not divide by zero. Both are the kind of degenerate case
`tests/test_arena_statistics.py` already exercises for the bootstrap.

### D-28's power claims — independently verified, and one caveat

Exact power computed by full enumeration over `D ~ Binom(n, ψ)` then `B ~ Binom(D, π)`,
rejecting when `mcnemar_exact(b, D-b) <= 0.05`. `[VERIFIED: command run this session]`

| n pairs | ψ | ΔHR@10 | π | exact power |
|---:|---:|---:|---:|---:|
| 300 | 0.08 | 0.03 | 0.688 | 0.373 |
| 300 | 0.08 | 0.04 | 0.750 | 0.632 |
| 300 | 0.08 | **0.05** | 0.812 | **0.854** |
| 300 | 0.08 | 0.06 | 0.875 | 0.968 |
| 100 | 0.08 | 0.06 | 0.875 | 0.442 |
| 100 | 0.08 | **0.08** | 1.000 | **0.820** |

**D-28's two numbers are correct**, and slightly conservative for the 300-pair arm (the true
80%-power point is ≈0.046, not 0.05).

⚠️ **The ψ = 0.08 assumption is load-bearing and it is a ceiling, not just a parameter.**
With ψ = 0.08, the *maximum representable* ΔHR@10 is 0.08 — every discordant pair going one
way. So D-28's 100-pair cross-check MDD of 0.08 sits exactly at that ceiling: detecting it
at 82% power requires π = 1.000, i.e. **all 8 expected discordant pairs favouring Sonnet**.
That is a real, disclosable limitation of the cross-check arm and should be stated as such
rather than presented as a clean MDD. It is also self-correcting in the good direction: if
the probe genuinely degrades, ψ will be much larger than 0.08 and the detectable range
widens. **Report the observed ψ alongside the observed Δ, and recompute the MDD post hoc
from the observed discordance.**

### ⚠️ D-25's σ_d = 0.315 model contradicts the rig's own MDD definition

`arena/statistics.py:315-337` states explicitly:

> *"The input is the BOOTSTRAP SE of the delta, not sd_d / sqrt(n). TechnicalScore is not a
> mean of per-session values (D-17), so there is no per-session difference whose standard
> deviation could be taken."*

D-25's `MDD(n) ≈ 0.882 / √n` is derived from exactly the σ_d/√n model the rig rejects. That
does not make D-25 wrong as an **a-priori sizing heuristic** — it is a reasonable planning
proxy and the corpus sizes it produces are defensible. But the rig will report
**bootstrap-SE-based** MDDs that may not match the table. The plan must not turn D-25's
table cells into acceptance criteria; treat them as sizing rationale and report the measured
MDDs beside them.

---

## 8. Volume, Runtime and Disk Realities

### ⚠️ D-25's 0.95 s/session is measurably wrong for the arena code path

Committed evidence in `experiments/baselines/*/summary.json` (read this session):

| run | sessions | `elapsed_seconds` | s/session |
|---|---:|---:|---:|
| `run-a` (baseline-auto-disabled, the D-48 spec) | 200 | **337.078** | **1.685** |
| `run-b` (fallback-lexical) | 200 | 462.274 | 2.311 |
| `run-c` (exploration-tail-only) | 200 | 335.231 | 1.676 |

The 0.95 s/session figure traces to CLAUDE.md's *"Full 200-session public evaluation:
~190 s"*, which matches `experiments/RUNS.md:240`'s "185.492 s and 126.485 s" — measurements
from the **older `experiments/run_public.py` path on a differently-loaded machine**, not the
`arena.run_candidate` path D-48 uses.

Worse, `experiments/RUNS.md:150-151` records the variance explicitly:

> *"Wall-clock runtime varies widely with machine load — two identical-output runs measured
> 796 s and 1690 s — so runtime is not a comparison axis."*

**Corrected D-48 budget**, using `run-a`'s own 1.685 s/session:

| Corpus | Sessions | D-25 estimate | Corrected estimate |
|---|---:|---:|---:|
| `public` | 200 | 3.2 min | **5.6 min** |
| `expanded_dev` | 2,000 | 32 min | **56 min** |
| `expanded_confirm` | 800 | 13 min | **22 min** |
| `probe` | 700 | 11 min | **20 min** |
| **Total** | **3,700** | **59 min** | **≈104 min** |

≈1.8× D-25's figure, and — given the documented 2× load-dependent variance — a plan should
budget **2-3.5 hours** for the five D-48 baseline runs, not one. Add ~45 ms backend open per
run (negligible) and ~60-90 s if the artifact must be rebuilt. `[VERIFIED: committed
records + RUNS.md]`

This does not invalidate the D-25 corpus **sizes** — only its run-cost column. Sizing was
driven by MDD, not by cost.

### Disk and repo weight

Measured/derived this session:

- `data/public_set.jsonl`: 88,440 B / 200 rows = **442 B/row** (no `intent_card`/`behavior`).
- A representative generated row, canonical JSON (`sort_keys=True,
  separators=(",",":")`), realistic constraint lengths:
  - `buying`, 2+2 constraints, with `pair_id`/`arm`: **814 B**
  - `intent_override` with the full four-key `override` block: **1,074 B**
- At a blended **950 B/row**:

| File | Rows | Size |
|---|---:|---:|
| `data/expanded_dev.v1.jsonl` | 2,000 | 1.81 MiB |
| `data/expanded_confirm.v1.jsonl` | 800 | 0.72 MiB |
| `data/probe.v1.jsonl` | 700 | 0.63 MiB |
| **Total committed corpora** | **3,500** | **≈3.2 MiB** |
| `data/datasets.json` | — | a few KB |
| Frozen LLM response log | ~1,300-3,000 calls | **~10-40 MiB** ⚠️ |

**3.2 MiB of corpora is unambiguously acceptable repo weight** — an order of magnitude below
any threshold that matters, and the repo already excludes the two large artifacts.

⚠️ **The frozen response log is the weight risk, not the corpora.** At ~5-15 KB per response
envelope × 1,300+ calls, the raw log is 10-40 MiB. Recommendations: store only the *parsed*
`result` payload plus the usage/provenance fields (drop the ~3 KB of Claude Code envelope
boilerplate per call), gzip is not an option for a diff-reviewable committed asset, and one
log file **per corpus** keeps any single file reviewable. Budget for and decide this in the
plan rather than discovering it at commit time.

### `.gitignore` coverage — verified

`.gitignore` excludes under `data/`: `data/catalog.jsonl`, `data/*.artifacts/`,
`data/releases/`. Nothing matches `data/expanded_dev.v1.jsonl`, `data/probe.v1.jsonl`, or
`data/datasets.json`. **They will be committed as intended.** `[VERIFIED: .gitignore read]`

⚠️ One adjacent trap: `experiments/*/` is excluded and only `!experiments/baselines/` is
re-included, with `experiments/baselines/.*/` re-excluded for staging dirs. **Any new
generated artifact placed under `experiments/` outside `baselines/` will be silently
ignored by git.** If the divergence report or the response log is written under
`experiments/`, it will not be committed and D-04/D-43's "frozen means committed" claim
becomes false without any error. Put non-baseline outputs under `data/` or
`arena/datasets/assets/`.

### Test-suite runtime growth

Current: **384 tests in 22.184 s** (`.venv/Scripts/python.exe -m unittest`, measured this
session — confirming D-45's "384 tests pass"). The suite is catalog-free: `tests/fixtures.py`
builds a 12-product temporary artifact, `tests/arena_fixtures.py` reads the committed
`anchor-legacy` record.

Phase 2 adds ~6 new test modules. Keeping the sub-30-second loop requires:

- **Never** load `data/catalog.jsonl` or open the 580 MB artifact in a test. Use
  `tests/fixtures.py`'s tiny builder, or a hand-written `products` dict.
- **Never** call `claude` from a test. The authoring driver must be tested against a
  recorded response fixture and an injected runner callable.
- For corpus-wide validation over 3,500 rows, `materialize_hidden_fields(row, {})` is a
  dict-membership check plus two lookups — 3,500 of those is single-digit milliseconds.
  Loading the JSONL is ~3 MiB of `json.loads`, well under a second.
- The `paired_contrast` bootstrap at `RESAMPLE_COUNT = 10_000` over 300 pairs is the one
  genuinely slow thing. `arena/statistics.py:19-21` already provides the pattern: tests pass
  a reduced `resamples=` keyword (the suite uses 200/500/2000), production paths take the
  default.

---

## Standard Stack

There is no stack decision to make. `pyproject.toml` declares `dependencies = []` and
`uv.lock` contains exactly one entry (the virtual root). Adding any dependency violates a
hard invariant in `CLAUDE.md`.

### Core (all already present)

| Module | Source | Purpose in this phase |
|---|---|---|
| `json`, `pathlib`, `dataclasses`, `enum` | stdlib | corpus schema, registry, frozen validated records |
| `hashlib` | stdlib | corpus sha256, prompt-revision hash, content-seeded RNG |
| `random.Random` | stdlib | content-seeded target sampling and pair-id override-turn derivation |
| `re`, `unicodedata` | stdlib (via `text_normalization`) | D-34 tokenization |
| `subprocess` | stdlib | `claude -p` invocation — **list argv, never `shell=True`** |
| `math.comb` | stdlib | exact McNemar |
| `unittest` | stdlib | all tests |
| `arena.statistics` | in-repo | bootstrap, MDD, content seeding |
| `arena.store` | in-repo | atomic publish, sha256, canonical JSON |
| `starter.shopping_agent.catalog_index` | in-repo | D-32 DF gist |
| `starter.shopping_agent.text_normalization` | in-repo | D-34 canonicalization |

### Alternatives considered

| Instead of | Could use | Why rejected |
|---|---|---|
| `math.comb` exact McNemar | `scipy.stats.mcnemar` | New dependency — forbidden |
| `subprocess` → `claude -p` | `anthropic` Python SDK | New dependency **and** a repo credential |
| `subprocess` → `claude -p` | direct `urllib.request` to the API | No credential exists; would introduce one |
| Reusing `_STOPWORDS` | NLTK / a new list | New dependency, or a second list the discretion note explicitly discourages |
| `concurrent.futures.ThreadPoolExecutor` over subprocesses | `asyncio.create_subprocess_exec` | Threads + `subprocess.run` is simpler and I/O-bound here; either works, this is discretionary |

**Installation:** none.

## Package Legitimacy Audit

**No packages are installed by this phase.** `pyproject.toml` declares
`dependencies = []`, `uv.lock` resolves exactly one entry (the virtual root project), and
CLAUDE.md makes zero-runtime-dependency a hard invariant. `slopcheck` was therefore not run —
there is nothing to check. `[VERIFIED: pyproject.toml, uv.lock read this session]`

The one external executable this phase depends on is `claude` (Claude Code CLI, version
`2.1.247`), already installed on the operator's PATH at `/c/nvm4w/nodejs/claude`, invoked
as a build-time tool and never at agent runtime. It is not a package dependency and is not
declared anywhere in the project. `[VERIFIED: command run this session]`

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System architecture — generation and measurement flow

```
                        data/catalog.artifacts/catalog.sqlite3   (580 MB, gitignored)
                                        |
                        CatalogIndex.value_counts(attribute)      [one-off, ~2.5 s]
                                        |
                                        v
                     +-- DF floor + FEATURE abstraction (D-32) ---+
                     |                                            |
                     v                                            v
       arena/datasets/assets/gist_vocabulary.json      arena/datasets/assets/
              (COMMITTED intermediate --                feature_abstractions.json
               downstream needs no 580 MB db)                (COMMITTED, ~90 rows)
                     |
   content-seeded    v
   target sample --> gist per target --> prompt pack (COMMITTED, revision-hashed)
        |                                       |
        |                                       v
        |                       subprocess: claude -p --model sonnet
        |                       cwd = CLAUDE.md-free temp dir
        |                       --setting-sources "" --output-format json --json-schema
        |                                       |
        |                                       v
        |                       raw response log (COMMITTED, frozen)  <-- replay source
        |                                       |
        |                                       v
        |                       +---------------+----------------+
        |                       |                                |
        |                       v                                v
        |           D-33 bucket gate                  D-35 faithfulness review
        |           classify_constraint                (SEPARATE claude -p process,
        |           (via evaluator_bridge)              fresh session, minimal payload)
        |                       |                                |
        |                       +---------------+----------------+
        |                                       |
        |                       D-34 divergence gate  <-- searchable_text (bridge)
        |                                            <-- search_terms (text_normalization)
        |                                       |
        |                              reject -> re-author loop
        |                                       |
        v                                       v
   evaluator.intent_card(product)  ------> corpus row assembly
   (CONTROL arm, verbatim, D-31)            + behavior (D-36 pair-pinned turn)
                                            + pair_id / arm (D-46)
                                                     |
                              D-37 static schema + dynamic materialize_hidden_fields
                                                     |
                                                     v
                              atomic write --> data/{name}.v1.jsonl (COMMITTED)
                                                     |
                                            sha256_file --> data/datasets.json (COMMITTED)
                                                     |
                                                     v
                   python -m arena.run_arena run --dataset <registry-name>
                   (5 invocations, D-48, ~104 min corrected)
                                                     |
                                    experiments/baselines/{corpus}-run-a/
                                    summary.json + sessions.jsonl
                                                     |
                             join on pair_id (AFTER evaluate() returns)
                                                     |
                                                     v
                              arena/paired_contrast.py  --> JSON truth + Markdown view
                              (bootstrap CI + exact McNemar + MDD; no Holm, no WC)
```

### Recommended project structure

```
arena/
├── evaluator_bridge.py            # widened to 8 names (D-47)
├── paired_contrast.py             # NEW: D-44 sibling of adjudicate
└── datasets/                      # NEW subpackage
    ├── __init__.py
    ├── schema.py                  # frozen SampleRow/IntentCard/Behavior + validate()
    ├── gist.py                    # D-32: DF floor, feature abstraction, gist extraction
    ├── divergence.py              # D-33 bucket gate + D-34 overlap/2-gram gate
    ├── authoring.py               # claude -p driver + replay; injected runner for tests
    ├── generate.py                # target sampling, pair-id derivation, row assembly, CLI
    ├── registry.py                # data/datasets.json read/write/verify
    └── assets/
        ├── gist_vocabulary.json           # committed DF-gated vocabulary
        ├── feature_abstractions.json      # committed ~90-row abstraction table
        ├── prompts/author_probe.md        # committed, revision-hashed
        ├── prompts/author_expanded.md
        └── prompts/review_faithfulness.md
data/
├── datasets.json                  # NEW: the registry (D-43)
├── expanded_dev.v1.jsonl          # NEW
├── expanded_confirm.v1.jsonl      # NEW
├── probe.v1.jsonl                 # NEW
└── responses/                     # NEW: frozen raw response logs, one per corpus
tests/
├── test_datasets_schema.py
├── test_datasets_gist.py
├── test_datasets_divergence.py
├── test_datasets_authoring.py
├── test_datasets_registry.py
├── test_arena_paired_contrast.py
└── dataset_fixtures.py            # tiny synthetic corpora, no catalog
```

### Pattern 1: The seam is a pure re-export — adapters live downstream

**What:** `arena/evaluator_bridge.py` may contain only imports and `__all__`. Zero
`FunctionDef`, zero `ClassDef` (asserted at `tests/test_arena_boundary.py:119-132`).

**When to use:** every time an evaluator function is needed.

**Example:**
```python
# arena/datasets/divergence.py
from arena.evaluator_bridge import classify_constraint, searchable_text
from starter.shopping_agent.text_normalization import normalize_text, search_terms

def content_tokens(phrase: str, stopwords: frozenset[str]) -> tuple[str, ...]:
    return tuple(t for t in search_terms(phrase) if t not in stopwords)

def preserves_bucket(control_phrase: str, probe_phrase: str) -> bool:
    # D-33. The evaluator's own classifier is the only correct authority on which
    # question unlocks a constraint (F-05); a reimplementation here would fork it.
    return classify_constraint(control_phrase) == classify_constraint(probe_phrase)
```

### Pattern 2: Re-key on `pair_id` before touching the paired engine

**What:** `arena.statistics` joins on `SessionOutcome.sample_id`. A cross-corpus pair joins
on `pair_id`. Bridge with `dataclasses.replace`, never by weakening `_require_paired`.

**When to use:** everywhere in `paired_contrast`.

**Example:**
```python
# Source pattern: tests/arena_fixtures.py:89 uses dataclasses.replace on SessionOutcome
import dataclasses

def align_on_pair_id(
    control: dict[str, SessionOutcome],
    probe: dict[str, SessionOutcome],
) -> tuple[tuple[SessionOutcome, ...], tuple[SessionOutcome, ...]]:
    missing = sorted(set(control) ^ set(probe))
    if missing:
        # Refuse rather than silently inner-joining: a dropped pair is a silently
        # smaller n, and MEAS-06 requires n to be honest.
        raise ValueError(f"unmatched pair ids between arms: {missing[:5]}")
    keys = sorted(control)  # explicit sort; never dict insertion order
    return (
        tuple(dataclasses.replace(control[k], sample_id=k) for k in keys),
        tuple(dataclasses.replace(probe[k], sample_id=k) for k in keys),
    )
```

### Pattern 3: The external process is injected, never called directly

**What:** `authoring.py` takes a `runner: Callable[[AuthoringRequest], AuthoringResponse]`.
Production supplies the `claude -p` subprocess runner; tests supply a replay runner backed
by the committed response log; the replay mode is itself a production path.

**Why:** the repo's existing discipline — *"Tracing is injected, never global:
`Agent(..., trace=JsonlEvaluationTrace(path))`"* (CLAUDE.md § Logging). It is also the only
way the suite stays offline and sub-30-second.

### Anti-Patterns to Avoid

- **Adding a helper function to `evaluator_bridge.py`.** The AST test fails on any
  `FunctionDef`. Adapters go in `arena/datasets/`.
- **Re-implementing `classify_constraint` in arena code.** F-05 makes it the authority on
  disclosure mechanics; a fork would drift and the D-33 gate would validate against the
  wrong rule.
- **Weakening `_require_paired` to allow differing sample_ids.** It is MEAS-04's structural
  guarantee (`statistics.py:110-113` comment). Re-key instead.
- **Running a solvability check through the project's own retrieval (D-35).** It would
  delete exactly the sessions carrying the signal.
- **Passing `shell=True` to `subprocess`** while interpolating LLM-adjacent strings.
- **Writing generated artifacts under `experiments/` outside `baselines/`.** Silently
  gitignored.
- **Reporting one aggregate divergence number.** F-06's conclusion holds even though its
  reasoning needed correcting.
- **Trusting `--model sonnet` as a provenance record.** Record the resolved id from
  `modelUsage`.

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Control-arm card phrasing | A "catalog-like" phrasing generator | `evaluator_bridge.intent_card(product)` (D-31) | Only the evaluator's own output *is* public-set phrasing; anything else is an approximation with unmeasured bias |
| Deciding which question unlocks a constraint | A keyword table | `evaluator_bridge.classify_constraint` | It is the actual disclosure rule (`local_evaluator.py:178-181`); substring semantics and clause order are non-obvious |
| The field set the overlap gate measures against | Hand-picking title+features+description | `evaluator_bridge.searchable_text` | Exactly six fields with specific dict/list flattening (`:27-37`); a hand-rolled version would silently differ |
| Tokenization for the divergence gate | `str.split()` / a new regex | `text_normalization.search_terms` | Zero overlap must mean zero overlap *to the agent*, in the same NFKC-casefold-token space |
| Stopwords | A new list | `constraint_extractor._STOPWORDS` (promote to public) | Explicit design note at `:75-78`; a second list would drift |
| Document frequency per attribute value | A catalog scan | `CatalogIndex.value_counts` | ~2.5 s for all ten attributes against the built index; a JSONL scan is 15 s and reimplements the extraction rules |
| Bootstrap CI on paired differences | A new resampler | `arena.statistics.paired_bootstrap` | One index vector applied to both arms (`:191`); the naive two-vector version inflates SE ~7× on this data and every aggregate assertion still passes |
| Content-seeded RNG | `hash()` or `random.seed(int)` | `arena.statistics.pair_seed` | `hash()` is PYTHONHASHSEED-salted and cannot identify anything across processes (`candidate.py:88-94`) |
| Atomic file publish on Windows | `Path.rename` | `arena.store.publish` / `os.replace` | WinError 183 and the open-handle `PermissionError` are already handled and documented (`store.py:109-147`) |
| Canonical JSON | `json.dumps(obj)` | `arena.store.write_json` / the `sort_keys=True, separators=(",",":")` form | Byte-comparability is an acceptance property; unsorted keys break it |
| Cross-corpus safety | A new check | `arena.adjudication`'s digest guard (`:208-216`) for same-corpus; a **new inverse** guard for paired_contrast | D-45: inherit, exercise, do not rebuild |
| McNemar | `scipy` | 12 lines of `math.comb` | No dependency may be added; the exact test is simpler than the approximation anyway |

**Key insight:** in this phase almost every "utility" you would reach for already exists and
is *the definition of correctness* rather than a convenience. The evaluator's functions are
not helpers — they are the specification. Copying rather than calling them is the dominant
failure mode.

---

## Common Pitfalls

### Pitfall 1: The AST boundary guard passes vacuously on the new subpackage

**What goes wrong:** `arena/datasets/*.py` imports the evaluator directly; every test stays
green; D-08/MEAS-15 is silently void.
**Why:** `glob("*.py")` at `tests/test_arena_boundary.py:80` is non-recursive.
**How to avoid:** convert to `rglob`, exclude `__pycache__`, re-anchor the bridge exemption
on the relative path, and add a scanner case that proves the recursive walk reaches a nested
file — mirroring the existing `ScannerTest` discipline at `:51-73`.
**Warning signs:** the boundary test's runtime does not change after adding six modules.

### Pitfall 2: The probe measures disclosure mechanics, not vocabulary

**What goes wrong:** a paraphrase flips its `classify_constraint` bucket; the constraint is
now unlocked by a different question; the paired delta mixes two effects.
**Why:** F-05 plus substring matching — `"no fitting room needed"` → `style` because of
`fit`; `"good for everyday work"` → `use_case`.
**How to avoid:** D-33 as a hard gate, run through the seam. Additionally, forbid the
trigger substrings in the prompt for `feature`-bucket items and re-author on failure. The
measured Sonnet/Haiku spike preserved 10/10, so the gate is cheap in practice.
**Warning signs:** the `feature`-bucket re-authoring rate is materially above the others.

### Pitfall 3: The DF floor lets verbatim catalog text into the prompt anyway

**What goes wrong:** `feature=rubber sole` (DF 5,616) clears any sane DF floor and is a
literal span of the target's `searchable_text`. MEAS-12's core claim becomes false.
**Why:** D-32's premise that FEATURE values have DF≈1 is 92% true; the 8% that survive are
exactly the boilerplate spans.
**How to avoid:** abstract high-DF feature values through a committed mapping table, and
write the data-flow assertion D-32 promises: no prompt payload string may appear as a
substring of `searchable_text(target)`.
**Warning signs:** the control-arm and probe-arm overlap distributions look similar in the
`feature` bucket.

### Pitfall 4: The solvability check launders the gap out (D-35)

**What goes wrong:** a "check the agent can find the target" filter deletes precisely the
sessions where the vocabulary gap bites; the probe then measures ~0 and the headline finding
evaporates — while every gate reports green.
**Why:** it is the obvious, responsible-looking step, and ARCHITECTURE.md:258 even
recommends it ("Validate solvability") for the *expanded* corpora.
**How to avoid:** D-35's split — solvability from construction, faithfulness by review. Note
the tension: ARCHITECTURE.md's step 4 is *correct for `expanded_dev`/`expanded_confirm`* (a
session no agent can win wastes budget and corrupts absolute scores) and *forbidden for the
probe*. The plan must apply it asymmetrically, and say why.
**Warning signs:** any code path in the probe pipeline that constructs an `Agent` or calls
`backend.search`.

### Pitfall 5: The override-turn confound (D-36) is only half the problem

**What goes wrong:** `behavior_for` seeds from `f"{sample_id}\0{scenario_type}"`
(`local_evaluator.py:210`), so different `sample_id`s give different `rng.choice([3,4])`.
**How to avoid:** D-36 — author `behavior` explicitly with the turn derived from `pair_id`.
Since the card is authored, `behavior_for` is never called for generated rows and the rng
never runs. Trivial once seen.
**The other half:** `old_value` and `new_value` also differ between arms by design (D-36:
"the vocabulary under test"). `old_value` is the *entire* opening user utterance for
intent_override (`:161-162`), so for 15% of the probe the opening turn's wording differs
between arms — which is the intended measurement, but it means the intent_override bucket
carries a *larger* per-session vocabulary delta than the others. Report the intent_override
delta separately and descriptively (D-30 already forbids Holm here).
**Warning signs:** an intent_override probe delta far larger than the other three buckets,
read as a system finding rather than as a dose-response artifact.

### Pitfall 6: Regenerating a corpus silently clobbers the frozen one

**What goes wrong:** `os.replace` on a *file* overwrites on Windows; the committed sha256 in
`data/datasets.json` now describes different bytes.
**How to avoid:** D-43's filename versioning plus an explicit refusal when the destination
exists (mirroring `arena/arena.py:128-129`), plus a registry-load-time sha256 verification
that fails loudly.
**Warning signs:** `git status` shows a modified rather than a new corpus file.

### Pitfall 7: `--model sonnet` drifts under you

**What goes wrong:** the alias resolves to a different model between the `expanded_dev` and
`probe` passes; the generator-affinity finding is confounded.
**How to avoid:** record `modelUsage`'s resolved key per call in the response log, assert
at corpus close that a single corpus used exactly one resolved id, and record it in
`data/datasets.json`. Note the asymmetry: Haiku resolves to a dated id, Sonnet does not.
**Warning signs:** a corpus whose response log contains two distinct `modelUsage` keys.

---

## Code Examples

### D-37 dynamic conformance check — no catalog needed

```python
# Source: evaluator/local_evaluator.py:204-213 (branch 1 ignores `products` entirely)
from arena.evaluator_bridge import materialize_hidden_fields

def assert_authored_branch(row: dict) -> None:
    card, behavior = materialize_hidden_fields(row, {})
    # Identity, not equality: branch 1 returns the sample's own objects (`:206`).
    # `is` proves branch 1 fired; `==` would also pass if branch 2 happened to agree.
    if card is not row["intent_card"] or behavior is not row["behavior"]:
        raise ValueError(f"{row['sample_id']} did not take the authored branch")
```

`products={}` is safe because branch 1 returns before touching it. This makes the 3,500-row
conformance sweep runnable in a unit test with no 61 MB catalog and no 580 MB artifact.

### D-34 divergence gate

```python
# Sources: evaluator/local_evaluator.py:27-37 (searchable_text),
#          starter/shopping_agent/text_normalization.py:8,12-14,46-47
import re
from arena.evaluator_bridge import searchable_text
from starter.shopping_agent.text_normalization import TOKEN_RE, normalize_text, search_terms

def _ordered_tokens(value: str) -> list[str]:
    # NOT search_terms: it dedupes (`dict.fromkeys` at text_normalization.py:47),
    # which destroys adjacency and makes the 2-gram half of D-34 unmeasurable.
    return TOKEN_RE.findall(normalize_text(value))

def divergence(probe_phrase: str, product: dict, pinned: frozenset[str],
               stopwords: frozenset[str]) -> dict[str, object]:
    target_tokens = set(search_terms(searchable_text(product)))
    target_bigrams = set(zip(*(lambda t: (t, t[1:]))(_ordered_tokens(searchable_text(product)))))
    probe_seq = _ordered_tokens(probe_phrase)
    content = [t for t in probe_seq if t not in stopwords and t not in pinned]
    overlapping = [t for t in content if t in target_tokens]
    shared_bigrams = [b for b in zip(probe_seq, probe_seq[1:]) if b in target_bigrams]
    return {
        "content_token_count": len(content),
        "overlap_ratio": (len(overlapping) / len(content)) if content else 0.0,
        "overlapping_tokens": sorted(set(overlapping)),
        "shared_bigrams": sorted({" ".join(b) for b in shared_bigrams}),
        "passes": not overlapping and not shared_bigrams,
    }
```

### Measured control-arm baseline for the D-34 report

Running the real `intent_card` over the 200 public targets and measuring content-token
overlap against `searchable_text` with `_STOPWORDS` removed:

```
CONTROL-ARM overlap: mean=0.9857  median=1.0000  min=0.5000  n=798 constraints
   bucket     n      mean      median   min
   color      60     0.8384    1.0000   0.500
   feature   402     0.9977    1.0000   0.929
   material  302     0.9987    1.0000   0.938
   size       11     0.9837    1.0000   0.950
   style      19     0.9888    1.0000   0.941
   use_case    4     1.0000    1.0000   1.000
```

`[VERIFIED: command run this session]` This is the "measured and reported anyway" number
D-34 asks for on the control arm, and it is a strong headline for Phase 7: **the public
set's simulated customer reuses 98.6% of the target's own catalog vocabulary.**

### `claude -p` driver

```python
# Source: `claude --help` and four calls made during this research session
import json, subprocess, tempfile
from pathlib import Path

def invoke(prompt: str, *, model: str, schema: dict, timeout_s: int = 300) -> dict:
    with tempfile.TemporaryDirectory() as clean_cwd:
        # cwd deliberately holds no CLAUDE.md: `claude -p` auto-discovers it, which both
        # costs ~31k prefix tokens per cold call AND tells the authoring model what the
        # probe is for -- the self-preference hazard the probe exists to avoid.
        # `--bare` would be stronger isolation but its own help text says OAuth is never
        # read under --bare, so it cannot work with the operator's login.
        completed = subprocess.run(
            [
                "claude", "-p",
                "--model", model,                      # alias; resolved id comes back in modelUsage
                "--output-format", "json",
                "--json-schema", json.dumps(schema),   # INLINE JSON -- a path is rejected
                "--setting-sources", "",
                # No --max-turns: 1 makes --json-schema fail with error_max_turns.
                # No -c/--continue and no -r/--resume, ever: D-35 no-shared-context.
            ],
            input=prompt, capture_output=True, text=True,
            cwd=clean_cwd, timeout=timeout_s, check=False,  # list argv, never shell=True
        )
    payload = json.loads(completed.stdout)
    if payload.get("is_error") or payload.get("subtype") != "success":
        # exit code can be 0 while is_error is true -- never branch on returncode alone
        raise RuntimeError(f"claude -p failed: {payload.get('subtype')}")
    return {
        "items": json.loads(payload["result"]),        # result is a JSON *string*
        "model_resolved": next(iter(payload["modelUsage"])),
        "usage": payload["usage"],
        "cost_usd": payload["total_cost_usd"],
        "session_id": payload["session_id"],
    }
```

### Exact McNemar

See § 7 for the function, the verified p-value table, and the power verification.

---

## State of the Art

Not a fast-moving-library phase. The relevant "state of the art" is methodological and is
already correctly captured in `.planning/research/ARCHITECTURE.md:288`:

| Old approach | Current approach | Impact here |
|---|---|---|
| Standalone "hard" probe, report probe-alone accuracy | **CheckList invariance test (INV)** — matched pairs, report the paired delta (Ribeiro et al.) | D-31/D-40's matched design; probe-alone HR@10 is context, never the finding |
| Contrast sets (Gardner et al.) — perturb so the label changes | Explicitly *not* this: the target is unchanged | Anti-Pattern 4 |
| Assume LLM-authored tests are neutral | **Self-preference bias is documented** (Xu et al. 2410.21819; Panickssery; Wataoka) | D-39/D-40 cross-check, and D-42's forward constraint on Phase 4 |
| McNemar via continuity-corrected chi-square | Exact binomial when discordant count < 25 | § 7; at b+c≈24 the exact test is both simpler and better calibrated |
| Ad-hoc LLM invocation | Frozen-asset + provenance-record reproducibility | The SEM-03 pattern, applied here |

**Deprecated for this phase:** `experiments/run_public.py` as a measurement path — D-06
keeps it byte-frozen and D-48 routes through `arena.run_candidate`. Its ~190 s/200-session
figure is the source of D-25's incorrect 0.95 s/session.

---

## Runtime State Inventory

Not applicable — this is an additive greenfield phase (new subpackage, new data files, new
statistical readout). No rename, refactor, migration, or string replacement. No stored data,
live service config, OS-registered state, secret, or build artifact carries a name this
phase changes.

Two adjacent state facts the planner should know anyway:
- **Build artifact:** `data/catalog.artifacts/catalog.sqlite3` must exist for the one-off
  D-32 gist extraction. It is gitignored; the extracted vocabulary must be committed so
  nothing downstream depends on it.
- **Committed evidence:** `experiments/baselines/leaderboard.json` and
  `experiments/LEADERBOARD.md` are regenerated by `run_arena adjudicate`. D-48 adds five
  records; whether they enter the leaderboard as `--include` report-only entries (they are
  not candidates) is a planner decision — `run_arena.py:222-228` documents that
  `--include` entries reach the tables without joining the Holm family.

---

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|:--:|---|---|
| CPython ≥ 3.10 | everything | ✓ | 3.13.11 in `.venv` | — |
| SQLite with FTS5 | `CatalogIndex.value_counts` (D-32) | ✓ | 3.50.4, `fts5_built: true` in manifest | `LexicalMode.FALLBACK`; irrelevant for facet scans, which do not use FTS |
| `data/catalog.jsonl` | artifact fingerprinting, `catalog_index()` at run time | ✓ | 60,546,327 B | none — required for D-48 runs |
| `data/catalog.artifacts/catalog.sqlite3` | D-32 gist extraction; every D-48 run | ✓ | 581,844,992 B | rebuild via `python -m starter.shopping_agent.build_catalog_artifacts` (~60-90 s) |
| `claude` CLI | D-38/D-39 authoring, D-35 review | ✓ | **2.1.247**, `/c/nvm4w/nodejs/claude` | **none for LLM authoring** — see below |
| Claude Sonnet via `--model sonnet` | D-38 | ✓ | resolves to `claude-sonnet-5` | Haiku (degrades the primary-author decision) |
| Claude Haiku 4.5 via `--model haiku` | D-39 | ✓ | resolves to `claude-haiku-4-5-20251001` | none; D-39 names it specifically |
| `uv` | `uv run`, `uv sync` | ✓ | present per LOCAL_ENVIRONMENT.md | `.venv/Scripts/python.exe` directly |
| `git` | `code_revision`, `code_revision_dirty` | ✓ | — | `candidate.py:150-154` fails closed to `dirty=True` |
| Network at authoring time | `claude -p` | ✓ | — | **Replay mode**: once the response log is committed, corpus regeneration is fully offline |
| Cloudflare Workers AI credentials | D-41 trigger only | ✗ | — | Out of scope this phase (deferred) |
| `scipy` / `numpy` | nothing | ✗ | — | stdlib `math.comb`, `statistics` — deliberate |

**Missing dependencies with no fallback:**
- **An interactive Claude Code login on the operator's machine.** `claude -p` authenticates
  via the operator's existing OAuth session; `--bare` explicitly does not read OAuth. There
  is no repo credential and none should be added. Corpus **generation** is therefore an
  operator-machine step, not a CI step. Corpus **consumption** (tests, D-48 runs, replay) is
  fully offline. The plan must make that boundary explicit so no test ever shells out.

**Missing dependencies with fallback:**
- Network during generation → replay mode from the committed response log.
- A pre-built artifact → the documented ~60-90 s rebuild.

---

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json`.

### Test Framework

| Property | Value |
|---|---|
| Framework | `unittest` (Python standard library). No pytest, no plugins, no config file. |
| Config file | **none** — discovery is `python -m unittest` from the repository root |
| Quick run command | `uv run python -m unittest tests.test_datasets_divergence -v` (single module, < 2 s) |
| Full suite command | `uv run python -m unittest` — **currently 384 tests in 22.184 s** (measured this session) |
| Warning-strict variant | `uv run python -W error::ResourceWarning -m unittest -v` |
| Fixture pattern | `tests/fixtures.py` (12-product temporary artifact via `CatalogArtifactBuilder`), `tests/arena_fixtures.py` (committed `anchor-legacy` record + `dataclasses.replace` helpers). **No test loads the 61 MB catalog or the 580 MB artifact.** |

### Phase Requirements → Test Map

| ID | Behavior | Test type | Automated command | File exists? |
|---|---|---|---|---|
| **MEAS-10** | Every generated row takes branch 1 — *static* schema layer (D-37) | unit | `uv run python -m unittest tests.test_datasets_schema` | ❌ Wave 0 |
| **MEAS-10** | Every generated row takes branch 1 — *dynamic* `materialize_hidden_fields` identity over the whole corpus (D-37) | integration (catalog-free, `products={}`) | `uv run python -m unittest tests.test_datasets_conformance` | ❌ Wave 0 |
| **MEAS-10** | `intent_override` rows carry all four override keys; `override["turn"] ∈ [2,10]`; `behavior["scenario_type"] == row["scenario_type"]` | unit | `uv run python -m unittest tests.test_datasets_schema` | ❌ Wave 0 |
| **MEAS-10** | Scenario mix is 40/40/15/5 in every corpus (D-30) | unit over committed corpora | `uv run python -m unittest tests.test_datasets_registry` | ❌ Wave 0 |
| **MEAS-11** | Every `probe` row has exactly one `control` partner with the same `pair_id` and the same `ground_truth.parent_asin` | unit | `uv run python -m unittest tests.test_datasets_registry` | ❌ Wave 0 |
| **MEAS-11** | `arm ∈ {control, probe_sonnet, probe_haiku}`; each `pair_id` has ≥2 arms; the 100 cross-check pairs have exactly 3 (D-40) | unit | `uv run python -m unittest tests.test_datasets_registry` | ❌ Wave 0 |
| **MEAS-11** | `align_on_pair_id` refuses an unmatched pair rather than inner-joining | unit | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ Wave 0 |
| **MEAS-11** | Control arm reproduces the public path: for a non-override target, a control row and a bare row drive byte-identical customer behavior (D-31 specific idea — **scoped, see L-2**) | integration, tiny fixture catalog | `uv run python -m unittest tests.test_datasets_control_fidelity` | ❌ Wave 0 |
| **MEAS-12** | Data-flow assertion: no string in an authoring prompt payload is a substring of `searchable_text(target)` | unit | `uv run python -m unittest tests.test_datasets_gist` | ❌ Wave 0 |
| **MEAS-12** | DF floor admits only values clearing the pinned constant; the constant is a named module-level symbol | unit | `uv run python -m unittest tests.test_datasets_gist` | ❌ Wave 0 |
| **MEAS-12** | D-33 bucket gate: `classify_constraint(probe) == classify_constraint(control)` for 100% of committed probe rows | unit over committed corpus | `uv run python -m unittest tests.test_datasets_divergence` | ❌ Wave 0 |
| **MEAS-12** | D-34 gate: zero non-pinned content-token overlap and zero shared 2-gram for 100% of committed probe rows | unit over committed corpus | `uv run python -m unittest tests.test_datasets_divergence` | ❌ Wave 0 |
| **MEAS-12** | The gate detects a violation (two-sided check — a gate that always passes is not a gate) | unit, synthetic violating row | `uv run python -m unittest tests.test_datasets_divergence` | ❌ Wave 0 |
| **MEAS-12** | Freeze: every corpus's on-disk sha256 equals its `data/datasets.json` entry | unit | `uv run python -m unittest tests.test_datasets_registry` | ❌ Wave 0 |
| **MEAS-12** | Registry resolution refuses a corpus whose sha256 has drifted | unit, temp corpus | `uv run python -m unittest tests.test_datasets_registry` | ❌ Wave 0 |
| **MEAS-13** | The `probe_haiku` arm's 100 pair_ids are a subset of the `probe_sonnet` pair_ids (D-40 three-arm pairing) | unit | `uv run python -m unittest tests.test_datasets_registry` | ❌ Wave 0 |
| **MEAS-13** | Each corpus's response log records exactly one resolved model id, and it matches `data/datasets.json` | unit | `uv run python -m unittest tests.test_datasets_authoring` | ❌ Wave 0 |
| **MEAS-13** | The generator-affinity contrast (`probe_sonnet` vs `probe_haiku` on the 100 matched targets) produces a `paired_contrast` record with its MDD | unit, fixture sessions | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ Wave 0 |
| **D-35** | The authoring driver's argv never contains `-c`, `--continue`, `-r`, `--resume` | unit, argv-builder introspection | `uv run python -m unittest tests.test_datasets_authoring` | ❌ Wave 0 |
| **D-35** | The review payload key set is exactly `{gist_attribute, gist_value, phrase}` | unit | `uv run python -m unittest tests.test_datasets_authoring` | ❌ Wave 0 |
| **D-44** | `paired_contrast` never calls `holm_bonferroni` or `winners_curse_correction` | unit, AST scan of `arena/paired_contrast.py` | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ Wave 0 |
| **D-44** | `mcnemar_exact` reproduces hand-checkable values: `(20,4)→0.00154`, `(18,6)→0.02266`, `(0,0)→1.0`, `(5,5)→1.0` | unit | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ Wave 0 |
| **D-44** | `paired_contrast` is byte-reproducible: two calls with the same inputs return identical records | unit, `resamples=500` | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ Wave 0 |
| **D-45** | `adjudicate` refuses two arms with differing `dataset_sha256` — the refusal path is now reachable | unit | `uv run python -m unittest tests.test_arena_adjudication` | ✅ module exists; case is Wave 0 |
| **D-45 inverse** | `paired_contrast` refuses two arms with the *same* `dataset_sha256`, or with differing `catalog_sha256` / `code_revision` / `overrides` | unit | `uv run python -m unittest tests.test_arena_paired_contrast` | ❌ Wave 0 |
| **D-47** | Seam re-exports exactly the eight names; still zero `FunctionDef`/`ClassDef`; evaluator sha256 unchanged | unit | `uv run python -m unittest tests.test_arena_boundary` | ✅ module exists; constants change |
| **D-47** | The boundary scan **recurses** into `arena/datasets/` and fires on a nested violation | unit | `uv run python -m unittest tests.test_arena_boundary` | ✅ module exists; case is Wave 0 |
| **Determinism** | Replay mode reproduces each committed corpus byte-for-byte from the committed response log | integration | `uv run python -m unittest tests.test_datasets_authoring` | ❌ Wave 0 |

### Roadmap Success Criteria → assertions

| # | Criterion | Machine-checkable assertion |
|---|---|---|
| 1 | Expanded sessions always take the authored branch, verified programmatically | D-37 static + dynamic tests above; the dynamic one asserts *identity* (`is`), which is what proves branch 1 fired |
| 2 | Matched control/probe pairs on the same hidden target | `pair_id` completeness + `ground_truth.parent_asin` equality within a pair; `align_on_pair_id` refusal on any orphan |
| 3 | Anti-circular authoring verified; lexical-overlap ratio reported per pair as an acceptance gate | prompt data-flow substring assertion + the D-34 gate over 100% of rows + a per-pair `overlap_ratio` field written into the registry, with a two-sided gate test |
| 4 | Second model family independently authored a cross-check subset; any gap reported explicitly | resolved-model-id uniqueness per corpus + the three-arm subset assertion + a `paired_contrast` record for `probe_sonnet` vs `probe_haiku` carrying its MDD and observed ψ |
| 5 | Probe checksummed and frozen before Phase 3/4 measures against it | `data/datasets.json` sha256 verification test + a recorded commit hash field; plus a registry-resolution refusal on drift |

### Sampling rate

- **Per task commit:** the single most relevant new module —
  `uv run python -m unittest tests.test_datasets_<module>` (< 2 s)
- **Per wave merge:** `uv run python -m unittest` (full suite; currently 22.2 s, budget < 45 s
  after this phase)
- **Phase gate:** full suite green **plus** the five D-48 baseline records published and the
  `paired_contrast` report regenerated, before `/gsd-verify-work`

### What genuinely needs the 580 MB artifact

Only **two** things, and both should be one-off operator steps whose output is committed:
1. D-32 gist vocabulary extraction (`CatalogIndex.value_counts`, ~2.5 s once opened).
2. The five D-48 baseline evaluation runs.

Everything else — schema validation, conformance, bucket gate, divergence gate, registry,
pairing, `paired_contrast`, replay — is testable against `tests/fixtures.py`'s 12-product
temporary artifact or a hand-written `products` dict. Design `gist.py` to read the
**committed** `gist_vocabulary.json` at use time and to build it only under an explicit CLI
flag, so no test ever touches the database.

### Wave 0 gaps

- [ ] `tests/dataset_fixtures.py` — tiny synthetic corpora (control/probe pairs across all
      four scenarios and all reachable buckets), a fake authoring runner, a recorded
      `claude -p` response envelope. Mirrors `tests/arena_fixtures.py`.
- [ ] `tests/test_datasets_schema.py` — MEAS-10 static layer
- [ ] `tests/test_datasets_conformance.py` — MEAS-10 dynamic layer over committed corpora
- [ ] `tests/test_datasets_gist.py` — MEAS-12 DF floor + data-flow assertion
- [ ] `tests/test_datasets_divergence.py` — MEAS-12 D-33/D-34 gates, two-sided
- [ ] `tests/test_datasets_authoring.py` — D-35 isolation, provenance, replay determinism
- [ ] `tests/test_datasets_registry.py` — MEAS-11/12/13 pairing, mix, freeze
- [ ] `tests/test_datasets_control_fidelity.py` — D-31 control-vs-fallback byte identity
      (scoped to non-override scenarios, per L-2)
- [ ] `tests/test_arena_paired_contrast.py` — D-44
- [ ] Extend `tests/test_arena_boundary.py` — D-47 (eight names, recursive scan)
- [ ] Extend `tests/test_arena_adjudication.py` — D-45 cross-corpus refusal
- [ ] Framework install: **none** — `unittest` is stdlib and already in use

---

## Security Domain

`workflow.security_enforcement` is `true`, `security_asvs_level` is `1`. This is an offline
build-time data pipeline with no server, no auth, no session, and no network exposure — but
it **does** shell out to an external process and ingest untrusted model output that becomes
committed data feeding a scoring harness.

### Applicable ASVS categories

| ASVS category | Applies | Standard control |
|---|:--:|---|
| V2 Authentication | no | No user auth surface. The `claude` CLI authenticates via the operator's ambient OAuth; the repo holds and must continue to hold zero credentials |
| V3 Session Management | no | No sessions. (`claude -p --session-id` is a correlation id, not a security boundary) |
| V4 Access Control | no | Single local operator, no multi-tenancy |
| V5 Input Validation | **yes — primary** | Frozen dataclass `validate()` raising `ValueError` on every LLM-derived value before it becomes a corpus row; `json.loads` only, never `eval`/`pickle`/`yaml` (the discipline `arena/store.py:80-81` already states); path allow-listing for corpus filenames mirroring `store.validate_run_id` (`:24-29`) and `resolve_run_directory`'s `is_relative_to` containment (`:40-41`) |
| V6 Cryptography | **yes — narrow** | SHA-256 via `hashlib` only, for integrity and reproducibility. `arena/store.py:46-48` and `candidate.py:90-94` already state the correct threat model: *"an integrity and reproducibility aid for a single local user, never an authenticity control"*. Repeat that framing in `data/datasets.json`'s documentation — a committed digest is not a signature |
| V7 Error Handling & Logging | yes | Never write the OAuth token, `ANTHROPIC_AUTH_TOKEN`, or any environment value into the response log or `data/datasets.json`. The `claude -p` JSON envelope does not contain credentials, but the driver must not add `env` dumps to its provenance record |
| V12 Files & Resources | yes | Corpus filenames are constructed, never taken from LLM output. Response-log writes go through a temp-then-replace path |
| V14 Configuration | yes | No new environment variable is read by any shipped code. The `claude` dependency lives only in `arena/datasets/authoring.py` and must never be reachable from `starter/` |

### Known threat patterns for this stack

| Pattern | STRIDE | Standard mitigation |
|---|---|---|
| Command injection via prompt/model/schema interpolation into a shell | Elevation of Privilege | `subprocess.run([...], shell=False)` with a **list** argv; prompt on **stdin**, never as a shell-interpolated argument. Never `os.system` |
| Untrusted LLM output written straight into a committed corpus | Tampering | Schema validation + `classify_constraint` gate + divergence gate + faithfulness review, all before serialization. Cap constraint length (the evaluator's own `_clean_constraint` limit is 180, `local_evaluator.py:48-49`) |
| Path traversal via a model-supplied or CLI-supplied corpus name | Tampering | Reuse `store.validate_run_id`'s regex discipline and the `is_relative_to` containment check |
| Credential leakage into a committed provenance record | Information Disclosure | Whitelist the recorded fields (`session_id`, `modelUsage` key, `usage`, `total_cost_usd`, `duration_ms`); never `dict(os.environ)`; never the raw `--settings` blob |
| Evaluator tampering to make a corpus "work" | Tampering | Already machine-checked: `EvaluatorIntegrityTest` (`tests/test_arena_boundary.py:151-163`) pins the byte digest |
| A silently regenerated corpus invalidating a committed measurement | Repudiation | D-43 filename versioning + registry sha256 verification at resolution time + refusal on an existing destination |
| Prompt injection from catalog content into the authoring model | Tampering | Structurally mitigated by D-32: raw catalog text never enters the prompt. The abstraction table (§ 5 option 2) keeps that true for the `feature` attribute, which is where the risk actually lives. The reviewer's payload is three fields, so there is no tool surface to hijack |
| Resource exhaustion from an unbounded authoring loop | Denial of Service | Cap re-authoring attempts per constraint (e.g. 3) and fail the item loudly; `subprocess` `timeout=`; a recorded per-corpus call budget |

**Nothing in this phase reaches ASVS L1's high-severity classes** (no authn, no session, no
access control, no injection into a datastore query, no untrusted deserialization). The
`security_block_on: high` gate should have nothing to fire on.

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | Total authoring cost of **$100-160** and **~17.5 h serial / ~2.2 h at 8× parallel** | § 6 Throughput | Extrapolated from three measured calls (10 items each). Real batching, thinking-token variance, and rate limits could move this 2-3× in either direction. If it is 3× worse, D-29 fires and `expanded_dev` is trimmed — the plan should pre-authorize that rather than discover it mid-execution |
| A2 | ~4 authored constraints per generated card, so ~12,800 total | § 6 | Measured universal (2 hard + 2 soft, 200/200) for `intent_card`. If generated cards carry more or fewer constraints, the volume scales linearly |
| A3 | ~950 B blended per generated JSONL row | § 8 | Constructed from one representative row per scenario. Longer authored phrasings push this up; at 1,500 B/row the corpora total ~5 MiB — still fine |
| A4 | Response-log weight of 10-40 MiB | § 8 | Depends entirely on whether the full envelope or only the parsed result is retained. Decide in the plan |
| A5 | Parallel `claude -p` fan-out at N=8 is achievable without rate-limiting | § 6 | Not tested. If 429s appear, `--fallback-model` exists and N must drop. Test N empirically on the first 50 items before committing to a schedule |
| A6 | `--model sonnet` resolves consistently to `claude-sonnet-5` for the duration of the phase | § 6 Pitfall 7 | Alias drift would confound generator affinity. Mitigated by recording the resolved id per call and asserting uniqueness per corpus |
| A7 | ψ ≈ 8% discordance on the control-vs-probe contrast | § 7 | D-28's own assumption, carried forward. It is a *ceiling* as well as a parameter (max representable ΔHR = ψ). Must be replaced with the observed ψ post hoc |
| A8 | Option 2 (a ~90-row feature-abstraction table) is the right resolution of the D-32 FEATURE gap | § 5 | It is a recommendation, not a measurement. Options 1 and 3 are also consistent with D-32; the planner should pick one deliberately and comment the rationale |
| A9 | Corpus generation cannot be run in CI because `claude -p` needs an interactive login | § "Environment Availability" | Based on `--bare`'s documented OAuth exclusion. If an API key were ever provisioned this changes — but provisioning one contradicts the project posture |

---

## Open Questions

1. **Does D-38 permit Haiku for `expanded_dev`/`expanded_confirm`?**
   - *Known:* D-38 says "Primary authoring is Claude Sonnet subagents (user directive)".
     D-29 says protect the probe over the dev corpus. Sonnet costs ~11× Haiku per constraint
     at the measured rates, and the dev/confirm corpora are 87.5% of the volume.
   - *Unclear:* whether "primary authoring" scopes to the whole phase or to the artifact
     that carries the finding.
   - *Recommendation:* the planner should surface this as an explicit checkpoint rather than
     resolve it silently. Defaulting to Sonnet everywhere is the safe reading and costs
     roughly $100 and several hours; defaulting to Haiku for dev/confirm is a material
     saving and arguably within D-38's intent. **Do not decide this in a task action.**

2. **How should the D-32 FEATURE gap be closed?**
   - *Known:* the DF floor alone admits verbatim catalog spans (§ 5b, measured).
   - *Unclear:* whether the ~90-row abstraction table is worth the authoring effort versus
     dropping FEATURE from the gist entirely.
   - *Recommendation:* option 2 (abstraction table), because `feature` is 50.5% of all
     constraints and dropping it would leave half the probe unanchored. Pin the choice with
     a commented rationale per the D-32 discretion note.

3. **Do the five D-48 records enter `experiments/LEADERBOARD.md`?**
   - *Known:* they are one candidate × five corpora, so `adjudicate` would refuse them as
     candidate arms (differing `dataset_sha256`) — correctly, per D-45.
   - *Unclear:* whether they should appear as `--include` report-only entries, or in a
     separate corpus-baselines table.
   - *Recommendation:* a separate table. Putting five different-corpus rows into a
     leaderboard whose entire premise is same-corpus comparison invites exactly the
     misreading D-45 exists to prevent.

4. **Should `_STOPWORDS` be promoted to public or re-exported?**
   - *Recommendation:* promote (rename to `STOPWORDS`, single call site at
     `constraint_extractor.py:109`), with a comment noting the D-34 consumer. A re-export
     leaves a private name importable across packages, which is the worse precedent.

---

## Landmines

Concrete traps a planner would otherwise walk into, in rough order of cost-if-hit.

**L-1 — The AST boundary guard does not recurse.** `glob("*.py")`,
`tests/test_arena_boundary.py:80`. `arena/datasets/` would be entirely unguarded, and the
basename-only bridge exemption would let a second `evaluator_bridge.py` hide inside it. See
§ 3. **Cost if hit:** MEAS-15 silently false; discovered at review, not by a test.

**L-2 — D-31's "free verification asset" conflicts with D-36 for `intent_override`.** D-31
proposes a test that a control-arm row and a bare row produce byte-identical customer
behavior. That holds for `buying`, `browsing` and `boundary` — `behavior_for` returns
`{"scenario_type": s}` and never touches the rng (`local_evaluator.py:74-87`). It **cannot**
hold for `intent_override`, because D-36 pins `override["turn"]` from `pair_id` while the
fallback draws `rng.choice([3,4])` from `f"{sample_id}\0{scenario_type}"`. The two agree
only by coincidence. **Scope the test to non-override scenarios and assert card-only
identity for `intent_override`**, with a comment naming D-36 as the reason. Writing the
unscoped test produces a 15%-flaky failure that reads as a corpus bug.

**L-3 — The D-35 solvability trap.** § "Pitfall 4". Compounded by the fact that
`.planning/research/ARCHITECTURE.md:258` explicitly *recommends* a solvability check for the
expanded corpora. The plan must apply it asymmetrically (expanded: yes; probe: never) and
state why, or a diligent implementer will "fix" the probe pipeline by adding it.

**L-4 — F-06's color keyword count is wrong (7, not 12), and the substring semantics change
what D-34 must exclude.** § "F-06". A divergence gate built on the twelve-colour list will
pin the wrong token and either over-report or under-report overlap.

**L-5 — D-33 bucket preservation is *not* the binding constraint; the trigger-substring
traps are.** Measured 10/10 preservation on both models for a naive prompt. But
`"no fitting room needed"` → `style`, `"good for everyday work"` → `use_case`,
`"a fabric that breathes"` → `material`. Because `feature` is the residual default and 50.5%
of the corpus, most re-authoring will be feature-bucket phrases that accidentally hit an
earlier clause. **Put the forbidden-substring list in the prompt**, not just in the gate.

**L-6 — D-32's FEATURE assumption is 92% true and the 8% is the hazard.** § 5b. `imported`,
`machine wash`, `rubber sole` all clear any sane DF floor and are verbatim catalog text.

**L-7 — The `budget` bucket does not exist in a control card.** Measured 0/798. Any plan
cell for a budget-bucket probe arm is planning for something `intent_card` cannot produce
(§ 2).

**L-8 — `_require_paired` rejects the control/probe arms.** § 4. Cheap to fix, expensive to
discover late because it surfaces only when real session data arrives.

**L-9 — D-25's run-cost column is ~1.8× low, against a quantity with documented 2×
variance.** § 8. Budget 2-3.5 h for D-48, not one.

**L-10 — `paired_contrast` needs a *new* inverse guard and cannot get its digests from
`CandidateEntry`.** § 4. `CandidateEntry` (`leaderboard.py:189-206`) carries `fingerprint`
but neither `catalog_sha256` nor `dataset_sha256`; use `spec_from_record`.

**L-11 — `run-a`'s override mapping requires typing both flags.** `run_arena.py:56-96`
documents that omitted flags are omitted from the fingerprint. D-48's "using the existing
`run-a` spec" is only literally reproduced if the invocation includes
`--exploration disabled --lexical-mode auto`.

**L-12 — `claude -p` loads this project's `CLAUDE.md` by default**, costing ~31k prefix
tokens per cold call and telling the authoring model exactly what the probe is for. § 6.
Run from a clean cwd with `--setting-sources ""`; `--bare` will not work with OAuth.

**L-13 — Generated artifacts under `experiments/` outside `baselines/` are silently
gitignored.** § 8. "Frozen means committed" (D-04/D-43) would become quietly false.

**L-14 — `--json-schema` takes inline JSON; `--max-turns 1` breaks structured output;
`result` is a JSON string; `is_error` can be true with exit code 0.** All four measured.
§ 6 Failure Modes.

**L-15 — `search_terms` deduplicates**, so it cannot support D-34's 2-gram half. Use
`TOKEN_RE.findall(normalize_text(...))` for adjacency. § 5.

**L-16 — Repo weight risk is the response log, not the corpora.** 3.2 MiB of JSONL is
nothing; 10-40 MiB of raw response envelopes is a decision. § 8.

**L-17 — `value_counts` returns an unsorted dict** (`catalog_index.py:41`); `values_for`
sorts, `value_counts` does not. Any iteration over it that reaches output must impose an
explicit sort, per the repo's determinism convention.

**L-18 — `metric_summary` raises on an empty tuple** (`metrics.py:126-127`). A per-scenario
or per-bucket paired-contrast breakdown must filter empty buckets before calling. The
`boundary` scenario is 5% of 300 pairs = 15 sessions; a further per-bucket split can
legitimately reach zero.

---

## Sources

### Primary (HIGH confidence) — read or executed this session

- `evaluator/local_evaluator.py` (full file, 313 lines) — all eight functions in § 1
- `arena/evaluator_bridge.py`, `arena/arena.py`, `arena/candidate.py`, `arena/store.py`,
  `arena/metrics.py`, `arena/statistics.py`, `arena/run_arena.py`,
  `arena/adjudication.py:60-260`, `arena/leaderboard.py:189-313`
- `tests/test_arena_boundary.py` (full), `tests/arena_fixtures.py` (full),
  `tests/fixtures.py:1-40`
- `starter/agent.py`, `starter/shopping_agent/catalog_index.py`,
  `starter/shopping_agent/text_normalization.py`, `starter/shopping_agent/models.py:1-40`,
  `starter/shopping_agent/local_search_backend.py:40-100,354-380`,
  `starter/shopping_agent/search_backend.py:158-226`,
  `starter/shopping_agent/catalog_artifacts.py:420-500`,
  `starter/shopping_agent/constraint_extractor.py:69-141`
- `.gitignore`, `.planning/config.json`, `docs/submission_rules.md:50-80`
- `experiments/baselines/{run-a,run-b,run-c,anchor-legacy,synthetic-promote-10}/summary.json`
- `experiments/RUNS.md:110-160,232-250`
- `.planning/research/ARCHITECTURE.md:235-325`, `.planning/research/PITFALLS.md:274-334`
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/PROJECT.md` (grep)

**Commands executed (measurements reported above):**
- Full `data/public_set.jsonl` schema/mix/target analysis
- `CatalogIndex.value_counts` over all ten `Attribute` values against the 580 MB artifact
- Full 50,000-product catalog scan for `searchable_text` token DF (14.8 s)
- `intent_card` + `classify_constraint` + `search_terms` over all 200 public targets
  (bucket distribution, control-arm overlap)
- `classify_constraint` substring-trap probe over 20 phrasings
- Exact McNemar p-values and full-enumeration power at n=300 / n=100
- Four real `claude -p` invocations (haiku smoke, haiku structured, sonnet structured,
  haiku clean-cwd)
- `python -m unittest` full suite (384 tests, 22.184 s)
- `claude --help`, `claude --version`

### Secondary (MEDIUM confidence)

- `CLAUDE.md` § Configuration / Platform Requirements — the "~190 s full evaluation" figure,
  which § 8 shows is superseded by the committed arena records for the D-48 code path
- `.planning/phases/02-expanded-dataset-paraphrase-probe/02-CONTEXT.md` — the locked
  decisions; F-03/F-04/F-05/F-07 confirmed against source, F-06 corrected

### Tertiary (LOW confidence) — flagged, not relied upon

- Throughput and cost extrapolation from four `claude -p` calls (Assumptions A1, A5)
- The ψ = 0.08 discordance assumption inherited from D-28 (Assumption A7)

No WebSearch, Context7, Exa or Firecrawl was used. `brave_search`, `exa_search` and
`firecrawl` are all `false` in `.planning/config.json`, and every question in this phase's
research focus was answerable from the working tree or from a command run against it. The
one class of question that would have warranted external lookup — the McNemar variant
choice — was instead settled by direct exact computation, which is stronger evidence than a
citation.

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|---|---|---|
| Evaluator surface (§ 1) | **HIGH** | Full file read; every claim carries a line number; the file is byte-pinned by a passing test |
| Sample schema (§ 2) | **HIGH** | Measured over all 200 rows; `intent_card` re-run over all 200 targets |
| Seam and AST guard (§ 3) | **HIGH** | Full test file read; the non-recursion is a direct reading of `glob` |
| Arena reuse (§ 4) | **HIGH** | All six modules read; the `_require_paired` blocker is a direct reading of `:114-117` |
| Catalog inputs (§ 5) | **HIGH** | DF distributions measured against the real 580 MB artifact; token DF measured over all 50,000 products |
| LLM pipeline mechanics (§ 6) | **HIGH** for mechanics, **MEDIUM** for projections | Four real calls verify the mechanism, the failure modes, the provenance fields and the context-contamination effect. Throughput/cost at 1,000× the tested volume is extrapolation |
| Statistics (§ 7) | **HIGH** | McNemar p-values and power computed by exact enumeration, not cited; D-28's two claims independently reproduced |
| Volume/runtime (§ 8) | **HIGH** | Committed `elapsed_seconds` values; measured suite runtime; measured row sizes |
| Validation architecture | **HIGH** | Framework, fixture pattern and current suite timing all measured |
| Landmines | **HIGH** | Every entry traces to a line number or a command run this session |

**Research date:** 2026-08-31
**Valid until:** 2026-09-30 for everything grounded in the working tree (the evaluator is
byte-pinned and the catalog is frozen). **7 days** for the `claude -p` CLI mechanics and
model-alias resolution — CLI flags and alias targets move, and § 6's failure modes were
verified against version 2.1.247 specifically.
