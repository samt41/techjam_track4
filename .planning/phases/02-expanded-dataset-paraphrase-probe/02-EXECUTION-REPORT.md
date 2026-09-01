# Phase 02 execution report

**Status:** 11 of 14 plans complete. `probe.v1`, `expanded_dev.v1`, `expanded_confirm.v1`
are not frozen. Plans 02-11, 02-12 and 02-13 remain incomplete.

**Test suite:** 800 passing, warning-strict, with no `claude` on PATH.

This report exists because the phase's most valuable output is not the corpus it failed to
freeze. It is a set of measured findings about the corpus-generation design, three of which
were defects that would otherwise have shipped inside a frozen artifact.

## What landed

| Plan | Delivered |
|---|---|
| 02-01 | Evaluator seam widened to eight names; boundary guard made recursive over `arena/**` |
| 02-02 | D-53 corpus-baselines JSON + Markdown surface, added as siblings to the leaderboard |
| 02-03 | Corpus row schema, canonical JSONL serializer, both MEAS-10 conformance layers |
| 02-04 | D-32 DF-gated anti-circularity gist; committed vocabulary and abstraction assets |
| 02-05 | D-33 bucket gate and D-34 divergence gate |
| 02-06 | D-44 paired-contrast readout with exact McNemar |
| 02-07 | Build-time authoring driver, prompt pack, runtime-purity import-graph proof |
| 02-08 | D-43 dataset registry with publish-time validation |
| 02-09 | Corpus generator |
| 02-10 | Operator CLI entry points; registry-name resolution |
| 02-14 | Control-arm fidelity, D-36 pair pinning, L-3 solvability absence |

Four corrective plans were added during execution and are also merged: 02-09a, 02-09b,
02-11a, 02-11b. Their SUMMARY files sit alongside the others.

## Three generator defects found by execution, not by review

Each was found only by attempting the next step, and each was invisible to the tests that
existed because those tests could not fail on it.

**1. Slot/gist assignment preferred novelty over bucket agreement (02-09a).**
`constraint_slots` ranked an unspent gist pair in the *wrong* bucket above a spent pair in the
*right* one. Once the bucket-matched pool exhausted, constraints were issued whose bucket and
gist named different attributes — `bucket=color` with `gist=entry_method=toothed_fastener`.
Such an item is unsatisfiable: D-33 demands the phrase classify as `color`, D-35 and the
prompt's rule 5 forbid inventing the colour word that would put it there. Measured: 393 of
1,197 constraints mismatched (32.8%); mismatched items failed 79.9% of the time after two
attempts against 49.5% for matched ones. The fix closed every avoidable case (`avoidable=0`).

**2. Gist supply could not serve every bucket (02-09b).**
After the ordering fix, 275 mismatches remained as a supply floor — targets with no gist pair
in the required bucket at all, 141 of them flatly unsatisfiable `color`/`size` cases.
`_GIST_DF_FLOOR = 10` retains only 24 of 1,127 catalogue colour values and 11 of 330 size
values. Constraints the gist cannot serve are now never emitted, and targets left without a
full hard or soft list are refused. Mismatches reached 0. **Cost:** the eligible pool fell
40,199 → 34,222 (14.9% refused), non-uniformly — `women|under_20` is 3.12% of admitted targets
but 10.29% of refused. Recorded in the sampling-bias section above.

**3. The D-34 adjacency check rejected on function-word spans (02-11b).**
Shared bigrams composed entirely of stopwords — `with a`, `it s`, `to be`, `to the` — counted
as lexical overlap. Twelve constraints were rejected with content overlap of exactly `0.0000`.
`STOPWORDS` was applied to content-word overlap but not to bigram formation. Fixed, with
`rubber sole` proven to still reject.

## The measured failure taxonomy

From a run that reached the cap and named every survivor with its reason — 310 constraints:

| Reason | Count | Share |
|---|---:|---:|
| D-34 lexical/bigram overlap | 202 | 65% |
| Phrase asserts admitted vocabulary the target lacks | 87 | 28% |
| D-35 review returned `drifted` | 17 | 5% |
| D-33 bucket moved | 4 | 1% |

Of the 202 overlap rejections: median overlap 0.125, 135 below 0.15.

## D-32 anti-circularity demonstrably has teeth

The dominant failure mode is the strongest evidence in this phase that the design works.
Authors never see the control phrase — the gist abstracts it away on purpose — and they
reconstructed it anyway by reaching for the obvious retail term:

| gist | stuck items | contained the catalogue's own word |
|---|---:|---:|
| `laundering=home_launderable` | 39 | **100%** contained "wash" (listing: "Machine wash") |
| `entry_method=toothed_fastener` | 17 | **100%** contained "zip" (listing: "Zipper closure") |
| `ground_contact=vulcanised_tread` | 62 | 53% contained "rubber" (listing: "Rubber sole") |

A corpus authored without this gate would be full of catalogue echoes and would flatter any
agent that matches on catalogue text. This is the circularity D-32 exists to prevent, caught
in the act.

## D-33 and D-35 are complementary, not redundant

Both gates are necessary, and each catches what the other structurally cannot.

- `a sturdy fabric` for `material=iron` passes D-33 cleanly — `fabric` is a valid `material`
  routing keyword — and is caught only by D-35 as `wrong`. It was independently re-caught by a
  different reviewer in a later round, which is reasonable evidence the instrument is
  measuring something real rather than sampling noise.
- A semantically perfect phrase that drops its routing keyword passes D-35 and is caught only
  by D-33.

## An unresolved tension worth carrying forward

For `ground_contact=vulcanised_tread` the two gates pull against each other. D-34 requires the
catalogue's word (`rubber`) to be absent; D-35 requires the phrase to pin the value rather than
its siblings. But the value's concise discriminator *is* that word — the defining trait is a
heat-bonded single-piece sole, and phrases that describe only the effect ("grips smooth floors
and won't skid") were correctly judged `drifted` because they fit `engineered_tread` equally
well. Reviewers flagged this pattern independently across several batches. Either the
abstraction needs a discriminator that is not the catalogue term, or this attribute needs a
documented exemption.

## Cost

Roughly 16M orchestrator + subagent tokens. No API spend and no `claude` CLI: authoring ran
through Claude Code subagents (`sonnet` for the probe arm) via the detached path, at the user's
direction. Provenance on that path is honest about its limits — `cost_usd` and usage counters
are recorded as `0` because nothing was billed and no per-request usage is observable, and
`model_resolved` is orchestrator-asserted rather than read back off a runtime. Both are
documented under "Deliberate zeros" in `docs/STATUS.md`.

## What blocks the corpus

See "Blocking defect: the detached authoring path cannot reach the attempt cap" in
`docs/STATUS.md`. `data/responses/probe.v1.jsonl` (179 records) is committed so the authoring
already paid for can be replayed rather than re-spent.

## Corrections to plan literals, owed when the corpus is next attempted

Plan 02-11 states `sessions=700`, `targets=300`, `snapshot_targets=300` and asserts
`target_snapshot_count == 300`. Under the 02-09b supply refusal the real figures are ~500
sessions over 217 viable pairs, before any cap-exhaustion drops. Those literals and that
acceptance command are wrong as written.
