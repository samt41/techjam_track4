# Retained Evaluation Runs

Only the best run for each meaningful implementation class is retained. Generated run directories are local artifacts and are not committed.

### Superseded as the system of record by the arena leaderboard

From Phase 1 onward the generated report is `experiments/LEADERBOARD.md`, and
`experiments/baselines/leaderboard.json` is its source of truth. The Markdown is a
rendered view — regenerate both with `python -m arena.run_arena adjudicate` rather
than editing either by hand.

**A "retained historical row" now means a committed file, not a number in prose.**
Every row below this section was a figure typed into this document. From Phase 1 a
retained result is a provenance-carrying record under `experiments/baselines/`,
carrying its own fingerprint, code revision, catalog and dataset digests, and its
full 200 session outcomes. This file is retained for the prose evidence it holds —
the exploration ablation, the two-run byte-determinism verification, the
forced-fallback verification, and the public-ceiling miss audit — none of which
exists anywhere else.

**Precision.** The aggregates in this file are recorded to four decimal places while
the leaderboard prints six, so the two agree only after rounding. The retained row
below reads `0.5245` / `0.7688`; the committed record reads `0.524466` / `0.76884`.
Do not compare them as exact equals — recomputing TechnicalScore from the four-place
figures gives `0.76885`, which displays as `0.7689`.

**Cross-validation.** The `0.920` / `0.524466` / `3.425` / `0.7575` / `0.76884`
anchor was reproduced by `arena/` independently of `experiments/run_public.py`, and
agrees with the rescued `anchor-legacy` record on all six aggregates and all four
scenario summaries.

**Two measured findings.** Both are reported as measured. Neither was predicted by
this rig, which holds no expectation about either outcome.

- **`ΔTS(A, B)`, the lexical-mode ablation** (`auto` vs forced TF-IDF `fallback`,
  exploration disabled in both): `+0.006110`, 95% CI `[-0.018886, 0.031239]`,
  permutation p `0.645335`, Holm-adjusted p `1.000000`, MDD `0.035987`, sigma-hat
  `0.012845`, corrected `ΔTS` `-0.001137`. Verdict **`not detectable`** — the
  observed delta sits below the minimum detectable difference, so this null is
  uninformative and must **not** be read as evidence that the two engines are
  equivalent. Run B's own aggregates were HitRate@10 `0.925` and TechnicalScore
  `0.774950`, both above run A; the comparison still does not resolve them apart at
  n=200. This differs in direction from the superseded-HEAD forced-fallback figure
  recorded further down this file (`0.75` / `0.599` against an FTS baseline of
  `0.76` / `0.609233`); those were measured at HEAD `e76b3ab` and are not
  same-HEAD-comparable to these.
- **`ΔTS(A, C)`, the exploration ablation** (`disabled` vs `tail-only`):
  `0.000000` exactly, 95% CI `[0.000000, 0.000000]`, permutation p `1.000000`,
  Holm-adjusted p `1.000000`, MDD `0.000000`, corrected `ΔTS` `0.000000`. Verdict
  **`no difference`**. Run C's 200 session outcomes are byte-identical to run A's,
  so the two arms are degenerate and the rig reports them through its zero-variance
  guard rather than as a detectable difference. This reproduces, on committed
  records and at current HEAD, the metric-identical exploration result the
  superseded section below describes in prose.

A permutation p reported by this rig can never be `0`: its Phipson-Smyth floor is
`1 / (R + 1)`, which at `R = 10,000` is `9.999e-05`.

**Which numbers are current.** The three records were regenerated after a defect was
fixed in which a record's stored fingerprint differed from the one the report derived
for it. Fingerprints seed the bootstrap and permutation streams, so the CI, p, MDD and
sigma-hat above are the post-fix values. The session outcomes were byte-identical
across the regeneration and both deltas are unchanged, which is the expected
consequence of an identity-only fix: `ΔTS` depends on the data, not on the seed. The
leaderboard also carries `anchor-legacy` and the `synthetic-promote-10` validation
fixture as report-only entries; neither is adjudicated, so neither joins the Holm
family nor changes `correction_k`, which remains `2`.

### Historical (pre-SQLite, in-memory catalog)

These numbers were measured on the original in-memory catalog. The Task 5 SQLite
artifact migration replaced that engine and its retrieval/ranking code, so these
are **not comparable** to the artifact-backed runs below and are retained only as
history. The `0.785` "accuracy reference" in particular is **not reproducible** on
the current engine and must not be treated as an acceptance gate.

| Class | HitRate@10 | MRR | MTTC | TechnicalScore | Runtime | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Organizer BM25 baseline | 0.125 | 0.068034 | 9.81 | 0.10671 | not recorded | Frozen reference |
| Strict multi-route (in-memory) | 0.315 | 0.149054 | 7.98 | 0.262616 | 106.275 s | Superseded |
| Slate rotation (in-memory) | 0.71 | 0.259663 | 5.71 | 0.538699 | 156.745 s | Superseded |
| Information-gain clarification (in-memory) | 0.785 | 0.38656 | 4.43 | 0.639868 | 185.261 s | Not reproducible post-SQLite |

### Artifact-backed, superseded (SQLite engine at HEAD `e76b3ab`, all 200 public sessions)

Superseded by the current section below. Retained because the exploration
ablation, the determinism check, and the forced-fallback verification recorded
here were measured on this configuration and still describe the shipped design.

Measured after the scalable-retrieval work plus the ranking-recall repair
(restored structured-attribute retrieval, unbounded strict recall, junk-token
gating). Counterfactual exploration on/off is **metric-identical** on the public
set, so the configuration optimizes the happy path: assume the strict pool fills
all ten slots, and fall back to counterfactual relaxation only when it cannot.

| Class | HitRate@10 | MRR | MTTC | TechnicalScore | Runtime | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Strict + empty-pool fallback | 0.76 | 0.360109 | 4.94 | 0.609233 | 747.99 s | Superseded |
| Always tail-explore when slate short | 0.76 | 0.360109 | 4.935 | 0.60933 | ~800 s | Rejected: no metric change |

Scenario HitRate@10 (this run): boundary `0.90`, browsing `0.9375`,
buying `0.775`, intent_override `0.20`.

**Determinism:** two independent full runs of the same configuration produced
identical results after canonicalizing run id, evaluator session UUIDs, and
timing — all 200 session outcomes, the canonical summary, and all 10,419 typed
trace events matched exactly. (Wall-clock runtime varies widely with machine
load — two identical-output runs measured 796 s and 1690 s — so runtime is not a
comparison axis.)

**Exploration ablation.** Counterfactual tail-fill fired on exactly **7 of ~1,500
public turns, every one an empty (zero-strict) pool**; it never fired on a
partial (1–9 strict) pool and changed **zero** hits. So exploration is scoped to
the empty-pool case only: whenever the strict pool holds ≥1 product it already
holds ≥10 on this catalog, and when it is empty the last-resort relaxation is the
only way to return a non-empty slate. This preserves the excluded-prefix
zero-strict guarantee at negligible cost while never running exploration on the
common path where it does nothing.

**Forced-fallback (no-FTS) verification.** Running the full public set with FTS5
disabled (`--lexical-mode fallback`, deterministic TF-IDF postings path) scored
HitRate@10 `0.75` / TechnicalScore `0.599` — near-parity with the FTS engine —
with all 200 sessions completing, no network events, and **every one of the 50
misses attributed to a concrete reason**. This confirms the agent runs fully
offline without FTS5.

### Artifact-backed, current (HEAD `eb4e836`, all 200 public sessions)

Same engine and same `--exploration disabled` configuration as the section
above. The gain came from extraction and matching correctness, not from a new
retrieval or ranking mechanism. Each row was measured on the full 200 sessions
and byte-verified for determinism. Blank cells were not recorded at the time.

| Change | HitRate@10 | MRR | MTTC | TechnicalScore | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline (`e76b3ab`) | 0.76 | 0.360109 | 4.94 | 0.609233 | Superseded |
| DF attribute classification + soft-retain on override + material recovery | 0.915 | | | 0.7642 | Superseded |
| Colon-spacing `match_key` (`2eda04f`) | 0.920 | 0.5221 | 3.425 | 0.7681 | Superseded |
| Comma and slash separator spacing (`4931b90`) | 0.920 | 0.5245 | 3.425 | 0.7688 | **Retained** |
| Keyed-feature recovery (`5044b7c`) | 0.920 | | | | Retained, zero public gain |

Scenario HitRate@10 (retained run): boundary `0.90`, browsing `0.95`,
buying `0.90`, intent_override `0.90`.

**Where the gain came from.** The largest single jump was Intent Override, from
`0.20` to `0.90`, on fixing a retrieve-then-reject bug in which a canonicalized
material reached retrieval SQL but not the eligibility gate. The colon-spacing
fix addressed a systematic false penalty: the catalog writes the same feature
both as `material: alloy` and `material:alloy`, splitting 131 concepts across
705 products, and a target carrying the other spelling took the full
soft-mismatch penalty (about -1.70 log-odds) despite being an exact concept
match. One buying target moved from rank 154 to rank 1.

**Keyed-feature recovery is deliberately retained at zero public gain.** It
structures 169 real product-value pairs across 40 recurring values and was
measured to leave the public metric unchanged with no regression. The public
simulator never constrains on the recovered values, because it speaks the
target's own catalog strings, so the benefit is private-set robustness only.

**Public ceiling.** The remaining 16 misses were audited one belief contribution
at a time. None is a false penalty and none is a vocabulary gap. The
representative case ties the top slate on every stated signal and differs only in
raw retrieval position among roughly 3,000 equally-matching products. A
popularity tie-break was tried and measured no effect, because the `route`
component already varies continuously and leaves no exact ties to break. See
`docs/STATUS.md`.

## Performance notes

- Backend open validates the catalog fingerprint and artifact sizes but does not
  re-hash the ~575 MB database on every startup; measured backend open dropped to
  ~45 ms.
- `get_products` caches materialized records for the life of the backend, so
  rotation-overlapping candidates are not re-fetched or re-parsed across turns.
- Continuous `tracemalloc` allocation tracking is disabled by default; it was the
  dominant cost of traced experiment runs and is diagnostic-only.
- The SQLite read connection is memory-mapped (1 GiB) with a 128 MiB page cache.

## Catalog artifact builds

| Catalog | Products | Catalog size | Database size | Manifest size | Terms | FTS5 | Build time |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| `data/catalog.jsonl` | 50,000 | 60,546,327 B | 575,311,872 B | 652 B | 101,291 | yes | 116.967 s |

## Artifact-backed retrieval microbenchmarks

| Catalog | Startup validation | Filtered count + Top-10 | FTS Top-1,000 | Filtered quality Top-10 |
| --- | ---: | ---: | ---: | ---: |
| 50,000 products | 453.760 ms | 8.192 ms | 81.365 ms | 8.321 ms |

## Constraints and failures

- The catalog contains 112 em-dash prices and five `from N` display prices; these normalize to unknown to avoid false hard-budget decisions.
- Exact catalog phrase matching is precomputed. Per-value regex compilation made the evaluator exceed two minutes before completing.
- Intent-override was the weakest public scenario at HitRate@10 0.2. Diagnosed and fixed: a canonicalized material reached retrieval SQL but not the eligibility gate, so matching products were retrieved and then rejected. Now 0.90.
- Counterfactual routes run only when strict eligibility yields fewer than the requested slate size. Explicit exclusions are never relaxed.
- Two final-schema runs had identical canonical summaries, all 200 session outcomes, and all 843 ordered slates. Runtime differed (185.492 s and 126.485 s).
- The first full artifact build exceeded the 120-second command window while maintaining indexes row by row. Its verified temporary directory was deleted; batching inserts and building secondary indexes after loading produced the retained build above.
- The fixed backend request has no turn identifier. Exact filtered counts remain uncached so results cannot leak across turn scopes; indexed posting-set filters reduced the retained measured request to 8.192 ms.
- Correlated categorical `EXISTS`/`NOT EXISTS` measured 263–293 ms warm on 50,000 products. Equivalent parameterized posting-set `IN`/`NOT IN` measured 3–7 ms and is the retained filter implementation.
