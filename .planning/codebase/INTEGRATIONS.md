# External Integrations

**Analysis Date:** 2026-08-29

## Integration Posture: Deliberately Offline and Air-Gapped

**This project has zero external integrations, by design. That is the integration story, and it is a load-bearing competition decision — not a gap to be filled.**

The organizer explicitly permits external models, with teams supplying their own credentials and cost (`README.md` line 166). This implementation refuses that option and reports zero prompt and completion tokens.

**Verified evidence of the offline posture:**
- `pyproject.toml` declares `dependencies = []`. `uv.lock` contains exactly one package: the virtual root project itself.
- No import of `http`, `urllib`, `socket`, `requests`, `httpx`, or any provider SDK appears anywhere in `starter/`, `evaluator/`, `experiments/`, or `tests/`. The complete import set is standard library plus local packages.
- No `os.environ` or `getenv` call exists in the entire codebase. There is no credential lookup path to disable.
- `LOCAL_ENVIRONMENT.md` ("Offline verification rationale"): "It has no HTTP client, socket call, provider SDK, credential lookup, model download, semantic configuration, or GPU code path. Removing credentials or disabling network access does not change behavior."

**What this posture forbids, and what must not be introduced:**
- No LLM or hosted inference call at query time — not OpenAI, Anthropic, Bedrock, Vertex, or a self-hosted model server. This would break the zero-token report and the byte-level determinism guarantee.
- No embedding API, vector database, or hosted reranker.
- No network fetch of any kind at build time or inference time. The catalog is downloaded once, manually, by the operator.
- No environment-variable-driven configuration or secret. Adding one reintroduces a credential surface where none exists.
- No telemetry, analytics, crash reporting, or remote logging.
- No package that pulls a transitive network dependency. Any new third-party dependency breaks the "zero runtime dependencies" claim in `README.md` and `LOCAL_ENVIRONMENT.md` and must be an explicit, documented decision.
- No modification of `evaluator/local_evaluator.py` or `data/public_set.jsonl` when reporting a score (`README.md` design invariants).

**The one specified exception, gated and not built:** `docs/superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md` designs an *offline* ONNX embedding route. Even that hedge keeps the air gap — it would ship weights locally, not call a service. It is deliberately not started, gated on evidence of a vocabulary gap that two independent miss classifications did not find. See `docs/STATUS.md` for the gating rationale.

## APIs & External Services

**None.** No REST client, no GraphQL client, no SDK, no service account.

**Manual, one-time, human-performed downloads** (not code-invoked integrations):
- `catalog.jsonl.gz` and `techjam-participant-kit.zip` from the participant-kit GitHub release: `https://github.com/TechJam2026/techjam-conversational-search/releases/tag/participant-kit`. The operator downloads, verifies SHA-256, and decompresses by hand per `LOCAL_ENVIRONMENT.md`. No code performs this fetch.

## Data Storage

**Databases:**
- **SQLite** — the only datastore. `data/catalog.artifacts/catalog.sqlite3` (581,844,992 bytes).
  - Connection: local file path, resolved in `starter/agent.py` (defaults to `catalog_path.with_suffix(".artifacts")`, i.e. `data/catalog.artifacts`). No connection string, host, port, or credential.
  - Client: standard-library `sqlite3`. No ORM.
  - Opened read-only and memory-mapped: `PRAGMA query_only = ON`, `mmap_size = 1 GiB`, `cache_size = -131072` (128 MiB), `temp_store = MEMORY` (`starter/shopping_agent/catalog_artifacts.py` lines 283-289).
  - Written once by `starter/shopping_agent/build_catalog_artifacts.py` with `journal_mode = DELETE`, `synchronous = FULL`, then published atomically. The builder refuses to overwrite an existing artifact.
  - Contains a structured `(attribute, value)` table for eligibility plus an FTS5 virtual table `products_fts` for lexical relevance (`_create_fts5_table`, `catalog_artifacts.py` line 559).

**Search index:**
- **SQLite FTS5**, built in-process. Tokenizer `unicode61-remove-diacritics-2`, 101,291 lexical terms, field weights title 6.0 / category 4.0 / feature 2.5 / details 2.5 / store 1.5 / description 1.0 (`data/catalog.artifacts/manifest.json`). Queried in `starter/shopping_agent/local_search_backend.py` (`_fts5_result`, line 296). No Elasticsearch, OpenSearch, Lucene, or hosted search.

**File Storage:**
- Local filesystem only. All paths are repo-relative and go through `pathlib`.

**Caching:**
- In-process only. Materialized product records are cached for the life of the backend so rotation-overlapping candidates are not re-fetched across turns. No Redis, Memcached, or external cache.

## Authentication & Identity

**None.** There is no auth provider, no login, no session token, no API key.

The only identity concept is the organizer's opaque `session_id` string passed to `Agent.reset` (`starter/agent.py` line 45), plus an anonymous aggregate `user_profile` dict. Per `docs/agent_api_contract.json`, the profile carries only `purchase_frequency`, `average_prior_rating`, `rating_style`, `preference_tags`, and `summary`. Raw user IDs, timestamps, reviews, and purchase history are held by the organizer and never reach this repository (`docs/organizer_briefing.md`, "The privacy boundary").

## Monitoring & Observability

**Error Tracking:**
- None. No Sentry, Rollbar, or equivalent.

**Logs / traces:**
- Local typed diagnostics only, in `starter/shopping_agent/diagnostics.py`. `EvaluationTrace` is the protocol; the organizer adapter (`starter/agent.py`) defaults to a **no-op sink**, so a scored run emits nothing.
- `JsonlEvaluationTrace` writes seven fixed-field typed events per turn — interpretation, retrieval, constraint, belief, question, slate, runtime — to local JSONL. It opens an append handle per event for failure isolation and adds filesystem overhead only when explicitly enabled.
- Diagnostic-only instrumentation: `tracemalloc` and `resource`, both off by default because continuous tracking dominated traced-run time.
- `*.log` is `.gitignore`d.

## CI/CD & Deployment

**Hosting:**
- None. The organizer's evaluator imports `starter.agent.Agent` in-process. "There is no URL and no fixed port" (`docs/organizer_briefing.md`).

**CI Pipeline:**
- None committed. No `.github/workflows/`, no `.gitlab-ci.yml`, no pre-commit config. Verification is manual: `uv run python -W error::ResourceWarning -m unittest -v`, then `uv run python -m evaluator.local_evaluator`.

## Environment Configuration

**Required env vars:**
- **None.** Nothing in the codebase reads the environment.
- `.env` appears in `.gitignore` purely as a precaution. No such file exists and no code path would load it.

**Secrets location:**
- There are no secrets. `data/README.md` states: "Never place API keys, private evaluation data, or participant outputs in this directory."
- `.gitignore` additionally excludes organizer-only material that must never enter this repository: `organizer/`, `secure/`, `docs/audits/`, `docs/data_selection_audit.md`, `docs/participant_release_checklist.md`, and the organizer-only pipeline tests `tests/test_5core_builder.py` and `tests/test_organizer_pipeline.py`.

## Webhooks & Callbacks

**Incoming:**
- None. There is no server, no route table, no listening socket.

**Outgoing:**
- None.

## Data Sources & Artifacts

The "integrations" that actually matter here are local data artifacts and their integrity contracts.

**`data/catalog.jsonl`** — the frozen 50,000-product catalog.
- Not committed (`.gitignore`: `data/catalog.jsonl`). Supplied by the operator.
- Verified compressed asset SHA-256: `07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8`.
- Verified decompressed: 50,000 non-empty rows, 60,546,327 bytes, SHA-256 `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`.
- Visible fields: `parent_asin`, `title`, `features`, `details`, `description`, `categories`, `store`, `average_rating`, `rating_number`, `price`. Only `parent_asin` is scored.

**`data/catalog.artifacts/`** — the prebuilt SQLite artifact plus `manifest.json`.
- Not committed (`.gitignore`: `data/*.artifacts/`).
- `manifest.json` is the integrity contract between build and run: `catalog_sha256`, `catalog_size_bytes`, `database_sha256`, `database_size_bytes`, `schema_version: 1`, `product_count: 50000`, `fts5_built`, `fts_tokenizer`, `normalization_version: "nfkc-casefold-v1"`.
- On open, the backend checks the catalog fingerprint and file sizes and **refuses to open on mismatch**, so a stale artifact cannot silently serve a different catalog. It deliberately does not re-hash the 580 MB database, which is why startup is ~45 ms.
- `ARTIFACT_SCHEMA_VERSION = 1` (`starter/shopping_agent/catalog_artifacts.py` line 22) is validated at line 65; a version mismatch is a hard failure.

**`data/public_set.jsonl`** — 200 labeled development sessions (80 Buying, 80 Browsing, 30 Intent Override, 10 Boundary). Committed, 88,440 bytes. Never modified when reporting a score.

**Upstream data lineage and attribution** — `DATA_ATTRIBUTION.md`: derived from **Amazon Reviews 2023** (McAuley Lab, UCSD), category `Clothing_Shoes_and_Jewelry`, joined on `parent_asin`, text and structured metadata only. No images, videos, credentials, or private labels. Source-dataset terms apply. Full lineage counts (2,524,981 source records → 1,406 candidate targets → 200 public + 800 private sessions) are in `docs/organizer_briefing.md`.

**Generated run artifacts** — `experiments/<run-id>/` contains exactly `summary.json`, `sessions.jsonl`, `failures.jsonl`, `retrieval_routes.jsonl`, `ablation.md`. Written atomically via a temporary directory (`experiments/run_public.py` lines 71-78); run IDs cannot overwrite. All run directories are `.gitignore`d (`experiments/*/`), as is `results.json`. Retained metrics are summarized by hand into `experiments/RUNS.md`.

## Interface Contracts (the only true external boundary)

The organizer's evaluator is the sole consumer of this code. The contract is `docs/agent_api_contract.json` (JSON Schema draft 2020-12), with `docs/evaluation_config.json` fixing the scoring parameters.

- `reset(session_id, user_profile)` — `user_profile` has exactly the five anonymous fields, `additionalProperties: false`.
- `respond(session_id, user_message, turn, top_k)` — `turn` is 1-10, `top_k` is `const: 10`.
- Response: `message`, `ask_attribute` (null or one of `category`, `material`, `color`, `size`, `style`, `brand`, `budget`, `feature`, `use_case`, `other`), ordered `recommendations` of `{parent_asin, score?}`, and optional `usage` with `prompt_tokens` / `completion_tokens` — reported as 0 / 0.
- `docs/evaluation_config.json`: `catalog_id_field: parent_asin`, `top_k: 10`, `max_turns: 10`, `miss_turn_value: 11`, `exact_match: true`, composite weights HR@10 0.5 / MRR 0.3 / efficiency 0.2.
- Only exact `parent_asin` equality counts. Final aggregation happens over the 800 private sessions, which share no users and no targets with the public 200.

---

*Integration audit: 2026-08-29*
