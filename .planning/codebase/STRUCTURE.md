# Codebase Structure

**Analysis Date:** 2026-08-29

## Directory Layout

```
techjam_track4/
├── starter/                     # The submitted agent (all inference code)
│   ├── __init__.py
│   ├── agent.py                 # `Agent` organizer adapter — the API boundary
│   └── shopping_agent/          # Domain modules
│       ├── agent internals ...  # see table below
├── evaluator/                   # Unmodified official evaluator
│   ├── __init__.py
│   └── local_evaluator.py
├── experiments/                 # Reproducible runs and miss analysis
│   ├── RUNS.md                  # Retained run history per implementation class
│   ├── run_public.py
│   ├── analyze_public.py
│   ├── analyze_misses_b1.py
│   └── <run-id>/                # Generated, git-ignored
├── tests/                       # unittest suite (167 tests, fixture catalogs)
├── docs/                        # Specs, status, organizer material
│   ├── STATUS.md                # Hardcoded-value audit + plan states
│   ├── organizer_briefing.md
│   ├── competition_specification.md
│   ├── submission_rules.md
│   ├── agent_api_contract.json
│   ├── evaluation_config.json
│   ├── baseline_results.json
│   └── superpowers/
│       ├── plans/               # Dated implementation plans
│       └── specs/               # Dated design specs
├── data/                        # Catalog + built artifact (mostly git-ignored)
│   ├── README.md
│   ├── catalog.jsonl            # ignored, ~60.5 MB, 50,000 rows
│   ├── catalog.artifacts/       # ignored, ~580 MB SQLite + manifest
│   └── public_set.jsonl         # 200 public sessions
├── README.md                    # Query-flow walkthrough, quick start, results
├── LOCAL_ENVIRONMENT.md
├── DATA_ATTRIBUTION.md
├── pyproject.toml               # uv project, `dependencies = []`
└── uv.lock
```

## Directory Purposes

**`starter/`:**
- Purpose: everything that ships as the agent
- Contains: the adapter plus one module per pipeline stage
- Key files: `starter/agent.py`, `starter/shopping_agent/coordinator.py`

**`starter/shopping_agent/`:**
- Purpose: one module per architectural responsibility, no sub-packages
- Contains:

| File | Role |
|------|------|
| `models.py` | All enums and frozen dataclasses (the shared vocabulary) |
| `text_normalization.py` | `normalize_text`, `match_key`, `flatten_text`, `search_terms` |
| `constraint_extractor.py` | Dialogue acts + catalog-gazetteer constraint parsing |
| `preference_ledger.py` | Typed constraint accumulation and intent versioning |
| `retrieval.py` | Route planning, route weights, relaxation ordering |
| `search_backend.py` | `ProductSearchBackend` Protocol + request/result types |
| `local_search_backend.py` | SQLite adapter (FTS5, TF-IDF fallback, quality routes) |
| `catalog_index.py` | Catalog-vocabulary facade over the backend |
| `ranking.py` | `EligibilityGate`, `ProductRanker`, population bounding |
| `belief.py` | Bayesian posterior with typed contributions |
| `clarification.py` | Information-gain question model and ask policy |
| `response.py` | Slate validation, message assembly, payload shaping |
| `diagnostics.py` | Seven typed trace events + JSONL sink |
| `catalog_artifacts.py` | Offline artifact build, recovery rules, manifest |
| `build_catalog_artifacts.py` | Thin CLI wrapper over the builder |

**`evaluator/`:**
- Purpose: the official scorer, held frozen
- Do not edit `evaluator/local_evaluator.py` or the public labels

**`experiments/`:**
- Purpose: traced runs and post-hoc miss attribution
- Generated `experiments/<run-id>/` directories hold exactly five files: `summary.json`, `sessions.jsonl`, `failures.jsonl`, `retrieval_routes.jsonl`, `ablation.md`

**`tests/`:**
- Purpose: flat unittest suite mirroring source modules
- Key files: `tests/fixtures.py` builds tiny catalogs in temp directories so no catalog download is required

**`docs/superpowers/`:**
- Purpose: dated design specs and implementation plans; status of each is tracked in `docs/STATUS.md`

## Key File Locations

**Entry Points:**
- `starter/agent.py`: organizer-facing `Agent` (`reset`, `respond`, `close`)
- `evaluator/local_evaluator.py`: `python -m evaluator.local_evaluator`
- `experiments/run_public.py`: `python -m experiments.run_public --run-id <id>`
- `starter/shopping_agent/build_catalog_artifacts.py`: `python -m starter.shopping_agent.build_catalog_artifacts`

**Configuration:**
- `pyproject.toml`: uv project metadata, Python >= 3.10, zero dependencies
- `docs/evaluation_config.json`, `docs/agent_api_contract.json`: organizer contract
- Tuning constants live inline in their owning module (`DEFAULT_BELIEF_CONFIGURATION` in `belief.py`, `_ROUTE_WEIGHTS` in `retrieval.py`, weights in `catalog_artifacts.py`); there is no central config file. Every one is audited in `docs/STATUS.md`.

**Core Logic:**
- `starter/shopping_agent/coordinator.py`: the turn pipeline, read this first
- `starter/shopping_agent/models.py`: the type vocabulary
- `starter/shopping_agent/ranking.py`: eligibility and ordering
- `starter/shopping_agent/local_search_backend.py`: all SQL

**Testing:**
- `tests/test_agent.py`: end-to-end turn behaviour
- `tests/test_search_backend.py`: the largest suite, backend contract
- `tests/fixtures.py`: shared fixture catalog builders

## Naming Conventions

**Files:**
- `snake_case.py`, one module per responsibility, no nesting below `shopping_agent/`
- Tests mirror the source name: `ranking.py` + `retrieval.py` → `tests/test_retrieval_ranking.py`
- Docs are dated and kebab-cased: `docs/superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md`

**Symbols:**
- Public classes `PascalCase`; module-private helpers and constants take a leading underscore (`_ROUTE_WEIGHTS`, `_hard_filters`, `_POPULATION_CAP`)
- Enums subclass `StrEnum` (`Attribute`, `RetrievalRoute`, `DialogueAct`)
- Data carriers are `@dataclass(frozen=True, slots=True)` with an explicit `validate()` where invariants exist; mutable session carriers use `@dataclass(slots=True)`
- Every module starts with `from __future__ import annotations`; imports are absolute from `starter.shopping_agent.*`

**Directories:**
- Package directories are lowercase and flat; generated run outputs are `experiments/<run-id>/`

## Where to Add New Code

**New pipeline stage or scoring component:**
- Implementation: a new module in `starter/shopping_agent/`, wired into `TurnCoordinator.respond` (`starter/shopping_agent/coordinator.py`)
- Shared types: add the enum/dataclass to `starter/shopping_agent/models.py`, never define cross-module types locally
- Tests: `tests/test_<module>.py`

**New retrieval route:**
- Add the enum member to `RetrievalRoute` in `models.py`, a fusion weight in `_ROUTE_WEIGHTS` (`retrieval.py`), the plan in `RetrievalPlanner.strict`, and the SQL branch in `LocalProductSearchBackend.search`

**New trace field or event:**
- Add the dataclass with `as_record()` in `starter/shopping_agent/diagnostics.py`, emit it from a `_emit_*` helper in the coordinator, and extend `experiments/analyze_public.py` to consume it

**New artifact-build rule (recovery, weighting, index):**
- `starter/shopping_agent/catalog_artifacts.py`, bumping `ARTIFACT_SCHEMA_VERSION` when the schema changes; tests in `tests/test_catalog_artifacts.py`

**New tuned constant:**
- Keep it as a module-level `_UPPER_SNAKE` constant next to its use, and record it in `docs/STATUS.md` under the correct principled/tuned/overfit heading

**Utilities:**
- Text/matching helpers belong in `starter/shopping_agent/text_normalization.py`; there is no generic `utils` module and none should be created

## Special Directories

**`data/`:**
- Purpose: raw catalog, built SQLite artifact, public session set
- Generated: `catalog.artifacts/` yes; `catalog.jsonl` downloaded
- Committed: no — `data/catalog.jsonl` and `data/*.artifacts/` are git-ignored; `data/README.md` and `data/public_set.jsonl` are tracked

**`experiments/<run-id>/`:**
- Purpose: one atomic, immutable run output
- Generated: yes; run ids cannot overwrite
- Committed: no (`experiments/*/` is ignored); only `RUNS.md` records results

**`docs/superpowers/`:**
- Purpose: plans and specs, including gated unbuilt work
- Committed: yes

**Ignored by design:** `__pycache__/`, `.venv/`, `.superpowers/`, `.worktrees/`, `results.json`, `docs/audits/`, `organizer/`, `secure/`, and the organizer-only tests `tests/test_5core_builder.py` and `tests/test_organizer_pipeline.py`.

---

*Structure analysis: 2026-08-29*
