# Semantic Constraint Extraction — Design & Research Notes

> Status: **research/design only, not yet implemented.** Captures the investigation
> into the next bottleneck (NLP constraint extraction) after the scalable-retrieval
> work. Sequencing is deliberately evidence-gated — do not build the embedding layer
> until a miss-classification proves the vocab gap is real.

## Problem statement

The current `constraint_extractor.py` maps a user message to typed
`PreferenceUpdate`s by matching catalog vocabulary phrases. Two failure classes
dominate the misses observed during the scalable-retrieval work:

1. **Extraction noise (precision).** Junk catalog values collide with ordinary
   English — a brand literally named `"not"`, a color `"m"`, a feature `"no"` —
   and an `OTHER`-residual fallback turns any unmatched conversational filler
   ("those options are not quite right yet") into a low-confidence soft
   constraint whose tokens pollute lexical ranking. This was patched with
   phrase-regexes (`_VERBOSE_DECLINE_RE`; a reverted slate-feedback regex) —
   **overfit to the 200-sample public evaluator**, not a principled fix.
2. **Vocabulary gap (recall).** User words may not match catalog surface forms
   ("warm" vs catalog "insulated"/"fleece"; "cozy" vs "fleece"). NOT yet shown
   to be material in our miss data — the observed misses were noise (class 1),
   not genuine vocab gaps.

**Key measured caveat:** every buying miss diagnosed this session was
extraction *noise* or ranking depth, NOT a semantic vocab gap. So the semantic
layer is speculative until the miss-classification experiment (below) runs.

## Load-bearing research conclusions (4 subagent investigations, 2026-08-28)

### A. Negation/modality MUST stay symbolic — three independent threads agree

- **Embeddings cannot carry polarity.** Antonyms are *near neighbors* in embedding
  space (distributional hypothesis: "the coat is very ___" fits warm and cold;
  contrastive terms co-occur). Cosine cannot separate synonym from antonym.
- **Vector-arithmetic negation does not transfer to static tables.** Widdows &
  Peters orthogonal projection (`a − (a·b/|b|²)b`) yields *topical dissimilarity*
  ("steer away from b"), NOT logical NOT — needs a base term, can't express
  unary ¬X, can't distinguish "no dog" from "dog", doesn't compose.
- **Task arithmetic / activation steering work only on TRAINED models** (weight
  or activation space), because the concept is a *learned disentangled direction*
  — a static lookup table has geometry but no computation to move along. Even in
  trained models it's coarse capability suppression (tunable λ, leaks via
  superposition — TIES needs sign-election), NOT propositional logic.
- **CLIP/VLMs confirm the negative result:** CLIP is negation-blind ("no dog"
  embeds ~onto "dog"); every fix (NegCLIP, NegBench, CoN-CLIP) *retrains weights*
  — nobody subtracts a negation vector, because there isn't one.

→ **Negation (EXCLUDE), requirement (HARD), and hedge (SOFT) are symbolic
operators applied OVER an embedding-resolved positive concept.** This seam holds
even if we later adopt a runtime model for concept resolution.

### B. The junk-value problem has a principled, catalog-derived fix (no embeddings)

- **Document-frequency gating, two-sided:** (1) a value that is a high-frequency
  *common English word* but low-frequency as a *real catalog value* ("not", "m",
  "key") is gated or requires disambiguating context; (2) a value with
  pathologically low catalog DF (data-entry junk) is dropped by an elbow-method
  cutoff. This is the Terrier stopword-construction method + standard gazetteer
  recipe. Side (1) needs a **general-English frequency reference** (see §D).
- **Context-required firing** for ambiguous mentions ("m" fires as size only
  adjacent to a garment category; "not" never fires as brand without a
  brand-position pattern). Rule-based, offline, kills our two example failures.
- **Aho-Corasick leftmost-longest** matcher (precomputed DFA, ~150 lines pure
  stdlib) prefers "north face" over "face" by construction.

→ **This replaces `_UNSAFE_METADATA_TOKENS` + phrase-regexes with a derived,
measurable, catalog-grounded gate.** Highest-leverage, lowest-risk, no embeddings.

### C. Synonyms can be mined from the catalog deterministically

- **PMI / co-occurrence (Turney 2001):** pointwise mutual information between a
  user word and a catalog attribute value across product texts. High-PMI pairs →
  synonym candidates ("warm"↔"insulated" IF they co-occur). Pure arithmetic,
  offline, deterministic.
- **Honest ceiling (SANTA, Amazon):** pure string/co-occurrence cannot catch
  synonyms that never co-occur ("720p"≈"HD"). Those need an embedding or a rule.

### D. Open-vocab semantic bridge — only if evidence demands it

- **No similarity method separates same-stem antonyms.** fastText subword makes
  it worse (shared `wat/ate/ter` n-grams elevate cos(waterproof, water-absorbent);
  NOTE: the distinct suffix n-grams `abs/bso/sor…` DO contribute — the earlier
  "numerically outvoted" claim was wrong; the real effect is an *elevated
  shared-stem similarity floor* plus the distributional antonym proximity that
  hits whole-word word2vec too). → prefer **whole-word** vectors over subword;
  correctness comes from a **shipped antonym/polarity veto**, not from cosine.
- **Counter-fitting (Mrkšić 2016):** offline post-process that bakes
  antonym-repulsion into a vector table using WordNet+PPDB + hand domain
  antonyms. Ships as a static table, zero runtime cost.
- **Morphology:** inflectional folding (boot/boots, insulate/insulated) SAFE;
  derivational/prefix stripping (-less, un-, -proof) DANGEROUS (flips polarity).
  Ship an **inflection-only lemma table** + a polarity-suffix blocklist. word2vec
  closed-vocab is a *feature* here (won't hallucinate water-absorbent from
  waterproof's chars).

## Pretrained artifact options (for the §D bridge, if built)

Hard-constraint path (static table + arithmetic, no runtime model):
- **ConceptNet Numberbatch** — 300d, retrofitted to ConceptNet relations
  (synonyms/antonyms baked in from human knowledge, not just co-occurrence);
  trim to domain vocab → few MB. Best fit: already knows lexical relations, no
  training needed on our side (sidesteps "50k is too small for word2vec").
- **Counter-fitted vectors (Mrkšić)** — explicitly antonym-repelled.
- **WordNet** — the polarity ground truth (explicit antonym relations); tiny.

Relaxed-constraint path (allows CPU runtime model — CHANGES project character):
- **all-MiniLM-L6-v2** (~90MB, 384d) — clause-level embeddings, best paraphrase
  quality, but a real dependency + inference (not "table + arithmetic").

## Training corpus options (if word2vec is trained)

The catalog is sampled from **Amazon Reviews 2023 (McAuley/UCSD)**. That dataset
has two halves with OPPOSITE roles:
- **Item metadata** (~48M items) — same catalog register as our 50k; more of it
  = same stilted language. Do NOT use for the gazetteer (would inject
  non-catalog attribute values). Gazetteer stays catalog-only.
- **Review text** (~570M reviews) — *buyer language* ("keeps me toasty",
  "runs small") — the register the evaluator SIMULATES. This is the right
  corpus for the user→catalog vocab bridge, better-fit than generic GloVe.

Caveats if used: (1) scope to the semantic layer ONLY, gazetteer stays
catalog-derived; (2) it's an external build dependency — breaks
"reproducible from shipped catalog alone" — pin as "table built from Amazon
Reviews 2023 category X, SHA Y"; (3) not leakage (word2vec learns co-occurrence,
not label mappings; organizer permits external data). The cheapest slice — a
general-English frequency list for the two-sided junk gate (§B) — is worth
grabbing FIRST regardless.

## Proposed architecture (layered, each independently testable)

```
BUILD (offline, deterministic, one-time; freeze all thresholds):
  catalog → DF-gated gazetteer            (kills junk: brand="not", color="m")
          → PMI-mined synonyms             (warm→insulated, from co-occurrence)
          → [+ pretrained table (Numberbatch) for open-vocab, IF gap proven]
          → [+ counter-fit w/ WordNet+PPDB+hand antonyms → polarity table]
          → inflection-only lemma table + polarity-suffix blocklist

INFERENCE (static tables + arithmetic, no model/GPU/network):
  [1] tokenize + inflection-normalize (boots→boot; NEVER strip -proof/-less)
  [2] clause segmentation (split on punctuation + contrastive but/however/instead)
  [3] modality per clause (SYMBOLIC): negation cue→EXCLUDE | must/only→HARD |
        hedge maybe/prefer→SOFT ; pseudo-cue blocklist ("not only") from day one
  [4] concept resolution: Aho-Corasick leftmost-longest gazetteer hit (DF-gated)
        else PMI synonym; else [embedding nearest catalog value + polarity veto]
  [5] compose: apply clause modality operator over resolved concept
```

Layers 3 (symbolic negation) and 4 (concept resolution) are DECOUPLED — that is
the whole point. This mirrors NegEx/ConText (clinical NLP, 20yr battle-tested):
trigger tables (negation / speculation / pseudo) + scope-to-clause-boundary,
with concept detection swapped for embedding resolution.

## Falsifiable test set (design before code)

**Concept resolution (layer 4):**
- `resolve("leather") == (material, "leather", exact)` — exact hit
- `resolve("warm") ∈ {feature:insulated, fleece, thermal}`, conf < exact — synonym
- `resolve("key") → no constraint` (DF-gated) — the principled junk fix
- `resolve("xyzzy") → no constraint, no crash` — true OOV
- determinism: identical output across runs (frozen tables)

**Modality/negation (layer 3) — vectors MUST NOT touch:**
- `"not leather" → EXCLUDE(material:leather)` (resolve positive, then negate)
- `"warm but not wool" → {SOFT(insulated), EXCLUDE(wool)}` — clause split
- `"must be leather" → HARD(...)`; `"maybe warm" → SOFT(...)`, low conf
- antonym guard: `resolve("not warm")` must NOT return feature:cold or a
  "negated vector" — returns EXCLUDE of the positive resolution
- pseudo-cue: `"not only warm" → does NOT EXCLUDE warm`

**Junk-rejection (the measurable win):**
- full-200 miss-classification becomes a regression test: "no miss caused by a
  DF-below-threshold constraint"
- golden set: ~30 hand-labeled evaluator replies → assert extraction produces
  intended constraints AND NOTHING ELSE (precision)

**Anti-overfit:** hold-out paraphrases NOT in the catalog ("cozy",
"water-repellent") → prove open-vocab generalization.

## B1 RESULT (RAN 2026-08-29) — embeddings de-prioritized to nil for public

Miss-classification of all **48 misses** in the retained 0.76 run
(`experiments/scalable-strict/`), reconstructed from typed traces + the
deterministic evaluator + catalog DF. Analysis is offline over retained
artifacts; no re-run.

| Cause class | Count / 48 |
| --- | ---: |
| **Vocab-gap** (user word ≠ catalog surface, target satisfies semantically) | **0** |
| **Genuine target-lacks** (target really lacks a required attribute) | **0** |
| Junk `other='those options are not quite right yet'` filler carried | 48 |
| Material-as-category misclassification (`category:equals:cotton`) | 18 |
| Overlong whole-description feature string (DF ≤ 1) | 5 |
| **intent_override: target in slate PRE-override, rotated out after** | **18** |
| Never retrieved (6 IO + tail) | 6 |

**Finding 1 — the embedding layer (§D) recovers zero on this evaluator, by
construction.** `local_evaluator.intent_card()` builds the simulated user's
words *verbatim from the target product's own catalog strings* (whitespace-clean
+ 180-char truncate; no paraphrase, no synonym substitution). So the
user→catalog register mismatch that motivates §C/§D (PMI synonyms, Numberbatch,
Amazon-Reviews word2vec) is **null on the public set**. All 6 apparent
"target-lacks" were false positives of a literal-substring check — after
stripping the injected `material: `/`color : ` dict-key prefixes, every content
word of every constraint is present in the target's own text. → **Drop §C and §D
for public scoring.** They would matter only on a private set with genuinely
paraphrased users — unproven and unmeasurable from here. Do NOT build embeddings
until such a probe exists.

**Finding 2 — the dominant single lever is a rotation bug, not NLP.** 18/48
(37.5%) are intent_override sessions where our slate *contained the target* at an
early turn — but every appearance was strictly BEFORE the override fired (the
evaluator credits a hit only once `override_applied` is true, at `rng.choice([3,4])`),
and the shown-set rotation then permanently excluded the already-shown target.
**0** cases had the target in-slate at/after the override. Fix = re-admit on
override (an override is a fresh intent → clear the shown-set so the now-best
matches, which include the target, resurface). **Ceiling ≈ +18/200: hit@10
0.76 → ~0.85, no semantic work.** Ship carefully: naive shown-set removal
already regressed buying 0.775→0.7375 (rotation coupling is real — decouple on
intent-change, don't disable).

**Finding 3 — the remaining 42 are precision/pollution**, all catalog-derivable,
no embeddings: junk `other` filler (48), material-as-category (18), overlong
feature strings (5). This is exactly the DF-gated gazetteer's job.

## Sequencing (REVISED post-B1 — rotation first, embeddings dropped)

1. **Rotation-decoupling / override re-admission** — NEW #1. Biggest measured
   lever (18 misses, ~+0.09 hit@10 ceiling), pure ranking logic, zero NLP.
   Decouple shown-set rotation from intent_version; on an override
   (old-preference replaced) treat as fresh intent and clear the shown-set.
   Guard against the known buying regression (measure buying + IO together).
2. **DF-gated gazetteer + context-gating** — addresses the 42 precision cases
   (junk `other`, material-as-category, overlong features). Catalog-derived,
   measurable, replaces the overfit phrase-regexes. Still worthwhile.
3. **NegEx-style cue/scope/pseudo tables** — correctness scaffolding for
   negation/modality; formalize `_NEGATION_CUE_RE`/`_SCOPE_BOUNDARY_RE`.
4. ~~**PMI synonym mining**~~ — **DROPPED for public** (B1: 0 vocab-gaps). Revisit
   only if a private-set paraphrase probe proves a gap.
5. ~~**Embeddings + counter-fitting**~~ — **DROPPED for public** (B1 Finding 1).
   Deferred indefinitely, evidence-gated on a private-set probe that does not
   yet exist.

The B1 analysis script is `experiments/analyze_misses_b1.py` (offline over
retained traces; safe to re-run).

## Sources (key)

- Negation symbolic: Chapman NegEx 2001; Morante *SEM-2012; Farkas CoNLL-2010 hedge
- Antonyms/embeddings: Mrkšić counter-fitting NAACL 2016; Nguyen dLCE ACL 2016
- Vector negation: Widdows & Peters ACL 2003 (topical only); Ilharco task
  arithmetic ICLR 2023; Arditi refusal-direction NeurIPS 2024; Alhamoud NegBench
  CVPR 2025; Yuksekgonul NegCLIP ICLR 2023
- E-commerce AVE: Amazon QAU ACL 2023; SANTA ECNLP 2021; Turney PMI-IR 2001;
  eBay synonym SIGIR-eCom 2019; Terrier stopword construction
- Embeddings offline: Bojanowski fastText 2017; Faruqui retrofitting NAACL 2015;
  ConceptNet Numberbatch; PPDB N13-1092
- Corpus: Amazon Reviews 2023 (McAuley/UCSD)
