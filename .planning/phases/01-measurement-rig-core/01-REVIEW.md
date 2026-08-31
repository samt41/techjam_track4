---
phase: 01-measurement-rig-core
reviewed: 2026-08-31T00:00:00Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - arena/__init__.py
  - arena/adjudication.py
  - arena/arena.py
  - arena/candidate.py
  - arena/evaluator_bridge.py
  - arena/import_legacy_results.py
  - arena/leaderboard.py
  - arena/metrics.py
  - arena/run_arena.py
  - arena/statistics.py
  - arena/store.py
  - tests/arena_fixtures.py
  - tests/test_arena_adjudication.py
  - tests/test_arena_boundary.py
  - tests/test_arena_candidate.py
  - tests/test_arena_import_legacy.py
  - tests/test_arena_leaderboard.py
  - tests/test_arena_metrics.py
  - tests/test_arena_runner.py
  - tests/test_arena_statistics.py
findings:
  critical: 3
  warning: 10
  info: 5
  total: 18
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-08-31
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

The statistical core is in better shape than the surrounding plumbing. I attacked
`statistics.py` hardest and could not break it: `percentile_indices` was brute-forced
against exact-rational arithmetic for every `R` in `[40, 2_000_000]` — symmetry
(`lower == R-1-upper`), coverage (`span >= 0.95R`) and float-vs-`Fraction` agreement hold
at every count, with no boundary where `floor`/`ceil` drifts. The Efron-Tibshirani
denominator, the Phipson-Smyth `+1` (and its correct *absence* in the exhaustive
enumeration), the Holm running maximum with an index tie-break, the Simpson weighting in
`expected_max_of_k`, and the `_delta`-recomputed-per-replicate discipline are all correct.
The adjudication fixes from the gap-closure round are real: `abs(mttc_delta)` is
load-bearing and covered, and the zero-variance path now measures rather than asserts —
I re-derived every column of both committed adjudication rows from its siblings and they
reconcile exactly.

The defects are in the layers that carry those numbers to disk. Three of them corrupt a
published number or a published identity:

1. `build_leaderboard` keys per-entry metrics by fingerprint, so two entries sharing one
   fingerprint silently print each other's metrics — reproduced.
2. `adjudicate` refuses a candidate that collides with the baseline but not one that
   collides with another candidate, so a duplicated `--candidate` inflates the Holm family
   and `correction_k` — reproduced (`k=2`, `holm_p=1.0` for a single hypothesis).
3. `SessionOutcome.validate()` admits internally inconsistent rows, so a record can
   publish `hit_rate_at_10 = 1.0` beside a curve `HR@10 = 0.0` — reproduced.

Below that, a cluster of provenance and durability gaps: a non-atomic two-file write to
git-tracked artifacts (the same defect that was just fixed in the sibling writer), a
`.gitignore` claim that `git check-ignore` disproves, override *values* that are never
validated while a comment claims they are, a dead `_SampleMappingAgent`, and no check that
two compared arms were even measured against the same dataset.

Full suite re-run during review: 207 tests, all passing. Every finding below is therefore
invisible to the current suite.

## Critical Issues

### CR-01: Two entries sharing a fingerprint collapse, so one record's row prints another record's metrics

**File:** `arena/leaderboard.py:296-312`, `arena/leaderboard.py:499`

**Issue:** `summaries` and `scores` are dicts keyed on `entry.fingerprint`:

```python
summaries = {entry.fingerprint: metric_summary(entry.sessions) for entry in entries}
scores   = {fingerprint: technical_score(summary) for fingerprint, summary in summaries.items()}
```

A fingerprint is *not* unique per entry. It hashes name + revision + dirty flag +
overrides + the two digests — deliberately, so one configuration has one identity. Two
retained records of the same configuration therefore share it. That happens in at least
three ordinary ways: re-running one configuration under a second `run_id` to measure
run-to-run variation (nothing in `run_candidate` prevents it), passing the same directory
twice to `--candidate`, or passing a record to both `--candidate` and `--include`.

When it happens, the dict collapses to the **last** entry's summary and both rows print
it. Reproduced with two entries of one configuration carrying different sessions:

```
row: run-x 30d5052e 0.83 0.5     <- run-x's real mrr is 0.541667, ts is higher
row: run-y 30d5052e 0.83 0.5
curve rows: [('30d5052e', 0.083333), ('30d5052e', 0.0)]
```

The candidate table prints identical (wrong) metrics for both, while `hit_rate_curve` and
`scenario_breakout` are computed from `entry.sessions` directly and print each entry's
*real* numbers — so the two tables in one report contradict each other, and the row order
is derived from the collapsed score as well. `render_markdown` compounds it: `names` is
also fingerprint-keyed (line 499), and the candidate table prints no `run_id`, so a reader
cannot even tell the two rows apart. This is precisely the class the phase exists to
prevent: a confident, auditable-looking, false number.

**Fix:** stop keying per-entry derived data on a value that is per-*configuration*. Compute
alongside the entry, and refuse an ambiguous report explicitly:

```python
if len({entry.fingerprint for entry in entries}) != len(entries):
    duplicated = sorted(
        fingerprint
        for fingerprint in {entry.fingerprint for entry in entries}
        if sum(1 for entry in entries if entry.fingerprint == fingerprint) > 1
    )
    raise ArenaStoreError(
        f"two entries share one fingerprint, so their rows cannot be told apart: {duplicated}"
    )
computed = tuple(
    (entry, metric_summary(entry.sessions)) for entry in entries
)
scored = tuple(
    (entry, summary, technical_score(summary)) for entry, summary in computed
)
ordered = sorted(scored, key=lambda item: (-item[2], item[0].fingerprint))
```

Then iterate `ordered` and use the tuple-local `summary`/`score` rather than a dict lookup,
and key `names` in `render_markdown` on `(fingerprint, run_id)` or add a `run_id` column so
the display is unambiguous even if the guard is later relaxed.

---

### CR-02: `adjudicate` guards against a baseline fingerprint collision but not a candidate-vs-candidate one, inflating the Holm family and `correction_k`

**File:** `arena/adjudication.py:200-205`, `arena/adjudication.py:296`, `arena/adjudication.py:315-316`

**Issue:** The entry guard checks only one direction:

```python
for candidate in candidates:
    if candidate.spec.fingerprint == baseline_fingerprint:
        raise ValueError("a candidate must not share the baseline's fingerprint")
```

Nothing rejects two candidates with the same fingerprint, and `run_arena._adjudicate`
(`--candidate` is `action="append"`) passes whatever the operator typed. Reproduced with
the same arm twice:

```
k: [2, 2]  holm: [1.0, 1.0]  perm: [1.0, 1.0]
holm_family_size: 2
```

One hypothesis, submitted twice, is reported as a family of two. Two reported numbers are
then wrong on the same row:

- `holm_p` is multiplied by 2 for a family that contains one real comparison, so a genuine
  result can be pushed past `SIGNIFICANCE_ALPHA` and land on `holm_significance` in
  `failed_criteria`, i.e. flip a `win` to `significant, below ship bar` or `not detectable`.
- `correction_k = 2` charges `sigma * E[max of 2] = 0.5642 * sigma` of winner's-curse
  correction against `clears_practical_floor` for a selection that never happened. At the
  committed report's own `sigma = 0.012845`, that is 0.0072 of TechnicalScore — most of the
  0.01 ship floor, removed for nothing.

Both arms also draw the *same* `pair_seed`, so the two rows are bit-identical replicates of
one another rather than independent evidence, and `assumptions.holm_family_size` (written
as `len(rows)`, leaderboard.py:425) states the inflated number as if it were measured
design.

The module's own comment at `adjudication.py:286-295` argues at length that the family is
"a property of the experimental DESIGN — how many arms were submitted for comparison". A
directory submitted twice is one arm, not two, so the guard is incomplete on exactly the
reading the comment adopts.

**Fix:** extend the existing loop to a full uniqueness check, and reject the CLI-level
overlap too:

```python
fingerprints = [candidate.spec.fingerprint for candidate in candidates]
if baseline_fingerprint in fingerprints:
    raise ValueError("a candidate must not share the baseline's fingerprint")
if len(set(fingerprints)) != len(fingerprints):
    raise ValueError("each candidate must appear in the family exactly once")
```

and in `arena/run_arena.py:_adjudicate`, after resolving the directories, refuse a record
that appears in more than one of `--baseline` / `--candidate` / `--include` (compare
`Path.resolve()` values, not the raw strings, so `./run-a` and `run-a` collide).

---

### CR-03: `SessionOutcome.validate()` admits internally inconsistent and non-integer rows, so a published record can contradict itself

**File:** `arena/metrics.py:37-47`, `arena/store.py:74-97`

**Issue:** `validate()` checks each field's range in isolation and one relationship
(`hit` vs `first_hit_turn`). It never checks the three relationships that make the metric
chain coherent:

- `hit` vs `best_rank` — a row with `hit=True, best_rank=None` is admitted.
- `reciprocal_rank` vs `best_rank` — any value in `[0, 1]` is admitted for any rank.
- `first_hit_turn` / `best_rank` integrality — the values are passed through
  `load_sessions` (store.py:87-88) with **no coercion at all**, unlike the four fields
  beside them.

Reproduced, from a `sessions.jsonl` row that `load_sessions` accepts without complaint:

```
inconsistent row accepted: SessionOutcome(hit=True, first_hit_turn=1, best_rank=None, reciprocal_rank=1.0)
hr: 1.0   curve: {1: 0.0, 3: 0.0, 5: 0.0, 10: 0.0}
```

`metric_summary.hit_rate_at_10` reads `hit`; `hit_rate_curve` reads `best_rank`. The
leaderboard prints both, in adjacent tables, for the same candidate: `HR@10 = 1.0` in
Candidates and `HR@10 = 0.0` in the HitRate@K curve. `tests/test_arena_metrics.py:157`
exists precisely to assert those two agree — but only for the anchor, so nothing enforces
it as an invariant.

Also reproduced: `"first_hit_turn": 2.5` and `"best_rank": true` are both accepted
(`1 <= True <= 10` is `True` because `bool` is an `int`), yielding a fractional MTTC of
2.5 and a rank that round-trips back to disk as JSON `true`:

```
mttc: 2.5
round-trip bytes: b'{"best_rank": true, "first_hit_turn": 2.5, ...}'
```

An unconstrained `reciprocal_rank` is the worst of the three: a record with
`best_rank=10, reciprocal_rank=1.0` on every session inflates MRR by 0.9, i.e.
TechnicalScore by 0.27 — twenty-seven times the ship floor — while passing every check on
the read path. This is reachable without hand-editing: `import_legacy_results` projects
`SESSION_FIELDS` verbatim (import_legacy_results.py:96) out of an untracked,
provenance-free `results.json`, and `_project_sessions` validates nothing but presence.

The comment at `store.py:79-80` states the opposite of what the code does: *"Every field
is explicitly coerced and then validated before it can reach a statistic."* Two of the six
fields are neither coerced nor type-checked.

**Fix:** make `validate()` enforce the relationships, and coerce the two integer fields at
the boundary:

```python
def validate(self) -> None:
    if not self.sample_id:
        raise ValueError("sample_id must not be empty")
    for name, value in (("best_rank", self.best_rank), ("first_hit_turn", self.first_hit_turn)):
        # bool is an int, and a float rank is not a rank: reject both by type.
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"{name} must be an integer or null")
    if self.best_rank is not None and not 1 <= self.best_rank <= MAX_SLATE_RANK:
        raise ValueError(f"best_rank must be between 1 and {MAX_SLATE_RANK}")
    if self.first_hit_turn is not None and not 1 <= self.first_hit_turn <= MAX_TURNS:
        raise ValueError(f"first_hit_turn must be between 1 and {MAX_TURNS}")
    if self.hit != (self.first_hit_turn is not None):
        raise ValueError("hit must agree with first_hit_turn presence")
    # The three relationships the metric chain assumes and never checked.
    if self.hit != (self.best_rank is not None):
        raise ValueError("hit must agree with best_rank presence")
    expected = 0.0 if self.best_rank is None else 1.0 / self.best_rank
    if abs(self.reciprocal_rank - expected) > 1e-12:
        raise ValueError("reciprocal_rank must equal 1 / best_rank, or 0 for a miss")
```

and correct the false comment in `load_sessions`. `evaluator/local_evaluator.py:269-275`
emits exactly these invariants, so no legitimate harness row is rejected — I checked the
committed records against the stricter rule in reasoning and they conform.

## Warnings

### WR-01: `CandidateSpec.validate()` validates override keys but never values, and `exploration` fails open

**File:** `arena/candidate.py:52-74`, `arena/arena.py:109-113`, `arena/run_arena.py:201-211`

**Issue:** `validate()` rejects unknown *keys* against `ALLOWED_OVERRIDES` and never looks
at a value. Downstream, `starter/shopping_agent/coordinator.py:87` reads
`self._exploration_enabled = exploration != "disabled"`, so every value that is not the
exact string `"disabled"` **enables** exploration: `"Disabled"`, `"disabled "`,
`"tail_only"`, `"bogus"`. Each mints its own fingerprint. A record therefore exists whose
hashed overrides say `exploration: "Disabled"` while the agent that ran had exploration on
— the fingerprint describes a configuration that was not applied.

The comment at `arena/arena.py:109-112` claims this cannot happen: *"an unknown or
unapplied override is rejected here, so a fingerprint can never describe a configuration
that did not run."* It is false for values. The only thing standing between a caller and
that record is `argparse`'s `choices=` in `run_arena.py:203, 208` — an allow-list of
admissible *values* living in the CLI rather than beside `ALLOWED_OVERRIDES`, so
`build_candidate_spec` (a public function the test suite itself calls directly) has no
protection. `lexical_mode` is accidentally safe because `LexicalMode(...)` raises;
`exploration` and `artifact_path` are not.

**Fix:** move the value allow-list into `arena/candidate.py` next to the key allow-list and
have both `validate()` and argparse consume it:

```python
ALLOWED_OVERRIDE_VALUES: dict[str, frozenset[str] | None] = {
    "exploration": frozenset({"disabled", "tail-only"}),
    "lexical_mode": frozenset({"auto", "fts5", "fallback"}),
    "artifact_path": None,  # a path, not an enumeration
}
# inside validate(), after the key checks:
for key, value in self.overrides:
    allowed = ALLOWED_OVERRIDE_VALUES.get(key)
    if allowed is not None and value not in allowed:
        raise ValueError(f"override {key} must be one of {sorted(allowed)}, got {value!r}")
```

and in `run_arena.py`, build `choices=sorted(ALLOWED_OVERRIDE_VALUES["exploration"])`.

---

### WR-02: `write_leaderboard` is a non-atomic two-file write to git-tracked artifacts, and renders after the JSON is already overwritten

**File:** `arena/leaderboard.py:685-695`

**Issue:**

```python
write_json(json_path, payload)
markdown_path.write_text(render_markdown(payload), encoding="utf-8")
```

Both targets are committed (`experiments/baselines/leaderboard.json` and
`experiments/LEADERBOARD.md`). `leaderboard.json` is destroyed and rewritten *before*
`render_markdown` has even been called, so any renderer failure — a `KeyError` on a payload
from a different schema version, a `TypeError` from `_cell(None)` on a field that becomes
nullable, a `float(value)` on a string — leaves a new JSON beside a stale Markdown, with
the old JSON gone. An interruption between the two writes does the same. Nothing detects
it at write time; `tests/test_arena_leaderboard.py:768` only notices afterwards, and by
then the pre-write state is unrecoverable.

This is the same defect class that plan 01-xx just closed in the sibling writer:
`import_legacy_results.py:168-183` stages both files and publishes them with one directory
rename precisely because *"Two files must land together or not at all."* The asymmetry is
the finding — and this writer's targets are committed, whereas that one's were not yet.

**Fix:** render first, then write, and stage each file so a partial write is not observable:

```python
def write_leaderboard(payload, *, json_path=LEADERBOARD_JSON_PATH, markdown_path=LEADERBOARD_MARKDOWN_PATH):
    # Rendered BEFORE anything is written: a renderer failure must not consume the JSON.
    rendered = render_markdown(payload)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    for path, text in (
        (json_path, json.dumps(payload, indent=2, sort_keys=True) + "\n"),
        (markdown_path, rendered),
    ):
        staging = path.with_name(f".{path.name}.partial")
        staging.write_text(text, encoding="utf-8", newline="\n")
        os.replace(staging, path)
    return (json_path, markdown_path)
```

---

### WR-03: the staging-directory `.gitignore` claim is false — an interrupted arena run is stageable and committable

**File:** `arena/arena.py:131-134`, `arena/import_legacy_results.py:168-175`

**Issue:** The comment asserts a mitigation that does not exist:

> The `.{run_id}-` prefix is not cosmetic: it puts the in-progress directory under
> .gitignore's `experiments/.*-/` rule, so an interrupted run cannot be staged and
> mistaken for a completed record (T-01-19).

It fails on two counts. First, depth: a gitignore pattern containing a slash is anchored,
and `*` does not cross `/`, so `experiments/.*-/` matches only a direct child of
`experiments/`. The staging directory lives at `experiments/baselines/.{run_id}-XXXX/`,
one level deeper, and `!experiments/baselines/` re-includes that whole subtree. Second,
the name: `tempfile.TemporaryDirectory` appends random characters *after* the prefix, so
the directory is `.run-x-ab12cd`, which does not end in `-` as the rule requires.

Verified directly:

```
$ git check-ignore -v experiments/baselines/.run-x-ab12cd/summary.json ; echo exit=$?
exit=1
$ git status --porcelain --untracked-files=all
?? experiments/baselines/.run-x-ab12cd/summary.json
```

Consequence: a run killed hard (not raising — `TemporaryDirectory` cleans up on an
exception) leaves a half-written record inside the committed baseline directory that
`git add -A` will commit. It also breaks
`tests/test_arena_leaderboard.py:776` immediately, which iterates every `is_dir()` under
`experiments/baselines/` and reads `summary.json` unconditionally — a staging corpse
without that file raises `FileNotFoundError` rather than the guard's own message.

**Fix:** either add an anchored rule that actually matches — `experiments/baselines/.*/`
— or, better, stage outside the published tree and make the invariant structural:

```python
with tempfile.TemporaryDirectory(prefix=f".{run_id}-", dir=root.parent) as temporary:
```

paired with `experiments/.*/` in `.gitignore`. Also make the leaderboard test skip
directories lacking `summary.json` so a corpse produces one legible failure rather than a
crash. If the current placement is kept, correct the comment — it currently states a
protection that `git check-ignore` disproves.

---

### WR-04: nothing checks that two compared arms measured the same catalog and dataset

**File:** `arena/adjudication.py:194-207`, `arena/run_arena.py:134-165`

**Issue:** `_require_paired` (statistics.py:107-117) enforces identical `sample_id`
ordering, which is the pairing invariant. Nothing enforces the *provenance* invariant:
that both arms were evaluated against the same catalog and the same dataset.
`CandidateSpec` carries `catalog_sha256` and `dataset_sha256` — the whole point of
recording them — and no consumer ever compares them across arms. `adjudicate` receives
two `CandidateArm`s each holding a full `spec` and reads only `.fingerprint` and `.name`.

So two records built on different dataset revisions with the same 200 sample ids adjudicate
cleanly, and the resulting delta — a difference of two scores measured on different data —
is published with a bootstrap CI, a permutation p, an MDD and a verdict, all of which are
meaningless. Nothing warns. The committed report happens to be safe (run-a/b/c share a
digest), and the one record carrying `"unknown"` for both digests, `anchor-legacy`, is
correctly routed through `--include` rather than adjudicated — but that is operator
discipline, not an enforced invariant, and `--include` is not what stops it.

**Fix:** assert digest agreement where the arms meet, and refuse an unverifiable arm
explicitly:

```python
for candidate in candidates:
    if candidate.spec.fingerprint == baseline_fingerprint:
        raise ValueError("a candidate must not share the baseline's fingerprint")
    for field in ("catalog_sha256", "dataset_sha256"):
        mine = getattr(candidate.spec, field)
        theirs = getattr(baseline.spec, field)
        if mine != theirs:
            raise ValueError(
                f"{candidate.spec.name} was measured against a different {field}"
                f" ({mine} vs baseline {theirs}); a paired delta across two datasets"
                " is not a comparison"
            )
        if mine == "unknown":
            raise ValueError(
                f"{candidate.spec.name} cannot state which {field} it measured;"
                " route a provenance-free record through --include, never --candidate"
            )
```

---

### WR-05: `assumptions.resample_count` fabricates `RESAMPLE_COUNT` in exactly the two cases where it does not know

**File:** `arena/leaderboard.py:389-395`

**Issue:**

```python
observed_resamples = tuple(sorted({row.resamples for row in rows}))
resample_count = observed_resamples[0] if len(observed_resamples) == 1 else RESAMPLE_COUNT
```

The comment directly above states the field's whole purpose: *"Describes what actually
produced these rows rather than what the constant says. A committed report generated at a
test resample count is exactly the failure T-01-20 guards against, and it is only visible
if the number is recorded."* The fallback breaks that contract in both branches it covers:

- `rows == ()` — the field reports `10000` for a report that resampled nothing. Compare
  `holm_family_size` twelve lines below, which the comment explicitly justifies as *"Zero
  is the honest answer for a report that adjudicated nothing."* The two adjacent fields
  answer the same question with opposite honesty conventions.
- rows disagree — the one case where the field could actually catch a mixed-provenance
  report is the case where it silently prints the production constant instead.

**Fix:** report the truth, or refuse:

```python
if len(observed_resamples) > 1:
    raise ArenaStoreError(
        f"adjudication rows disagree on resample count {observed_resamples};"
        " one report must describe one resampling budget"
    )
resample_count = observed_resamples[0] if observed_resamples else None
```

`None` serializes as JSON `null`, and `render_markdown` prints it as `None` in the
metadata line — legible, and honest for a report with no adjudication.

---

### WR-06: `_SampleMappingAgent` is dead code whose docstring describes a join that never happens

**File:** `arena/arena.py:54-91`, `arena/arena.py:147-150`

**Issue:** The wrapper's only purpose is `session_to_sample`, and the docstring explains
the join in detail: *"recording each reset maps that UUID back to the public sample id.
The join happens only AFTER evaluate() returns."* No join happens. `run_candidate` never
reads `agent.session_to_sample`; it builds outcomes from `row["sample_id"]` in the harness
result (arena.py:183-184). Verified across the repository:

```
$ grep -rn "session_to_sample" arena/ experiments/
arena/arena.py:75, arena/arena.py:82          <- written, never read
experiments/run_public.py:44, :48, :228       <- written AND read
```

`run_public.py` needs it because it passes a real `trace` and must attribute JSONL trace
events to samples; `arena/arena.py` passes `trace=None` (line 146), so there is nothing to
attribute. The evaluator already emits `sample_id` on every session row
(`evaluator/local_evaluator.py:270`), which is what `_session_outcome` consumes.

Cost of keeping it: ~38 lines of a hand-copy of `run_public.py:31-56` (the module comment
argues the duplication is deliberate — but the duplication is of code that has no
consumer), plus a real hazard. The wrapper forwards exactly `reset`/`respond`/`close`, so
if the harness ever calls another `Agent` method the arena path breaks while the frozen
`run_public.py` path does not; and its `SampleMappingTest` class (five tests) asserts
behaviour that no production path depends on.

**Fix:** delete `_SampleMappingAgent`, pass the `Agent` straight to `evaluate`, and delete
`SampleMappingTest`. If the wrapper is instead being kept for a Phase 3 tracing plan, say
so and correct the docstring — the current text asserts a join that a reader will look for
and not find.

---

### WR-07: `publish` deletes the destination before knowing the retry can succeed, and `rmtree` failure escapes as a bare `OSError`

**File:** `arena/store.py:125-138`

**Issue:** Building on the disclosed residual risk (that a directory at `destination`
cannot be distinguished from a completed record), two exposures are additional rather than
covered by that disclosure:

1. `shutil.rmtree(destination)` fires **before** the second `os.replace` is attempted. If
   the retry also fails — the same ACL denial, antivirus lock or cross-device condition
   that plausibly caused the first failure — the committed record is already gone and the
   working directory is then removed by `TemporaryDirectory`'s cleanup on scope exit. Both
   copies are lost. `tests/test_arena_metrics.py:435` exercises exactly this path (it
   patches `os.replace` to always raise) and asserts only the message, silently accepting
   the destruction.
2. `shutil.rmtree` can raise mid-delete. That `OSError` propagates out of `publish`
   unwrapped, so a caller catching `ArenaStoreError` misses it, and the destination is left
   *partially* deleted — a committed record with some files removed, which is worse than
   either outcome the docstring contemplates.

The docstring's closing sentence is false for both: *"every other failure — a cross-device
link, an ACL denial, a path-too-long, an antivirus lock — is reported by name with its
cause attached and nothing is removed."* In case 2 something is removed, and the failure is
not reported by name.

**Fix:** rename the corpse aside instead of deleting it, so no retry failure can be
destructive, and wrap the cleanup:

```python
        quarantine = destination.with_name(f".{destination.name}-superseded")
        try:
            if quarantine.exists():
                shutil.rmtree(quarantine)
            os.replace(destination, quarantine)
        except OSError as clear_error:
            raise ArenaStoreError(
                f"could not clear {destination} before publishing: {clear_error}"
            ) from clear_error
        try:
            os.replace(working, destination)
        except OSError as retry_error:
            os.replace(quarantine, destination)  # put it back; lose nothing
            raise ArenaStoreError(
                f"could not publish to {destination} after clearing it: {retry_error}"
            ) from retry_error
        shutil.rmtree(quarantine)
```

This also gives the positive corpse marker the disclosure says is needed: a
`.{name}-superseded` directory is unambiguously evidence that a publish moved something
aside, and an operator can inspect it rather than reconstruct it.

---

### WR-08: `HOW_TO_READ` states a sigma-hat range that the committed report's own only real row falls outside

**File:** `arena/leaderboard.py:67-76`, `arena/leaderboard.py:78-87`

**Issue:** Item 2 tells the reader that sigma-hat is *"typically 0.002 to 0.008 on this
data"*; item 3 tells them a realistic candidate yields *"an MDD of roughly 0.0104 —
detectable at n=200"* and that the paired SE is *"roughly 0.0037"*. The only non-degenerate
adjudication row in the very report those paragraphs preface reads:

```
fallback-lexical: standard_error 0.012845110588600097
                  minimum_detectable_difference 0.0359866719500484
```

1.6x above the top of the stated range, and 3.5x the quoted MDD. The block's stated job is
to convert apparent inconsistencies into demonstrations of care; here it manufactures one.
A judge who reads item 2 and then the sigma-hat column sees the guide contradicted by the
table it introduces on the same page. (Item 3 is scoped to a specific synthetic candidate
and is defensible as written; item 2's "typically ... on this data" is not.)

**Fix:** either widen the claim to the measured range and name where the wide value comes
from — a lexical-backend swap moves individual sessions far more than a rank promotion
does, so its paired SE is legitimately larger — or drop the numeric range and keep only the
methodological point (that sigma-hat is the paired-difference SE, not the absolute binomial
SE). A range asserted in prose that the payload can falsify is a maintenance trap; if it is
kept, add a test that reads `leaderboard.json` and fails when any row's `standard_error`
falls outside the range the prose states.

---

### WR-09: `import_legacy_results` never validates `--output`, yet `destination.name` becomes a hashed identity field

**File:** `arena/import_legacy_results.py:134-163`, `arena/import_legacy_results.py:191-193`

**Issue:** The sibling writer routes its destination through `validate_run_id` and
`resolve_run_directory` (arena.py:124-127) — an allow-list plus a resolved-path containment
check described as defence in depth for T-01-06. This entry point applies neither:
`--output` is an unchecked `Path`, `destination.parent.mkdir(parents=True)` will create
any tree, and `summary["run_id"] = destination.name` (line 117) writes whatever the last
path component happened to be.

That value is not inert. `arena/leaderboard.py:210` reads it back as `run_id`, and
`spec_name_from_record(record, run_id)` (candidate.py:117-125) falls back to it for
`CandidateSpec.name` when the record carries no `candidate_name` — which is exactly the
rescued-anchor case this CLI produces. So an arbitrary, unvalidated path component becomes
part of the record's hashed identity. `--output experiments/baselines/` (trailing slash)
silently names the record `baselines`; `--output ../elsewhere/x` writes outside the
baseline root entirely.

**Fix:** apply the same boundary the sibling applies. The module deliberately imports
nothing from `arena`, so inline the two checks rather than importing them:

```python
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")  # mirrors arena/store.py:17

if not _RUN_ID_RE.fullmatch(destination.name):
    raise ValueError(
        f"import destination name is not a usable run id: {destination.name!r}"
    )
```

placed before `_build_summary` so a bad name cannot reach the hashed payload.

---

### WR-10: the evaluator digest pin is duplicated across two test modules, and only one discloses the line-ending caveat

**File:** `tests/test_arena_metrics.py:391-396`, `tests/test_arena_boundary.py:15`

**Issue:** `84ea899707452de249ca62abee77c4b40ab7a3139b5cc798ac30c9f521f91b30` appears twice.
`test_arena_boundary.py` owns it as a named constant with a careful comment and a failure
message that explicitly anticipates *"or this checkout normalizes line endings
differently"*. `test_arena_metrics.py` repeats the bare literal inside an assertion whose
comment says only *"Also a standing check that the immutable scoring harness is
unmodified."*

The pin is the CRLF working-tree digest, verified:

```
worktree sha:       84ea899707452de249ca62abee77c4b40ab7a3139b5cc798ac30c9f521f91b30  (312 CRLF pairs)
LF-normalized sha:  79a5ea06f9a1b8c5036f30efa85dc1f36b8f6b06eb8feb8f545dfa767bc45564
$ git ls-files --eol evaluator/local_evaluator.py
i/lf    w/crlf
```

The index stores LF, so any checkout without `core.autocrlf=true` — every Linux/macOS
machine, and any Windows machine without that setting — fails both tests with a message
claiming the immutable evaluator was modified. `test_arena_boundary.py` at least tells the
reader why; `test_arena_metrics.py` reads as a genuine tamper alarm. And a deliberate
re-pin in the module that owns the constant leaves the duplicate stale, so the guard fires
on the wrong thing.

**Fix:** import the single owner rather than repeating the literal, and normalize the
comparison so the guard tests bytes-that-matter rather than checkout configuration:

```python
from tests.test_arena_boundary import EVALUATOR_SHA256
...
def test_sha256_file_matches_the_immutable_evaluator_digest(self) -> None:
    # sha256_file hashes worktree bytes, so the pin is line-ending dependent by
    # construction; test_arena_boundary owns the constant and states why.
    self.assertEqual(sha256_file(Path("evaluator/local_evaluator.py")), EVALUATOR_SHA256)
```

and add a `.gitattributes` entry (`evaluator/local_evaluator.py -text` or `* text=auto
eol=lf`) so the immutable file checks out identically everywhere and the pin becomes
platform-independent.

## Info

### IN-01: `Path.write_text` without `newline="\n"` makes every record platform-dependent

**File:** `arena/store.py:56-71`, `arena/import_legacy_results.py:62-73`, `arena/leaderboard.py:694`

**Issue:** `Path.write_text` opens in text mode with `newline=None`, which translates `\n`
to `os.linesep`. Verified: on this machine `write_text("a\nb\n")` produces
`b'a\r\nb\r\n'`. So `sessions.jsonl`, `summary.json`, `leaderboard.json` and
`LEADERBOARD.md` are CRLF on Windows and LF on POSIX. `write_sessions`' comment claims
*"the fingerprint and byte-reproducibility assertions downstream compare these files byte
for byte"* — true within one platform, false across two. `core.autocrlf=true` normalizes
the index here, and every read path uses `read_text` (which translates back), so nothing
currently breaks; but WR-10 shows what happens when a digest is taken over these bytes.
The frozen `experiments/run_public.py:283-293` has the same pattern, so this is a
pre-existing convention rather than new drift.

**Fix:** pass `newline="\n"` in all four writers, and add `* text=auto eol=lf` to
`.gitattributes` so the committed records are LF everywhere.

### IN-02: `expected_max_of_k` validates `panels` only after the `k == 1` early return

**File:** `arena/statistics.py:351-356`

**Issue:** `expected_max_of_k(1, panels=1999)` returns `0.0`; `expected_max_of_k(2,
panels=1999)` raises. Argument validation that depends on which branch the function takes
means a caller cannot rely on a bad argument being reported.

**Fix:** move the `if panels % 2:` check above the `if k == 1:` return, next to the `k < 1`
check.

### IN-03: `result.pop("sessions")` raises a bare `KeyError` past the CLI's exception filter

**File:** `arena/arena.py:183-185`, `arena/run_arena.py:119`

**Issue:** Every other contract violation in `run_candidate` raises `ValueError` or
`ArenaStoreError`, both of which `_run` catches and converts to `parser.error`. A harness
result without a `"sessions"` key produces an uncaught `KeyError` and a raw traceback,
after the evaluation has already run.

**Fix:** check with the same discipline as the collision guard immediately above:

```python
if "sessions" not in result:
    raise ArenaStoreError("harness result carries no sessions")
```

### IN-04: `best_rank` is bounded by `MAX_TURNS`, conflating a turn budget with a slate depth

**File:** `arena/metrics.py:40-41`

**Issue:** `best_rank` is a rank within a slate, bounded by the evaluator's `TOP_K = 10`;
`first_hit_turn` is bounded by `MAX_TURNS = 10`. They are numerically equal today and
independent in principle, so validating both against `MAX_TURNS` means a future change to
the turn budget silently moves the rank bound. The message also hardcodes `"between 1 and
10"` rather than interpolating the constant, so it would lie after any re-tune.

**Fix:** add `MAX_SLATE_RANK = 10  # evaluator/local_evaluator.py:16 (TOP_K)`, use it for
`best_rank`, and interpolate both constants into their messages.

### IN-05: `--output-root` writes the Markdown outside the root it names

**File:** `arena/run_arena.py:131-132`

**Issue:** `markdown_path = output_root.parent / "LEADERBOARD.md"`. The comment says this
lets *"a test or a dry run point the whole report at a temporary tree"*, but the Markdown
half lands in the root's **parent**: `--output-root /tmp/arena-scratch` writes
`/tmp/LEADERBOARD.md`, and `--output-root baselines` writes `./LEADERBOARD.md`. Only the
default value happens to produce the intended pair. Confirmed by inspection of the four
plausible roots.

**Fix:** keep both artifacts inside the named root and derive nothing from `.parent`:

```python
json_path = output_root / LEADERBOARD_JSON_PATH.name
markdown_path = output_root / LEADERBOARD_MARKDOWN_PATH.name
```

then move the committed Markdown to `experiments/baselines/LEADERBOARD.md`, or add an
explicit `--markdown-path` flag rather than inferring one path from another.

---

_Reviewed: 2026-08-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
