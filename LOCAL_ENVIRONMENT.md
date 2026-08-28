# Track 4 Local Environment

Last verified: 28 August 2026, Singapore time

## Purpose

This is the operational reference for preparing the Track 4 repository, verifying its offline deterministic agent, reproducing the retained public result, and locating generated diagnostics.

## Verified environment

- Windows PowerShell
- CPython 3.13.11 in a `uv`-managed `.venv`
- SQLite 3.50.4 with FTS5 enabled
- no third-party runtime packages
- no Node.js, frontend, middleware service, GPU, Docker, LLM, API key, or network service required

Python 3.10 or later is supported by the project metadata. If JavaScript or TypeScript is introduced for a later visualization, use `pnpm`; there is no current JS/TS component.

## Directory and artifact map

| Location | Purpose |
| --- | --- |
| `starter/agent.py` | Organizer-compatible adapter |
| `starter/shopping_agent/` | Typed parsing, ledger, retrieval, ranking, clarification, response, coordination, and diagnostics |
| `evaluator/local_evaluator.py` | Unchanged deterministic public evaluator |
| `data/public_set.jsonl` | 200 labeled development sessions |
| `data/catalog.jsonl` | Ignored decompressed 50,000-product catalog |
| `experiments/run_public.py` | Atomic reproducible experiment command |
| `experiments/RUNS.md` | Retained metrics, failures, constraints, and decisions |
| `experiments/<run-id>/` | Ignored five-file run artifact set |
| `docs/superpowers/specs/` | Approved architecture and behavior specification |
| `docs/superpowers/plans/` | Deterministic-core implementation plan |
| `results.json` | Ignored output of the organizer evaluator command |

## Setup with uv

From the repository root:

```powershell
uv sync
```

Verify FTS5:

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE x USING fts5(body)'); print(sqlite3.sqlite_version); c.close()"
```

Download `catalog.jsonl.gz` from the official participant-kit release. Verify the compressed asset:

```powershell
(Get-FileHash -Algorithm SHA256 .\catalog.jsonl.gz).Hash.ToLowerInvariant()
```

Expected compressed SHA-256:

```text
07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8
```

Decompress it as `data/catalog.jsonl`. The verified decompressed file has:

- 50,000 non-empty JSONL rows
- 60,546,327 bytes
- SHA-256 `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`

Verify it in PowerShell:

```powershell
(Get-FileHash -Algorithm SHA256 .\data\catalog.jsonl).Hash.ToLowerInvariant()
```

## Verification commands

Run the warning-strict unit suite:

```powershell
uv run python -W error::ResourceWarning -m unittest -v
```

Run the unchanged public evaluator:

```powershell
uv run python -m evaluator.local_evaluator
```

Run an instrumented experiment:

```powershell
uv run python -m experiments.run_public --run-id my-run
```

The experiment command refuses overwrite. A successful run contains only `summary.json`, `sessions.jsonl`, `failures.jsonl`, `retrieval_routes.jsonl`, and `ablation.md`.

## Retained result

The retained 200-session run reports:

| Metric | Value |
| --- | ---: |
| Hit Rate@10 | 0.785 |
| MRR | 0.38656 |
| MTTC | 4.43 |
| TechnicalScore | 0.639868 |
| Reported prompt/completion tokens | 0 / 0 |

Scenario Hit Rate@10:

| Boundary | Browsing | Buying | Intent Override |
| ---: | ---: | ---: | ---: |
| 0.90 | 0.9625 | 0.8125 | 0.20 |

The retained instrumented evaluator duration is 185.492 seconds, excluding one-time catalog construction. A second run took 126.485 seconds. Canonical metrics, all session outcomes, and all 843 ordered slates matched exactly; only timing and run/session identifiers differed.

## Runtime characteristics

- Catalog normalization, metadata indexes, cached quality order, and the in-memory FTS table are built once when `Agent` is constructed.
- Catalog startup is CPU and RAM work; no artifact or network lookup occurs.
- Phrase lookup is precomputed. The discarded per-value regex implementation exceeded a practical evaluator runtime.
- Quality fallback order is cached because repeated sorting of 50,000 products materially increased multi-run time.
- Leave-one-out counterfactual FTS routes run only when strict eligibility yields fewer than `top_k` products.
- JSONL tracing opens an append handle per event for simple failure isolation. It adds filesystem overhead only when the JSONL sink is explicitly enabled; the organizer adapter defaults to a no-op sink.

## Constraints and known failures

- Exact `parent_asin` equality is the only hit condition; only the first ten valid unique IDs are scored.
- Sessions end on a hit or after turn ten; misses use turn eleven for MTTC.
- Intent Override is the weakest retained scenario at 0.20 Hit Rate@10.
- Display-only prices (`—` and `from N`) normalize to unknown and cannot satisfy hard price constraints.
- Explicit exclusions are protected from counterfactual relaxation.
- The agent is lexical and metadata-based; semantic embeddings and feature clustering are not present.
- The public set has 200 sessions and the private set has 800, so public overfitting is a material risk.
- The catalog is ignored by Git and must be supplied before tests or evaluation that construct a full agent.
- Generated experiment directories are ignored. Retain only the best run for a meaningful change class and summarize it in `experiments/RUNS.md`.
- Do not modify the evaluator, public labels, or organizer contract when reporting a score.

## Offline verification rationale

The runtime dependency list is empty, and the agent imports only Python standard-library modules and local packages. It has no HTTP client, socket call, provider SDK, credential lookup, model download, semantic configuration, or GPU code path. Removing credentials or disabling network access does not change behavior.

## Design references

- [Approved offline hybrid agent design](docs/superpowers/specs/2026-08-28-offline-hybrid-shopping-agent-design.md)
- [Deterministic offline agent implementation plan](docs/superpowers/plans/2026-08-28-deterministic-offline-agent-implementation.md)
- [Retained experiment history](experiments/RUNS.md)
