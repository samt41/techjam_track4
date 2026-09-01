# Stack Research: Rank-1 Precision (MRR) and Convergence Speed (MTTC)

**Domain:** Reranking, offline semantic indexing, and clarifying-question policy for a
deterministic, stdlib-only conversational product-search agent (SQLite/FTS5 +
Bayesian belief ranking, HR@10 0.920 already near-saturated).
**Researched:** 2026-08-29
**Confidence:** MEDIUM-HIGH (technique-level findings verified against multiple
current sources; exact numeric transfer to *this* system's already-strong baseline
is unverified until measured in the bake-off — flagged per item below)

**Framing.** This is not a "what exists for search" survey — that system is built.
Every recommendation below is filtered through one question: *does this move MRR
or MTTC on a system that already clears HR@10 0.920, MRR 0.5245, MTTC 3.425, under
a stdlib-only, byte-deterministic, no-GPU/no-model-server/no-vector-DB
constraint?* Several textbook "improve ranking" techniques (ColBERT, runtime LLM
reranking, live dense retrieval) are excluded below, not omitted — see "What NOT
to Use."

## Recommended Stack

### Tier 1 — build first (stdlib-safe, deterministic, directly targets MRR/MTTC)

| Technique | Purpose | Why Recommended |
|---|---|---|
| **Hand-rolled linear/logistic reranker over the fused candidate list** (no ML library at runtime) | Re-order the top ~20-50 RRF-fused candidates using a small set of interpretable features (fused RRF score, per-route hit count/diversity, exact-title/exact-phrase flag, structured-attribute match count, price-fit, category-depth match, `already_shown`) combined by a frozen dot product | This *is* learning-to-rank, done the only way that survives the stdlib constraint: fit weights **offline** (pure-Python gradient descent, or scikit-learn/LightGBM as a **build-time-only, never-shipped** dev dependency used purely to produce coefficients), then bake the resulting floats into `ranking.py` as constants, exactly like `_ROUTE_WEIGHTS` already is. Zero runtime dependency, byte-deterministic, and it directly attacks the stated problem: hits sitting at rank 2-4 with the right candidates already recalled. This is the single highest-leverage, lowest-risk bake-off candidate. |
| **Decision-theoretic clarifying-question value, replacing/augmenting pure entropy** | Score each candidate attribute question not by expected posterior-entropy reduction alone, but by expected improvement in the *rank of the eventual target* (e.g., expected reciprocal-rank gain, or P(top-1 after answer) − P(top-1 now), computed over the existing strict population) | 2024-2025 conversational-search literature (Rahmani et al., EACL 2024 "Clarifying the path to user satisfaction"; Chen et al. 2024 "Learning to Clarify") converges on the same critique: information-theoretic entropy reduction is a *proxy* for what you actually want (task success / fewer turns), and usefulness-aware or outcome-aware question selection consistently beats pure EIG in reported studies. No published number transfers directly to this system's MTTC, but the mechanism is already 90% built (the posterior and the population scan exist; only the scoring function inside `PosteriorQuestionModel` changes), so the marginal build cost is small relative to the plausible MTTC gain. **Confidence: MEDIUM** (directional consensus in literature, no direct benchmark on this system). |
| **Tuned, normalized weighted score fusion, replacing/augmenting RRF k=60** | Instead of pure `1/(60+rank)`, use per-route weights tuned on a held-out dev split, with scores min-max or z-normalized per route before combination (convex/CombSUM-style fusion) | Bruch et al. (2022) and OpenSearch's own six-dataset benchmark found RRF underperforms tuned score-based fusion by a measured **~3.86% NDCG@10** when a validation set is available to calibrate weights — which this project has (200 public sessions, soon more via the paraphrase probe). RRF's stated rationale (score-scale independence, no tuning needed) is a *convenience* property this project doesn't need, since routes here are heterogeneous but stable (metadata, exact FTS, expanded FTS, category, counterfactual) and weights are already hand-set (`_ROUTE_WEIGHTS`) rather than untuned — i.e., the project has already half-abandoned "pure" RRF discipline. Tuning it properly is a natural next step. **Confidence: MEDIUM-HIGH** (OpenSearch and Bruch et al. are credible, reproduced findings; exact transfer to this fusion topology unverified). |
| **Offline LLM-generated concept/synonym table (expand the existing 6-entry `_EXPANSIONS`)** | Replace the ad hoc expansion table with a catalog-derived, LLM-authored synonym/near-synonym/hypernym table generated once at build time, baked into `EXPANDED_FTS` route input | Already scoped in `docs/superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md`, but that spec targets **recall** (open-vocabulary matching) and is explicitly gated on evidence of a vocabulary gap the public set structurally cannot produce. Reframe the same infrastructure for **MRR**: better/more precise expansions reduce false-positive `EXPANDED_FTS` hits that currently compete with the true target for top rank. This is Tier 1 because it stays stdlib at runtime (frozen text baked into FTS content) — no vector math, no ONNX. **Confidence: MEDIUM** (mechanism is sound; magnitude depends entirely on how much of the 2-4 rank gap is caused by expansion noise vs. genuine ambiguity — not yet measured). |
| **doc2query-style offline term injection, "Rewrite" variant only** | At build time, generate short synthetic queries/phrases per product (or per concept, as the existing spec already proposes) and fold them into the FTS-indexed text or into per-term weight adjustments — but favor the **term-reweighting** effect over the **new-term-injection** effect | docTTTTTquery / DeepImpact literature draws an explicit split: "Inject" (add unseen terms) mainly lifts **recall**, "Rewrite" (reweight existing terms toward salience) mainly lifts **MRR**. Since this system's recall is already saturated (HR@10 0.920) and the stated gap is precision among already-recalled candidates, the Rewrite half of doc2query's effect is the relevant half — implemented here as a build-time term-importance signal (see next row) rather than literally running docT5query. **Confidence: MEDIUM** (well-established literature pattern; not previously applied to a catalog of this structure). |
| **SPLADE-style term-importance weights, frozen into the existing TF-IDF postings table** | Run a SPLADE (or comparable learned-sparse) encoder **once, offline**, over catalog documents; extract the learned per-term importance weights; merge them into `lexical_postings` as a static multiplier on top of (or replacing) the current pure TF-IDF weight — never run the encoder at query time | SPLADE's whole design point (`SPLADE-doc` variant explicitly) is compatibility with classical inverted-index infrastructure: document-side weights are precomputed, and a plain bag-of-words query needs no query-time model. This is a very close match to `lexical_postings`/TF-IDF fallback already in the codebase — it's the same data structure with better numbers in it. Directly targets MRR because it up-weights the *discriminative* terms in a title/description rather than raw frequency, which is exactly the signal that currently sits behind pure count-based TF-IDF and (separately) the fixed FTS field weights (title 6.0, category 4.0, etc.). **Confidence: MEDIUM** (SPLADE's doc-side-only mode is well documented; distilling it into a legacy TF-IDF postings table rather than a native sparse-vector search engine is a nonstandard but mechanically straightforward adaptation — size and integration risk noted below). |

### Tier 2 — spike only, with dependency/latency cost explicitly measured (candidates, not defaults)

| Technique | Purpose | Cost |
|---|---|---|
| **Small ONNX cross-encoder rerank of top-N fused candidates** (e.g. `cross-encoder/ms-marco-MiniLM-L6-v2`, 22M params, 6-layer) | Score (query, product-text) pairs directly, replacing/supplementing the belief-model reordering for the top 20-50 candidates before final sort | **Effect:** on raw BM25, cross-encoder MiniLM roughly doubles MRR@10 (BM25 0.1874 → 0.3901 on MS MARCO, per the official model card). But that gain is measured against an unranked/weak baseline. Against an already-good first-stage ranker, gains shrink sharply — a 2025 applied study (CheckThat! 2025) found the same model class lifted MRR@5 only 0.6300 → 0.6474 (+2.8%) on top of decent retrieval, and a domain-shift study found off-the-shelf MS MARCO cross-encoders *degraded* NDCG by up to 3% outside web-search-like domains while adding 560-2100 ms latency. This system's MRR (0.5245) is already well above raw-BM25 territory, so expect the CheckThat-style small gain, not the MS MARCO headline gain — **and** verify the model isn't out-of-domain-brittle on e-commerce attribute language before trusting it. **Confidence: MEDIUM** for "some gain," **LOW** for magnitude on this specific system. **Dependency cost:** `onnxruntime` (CPU package ~16-25 MB wheel, ~40-50 MB installed with numpy/sympy transitively) + a tokenizer (WordPiece for MiniLM is implementable in pure Python from `vocab.txt` with no extra dependency, avoiding the `tokenizers` Rust wheel) + the exported ONNX graph (~85-90 MB fp32, or int8-quantized to roughly 20-25 MB with typically <1% MTEB-class accuracy loss). **This breaks the "zero declared runtime dependencies" claim** that Feasibility & Practicality currently banks on — must be weighed against the Impact/Innovation framing, not assumed free. **Latency cost:** tens of ms per candidate on CPU for a 6-layer MiniLM at short sequence lengths (community-reported; no authoritative CPU-specific benchmark found — flag as needing local measurement), so reranking 20-50 candidates per turn is plausibly 0.2-2 s/turn — must be budgeted against the per-turn soft deadline already on the roadmap. |
| **Small local ONNX embedding model as an added dense/semantic route** (`BAAI/bge-small-en-v1.5`, `TaylorAI/gte-tiny`, `intfloat/e5-small-v2`) | Adds a semantic-nearest-neighbor route to the existing multi-route fusion | This is the *recall*-oriented spec already written and deliberately gated (`docs/superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md`). Re-purposing it for MRR (using similarity as an additional reranking signal on already-recalled candidates rather than a new recall route) is plausible but unvalidated — treat as a variant of the Tier-2 cross-encoder spike, not a separate priority. **Sizes:** bge-small-en-v1.5 is 33M params, ~127 MB fp32 ONNX / ~32-40 MB int8 (measured, <1% MTEB accuracy loss per Intel's PTQ study); gte-small/gte-tiny are comparable or smaller. **Dependency cost:** same onnxruntime footprint as above (~40-50 MB installed), plus the model file. **Determinism:** ONNX CPU inference with fixed execution providers is deterministic in practice (no dropout/sampling at inference), but is a materially larger surface to verify byte-determinism on than pure-Python arithmetic — treat as "deterministic with verification burden," not "free." |
| **Pure-Python (no onnxruntime) transformer inference** | Avoid the onnxruntime dependency entirely by hand-rolling matrix multiplication in `array`/stdlib | **Not realistic at usable latency.** A 6-22M-parameter transformer forward pass in pure Python (no NumPy, no BLAS) is 2-3 orders of magnitude slower than a vectorized implementation; even NumPy-only (no onnxruntime) reinstates a real dependency and still lacks fused/optimized kernels. If any embedding/cross-encoder route is built, `onnxruntime` (or at minimum NumPy) is the realistic floor — there is no free lunch here. State this plainly rather than chasing a zero-dependency dense-inference illusion. |

### What NOT to Use

| Avoid | Why | Use Instead |
|---|---|---|
| **ColBERT / ColBERTv2 / late-interaction retrieval** | Per-token embeddings require a specialized compressed index (residual quantization, k-means codebooks) — ColBERTv2 itself needs 16-25 GiB for MS MARCO-scale corpora even after 6-10x compression; even naively scaled down to 50K products it is architecturally a vector index, which the competition rules explicitly exclude ("no vector database"). It is also gross overkill for a catalog this size relative to the MRR gap being chased. | The SPLADE-frozen-weights or cross-encoder-rerank Tier 1/2 options above give comparable *rank-1 precision* mechanisms without a specialized ANN/quantized index. |
| **Runtime LLM-as-reranker (RankGPT, RankZephyr, pairwise/listwise/setwise LLM reranking, GPT-4/Claude reranking a candidate list per turn)** | Requires either a network call per turn (violates the "network may be disabled during scoring" hard constraint — no fallback means zero, not degraded) or a multi-GB local LLM (violates "no GPU," and CPU latency for even a 7B model reranking a list is far outside a conversational per-turn budget — RankZephyr is a 7B model built specifically because smaller listwise rerankers underperform). Also non-deterministic unless temperature=0 and the provider's inference is bit-exact, which is not guaranteed. | If LLM judgment is wanted for reranking-like signal, do it **offline** at build time (Tier 1 synonym/concept tables, or offline-computed per-product "salience" annotations folded into the frozen linear reranker's features) — never in the per-turn request path. |
| **Full SPLADE/dense encoder inference at query time** | Requires a transformer forward pass per turn on the query, which reinstates a real runtime ML dependency (onnxruntime at minimum) for a component whose main value (document-side term importance) can be captured entirely offline. | Distill SPLADE's *document-side* weights into the static `lexical_postings` table at build time (Tier 1); only spend the runtime dependency budget on cross-encoder rerank (Tier 2) if it's the highest-measured bake-off winner, and disclose the cost explicitly. |
| **Vector databases (FAISS, Qdrant, Milvus, pgvector, etc.)** | Explicitly out of scope by competition rules regardless of any performance argument. | Exact in-process matrix multiplication over a small (thousands-of-concepts, not 50K-products) NumPy array, as the existing gated spec already specifies — only if a dense route is built at all. |
| **LightGBM/XGBoost LambdaMART as a *runtime* dependency** | Unnecessary — pulls in a compiled library (tens of MB) to serve what amounts to a monotonic scoring function over a handful of engineered features, which a frozen linear/logistic model can approximate at effectively zero runtime cost. | Use LightGBM/scikit-learn only as a **build-time, dev-only** fitting tool (never imported by `starter/`), and bake the resulting coefficients as Python float constants, exactly like `_ROUTE_WEIGHTS` and `DEFAULT_BELIEF_CONFIGURATION` already are. |
| **RRF with an untuned k=60 treated as sacred** | It's a robust, tuning-free default from Cormack et al., not evidence that it's optimal here. The routes being fused (metadata/exact-FTS/expanded-FTS/category/counterfactual) are not "roughly equally trustworthy," which is RRF's core assumption — this project already overrides that assumption informally via `_ROUTE_WEIGHTS` layered on top of RRF ranks. | Move to properly normalized, dev-tuned weighted fusion (Tier 1) rather than layering more ad hoc weights on an algorithm whose whole premise is "don't need weights." |
| **doc2query's "Inject" behavior (adding unseen terms wholesale)** | Targets recall, which is documented as near-exhausted (+0.040 ceiling) and largely unrecoverable per `docs/STATUS.md`. Spending build-time LLM budget generating large volumes of injected terms optimizes the wrong term of the score. | Prefer the "Rewrite"/term-salience half of the same literature (Tier 1, folded into SPLADE-style postings weights). |

## Installation

```bash
# Tier 1 (stdlib-only, ships in the runtime environment) — no new packages.
# All Tier 1 techniques are implemented with modules already imported by the codebase
# (sqlite3, math, statistics, dataclasses) plus a build-time-only fitting step.

# Build-time-only tooling (never imported by starter/, not in the shipped
# requirements.txt / pyproject.toml dependencies list):
uv add --dev scikit-learn   # or lightgbm, only to fit reranker coefficients offline

# Tier 2 spike (if pursued) — a real runtime dependency, must be disclosed:
uv add onnxruntime          # ~16-25 MB wheel, ~40-50 MB installed w/ numpy+sympy
# tokenization: implement WordPiece in pure Python from the model's vocab.txt
# to avoid also pulling in the `tokenizers` package.
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|---|---|---|
| Hand-rolled frozen linear reranker | Full LambdaMART (LightGBM) shipped at runtime | Only if the linear model's ceiling is measured and clearly insufficient — unlikely with ~5-8 well-chosen features over a candidate list this size, and the dependency cost is real. |
| SPLADE weights distilled into legacy TF-IDF postings | Native SPLADE/learned-sparse query-time scoring engine | Only if this project ever drops the "zero runtime dependency" posture entirely and adopts a real sparse-retrieval library — not indicated by current constraints. |
| Tuned weighted fusion | Learned fusion (a small model over per-route scores) | If the number of routes/features grows enough that hand-tuning becomes unreliable; at 5 routes, direct tuning on a dev set is simpler and equally defensible. |
| Offline LLM concept/synonym table | Runtime paraphrase handling via LLM (Tier 2/3 per PROJECT.md) | Already the project's own stated ordering — Tier 1 preferred, Tier 2 only with a deterministic fallback. Consistent with this research. |
| ONNX cross-encoder Tier 2 spike | Skipping dense/cross-encoder entirely | If the Tier 1 candidates alone close enough of the MRR gap (0.5245 → close to the 0.920 ceiling) that the dependency/latency/determinism-verification cost of Tier 2 isn't justified — plausible given how much of the gap looks like fusion/question-policy-shaped, not "missing semantic signal." |

## Stack Patterns by Variant

**If the bake-off needs a zero-dependency, byte-deterministic candidate that can ship with full confidence in the Feasibility narrative:**
- Build only the Tier 1 set (frozen linear reranker, decision-theoretic question value, tuned fusion, expanded offline synonym table, SPLADE-distilled postings weights).
- These compose: they touch different pipeline stages (fusion → question selection → reranking → lexical scoring) and can be measured both individually and stacked.

**If the bake-off wants to measure the ceiling of a dependency-bearing approach before deciding whether it's worth the Feasibility-narrative cost:**
- Spike the ONNX cross-encoder rerank Tier 2 candidate in isolation, on a branch, with `onnxruntime` explicitly declared and disclosed, and report its MRR delta *and* its added latency *and* its dependency footprint side-by-side with the Tier 1 stack — so the tradeoff is an evidenced decision, not a default.

**If network access is available at build time but must be absent at scoring time (already the project's own model):**
- All LLM-authored assets (synonym tables, contrast sets, distillation targets for the reranker's features) are produced via the already-available Cloudflare Workers AI / Claude Opus-Sonnet build tooling, frozen, checksummed, and committed — never fetched again at runtime.

## Version Compatibility

| Package | Compatible With | Notes |
|---|---|---|
| `onnxruntime` (if Tier 2 pursued) | CPython 3.10+ (project already requires 3.10+) | Verify wheel availability for the target platform/arch (Windows verified environment here); CPU package only — never the GPU package, per hard constraint. |
| `cross-encoder/ms-marco-MiniLM-L6-v2` ONNX export | `onnxruntime` >= 1.15 (any recent CPU build; 1.29.0 was current as of Aug 2026) | Use a community ONNX export (e.g. Xenova's) or export directly via `optimum`/`sentence-transformers` at build time only. |
| `BAAI/bge-small-en-v1.5` ONNX export | Same onnxruntime constraint | int8 quantized variant (~32-40 MB) is the size-appropriate choice if this route is spiked; verify accuracy loss on this catalog's domain, not just MTEB, per the already-written domain-probe gate in the gated semantic spec. |
| Build-time `scikit-learn`/`lightgbm` | Any version; dev-only | Never imported by `starter/`; must not appear in the shipped `pyproject.toml` `dependencies` list, only (optionally) in a `[dev]` extra or a separate `tools/` requirements file. |

## Sources

- Cross-encoder vs. BM25 MRR figures — official `cross-encoder/ms-marco-MiniLM-L6-v2`
  model card (Hugging Face); CheckThat! 2025 applied reranking study (arXiv
  2507.06563); out-of-domain cross-encoder degradation study (HYRR, arXiv
  2212.10528) — MEDIUM-HIGH confidence, cross-checked across independent sources.
- doc2query / docTTTTTquery Rewrite-vs-Inject distinction — DeepImpact framework
  discussion (arXiv 2104.12016), Doc2Query++ (arXiv 2510.09557), original
  docTTTTTquery repo (`castorini/docTTTTTquery`) — MEDIUM confidence.
- SPLADE document-side-only design (`SPLADE-doc`) — SIGIR 2021 SPLADE paper (ACM
  DOI 10.1145/3404835.3463098), Two-Step SPLADE (arXiv 2404.13357), DF-FLOPS /
  pruning literature — MEDIUM confidence on the mechanism; LOW confidence on
  exact integration into a legacy TF-IDF postings table (nonstandard adaptation,
  not benchmarked in the literature as described).
- RankGPT/RankZephyr listwise LLM reranking, latency and model-size context —
  RankZephyr paper (arXiv 2312.02724), ICR (ICLR 2025), FIRST (arXiv 2406.15657),
  2025 empirical MRR-vs-latency analysis (arXiv 2508.16757 / ACL Findings 2025) —
  MEDIUM-HIGH confidence on qualitative conclusions (large models needed for
  competitive quality, meaningful per-query latency), used here to justify
  exclusion rather than adoption.
- RRF weaknesses and tuned-fusion evidence — Bruch et al. 2022 (convex
  combination vs. RRF), OpenSearch fusion benchmark (~3.86% NDCG delta),
  Cormack et al. RRF original k=60 tuning — MEDIUM-HIGH confidence, reproduced
  across independent sources (OpenSearch engineering blog + academic paper).
- Clarifying-question value beyond entropy — Rahmani et al., "Clarifying the
  path to user satisfaction" (Findings of ACL: EACL 2024); Chen, Sun, Arik,
  Pfister, "Learning to Clarify" (2024); Zamani et al., "Generating clarifying
  questions for information retrieval" (WWW 2020, foundational) — MEDIUM
  confidence; directional consensus, no number transfers to this system's MTTC
  without a dedicated measurement.
- ONNX Runtime CPU package footprint — PyPI `onnxruntime` listing, 2026 dev.to
  footprint analysis, official onnxruntime.ai build docs — HIGH confidence
  (official package metadata plus corroborating third-party measurement).
- bge-small-en-v1.5 / gte-small ONNX sizes and int8 quantization accuracy —
  Hugging Face model repos (`Teradata/bge-small-en-v1.5`, `Xenova/bge-small-en-v1.5`,
  `thenlper/gte-small`), Intel PTQ benchmarking article — MEDIUM-HIGH confidence
  (multiple independent conversions agree on size; accuracy-loss figure from a
  single vendor study).
- ColBERTv2 index size and late-interaction storage cost — ColBERTv2 paper
  (arXiv 2112.01488), PLAID engine paper (arXiv 2205.09707), Weaviate late-
  interaction overview — HIGH confidence (primary paper figures, corroborated).
- Existing system baselines and constraints — `.planning/PROJECT.md`,
  `.planning/codebase/STACK.md`, `.planning/codebase/ARCHITECTURE.md`,
  `docs/superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md`
  (read directly, not web-sourced).

---
*Stack research for: conversational product search reranking/fusion/clarification, MRR + MTTC focus*
*Researched: 2026-08-29*
