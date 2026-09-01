# Technology Stack

**Analysis Date:** 2026-08-29

## Languages

**Primary:**
- Python 3.10+ (CPython 3.13.11 verified) — the entire repository. Agent (`starter/`), evaluator (`evaluator/`), experiment harness (`experiments/`), tests (`tests/`).

**Secondary:**
- SQL (SQLite dialect, including FTS5 `MATCH` queries) — embedded in `starter/shopping_agent/catalog_artifacts.py` (build-time DDL/DML) and `starter/shopping_agent/local_search_backend.py` (query-time retrieval SQL).
- PowerShell — used only for documented operator commands in `README.md` and `LOCAL_ENVIRONMENT.md`. No `.ps1` scripts are committed.
- Markdown / JSON / JSONL — documentation, contracts, datasets, and run artifacts.

There is no JavaScript, TypeScript, or frontend component. `LOCAL_ENVIRONMENT.md` line 17 states that if JS/TS is ever added, `pnpm` is the chosen manager.

## Runtime

**Environment:**
- CPython, `requires-python = ">=3.10"` (`pyproject.toml`).
- Verified: CPython 3.13.11 inside a `uv`-managed `.venv` on Windows PowerShell.
- Hard runtime requirement: the CPython build's bundled SQLite must have **FTS5 enabled**. Verified against SQLite 3.50.4. The check command is in `LOCAL_ENVIRONMENT.md` lines 47-49.
- Graceful degradation exists: `CatalogArtifactBuilder(fts5_enabled=...)` and `LexicalMode` (`starter/shopping_agent/search_backend.py`, default `LexicalMode.AUTO` in `starter/agent.py`) allow a non-FTS5 path, and the manifest records `fts5_built`.

**Package Manager:**
- `uv` (`uv sync`). Lockfile `uv.lock` is present and committed — 8 lines, lock `version = 1`, `revision = 3`, and exactly one package entry: the virtual root project itself (`source = { virtual = "." }`). There are no third-party packages to resolve.

## Frameworks

**Core:**
- None. There is no web framework, ORM, retrieval library, or ML framework. Storage and search are hand-written over the standard-library `sqlite3` module.

**Testing:**
- `unittest` (standard library). No pytest, no plugins. 167 tests, run via `uv run python -m unittest -v`, or warning-strict via `uv run python -W error::ResourceWarning -m unittest -v`. Shared fixture builders live in `tests/fixtures.py` and construct tiny catalogs in temporary directories, so the suite needs no catalog download.

**Build/Dev:**
- `starter/shopping_agent/build_catalog_artifacts.py` — the one-off offline artifact builder CLI (`--catalog`, `--output`, both required).
- `evaluator/local_evaluator.py` — the unchanged organizer evaluator CLI (`--catalog` default `data/catalog.jsonl`, `--dataset` default `data/public_set.jsonl`, `--output` default `results.json`).
- `experiments/run_public.py` — the reproducible experiment CLI (`--run-id` required, `--catalog`, `--dataset`, `--output-root` default `experiments`, `--exploration` default `disabled`, plus a `--...` mode defaulting to `auto`).
- `experiments/analyze_public.py` and `experiments/analyze_misses_b1.py` — post-run trace analysis and typed miss attribution.
- No linter, formatter, type-checker, pre-commit hook, Makefile, Dockerfile, or CI workflow is committed.

## Key Dependencies

**Critical:**
- **Zero declared runtime dependencies.** `pyproject.toml` has `dependencies = []`. This is a deliberate competition posture, not an oversight (`LOCAL_ENVIRONMENT.md`, "Offline verification rationale").

**Standard-library modules actually imported** across `starter/`, `evaluator/`, `experiments/`, `tests/`:
- `sqlite3` — the entire storage and retrieval engine, including the FTS5 virtual table.
- `json`, `pathlib`, `dataclasses`, `enum` (`StrEnum`), `typing` (`Protocol`, `Union`) — typed models and artifact/manifest serialization (`starter/shopping_agent/models.py`, `catalog_artifacts.py`).
- `re`, `unicodedata`, `collections` (`Counter`, `defaultdict`), `math`, `statistics` — normalization, gazetteer construction, and scoring (`starter/shopping_agent/text_normalization.py`, `constraint_extractor.py`, `belief.py`, `ranking.py`).
- `hashlib` — catalog and database SHA-256 fingerprinting (`experiments/run_public.py`, `catalog_artifacts.py`).
- `argparse`, `sys`, `os`, `io`, `shutil`, `tempfile`, `contextlib`, `subprocess` — CLIs, atomic publish, and test harness plumbing.
- `time` (`perf_counter`), `tracemalloc`, `resource` — runtime and memory diagnostics; continuous `tracemalloc` tracking is off by default because it dominated traced-run time.
- `random`, `uuid` — internal session identifiers only; never used for ranking decisions, which is why determinism is byte-verifiable.
- `unittest`, `unittest.mock.patch` — tests.

**Infrastructure:**
- None external. The only "infrastructure" is the local file `data/catalog.artifacts/catalog.sqlite3`.

## Configuration

**Environment:**
- **No environment variables are read anywhere.** A repository-wide grep for `os.environ` and `getenv` across `starter/`, `evaluator/`, and `experiments/` returns nothing. There are no API keys, credentials, or provider settings.
- `.env` is listed in `.gitignore` as a precaution; no `.env` file exists and nothing would read it.
- All configuration is either a CLI flag or a typed dataclass default in code.

**In-code configuration objects:**
- `DEFAULT_BELIEF_CONFIGURATION` (`starter/shopping_agent/belief.py`) — `route_scale=0.60`, `soft_match_likelihood=0.80`, `soft_mismatch_likelihood=0.12`, `unknown_likelihood=0.40`, `feature_likelihood=0.55`, `profile_cap=0.35`, `quality_cap=0.40`, `temperature=1.0`. `quality_cap` is present but neutralized (a `0.0` quality prior is threaded in).
- `_ROUTE_WEIGHTS` (`starter/shopping_agent/retrieval.py`) — metadata 1.40, exact FTS 1.20, expanded FTS 0.80, category fallback 0.25, counterfactual 0.15; route limit 1,000.
- `QuestionModelConfiguration` (`starter/shopping_agent/clarification.py`) — population cap 64.
- Caps: ranker population 5,000 (`ranking.py`), belief trace 20 (`coordinator.py`).
- Extractor floors: `_STRUCTURED_DF_FLOOR = 2`, `_STOPWORDS` (`constraint_extractor.py`); `_MATERIAL_VOCAB_FLOOR = 2`, `_KEYED_VALUE_FLOOR = 2`, `_KEYED_VALUE_MAX_TOKENS = 4`, `_KEYED_VALUE_MAX_LENGTH = 25` (`catalog_artifacts.py`).
- Full audit of every tuned constant, with how principled each is: `docs/STATUS.md`.

**Build:**
- `pyproject.toml` — five lines: project name `techjam-track4-agent`, version `0.1.0`, `requires-python`, empty dependencies. No build backend, no tool sections.
- `data/catalog.artifacts/manifest.json` — the generated build configuration record: `schema_version: 1` (matching `ARTIFACT_SCHEMA_VERSION` in `catalog_artifacts.py`), `catalog_sha256`, `catalog_size_bytes`, `database_sha256`, `database_size_bytes`, `product_count: 50000`, `lexical_term_count: 101291`, `fts5_built: true`, `fts_tokenizer: "unicode61-remove-diacritics-2"`, `normalization_version: "nfkc-casefold-v1"`, `posting_batch_size: 1000`, and the FTS field weights (title 6.0, category 4.0, feature 2.5, details 2.5, store 1.5, description 1.0).

**SQLite PRAGMA configuration** (`starter/shopping_agent/catalog_artifacts.py`):
- Read path (lines 283-289): `query_only = ON`, `mmap_size = 1073741824` (1 GiB), `cache_size = -131072` (128 MiB page cache), `temp_store = MEMORY`.
- Build path (lines 442-443): `journal_mode = DELETE`, `synchronous = FULL`.

## Platform Requirements

**Development:**
- `uv` on PATH; CPython 3.10+ with FTS5-enabled SQLite.
- Disk: ~61 MB decompressed catalog (`data/catalog.jsonl`, 60,546,327 bytes) plus ~580 MB artifact (`data/catalog.artifacts/catalog.sqlite3`, 581,844,992 bytes on disk). Neither is committed; both are `.gitignore`d.
- RAM sufficient for a 1 GiB memory map plus a 128 MiB page cache.
- Verified on Windows 11 / PowerShell. Nothing in the code is OS-specific; paths go through `pathlib`.

**Production:**
- There is no deployment target. The organizer's evaluator imports `starter.agent.Agent` locally in-process. `docs/organizer_briefing.md` states plainly: "The evaluator imports the submission locally. There is no URL and no fixed port." No hosted service, container, GPU, model server, or port is required.

**Measured runtime budget:**
- One-off artifact build: ~60-90 s, single-threaded, ~580 MB written.
- Backend open: ~45 ms (the 580 MB database is deliberately not re-hashed on open; catalog fingerprint and file sizes are checked instead).
- Full 200-session public evaluation: ~190 s wall-clock on the reference machine, excluding the build.
- Reported prompt/completion tokens: 0 / 0.

---

*Stack analysis: 2026-08-29*
