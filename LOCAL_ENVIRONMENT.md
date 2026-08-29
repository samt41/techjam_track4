# Track 4 Local Environment

Last verified: 29 August 2026, Singapore time

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
| `starter/shopping_agent/build_catalog_artifacts.py` | One-off offline artifact builder |
| `evaluator/local_evaluator.py` | Unchanged deterministic public evaluator |
| `data/public_set.jsonl` | 200 labeled development sessions |
| `data/catalog.jsonl` | Ignored decompressed 50,000-product catalog |
| `data/catalog.artifacts/` | Ignored prebuilt SQLite artifact and manifest, what the agent actually reads |
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

## Build the catalog artifact

The agent reads a prebuilt SQLite artifact, not the raw catalog. Build it once
before any evaluation:

```powershell
uv run python -m starter.shopping_agent.build_catalog_artifacts --catalog data/catalog.jsonl --output data/catalog.artifacts
```

This writes `data/catalog.artifacts/catalog.sqlite3` plus a manifest, takes
roughly 60 to 90 seconds, and produces an approximately 580 MB database. The
builder refuses to overwrite an existing artifact, so delete the directory first
when rebuilding.

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

The retained 200-session run (current SQLite artifact engine, `--exploration
disabled`) reports:

| Metric | Value |
| --- | ---: |
| Hit Rate@10 | 0.920 |
| MRR | 0.5245 |
| MTTC | 3.425 |
| TechnicalScore | 0.7688 |
| Reported prompt/completion tokens | 0 / 0 |

Scenario Hit Rate@10:

| Boundary | Browsing | Buying | Intent Override |
| ---: | ---: | ---: | ---: |
| 0.90 | 0.95 | 0.90 | 0.90 |

The retained evaluator duration is ~190 seconds on the reference machine,
excluding the one-time artifact build. Determinism is byte-verified: two
independent full runs matched exactly on the canonical summary, all 200
per-session outcomes including first-hit turn, and all typed trace events; only
timing and run/session identifiers differed. Wall-clock varies widely with
machine load, so runtime is not a comparison axis.

An earlier `0.785` figure was measured on the pre-SQLite in-memory engine and is
not reproducible on the current backend; it is not an acceptance target. See
`experiments/RUNS.md` for the historical-vs-current split.

## Runtime characteristics

- All catalog parsing, normalization, structured-attribute projection, material and keyed-feature recovery, quality priors, and the FTS5 index are built once by the offline artifact builder, not at process start.
- Backend open memory-maps the prebuilt SQLite artifact and validates the catalog fingerprint and file sizes. It deliberately does not re-hash the ~580 MB database, so measured startup is ~45 ms.
- The read connection uses a 1 GiB memory map and a 128 MiB page cache. Materialized product records are cached for the life of the backend, so rotation-overlapping candidates are not re-fetched across turns.
- Per turn: one bounded SQL shortlist per route (route limit 1,000), candidate materialization capped at 5,000, and belief scoring linear in that bounded pool. No per-turn allocation grows with conversation length.
- Phrase lookup is precomputed. The discarded per-value regex implementation exceeded a practical evaluator runtime.
- Leave-one-out counterfactual FTS routes run only when strict eligibility yields fewer than `top_k` products, and by default only when that pool is empty.
- Continuous `tracemalloc` tracking is off by default; it dominated traced-run time and is diagnostic-only.
- JSONL tracing opens an append handle per event for simple failure isolation. It adds filesystem overhead only when the JSONL sink is explicitly enabled; the organizer adapter defaults to a no-op sink.

## Constraints and known failures

- Exact `parent_asin` equality is the only hit condition; only the first ten valid unique IDs are scored.
- Sessions end on a hit or after turn ten; misses use turn eleven for MTTC.
- Scenario Hit Rate@10 is now level at 0.90 for Boundary, Buying, and Intent Override, with Browsing at 0.95. Intent Override was the weakest scenario at 0.20 until a retrieve-then-reject bug was fixed, where a canonicalized material reached retrieval SQL but not the eligibility gate.
- The remaining 16 public misses are ranking-discrimination cases, not vocabulary gaps. Two independent miss classifications found zero vocabulary gaps, because the simulator builds the customer's words from the target product's own catalog strings. See `docs/STATUS.md` for the contribution-level diagnosis.
- Display-only prices (`—` and `from N`) normalize to unknown and cannot satisfy hard price constraints.
- Explicit exclusions are protected from counterfactual relaxation.
- The agent is lexical and metadata-based; semantic embeddings and feature clustering are not present. The offline embedding route is specified but deliberately not built, gated on evidence of a real vocabulary gap.
- The public set has 200 sessions and the private set has 800, so public overfitting is a material risk.
- The catalog is ignored by Git and must be supplied before tests or evaluation that construct a full agent.
- Generated experiment directories are ignored. Retain only the best run for a meaningful change class and summarize it in `experiments/RUNS.md`.
- Do not modify the evaluator, public labels, or organizer contract when reporting a score.

## Offline verification rationale

The runtime dependency list is empty, and the agent imports only Python standard-library modules and local packages. It has no HTTP client, socket call, provider SDK, credential lookup, model download, semantic configuration, or GPU code path. Removing credentials or disabling network access does not change behavior.

## Design references

- [Project status: hardcoded values and plan states](docs/STATUS.md)
- [Organizer briefing notes](docs/organizer_briefing.md)
- [Approved offline hybrid agent design](docs/superpowers/specs/2026-08-28-offline-hybrid-shopping-agent-design.md)
- [Scalable retrieval and oversight design](docs/superpowers/specs/2026-08-28-scalable-retrieval-and-oversight-design.md)
- [Deterministic offline agent implementation plan](docs/superpowers/plans/2026-08-28-deterministic-offline-agent-implementation.md)
- [Retained experiment history](experiments/RUNS.md)
