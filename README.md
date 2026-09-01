# Deterministic Offline Shopping Agent

This Track 4 submission is a headless Python shopping agent for the TechJam Conversational E-Commerce Search Challenge. It returns up to ten catalog products on every turn, optionally asks one focused clarification question, accumulates typed preferences across turns, and runs without a network connection, GPU, model server, or API credential.

The implementation is deterministic and standard-library-only at inference time. It uses catalog-derived metadata indexes, SQLite FTS5, reciprocal-rank fusion, hard eligibility checks, information-gain questions, slate rotation, and bounded leave-one-constraint-out exploration.

## Project description

Shopping requests rarely arrive fully formed. A shopper may begin with a broad category, add a budget or material, reject an attribute, correct an earlier answer, or change direction after seeing the first results. Treating every turn as an isolated keyword query loses that context and can surface products that contradict what the shopper just said.

This agent treats the conversation as structured, revisable state. It extracts typed constraints from each message, distinguishes hard requirements from soft preferences and exclusions, replaces conflicting values, and retains earlier details that still matter. Aggregate profile signals can personalize ranking without exposing raw user history. Shoppers can revise a request without restating every earlier detail.

On each turn, the agent searches the frozen 50,000-product catalog through both structured metadata indexes and SQLite FTS5. Reciprocal-rank fusion combines the retrieval routes, an eligibility gate removes products that violate hard constraints, and an auditable Bayesian score ranks the remaining candidates. The agent can ask the unanswered question with the highest expected information gain while still returning up to ten recommendations. It rotates previously shown products and, only when the strict result set is too small, fills the slate with clearly disclosed near matches that relax one non-exclusion constraint.

The full inference path runs locally on CPU and has deterministic tie-breaking by `parent_asin`. It needs no network connection, GPU, vector database, model server, API key, or paid model call. On the unchanged 200-session public evaluator, the retained run reaches 0.920 Hit Rate@10 and 0.5245 MRR, compared with 0.125 and 0.068034 for the organizer's BM25 baseline. These public results are development evidence; the private evaluation remains the final test of generalization.

### Development tools, APIs, libraries, and data

| Category | What this project uses |
| --- | --- |
| Development tools | CPython 3.11+, `uv` for environment and command management, Cursor for collaborative coding, Claude Code and Codex for AI-assisted ideation and execution, Git and GitHub for version control, Python's `unittest` for automated tests, and the organizer's unchanged local evaluator for end-to-end measurement. |
| APIs | The submission implements the organizer's local Python `Agent` contract: `reset` starts a session and `respond` returns the message, optional clarification attribute, ranked recommendations, and token counts. Catalog access uses Python's local `sqlite3` API. We prototyped live AI endpoints with Cloudflare Workers AI during development, but the submitted inference path calls no external web, commerce, or model API. |
| Libraries and frameworks | Inference uses only the Python standard library and SQLite FTS5. There are no third-party runtime packages, hosted frameworks, embedding models, or LLM dependencies. |
| Datasets and assets | The frozen catalog contains 50,000 products from the competition's `Clothing_Shoes_and_Jewelry` selection of the [Amazon Reviews 2023 dataset](https://amazon-reviews-2023.github.io/), published by McAuley Lab at UCSD. Development uses the organizer-provided 200-session public set with Buying, Browsing, Intent Override, and Boundary scenarios plus privacy-safe aggregate user profiles. The SQLite search artifact is built locally from that catalog. No external media, private labels, or model weights are used. See [DATA_ATTRIBUTION.md](DATA_ATTRIBUTION.md) for source and use notes. |

We used Claude Code and Codex during ideation and implementation. They helped us explore several candidate architectures in parallel and dig deeply into retrieval, ranking, conversation state, and evaluation. Not every experiment worked, but the failed and neutral results gave us useful clues about the approach we eventually retained. Cursor was our collaborative coding environment, and we also prototyped live AI endpoints with Cloudflare Workers AI. Those prototypes were development experiments only; the submitted agent remains fully offline, deterministic, and independent of external AI services at runtime.

## Demo video plan

The [Devpost video storyboard](docs/devpost_video_storyboard.md) provides a 13-slide, approximately 2:45 recording plan with on-screen copy, voiceover, architecture and state-flow diagrams, BM25 comparisons, test cases, measured results, failed experiments, and the complete unfinished GSD roadmap. It ends with a runnable Intent Override session from the released public set:

```powershell
uv run python -m experiments.demo_session --sample-id public_0003
```

The [expanded Devpost presenter script](docs/devpost_video_full_script.txt) contains the word-for-word narration for Samuel, Cervon, and Weichu, with clear cues for each slide change and the final terminal demo.

The demo harness uses the public label only to annotate the presentation result. The submitted `Agent` still receives exactly the same aggregate profile and customer messages as it does under the unchanged evaluator.

## Quick start

Requirements:

- `uv`
- CPython 3.11 or later. CPython 3.11 through 3.13 are verified.
- Python's SQLite build with FTS5 enabled.
- Approximately 61 MB for the decompressed catalog. Approximately 580 MB for the prebuilt artifact database. RAM for a memory-mapped read connection.

Create the environment and run the tests:

```powershell
uv sync
uv run python -m unittest -v
```

The suite is 772 tests and runs in a few seconds. It needs no catalog download because it builds tiny fixture catalogs in temporary directories.

### Get the catalog

Download `catalog.jsonl.gz` from the official participant-kit release. The compressed asset SHA-256 is:

```text
07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8
```

Decompress it into the repository's `data` directory as `catalog.jsonl`. The verified decompressed catalog has 50,000 non-empty rows, is 60,546,327 bytes, and has SHA-256:

```text
da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67
```

### Build the artifact once

The agent reads a prebuilt SQLite artifact, not the raw catalog, so build it once before any evaluation:

```powershell
uv run python -m starter.shopping_agent.build_catalog_artifacts --catalog data/catalog.jsonl --output data/catalog.artifacts
```

This writes `data/catalog.artifacts/catalog.sqlite3` and a manifest. It takes roughly 60 to 90 seconds and produces an approximately 580 MB database. The builder refuses to overwrite an existing artifact, so delete the directory first if you are rebuilding.

### Run the evaluator

Run the unchanged public evaluator against the full 200-session public set:

```powershell
uv run python -m evaluator.local_evaluator
```

Or run a reproducible experiment that also writes typed traces and miss attribution:

```powershell
uv run python -m experiments.run_public --run-id my-run
```

Run identifiers cannot overwrite an existing experiment. Generated run directories are ignored by Git.

## Runtime and resource consumption

- One-off artifact build: approximately 60 to 90 seconds, single-threaded, roughly 580 MB written to disk.
- Backend open at process start: approximately 45 milliseconds. The full-database hash is deliberately not recomputed on open. The catalog fingerprint and file sizes are checked instead.
- Full 200-session public evaluation: approximately 190 seconds of wall-clock on the reference machine, excluding the artifact build. Wall-clock varies with machine load. Outcomes do not.
- Per turn: one bounded SQL shortlist per route, product materialization capped at 5,000 candidates, and Bayesian scoring linear in that bounded pool. No per-turn allocation grows with conversation length.
- Memory: the read connection is memory-mapped with a 1 GiB map and a 128 MiB page cache. Materialized product records are cached for the life of the backend so rotation-overlapping candidates are not re-fetched.

## Where the outputs go

A successful experiment atomically creates one directory under `experiments/<run-id>/` containing exactly five files:

- `summary.json` has catalog and dataset hashes, aggregate and per-scenario metrics, token usage, and runtime.
- `sessions.jsonl` has one scored outcome per public session, annotated with its first miss reason.
- `failures.jsonl` has a typed miss attribution per missed session, naming the reason and the implicating constraint.
- `retrieval_routes.jsonl` has the seven fixed-field typed trace events emitted per turn.
- `ablation.md` is a compact human-readable summary with a miss-reason table.

`experiments/RUNS.md` records the retained best run per meaningful implementation class and the historical-versus-current metric split.

## Current results

The retained deterministic run on all 200 public sessions, current artifact engine:

| Metric | Deterministic agent | Organizer BM25 baseline |
| --- | ---: | ---: |
| Hit Rate@10 | 0.920 | 0.125 |
| MRR | 0.5245 | 0.068034 |
| MTTC | 3.425 | 9.81 |
| TechnicalScore | 0.7688 | 0.10671 |

Per-scenario Hit Rate@10 is 0.90 for Boundary, 0.95 for Browsing, 0.90 for Buying, and 0.90 for Intent Override.

Determinism is byte-verified. Two independent full evaluations produced identical aggregate metrics, all 200 per-session outcomes including first-hit turn, and all typed trace events, after excluding run identifiers, random internal session IDs, and measured timing.

## Architecture, as a query experiences it

The organizer calls one headless `Agent`. It exposes `reset`, which starts a session, and `respond`, which returns a message, an allowed `ask_attribute` or `null`, up to ten recommendations, and zero token usage for this local implementation. Everything below sits behind that boundary.

### Built once, offline, before any query arrives

1. The catalog is parsed and every text field is normalized with NFKC and case-folding, so later matching never depends on source casing or spacing.
2. Each product is projected into two representations. One is a structured `(attribute, value)` table, which is the exact boolean signal used for eligibility. The other is an FTS5 lexical index over title, categories, features, details, store, and description, which is the fuzzy relevance signal.
3. Materials are recovered from free text into the structured detail set. A material vocabulary is derived from the catalog's own structured material values, keeping single-token values seen on at least two products. Each product's feature phrases are then scanned by a head-noun rule. → a token is recovered only if it is the last word of its phrase and is in that vocabulary, so "100% leather" and "faux leather" both become leather, while "leather sole" and "leather lining" do not. Blends split on "and" and slashes so "100% leather and textile" contributes both materials. This runs before the structured rows and the stored record are written, so retrieval SQL, the eligibility gate, and the ranker all read one consistent material set.
4. A per-product quality prior is precomputed from ratings.
5. The completed artifact is validated and published atomically. → any fingerprint or size mismatch marks it unusable rather than partly trusted.

None of this happens again at query time.

### On process start, once per run

1. The backend opens the SQLite artifact read-only and memory-maps it.
2. It checks the catalog fingerprint and file sizes. → it refuses to open if either does not match, so a stale artifact cannot silently serve a different catalog.
3. It builds the constraint extractor's phrase gazetteer from catalog vocabulary. Each phrase is classified to exactly one attribute by document-frequency evidence. The free-text feature bucket is residual, a structured attribute wins when it clears a small frequency floor, and single-character, stop-word, and one-off junk values are dropped. This replaces hand-ordered attribute priority and a hand-maintained block list with a catalog-derived rule.

### On every query turn

1. The turn starts a timer and looks up the session. → it raises if the session was never reset, and raises if the agent was closed.
2. The message is classified into a dialogue act, such as a correction, an exclusion, a removal, a short answer, or a boundary decline.
3. The constraint extractor parses the message against the gazetteer, with scoped negation and typed confidence. → a verbose no-preference reply becomes a decline of the asked attribute rather than a literal value, and unmatched filler produces no constraint.
4. The updates are applied atomically to the typed preference ledger. A correction supersedes a conflicting scalar value instead of accumulating a contradiction. An override retracts the earlier provisional preference. → if the override adds a requirement on a different attribute, the earlier preference is kept as soft scoring evidence rather than discarded, so the discriminator that separates the target from an otherwise identical pool survives.
5. The ledger emits the new intent with an incremented version whenever the active constraint set changed.
6. Retrieval planning issues several routes that share one immutable hard-filter tuple. There is one structured route per soft attribute value, plus exact FTS, expanded FTS, and a category-quality route. The structured routes ensure a genuine leather item whose free text barely says "leather" is still retrieved.
7. Each route returns a bounded, ordered candidate list, and every route result is recorded as a typed retrieval trace.
8. The candidate pool is bounded to the top 5,000 by cheap evidence-only fusion before any product is materialized, so scoring never runs on an unbounded set.
9. The eligibility gate re-checks each candidate against the active hard constraints as defense. → a product that violates any hard requirement or exclusion is removed here, before ranking, and an exclusion is never relaxed.
10. Strict candidates are ranked by an auditable Bayesian posterior. Route evidence, soft-preference matches, and profile grounding contribute typed, logged terms combined through a stable softmax. The reserved quality-prior term is logged but neutral in the shipped configuration. Previously shown products within the current intent version sort last, which rotates the slate across turns.
11. The clarifying question is estimated from the full preliminary strict population, choosing the unanswered attribute that most reduces expected posterior entropy. This is computed before any tail fill, so the question sees the true spread rather than the final slate.
12. The slate is assembled. → on the common path the strict pool already fills all ten slots and no exploration runs. → only if the pool cannot fill the slate does counterfactual tail fill add disclosed near matches that each relax exactly one non-exclusion constraint, and the empty-pool case always triggers this last-resort fill regardless of configuration.
13. Response validation removes unknown or duplicate identifiers and discloses any relaxed requirement.
14. The shown set is recorded for the next turn's rotation, the asked attribute is remembered so it is not repeated, and seven typed diagnostic events for this turn are emitted: interpretation, retrieval, constraint, belief, question, slate, and runtime.
15. The turn returns a message, the allowed `ask_attribute` or `null`, and the validated recommendations.

After a run, a separate analyzer reads the traces and attributes every public miss to a typed reason, so failures are explained rather than merely counted.

## Design invariants

- Exact structured matching is the highest-authority signal. Hard constraints control eligibility and are enforced in SQL.
- Negation is explicit symbolic state, not a negative probability. "Not leather" excludes leather. It never selects an embedding opposite.
- Soft preferences route to the structured index for recall and feed the Bayesian ranking. They never gate eligibility.
- Recommendations are produced on every turn. Asking a question does not shrink the ten-product slate.
- The public evaluator and its labels are never modified.

## Hardcoded values and plan status

Every tuned constant and hardcoded choice in the code, with how principled each is, plus the state of each design document and what unbuilt work is gated on, is recorded in [docs/STATUS.md](docs/STATUS.md).

## Limitations and future work

- Retrieval combines structured attribute matching, lexical FTS5, and Bayesian ranking. No embeddings, local model, or LLM is used. A measured miss classification found zero of the current public misses to be vocabulary gaps, because the simulator speaks the target product's own catalog words. Open-vocabulary synonym resolution is therefore deferred and gated on evidence that a real gap exists, most plausibly on the private set. See the [semantic concept-retrieval design](docs/superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md).
- The remaining public misses are ranking-discrimination cases, where the target is retrieved into the pool but ranks below the slate among near-identical products. This, not vocabulary, is the current bottleneck.
- Public evaluation contains only 200 sessions. Private performance may differ, so tuning directly to individual public targets is avoided.
- Display-only prices, such as an em-dash placeholder or a "from" price, are treated as unknown so they cannot falsely satisfy a hard budget constraint.
- The catalog and the built artifact are large and are not committed to Git.

Given more time, the team would test the planned offline semantic fallback on independently authored paraphrases before deciding whether to ship it. The other priorities are ranking signals that can separate near-identical eligible products without target-specific tuning, broader multi-turn evaluation outside the public simulator's vocabulary, and a smaller artifact that keeps the same deterministic behavior. Every ranking change would still need paired evaluation and an explicit stable tie-break.

## Team member contributions

This project was completed collaboratively by:

- Cervon, contributor
- Samuel, contributor
- Weichu, contributor

## Competition contract

Only exact `parent_asin` equality counts as a hit. The evaluator scores the first ten valid unique identifiers, ends a session after a hit or after turn ten, and assigns turn eleven to misses for MTTC. The evaluator and public labels are not modified when reporting results.

Final aggregation happens over the 800 private sessions, which share no users and no targets with the public 200. Public results are a development signal, not the score.

The organizer allows optional external models, with teams supplying their own credentials and cost. This implementation deliberately avoids that dependency and reports zero prompt and completion tokens.

Organizer briefing material, including the benchmark's data lineage, the verified public/private disjointness, the suggested build path, and the named innovation directions, is transcribed in [docs/organizer_briefing.md](docs/organizer_briefing.md).
