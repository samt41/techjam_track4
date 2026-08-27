# Track 4 Local Environment

Last verified: 28 August 2026 (Singapore time)

## Purpose

This document records the reproducible local setup for the official Track 4 participant repository. A teammate should be able to prepare the catalog, run the tests, and reproduce the published BM25 baseline using the commands below.

## Project design documents

- [Approved offline hybrid agent design](docs/superpowers/specs/2026-08-28-offline-hybrid-shopping-agent-design.md)
- [Deterministic offline agent implementation plan](docs/superpowers/plans/2026-08-28-deterministic-offline-agent-implementation.md)

## Verified repository state

- Repository: `TechJam2026/techjam-conversational-search`
- Revision: `34078351e1c3615e5505a2e829600b56a542e462`
- Revision message: `Clarify TechnicalScore judging role`
- Python verified locally: CPython 3.13.11 in a uv-managed `.venv`
- SQLite verified locally: 3.50.4 with FTS5 enabled
- Third-party Python packages required by the supplied baseline: none
- JavaScript/TypeScript components: none

The organizer recommends Python 3.10 or later. Python 3.13.11 successfully runs the current tests and evaluator.

## Important directories and files

| Location | Purpose |
|---|---|
| `starter/agent.py` | The participant-editable `Agent` implementation |
| `evaluator/local_evaluator.py` | Deterministic public evaluator; do not modify for reported results |
| `data/public_set.jsonl` | 200 labeled development sessions |
| `data/catalog.jsonl` | Decompressed 50,000-product catalog; downloaded separately and ignored by Git |
| `docs/agent_api_contract.json` | Machine-readable input/output contract |
| `docs/evaluation_config.json` | Turn limit, Top-K, metrics, and composite weights |
| `docs/submission_rules.md` | Packaging, offline/network, and reproducibility requirements |
| `results.json` | Generated evaluator output; ignored by Git |

## Minimum environment

Required:

- `uv`
- CPython 3.10 or newer
- A Python build whose `sqlite3` module includes SQLite FTS5
- Approximately 61 MB for the decompressed catalog, plus space for the in-memory FTS index and result files

Not required for the supplied baseline:

- GPU
- Node.js or a JavaScript package manager
- Docker
- An LLM or API key
- NumPy, pandas, PyTorch, Transformers, FAISS, or scikit-learn

If JavaScript or TypeScript is introduced later, use `pnpm`. There is currently no reason to add a JS/TS toolchain.

## Reproducible setup with uv

Create the environment:

```powershell
uv venv --python 3.13 .venv
```

Verify SQLite FTS5:

```powershell
uv run --python '.\.venv\Scripts\python.exe' python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE x USING fts5(body)'); print(sqlite3.sqlite_version)"
```

Download the official release assets from:

`https://github.com/TechJam2026/techjam-conversational-search/releases/tag/participant-kit`

Required asset:

- `catalog.jsonl.gz`
- Expected SHA-256: `07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8`

Decompress it to `data/catalog.jsonl`. The verified file contains 50,000 non-empty JSONL rows and is 60,546,327 bytes at this revision.

Run tests:

```powershell
uv run --python '.\.venv\Scripts\python.exe' python -m unittest -v
```

Run the baseline:

```powershell
uv run --python '.\.venv\Scripts\python.exe' python -m evaluator.local_evaluator
```

## Verified results

The current environment produced the following from all 200 public sessions:

| Metric | Actual | Organizer reference |
|---|---:|---:|
| Hit Rate@10 | 0.125 | 0.125 |
| MRR | 0.068034 | 0.068034 |
| MTTC | 9.81 | 9.81 |
| TechnicalScore | 0.10671 | 0.10671 |

All values match exactly. The full baseline took approximately 27.9 seconds on the current Windows machine, including catalog indexing and evaluation.

## Optional dependencies by implementation direction

Do not install these speculatively. Add only the packages required by the approach we implement, using `uv add` and a project manifest.

### Standard-library retrieval and dialogue state

Dependencies: none.

SQLite FTS5, `json`, `re`, and explicit Python state are sufficient for improving field weighting, query construction, constraint handling, and clarification strategy. This is the lowest-risk offline path.

### Classical vectorization or numerical reranking

Likely dependencies:

- `numpy`
- optionally `scikit-learn`

This supports TF-IDF, sparse features, learned/rule-based reranking, and efficient scoring without a model server.

### Dense retrieval or a local semantic reranker

Likely dependencies:

- `sentence-transformers`
- `torch`
- transitive Hugging Face/Transformers packages
- `numpy`

This path requires substantially more disk, installation time, RAM, and possibly a GPU. Model weights must be available in the final environment if network access is disabled. For only 50,000 products, a precomputed embedding matrix plus NumPy scoring may be simpler and more portable than FAISS.

### External LLM API

Possible dependency:

- a provider SDK, or a small HTTP client such as `httpx`

This must remain optional. The submission rules say final scoring may disable network access, so the agent needs a functional offline fallback and must document credentials, cost, latency, and token usage.

## Environment variables

The supplied baseline requires none.

If an external model is added, credentials must be supplied through environment variables and never committed. Keep provider-specific variables documented in the submission README and ensure the offline path works when they are absent.

## Constraints and known issues

- The catalog is not stored in Git and must be downloaded from the participant-kit release.
- Exact `parent_asin` equality is the only successful recommendation match.
- Only the first 10 unique, valid catalog IDs are scored.
- A session ends on a hit or after turn 10; misses are assigned turn 11 for MTTC.
- Intent Override sessions cannot convert before the override arrives.
- Exceptions, malformed responses, and timeouts can count as misses.
- Do not modify the evaluator or public labels when reporting results.
- Public development has only 200 sessions, so overfitting is a serious risk.
- Final evaluation uses 800 private sessions with different users and target products.
- Final scoring may impose unspecified CPU, RAM, timeout, and network restrictions.
- Code must not depend on undeclared external services.
- The supplied README uses Unix `gzip`/`mv` commands. On Windows, use an equivalent decompressor and place the resulting file at `data/catalog.jsonl`.
- In the managed Codex sandbox, uv needed escalated access to its user cache. This is an agent-environment restriction, not a repository requirement.

## Recommended initial implementation boundary

Keep the first improvement CPU-only and offline:

1. retain SQLite FTS5 retrieval;
2. add structured per-session constraints and override handling;
3. search accumulated conversation state rather than only the latest message;
4. introduce scenario-aware clarification;
5. add field-aware filtering/reranking; and
6. rerun the deterministic evaluator after each isolated change.

Only introduce NumPy, scikit-learn, embeddings, or an LLM after the standard-library improvements establish a stronger reproducible baseline.
