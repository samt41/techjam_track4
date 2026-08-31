# Phase 2: Expanded Dataset & Paraphrase Probe - Pattern Map

**Mapped:** 2026-08-31
**Files analyzed:** 27 (7 new `arena/datasets/` modules, 1 new `arena/` sibling, 5 committed assets, 5 modified sources, 9 new test modules, 3 extended test modules)
**Analogs found:** 25 / 27 (2 have no analog — the `claude -p` driver and the McNemar readout)

Every excerpt below is verbatim from the working tree at commit `a875184`. Line
numbers are current as of this mapping; the planner should cite them in plan
actions rather than re-deriving them.

---

## File Classification

### New — `arena/datasets/` subpackage

| New file | Role | Data flow | Closest analog | Match |
|---|---|---|---|---|
| `arena/datasets/__init__.py` | package stub | — | `arena/__init__.py` (1 line, exports nothing) | exact |
| `arena/datasets/schema.py` | model | transform | `arena/metrics.py:29-70` (`SessionOutcome` + `validate()`), `arena/candidate.py:41-124` | exact |
| `arena/datasets/gist.py` | service | batch / file-I/O | `starter/shopping_agent/catalog_index.py:28-40` (`value_counts`) + `arena/store.py:56-60` (`write_json`) | role-match |
| `arena/datasets/divergence.py` | utility | transform | `starter/shopping_agent/constraint_extractor.py:78-95` (stopword-filtered token work) + `text_normalization.py:46-47` | role-match |
| `arena/datasets/authoring.py` | service (external process) | request-response | **none** — see "No Analog Found". Nearest structural: `arena/candidate.py:142-155` (`subprocess.run` argv discipline), `arena/store.py` (write path) | partial |
| `arena/datasets/generate.py` | entry point / CLI | batch | `starter/shopping_agent/build_catalog_artifacts.py` (whole file) + `arena/arena.py:116-134` (refuse-then-tempdir-then-publish) | exact |
| `arena/datasets/registry.py` | config / store | file-I/O | `arena/store.py:24-60` + `arena/leaderboard.py:255-289` (`spec_from_record` / `entry_from_record`) | exact |

### New — committed assets (not code)

| New file | Role | Analog |
|---|---|---|
| `arena/datasets/assets/gist_vocabulary.json` | config | `data/catalog.artifacts/manifest.json` shape; written via `store.write_json` |
| `arena/datasets/assets/feature_abstractions.json` | config (hand-written, D-52) | `_EXPANSIONS` in `retrieval.py` — a hand-written map, tier-3 in `docs/STATUS.md` |
| `arena/datasets/assets/prompts/*.md` | config | no code analog; revision-hashed with `store.sha256_file` |
| `data/datasets.json` | config (registry, D-43) | `experiments/baselines/leaderboard.json` (JSON is truth, D-12) |
| `data/{expanded_dev,expanded_confirm,probe}.v1.jsonl` | data | `data/public_set.jsonl` row schema |

### New — arena sibling

| New file | Role | Data flow | Closest analog | Match |
|---|---|---|---|---|
| `arena/paired_contrast.py` | service (statistics) | transform | `arena/adjudication.py:194-240` (structure, guards, row assembly) + `arena/statistics.py:173-214` (the engine it reuses) | exact |

### Modified

| File | Role | Change | Analog for the change |
|---|---|---|---|
| `arena/evaluator_bridge.py` | seam | 3 → 8 re-exported names (D-47) | itself, lines 1-17 |
| `tests/test_arena_boundary.py` | test | widen `BRIDGE_EXPORTS`; `glob` → `rglob`; path-anchored bridge exemption | itself, lines 17, 77-83, 98-132 |
| `arena/run_arena.py` | entry point | `--dataset` resolves registry names | `arena/run_arena.py:46-51` (`_existing_file`) |
| `arena/leaderboard.py` | service / view | D-53 separate corpus-baselines table | `arena/leaderboard.py:488-560` (`_table` + `render_markdown`) |
| `starter/shopping_agent/constraint_extractor.py` | domain | `_STOPWORDS` → `STOPWORDS`, one call site at `:109` | `text_normalization.py:7-9` (public `UPPER_SNAKE` constants) |

### New tests

| New file | Analog | Match |
|---|---|---|
| `tests/dataset_fixtures.py` | `tests/arena_fixtures.py` (whole file) | exact |
| `tests/test_datasets_schema.py` | `tests/test_arena_candidate.py` | exact |
| `tests/test_datasets_conformance.py` | `tests/test_evaluator.py` | role-match |
| `tests/test_datasets_gist.py` | `tests/test_catalog_index.py` | exact |
| `tests/test_datasets_divergence.py` | `tests/test_text_normalization.py` | exact |
| `tests/test_datasets_authoring.py` | `tests/test_arena_candidate.py:200-215` (patched `subprocess.run`) | role-match |
| `tests/test_datasets_registry.py` | `tests/test_arena_leaderboard.py` | exact |
| `tests/test_datasets_control_fidelity.py` | `tests/test_evaluator.py` | role-match |
| `tests/test_arena_paired_contrast.py` | `tests/test_arena_statistics.py` + `tests/test_arena_adjudication.py` | exact |

---

## Pattern Assignments

### `tests/dataset_fixtures.py` (test fixture, transform) — THE most important analog

**Analog:** `tests/arena_fixtures.py` (94 lines, read in full)

**Path anchoring** (lines 10-14) — never the process cwd:

```python
# Derived from this file's location rather than the process working directory, so
# the fixtures resolve identically however unittest is invoked.
ANCHOR_RECORD_DIR = (
    Path(__file__).resolve().parent.parent / "experiments" / "baselines" / "anchor-legacy"
)
```

**Builder pattern** (lines 17-36) — a module-level function, keyword-only optional
fields, derived fields computed rather than passed:

```python
def session(
    sample_id: str,
    *,
    scenario_type: str = "buying",
    best_rank: int | None = None,
    first_hit_turn: int | None = None,
    reciprocal_rank: float | None = None,
) -> SessionOutcome:
    return SessionOutcome(
        sample_id=sample_id,
        scenario_type=scenario_type,
        hit=first_hit_turn is not None,
        first_hit_turn=first_hit_turn,
        best_rank=best_rank,
        reciprocal_rank=(
            (0.0 if best_rank is None else 1.0 / best_rank)
            if reciprocal_rank is None
            else reciprocal_rank
        ),
    )
```

**Zero-padded identifiers** (lines 45-54) — so lexicographic order equals
positional order. `dataset_fixtures` must do the same for `pair_id`:

```python
    # Zero-padded to three digits so lexicographic and positional order agree.
    return tuple(
        session(
            f"s{index:03d}",
            scenario_type=scenario_type,
            best_rank=rank,
            first_hit_turn=None if rank is None else turn,
        )
        for index, rank in enumerate(ranks)
    )
```

**Variant construction via `dataclasses.replace`** (lines 61-94) — this is the
exact idiom `paired_contrast` re-uses for the `pair_id` re-key. Note the
docstring shape (one-line summary, blank line, reasoning + evidence) and the
`ValueError` on an impossible request:

```python
def promote_hits_to_rank_one(
    sessions: tuple[SessionOutcome, ...],
    count: int,
) -> tuple[SessionOutcome, ...]:
    """Promote the first `count` non-rank-1 hits to rank 1, in file order.

    The deterministic synthetic large-effect control. This is a stronger
    true-positive check than any real evaluation run: ...

    File order rather than a seeded random draw: it needs no RNG and is therefore
    byte-stable by construction.
    """
    promotable = sum(
        1 for item in sessions if item.best_rank is not None and item.best_rank > 1
    )
    if promotable < count:
        raise ValueError(
            f"cannot promote {count} sessions; only {promotable} are promotable"
        )
    ...
            promoted.append(
                dataclasses.replace(item, best_rank=1, reciprocal_rank=1.0)
            )
```

**Catalog-free property to preserve:** `arena_fixtures.py` imports only
`dataclasses`, `pathlib`, `arena.metrics` and `arena.store`. It constructs typed
records directly and reads one small committed JSONL. `dataset_fixtures.py` must
match: hand-written `products` dicts and hand-written sample rows, **never**
`data/catalog.artifacts/`. `02-VALIDATION.md` line 147 makes this a sign-off item.
The dynamic conformance sweep is possible catalog-free because
`materialize_hidden_fields` branch 1 ignores `products` entirely — pass `{}`.

---

### `arena/datasets/registry.py` and every other write path (store, file-I/O)

**Analog:** `arena/store.py` (147 lines, read in full)

**Name validation at the boundary** (lines 17, 24-29) — the registry corpus-name
resolver must reuse this regex discipline verbatim, because a registry name
becomes a filename:

```python
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")  # experiments/run_public.py:28


class ArenaStoreError(RuntimeError):
    """Raised when a baseline record cannot be read, written, or published safely."""


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError(
            "run_id must contain only letters, digits, dots, dashes, or underscores"
        )
    return run_id
```

**Containment as defence in depth** (lines 32-42) — copy this shape for resolving
a registry entry's `path` under `data/`:

```python
def resolve_run_directory(root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    resolved_root = root.resolve()
    destination = (root / run_id).resolve()
    # The regex alone already rejects "..", a leading separator, a drive letter and an
    # NTFS alternate-data-stream ":". This containment check is defence in depth
    # (T-01-06): it keeps traversal impossible even if the allow-list is later widened
    # by someone who does not realise the id becomes a directory name.
    if not destination.is_relative_to(resolved_root):
        raise ArenaStoreError(f"run id escapes its output root: {run_id}")
    return destination
```

**Digest + canonical JSON** (lines 45-71) — `data/datasets.json` and the response
log must both go through `write_json`, never a hand-rolled `open()`. Note the
threat-model comment; RESEARCH § Security Domain V6 requires it be repeated for
`data/datasets.json`:

```python
def sha256_file(path: Path) -> str:
    # An integrity and reproducibility aid for a single local user, never an
    # authenticity control (T-01-09): nothing here is signed, so a digest proves only
    # that two files are the same bytes, not who produced them.
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_sessions(path: Path, sessions: tuple[SessionOutcome, ...]) -> None:
    # Canonical form is not cosmetic: the fingerprint and byte-reproducibility
    # assertions downstream compare these files byte for byte.
    path.write_text(
        "".join(
            json.dumps(row.as_record(), sort_keys=True) + "\n" for row in sessions
        ),
        encoding="utf-8",
    )
```

`write_sessions` is the direct analog for the corpus JSONL serializer (D-37): one
canonical `json.dumps(..., sort_keys=True)` per row, single `write_text`.

**Untrusted-line ingestion** (lines 74-106) — the analog for reading a corpus back
in the schema validator. Copy the shape: `json.loads` only, coerce identifiers to
`str`, call `validate()`, wrap `(KeyError, TypeError, ValueError)` and re-raise a
domain error naming the file **and line number**:

```python
        # json.loads only -- never pickle, eval or yaml (T-01-07). Identifiers are
        # normalized to strings; metric fields keep their JSON types until validate()
        # can reject incoherent rows.
        try:
            record = json.loads(line)
            outcome = SessionOutcome(...)
            outcome.validate()
        except (KeyError, TypeError, ValueError) as error:
            raise ArenaStoreError(
                f"invalid session row in {path} at line {number}: {error}"
            ) from error
```

**Atomic publish** (lines 109-147) — `publish(working, destination)` already
handles Windows WinError 183 and the open-handle `PermissionError`, and its
docstring is the exemplar for documenting a platform quirk. Call it; do not
re-derive it. Pitfall 6 (a silently clobbered frozen corpus) is closed by
combining it with the refusal below.

---

### `arena/datasets/schema.py` (model, transform)

**Analog:** `arena/candidate.py:41-124` (`CandidateSpec`) for the frozen-dataclass +
content-hash shape; `arena/metrics.py:29-70` (`SessionOutcome.validate`) for a
dense field-by-field validator.

**Full dataclass to copy the shape of** (`candidate.py:41-124`):

```python
@dataclass(frozen=True, slots=True)
class CandidateSpec:
    """One declared arena candidate and the provenance of the run it describes."""

    name: str
    code_revision: str
    code_revision_dirty: bool
    # Ordered pairs, never a dict: a dict field breaks `frozen=True` hashability and
    # admits insertion-order variation, which would produce two different
    # fingerprints for one configuration. `validate()` enforces the sort so an
    # unsorted construction fails loudly instead of minting a second fingerprint.
    overrides: tuple[tuple[str, str], ...]
    catalog_sha256: str
    dataset_sha256: str

    def validate(self) -> None:
        if not self.name:
            raise ValueError("candidate name must not be empty")
        keys = [key for key, _ in self.overrides]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate overrides contain a duplicate key")
        if sorted(keys) != keys:
            raise ValueError("candidate overrides must be in sorted key order")
        unknown = sorted(set(keys) - ALLOWED_OVERRIDES)
        if unknown:
            raise ValueError(f"unknown candidate override keys: {unknown}")
        ...

    @property
    def fingerprint(self) -> str:
        # SHA-256 over canonical JSON (D-09), never the builtin hash(), which is
        # salted per process by PYTHONHASHSEED and so cannot identify a candidate
        # across two runs. `separators` is pinned so the digest cannot drift if a
        # future edit adds `indent`; ...
        payload = json.dumps(
            {...},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_record(self) -> dict[str, object]:
        return {..., "fingerprint": self.fingerprint}
```

Load-bearing details for `SampleRow` / `IntentCard` / `Behavior` /
`RegistryEntry`:
- `tuple[tuple[str, str], ...]` instead of a dict for any mapping field, with
  `validate()` enforcing sorted key order — a dict breaks `frozen=True`
  hashability and admits insertion-order drift.
- `as_record()` returns a plain `dict[str, object]` for serialization; the
  content hash is a `@property`, computed, never stored.
- `validate()` is called **before** the value is used to build anything —
  see `arena/arena.py:110-113`: *"Validated BEFORE it is used to build anything."*

**Dense validator shape** (`metrics.py:37-70`) — note the loop over
`(name, value)` pairs to avoid repeating a message, the explicit
`isinstance(value, bool)` exclusion (bool is an int), and cross-field coherence
checks. `SampleRow.validate()` must check the same way: non-empty
`hard_constraints`/`soft_preferences`, a `behavior` with `scenario_type`, the four
override keys iff `scenario_type == "intent_override"`, and constraint length
≤ 180 (the evaluator's own `_clean_constraint` limit, `local_evaluator.py:48-49`):

```python
        for name, value in (
            ("best_rank", self.best_rank),
            ("first_hit_turn", self.first_hit_turn),
        ):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise ValueError(f"{name} must be an integer or null")
        ...
        if (self.first_hit_turn is None) != (self.best_rank is None):
            raise ValueError("first_hit_turn and best_rank must agree on hit presence")
```

---

### `arena/paired_contrast.py` (service, transform)

**Analogs:** `arena/statistics.py` for the engine and the guard;
`arena/adjudication.py:194-240` for the structure and the inverse guard.

**The guard that will reject the arms as-handed** (`statistics.py:107-117`) —
extract verbatim, because the fix is at the call site, never here:

```python
def _require_paired(
    baseline: tuple[SessionOutcome, ...],
    candidate: tuple[SessionOutcome, ...],
) -> None:
    # MEAS-04's join-on-sample_id made structural: an independent-sample comparison
    # becomes impossible to EXPRESS rather than merely discouraged. Pitfall 3 is silent
    # by construction, so the guard has to sit at the entry of every paired routine.
    if len(baseline) != len(candidate) or tuple(
        item.sample_id for item in baseline
    ) != tuple(item.sample_id for item in candidate):
        raise ValueError("paired comparison requires identical sample_id ordering")
```

Control and probe arms carry different `sample_id`s by construction (D-46), so
this **rejects them**. Do not weaken it (RESEARCH Anti-Patterns). Re-key on
`pair_id` first, using the `dataclasses.replace` idiom from
`tests/arena_fixtures.py:89`. Intended call site (RESEARCH Pattern 2):

```python
def align_on_pair_id(
    control: dict[str, SessionOutcome],
    probe: dict[str, SessionOutcome],
) -> tuple[tuple[SessionOutcome, ...], tuple[SessionOutcome, ...]]:
    missing = sorted(set(control) ^ set(probe))
    if missing:
        # Refuse rather than silently inner-joining: a dropped pair is a silently
        # smaller n, and MEAS-06 requires n to be honest.
        raise ValueError(f"unmatched pair ids between arms: {missing[:5]}")
    keys = sorted(control)  # explicit sort; never dict insertion order
    return (
        tuple(dataclasses.replace(control[k], sample_id=k) for k in keys),
        tuple(dataclasses.replace(probe[k], sample_id=k) for k in keys),
    )
```

**The bootstrap primitive to reuse, not rebuild** (`statistics.py:173-214`) — one
index vector applied to both arms is the load-bearing line:

```python
def paired_bootstrap(
    baseline: tuple[SessionOutcome, ...],
    candidate: tuple[SessionOutcome, ...],
    *,
    seed: int,
    resamples: int = RESAMPLE_COUNT,
) -> BootstrapResult:
    _require_paired(baseline, candidate)
    _require_resamples(resamples)
    rng = random.Random(seed)  # an instance, never the module-global RNG (D-24)
    count = len(baseline)
    deltas: list[float] = []
    for _ in range(resamples):
        # ONE index vector, applied to BOTH arms. Drawing two independent vectors
        # silently discards the pairing and inflates the standard error roughly
        # sevenfold on this repository's data (0.003715 paired vs 0.025922 unpaired),
        # which turns every candidate this project can build into "not detectable"
        # while every aggregate assertion still passes (Pitfall 3).
        indices = [rng.randrange(count) for _ in range(count)]
        deltas.append(
            _delta(
                tuple(baseline[index] for index in indices),
                tuple(candidate[index] for index in indices),
            )
        )
    deltas.sort()
    lower_index, upper_index = percentile_indices(resamples)
    return BootstrapResult(
        delta=_delta(baseline, candidate),
        lower=deltas[lower_index],
        upper=deltas[upper_index],
        standard_error=statistics.pstdev(deltas),
        resamples=resamples,
    )
```

**Content-seeded RNG** (`statistics.py:88-104`) — reuse `pair_seed` with a new
label (e.g. `"paired-contrast-bootstrap"`) so the probe readout sits on its own
RNG stream:

```python
def pair_seed(
    baseline_fingerprint: str,
    candidate_fingerprint: str,
    label: str,
) -> int:
    """Content-seeded, never clock-seeded -- two runs must agree byte for byte."""
    digest = hashlib.sha256(
        f"{baseline_fingerprint}\0{candidate_fingerprint}\0{label}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big")
```

**MDD, reported beside the result** (`statistics.py:315-337`) — takes the
**bootstrap SE**, not `sd_d / sqrt(n)`:

```python
def minimum_detectable_difference(standard_error: float) -> float:
    """Smallest true delta detectable at 80% power, alpha=0.05 two-sided, given this SE."""
    if standard_error < 0.0:
        raise ValueError("standard error must be non-negative")
    # ... This value must be reported beside EVERY adjudication row including null ones
    # (D-22, MEAS-06). Reporting it is the entire mechanism that makes "no significant
    # difference" visibly distinct from "we could not have detected one".
    return MDD_MULTIPLIER * standard_error
```

Do **not** import `holm_bonferroni` or `winners_curse_correction` (D-44). State
the omission in the report text, in the style of the load-bearing comments above.

**The inverse same-corpus guard** — mirror this refusal, negated
(`adjudication.py:205-219`):

```python
        for digest_field in ("catalog_sha256", "dataset_sha256"):
            if getattr(candidate.spec, digest_field) != getattr(
                baseline.spec,
                digest_field,
            ):
                raise ValueError(
                    f"{candidate.spec.name} was measured against a different"
                    f" {digest_field}"
                )
        candidate_fingerprints.append(fingerprint)
    if len(set(candidate_fingerprints)) != len(candidate_fingerprints):
        raise ValueError("candidate fingerprints must be unique")
```

`paired_contrast` needs the mirror image: **identical** `catalog_sha256`
(same catalog) but **differing** `dataset_sha256` (two corpora) — refuse if the
two arms share a `dataset_sha256`, in the same message style. RESEARCH L-10:
`CandidateEntry` (`leaderboard.py:188-206`) carries neither digest, so the digests
must come from `spec_from_record(run_directory)` (`leaderboard.py:255`), the same
source `run_arena._adjudicate` uses at `run_arena.py:143`.

**Result dataclass shape** (`statistics.py:56-71`) — a small frozen record with an
`as_record()`, one per readout:

```python
@dataclass(frozen=True, slots=True)
class BootstrapResult:
    delta: float
    lower: float
    upper: float
    standard_error: float
    resamples: int

    def as_record(self) -> dict[str, object]:
        return {
            "delta": self.delta,
            "lower": self.lower,
            "upper": self.upper,
            "standard_error": self.standard_error,
            "resamples": self.resamples,
        }
```

---

### `arena/evaluator_bridge.py` + `tests/test_arena_boundary.py` (the pair, one commit)

**Current seam, in full** (17 lines) — the whole file is the pattern. Widening
means editing the docstring's "three names" sentence, the one from-import, and
`__all__`, and nothing else:

```python
"""The only module in `arena/` permitted to import from `evaluator/` (D-08).

Every arena module reaches the scoring authority through this seam and calls
`evaluate` as an opaque function, so the rig's entire dependency on the harness
is one reviewable line that never touches harness internals.

`tests/test_arena_boundary.py` enforces both halves of that claim: no other
`arena/*.py` may name the harness package, and this seam re-exports exactly the
three names below.
"""

from __future__ import annotations

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl


__all__ = ("catalog_index", "evaluate", "load_jsonl")
```

Post-D-47 the sorted eight are: `behavior_for`, `catalog_index`,
`classify_constraint`, `evaluate`, `intent_card`, `load_jsonl`,
`materialize_hidden_fields`, `searchable_text`. D-47 requires the *why* commented
at the seam. The AST test asserts a **sorted** alias list, so the import must stay
alphabetical.

**The assertion mechanism** (`test_arena_boundary.py:17, 98-132`) — parsed, never
imported; the surface list and the two purity assertions:

```python
BRIDGE_EXPORTS = ("catalog_index", "evaluate", "load_jsonl")

_BRIDGE_MODULE_NAME = "evaluator_bridge.py"
...
    def test_bridge_surface_is_exactly_three_names(self) -> None:
        # Parsed rather than imported, so the surface assertion still holds when
        # the evaluator itself is unimportable.
        bridge = REPOSITORY_ROOT / "arena" / _BRIDGE_MODULE_NAME
        tree = ast.parse(bridge.read_text(encoding="utf-8"), filename=str(bridge))
        seams = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module != "__future__"
        ]
        self.assertEqual(len(seams), 1, "the seam must be exactly one from-import of the evaluator")
        self.assertEqual(seams[0].module, "evaluator.local_evaluator")
        self.assertEqual(
            sorted(alias.name for alias in seams[0].names),
            list(BRIDGE_EXPORTS),
            "a fourth name through the seam breaks 'evaluate() as an opaque function'",
        )
        self.assertEqual(
            [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)],
            [], "the seam must stay a pure re-export",
        )
        self.assertEqual(
            [node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))],
            [], "the seam must stay a pure re-export",
        )
```

Rename the method (it will no longer be "three names") and update the failure
message, which currently says "a fourth name".

**The non-recursive glob that must change** (`test_arena_boundary.py:77-83`) —
L-1 / Pitfall 1. Note the exemption is **basename-only**, which is why it must
become path-anchored once `arena/datasets/` exists:

```python
    def _non_bridge_modules(self) -> list[Path]:
        arena_directory = REPOSITORY_ROOT / "arena"
        return [
            path
            for path in sorted(arena_directory.glob("*.py"))
            if path.name != _BRIDGE_MODULE_NAME
        ]
```

Target shape: `arena_directory.rglob("*.py")`, excluding `__pycache__`, with the
exemption expressed as
`path.relative_to(REPOSITORY_ROOT) != Path("arena") / _BRIDGE_MODULE_NAME`.

**The detector to reuse unchanged** (`:22-48`) — it already catches
`ast.Import`, `ast.ImportFrom` (including relative), and `ast.Constant` strings,
and it takes a `path` specifically so `ScannerTest` can prove it fires:

```python
def evaluator_references(path: Path) -> tuple[str, ...]:
    # Takes a path instead of hard-coding arena/ so ScannerTest can prove the
    # detector actually fires, on files written into a TemporaryDirectory. ...
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
```

**The non-vacuity guard to extend** (`:134-141`) — add a sibling asserting the
recursive walk actually reaches a nested file, mirroring the `ScannerTest`
discipline at `:51-73`:

```python
    def test_arena_package_has_modules_to_scan(self) -> None:
        modules = [path.name for path in self._non_bridge_modules()]
        self.assertGreaterEqual(
            len(modules), 1,
            "the boundary scan would pass vacuously on an arena package holding "
            f"nothing but the bridge; found {modules}",
        )
```

**Do not touch** `EvaluatorIntegrityTest` (`:151-163`) or `EVALUATOR_SHA256`.

---

### `arena/datasets/gist.py` (service, batch/file-I/O)

**Analog:** `starter/shopping_agent/catalog_index.py:28-40`

```python
    def value_counts(self, attribute: Attribute) -> dict[str, int]:
        """Per-value document frequency (product count) for an attribute.

        Same facet scan as ``values_for`` but preserves ``FacetBucket.count``
        instead of discarding it — the gazetteer uses this catalog evidence to
        classify a phrase to the attribute where it is a strong structured value
        rather than a rare data-entry artifact.
        """
        result = self.backend.facets(FacetRequest(
            filters=(),
            attributes=(attribute,),
            work_limit=1_000_000_000,
        ))
        return {bucket.value: bucket.count for bucket in result.buckets}
```

**L-17 — the return is an unsorted dict.** Contrast with the sibling
`values_for` (`:20-26`), which does `tuple(sorted(...))`. Any gist vocabulary
reaching a committed asset must sort explicitly, with `value` as the final
tie-break after `count`.

**DF-floor constant pattern** — an `UPPER_SNAKE` module constant with the
rationale commented, per `constraint_extractor._STRUCTURED_DF_FLOOR = 2` and
`catalog_artifacts._MATERIAL_VOCAB_FLOOR = 2`. Underscore-prefixed because it is
a tuning constant (CONVENTIONS.md lines 42-48). It must also be recorded in
`docs/STATUS.md` under one of the four honesty tiers (CONVENTIONS.md lines
242-259) — tier 1 for the DF floor, **tier 3** for the hand-written D-52
`feature_abstractions.json` table, alongside `_EXPANSIONS`.

**Two-phase discipline** (`02-VALIDATION.md` lines 124-126): `gist.py` reads the
**committed** `gist_vocabulary.json` at use time and builds it only under an
explicit CLI flag, so no test opens the 580 MB database. The analog is
`catalog_artifacts.py` vs `local_search_backend.py` — offline precomputation is
separated from query time.

---

### `arena/datasets/divergence.py` (utility, transform)

**Analogs:** `starter/shopping_agent/text_normalization.py` and
`constraint_extractor.py:75-95`.

**The normalizer surface** (`text_normalization.py:7-8, 12-14, 46-47`):

```python
WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-z0-9]+")
PUNCT_SPACING_RE = re.compile(r"\s*([:,/])\s*")


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return WHITESPACE_RE.sub(" ", text).strip()


def search_terms(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(TOKEN_RE.findall(normalize_text(value))))
```

**L-15 — `search_terms` deduplicates** (`dict.fromkeys`), so it destroys token
order-multiplicity and **cannot** support D-34's 2-gram half. Use it for the
set-overlap half only; for the 2-gram half use the underlying idiom directly:

```python
# search_terms() de-duplicates via dict.fromkeys (text_normalization.py:47), which
# collapses the adjacency a 2-gram check needs. Same token space, order preserved.
tokens = TOKEN_RE.findall(normalize_text(phrase))
bigrams = frozenset(zip(tokens, tokens[1:]))
```

**Docstring exemplar** — `match_key` (`text_normalization.py:17-30`) is the
canonical shape CONVENTIONS.md names: catalog anomaly, consequence, fix, and the
invariant the fix preserves. The divergence gate's per-bucket floor reasoning
(D-51) belongs in exactly this form.

**The stopword promotion (D-54)** — `constraint_extractor.py:75-95`. The comment
above it is the justification the D-34 consumer inherits; extend it naming the
consumer rather than replacing it:

```python
# Standard English stop words (Snowball/NLTK). Function words such as "on", "by",
# and "no" also occur as junk catalog metadata; a generic list suppresses them
# without any evaluator- or catalog-specific tuning. It contains no garment
# vocabulary (a catalog-derived stop list would wrongly drop "buckle"/"dress").
_STOPWORDS = frozenset({
    "i", "me", "my", ...
})
```

Single call site: `constraint_extractor.py:109` — `if phrase in _STOPWORDS:`.
Rename in the same commit (D-54). A public constant carries no underscore
(CONVENTIONS.md line 44).

**The bucket gate through the seam** (RESEARCH Pattern 1) — never a
reimplementation:

```python
from arena.evaluator_bridge import classify_constraint, searchable_text

def preserves_bucket(control_phrase: str, probe_phrase: str) -> bool:
    # D-33. The evaluator's own classifier is the only correct authority on which
    # question unlocks a constraint (F-05); a reimplementation here would fork it.
    return classify_constraint(control_phrase) == classify_constraint(probe_phrase)
```

---

### `arena/datasets/generate.py` (entry point, batch)

**Analog A — the CLI shape:** `starter/shopping_agent/build_catalog_artifacts.py`
(46 lines, read in full). `argparse` in `main(argv: tuple[str, ...] | None = None)`,
narrow `except` on domain errors printing to stderr and returning 1,
`key=value` lines to stdout, `raise SystemExit(main())`:

```python
def main(argv: tuple[str, ...] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic Track 4 catalog search artifact.",
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)

    started_at = time.perf_counter()
    try:
        manifest = CatalogArtifactBuilder().build(arguments.catalog, arguments.output)
    except (ArtifactBuildError, ArtifactValidationError, OSError) as error:
        print(f"artifact build failed: {error}", file=sys.stderr)
        return 1
    elapsed_ms = (time.perf_counter() - started_at) * 1_000.0
    print(f"catalog_sha256={manifest.catalog_sha256}")
    ...
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The `argv=None` parameter is what makes the CLI testable without a subprocess —
`test_datasets_authoring.py`'s argv-hygiene assertion depends on it.

**Analog B — refuse, stage, publish:** `arena/arena.py:116-134`. This is the
Pitfall 6 mitigation (a regenerated corpus must never clobber a frozen one):

```python
def run_candidate(
    spec: CandidateSpec,
    *,
    run_id: str,
    ...
) -> Path:
    validate_run_id(run_id)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = resolve_run_directory(root, run_id)
    if destination.exists():
        raise FileExistsError(f"arena run already exists: {destination}")

    # Under the default baseline root, the `.{run_id}-` prefix is matched by
    # .gitignore's `experiments/baselines/.*/` rule, so an interrupted run is not
    # staged and mistaken for a completed record (T-01-19).
    with tempfile.TemporaryDirectory(prefix=f".{run_id}-", dir=root) as temporary:
        working = Path(temporary)
```

**Analog C — validate before building anything:** `arena/arena.py:110-113`:

```python
    # Validated BEFORE it is used to build anything. This ordering is the whole
    # mitigation for T-01-01: an unknown or unapplied override is rejected here, so
    # a fingerprint can never describe a configuration that did not run.
    spec.validate()
    return spec
```

**D-36 pair-pinned override turn** — content-seeded from `pair_id`, mirroring the
evaluator's own idiom (`local_evaluator.py:210-212`, quoted in CONVENTIONS.md
line 112): `random.Random(f"{pair_id}\0{scenario_type}")`, an instance and never
the module-global RNG (`statistics.py:182`).

---

### `arena/run_arena.py` — `--dataset` registry-name resolution

**Analog:** its own boundary helpers at `:46-51`. Extend `_existing_file`'s
sibling rather than inlining resolution into `_run`:

```python
def _existing_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path
```

The rationale comment at `:32-38` states the pattern: *"Reject an unusable record
at the boundary, with a message naming the path. Without this the first failure
surfaces as a FileNotFoundError from inside json.loads or load_sessions, several
frames below the CLI, which reads as a crash rather than as the operator error it
is."* A registry name that resolves to a path whose sha256 does not match the
committed digest must fail here, loudly (Pitfall 6).

Both CLI subcommands funnel errors through `parser.error(str(error))` with a
narrow tuple (`:117`, `:177`): `except (ValueError, FileExistsError, OSError,
ArenaStoreError)`. Add the registry error type to that tuple, not a broad
`except`.

---

### `arena/leaderboard.py` — D-53 corpus-baselines table

**Analog:** the table machinery already in the file.

**`_table`** (`:488-502`) — reuse verbatim; the `_none_` fallback matters:

```python
def _table(
    header: tuple[str, ...],
    alignment: tuple[str, ...],
    rows: tuple[str, ...],
) -> str:
    # The `| _none_ |` fallback mirrors run_public.py:308: an empty body would emit a
    # header and separator with nothing under them, which renders as a malformed table
    # rather than as an honest "no rows".
    body = "\n".join(rows) or "| " + " | ".join(["_none_"] * len(header)) + " |"
    return (
        "| " + " | ".join(header) + " |\n"
        "| " + " | ".join(alignment) + " |\n"
        + body
        + "\n"
    )
```

**Row rendering + `_cell`** (`:469-486`, `:520-545`) — every numeric cell goes
through `_cell` (bool before int; scientific notation below the threshold so a
Phipson-Smyth floor p never prints as `0.000000`; six decimal places otherwise).

**`render_markdown` is pure** (`:505`): *"Render the committed report. A pure
function of the payload -- no I/O, no clock."* The D-53 table must be built from
the payload, and D-12 requires the JSON to carry it too — a Markdown-only table
is not the source of truth.

**Precedent for keeping non-comparable rows out of the tested family** —
`run_arena.py:158-163` explains `--include`:

```python
        # Report-only entries are loaded the same way but are NEVER built into a
        # CandidateArm, so they reach the candidate, curve and scenario tables without
        # entering adjudicate() -- and therefore without joining the Holm family or
        # changing correction_k. That separation is why the two real rows below are
        # numerically identical whether or not these are present.
```

D-53 **rejects** reusing `--include` for the five corpus baselines: they must not
enter the candidate table at all. `CandidateEntry.provenance`
(`leaderboard.py:203-206`) is the existing precedent for a field whose only job is
to stop one kind of row being misread as another:

```python
    # T-01-16b: a synthetic validation control sitting in the same table as a measured
    # configuration is a spoofing surface. The `synthetic-` name prefix and the report's
    # stated convention are the primary mitigation; this field carries the record's own
    # words so the JSON says it too, not only the rendered view.
    provenance: str = ""
```

---

## Shared Patterns

### Module preamble
**Source:** every module in the repo. **Apply to:** all new files.
`from __future__ import annotations` as the first statement; three import groups
(future / stdlib `import x` then `from x import y` / first-party absolute,
`arena` → `evaluator` → `experiments` → `starter` → `tests`); two blank lines
before module constants and between top-level definitions; no `__all__` outside
the bridge; package `__init__.py` is a stub exporting nothing.

### Frozen slotted dataclass with `validate()`
**Source:** `arena/candidate.py:41-124`, `arena/metrics.py:29-70`.
**Apply to:** `schema.py`, `registry.py`, `paired_contrast.py`, `authoring.py`
request/response records. `validate()` raises `ValueError` with a lowercase
specific message; `as_record()` for serialization; `tuple[...]` across every
module boundary; wrap-and-chain with `raise ... from error`.

### Deterministic ordering
**Source:** `catalog_index.py:20-26` (`tuple(sorted(...))`),
`statistics.py:299-301` (stable final tie-break on input index),
`store.py:63-71` (`sort_keys=True`).
**Apply to:** every gist vocabulary dump, every registry write, every pair
alignment, every divergence report. Named tie-break: `parent_asin` last for
product-keyed output, `pair_id` last for pair-keyed output. L-17: `value_counts`
is unsorted — sort at the call site.

### Content-seeded randomness
**Source:** `statistics.py:88-104` (`pair_seed`), `statistics.py:182`
(`random.Random(seed)` instance, never the module global).
**Apply to:** target sampling, batch assignment, D-36 override-turn derivation,
the paired bootstrap. Never `hash()` (PYTHONHASHSEED-salted), never a clock seed.

### Comment the why
**Source:** `store.py:36-39`, `candidate.py:48-51`, `statistics.py:186-190`.
**Apply to:** every constant and every guard. Each new tuning constant must also
be recorded in `docs/STATUS.md` under one of the four honesty tiers
(CONVENTIONS.md lines 242-259) — this is as binding as the code conventions.

### Test module shape
**Source:** `tests/test_arena_boundary.py`.
`from __future__ import annotations`; stdlib imports; `unittest.TestCase`
subclasses grouped by concern; `-> None` on every test; assertion messages that
explain the invariant, not the mechanism; `if __name__ == "__main__":
unittest.main()`. `REPOSITORY_ROOT = Path(__file__).resolve().parent.parent` for
any path.

### Patched subprocess in tests
**Source:** `tests/test_arena_candidate.py:200-215`:

```python
            subprocess.CalledProcessError(128, ("git", "status", "--porcelain")),
                with patch("arena.candidate.subprocess.run", side_effect=failure):
```

**Apply to:** `test_datasets_authoring.py`. Patch
`arena.datasets.authoring.subprocess.run`, capture the argv tuple, and assert the
D-57 flags (`--setting-sources ""`, the clean cwd) are present and that the prompt
is **not** in argv. This is how the suite stays offline and fast.

---

## No Analog Found

| File | Role | Data flow | Reason |
|---|---|---|---|
| `arena/datasets/authoring.py` | service (external process) | request-response | **No existing module drives an external interactive tool.** The only two `subprocess` call sites in shipped code (`arena/candidate.py:142-155`, `experiments/analyze_public.py:231-237`) both run `git` with a fixed argv, no stdin, no timeout, and no output parsing. There is no precedent for prompt-on-stdin, JSON envelope parsing, a response log, a replay mode, or fan-out. |
| the McNemar readout inside `paired_contrast.py` | statistics | transform | No exact binomial test exists in the repo. RESEARCH: "12 lines of `math.comb`" — `arena/statistics.py:257-274` (`exact_paired_sign_flip_p_value`) is the nearest for the two-sided tail convention and the deliberate absence of a `+1` under exhaustive enumeration. |

### Structural patterns `authoring.py` must still follow

Despite the absent analog, four existing patterns constrain it:

1. **argv discipline** — `arena/candidate.py:142-155` is the shape to copy: a
   **tuple** argv, `capture_output=True, text=True`, a narrow
   `except (OSError, subprocess.CalledProcessError)`, and a documented
   fail-closed default:

```python
    try:
        result = subprocess.run(
            ("git", "status", "--porcelain"),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        # Fail closed. An unknown tree state is recorded as dirty because a clean
        # flag we could not establish would let a run with uncommitted changes
        # masquerade as the committed revision it names (T-01-11b).
        return True
```

2. **Injected runner, never a direct call** (RESEARCH Pattern 3). `authoring.py`
   takes `runner: Callable[[AuthoringRequest], AuthoringResponse]`; production
   supplies the `claude -p` subprocess runner, tests supply a replay runner backed
   by the committed response log, and replay is itself a production path. The
   repo's stated precedent is *"Tracing is injected, never global:
   `Agent(..., trace=JsonlEvaluationTrace(path))`"* (CLAUDE.md § Logging;
   `diagnostics.py` defines the `EvaluationTrace` Protocol and the default is
   `trace=None`). Use a `Protocol` from `typing`, as `search_backend.py:212` does
   for `ProductSearchBackend`.

3. **CLI shape** — `build_catalog_artifacts.py` (quoted above) plus
   `run_arena.py:183-206` for subparsers and `--replay` / `--build-vocabulary`
   flags. `argv=None` so tests never spawn a process.

4. **Write path** — `store.write_json` for the response log and
   `store.publish` / `os.replace` for any staged file. Never a hand-rolled
   `open()`.

### Security controls the driver must carry (RESEARCH § Security Domain)

| Control | Requirement |
|---|---|
| argv | `subprocess.run([...], shell=False)` with a **list/tuple** argv. Never `os.system`, never `shell=True`. |
| prompt delivery | On **stdin**, never as a shell-interpolated argument. |
| timeout | `timeout=` on every call; cap re-authoring attempts per constraint (3) and fail loudly. Unbounded retry is the DoS path. |
| provenance whitelist | Record only `session_id`, the resolved `modelUsage` key, `usage`, `total_cost_usd`, `duration_ms`. **Never** `dict(os.environ)`, never the raw `--settings` blob, never a token. No shipped code reads any environment variable today — keep it that way. |
| D-57 argv hygiene | Explicit clean cwd (a `CLAUDE.md`-free temp dir) and `--setting-sources ""`, asserted in the driver's argv test. Loading this project's `CLAUDE.md` is an anti-circularity breach, not just a token cost. `--bare` does not work with OAuth. |
| corpus filenames | Constructed by the driver, never taken from LLM output. Reuse `store.validate_run_id`'s regex and `resolve_run_directory`'s `is_relative_to` containment. |
| output validation | Every LLM-derived string passes `SampleRow.validate()`, the `classify_constraint` gate, the divergence gate, and the faithfulness review **before** serialization. Cap constraint length at 180 (`local_evaluator.py:48-49`). |
| layering | The `claude` dependency lives only in `arena/datasets/authoring.py` and must never be reachable from `starter/`. CONVENTIONS.md § Layering already forbids `starter/` importing `arena/`. |

---

## Metadata

**Analog search scope:** `arena/` (all 11 modules), `tests/` (fixture and
boundary modules), `starter/shopping_agent/` (`catalog_index.py`,
`text_normalization.py`, `constraint_extractor.py`,
`build_catalog_artifacts.py`), `experiments/` (subprocess call sites).
**Files scanned:** 24 read; 5 read in full (`tests/arena_fixtures.py`,
`arena/store.py`, `arena/candidate.py`, `arena/evaluator_bridge.py`,
`tests/test_arena_boundary.py`, `arena/statistics.py`).
**Pattern extraction date:** 2026-08-31
