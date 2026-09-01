---
phase: 02-expanded-dataset-paraphrase-probe
plan: 11a
subsystem: testing
tags: [corpus-generation, authoring, detached-authoring, replay, determinism, cli, provenance]

# Dependency graph
requires:
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-07 AuthoringRequest/AuthoringResponse/request_digest/replay_runner/load_prompt/write_response_log"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-09 arena/datasets/generate.py, author_arm's gate loop, main()'s publish sequence"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-05 D-33 preserves_bucket, D-34 measure, D-35 contradicts"
  - phase: 02-expanded-dataset-paraphrase-probe
    provides: "02-08 DatasetEntry registry, publish_corpus"
provides:
  - "arena/datasets/authoring.py: collecting_runner / PendingRequestCollector, the replay-or-collect runner"
  - "arena/datasets/authoring.py: PendingRequest, pending_request, write_pending_requests, load_pending_requests"
  - "arena/datasets/authoring.py: external_response_record, append_response_log"
  - "arena/datasets/authoring.py: PendingRequestsError, DETACHED_SESSION_ID, DETACHED_COST_USD, PENDING_MODEL_RESOLVED"
  - "arena/datasets/generate.py: --emit-pending and PENDING_REQUESTS_EXIT_STATUS = 3"
  - "tests/test_datasets_detached_authoring.py: the end-to-end byte-identity proof on a published 44-session corpus"
affects: [02-11, 02-12]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Replay-or-collect: a runner that answers from a frozen log and queues, rather than fabricates, what it cannot answer"
    - "Dependency-expressed-as-item-overlap: collect one wave per run, stop at the first request conditional on an unanswered one"
    - "Self-sufficient queue record: the full post-load_prompt prompt travels with the request, never its name"
    - "Verbatim key plus an agreement check, rather than recomputing a key that would always agree with itself"
    - "Honest zeros with a sentinel marker, rather than a plausible estimate for provenance nobody observed"

key-files:
  created:
    - tests/test_datasets_detached_authoring.py
  modified:
    - arena/datasets/authoring.py
    - arena/datasets/generate.py
    - docs/STATUS.md

key-decisions:
  - "One run collects one dependency-free WAVE, decided by item-set disjointness, not one batch and not all three attempts speculatively"
  - "The queue record carries the full prompt after load_prompt stripping; a prompt name would leak the maintainer note (D-57) and re-derive a different digest"
  - "request_digest is taken from the queue verbatim and the rebuilt request is only checked against it, never used as its source"
  - "cost_usd, duration_ms and the four usage counters are 0 on this path because nothing was billed, timed or counted; session_id carries DETACHED_SESSION_ID so the log self-identifies"
  - "--emit-pending exits 3, distinct from 1, so a driving script can tell 'answer these and run me again' from 'this corpus cannot be built'"
  - "--emit-pending requires --replay rather than adding a second replay path, so the queue and the log it fills cannot diverge"

metrics:
  duration: "one session"
  completed: 2026-09-01
  tasks: 4
  files: 4
---

# Phase 2 Plan 11a: Detached Authoring Path Summary

A replay-or-collect authoring runner plus an `--emit-pending` CLI, so plan 02-11's corpus
can be authored by externally-spawned subagents instead of by `claude -p` subprocess calls —
proven to produce a byte-identical corpus.

## What was built

`arena/datasets/authoring.py` gains a second way to answer an `AuthoringRequest`, beside
`claude_runner` and `replay_runner`, and both of those are behaviourally untouched.

- **`collecting_runner(*, replay_path, pending_path) -> PendingRequestCollector`.** On a
  digest the log holds it *is* `replay_runner` — the same `_response_index`, the same
  duplicate-digest refusal with the same message (asserted equal, not similar, in
  `test_a_duplicated_digest_in_the_log_is_refused_as_replay_refuses_it`). On a miss it writes
  a pending record and returns an empty-item response, which is a legitimate shape in this
  system rather than a special case: it is what a model returning `[]` produces, so nothing
  downstream needs to know.
- **`PendingRequest` + `write_pending_requests` / `load_pending_requests`.** JSONL,
  `sort_keys=True`, one object per line, `schema_version` 1, exactly nine fields.
- **`external_response_record` + `append_response_log`.** The writer for answers this
  repository did not produce, and an append that refuses a digest the log already carries.
- **`--emit-pending <path>`** on `arena.datasets.generate`, requiring `--replay <log>`, and
  `PENDING_REQUESTS_EXIT_STATUS = 3`.

Nothing downstream changed. The D-33 bucket gate, D-34 divergence gate, D-35 faithfulness
review, D-45 publish validation and D-50 replay reproducibility all run exactly as before,
because the substitution is only in who produces the text.

## How much one run collects, and why that is the maximum

**One run collects one dependency-free wave — every batch of one authoring stage.** For the
probe that is on the order of 60 author requests in a single round, not one.

The rule is item-set disjointness. Two requests naming disjoint item sets cannot depend on
each other: an author batch's prompt is built from its own items' gist payloads and a review
batch's from its own items' phrases, so a miss whose items are disjoint from every already
queued miss is genuinely needed and is queued. The first miss touching an already-queued item
is refused and the run stops.

That is the maximum the loop structure permits, and the two boundaries are structural rather
than chosen:

1. **Within a stage, everything fans out.** `author_arm`'s `produce` issues every batch of
   the pending set before `_local_gates` consumes any of them (`generate.py`, the
   `for start in range(0, len(pending), batch_size)` loop). So the whole stage is collectible
   and halting on the first miss would have cost ~160 runs for the probe.
2. **Across a stage, it cannot.** A review request's prompt embeds the phrases the author
   stage returned (`_review` builds its payload from `produced[item_id]`), and an attempt-1
   author request exists only because specific items failed their gates. Both are conditional
   on an answer nobody has given, so collecting them would be speculation. Concretely: without
   the stop rule, `attempt_until` burns all three attempts on every unanswered item and the
   first round queues **3x** the work, of which two thirds is for prompts the converged run
   never issues.

Measured on the 44-session fixture corpus: **4 rounds, 8 requests, 4/2/1/1** — the sonnet
arm's author stage, the sonnet arm's review stage, then the same two for the haiku
cross-check arm. `test_convergence_takes_one_round_per_dependency_wave` pins that count, so a
regression to one-round-per-batch is visible rather than merely slower.

## The property that had to be proven

**A corpus built through emit → externally-answer → append → replay is byte-identical to one
built by a runner that answered inline.**

`tests/test_datasets_detached_authoring.py` builds a real 44-session probe corpus twice from
a 24-product hand-written catalog — 20 pairs, a 4-pair cross-check arm, three arms, 20
distinct targets, every D-33/D-34/D-35 gate live — once with a runner answering inline and
once by driving `--emit-pending` to convergence with a stand-in answerer that reads only the
queued prompt. `probe.v1.jsonl`, `divergence.jsonl` and `targets.json` compare equal as bytes.

The comparison is two-sided (`test_the_byte_comparison_can_fail` perturbs one phrase and the
bytes differ) and non-vacuous (`test_the_corpus_being_compared_is_not_degenerate` asserts 44
rows, three arms, 20 targets).

The response log is *not* byte-identical, and that is the honest result rather than a defect:
the two logs differ in exactly one field, `session_id`, which is `DETACHED_SESSION_ID` on
every detached record. `test_the_response_log_differs_only_in_its_honest_provenance` asserts
the differing key set is exactly `{"session_id"}`, which is a stronger statement than
equality would have been.

## Honest provenance

No subprocess runs on this path, so `total_cost_usd`, `duration_ms` and the four usage
counters do not exist to be recorded. They are written as `0.0` / `0` — the amount this
repository actually observed — and never as an estimate. A fabricated cost would corrupt the
registry entry's summed corpus spend; a fabricated latency would corrupt the measurement
`CALL_TIMEOUT_SECONDS` is justified against. Because a run of zeros reads equally as "not
billed" and "nobody filled this in", every detached record carries
`session_id = "detached-external-authoring"`. Documented in the `authoring.py` module
docstring and in a new `docs/STATUS.md` subsection, "Deliberate zeros: the provenance the
detached authoring path cannot observe".

`PENDING_MODEL_RESOLVED = "pending-external-authoring"` rides on the placeholder returned for
an unanswered request. It can never reach a committed log — a queued request leaves its items
unaccepted and `attempt_until` refuses to return — and
`test_the_placeholder_model_id_never_reaches_the_committed_log` checks the published bytes.

## Verification

Every new gate was measured in **both** directions with a 12-mutant battery
(`scratchpad/mutate.py`, not committed): each mutant was applied to the source, the module
re-run, and the file restored from bytes.

| Mutant | Caught by |
| --- | --- |
| Collector halts on the first miss | `test_disjoint_misses_are_all_collected_in_one_run`, `..._stop_rule_is_dependency...`, `..._convergence_takes_one_round_per_dependency_wave` |
| Collector never stops | `test_a_miss_sharing_an_item_with_a_queued_one_stops_the_run` |
| Queue tampering unchecked | `test_an_edited_queue_entry_is_refused_rather_than_rehashed` |
| Queue record drops the prompt, keeps the name | `setUpClass` + 3 others |
| `DETACHED_COST_USD = 0.2665` | `test_the_provenance_it_cannot_observe_is_recorded_as_zero` |
| `DETACHED_SESSION_ID = ""` | `test_the_response_log_differs_only_in_its_honest_provenance` |
| Answered items unchecked against the schema | `test_an_item_shaped_against_a_different_schema_is_refused` |
| Append admits a duplicate digest | `test_a_digest_the_log_already_carries_is_refused` |
| Any failure reports as pending | `test_a_failure_with_nothing_queued_is_not_reported_as_pending` |
| Pending status collides with 1 | `test_the_pending_status_is_distinct_from_the_failure_status` |
| Collector not wired into the generator | `setUpClass` + 3 others |
| Digest recomputed rather than taken verbatim | `test_the_response_takes_the_recorded_digest` |

**Zero survivors.** The last one initially survived, and the reason is worth recording: with
the tamper guard in place the rebuilt request provably agrees with the recorded digest, so a
recomputing version is *observationally equivalent* and passes every behavioural test. It is
now pinned with an AST assertion, because someone who later relaxed the guard would be left
with a recomputed digest that always agrees with itself and fails as an unexplained replay
miss.

Traps explicitly avoided:

- **Patched where the name is looked up.** `generate.py` does
  `from ...authoring import replay_runner`, so the test patches
  `arena.datasets.generate.replay_runner`, not the authoring module's attribute. A no-op
  patch would fall through to `claude_runner` and the patched `subprocess.run` raises.
- **No structurally unreachable branch.** The de-duplication branch is reachable only because
  the digest check precedes the overlap check — the other order would have made a repeated
  request overlap itself and left the branch dead. `test_an_identical_request_is_queued_once...`
  enters it directly.
- **Negative tests assert the branch's own message**, not just `AuthoringError`: the module
  raises that type from 36 places, several of them reachable from the same input. Every
  `assertRaises` checks a distinguishing substring.
- **The fixture is not degenerate.** The catalog and phrase table were built against the real
  gates, not around them: `plasticky` was the first draft of the material paraphrase and is
  rejected because `plastic` is admitted vocabulary the fixture targets lack (D-35), and 20
  pairs with a 4-pair cross-check arm is the smallest shape clearing the registry's 0.02
  scenario-mix tolerance *in rows*.

Suite: **742 tests, 8.0 s, OK** (697 at base + 45 new), green under
`python -W error::ResourceWarning`, and green with `claude` removed from `PATH`.

## OPERATOR PROTOCOL

Read this section alone; it does not require the code.

### Prerequisites

- `data/catalog.jsonl` present (61 MB, gitignored, not needed for tests but needed here).
- `.scratch/` exists: `uv run python -c "import pathlib; pathlib.Path('.scratch').mkdir(exist_ok=True)"`
- `claude` need NOT be on PATH. Nothing on this path spawns it.

### 1. Emit pending requests (the command, run from the repository root)

```
uv run python -m arena.datasets.generate --corpus probe.v1 \
    --pairs 300 --cross-check-pairs 100 \
    --model sonnet --prompt author_probe.md --batch-size 20 \
    --replay data/responses/probe.v1.jsonl \
    --emit-pending .scratch/pending.probe.v1.jsonl \
    --response-log data/responses/probe.v1.jsonl
```

`--response-log` is given explicitly because its default is
`data/responses/responses.probe.v1.jsonl`, and plan 02-11's artifact list names
`data/responses/probe.v1.jsonl`. `--replay` must be that same file: it is the log being
accumulated, and `--emit-pending` refuses to run without it.

Exit statuses:

| Status | Meaning |
| --- | --- |
| `3` | Requests were queued. Answer them, append, run the identical command again. Stdout carries `pending_requests=<n>`, `pending_path=...`, `response_log=...`. |
| `0` | The log satisfied every request. The corpus is already published, gated, registered and rendered. Stop. |
| `1` | A real failure. Stderr carries `corpus generation failed: ...`. Do NOT re-run blindly; nothing was queued, so repeating the round changes nothing. |

Rounds 2+ are the **identical command**. Nothing changes between rounds except the contents
of the log.

### 2. The pending-record shape a subagent must be handed

One JSON object per line in `.scratch/pending.probe.v1.jsonl`, exactly nine keys:

```json
{
  "item_ids": ["probe_v1_0000:h0", "probe_v1_0000:h1"],
  "kind": "author",
  "model_alias": "sonnet",
  "prompt": "<the FULL prompt text, maintainer notes already stripped, ending in a single JSON line>",
  "prompt_name": "author_probe.md",
  "prompt_revision": "<sha256 of the newline-normalized prompt file>",
  "request_digest": "<sha256, the replay key>",
  "schema_json": "{\"items\":{...},\"type\":\"array\"}",
  "schema_version": 1
}
```

Hand the subagent **`prompt` verbatim** as its entire instruction, plus `schema_json` as the
required output shape. Do NOT hand it `prompt_name` and let it read the file: the committed
prompt carries a maintainer note that tells the author what the measurement is for, which is
the D-57 contamination `load_prompt` strips, and any re-derived whitespace mints a different
digest.

Give the subagent no other repository context — no `CLAUDE.md`, no catalog, no `parent_asin`.
The `prompt` is deliberately the complete and only input.

`kind` is `"author"` or `"review"`. Author batches are ~20 items, review batches ~40.

### 3. The shape a subagent must return

A JSON array, one object per requested `id`, ids drawn only from `item_ids`, no duplicates.
A short array is acceptable — the generator re-authors what is missing.

- `kind: "author"` → `[{"id": "probe_v1_0000:h0", "phrase": "..."}, ...]`
- `kind: "review"` → `[{"id": "probe_v1_0000:h0", "verdict": "faithful"}, ...]` where
  `verdict` is one of `drifted`, `faithful`, `wrong`.

Exactly those keys — an extra or renamed key is refused at append time with
`answered item N has keys [...], expected [...]`.

### 4. Append an answered record to the response log (the function)

Write this to `.scratch/answer_pending.py` (`.scratch/` is gitignored) and run it once per
round after every queued record has an answer. `ANSWERS` maps `request_digest` to the array
the subagent returned.

```python
import json
from pathlib import Path

from arena.datasets.authoring import (
    append_response_log,
    external_response_record,
    load_pending_requests,
)

PENDING = Path(".scratch/pending.probe.v1.jsonl")
LOG = Path("data/responses/probe.v1.jsonl")
ANSWERS = json.loads(Path(".scratch/answers.json").read_text(encoding="utf-8"))
RESOLVED = {
    # The id the subagent ACTUALLY ran as, read off the subagent, not guessed.
    # Deliberately left as placeholders here: writing a plausible id into this
    # summary would be the same fabrication the zeroed cost fields exist to avoid,
    # and the recorded id is the whole of the D-39/MEAS-13 generator-affinity claim.
    "sonnet": "<resolved sonnet id>",
    "haiku": "<resolved haiku id>",
}

for record in load_pending_requests(PENDING):
    digest = str(record["request_digest"])
    items = tuple(ANSWERS[digest])
    appended = external_response_record(
        dict(record),
        items,
        model_resolved=RESOLVED[str(record["model_alias"])],
    )
    append_response_log(LOG, (appended,))
print(f"appended {len(load_pending_requests(PENDING))} record(s) to {LOG}")
```

`model_resolved` must be a **resolved model id, never the alias** `sonnet` or `haiku` —
`AuthoringResponse.validate()` refuses an alias, and `_resolved_for_alias` requires exactly
one resolved id per arm, so it must be the same string for every record of one arm across all
rounds. Getting this wrong is caught, but only at the end of the last round.

### 5. Finish the corpus

Re-run the **step 1 command unchanged** until it exits `0`. That run does the whole normal
publish: `publish_corpus`, `write_response_log`, `write_divergence_log`,
`write_target_snapshot`, `upsert_entry`, `render_markdown`, and prints the same summary line
plan 02-11 task 1 asks for:

```
corpus=probe.v1  sessions=700  targets=300  sha256=...  divergence_pairs=...
snapshot_targets=300  calls=...  cost_usd=0.0  model_resolved=...
```

`cost_usd=0.0` is expected and correct on this path. Then continue with plan 02-11 task 1
step 5 (commit the six artifacts, report the freezing commit hash) unchanged.

Note: the final run **rewrites** `data/responses/probe.v1.jsonl` from the calls it actually
made, in call order. The committed log is therefore canonical and minimal, and any record an
operator appended that the run did not need is dropped rather than committed.

### 6. Expected round count, and how to tell it has converged

**Converged ⇔ exit status `0` and `.scratch/pending.probe.v1.jsonl` is empty (0 bytes).**
The queue file is rewritten at the start of every round, so it always describes the current
round and never a stale one. An absent corpus file plus a non-empty queue means another round.

**Minimum 4 rounds** if no constraint fails a gate:

| Round | Wave | Approximate request count |
| --- | --- | --- |
| 1 | sonnet arm, author stage | ~60 (≈1,200 items / 20) |
| 2 | sonnet arm, faithfulness review | ~30 (≈1,200 items / 40) |
| 3 | haiku cross-check arm, author stage | ~20 (≈400 items / 20) |
| 4 | haiku cross-check arm, review | ~10 (≈400 items / 40) |

Roughly 120 requests total. Each round of re-authoring adds **two** rounds for the affected
arm (a re-author wave and its review wave), and `AUTHORING_ATTEMPT_CAP = 3` bounds it, so the
worst case is **12 rounds**. `pending_requests=` falls sharply once re-authoring starts —
a round queueing 3 requests is re-authoring a handful of items, not a stage.

If a round exits `1` with `authoring failed after 3 attempts for N item(s): ...`, that is the
attempt cap, not this path. Plan 02-11's instruction applies unchanged: report which gate and
which bucket failed and stop. **Do not relax a gate.**

## Deviations from Plan

This was enabling work specified directly in the executor brief rather than by a PLAN.md, so
there is no plan to deviate from. Two judgement calls worth recording:

1. **`collecting_runner` returns a `PendingRequestCollector`, not a bare `AuthoringRunner`.**
   The brief's signature says `-> AuthoringRunner`. The concrete class satisfies that Protocol
   (`test_the_collector_satisfies_the_runner_protocol`), and the generator needs `.pending` and
   `.pending_path` to decide the exit status, so annotating the concrete type is honest where
   the Protocol would have required an untyped attribute access.
2. **`external_response_record` rebuilds the request and checks it against the recorded
   digest.** The brief says never to recompute the digest, which this honours — the recorded
   value is what is written. The rebuild exists only to catch a queue file edited in transit,
   a failure the brief's rule would otherwise leave silent.

No gate was weakened, bypassed or special-cased. `claude_runner` and `replay_runner` are
behaviourally unchanged; the only edit to either was extracting `replay_runner`'s index
loading into `_response_index` so the collector could share it, and the duplicate-digest
message is asserted equal between the two.

## Known Stubs

None.

## Self-Check

- `arena/datasets/authoring.py` — FOUND (modified)
- `arena/datasets/generate.py` — FOUND (modified)
- `docs/STATUS.md` — FOUND (modified)
- `tests/test_datasets_detached_authoring.py` — FOUND (created)
- commit `88d9c01` — FOUND
- commit `6e44d3a` — FOUND

## Self-Check: PASSED
