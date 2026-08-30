---
phase: 01-measurement-rig-core
reviewed: 2026-08-30T10:36:25Z
depth: standard
files_reviewed: 22
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
  - tests/test_arena_leaderboard.py
  - tests/test_arena_metrics.py
  - tests/test_arena_runner.py
  - tests/test_arena_statistics.py
  - .gitignore
  - experiments/LEADERBOARD.md
  - experiments/RUNS.md
findings:
  critical: 3
  warning: 13
  info: 6
  total: 22
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-08-30T10:36:25Z
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

The rig is unusually well-documented and the statistical primitives in
`arena/statistics.py` are, taken individually, correct: Holm's running maximum is
present, the Phipson-Smyth `+1/+1` is present in both terms, the MDD multiplier is
computed rather than hard-coded, Simpson integration matches its closed-form anchors,
seeds are content-derived and never clock-derived, and every sort carries an explicit
tie-break. I found no determinism violation, no unseeded RNG, no set-iteration ordering
leak, and no path traversal or injection surface.

The defects are concentrated in `arena/adjudication.py`, in the *composition* of those
primitives into the D-22/D-23 verdict rule. Two of them are demonstrable, reproducible
false verdicts on realistic inputs, and both fail in the exact direction the phase claims
to prevent:

1. A candidate with a **+0.15 TechnicalScore** improvement (15x the ship floor) is
   reported as `no difference`, because the zero-variance guard treats "the delta does
   not move under resampling" as "there is no delta". The emitted row is internally
   contradictory: `corrected_delta = 0.15` beside `clears_practical_floor = false`.
2. A candidate that **regresses HR@10 by 3 points and regresses MRR** is adjudicated
   `win`, because the D-23 exchange-rate criterion becomes vacuous whenever MTTC
   improves. The criterion that exists to make an HR@10 regression disqualifying does
   not fire.

Both were executed against the checked-in code, not inferred; the reproducers are in the
findings. Neither is covered by the 339-test suite, because every adjudication fixture in
`tests/test_arena_adjudication.py` is built to have non-uniform per-session effects and a
positive `mttc_delta`.

Beyond those, the trust-boundary hardening is asymmetric: `arena/import_legacy_results.py`
will silently overwrite a committed baseline record where `arena/arena.py` refuses to;
`arena/leaderboard.py` recomputes a record's fingerprint but never checks it against the
one the record stores (that check lives only in a test over the already-committed set);
and `arena/run_arena.py`'s override construction contradicts its own stated invariant
about omitting unset flags.

---

## Critical Issues

### CR-01: Zero-variance guard reports a large real effect as "no difference"

**BLOCKER**
**File:** `arena/adjudication.py:207-209`, `arena/adjudication.py:264-277`

**Issue:** `degenerate` is defined purely as `standard_error <= ZERO_VARIANCE_TOLERANCE`.
The comment (`adjudication.py:202-206`) justifies it with the identical-arms case, where
delta and SE collapse *together*. But SE and delta are independent quantities. The
bootstrap SE is zero whenever the delta is invariant to *which* sessions are resampled —
i.e. whenever the candidate improves every session by the same amount — regardless of how
large that delta is.

When that happens the branch hard-codes `holm_p = 1.0`, `detectable_difference = 0.0`,
`clears_practical_floor = False` and `failed_criteria = ("holm_significance",
"practical_floor")` while `corrected_delta` keeps the *real* delta. `classify_verdict`
then returns `NO_DIFFERENCE`. The permutation test — which would have returned the
Phipson-Smyth floor `1/(R+1)` here — is short-circuited at `adjudication.py:214-216` and
never runs.

Reproduced against the checked-in code:

```
baseline  = sessions_from_ranks((2,)*200)   # every session hits at rank 2
candidate = sessions_from_ranks((1,)*200)   # every session hits at rank 1

delta            = 0.15000000000000002
standard_error   = 0.0
permutation_p    = 1.0        <- asserted, never measured
holm_p           = 1.0
corrected_delta  = 0.15000000000000002
clears_practical_floor = False   <- contradicts corrected_delta on the same row
VERDICT          = no difference
```

A uniform rank-2 -> rank-1 promotion is exactly the class of ranking change this project
says it is hunting (`CLAUDE.md`: "0.151 points sit in ranking"). The rig would tell the
operator to discard it. The emitted `AdjudicationRow` also violates the module's own
auditability contract (`adjudication.py:93-95`): a reader who re-derives
`corrected_delta >= PRACTICAL_FLOOR` by hand gets `True` while the row says `False`.

No test catches this. `_WIN_BASELINE`/`_WIN_CANDIDATE`, `_FLOOR_*`, `_SMALL_*` and the
anchor controls all have heterogeneous per-session effects, so their SE is never zero.

**Fix:** The guard must be conditioned on the *delta*, not only on the SE. A zero-SE
result with a nonzero delta is a perfectly detectable effect and should go down the
normal path (the permutation test handles it correctly — every sign-flip that moves any
session changes the statistic, so `p` lands at the floor).

```python
degenerate = tuple(
    result.standard_error <= ZERO_VARIANCE_TOLERANCE
    and abs(result.delta) <= ZERO_VARIANCE_TOLERANCE
    for result in bootstraps
)
```

The `abs(delta) >= mdd` reading `0 >= 0 == True` that Pitfall 5 warns about only arises
when both are zero, so this narrower guard still covers the case it was written for. Add
a regression test with the uniform-promotion fixture above asserting the verdict is
**not** `NO_DIFFERENCE`.

---

### CR-02: The HR@10 exchange-rate criterion is vacuous when MTTC improves, producing a `win` on a double regression

**BLOCKER**
**File:** `arena/adjudication.py:295-297`

**Issue:**

```python
exchange_rate_ok = hit_rate_delta >= 0.0 or (
    mrr_delta > EXCHANGE_RATE_PER_MTTC * mttc_delta
)
```

`mttc_delta = candidate_mttc - baseline_mttc`, so an MTTC *improvement* is negative. When
`mttc_delta < 0` the right-hand side is negative and the condition is satisfied by any
`mrr_delta` above a negative threshold — including a negative one. Nothing requires
`mrr_delta > 0`, yet the constant's own docstring (`adjudication.py:31-35`) says "an
HR@10 regression is forgiven only when the **MRR gain** exceeds 0.0667 x the MTTC
movement". There is no gain in the passing case.

Reproduced against the checked-in code (100 sessions, baseline all rank 3 / turn 8;
candidate drops 3 sessions to misses and pulls 60 others forward to turn 1):

```
hit_rate_delta = -0.030000000000000027   <- HR@10 regressed
mrr_delta      = -0.010000000000000009   <- MRR regressed too
mttc_delta     = -4.109999999999999      <- MTTC improved, so the RHS is negative
exchange_ok    = True
failed         = ()
verdict        = win
```

`clears_practical_floor` passes here because the 0.20-weighted efficiency term alone
carries the delta over 0.01. So the single criterion whose entire job is to stop an HR@10
regression from shipping does not fire, and the rig returns `win` — with an empty
`failed_criteria`, which the committed leaderboard test
(`tests/test_arena_leaderboard.py:508`) treats as the definition of a win.

The existing tests only exercise `mttc_delta > 0` (`_TRADE_UNDERPAID` / `_TRADE_PAID`
both add misses without pulling other sessions forward), so the negative-`mttc_delta`
half of the branch is untested.

**Fix:** Require an actual MRR gain, and compare TechnicalScore-equivalent magnitudes
rather than raw units, so the criterion cannot be satisfied by an MTTC term the practical
floor has already counted:

```python
exchange_rate_ok = hit_rate_delta >= 0.0 or (
    mrr_delta > 0.0
    and mrr_delta > EXCHANGE_RATE_PER_MTTC * abs(mttc_delta)
)
```

Add fixtures for both sign branches of `mttc_delta`. Independently, consider whether the
criterion should scale with the *size* of the HR@10 regression — today a `-0.10` HR@10
regression is forgiven on the same terms as a `-0.005` one.

---

### CR-03: `import_legacy_results` silently overwrites an existing committed baseline record

**BLOCKER**
**File:** `arena/import_legacy_results.py:146-150`

**Issue:**

```python
destination.mkdir(parents=True, exist_ok=True)
sessions_path = destination / _SESSIONS_FILENAME
summary_path = destination / _SUMMARY_FILENAME
_write_jsonl(sessions_path, sessions)
_write_json(summary_path, summary)
```

There is no existence check and no atomic publish. `--output experiments/baselines/run-a`
overwrites the measured 200-session record for `baseline-auto-disabled` — the record that
is the **baseline of every delta in the committed leaderboard** — with provenance-free
legacy data carrying `provenance_complete: false`, `code_revision: "unknown_revision"`
and `catalog_sha256: "unknown"`. The write is also non-atomic and split across two files,
so an interruption between them leaves a record whose `sessions.jsonl` and `summary.json`
describe different runs, which nothing downstream detects.

This is asymmetric with the sibling writer: `arena/arena.py:110-111` explicitly refuses
(`FileExistsError`) and publishes atomically through a temporary directory
(`arena/store.py:100-119`) for exactly this reason. The migration path, which by
construction writes *lower*-provenance data, is the one without the guard.

The module's opening comment says it deliberately imports nothing from `arena/`. That is
a fine rule, but it does not require dropping the safety property — the check is three
lines of stdlib.

**Fix:**

```python
if destination.exists():
    raise ValueError(f"refusing to overwrite an existing record: {destination}")
destination.mkdir(parents=True, exist_ok=False)
```

Better: stage both files into a sibling temporary directory and `os.replace` the
directory into place, mirroring `arena/store.publish`. Also add an `--force` flag if
re-import is genuinely wanted, so clobbering is explicit.

---

## Warnings

### WR-01: The CLI always injects `exploration` and `lexical_mode` defaults into the fingerprinted overrides, contradicting its own stated invariant

**WARNING**
**File:** `arena/run_arena.py:60-64`, `arena/run_arena.py:164-174`

**Issue:** The comment claims "An unset flag is OMITTED rather than recorded as None: it
must leave the fingerprint identical to a run that never mentioned it, otherwise one
configuration fingerprints two ways." The filter is `if getattr(args, flag) is not None` —
but `--exploration` defaults to `"disabled"` and `--lexical-mode` defaults to `"auto"`,
never `None`. Only `--artifact-path` (default `None`) is actually omitted. Confirmed on
the committed records: every CLI-produced summary carries
`overrides = {"exploration": ..., "lexical_mode": ...}`.

Consequences:

- The default-everything configuration fingerprints one way through the CLI
  (`{"exploration": "disabled", "lexical_mode": "auto"}`) and a different way through
  `build_candidate_spec(..., overrides={})` or `import_legacy_results` (`{}`). Two
  fingerprints, one configuration — the failure this module is built around.
- The half-implemented rule is itself a hazard: passing `--artifact-path` with its
  effective default value produces a different fingerprint from omitting it, for an
  identical agent.
- The `adjudicate` guard at `arena/adjudication.py:168-170` ("a candidate must not share
  the baseline's fingerprint") can therefore be passed by two specs describing the same
  configuration.

**Fix:** Pick one rule and enforce it. Simplest and most robust: set every override flag's
argparse `default=None`, record only what the operator actually passed, and let the Agent
constructor supply its own defaults — then the fingerprint describes the *invocation*
consistently across every entry path. Otherwise, canonicalise in `candidate_overrides()`
by filling every `ALLOWED_OVERRIDES` key with its Agent default, so `{}` and
`{"exploration": "disabled", "lexical_mode": "auto"}` collapse to one digest. Either way,
fix the comment.

---

### WR-02: A record's stored fingerprint is never checked against the one the reader derives

**WARNING**
**File:** `arena/leaderboard.py:155-175`

**Issue:** `_spec_from_payload` rebuilds a `CandidateSpec` from `summary.json` and every
downstream consumer uses `spec.fingerprint` — as the leaderboard identity, as the
`baseline_fingerprint` in the report, as the champion tie-break key, and as the RNG seed
via `pair_seed`. But the record's own `record["fingerprint"]`, written by
`arena/arena.py:152`, is never read and never compared.

`experiments/RUNS.md:59-64` records that this exact divergence shipped once already
("a record's stored fingerprint differed from the one the report derived for it") and
that it silently changed the CI, p, MDD and sigma-hat. The remediation was
`SPEC_NAME_FIELD` plus `spec_name_from_record` — which fixes *that* instance — and
`test_every_record_derives_the_fingerprint_it_stores`
(`tests/test_arena_leaderboard.py:535-563`), which only runs over records that are
already committed. Any *new* record with a drifted reconstruction (a missing field
defaulting to `"unknown"`, an override value that round-trips as a non-string) is
reported under a fingerprint that appears nowhere in its own `summary.json`, and the
operator finds out only after committing it.

**Fix:** Fail closed in the code path, not only in the suite:

```python
spec.validate()
stored = record.get("fingerprint")
if stored is not None and stored != spec.fingerprint:
    raise ArenaStoreError(
        f"{run_directory.name} stores fingerprint {stored} but derives {spec.fingerprint}"
    )
return spec
```

(`stored is None` remains legal for the rescued anchor-legacy record, which stores none.)

---

### WR-03: `adjudicate` rejects a candidate matching the baseline but not duplicate candidates

**WARNING**
**File:** `arena/adjudication.py:167-170`; `arena/run_arena.py:99-119`; `arena/leaderboard.py:219-235`

**Issue:** The guard only compares each candidate against the baseline. Passing the same
record twice (`--candidate X --candidate X`, or the same configuration under two run ids)
is accepted and:

- doubles the Holm family size, weakening every genuine comparison (`total` at
  `arena/statistics.py:237`),
- inflates `correction_k`, inflating the winner's-curse subtraction on every row,
- and in `build_leaderboard`, `summaries` (line 219), `scores` (line 222) and `names`
  (line 385) are all keyed by fingerprint, so the duplicates silently collapse into one
  entry in those maps while `ordered` still yields two rows.

Nothing in `run_arena._adjudicate` deduplicates `--candidate` / `--include`, and the same
directory can legitimately appear in both lists.

**Fix:** In `adjudicate`, after the baseline check:

```python
fingerprints = [candidate.spec.fingerprint for candidate in candidates]
if len(set(fingerprints)) != len(fingerprints):
    raise ValueError("candidates must have distinct fingerprints")
```

And in `run_arena._adjudicate`, reject a directory that appears in more than one of
`--baseline` / `--candidate` / `--include`.

---

### WR-04: Bootstrap percentile indices are wrong at small R and asymmetric at every R

**WARNING**
**File:** `arena/statistics.py:154-155`

**Issue:**

```python
lower=deltas[int(0.025 * resamples)],
upper=deltas[int(0.975 * resamples) - 1],
```

`_require_resamples` (line 101-103) admits `resamples >= 1`, but the index arithmetic is
only meaningful well above that. Measured on the checked-in code:

```
R=1   lower=0.101250  upper=0.101250
R=2   lower=0.090000  upper=0.090000   <- "97.5th percentile" is the MINIMUM replicate
R=3   lower=0.045000  upper=0.090000
```

At `R=2`, `int(0.975*2) - 1 == 0`, so `upper` is `deltas[0]`. The interval silently
degenerates to a point at the low end, and for any distribution with `min < max` the
reported upper bound is below the true median. The two bounds are also asymmetric at
every R: at `R=10_000` `lower` is order statistic 251 (2.51%) while `upper` is 9750
(97.50%), giving 94.99% nominal coverage rather than 95%.

Production always runs at `R=10_000`, so the practical impact today is the 0.01%
coverage shortfall. But `resamples` is a public keyword argument the suite already uses
at 200 and 500, and a future caller at a smaller R gets a silently wrong interval with no
error.

**Fix:** Raise the floor and make the indices symmetric:

```python
_MINIMUM_RESAMPLES = 40  # below this a 95% percentile interval has no resolution

def _require_resamples(resamples: int) -> None:
    if resamples < _MINIMUM_RESAMPLES:
        raise ValueError(f"resample count must be at least {_MINIMUM_RESAMPLES}")
...
lower_index = max(0, int(math.floor(0.025 * resamples)))
upper_index = min(resamples - 1, int(math.ceil(0.975 * resamples)) - 1)
```

---

### WR-05: Degenerate arms consume Holm family budget and `correction_k` on an asserted, never-measured p-value

**WARNING**
**File:** `arena/adjudication.py:212-216`, `arena/adjudication.py:233`, `arena/adjudication.py:244-246`

**Issue:** A degenerate candidate never runs `paired_permutation`; `1.0` is appended
directly. That synthetic value is then fed into `holm_bonferroni` alongside the real
p-values, so it increments `total` and inflates the multiplier applied to every genuine
comparison. It also counts toward `correction_k`, inflating the winner's-curse
subtraction on rows that had nothing to do with it.

This is live in the committed report: `run-c` is byte-identical to the baseline `run-a`
(verified: `sessions.jsonl` are the same bytes), so the `fallback-lexical` row was
Holm-adjusted at `m=2` and corrected at `k=2` because of an arm that could not have been
a selection option — its delta is exactly `0.0`. Both directions are conservative, so no
false positive results, but the rig is throwing away power it was designed to protect,
and `run_arena.py:186-191` already establishes the pattern (`--include`) for arms that
belong in the report without joining the family.

**Fix:** Either run the permutation for degenerate arms too (it is cheap and gives an
honest p at the floor), or exclude zero-delta/zero-variance arms from both the Holm
family and `correction_k` while still emitting their descriptive row. Whichever is
chosen, state it in the `assumptions` block so a reader can see which arms formed the
family.

---

### WR-06: `SessionOutcome.validate()` does not tie `best_rank` to `hit` or to `reciprocal_rank`

**WARNING**
**File:** `arena/metrics.py:37-47`

**Issue:** The only cross-field check is `hit != (first_hit_turn is not None)`.
`best_rank` and `reciprocal_rank` are validated only for range. So a session row with
`best_rank=5, first_hit_turn=None, hit=False` validates cleanly, and then:

- `metric_summary` counts it as a **miss** (`hit_rate_at_10`),
- `hit_rate_curve` counts it as a **hit at depth 5 and 10** (`metrics.py:150-153`).

The report would print an HR@10 in the Candidates table that disagrees with `HR@10` in
the HitRate@K curve table for the same row, with no error anywhere. Likewise
`reciprocal_rank=1.0` with `best_rank=10` validates, and MRR carries 30% of
TechnicalScore.

`arena/store.load_sessions` (line 74-97) is the untrusted boundary here — it parses
arbitrary JSONL, including the hand-rescued `anchor-legacy` record and anything an
operator edits. The module comment at `store.py:79-80` claims "Every field is explicitly
coerced and then validated before it can reach a statistic", which is only half true.

**Fix:**

```python
if (self.best_rank is not None) != self.hit:
    raise ValueError("best_rank must agree with hit")
expected = 0.0 if self.best_rank is None else 1.0 / self.best_rank
if abs(self.reciprocal_rank - expected) > 1e-12:
    raise ValueError("reciprocal_rank must equal 1/best_rank, or 0 for a miss")
```

Verify against the committed `anchor-legacy` sessions before tightening; if that record
violates it, that is itself worth knowing.

---

### WR-07: `_SampleMappingAgent` is dead weight — the harness already emits `sample_id`

**WARNING**
**File:** `arena/arena.py:36-72`, `arena/arena.py:129-132`, `arena/arena.py:146-148`

**Issue:** The class docstring says its job is to "record reset-call order [so] the join
maps that UUID back to the public sample id". But `evaluator/local_evaluator.py:269-276`
already puts `sample_id` on every session row, and `run_candidate` reads it directly at
`arena/arena.py:176` (`sample_id=str(row["sample_id"])`). `session_to_sample` is written
on every `reset` and **never read** by any production code path — only by
`tests/test_arena_runner.py`, which tests the dead attribute against itself.

So the wrapper contributes nothing but an extra indirection layer, a mutable dict that
grows with the sample count, and a 21-line docstring justifying a duplication of
`experiments/run_public.py:31-56` that is not needed here. The tests it carries
(`SampleMappingTest`, 5 methods) assert properties of machinery that does not affect any
output — including `test_mapping_is_written_during_and_read_only_after`, whose "read only
after" property is trivially true because nothing ever reads it.

**Fix:** Delete `_SampleMappingAgent` and pass the `Agent` to `evaluate` directly, keeping
`agent.close()` in the `finally` (the close-before-publish ordering asserted by
`test_agent_is_closed_before_publish` still holds). Delete `SampleMappingTest`. If the
wrapper is being kept as a seam for Phase 3, say so in the docstring instead of claiming a
correctness role it does not have.

---

### WR-08: `publish` deletes the destination on any `OSError`, and blindly retries when it does not exist

**WARNING**
**File:** `arena/store.py:114-119`

**Issue:**

```python
try:
    os.replace(working, destination)
except OSError:
    if destination.exists():
        shutil.rmtree(destination)
    os.replace(working, destination)
```

Two problems. First, the `except` catches *every* `OSError` — cross-device link, ACL
denial, path-too-long, antivirus lock — and responds by recursively deleting whatever is
at `destination`. The docstring's premise ("a destination present now is a corpse from an
earlier crashed run") holds only for `run_candidate`, which pre-checked at
`arena/arena.py:110`; the function is a module-level public helper with no such
precondition, and even in `run_candidate` there is a multi-minute TOCTOU window between
the check and the publish (337-462 s per the committed `elapsed_seconds`). A completed
committed record under `experiments/baselines/` is exactly what would be destroyed.

Second, when `destination` does not exist the code re-issues the identical `os.replace`
that just failed, so the original cause is re-raised from the wrong line with no context
about the first attempt.

**Fix:** Narrow the trigger and preserve the cause:

```python
try:
    os.replace(working, destination)
except OSError as error:
    if not destination.is_dir():
        raise ArenaStoreError(f"could not publish to {destination}: {error}") from error
    shutil.rmtree(destination)
    try:
        os.replace(working, destination)
    except OSError as retry_error:
        raise ArenaStoreError(
            f"could not publish to {destination} after clearing it: {retry_error}"
        ) from retry_error
```

---

### WR-09: Evaluator output is splatted over the provenance keys with no collision guard

**WARNING**
**File:** `arena/arena.py:151-167`

**Issue:** `**result` is the **last** entry in the summary dict literal, so any key the
harness returns wins over the arena-written provenance fields — `fingerprint`,
`candidate_name`, `code_revision`, `catalog_sha256`, `dataset_sha256`,
`provenance_complete`. Today `evaluate` returns none of those, so nothing collides. But
the sibling writer, `arena/import_legacy_results._build_summary`
(`import_legacy_results.py:107-111`), explicitly *refuses* to write when the payload
already carries a provenance key — the same hazard, guarded in one path and not the
other. A provenance field silently overwritten by harness output is a record that lies
about what produced it, and no downstream check would notice
(`test_published_summary_carries_the_fingerprint` compares the record to a spec built by
the same code path).

**Fix:** Put `**result` first, or assert non-collision:

```python
_PROVENANCE_KEYS = frozenset({
    "run_id", "fingerprint", SPEC_NAME_FIELD, "code_revision", "code_revision_dirty",
    "overrides", "catalog_sha256", "dataset_sha256", "elapsed_seconds",
    "provenance", "provenance_complete",
})
colliding = sorted(_PROVENANCE_KEYS & set(result))
if colliding:
    raise ArenaStoreError(f"harness result carries provenance keys {colliding}")
```

---

### WR-10: `resample_count` reports the module constant when rows disagree

**WARNING**
**File:** `arena/leaderboard.py:294-300`

**Issue:**

```python
observed_resamples = tuple(sorted({row.resamples for row in rows}))
resample_count = (
    observed_resamples[0] if len(observed_resamples) == 1 else RESAMPLE_COUNT
)
```

The comment says this "Describes what actually produced these rows rather than what the
constant says" and that "A committed report generated at a test resample count is exactly
the failure T-01-20 guards against". But the fallback does precisely the opposite: if the
rows disagree, the report prints `10000` — a value **no row was generated at** — and the
`assumptions.resample_count` field, which is the audit trail for T-01-20, becomes a
fabrication. The `len == 0` case (an empty adjudication, which
`test_an_empty_adjudication_renders_the_none_fallback` exercises) also silently claims
10,000 replicates for a report that ran none.

**Fix:** Report what is true, or fail:

```python
if len(observed_resamples) > 1:
    raise ValueError(f"adjudication rows disagree on resample count: {observed_resamples}")
resample_count = observed_resamples[0] if observed_resamples else None
```

---

### WR-11: `code_revision_dirty()` runs git with no `cwd` and no `timeout`

**WARNING**
**File:** `arena/candidate.py:132-145`

**Issue:** `subprocess.run(("git", "status", "--porcelain"), ...)` inherits the process
working directory. The dirty flag is part of the fingerprint payload
(`candidate.py:85-96`), so a run launched from a different directory — a sibling
repository, a nested worktree, or anywhere outside a repo — records a provenance flag
describing the **wrong tree**, and the fingerprint that claims to identify the code that
ran is derived from it. The out-of-repo case fails closed to `True` (correct), but the
wrong-repo case fails *silently* to whatever that repo's state is.

There is also no `timeout=`. `git status` on a large or lock-contended tree can block
indefinitely, hanging `build_candidate_spec` before any evaluation starts, with no
diagnostic.

**Fix:**

```python
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

result = subprocess.run(
    ("git", "status", "--porcelain"),
    capture_output=True,
    text=True,
    check=True,
    cwd=_REPOSITORY_ROOT,
    timeout=30,
)
```

and add `subprocess.TimeoutExpired` to the caught tuple so a timeout still fails closed.
`experiments/analyze_public.code_revision()` should be checked for the same two gaps,
since `current_revision()` pairs the two values.

---

### WR-12: Leaderboard artifacts are written non-atomically to CWD-relative paths

**WARNING**
**File:** `arena/leaderboard.py:36-37`, `arena/leaderboard.py:556-566`; `arena/store.py:56-71`

**Issue:** `LEADERBOARD_JSON_PATH` and `LEADERBOARD_MARKDOWN_PATH` are relative
(`experiments/baselines/leaderboard.json`, `experiments/LEADERBOARD.md`), so
`write_leaderboard` resolves them against the process CWD. Running
`python -m arena.run_arena adjudicate` from anywhere but the repository root silently
creates a second `experiments/` tree instead of updating the committed one, and the
operator sees two printed paths that look right.

Separately, both writes are bare `write_text`, and the JSON and Markdown are written
sequentially (`leaderboard.py:564-565`). An interruption between them leaves the
committed Markdown view describing a different payload than the committed JSON source of
truth — the exact drift `test_the_committed_markdown_matches_the_committed_payload`
exists to detect, but only after the fact. This matters more than for a run record
because these two files are committed evidence.

**Fix:** Resolve the defaults against `Path(__file__).resolve().parents[1]`, and write
both files to `.tmp` siblings then `os.replace` them into place (a shared
`store.write_text_atomic` helper would serve both `write_json` and the Markdown write).

---

### WR-13: The `failures` mapping in `adjudicate` holds passes, not failures

**WARNING**
**File:** `arena/adjudication.py:298-307`

**Issue:**

```python
failures = {
    "holm_significance": holm_p < SIGNIFICANCE_ALPHA,
    "practical_floor": clears_practical_floor,
    "hr10_exchange_rate": exchange_rate_ok,
}
failed_criteria = tuple(name for name in CRITERION_ORDER if not failures[name])
```

Every value in `failures` is `True` when the criterion **passed**. The logic is correct,
but the name inverts its meaning inside the single most safety-critical function in the
rig — the one whose output the whole leaderboard's `win`/no-win identity rests on
(`tests/test_arena_leaderboard.py:508`). A future edit that reads `if failures[name]` in
the obvious sense inverts every verdict in the report, and the failure would be a silent
change in `failed_criteria` content, not a crash.

**Fix:** Rename to `passed` (and `failed_criteria = tuple(name for name in CRITERION_ORDER
if not passed[name])`). Zero behavioural change, removes a live foot-gun.

---

## Info

### IN-01: `_cell` breaks the report's stated 6-dp convention for exact zeros

**INFO (non-blocking)**
**File:** `arena/leaderboard.py:346-347`

`if number == 0.0: return "0.0"` produces the ragged committed output visible in
`experiments/LEADERBOARD.md`: `` `0.006110` `` beside `` `0.0` `` and `` `[0.0, 0.0]` ``
in the same table, while the `HOW_TO_READ` block promises "Six decimal places
throughout". Return `"0.000000"` and let the scientific-notation branch keep its
`abs(number) < 1e-4 and number != 0.0` guard.

### IN-02: Dead `return` after `parser.error()`, and a redundant exception class

**INFO (non-blocking)**
**File:** `arena/run_arena.py:82-84`, `arena/run_arena.py:139-141`

`argparse.ArgumentParser.error` raises `SystemExit`, so both `return` statements are
unreachable. Also `FileExistsError` is a subclass of `OSError`, already covered by the
same tuple.

### IN-03: `expected_max_of_k(1, panels=<odd>)` returns before validating `panels`

**INFO (non-blocking)**
**File:** `arena/statistics.py:295-300`

The `k == 1` early return precedes the `panels % 2` check, so an invalid panel count is
silently accepted at `k=1` and rejected at `k>=2`.
`test_rejects_invalid_arguments` only covers `k=2`. Move the `panels`/`bound` validation
above the `k == 1` short-circuit.

### IN-04: The degenerate branch's `holm_p = 1.0` override is dead

**INFO (non-blocking)**
**File:** `arena/adjudication.py:265`

`holm_bonferroni` caps every adjusted value at `1.0` (`statistics.py:254`), and the input
for a degenerate row is `1.0`, so `holm_p_values[index]` is already exactly `1.0`. The
override never changes the value. Harmless, but it obscures the fact that the degenerate
row *is* in the Holm family (see WR-05).

### IN-05: `_session_outcome` does not coerce the integer fields

**INFO (non-blocking)**
**File:** `arena/arena.py:179-180`

`sample_id`, `scenario_type`, `hit` and `reciprocal_rank` are all explicitly coerced;
`first_hit_turn` and `best_rank` are passed through raw. A float `3.0` would satisfy
`1 <= x <= 10` in `validate()` and then serialize into `sessions.jsonl` as `3.0` rather
than `3`, breaking byte-comparison against a record written from an int. `store.py:87-88`
has the same gap. Coerce with `None if row[k] is None else int(row[k])`.

### IN-06: The rendered adjudication table omits `is_champion`

**INFO (non-blocking)**
**File:** `arena/leaderboard.py:442-502`

`is_champion` is in the JSON but not in the Markdown. Since the champion is the row whose
selection drives `correction_k`, and the committed report's champion
(`fallback-lexical`) carries the verdict `not detectable`, a reader of the Markdown alone
cannot see which row was selected. One extra column would close the loop with the
`E[max k]` audit columns beside it.

---

## Not defects (checked and cleared)

Recorded so a later reviewer does not re-open them:

- `efficiency()` returning unrounded is correct and deliberate; `leaderboard.py:268`
  rounds at the output boundary and `technical_score` consumes the unrounded value,
  matching `local_evaluator.py:279-280, 286`.
- Holm's running maximum (`statistics.py:254`) is present and correctly placed inside the
  `min(1.0, ...)`; the textbook `(0.01, 0.04, 0.03) -> (0.03, 0.06, 0.06)` case verifies.
- The Phipson-Smyth `+1` appears in both numerator and denominator for the Monte-Carlo
  path and correctly does **not** appear in `exact_paired_sign_flip_p_value`.
- Composite Simpson in `expected_max_of_k` is assembled correctly
  (`[f(-b), f(b)]` + alternating 4/2 interior weights, `* width / 3`), uses `math.fsum`,
  and matches `1/sqrt(pi)` and `3/(2 sqrt(pi))` to 12 places.
- `pair_seed` is SHA-256 over content, order-sensitive by design, and never touches the
  clock or `PYTHONHASHSEED`; `test_reproducible_across_processes` covers it.
- No set-iteration ordering leak: every set-derived output is passed through `sorted()`
  (`candidate.py:60`, `metrics.py:179`, `leaderboard.py:294`).
- `.gitignore`'s `!experiments/baselines/` negation is correctly placed after
  `experiments/*/`, and `experiments/*/` does not match the nested record directories
  (verified: `git check-ignore` clears `experiments/baselines/run-a/summary.json`, and
  all 11 record files are tracked).
- `resolve_run_directory` traversal defence is sound; the regex rejects `..`, leading
  separators, drive letters and `:`, and `is_relative_to` backs it up.
- Moving the `tempfile.TemporaryDirectory` out from under itself in `run_candidate` is
  safe: `TemporaryDirectory._rmtree`'s error handler swallows `FileNotFoundError`.

---

_Reviewed: 2026-08-30T10:36:25Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
