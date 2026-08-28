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
3. retrieves candidates through exact metadata, exact FTS, expanded FTS, and category-quality routes;
4. rejects products that violate active hard constraints;
5. fuses route ranks and rotates previously rejected slates;
6. estimates which unanswered attribute would provide the most information;
7. returns ten valid unique product identifiers whenever the catalog permits; and
8. if the strict pool is too small, adds disclosed near matches that relax exactly one non-exclusion constraint.

Hard constraints control eligibility. Soft preferences and weighted concepts influence retrieval and ranking. Negation is explicit state, not a negative probability. Corrections supersede conflicting scalar values instead of accumulating contradictions.

The organizer-facing `Agent` interface remains unchanged: `reset` starts a session and `respond` returns a message, an allowed `ask_attribute` or `null`, recommendations, and zero token usage for this local implementation.

## Architecture

The organizer adapter delegates to a one-way turn coordinator. The domain is separated into focused components:

- the catalog index owns immutable normalized products, metadata vocabularies, cached quality order, and weighted SQLite FTS5;
- the constraint extractor performs deterministic, catalog-grounded parsing with scoped negation and typed confidence;
- the preference ledger owns active constraints, supersession history, declined questions, weighted concepts, and intent versions;
- retrieval planning and candidate generation define strict and counterfactual routes;
- the eligibility gate and ranker enforce hard requirements, fuse route evidence, rotate slates, and allocate strict versus exploratory results;
- the clarification estimator converts weighted catalog uncertainty into entropy, effective possibilities, and expected information gain;
- response validation removes unknown or duplicate identifiers and discloses any relaxed requirement; and
- typed diagnostic sinks record routes, filtering, fallback, questions, slates, and latency without arbitrary event payloads.

There is no frontend or middleware service in the current scope. A future interface can call the existing headless `Agent` boundary without changing search behavior.

## Retained public result

The retained deterministic run on all 200 public sessions produced:

| Metric | Deterministic agent | Organizer BM25 baseline |
| --- | ---: | ---: |
| Hit Rate@10 | 0.785 | 0.125 |
| MRR | 0.38656 | 0.068034 |
| MTTC | 4.43 | 9.81 |
| TechnicalScore | 0.639868 | 0.10671 |

Scenario Hit Rate@10 is 0.90 for Boundary, 0.9625 for Browsing, 0.8125 for Buying, and 0.20 for Intent Override. The retained instrumented evaluation took 185.492 seconds on the current Windows machine, excluding catalog construction; measured runtime varies between runs while outputs remain deterministic.

Two independent full evaluations produced identical canonical metrics, all 200 per-session outcomes, and all 843 ordered recommendation slates. Run identifiers, random internal session IDs, and measured timing were excluded from that comparison.

## Experiment artifacts

Each successful experiment atomically creates exactly five files:

- `summary.json`: hashes, aggregate and scenario metrics, token usage, and runtime;
- `sessions.jsonl`: one scored outcome per public session;
- `failures.jsonl`: only missed sessions;
- `retrieval_routes.jsonl`: fixed-field per-turn route, filtering, fallback, question, slate, and latency events; and
- `ablation.md`: a compact human-readable run summary.

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

- Retrieval is lexical and metadata-based. No embeddings, semantic clustering, local model, or LLM is implemented.
- Intent Override is the weakest public scenario and is the main target for future diagnostic work.
- Catalog metadata is noisy. Exact phrase matching filters unsafe stopword-like values, but unusual values can still be ambiguous.
- Display-only prices such as an em dash or `from 12.99` are treated as unknown so they cannot falsely satisfy a hard budget constraint.
- Sparse-pool counterfactual retrieval adds CPU time. It is gated off whenever strict eligibility can already fill the requested slate.
- Public evaluation contains only 200 sessions. Private performance may differ, so tuning directly to individual public targets should be avoided.
- The catalog is downloaded separately and is not committed to Git.

## Competition contract

Only exact `parent_asin` equality counts as a hit. The evaluator scores the first ten valid unique identifiers, ends a session after a hit or turn ten, and assigns turn eleven to misses for MTTC. Do not modify the evaluator or public labels when reporting results.

The organizer allows optional external models, but teams supply their own credentials and cost. This implementation deliberately avoids that dependency and reports zero prompt and completion tokens.
