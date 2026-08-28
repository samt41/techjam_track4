# Deterministic Offline Shopping Agent

This Track 4 submission is a headless Python shopping agent for the TechJam Conversational E-Commerce Search Challenge. It returns up to ten catalog products on every turn, optionally asks one focused clarification question, accumulates typed preferences across turns, and runs without a network connection, GPU, model server, or API credential.

The implementation is intentionally deterministic and standard-library-only. It uses catalog-derived metadata indexes, SQLite FTS5, reciprocal-rank fusion, hard eligibility checks, information-gain questions, slate rotation, and bounded leave-one-constraint-out exploration.

## Quick start

Requirements:

- `uv`
- CPython 3.10 or later; CPython 3.13.11 is verified
- Python's SQLite build with FTS5 enabled
- approximately 61 MB for the decompressed catalog, plus RAM for normalized records and an in-memory FTS index

Create the environment and run the tests:

```powershell
uv sync
uv run python -m unittest -v
```

Download `catalog.jsonl.gz` from the official participant-kit release. The compressed asset SHA-256 is:

```text
07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8
```

Decompress it into the repository's `data` directory as `catalog.jsonl`. The verified decompressed catalog has 50,000 non-empty rows, is 60,546,327 bytes, and has SHA-256:

```text
da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67
```

Run the unchanged public evaluator:

```powershell
uv run python -m evaluator.local_evaluator
```

Run a reproducible experiment with typed traces:

```powershell
uv run python -m experiments.run_public --run-id my-run
```

Run IDs cannot overwrite an existing experiment. Generated run directories are ignored by Git.

## Product behavior

On each turn the agent:

1. classifies corrections, exclusions, removals, short answers, and boundary replies;
2. applies updates atomically to a typed preference ledger;
3. retrieves candidates through **structured attribute-value routes** (products
   that actually carry each preferred value), exact FTS, expanded FTS, and
   category-quality routes, all sharing one hard-filter tuple;
4. rejects products that violate active hard constraints;
5. fuses route ranks and ranks strict candidates by an auditable Bayesian
   posterior, rotating previously shown products within an intent version;
6. estimates which unanswered attribute maximizes expected posterior entropy
   reduction over the full strict belief population;
7. returns ten valid unique product identifiers whenever the catalog permits; and
8. only if the strict pool cannot fill the slate, adds disclosed near matches
   that relax exactly one non-exclusion constraint (disabled by default; see below).

Hard constraints control eligibility and are enforced in SQL. Soft preferences
route to the structured index for recall and feed the Bayesian ranking. Negation
is explicit symbolic state, not a negative probability. Corrections supersede
conflicting scalar values instead of accumulating contradictions.

**Two catalog representations.** Each product is indexed both as **structured
attributes** (exact `(attribute, value)` rows — the boolean/eligibility signal)
and as **lexical text** (FTS5/bm25 — the fuzzy relevance signal). A soft
preference like "leather" routes to the structured index so a genuine leather
item whose free text barely mentions "leather" is still retrieved and ranked —
recovering the exact-match signal a purely lexical query buries.

**Happy path first, fallback only when needed.** The agent assumes the strict
pool fills all ten slots and runs no exploration on that common path. It falls
back to counterfactual near-match relaxation only when the strict pool cannot
fill the slate. On the full public set this fallback fired on 7 of ~1,500 turns —
every one a completely empty pool — so it functions purely as an empty-slate
guarantee, with byte-identical metrics to always-strict.

The organizer-facing `Agent` interface remains unchanged: `reset` starts a session and `respond` returns a message, an allowed `ask_attribute` or `null`, recommendations, and zero token usage for this local implementation.

## Architecture

The organizer adapter delegates to a one-way turn coordinator. The domain is separated into focused components:

- the catalog artifact is a prebuilt SQLite database with a structured
  `attributes` table, an FTS5 lexical index, and precomputed quality priors,
  loaded read-only behind a substitutable `ProductSearchBackend` boundary;
- the constraint extractor performs deterministic, catalog-grounded parsing with
  scoped negation and typed confidence;
- the preference ledger owns active constraints, supersession history, declined
  questions, weighted concepts, and intent versions;
- retrieval planning issues per-attribute structured-target routes plus lexical
  and quality routes sharing one immutable hard-filter tuple, and reliability-
  ordered counterfactual routes for tail fill;
- the eligibility gate re-checks hard requirements as defense, and the ranker
  fuses route evidence and orders strict candidates by an auditable Bayesian
  posterior (typed contributions, stable softmax) with unseen-before-shown
  rotation, filling only unused slots with near matches;
- the clarification model computes expected posterior entropy reduction over the
  bounded strict belief population;
- response validation removes unknown or duplicate identifiers and discloses any
  relaxed requirement; and
- seven typed diagnostic events per turn (interpretation, retrieval, constraint,
  belief, question, slate, runtime) record decisions without arbitrary payloads,
  and a post-run analyzer attributes every public miss to a typed reason.

There is no frontend or middleware service in the current scope. A future interface can call the existing headless `Agent` boundary without changing search behavior.

## Retained public result

The retained deterministic run on all 200 public sessions (current SQLite
artifact engine) produced:

| Metric | Deterministic agent | Organizer BM25 baseline |
| --- | ---: | ---: |
| Hit Rate@10 | 0.76 | 0.125 |
| MRR | 0.360109 | 0.068034 |
| MTTC | 4.94 | 9.81 |
| TechnicalScore | 0.609233 | 0.10671 |

Scenario Hit Rate@10 is 0.90 for Boundary, 0.9375 for Browsing, 0.775 for
Buying, and 0.20 for Intent Override. The retained evaluation took ~748 seconds
on the current Windows machine, excluding catalog construction; measured runtime
varies between runs while outputs remain deterministic.

Two independent full evaluations produced identical canonical metrics, all 200
per-session outcomes, and all 10,419 typed trace events. Run identifiers, random
internal session IDs, and measured timing were excluded from that comparison.

**Note on an earlier `0.785` figure.** Prior documentation quoted a HitRate@10 of
`0.785`. That number was measured on an earlier *in-memory* catalog engine that
the SQLite artifact backend replaced during the scalable-retrieval work. It is
**not reproducible** on the current engine and is not an acceptance target; see
`experiments/RUNS.md` for the historical-vs-current split. The current `0.76` is
the honest artifact-backed result and improves substantially on the
post-migration engine before the ranking-recall repair.

## Experiment artifacts

Each successful experiment atomically creates exactly five files:

- `summary.json`: hashes, aggregate and scenario metrics, token usage, and runtime;
- `sessions.jsonl`: one scored outcome per public session;
- `failures.jsonl`: typed miss attribution (reason + implicating constraint) per missed session;
- `retrieval_routes.jsonl`: the seven fixed-field per-turn typed trace events; and
- `ablation.md`: a compact human-readable run summary with a miss-reason table.

The retained-run table records accepted and rejected implementation classes. Old generated runs should be removed unless they remain the best evidence for a distinct class of change.

## Example conversation

This example was run against the full local catalog. Only the first three of ten recommendations are shown here.

```text
Customer: I need winter boots
Agent: Here are the strongest matches for your current preferences. Do you have a preferred brand?
ask_attribute: brand
Top products: B0BGQBLKY8, B0797W5MT4, B01FKMICPW

Customer: no preference
Agent: Here are the strongest matches for your current preferences.
ask_attribute: null
Top products: B09P5B5PT8, B09HHGMS9F, B08FFTK17T

Customer: black
Agent: Here are the strongest matches for your current preferences.
ask_attribute: null
Top products: B0BGQBLKY8, B07THG1SH7, B09P5B5PT8
```

The second turn records that brand should not be asked again and rotates the failed slate. The third turn adds a color preference, advances the intent version, and reranks from the updated state.

## Limitations

- Retrieval combines structured attribute matching with lexical FTS5 and a
  Bayesian ranking. No embeddings, semantic clustering, local model, or LLM is
  implemented; open-vocabulary synonym resolution (e.g. "warm" → "insulated") is
  deferred — see `docs/superpowers/specs/2026-08-28-semantic-constraint-extraction-design.md`.
- Intent Override is the weakest public scenario (HitRate@10 `0.20`) and remains
  the main target for future work.
- Catalog metadata is noisy — it contains junk single-word attribute values (a
  brand literally named "not", a color "m"). These are filtered by a stopword set
  and a small number of phrase rules that match the public evaluator's decline
  phrasing; that phrase-matching is a **known overfit to the 200-sample public
  set** and is slated to be replaced by document-frequency-gated, catalog-derived
  value filtering (see the spec above).
- The `OTHER`-residual constraint fallback is coupled to slate rotation (its
  intent-version bump drives the rotation scope); removing it naively regresses
  Buying, so the principled fix requires decoupling rotation first.
- Display-only prices such as an em dash or `from 12.99` are treated as unknown
  so they cannot falsely satisfy a hard budget constraint.
- Public evaluation contains only 200 sessions; private performance may differ,
  so tuning directly to individual public targets should be avoided.
- The catalog is downloaded separately and is not committed to Git.

## Competition contract

Only exact `parent_asin` equality counts as a hit. The evaluator scores the first ten valid unique identifiers, ends a session after a hit or turn ten, and assigns turn eleven to misses for MTTC. Do not modify the evaluator or public labels when reporting results.

The organizer allows optional external models, but teams supply their own credentials and cost. This implementation deliberately avoids that dependency and reports zero prompt and completion tokens.
