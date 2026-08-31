<!-- GSD:project-start source:PROJECT.md -->

## Project

**TechJam Track 4 — Conversational Shopping Agent**

A multi-turn conversational shopping agent for the TechJam 2026 Conversational
E-Commerce Search Challenge (Track 4). It talks to a simulated customer, keeps
structured state about what they want, asks clarifying questions, and returns up
to ten ranked `parent_asin` values from a frozen 50,000-product Amazon
Clothing/Shoes/Jewelry catalog. A hidden target product is scored on exact match.

An agent already exists and works: deterministic, zero runtime dependencies,
stdlib + SQLite/FTS5 only, scoring HR@10 `0.920` / TechnicalScore `0.7688` on
the 200 public sessions. **This milestone is not about building an agent. It is
about winning a hackathon** — which, per the judging rubric, is a materially
different objective from maximizing the retrieval metric.

**Core Value:** **Maximize total rubric score, not HitRate@10.**

**Winning Prompt:** This project will be the winner of TikTok Tech Jam 2026
because it has the best potential to score the best across the full judging
criteria: Technical Execution, Innovation & Problem Insight, Impact &
Relevance, Feasibility & Practicality, and Presentation & Communication.

Use that as an operating prompt, not a slogan. Every change should make the
submission stronger against at least one criterion without weakening the
organizer-scored agent contract.

Two measurements drive every prioritization call in this project:

1. **TechnicalScore is evidence feeding one criterion of five.** Technical
   Execution is 35%, and the competition specification states explicitly that
   TechnicalScore "does not represent the entire Technical Execution score." 65%
   of the outcome does not touch the retrieval metric at all.

2. **Within the metric, recall is nearly exhausted and ranking is not.** MRR and
   Efficiency are both bounded above by HR@10, so at current recall every term
   ceilings at `0.920`. See the headroom decomposition in Context. Roughly
   **0.151 points sit in ranking and speed; 0.040 sit in recall**, and the
   project's own `docs/STATUS.md` documents most of that 0.040 as unrecoverable
   under-specification.

When a tradeoff arises, prefer the change that moves more rubric points per unit
of effort — which is usually *not* the change that moves HR@10.

### Rubric Targets

- **Technical Execution:** preserve the offline, deterministic, well-structured
  Python agent; improve private-set potential through HR@10, MRR, Efficiency,
  reliability, latency, and clean architecture.
- **Innovation & Problem Insight:** make the problem framing sharp: multi-turn
  shopping is about state, constraint replacement, adaptive clarification,
  scenario routing, and ranked retrieval under hidden intent.
- **Impact & Relevance:** show why the system matters beyond the benchmark:
  lower-friction product discovery, safer personalization from aggregate
  profiles, and transparent recommendation behavior.
- **Feasibility & Practicality:** keep the solution reproducible,
  CPU-friendly, dependency-light, low-cost, and robust when network access or
  credentials are unavailable.
- **Presentation & Communication:** maintain a judge-ready README, short report,
  cost/latency/model disclosure, limitation notes, and one demonstrated
  multi-turn session.

### Constraints

- **Evaluator immutability**: `evaluator/local_evaluator.py` is never modified —
  results reported against a modified evaluator are invalid.

- **Runtime purity**: the shipped agent is stdlib-only, offline-capable, and
  byte-deterministic. LLM contributions reach it as frozen assets, not live
  calls, unless a deterministic fallback sits underneath.

- **Network**: may be disabled during official scoring — an agent that cannot
  run without credentials scores zero.

- **Determinism**: preferred but not absolute. A non-deterministic candidate may
  be *spiked* to measure headroom; shipping one is a deliberate, evidenced
  decision, not a default.

- **Tech stack**: Python 3.10+, `uv`, CPython SQLite with FTS5 (graceful TF-IDF
  fallback verified). No GPU, no model server, no vector database.

- **Timeline**: 2+ weeks — room for a genuine multi-candidate bake-off.
- **Team**: solo. Contributions section is trivial; phases can sequence freely
  without ownership boundaries.

- **LLM access**: Cloudflare Workers AI (open-source models — GLM, DeepSeek and
  similar) for high-volume mechanical passes; Claude Opus/Sonnet subagents for
  judgment-heavy, moderate-volume work. Credentials supplied when needed.

- **Disk/compute**: ~61 MB catalog plus ~580 MB artifact, neither committed. Full
  public evaluation ~190 s on the reference machine.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python 3.10+ (CPython 3.13.11 verified) — the entire repository. Agent (`starter/`), evaluator (`evaluator/`), experiment harness (`experiments/`), tests (`tests/`).
- SQL (SQLite dialect, including FTS5 `MATCH` queries) — embedded in `starter/shopping_agent/catalog_artifacts.py` (build-time DDL/DML) and `starter/shopping_agent/local_search_backend.py` (query-time retrieval SQL).
- PowerShell — used only for documented operator commands in `README.md` and `LOCAL_ENVIRONMENT.md`. No `.ps1` scripts are committed.
- Markdown / JSON / JSONL — documentation, contracts, datasets, and run artifacts.

## Runtime

- CPython, `requires-python = ">=3.10"` (`pyproject.toml`).
- Verified: CPython 3.13.11 inside a `uv`-managed `.venv` on Windows PowerShell.
- Hard runtime requirement: the CPython build's bundled SQLite must have **FTS5 enabled**. Verified against SQLite 3.50.4. The check command is in `LOCAL_ENVIRONMENT.md` lines 47-49.
- Graceful degradation exists: `CatalogArtifactBuilder(fts5_enabled=...)` and `LexicalMode` (`starter/shopping_agent/search_backend.py`, default `LexicalMode.AUTO` in `starter/agent.py`) allow a non-FTS5 path, and the manifest records `fts5_built`.
- `uv` (`uv sync`). Lockfile `uv.lock` is present and committed — 8 lines, lock `version = 1`, `revision = 3`, and exactly one package entry: the virtual root project itself (`source = { virtual = "." }`). There are no third-party packages to resolve.

## Frameworks

- None. There is no web framework, ORM, retrieval library, or ML framework. Storage and search are hand-written over the standard-library `sqlite3` module.
- `unittest` (standard library). No pytest, no plugins. 167 tests, run via `uv run python -m unittest -v`, or warning-strict via `uv run python -W error::ResourceWarning -m unittest -v`. Shared fixture builders live in `tests/fixtures.py` and construct tiny catalogs in temporary directories, so the suite needs no catalog download.
- `starter/shopping_agent/build_catalog_artifacts.py` — the one-off offline artifact builder CLI (`--catalog`, `--output`, both required).
- `evaluator/local_evaluator.py` — the unchanged organizer evaluator CLI (`--catalog` default `data/catalog.jsonl`, `--dataset` default `data/public_set.jsonl`, `--output` default `results.json`).
- `experiments/run_public.py` — the reproducible experiment CLI (`--run-id` required, `--catalog`, `--dataset`, `--output-root` default `experiments`, `--exploration` default `disabled`, plus a `--...` mode defaulting to `auto`).
- `experiments/analyze_public.py` and `experiments/analyze_misses_b1.py` — post-run trace analysis and typed miss attribution.
- No linter, formatter, type-checker, pre-commit hook, Makefile, Dockerfile, or CI workflow is committed.

## Key Dependencies

- **Zero declared runtime dependencies.** `pyproject.toml` has `dependencies = []`. This is a deliberate competition posture, not an oversight (`LOCAL_ENVIRONMENT.md`, "Offline verification rationale").
- `sqlite3` — the entire storage and retrieval engine, including the FTS5 virtual table.
- `json`, `pathlib`, `dataclasses`, `enum` (`StrEnum`), `typing` (`Protocol`, `Union`) — typed models and artifact/manifest serialization (`starter/shopping_agent/models.py`, `catalog_artifacts.py`).
- `re`, `unicodedata`, `collections` (`Counter`, `defaultdict`), `math`, `statistics` — normalization, gazetteer construction, and scoring (`starter/shopping_agent/text_normalization.py`, `constraint_extractor.py`, `belief.py`, `ranking.py`).
- `hashlib` — catalog and database SHA-256 fingerprinting (`experiments/run_public.py`, `catalog_artifacts.py`).
- `argparse`, `sys`, `os`, `io`, `shutil`, `tempfile`, `contextlib`, `subprocess` — CLIs, atomic publish, and test harness plumbing.
- `time` (`perf_counter`), `tracemalloc`, `resource` — runtime and memory diagnostics; continuous `tracemalloc` tracking is off by default because it dominated traced-run time.
- `random`, `uuid` — internal session identifiers only; never used for ranking decisions, which is why determinism is byte-verifiable.
- `unittest`, `unittest.mock.patch` — tests.
- None external. The only "infrastructure" is the local file `data/catalog.artifacts/catalog.sqlite3`.

## Configuration

- **No environment variables are read anywhere.** A repository-wide grep for `os.environ` and `getenv` across `starter/`, `evaluator/`, and `experiments/` returns nothing. There are no API keys, credentials, or provider settings.
- `.env` is listed in `.gitignore` as a precaution; no `.env` file exists and nothing would read it.
- All configuration is either a CLI flag or a typed dataclass default in code.
- `DEFAULT_BELIEF_CONFIGURATION` (`starter/shopping_agent/belief.py`) — `route_scale=0.60`, `soft_match_likelihood=0.80`, `soft_mismatch_likelihood=0.12`, `unknown_likelihood=0.40`, `feature_likelihood=0.55`, `profile_cap=0.35`, `quality_cap=0.40`, `temperature=1.0`. `quality_cap` is present but neutralized (a `0.0` quality prior is threaded in).
- `_ROUTE_WEIGHTS` (`starter/shopping_agent/retrieval.py`) — metadata 1.40, exact FTS 1.20, expanded FTS 0.80, category fallback 0.25, counterfactual 0.15; route limit 1,000.
- `QuestionModelConfiguration` (`starter/shopping_agent/clarification.py`) — population cap 64.
- Caps: ranker population 5,000 (`ranking.py`), belief trace 20 (`coordinator.py`).
- Extractor floors: `_STRUCTURED_DF_FLOOR = 2`, `STOPWORDS` (`constraint_extractor.py`, public since D-54 because `arena/datasets/divergence.py` consumes it); `_MATERIAL_VOCAB_FLOOR = 2`, `_KEYED_VALUE_FLOOR = 2`, `_KEYED_VALUE_MAX_TOKENS = 4`, `_KEYED_VALUE_MAX_LENGTH = 25` (`catalog_artifacts.py`).
- Full audit of every tuned constant, with how principled each is: `docs/STATUS.md`.
- `pyproject.toml` — five lines: project name `techjam-track4-agent`, version `0.1.0`, `requires-python`, empty dependencies. No build backend, no tool sections.
- `data/catalog.artifacts/manifest.json` — the generated build configuration record: `schema_version: 1` (matching `ARTIFACT_SCHEMA_VERSION` in `catalog_artifacts.py`), `catalog_sha256`, `catalog_size_bytes`, `database_sha256`, `database_size_bytes`, `product_count: 50000`, `lexical_term_count: 101291`, `fts5_built: true`, `fts_tokenizer: "unicode61-remove-diacritics-2"`, `normalization_version: "nfkc-casefold-v1"`, `posting_batch_size: 1000`, and the FTS field weights (title 6.0, category 4.0, feature 2.5, details 2.5, store 1.5, description 1.0).
- Read path (lines 283-289): `query_only = ON`, `mmap_size = 1073741824` (1 GiB), `cache_size = -131072` (128 MiB page cache), `temp_store = MEMORY`.
- Build path (lines 442-443): `journal_mode = DELETE`, `synchronous = FULL`.

## Platform Requirements

- `uv` on PATH; CPython 3.10+ with FTS5-enabled SQLite.
- Disk: ~61 MB decompressed catalog (`data/catalog.jsonl`, 60,546,327 bytes) plus ~580 MB artifact (`data/catalog.artifacts/catalog.sqlite3`, 581,844,992 bytes on disk). Neither is committed; both are `.gitignore`d.
- RAM sufficient for a 1 GiB memory map plus a 128 MiB page cache.
- Verified on Windows 11 / PowerShell. Nothing in the code is OS-specific; paths go through `pathlib`.
- There is no deployment target. The organizer's evaluator imports `starter.agent.Agent` locally in-process. `docs/organizer_briefing.md` states plainly: "The evaluator imports the submission locally. There is no URL and no fixed port." No hosted service, container, GPU, model server, or port is required.
- One-off artifact build: ~60-90 s, single-threaded, ~580 MB written.
- Backend open: ~45 ms (the 580 MB database is deliberately not re-hashed on open; catalog fingerprint and file sizes are checked instead).
- Full 200-session public evaluation: ~190 s wall-clock on the reference machine, excluding the build.
- Reported prompt/completion tokens: 0 / 0.

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- `snake_case.py`, one module per responsibility, no plural package names.
- Test modules mirror the module under test with a `test_` prefix:
- Executable entry points are runnable modules invoked with `python -m`:
- `snake_case`, verb-led for actions (`normalize_text`, `analyze_session`,
- A leading underscore marks a module-private helper and is used heavily:
- `snake_case`, spelled out in full. The codebase avoids abbreviations:
- Units are in the name: `startup_ms`, `elapsed_seconds`,
- Module-level constants are `UPPER_SNAKE`. Public ones carry no underscore
- Compiled regexes always end in `_RE`: `_VERBOSE_DECLINE_RE`,
- `PascalCase` classes. Domain value objects are named for the concept
- Private dataclasses used only inside a module take the underscore prefix:

## Code Style

- No formatter is configured. Written in a Black-compatible style at a
- Multi-line calls and literals use a trailing comma and one argument per
- Every module begins with `from __future__ import annotations` as the first
- Two blank lines separate top-level definitions; module constants are
- Full annotations on every function signature and return, including `-> None`
- Keyword-only parameters are marked with a bare `*` when a call site would
- All domain types are `@dataclass(frozen=True, slots=True)`. See the whole of
- Enumerations are `StrEnum` with `UPPER_SNAKE` members and lowercase string
- Sequences that cross a module boundary are `tuple[...]`, not `list`. Lists
- Validation lives on the dataclass as a `validate()` method that raises
- Any iteration that affects output must be ordered. Dicts are dumped with
- Ties are broken on a stable key, never left to insertion order. The belief
- Randomness is always seeded from stable content, never from the clock:
- De-duplication preserves order via `dict.fromkeys`, not `set`

## Import Organization

- Always absolute from the repository root (`from starter.shopping_agent.models
- No path aliases and no barrel files. `starter/__init__.py`,
- Multi-name imports are parenthesized one-per-line with a trailing comma

## Error Handling

- Raise a domain exception with a lowercase, specific message. The artifact
- Chain the cause with `raise ... from error` whenever wrapping a lower-level
- `ValueError` for contract violations on typed values
- Fail closed on corruption. A fingerprint or size mismatch marks the artifact
- Validate untrusted input at the boundary before use:
- Broad `except Exception` appears exactly once, in the unmodified evaluator
- Platform quirks are handled explicitly and documented in a docstring rather

## Logging

- The CLI builder prints `key=value` lines to stdout and errors to stderr
- Observability is structured, not textual. `starter/shopping_agent/diagnostics.py`
- Tracing is injected, never global: `Agent(..., trace=JsonlEvaluationTrace(path))`.

## Comments

- Comment the *why*, never the *what*. Every comment in the codebase explains a
- Reserve comments for: an overfit or hardcoded choice being flagged as debt
- Sparse and load-bearing. Most modules have zero or one; `belief.py`,
- When present, a docstring is a one-line summary, then a blank line, then
- No parameter/return/raises sections. No reStructuredText or Google-style

## Function Design

## Module Design

## Documentation and Experiment-Logging Conventions

## Hard Invariants

- Never modify `evaluator/local_evaluator.py` or the public labels. It is the
- Ground truth must never reach the `Agent`. `_SessionMappingAgent`
- Inference is standard-library-only and offline. No new runtime dependency,
- Negation is symbolic state, never a negative weight. An exclusion is never
- Output must be byte-reproducible across runs, excluding run ids, evaluator

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text

```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `Agent` | Organizer-facing adapter; opens backend, maps dict payloads to typed models | `starter/agent.py` |
| `TurnCoordinator` | Single-turn orchestration and session state; emits all seven trace events | `starter/shopping_agent/coordinator.py` |
| `ConstraintExtractor` | Dialogue-act classification and catalog-gazetteer constraint parsing | `starter/shopping_agent/constraint_extractor.py` |
| `PreferenceLedger` | Typed constraint accumulation, correction/override/removal, intent versioning | `starter/shopping_agent/preference_ledger.py` |
| `RetrievalPlanner` | Builds the multi-route `SearchRequest` plan sharing one hard-filter tuple | `starter/shopping_agent/retrieval.py` |
| `LocalProductSearchBackend` | SQL execution: structured, FTS5, TF-IDF fallback, quality routes; product materialization + cache | `starter/shopping_agent/local_search_backend.py` |
| `EligibilityGate` | Re-checks each materialized candidate against hard constraints | `starter/shopping_agent/ranking.py` |
| `ProductRanker` | Evidence fusion, population bounding, eligibility, soft scoring, ordering | `starter/shopping_agent/ranking.py` |
| `CandidateBeliefModel` | Auditable Bayesian posterior with typed log contributions | `starter/shopping_agent/belief.py` |
| `PosteriorQuestionModel` / `ClarificationPolicy` | Expected-entropy-reduction attribute choice and ask/skip decision | `starter/shopping_agent/clarification.py` |
| `ResponseValidator` | Drops unknown/duplicate ids, caps slate, discloses relaxations | `starter/shopping_agent/response.py` |
| `CatalogArtifactBuilder` | Offline artifact build, material/keyed-feature recovery, FTS weighting, atomic publish | `starter/shopping_agent/catalog_artifacts.py` |
| `CatalogIndex` | Thin catalog-vocabulary facade over the backend (facets, value counts) | `starter/shopping_agent/catalog_index.py` |
| Diagnostics | Typed trace event records and JSONL sink | `starter/shopping_agent/diagnostics.py` |

## Pattern Overview

- Offline precomputation is separated from query time. Nothing in `catalog_artifacts.py` runs during a turn.
- Storage is abstracted by the `ProductSearchBackend` Protocol (`search_backend.py:212`); the agent never touches `sqlite3` directly.
- Every stage is a pure-ish transform over frozen dataclasses in `models.py`; state lives only in `_SessionState` inside the coordinator.
- Determinism is a hard invariant: all sorts carry `parent_asin` as a final tie-break, and traces are byte-comparable across runs.
- Diagnostics are a first-class output, not logging: seven fixed-schema typed events per turn.

## Layers

- Purpose: harness integration and payload marshalling
- Location: `starter/agent.py`, `evaluator/local_evaluator.py`, `experiments/run_public.py`
- Contains: `Agent`, `_profile_from_payload`, `_SessionMappingAgent`
- Depends on: coordinator, response, diagnostics
- Used by: the organizer harness
- Purpose: sequence one turn, own session state, emit traces
- Location: `starter/shopping_agent/coordinator.py`
- Contains: `TurnCoordinator`, `_SessionState`
- Depends on: every domain module
- Used by: `Agent`
- Purpose: constraint understanding, retrieval planning, eligibility, ranking, questioning
- Location: `constraint_extractor.py`, `preference_ledger.py`, `retrieval.py`, `ranking.py`, `belief.py`, `clarification.py`, `response.py`
- Depends on: `models.py`, `search_backend.py` (types only), `text_normalization.py`
- Used by: the coordinator
- Purpose: bounded SQL shortlists and product materialization
- Location: `search_backend.py` (port), `local_search_backend.py` (adapter), `catalog_index.py` (vocabulary facade)
- Depends on: `sqlite3`, the built artifact
- Used by: planner execution, ranker, validator, extractor gazetteer
- Purpose: one-off artifact construction and validation
- Location: `catalog_artifacts.py`, `build_catalog_artifacts.py`
- Used by: CLI only, never at query time
- Purpose: post-run miss attribution over the typed traces
- Location: `experiments/analyze_public.py`, `experiments/analyze_misses_b1.py`
- Used by: `run_public.py`

## Data Flow

### Primary Request Path — one query end to end

### Offline Build Flow

### Process-Start Flow

- All mutable state is per-session in `_SessionState` (`coordinator.py:57`): profile, `PreferenceLedger`, `RecommendationHistory`, `last_asked_attribute`, `turn_history`.
- `ProductRanker._scored_cache` is a single-entry, identity-keyed memo that deliberately retains its key objects to avoid `id()` reuse (`ranking.py:154`).

## Key Abstractions

- Purpose: the storage port — `search`, `facets`, `get_products`, `contains_product`, `catalog_fingerprint`, `close`
- Examples: `starter/shopping_agent/search_backend.py:212`, implemented by `local_search_backend.py:47`
- Pattern: structural typing; tests substitute fakes without SQLite
- Purpose: the versioned typed constraint set that every downstream stage reads
- Examples: `starter/shopping_agent/models.py:96`, `models.py:155`
- Pattern: frozen slotted dataclasses with `validate()`
- Purpose: attribute retrieval provenance to each candidate so fusion and traces can explain it
- Examples: `models.py:63`, `models.py:183`
- Purpose: one auditable named log-odds term per scoring component
- Examples: `belief.py:67`, surfaced in `BeliefTrace` (`diagnostics.py:115`)
- Purpose: seven fixed-field per-turn records — interpretation, retrieval, constraint, belief, question, slate, runtime
- Examples: `diagnostics.py:21`–`diagnostics.py:195`
- Pattern: each exposes `as_record()`; sinks are `NoOpEvaluationTrace` and `JsonlEvaluationTrace`

## Entry Points

- Location: `starter/agent.py:15`
- Triggers: the organizer harness
- Responsibilities: `reset`, `respond`, `close`, `turn_history`
- Location: `evaluator/local_evaluator.py:298`
- Triggers: `uv run python -m evaluator.local_evaluator`
- Responsibilities: unmodified official scoring loop; never edited
- Location: `experiments/run_public.py:327`
- Triggers: `uv run python -m experiments.run_public --run-id <id>`
- Responsibilities: traced reproducible run; atomically publishes five files under `experiments/<run-id>/`
- Location: `starter/shopping_agent/build_catalog_artifacts.py:16`
- Triggers: one-off CLI before any evaluation

## Architectural Constraints

- **Determinism:** byte-level reproducibility is an acceptance property. Any new sort, set iteration, or dict ordering must have an explicit deterministic tie-break (convention: `parent_asin` last).
- **Threading:** single-threaded throughout. The SQLite connection is opened read-only and is not shared across threads.
- **No runtime dependencies:** `pyproject.toml` has `dependencies = []`. Inference must remain standard-library only — no network, model server, GPU, or credential.
- **Global state:** none mutable at module level. Module constants (`_ROUTE_WEIGHTS`, `DEFAULT_BELIEF_CONFIGURATION`, `_EXPANSIONS`, `_NEUTRAL_PROFILE`) are frozen values.
- **Circular imports:** none. Import direction is strictly entry → coordinator → domain → `search_backend`/`models`/`text_normalization`.
- **Bounded per-turn work:** route limit 1,000 (`retrieval.py:70`), ranker population 5,000 (`ranking.py:31`), clarification population 64 (`clarification.py:44`), belief trace 20 (`coordinator.py:54`), rejected trace 50 (`coordinator.py:53`). Nothing may grow with conversation length.
- **Evaluator immutability:** `evaluator/local_evaluator.py` and the public labels are never modified.

## Anti-Patterns

### Retrieve-then-reject constraint mismatch

### Hand-ordered attribute priority and hand-written block lists

### Estimating the clarifying question from the final slate

### Scoring before bounding

### Identity-keyed caches that drop their keys

### Modelling negation as a negative score

## Error Handling

- Typed build/validation errors: `ArtifactBuildError`, `ArtifactValidationError` (`catalog_artifacts.py:36`).
- Dataclass `validate()` methods on every request/result type (`search_backend.py`, `models.py`) enforce invariants at construction boundaries.
- `RuntimeError` for lifecycle misuse: closed agent, `respond` before `reset` (`coordinator.py:120`).
- Graceful degradation only where deterministic: `LexicalMode.AUTO` falls back from FTS5 to the TF-IDF posting path (`local_search_backend.py:195`); `resource` import is optional on Windows (`coordinator.py:48`).
- Output defence: `ResponseValidator` removes unknown or duplicate identifiers rather than trusting upstream.

## Cross-Cutting Concerns

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
