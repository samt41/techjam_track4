# Phase 1: Measurement Rig Core - Pattern Map

**Mapped:** 2026-08-30
**Files analyzed:** 17 (10 new `arena/` modules, 5 new test modules, 2 modified)
**Analogs found:** 15 / 17

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `arena/__init__.py` | package marker | — | `experiments/__init__.py` (48 bytes, docstring only) | exact |
| `arena/evaluator_bridge.py` | adapter / port | request-response | `experiments/run_public.py:13` (the import line itself) + `starter/shopping_agent/search_backend.py` Protocol seam | role-match |
| `arena/candidate.py` | model | transform | `starter/shopping_agent/models.py:95-117` (`PreferenceConstraint`) + `experiments/run_public.py:275-280` (`_sha256`) | exact |
| `arena/metrics.py` | service (pure) | transform | `evaluator/local_evaluator.py:188-201, 278-295` (re-implemented, not imported) | exact |
| `arena/statistics.py` | service (pure) | transform | `starter/shopping_agent/belief.py` / `ranking.py` (hand-rolled numerics, stdlib only) | role-match |
| `arena/adjudication.py` | service (policy) | transform | `starter/shopping_agent/ranking.py:96-113` (deterministic ordering + policy over scored items) | role-match |
| `arena/store.py` | adapter (file I/O) | file-I/O | `experiments/run_public.py:135-150, 283-294` (`_publish`, `_write_json`, `_write_jsonl`) | exact |
| `arena/leaderboard.py` | presentation | transform | `experiments/run_public.py:297-324` (`_ablation_markdown`) + `_write_json` | exact |
| `arena/arena.py` | entry adapter | request-response | `experiments/run_public.py:31-56, 59-132` (`_SessionMappingAgent`, `run_experiment`) | exact |
| `arena/run_arena.py` | CLI | request-response | `experiments/run_public.py:327-356` (`main`) | exact |
| `tests/test_arena_metrics.py` | test | transform | `tests/test_models.py:1-40` + `tests/test_experiment_analysis.py:1-45` | exact |
| `tests/test_arena_statistics.py` | test | transform | `tests/test_experiment_analysis.py` (module-level factory fixtures) | exact |
| `tests/test_arena_adjudication.py` | test | transform | `tests/test_experiment_analysis.py` | exact |
| `tests/test_arena_candidate.py` | test | transform | `tests/test_models.py` (`validate()` raises `ValueError`) | exact |
| `tests/test_arena_boundary.py` | test (AST/static) | transform | none — no existing static-analysis test | **no analog** |
| `.gitignore` | config | — | itself (lines 11-12) | modify |
| `experiments/RUNS.md` | docs | — | itself | modify |

---

## Pattern Assignments

### `arena/arena.py` (entry adapter, request-response)

**Analog:** `experiments/run_public.py:31-56` and `:59-132`

**Session-mapping wrapper — copy verbatim in shape, rename, and add the D-07 "why" comment** (`experiments/run_public.py:31-56`):

```python
class _SessionMappingAgent:
    """Wraps Agent to record reset-call order without touching the evaluator.

    The evaluator generates a random session UUID per sample in sample order,
    so recording each reset maps that UUID back to the public sample id. This
    join happens only after evaluate() returns; ground truth never enters the
    Agent.
    """

    def __init__(self, agent: Agent, sample_ids: tuple[str, ...]) -> None:
        self._agent = agent
        self._sample_ids = sample_ids
        self._reset_count = 0
        self.session_to_sample: dict[str, str] = {}

    def reset(self, session_id: str, user_profile: dict) -> None:
        if self._reset_count < len(self._sample_ids):
            self.session_to_sample[session_id] = self._sample_ids[self._reset_count]
        self._reset_count += 1
        self._agent.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        return self._agent.respond(session_id, user_message, turn, top_k)

    def close(self) -> None:
        self._agent.close()
```

The new docstring must additionally state *why it is duplicated rather than imported*:
importing `experiments.run_public` transitively pulls `evaluator.local_evaluator`
(`experiments/run_public.py:13`) into `arena/` and defeats D-08.

**Run body: sample load → agent construct → evaluate → close-in-`finally` → publish** (`experiments/run_public.py:77-98`):

```python
    with tempfile.TemporaryDirectory(prefix=f".{run_id}-", dir=root) as temporary:
        working = Path(temporary)
        samples = load_jsonl(dataset_path)
        catalog_ids, categories, products = catalog_index(catalog_path)
        base_agent = Agent(
            catalog_path,
            trace=trace,
            exploration=exploration,
            lexical_mode=LexicalMode(lexical_mode),
        )
        agent = _SessionMappingAgent(
            base_agent,
            tuple(str(sample["sample_id"]) for sample in samples),
        )
        started = perf_counter()
        try:
            result = evaluate(agent, samples, catalog_ids, categories, products)
        finally:
            agent.close()
        elapsed_seconds = perf_counter() - started
```

Note `agent.close()` in `finally` **before** publish — required so `os.replace`
on the working directory does not hit `PermissionError` from the open SQLite handle
(Windows). RESEARCH Pattern 10 flags this explicitly.

**Guard-at-entry pattern** (`experiments/run_public.py:28, 67-75`) — regex-validated
run id, refuse existing destination:

```python
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
...
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError(
            "run_id must contain only letters, digits, dots, dashes, or underscores"
        )
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / run_id
    if destination.exists():
        raise FileExistsError(f"experiment run already exists: {destination}")
```

**Summary dict shape to mirror in `experiments/baselines/<id>/summary.json`** (`experiments/run_public.py:106-118`):

```python
        revision = code_revision()
        summary = {
            "run_id": run_id,
            "code_revision": revision,
            "exploration": exploration,
            "lexical_mode": lexical_mode,
            "catalog_sha256": _sha256(Path(catalog_path)),
            "dataset_sha256": _sha256(Path(dataset_path)),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "belief_configuration": DEFAULT_BELIEF_CONFIGURATION.as_dict(),
            "question_configuration": QuestionModelConfiguration.default().as_dict(),
            **result,
        }
```

The arena's version adds `"fingerprint": spec.fingerprint` and drops the
`belief_configuration`/`question_configuration` keys only if they cannot be reached
without importing `starter` internals — they can, so keep them.

---

### `arena/candidate.py` (model, transform)

**Analog:** `starter/shopping_agent/models.py:95-117` (frozen+slots+`validate()`)

**Dataclass + `validate()` raising `ValueError` with lowercase specific messages** (`models.py:95-117`):

```python
@dataclass(frozen=True, slots=True)
class PreferenceConstraint:
    constraint_id: str
    attribute: Attribute
    ...

    def validate(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("constraint confidence must be between 0 and 1")
        if self.strength is Strength.HARD and self.confidence < 0.90:
            raise ValueError("hard constraint confidence must be at least 0.90")
        if not self.preference_group_id:
            raise ValueError("preference_group_id must not be empty")
```

Note: `validate()` is a **method the caller invokes**, never `__post_init__`. See
`models.py:110`, `:133`. `CandidateSpec.validate()` follows this exactly (D-10).

**Module-constant convention for the allow-list** — `UPPER_SNAKE`, leading
underscore when module-private, defined above the class (cf. `catalog_artifacts.py:22-32`):

```python
ARTIFACT_SCHEMA_VERSION = 1
DATABASE_FILENAME = "catalog.sqlite3"
NORMALIZATION_VERSION = "nfkc-casefold-v1"
POSTING_BATCH_SIZE = 1_000
```

**Allow-list source of truth — `Agent.__init__` signature** (`starter/agent.py:18-25`):

```python
    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        artifact_path: str | Path | None = None,
        lexical_mode: LexicalMode = LexicalMode.AUTO,
        trace: EvaluationTrace | None = None,
        exploration: str = "disabled",
    ) -> None:
```

Phase 1 allow-list is exactly `{"lexical_mode", "exploration", "artifact_path"}`.
`catalog_path` and `trace` are arena-controlled plumbing, not candidate knobs.

**Fingerprint input hashing — `_sha256`** (`experiments/run_public.py:275-280`):

```python
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
```

**Git revision — `code_revision()`** (`experiments/analyze_public.py:229-240`):

```python
def code_revision() -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown_revision"
    revision = result.stdout.strip()
    return revision or "unknown_revision"
```

Import this from `experiments.analyze_public` — **safe**, that module does not import
`evaluator` (verified: its imports are stdlib + `starter.shopping_agent` only; the
evaluator import lives in `run_public.py:13`, not `analyze_public.py`). If the planner
prefers zero coupling, duplicate it with the same tuple-args / `check=True` /
`"unknown_revision"` fallback shape and add the arena's own dirty-tree flag alongside
(RESEARCH Pattern 8, `code_revision()` gap).

---

### `arena/metrics.py` (pure service, transform)

**Analog:** `evaluator/local_evaluator.py:188-201` and `:278-295` — **transcribed, never imported** (D-08).

**Rounding order is load-bearing** (`local_evaluator.py:188-201`):

```python
def metric_summary(sessions: list[dict]) -> dict:
    if not sessions:
        return {"sample_count": 0, "hit_rate_at_10": 0.0, "mrr": 0.0, "mttc": None}
    hit_rate = sum(int(item["hit"]) for item in sessions) / len(sessions)
    mrr = statistics.fmean(item["reciprocal_rank"] for item in sessions)
    mttc = statistics.fmean(
        item["first_hit_turn"] if item["first_hit_turn"] is not None else MAX_TURNS + 1 for item in sessions
    )
    return {
        "sample_count": len(sessions),
        "hit_rate_at_10": round(hit_rate, 6),
        "mrr": round(mrr, 6),
        "mttc": round(mttc, 6),
    }
```

**Efficiency / TechnicalScore / per-scenario grouping** (`local_evaluator.py:278-295`):

```python
    overall = metric_summary(sessions)
    efficiency = max(0.0, min(1.0, (11.0 - float(overall["mttc"])) / 10.0))
    technical_score = 0.50 * overall["hit_rate_at_10"] + 0.30 * overall["mrr"] + 0.20 * efficiency
    grouped: dict[str, list[dict]] = defaultdict(list)
    for session in sessions:
        grouped[session["scenario_type"]].append(session)
    return {
        **overall,
        "efficiency": round(efficiency, 6),
        "recommended_technical_score": round(technical_score, 6),
        ...
        "scenario_metrics": {name: metric_summary(grouped[name]) for name in sorted(grouped)},
        "sessions": sessions,
    }
```

Two details the executor must preserve: `efficiency` consumes the **rounded** `mttc`,
and `scenario_metrics` iterates `sorted(grouped)` — deterministic key order.

**Per-session record shape** (`local_evaluator.py:269-276`) — the exact row that lands in `sessions.jsonl`:

```python
        sessions.append({
            "sample_id": sample["sample_id"],
            "scenario_type": sample["scenario_type"],
            "hit": hit_turn is not None,
            "first_hit_turn": hit_turn,
            "best_rank": best_rank,
            "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
        })
```

**Typed-row modelling for `SessionOutcome`:** follow the frozen+slots pattern of
`starter/shopping_agent/models.py:80-92` (`ProductRecord`) — plain scalar fields,
`| None` for optionals, no defaults.

---

### `arena/statistics.py` (pure service, transform)

**Analog:** `starter/shopping_agent/ranking.py` / `belief.py` — hand-rolled numerics over `math`/`statistics` with zero third-party deps.

**Deterministic ordering with an explicit stable final tie-break** (`ranking.py:96-113`) — the pattern Holm's sort and the leaderboard sort must both follow:

```python
        strict = sorted(
            (item for item in ranked if item.exact_match),
            key=lambda item: (
                item.parent_asin in shown_product_ids,
                -item.posterior,
                -item.score,
                item.parent_asin,
            ),
        )
```

The final key element is always the stable identifier. In `arena/statistics.py`'s
`holm_bonferroni` that is the input index (`key=lambda i: (p_values[i], i)`); in
`arena/leaderboard.py` it is the candidate fingerprint (D-14).

**Bounded work with an explicit sorted key** (`ranking.py:180-182`):

```python
        bounded_ids = sorted(
            evidence_score,
            key=lambda parent_asin: (-evidence_score[parent_asin], parent_asin),
        )
```

**No analog exists for the resampling routines themselves.** The full reference
implementations for `paired_bootstrap`, `paired_permutation`, `holm_bonferroni`,
`minimum_detectable_difference`, `expected_max_of_k` and `winners_curse_correction`
are in `01-RESEARCH.md` Patterns 3-7, already written in repo style and verified
in-session. Use those as the source; use `ranking.py` only for the ordering and
tie-break discipline.

---

### `arena/store.py` (adapter, file-I/O)

**Analog:** `experiments/run_public.py:135-150, 283-294`

**Atomic publish — copy verbatim including the Windows rationale comment** (`run_public.py:135-150`):

```python
def _publish(working: Path, destination: Path) -> None:
    """Move the completed working directory to its final name.

    `Path.rename` maps to `os.rename`, which on Windows raises WinError 183 when
    the destination already exists (unlike POSIX rename, which replaces). The
    run refused to overwrite an existing destination at entry, so a destination
    present now is a corpse from an earlier crashed run of the same id; clear it
    and retry rather than losing a completed 200-session evaluation at the final
    publish step.
    """
    try:
        os.replace(working, destination)
    except OSError:
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(working, destination)
```

**Canonical JSON writers — fingerprint stability depends on these exactly** (`run_public.py:283-294`):

```python
def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
```

`indent=2, sort_keys=True` + trailing newline for `.json`; `sort_keys=True`, no indent,
one line per row for `.jsonl`. Note this differs from `CandidateSpec.fingerprint`,
which uses `separators=(",", ":")` (RESEARCH Pattern 8) — the fingerprint payload is
never a file, so pinning whitespace there is independent and correct.

**JSONL read-back** (`run_public.py:153-160`):

```python
def _load_events(trace_path: Path) -> tuple[dict, ...]:
    if not trace_path.exists():
        return ()
    return tuple(
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
```

This is the shape for `load_sessions(path) -> tuple[SessionOutcome, ...]`.

**Typed record serialization (`as_record()`)** — if the executor models rows as
dataclasses rather than dicts, follow `starter/shopping_agent/diagnostics.py:29-38`:

```python
    def as_record(self) -> dict[str, object]:
        return {
            "event_type": "interpretation",
            "session_id": self.session_id,
            "turn": self.turn,
            "dialogue_act": self.dialogue_act.value,
            "update_kinds": list(self.update_kinds),
            ...
        }
```

Tuples become `list(...)`, enums become `.value`, floats are `round(..., 3)`
(`diagnostics.py:199-200`).

**Typed error classes** (`starter/shopping_agent/catalog_artifacts.py:35-40`) — for
`ArenaStoreError` / `ArenaValidationError` if the executor needs them:

```python
class ArtifactBuildError(RuntimeError):
    """Raised when a catalog artifact cannot be built safely."""


class ArtifactValidationError(RuntimeError):
    """Raised when an artifact does not match its fixed schema or catalog."""
```

---

### `arena/leaderboard.py` (presentation, transform)

**Analog:** `experiments/run_public.py:297-324` (`_ablation_markdown`)

**Markdown table generation from a dict — f-string concatenation, sorted rows, `| _none_ |` empty fallback:**

```python
    reason_lines = "\n".join(
        f"| `{reason}` | {count} |"
        for reason, count in sorted(reason_counts.items())
    ) or "| _none_ | 0 |"
    return (
        f"# Run {summary['run_id']}\n\n"
        f"- Configuration: exploration=`{summary['exploration']}`, "
        f"lexical_mode=`{summary['lexical_mode']}`, "
        f"revision=`{summary['code_revision']}`\n"
        f"- TechnicalScore: `{summary['recommended_technical_score']}`\n"
        ...
        "## Miss attribution\n\n"
        "| Reason | Count |\n"
        "| --- | --- |\n"
        f"{reason_lines}\n\n"
        "Compare this run with retained rows in `experiments/RUNS.md`.\n"
    )
```

Metric values are wrapped in backticks; column separators are `| --- |`; the file
ends with a single `\n`. `experiments/RUNS.md:13` shows the right-aligned numeric
form the four D-13 tables should use: `| Class | HitRate@10 | ... | --- | ---: | ... |`.

`leaderboard.json` is written with `_write_json` (`indent=2, sort_keys=True`).

---

### `arena/run_arena.py` (CLI, request-response)

**Analog:** `experiments/run_public.py:327-356`

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Run a reproducible public evaluation")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output-root", default="experiments")
    parser.add_argument(
        "--exploration",
        choices=("disabled", "tail-only"),
        default="disabled",
    )
    parser.add_argument(
        "--lexical-mode",
        choices=("auto", "fts5", "fallback"),
        default="auto",
    )
    args = parser.parse_args()
    run_directory = run_experiment(
        run_id=args.run_id,
        ...
    )
    print(run_directory)


if __name__ == "__main__":
    main()
```

`choices=(...)` tuples bound the enumerated flags; `main()` returns `None` and
`print`s the produced path; the `if __name__ == "__main__":` guard is last.
Arena default `--output-root` becomes `experiments/baselines` (D-04).

---

### `arena/evaluator_bridge.py` (adapter seam, request-response)

**Analog:** `experiments/run_public.py:13` — the exact import line, isolated into its own module:

```python
from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
```

The bridge's entire body is that import plus `__all__ = ("catalog_index", "evaluate", "load_jsonl")`.
Precedent for a single named seam is `starter/shopping_agent/search_backend.py`'s
`ProductSearchBackend` Protocol (see `starter/shopping_agent/diagnostics.py:222-226`
for the repo's Protocol style):

```python
class EvaluationTrace(Protocol):
    def record(self, event: TraceEvent) -> None: ...

    def close(self) -> None: ...
```

---

### `tests/test_arena_*.py` (test, transform)

**Analogs:** `tests/test_experiment_analysis.py:1-45` (module-level factory fixtures), `tests/test_models.py:1-40` (validate/raises)

**Module-level factory functions with keyword-only defaults — the fixture pattern the arena tests must match** (`tests/test_experiment_analysis.py:14-27`):

```python
def target_profile(
    parent_asin: str,
    *,
    material: str = "canvas",
    color: str = "black",
    price: float | None = 70.0,
    searchable_text: str = "canvas boot durable",
) -> TargetProfile:
    return TargetProfile(
        parent_asin=parent_asin,
        attributes={"material": material, "color": color},
        price=price,
        searchable_text=searchable_text,
    )
```

Note: these fixtures live **in the test module itself**, not in `tests/fixtures.py`.
`tests/fixtures.py` (`sample_products`, `write_catalog`, `build_test_artifacts`) is
reserved for catalog/artifact construction only — the arena's Layer-1 statistical
fixtures need no catalog and therefore belong in their own test modules, matching
`test_experiment_analysis.py`.

**Test module header and class shape** (`tests/test_models.py:1-30`):

```python
from __future__ import annotations

import unittest

from starter.shopping_agent.models import (
    Attribute,
    ...
)


class PreferenceConstraintTest(unittest.TestCase):
    def test_hard_constraint_requires_high_confidence(self) -> None:
```

`from __future__ import annotations` first; absolute imports parenthesized
one-per-line alphabetically; class named `<Subject>Test`; every test method
annotated `-> None`; assert `ValueError` with `assertRaises`.

**`tests/fixtures.py` builder pattern** (for reference, `tests/fixtures.py:92-104`) — keyword-only flag, returns a tuple of paths, writes into a caller-supplied temp `directory`:

```python
def build_test_artifacts(
    directory: Path,
    products: list[dict[str, object]],
    *,
    fts5_enabled: bool = True,
) -> tuple[Path, Path]:
```

---

### `.gitignore` (config)

**Current ignore shape:**

```text
experiments/*/
experiments/.*-/
!experiments/baselines/
experiments/baselines/.*/
```

D-04 keeps committed baseline records visible with `!experiments/baselines/`.
T-01-19 keeps dot-prefixed staging directories invisible with
`experiments/baselines/.*/`; verify that with
`git check-ignore -v experiments/baselines/.run-x-ab12cd/summary.json`. Line 8
(`results.json`) is what F-03's untracked anchor file is hidden by; leave it.

---

### `experiments/RUNS.md` (docs)

**Analog:** itself. D-05 forbids rewriting. Existing structure is `##`/`###` sections
with right-aligned pipe tables (`RUNS.md:13`) and a prose caveat paragraph above each
table. The change is **additive only**: one pointer line/section referencing
`experiments/LEADERBOARD.md`. Match the existing tone — the file already ends its
generated companion with "Compare this run with retained rows in
`experiments/RUNS.md`." (`run_public.py:323`), so the pointer closes that loop.

---

## Shared Patterns

### Module header
**Source:** every module in the repo (`starter/agent.py:1`, `experiments/run_public.py:1`, `tests/test_models.py:1`)
**Apply to:** all 15 new files

```python
from __future__ import annotations

import argparse
import hashlib
import json
import os
...
from pathlib import Path
from time import perf_counter

from starter.agent import Agent
```

First line is always `from __future__ import annotations`, then a blank line, then
stdlib imports alphabetically, then a blank line, then absolute project imports.
No relative imports, no barrel files. Two blank lines between top-level definitions.

### Canonical JSON serialization
**Source:** `experiments/run_public.py:283-294`
**Apply to:** `arena/store.py`, `arena/leaderboard.py`, `arena/candidate.py`
`json.dumps(payload, indent=2, sort_keys=True) + "\n"` for `.json`;
`json.dumps(row, sort_keys=True) + "\n"` per line for `.jsonl`;
`json.dumps(..., sort_keys=True, separators=(",", ":"))` for hash payloads.

### Determinism / stable tie-break
**Source:** `starter/shopping_agent/ranking.py:96-113, 180-182`; `evaluator/local_evaluator.py:293` (`sorted(grouped)`)
**Apply to:** `arena/statistics.py` (Holm sort), `arena/adjudication.py`, `arena/leaderboard.py` (D-14 fingerprint tie-break), `arena/metrics.py` (scenario iteration)
Every sort's final key element is a stable identifier. No set iteration reaches output.

### Content-seeded randomness
**Source:** `evaluator/local_evaluator.py:210-211`
```python
    seed_source = f"{sample.get('sample_id', '')}\0{sample.get('scenario_type', '')}"
    rng = random.Random(seed_source)
```
**Apply to:** `arena/statistics.py`
Note the `\0` field separator and the `random.Random(...)` **instance** — never
`random.seed()`. D-24's `_pair_seed` mirrors this with SHA-256 over the two
fingerprints plus a `label`.

### `validate()` raising lowercase specific `ValueError`
**Source:** `starter/shopping_agent/models.py:110-116, 133-143`
**Apply to:** `arena/candidate.py`, and any arena dataclass with an invariant
Caller-invoked method, not `__post_init__`. Message is lowercase, names the field.

### Frozen slotted dataclasses
**Source:** `starter/shopping_agent/models.py:71-108`, `diagnostics.py:20-38`
**Apply to:** `CandidateSpec`, `SessionOutcome`, `MetricSummary`, `BootstrapResult`, `PermutationResult`, `AdjudicationRow`
`@dataclass(frozen=True, slots=True)`; cross-module sequences are `tuple[...]`, never `list`.

### Comment the *why*, never the *what*
**Source:** `experiments/run_public.py:136-144`, `starter/shopping_agent/diagnostics.py:246-250`
**Apply to:** D-07 duplication site, D-20 ordering, the Phipson-Smyth `+1`, the single-index-vector bootstrap, the Windows `os.replace` retry.
Most modules carry zero or one comment; each one is load-bearing and explains a
decision that would otherwise look wrong.

### Typed error classes
**Source:** `starter/shopping_agent/catalog_artifacts.py:35-40`
**Apply to:** `arena/store.py`, `arena/candidate.py` if a non-`ValueError` domain error is needed
`class XError(RuntimeError):` with a one-line docstring, no body.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/test_arena_boundary.py` | test (static analysis) | transform | No AST- or import-graph-based test exists anywhere in the 167-test suite. Use the verified reference implementation in `01-RESEARCH.md` Pattern 9 (AST import walk + string-constant scan, validated against 7 evasion forms), styled per `tests/test_models.py`. |
| `arena/statistics.py` resampling internals | service (pure) | transform | No bootstrap/permutation/Holm code exists in the repo. `belief.py` / `ranking.py` supply the *style* (stdlib-only hand-rolled numerics, deterministic ordering) but not the algorithms; take those from `01-RESEARCH.md` Patterns 3-7. |

---

## Metadata

**Analog search scope:** `experiments/`, `starter/`, `starter/shopping_agent/`, `evaluator/`, `tests/`, repository root config
**Files scanned:** 12 read (7 in full, 5 targeted ranges)
**Pattern extraction date:** 2026-08-30
