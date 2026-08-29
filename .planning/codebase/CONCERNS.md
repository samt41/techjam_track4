# Codebase Concerns

**Analysis Date:** 2026-08-29

This document separates **(a) concerns the project already documents** — chiefly
in `docs/STATUS.md`, `docs/organizer_briefing.md`, and `experiments/RUNS.md` —
from **(b) additional concerns found by reading the code**. Documented concerns
are carried forward faithfully and marked `[documented]`; new ones are marked
`[found in code]`.

The engineering baseline is genuinely strong: 167 tests, byte-verified
determinism, zero third-party runtime dependencies (`pyproject.toml` declares
`dependencies = []`), and no `TODO`/`FIXME`/`HACK` marker anywhere in
`starter/`, `evaluator/`, `experiments/`, or `tests/`. The concerns below are
therefore mostly about generalization to the private set, submission
deliverability, and a small amount of dead or unprincipled code — not about
correctness of the shipped path.

## Tech Debt

**Overfit phrase matchers to the public simulator's exact wording `[documented]`:**
- Issue: `_VERBOSE_DECLINE_RE` and `_SLATE_FEEDBACK_RE` match the public
  simulator's literal boilerplate. Verified in code: `_VERBOSE_DECLINE_RE`
  (`starter/shopping_agent/constraint_extractor.py:25-29`) matches
  `don't/do not/have no ... preference`, `no additional preference`, and
  `use your judgment`; `_SLATE_FEEDBACK_RE`
  (`starter/shopping_agent/constraint_extractor.py:49-51`) is a `fullmatch` on
  exactly `show me others|more|something else`, `more options`,
  `other options`, `next`.
- Files: `starter/shopping_agent/constraint_extractor.py`
- Impact: These strings are produced verbatim by
  `evaluator/local_evaluator.py:169` (`"I don't have a preference for
  {attribute}; please use your judgment."`) and
  `evaluator/local_evaluator.py:184` (`"I don't have an additional preference
  for {attribute}."`). If the organizer's private simulator rephrases them, the
  matchers do not fire, the `OTHER` residual at
  `constraint_extractor.py:242-247` manufactures a junk constraint at confidence
  0.55, and boundary/browsing sessions degrade. `_SLATE_FEEDBACK_RE` being a
  `fullmatch` is especially brittle: a trailing period or "please" defeats it.
- Fix approach: As STATUS.md states, remove the `OTHER`-residual fallback that
  manufactures the junk constraint, rather than widening the regexes. Deferred
  because the fallback is coupled to slate rotation. An intermediate hardening
  is to make `_SLATE_FEEDBACK_RE` a `search` over a normalized, punctuation-
  stripped message.

**Hardcoded synonym table `[documented]`:**
- Issue: `_EXPANSIONS` (`starter/shopping_agent/retrieval.py:50`) is a six-entry
  hand-written synonym/inflection map (boots, shoes, waterproof, warm).
- Files: `starter/shopping_agent/retrieval.py` (used at line 111)
- Impact: Low. It only widens lexical recall on the expanded-FTS route
  (`_ROUTE_WEIGHTS` weight 0.80) and never gates eligibility. But it is
  unprincipled by the project's own standard: every other word relation in the
  system is catalog-derived.
- Fix approach: Either delete it and measure, or replace with catalog-derived
  co-occurrence evidence. It is the only surviving hand-written word map.

**Dead quality-prior pathway `[documented as neutralized, found in code as dead weight]`:**
- Issue: STATUS.md records that the quality prior is neutralized after a 2x2
  ablation showed it cost 0.040 Hit Rate@10. In code the neutralization is a
  hardcoded literal: `ranking.py:229` threads `quality_prior=0.0` into a belief
  component that still exists in full — `quality_cap=0.40` in
  `DEFAULT_BELIEF_CONFIGURATION` (`starter/shopping_agent/belief.py:52`), the
  `quality_cap` field (`belief.py:29,40`), and the scoring and trace emission at
  `belief.py:184-192`.
- Files: `starter/shopping_agent/ranking.py`, `starter/shopping_agent/belief.py`,
  `starter/shopping_agent/catalog_artifacts.py`
- Impact: A per-product quality prior is computed and stored at artifact build
  time (README step 4 of the offline build) but is multiplied by nothing. Every
  turn emits a `quality_prior` belief-trace component whose weighted
  contribution is always 0.0, which is noise in the diagnostics. A future reader
  can reasonably believe the prior is active.
- Fix approach: Keep the component (it is the documented ablation hook) but make
  the neutralization explicit as a named configuration value rather than a bare
  `0.0` literal in the ranker, and note in the belief trace that the term is
  disabled.

**`_ATTRIBUTE_PRIORITY` survives after being documented as replaced `[found in code]`:**
- Issue: STATUS.md says the document-frequency classifier "replaced a
  hand-ordered `_ATTRIBUTE_PRIORITY`". The tuple still exists at
  `starter/shopping_agent/constraint_extractor.py:55-64` and is still consulted
  via `_ATTRIBUTE_RANK` (line 74) as a tie-break in `_resolve_phrase`.
- Files: `starter/shopping_agent/constraint_extractor.py`
- Impact: Documentation/code drift. The hand-ordered priority is not gone, it is
  demoted to a tie-break under the DF evidence rule. The claim "not a
  hand-ordered priority" is therefore slightly stronger than the code supports.
- Fix approach: Correct the wording in `docs/STATUS.md` to "DF evidence decides;
  the hand-ordered list only breaks exact ties", or make the tie-break
  deterministic on the attribute name instead.

**One-off analysis script retained in the package `[found in code]`:**
- Issue: `experiments/analyze_misses_b1.py` (257 lines) is a single-question
  investigation script whose docstring reports a result measured on a superseded
  run (`HEAD 1b8d88d`, the 0.76 configuration, 48 misses).
- Files: `experiments/analyze_misses_b1.py`
- Impact: Its stated conclusion ("dominant lever is intent_override
  slate-rotation") is stale — intent override was subsequently fixed from 0.20
  to 0.90. A reader who trusts the docstring gets a superseded diagnosis.
- Fix approach: Either annotate the docstring as historical with a pointer to
  the current 16-miss audit in `docs/STATUS.md`, or fold the script into
  `experiments/analyze_public.py`.

## Known Bugs

No open bugs are recorded, and none were found. The two systematic defects the
project documents were both diagnosed and fixed:

**Retrieve-then-reject on canonicalized material `[documented, fixed]`:**
- Symptoms: Intent Override scored Hit Rate@10 0.20; matching products were
  retrieved by SQL then dropped by the eligibility gate.
- Trigger: A canonicalized material value reached retrieval SQL but not the
  eligibility gate.
- Status: Fixed; Intent Override is now 0.90 (`experiments/RUNS.md`).

**Colon-spacing soft-match split `[documented, fixed]`:**
- Symptoms: The catalog writes the same feature as both `material: alloy` and
  `material:alloy`, splitting 131 concepts across 705 products; a target
  carrying the other spelling took the full soft-mismatch penalty (~-1.70
  log-odds) despite an exact concept match. One buying target sat at rank 154.
- Status: Fixed by `match_key` normalization; that target moved to rank 1 and
  Hit Rate@10 went 0.915 → 0.920.

## Security Considerations

**Secret and private-data hygiene `[found in code, currently sound]`:**
- Risk: The repository sits next to organizer-only material.
- Current mitigation: `.gitignore` excludes `organizer/`, `secure/`,
  `docs/audits/`, `docs/data_selection_audit.md`,
  `docs/participant_release_checklist.md`, the organizer-only pipeline tests
  (`tests/test_5core_builder.py`, `tests/test_organizer_pipeline.py`), `.env`,
  `results.json`, `data/catalog.jsonl`, `data/*.artifacts/`, and
  `experiments/*/`. `docs/submission_rules.md` explicitly disallows shipping
  private evaluation data or copied organizer-only files.
- Recommendations: Before packaging the submission, verify the bundle against
  the disallowed-contents list in `docs/submission_rules.md` — particularly that
  no `experiments/<run-id>/` directory, no `results.json`, and no `data/`
  artifact is included. The ignore rules protect the Git history, not a manually
  assembled zip.

**Untrusted input surface `[found in code]`:**
- Risk: `respond()` takes an arbitrary customer string. The extractor compiles no
  per-message regex (patterns are module-level constants at
  `constraint_extractor.py:25-54`), so there is no catastrophic-backtracking
  vector from user text, and `RUNS.md` records that per-value regex compilation
  was already rejected on performance grounds.
- Current mitigation: All SQL uses parameterized posting-set `IN`/`NOT IN`
  filters (`experiments/RUNS.md`, performance notes).
- Recommendations: None urgent. The surface is a local in-process call.

## Performance Bottlenecks

**Artifact build cost and size `[documented]`:**
- Problem: ~60-90 s single-threaded build producing a ~575 MB SQLite database
  (`experiments/RUNS.md`: 575,311,872 B; README says ~580 MB).
- Files: `starter/shopping_agent/build_catalog_artifacts.py`,
  `starter/shopping_agent/catalog_artifacts.py` (801 lines, the largest module)
- Cause: FTS5 index plus structured attribute rows over 50,000 products,
  101,291 terms.
- Improvement path: Already optimized once — `RUNS.md` records that the first
  build exceeded a 120-second window while maintaining indexes row by row, and
  that batching inserts and deferring secondary indexes fixed it. Further gains
  are not needed for correctness but see the deliverability risk below.

**Unbounded per-run memory growth `[found in code]`:**
- Problem: Three structures grow monotonically for the life of the process and
  are never evicted:
  1. `TurnCoordinator._sessions` (`starter/shopping_agent/coordinator.py:83`) is
     a dict keyed by `session_id`, populated in `reset` (line 98) and cleared
     only in `close()` (line 92). The evaluator calls `reset` once per session
     and never calls `close()` (`evaluator/local_evaluator.py:306` constructs
     `Agent(args.catalog)` and no `close()` appears).
  2. Each `_SessionState.turn_history` accumulates every `TurnRecord`
     (`coordinator.py:247`), including extracted updates and full slates.
  3. `LocalProductSearchBackend._product_cache`
     (`starter/shopping_agent/local_search_backend.py:59`) is deliberately
     unbounded — "valid for the life of the backend".
- Cause: Deliberate design for a 200-session run; the cache is a measured
  optimization for slate rotation.
- Impact: On the 800 private sessions this is 4x the retained-state growth, on
  top of a 1 GiB SQLite mmap and a 128 MiB page cache, in an environment where
  `docs/submission_rules.md` reserves the right to impose memory limits. Nothing
  in the repository measures peak RSS on a full run; `RUNS.md` notes that
  continuous `tracemalloc` tracking is disabled by default because it dominated
  traced-run cost.
- Improvement path: Measure peak RSS across a 200-session run and extrapolate;
  if it is material, bound `_product_cache` with an LRU and drop
  `_SessionState` for sessions that are finished (the coordinator cannot know
  this today — there is no end-of-session signal in the contract, so an
  LRU over sessions is the pragmatic bound).

**Wall-clock variance and per-turn timeout exposure `[documented]`:**
- Problem: `RUNS.md` records two byte-identical runs measuring 796 s and 1690 s,
  and elsewhere 185.492 s vs 126.485 s. Runtime is explicitly not a comparison
  axis.
- Impact: The organizer "reserves the right to run your submission under CPU,
  memory, timeout, and network restrictions"
  (`docs/submission_rules.md`), and the agent contract counts a timeout as a
  miss. Backend open alone measured 453.760 ms of startup validation in the
  microbenchmark table, and FTS Top-1,000 measured 81.365 ms. There is no
  per-turn deadline or budget in the code, so a slow host degrades silently into
  misses rather than into a cheaper answer.
- Improvement path: Add a soft per-turn deadline that short-circuits to the
  best-so-far slate rather than risking a timeout-scored miss.

## Fragile Areas

**The whole public metric rests on a locally reimplemented simulator `[found in code]`:**
- Files: `evaluator/local_evaluator.py:38-190` (`intent_card`,
  `classify_constraint`, `coarse_category`, `initial_message`,
  `customer_reply`, `materialize_hidden_fields`)
- Why fragile: `materialize_hidden_fields` (line 204) synthesizes the intent
  card from the target product itself when the sample does not carry one —
  `card = intent_card(product)` — and `intent_card` builds candidate constraints
  straight from the product's own catalog fields, including
  `f"budget around ${product['price']}"` at line 63. `customer_reply` then emits
  those strings verbatim. This is *why* two independent miss classifications
  found zero vocabulary gaps: the customer literally speaks the target's catalog
  text. `docs/organizer_briefing.md` confirms the real intent cards are
  organizer-only and never released.
- Impact: The 0.920 figure is measured against a customer model the repository
  itself constructs. The private set's simulator has organizer-authored intent
  cards and different phrasing. The "no vocabulary gap" finding — the single
  piece of evidence gating all embedding work — is a property of the local
  simulator, and the repository already says so
  (`docs/STATUS.md`, gating section). It deserves to be treated as the largest
  generalization unknown in the project, not as a settled result.
- Safe modification: Never tune extraction against the local simulator's
  phrasing. Prefer catalog-derived rules, which is what the project already
  does.
- Test coverage: `tests/test_evaluator.py` (85 lines) is the thinnest test file
  relative to the 312-line evaluator it covers.

**Slate rotation coupled to the `OTHER` residual `[documented]`:**
- Files: `starter/shopping_agent/constraint_extractor.py:242-247`,
  `starter/shopping_agent/coordinator.py:162-166,203`
- Why fragile: STATUS.md states the principled fix for the overfit matchers
  (removing the `OTHER` residual) is blocked because the residual is coupled to
  slate rotation. That coupling means the junk-constraint path and the
  rotation path cannot be changed independently.
- Safe modification: Decouple rotation from intent-version churn before touching
  the residual.

**Hard dependency on a stale-artifact refusal `[found in code, deliberate]`:**
- Files: `starter/shopping_agent/local_search_backend.py:61-72`,
  `starter/shopping_agent/catalog_artifacts.py`
  (`LoadedCatalogArtifacts.open`), `starter/agent.py:26-37`
- Why fragile: `Agent.__init__` opens the artifact eagerly and the loader
  refuses to open on any fingerprint or size mismatch. This is correct — a stale
  artifact must not silently serve a different catalog — but it means the
  failure mode is a construction-time exception, i.e. total run failure rather
  than degraded results. See the deliverability risk below.

## Scaling Limits

**Bounded pools chosen against this catalog `[documented]`:**
- Current capacity: ranker population cap 5,000 (`ranking.py:31`), retrieval
  route limit 1,000 (`retrieval.py`), clarification population cap 64
  (`clarification.py:44`), belief trace cap 20 and rejected-trace cap 50
  (`coordinator.py:53-54`).
- Limit: STATUS.md notes the 5,000 cap "was chosen so recall is not truncated on
  this catalog". The catalog is frozen at 50,000 products for this competition,
  so the cap is safe here by construction, but it is a catalog-sized constant,
  not a catalog-derived one.
- Scaling path: Derive the cap from catalog size if the catalog ever changes.

**Under-specified sessions are the public ceiling `[documented]`:**
- Current capacity: Hit Rate@10 0.920, 16 remaining misses.
- Limit: STATUS.md and RUNS.md both audit the remaining misses one belief
  contribution at a time and conclude none is a false penalty and none is a
  vocabulary gap. The representative case ties the top slate on every stated
  signal and differs only in raw retrieval `route` position among roughly 3,000
  equally matching sneakers.
- Scaling path: None available without inventing information the customer never
  gave. A popularity tie-break was tried and measured no effect because `route`
  varies continuously and leaves no exact ties.

## Dependencies at Risk

**Zero runtime dependencies, one environment requirement `[documented]`:**
- Risk: `pyproject.toml` declares `dependencies = []` and `requires-python =
  ">=3.10"`. The only external requirement is that CPython's SQLite build has
  FTS5 enabled (README).
- Impact: A judging host whose Python lacks FTS5 would break the primary lexical
  route.
- Migration plan: Already mitigated and measured. `RUNS.md` records a
  forced-fallback verification: running the full public set with
  `--lexical-mode fallback` (deterministic TF-IDF postings path) scored 0.75 /
  0.599 — near parity — with all 200 sessions completing and every miss
  attributed. The `LexicalMode.AUTO` default in `starter/agent.py:22` selects
  this automatically. This is a genuine strength, not a risk.

**`uv` is the documented toolchain but the rules ask for `requirements.txt` `[found in code]`:**
- Risk: README and `LOCAL_ENVIRONMENT.md` document `uv sync` / `uv run`, and
  `uv.lock` is committed. `docs/submission_rules.md` recommends a layout of
  `submission/agent.py`, `requirements.txt`, `README.md`, `src/` and requires
  "dependency installation steps".
- Impact: Low, since the dependency set is empty, but a judge following the
  recommended layout will not find a `requirements.txt`.
- Migration plan: Ship an empty-but-explanatory `requirements.txt` alongside the
  `uv` instructions, or state plainly in the submission README that there are no
  third-party dependencies.

## Competition-Rule and Deliverable Risks

**The submission cannot run without an out-of-band 580 MB build step `[found in code]`:**
- Problem: `docs/submission_rules.md` requires "one command to run the agent in
  the official harness" and warns that a submission that cannot be reproduced
  from the bundle "may be treated as invalid". But `Agent.__init__`
  (`starter/agent.py:26-37`) resolves the artifact path from the catalog path
  and opens it immediately; if `data/catalog.artifacts/catalog.sqlite3` does not
  exist, construction raises. Building it requires a separate documented command
  (`python -m starter.shopping_agent.build_catalog_artifacts`), 60-90 s, and
  ~580 MB of disk. The artifact is `.gitignore`d
  (`data/*.artifacts/`) and cannot be bundled — `docs/submission_rules.md`
  allows only "lightweight local assets".
- Blocks: If the organizer's harness imports `Agent` and constructs it without
  first running the build, the run fails at construction, not per-turn. The
  evaluator's own `except Exception` fallback at
  `evaluator/local_evaluator.py:241` only guards `respond`, not construction.
- Fix approach: Make the artifact build lazy and self-healing — if the artifact
  is absent but `data/catalog.jsonl` is present, build it on first construction
  with a clear log line — and state the disk, time, and memory cost prominently
  at the top of the submission README. This is the single highest-risk item for
  the submission actually scoring.

**Missing deliverables `[documented]`:**
- Problem: `docs/organizer_briefing.md` "Outstanding deliverable gaps" records
  two open items against the specification's Final Deliverables list:
  1. **Short report** — content exists across `README.md`, `docs/STATUS.md`, and
     `experiments/RUNS.md`, but there is no single report document and nothing
     on team contributions. `docs/submission_rules.md` additionally requires
     "a disclosure of latency, token usage, and estimated model cost" — the
     numbers exist (README "Runtime and resource consumption"; zero tokens via
     `response.py`, which always returns
     `{"prompt_tokens": 0, "completion_tokens": 0}`) but are not assembled as a
     disclosure.
  2. **One demonstrated multi-turn session** — not built. The briefing notes the
     raw material is already available: `Agent.turn_history()`
     (`starter/agent.py:52`, `coordinator.py:106`) returns typed `TurnRecord`
     values carrying dialogue act, extracted updates, intent version, question
     asked, and slate.
- Blocks: Both are explicit Final Deliverables. Neither affects `TechnicalScore`,
  which is why they have been deprioritized, but `docs/organizer_briefing.md`
  notes `TechnicalScore` "is not a separate judging criterion and does not
  represent the entire Technical Execution score", and that the full rubric is
  still not in this repository. Points are being left on an unmeasured table.

**"Transparent explanations" is a named innovation direction and is not built `[documented]`:**
- Problem: `response.py:34-58` templates a single fixed sentence plus an
  optional relaxation disclosure and the clarification prompt. The evaluator
  never reads `message`, so it contributes nothing to `TechnicalScore` — but the
  organizer names transparent explanations as an innovation direction.
- Blocks: Qualitative judging only.

**Public/private disjointness makes every tuned constant a bet `[documented]`:**
- Problem: `docs/organizer_briefing.md` records four verified-zero properties,
  including zero public/private user overlap and zero target overlap, and
  confirms final aggregation is over the 800 private sessions. Public
  performance is a development signal, not the score.
- Blocks: Nothing directly, but it is the reason the two overfit matchers are
  logged as debt and the reason keyed-feature recovery was kept at zero public
  gain. The correct posture — prefer catalog-derived rules over tuned constants
  — is already the project's stated policy.

## Measured-but-Unexplained in the Run History

**A 0.785 historical number that is not reproducible `[documented]`:**
- `experiments/RUNS.md` retains an in-memory "Information-gain clarification"
  row at Hit Rate@10 0.785, and flags in bold that it is **not reproducible** on
  the current SQLite engine and **must not** be treated as an acceptance gate.
  The artifact-backed engine started at 0.76 and only exceeded 0.785 after the
  extraction and matching fixes. Why the pre-SQLite engine scored higher than
  its successor's starting point is recorded as not comparable rather than
  explained.
- Risk: A reader could conclude the migration regressed accuracy. The honest
  reading is that the two engines' retrieval and ranking code differ enough that
  no comparison is meaningful — but that is an assertion, not a measurement.

**Counterfactual exploration is metric-identical on/off `[documented, explained]`:**
- Tail-fill fired on exactly 7 of ~1,500 public turns, every one an empty pool,
  and changed zero hits. Explanation given: whenever the strict pool holds >=1
  product on this catalog it already holds >=10. Well characterized, but it
  means the exploration machinery is essentially untested by the public metric —
  its correctness rests on unit tests, not on measured outcomes. On a private
  set with tighter constraints it could fire far more often, on a path with
  almost no measured evidence behind it.

**Keyed-feature recovery: measured zero public gain, retained anyway `[documented]`:**
- Structures 169 real product-value pairs across 40 recurring values; measured to
  leave the public metric unchanged with no regression. STATUS.md calls this "a
  judgment call in favour of correctness and private robustness over
  minimalism". The justification is sound but unfalsifiable on available
  evidence — there is no measurement that shows it helps anything.

**A popularity tie-break measured no effect `[documented, explained]`:**
- Explanation given: the `route` component already varies continuously and
  leaves no exact ties to break. Consistent with `ranking.py:177`, where the RRF
  score `item.score / (60.0 + item.rank)` is a continuous float.

## Test Coverage Gaps

The suite is 167 tests across 16 files (`tests/`), builds tiny fixture catalogs
in temp directories, and needs no catalog download. Gaps found:

**Evaluator/simulator `[found in code]`:**
- What's not tested: `tests/test_evaluator.py` is 85 lines against a 312-line
  `evaluator/local_evaluator.py`. `intent_card`, `classify_constraint`,
  `coarse_category`, and `materialize_hidden_fields` are the machinery that
  generates every public number.
- Risk: A silent change to the local simulator would move the headline metric
  with no test failure.
- Priority: Medium. The evaluator is organizer-supplied and must not be
  modified, which caps the value of testing it — but it also means any local
  drift is a reporting-integrity problem.

**Rephrased decline and slate-feedback wording `[found in code]`:**
- What's not tested: `tests/test_constraint_extractor.py:278-288` and
  `tests/test_agent.py:283` cover the short `"no preference"` form. No test
  exercises a *paraphrase* the regexes would miss — e.g. `"no strong feelings
  about color"`, or `"show me others please"` (which defeats the `fullmatch` in
  `_SLATE_FEEDBACK_RE`).
- Files: `starter/shopping_agent/constraint_extractor.py:25-51`,
  `tests/test_constraint_extractor.py`
- Risk: The single largest private-set risk has no test that characterizes its
  failure mode. A test asserting the *current* (degraded) behavior on
  paraphrases would at least make the exposure visible and would fail loudly
  when the `OTHER`-residual fix lands.
- Priority: High.

**Long-run resource behavior `[found in code]`:**
- What's not tested: No test resets many sessions against one `Agent` and
  asserts bounded growth of `TurnCoordinator._sessions`,
  `_SessionState.turn_history`, or `LocalProductSearchBackend._product_cache`.
- Files: `starter/shopping_agent/coordinator.py:83,247`,
  `starter/shopping_agent/local_search_backend.py:59`
- Risk: An 800-session private run is 4x the retained state of any run ever
  measured here.
- Priority: Medium.

**Missing-artifact construction path `[found in code]`:**
- What's not tested: `Agent(...)` when the artifact directory does not exist.
- Files: `starter/agent.py:26-37`, `tests/test_agent.py`
- Risk: This is the deliverability failure mode described above; there is no
  test pinning what the error looks like or how actionable its message is.
- Priority: High, and it pairs directly with the lazy-build fix.

---

*Concerns audit: 2026-08-29*
