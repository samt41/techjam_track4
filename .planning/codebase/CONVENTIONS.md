# Coding Conventions

**Analysis Date:** 2026-08-29

This is a standard-library-only CPython project (`pyproject.toml` declares
`dependencies = []`). There is no linter, formatter, or type-checker config in
the repository, so conventions are enforced by consistency and by the unit
suite, not by tooling. Match the existing code exactly.

## Naming Patterns

**Files:**
- `snake_case.py`, one module per responsibility, no plural package names.
  `starter/shopping_agent/constraint_extractor.py`,
  `starter/shopping_agent/preference_ledger.py`,
  `starter/shopping_agent/local_search_backend.py`.
- Test modules mirror the module under test with a `test_` prefix:
  `tests/test_constraint_extractor.py`, `tests/test_belief.py`. Two modules
  cover a pair of collaborators: `tests/test_retrieval_ranking.py`,
  `tests/test_experiment_analysis.py`.
- Executable entry points are runnable modules invoked with `python -m`:
  `starter/shopping_agent/build_catalog_artifacts.py`,
  `evaluator/local_evaluator.py`, `experiments/run_public.py`.

**Functions:**
- `snake_case`, verb-led for actions (`normalize_text`, `analyze_session`,
  `build_test_artifacts`), noun-led for pure projections (`match_key`,
  `search_terms`, `intent_card`, `response_payload`).
- A leading underscore marks a module-private helper and is used heavily:
  `_publish`, `_load_events`, `_target_attributes`, `_sha256`, `_write_jsonl`
  in `experiments/run_public.py`; `_constraint`, `_intent` in
  `tests/test_belief.py`.

**Variables:**
- `snake_case`, spelled out in full. The codebase avoids abbreviations:
  `resolved_artifact_path`, `annotated_sessions`, `effective_intent_card`,
  `total_completion_tokens`. Loop variables are named for their content
  (`for number in range(...)`, `for sample in samples`), never `i` or `x`.
- Units are in the name: `startup_ms`, `elapsed_seconds`,
  `catalog_size_bytes`, `database_size_bytes`.

**Constants:**
- Module-level constants are `UPPER_SNAKE`. Public ones carry no underscore
  (`MAX_TURNS`, `TOP_K`, `WHITESPACE_RE` in
  `starter/shopping_agent/text_normalization.py`); tuning constants and
  internal tables are underscore-prefixed (`_STRUCTURED_DF_FLOOR`,
  `_MATERIAL_VOCAB_FLOOR`, `_KEYED_VALUE_FLOOR`, `_KEYED_VALUE_MAX_TOKENS`,
  `_KEYED_VALUE_MAX_LENGTH`, `_ROUTE_WEIGHTS`, `_EXPANSIONS`, `_STOPWORDS`).
- Compiled regexes always end in `_RE`: `_VERBOSE_DECLINE_RE`,
  `_NEGATION_CUE_RE`, `PUNCT_SPACING_RE`, `_RUN_ID_RE`. They are compiled once
  at module import, never inside a function — this is a measured requirement,
  see `tests/test_constraint_extractor.py::test_extraction_does_not_compile_patterns_per_catalog_value`.

**Types:**
- `PascalCase` classes. Domain value objects are named for the concept
  (`PreferenceConstraint`, `ShoppingIntent`, `ProductCandidate`,
  `RankedRecommendation`), collaborators are named for the role
  (`ConstraintExtractor`, `CandidateBeliefModel`, `TurnCoordinator`,
  `CatalogArtifactBuilder`, `LocalProductSearchBackend`).
- Private dataclasses used only inside a module take the underscore prefix:
  `_ParsedConstraint` in `experiments/analyze_public.py`,
  `_SessionMappingAgent` in `experiments/run_public.py`.

## Code Style

**Formatting:**
- No formatter is configured. Written in a Black-compatible style at a
  ~88-column soft limit, four-space indent, double quotes.
- Multi-line calls and literals use a trailing comma and one argument per
  line. See `starter/agent.py:39-44`, `experiments/run_public.py:107-118`.
- Every module begins with `from __future__ import annotations` as the first
  statement. This is universal across `starter/`, `evaluator/`,
  `experiments/`, and `tests/` — add it to any new module.
- Two blank lines separate top-level definitions; module constants are
  separated from imports by two blank lines.

**Typing:**
- Full annotations on every function signature and return, including `-> None`
  on tests and `__init__`. Modern PEP 604 unions (`float | None`,
  `str | Path`), built-in generics (`dict[str, str]`, `tuple[str, ...]`), and
  `frozenset[Attribute]` are used directly — never `Optional`, `Union`, or
  `typing.Dict`.
- Keyword-only parameters are marked with a bare `*` when a call site would
  otherwise be ambiguous: `def candidate(parent_asin: str, *, color: ... )` in
  `tests/test_belief.py:70`, `fts5_enabled: bool = True` in
  `tests/fixtures.py:96`.

**Data modelling:**
- All domain types are `@dataclass(frozen=True, slots=True)`. See the whole of
  `starter/shopping_agent/models.py`. Mutable state is the deliberate
  exception and is marked `@dataclass(slots=True)` without `frozen`
  (`RecommendationHistory`, `models.py:164`).
- Enumerations are `StrEnum` with `UPPER_SNAKE` members and lowercase string
  values (`Attribute`, `Strength`, `DialogueAct`, `RetrievalRoute` in
  `models.py`; `MissReason` in `experiments/analyze_public.py`). This makes
  every enum JSON-serializable without a custom encoder.
- Sequences that cross a module boundary are `tuple[...]`, not `list`. Lists
  are used only as local accumulators and converted with `tuple(...)` before
  return. See `experiments/run_public.py:233-255`.
- Validation lives on the dataclass as a `validate()` method that raises
  `ValueError`, not in a constructor (`PreferenceConstraint.validate`,
  `PreferenceUpdate.validate`, `models.py:110-143`).

**Determinism (non-negotiable):**
- Any iteration that affects output must be ordered. Dicts are dumped with
  `sort_keys=True` (`_write_json`, `_write_jsonl` in
  `experiments/run_public.py`); reason counts are emitted via
  `sorted(reason_counts.items())`.
- Ties are broken on a stable key, never left to insertion order. The belief
  ranker breaks ties by `parent_asin`
  (`tests/test_belief.py::test_ties_break_by_product_id`).
- Randomness is always seeded from stable content, never from the clock:
  `random.Random(f"{sample_id}\0{scenario_type}")` in
  `evaluator/local_evaluator.py:210-212`.
- De-duplication preserves order via `dict.fromkeys`, not `set`
  (`search_terms`, `text_normalization.py:47`).

## Import Organization

**Order** (three groups, blank line between, alphabetical within group):
1. `from __future__ import annotations`
2. Standard library — plain `import x` lines first, then `from x import y`.
   See `experiments/run_public.py:3-11`.
3. First-party absolute imports, `evaluator` then `experiments` then
   `starter` then `tests`.

**Rules:**
- Always absolute from the repository root (`from starter.shopping_agent.models
  import ...`). There are no relative imports anywhere.
- No path aliases and no barrel files. `starter/__init__.py`,
  `evaluator/__init__.py`, `experiments/__init__.py`, and
  `starter/shopping_agent/__init__.py` are 1-2 line stubs that export nothing;
  import the concrete module.
- Multi-name imports are parenthesized one-per-line with a trailing comma
  (`tests/test_belief.py:5-22`).

## Error Handling

**Patterns:**
- Raise a domain exception with a lowercase, specific message. The artifact
  layer defines `ArtifactValidationError` and `ArtifactBuildError`
  (`starter/shopping_agent/catalog_artifacts.py`) and raises them for every
  fingerprint, size, manifest, and parse failure — 20+ call sites, each with a
  distinct message naming the field or line number.
- Chain the cause with `raise ... from error` whenever wrapping a lower-level
  exception: `catalog_artifacts.py:161, 262, 300, 319`.
- `ValueError` for contract violations on typed values
  (`models.py:112`, `belief.py:98`), `RuntimeError` for lifecycle misuse
  (responding before `reset`, or after `close` — asserted in
  `tests/test_agent.py:227-242`), `FileExistsError` for a refused overwrite
  (`experiments/run_public.py:75`).
- Fail closed on corruption. A fingerprint or size mismatch marks the artifact
  unusable rather than partly trusted; the builder refuses to overwrite an
  existing artifact directory.
- Validate untrusted input at the boundary before use:
  `_RUN_ID_RE.fullmatch(run_id)` in `experiments/run_public.py:67`.
- Broad `except Exception` appears exactly once, in the unmodified evaluator
  (`evaluator/local_evaluator.py:241`), where an agent crash must degrade to an
  empty response rather than abort the run. Do not introduce it elsewhere.
- Platform quirks are handled explicitly and documented in a docstring rather
  than silently swallowed — see `_publish` in `experiments/run_public.py:135-150`
  for the Windows `os.rename` WinError 183 case.

## Logging

**Framework:** None. There is no `logging` import in the entire codebase.

**Patterns:**
- The CLI builder prints `key=value` lines to stdout and errors to stderr
  (`starter/shopping_agent/build_catalog_artifacts.py:31-42`). The evaluator
  and experiment runner print a JSON summary or the run path.
- Observability is structured, not textual. `starter/shopping_agent/diagnostics.py`
  defines the `EvaluationTrace` protocol and `JsonlEvaluationTrace`; the
  coordinator emits exactly seven fixed-field typed events per turn
  (interpretation, retrieval, constraint, belief, question, slate, runtime) to
  `retrieval_routes.jsonl`. Add a typed event, not a log line.
- Tracing is injected, never global: `Agent(..., trace=JsonlEvaluationTrace(path))`.
  The default is `trace=None`, so the organizer path emits nothing.

## Comments

**When to Comment:**
- Comment the *why*, never the *what*. Every comment in the codebase explains a
  non-obvious decision, a measured fact, or a platform constraint. Purely
  descriptive comments are absent.
- Reserve comments for: an overfit or hardcoded choice being flagged as debt
  (`_VERBOSE_DECLINE_RE`, `constraint_extractor.py:21-24`), a measured
  performance constraint, or a data anomaly in the catalog.

**Docstrings:**
- Sparse and load-bearing. Most modules have zero or one; `belief.py`,
  `clarification.py`, `coordinator.py`, `models.py`, and `diagnostics.py` have
  none, because their names and types carry the meaning.
- When present, a docstring is a one-line summary, then a blank line, then
  prose paragraphs explaining the reasoning and the evidence. The exemplar is
  `match_key` in `starter/shopping_agent/text_normalization.py:17-30`, which
  states the catalog anomaly, the consequence, the fix, and the invariant the
  fix preserves. `_SessionMappingAgent` and `_publish` in
  `experiments/run_public.py` follow the same shape.
- No parameter/return/raises sections. No reStructuredText or Google-style
  field lists anywhere.

## Function Design

**Size:** Small and single-purpose. Helpers are typically 5-25 lines; the
largest modules reach ~800 lines by holding many such helpers
(`catalog_artifacts.py`), not a few large ones.

**Parameters:** Prefer explicit typed parameters over dicts. Where an argument
list would be ambiguous at the call site, force keywords with `*`. Call sites
pass keywords freely even when positional would work
(`CandidateBeliefModel(TEST_CONFIG).score(candidates=..., intent=..., profile=...)`).

**Return Values:** Return a frozen dataclass or a tuple of them. `None` is
returned only where absence is a real domain state (`analyze_session` returns
`FailureAnalysis | None`; `ask_attribute` is `Attribute | None`).

**Configuration:** Tuning is bundled into a frozen configuration dataclass with
a module-level default and an `as_dict()` serializer, so the exact
configuration is recorded in every run summary:
`DEFAULT_BELIEF_CONFIGURATION` (`starter/shopping_agent/belief.py`),
`QuestionModelConfiguration.default()` (`starter/shopping_agent/clarification.py`),
both written into `summary.json` by `experiments/run_public.py:115-116`.

## Module Design

**Exports:** No `__all__` anywhere. Visibility is signalled by the underscore
prefix alone.

**Barrel Files:** Not used. Package `__init__.py` files are empty stubs.

**Layering:** `starter/shopping_agent/` may not import from `evaluator/`,
`experiments/`, or `tests/`. `experiments/` imports from both `evaluator/` and
`starter/`. `evaluator/local_evaluator.py` imports only `starter.agent.Agent`
and is treated as frozen — see below.

## Documentation and Experiment-Logging Conventions

These are as binding as the code conventions. A change is not complete until
the corresponding record is updated.

**Recording a constant.** Every tuned or hardcoded value must be listed in
`docs/STATUS.md` under one of four honesty tiers, with its symbol name, its
file, and its justification:
1. *Catalog-derived rules, not word lists* — computed from the frozen catalog,
   would adapt to a different catalog (attribute classification in
   `constraint_extractor.py`, material vocabulary in `catalog_artifacts.py`).
2. *Tuned constants* — a fixed number chosen by measurement, with the measured
   robustness range where known (`_STRUCTURED_DF_FLOOR = 2` is recorded as
   "verified robust across a floor of 2 through 5").
3. *Hardcoded word relations, still present* — small hand-written maps
   explicitly labelled as not principled (`_EXPANSIONS` in `retrieval.py`).
4. *Overfit to the public evaluator, flagged debt* — matchers tied to the
   simulator's exact wording, with the principled replacement named and the
   reason it is deferred (`_VERBOSE_DECLINE_RE`, `_SLATE_FEEDBACK_RE`).

Do not introduce an unrecorded constant. If you cannot place it in a tier,
that is a signal the value needs justification, not that the tier list needs
extending.

**Logging a run in `experiments/RUNS.md`.** Runs are grouped by engine era
(historical in-memory, artifact-backed superseded, artifact-backed current),
because numbers across eras are not comparable and the file says so explicitly.
Each row records: the change name with its short commit SHA, HitRate@10, MRR,
MTTC, TechnicalScore, and a Decision of `Retained`, `Superseded`, or
`Rejected: <reason>`. Only the best run per meaningful implementation class is
retained; generated `experiments/<run-id>/` directories are git-ignored.

Prose sections below the table carry the evidence a table cannot: where the
gain came from, ablation results (including changes measured at zero effect and
kept or rejected anyway), the determinism verification, performance notes,
artifact build stats, and a "Constraints and failures" list of everything that
was tried and did not work. Record negative and zero-gain results with the same
rigour as wins — `RUNS.md` documents a popularity tie-break that measured no
effect and a keyed-feature recovery deliberately retained at zero public gain.
Wall-clock runtime is explicitly *not* a comparison axis and is annotated as
such.

**Design documents.** Specs and plans live in `docs/superpowers/specs/` and
`docs/superpowers/plans/`, named `YYYY-MM-DD-kebab-case-topic.md`. Every
document is assigned a status in `docs/STATUS.md`: `done`, `superseded`, or
`gated`. A gated document must state the evidence that would unblock it — the
semantic concept-retrieval spec is gated on a held-out paraphrase probe showing
a real vocabulary gap, and the counter-evidence measured so far is written down
alongside it.

**Commit messages** (from `git log`): `type: lowercase imperative summary`, one
line, no body, no scope parentheses, no trailing period. Types in use, by
frequency: `feat:`, `docs:`, `fix:`, `perf:`, `analysis:`. The summary states
the outcome, not the mechanism — `fix: match colon-prefixed attribute values
regardless of colon spacing`, `perf: cache products, drop startup db hash,
disable continuous tracemalloc`, `analysis: B1 miss-classification proves 0
vocab-gaps, rotation is top lever`. A code change and its documentation update
are frequently separate commits (`5044b7c` feat, then `ab4d355` docs).

## Hard Invariants

- Never modify `evaluator/local_evaluator.py` or the public labels. It is the
  organizer's unchanged evaluator and results reported against a modified
  evaluator are meaningless.
- Ground truth must never reach the `Agent`. `_SessionMappingAgent`
  (`experiments/run_public.py:31-56`) joins sessions to samples only *after*
  `evaluate()` returns, and its docstring says so.
- Inference is standard-library-only and offline. No new runtime dependency,
  no network call, no model server.
- Negation is symbolic state, never a negative weight. An exclusion is never
  relaxed.
- Output must be byte-reproducible across runs, excluding run ids, evaluator
  session UUIDs, and measured timing.

---

*Convention analysis: 2026-08-29*
