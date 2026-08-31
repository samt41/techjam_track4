---
phase: 01-measurement-rig-core
plan: 14
subsystem: arena-leaderboard
tags: [auditability, fail-closed, gap-closure, mutation-tested, holm-family]
requires:
  - arena/store.py
  - arena/candidate.py
  - arena/adjudication.py
provides:
  - "fail-closed stored-versus-derived fingerprint check on the record read path"
  - "assumptions.holm_family_size derived from the adjudicated rows"
  - "assumptions.holm_family_includes_degenerate_arms as stated policy"
  - "RecordIdentityTest: mutation-verified refusal plus the legal absent-digest case"
affects:
  - arena/leaderboard.py
tech-stack:
  added: []
  patterns:
    - "promote a suite-only invariant into the code path when the suite can only speak for artifacts that already exist"
    - "a report states its own family composition rather than leaving the multiplier to be inferred from source"
key-files:
  created: []
  modified:
    - arena/leaderboard.py
    - tests/test_arena_leaderboard.py
decisions:
  - "A record storing NO fingerprint stays legal: the rescued anchor-legacy record is provenance-free by design, and refusing it would reject the MEAS-16 anchor"
  - "holm_family_size is derived from rows; holm_family_includes_degenerate_arms is a hardcoded True because it states the POLICY, not an observation about one report"
  - "LEADERBOARD_SCHEMA_VERSION stays 1 -- both keys are additive inside assumptions and no consumer reads that block positionally"
metrics:
  duration: "~25m"
  completed: 2026-08-31
  tasks: 3
  commits: 3
  tests_before: 366
  tests_after: 370
---

# Phase 01 Plan 14: Leaderboard Record Identity and Holm-Family Disclosure Summary

Promoted the stored-versus-derived fingerprint check from a suite-only assertion over
already-committed records into a fail-closed guard on the read path, and recorded plan
01-10's WR-05 decision in the machine-readable `assumptions` block so the Holm multiplier
is re-derivable from the payload alone.

## What changed

**Task 1 (`75f0c67`) — a record that cannot identify itself is refused when read.**
`_spec_from_payload` now reads `record.get("fingerprint")` into `stored` and raises
`ArenaStoreError` when it disagrees with `spec.fingerprint`, naming the run directory,
the stored digest and the derived digest in that order. `ArenaStoreError` was added to
the existing `arena.store` import block — no new import statement, no new module
dependency. Because `spec_from_record` and `entry_from_record` both route through
`_spec_from_payload`, one edit covers both public readers and neither carries a copy.

The `stored is None` branch proceeds unchanged and is commented as deliberate rather than
lax: the rescued `anchor-legacy` record stores no `fingerprint` key at all, so there is
nothing for it to diverge from, and hardening the branch into a refusal would reject the
MEAS-16 anchor. `spec_name_from_record`, the `"unknown_revision"` / `"unknown"` defaults
and the `code_revision_dirty` fail-closed default of `True` are untouched.

**Task 2 (`ef7f1d9`) — the payload states its own family composition.** Two additive keys
inside `assumptions`:

- `holm_family_size` — `len(rows)`, derived from the rows on the same "describe what
  actually produced these rows" discipline as `resample_count`. `0` for an empty
  adjudication, which is the honest answer for a report that adjudicated nothing.
- `holm_family_includes_degenerate_arms` — a literal `True`, stated as standing policy so
  it reads the same whether or not a given report happened to contain a degenerate arm.

The `holm_family` prose keeps its existing content and appends why a zero-delta,
zero-SE arm still counts toward the family and toward `correction_k` (the family size is
a property of the experimental design; shrinking it post hoc is a data-dependent family
definition) and names `--include` as the a-priori mechanism for a retained record that
belongs in the report without joining the family.

**Task 3 (`9ad5dfa`) — `RecordIdentityTest`, 4 methods.** A module-level `_write_record`
builder writes a minimal valid record into a temporary directory, with a single
`fingerprint: str | None` keyword where `None` omits the key, so the drifted, absent and
matching cases differ only in the stored digest. Nothing reads or writes under the
committed baselines. `CommittedLeaderboardTest` is untouched, and no assertion was added
requiring the committed `leaderboard.json` to carry the new keys — plan 01-15 regenerates
it.

## Verification

| Check | Result |
|---|---|
| `uv run python -m unittest -v tests.test_arena_leaderboard` | 34 tests, OK, 0.10 s (30 before + 4) |
| `uv run python -m unittest tests.test_arena_boundary` | 8 tests, OK |
| `uv run python -W error::ResourceWarning -m unittest discover -s tests` | **370 tests, OK, 4.84 s** (366 baseline + 4) |
| `test_the_committed_markdown_matches_the_committed_payload` | passes — not one rendered byte changed |
| `test_every_record_derives_the_fingerprint_it_stores` | still passes |
| `git status --porcelain experiments/` | empty, after the full suite ran |

**Scope fence held.** `git diff -U0 arena/leaderboard.py` produced hunks at the import
block and inside `_spec_from_payload` (Task 1), then two inside `build_leaderboard`'s
returned `assumptions` mapping (Task 2). No hunk falls inside `HOW_TO_READ`,
`render_markdown`, `_cell` or `_table`.

**Grep gates, verified in BOTH directions** against `git show 0e5bc91:<file>`:

| Gate | Pre | Post | Required |
|---|---|---|---|
| `grep -c 'ArenaStoreError' arena/leaderboard.py` | 0 | 2 | 2 |
| `grep -v '^\s*#' … \| grep -c 'record.get("fingerprint")'` | 0 | 1 | 1 |
| `grep -c 'def _spec_from_payload' arena/leaderboard.py` | 1 | 1 | 1 |
| `grep -c 'holm_family_size' arena/leaderboard.py` | 0 | 1 | — |
| `grep -c 'holm_family_includes_degenerate_arms'` | 0 | 1 | — |
| `grep -cE 'holm_family_size\|…\|is_degenerate' tests/…` | 0 | 4 | >= 4 |
| `grep -c 'experiments/baselines' tests/…` | 2 | 2 | no increase |

Every gate except `def _spec_from_payload` discriminates. That one is structural — it
reads `1` on unmodified source too — so it confirms the function was not duplicated
rather than that the change landed; the discriminating evidence for Task 1 is the
`ArenaStoreError` count plus the mutation check below.

**Behavioural checks (executed):**

- A temporary record storing `"0" * 64` raises `ArenaStoreError` from both readers, with
  message `drifted-record stores fingerprint 0000… but derives b371aa7499c4…` — directory
  name, stored digest, derived digest, in that order.
- `spec_from_record` still succeeds on all five committed records: `anchor-legacy`
  (`b8ce126916a0`, stores no digest), `run-a` (`c23c99876ee0`), `run-b` (`e0d73537d58b`),
  `run-c` (`8c95a79adbf4`), `synthetic-promote-10` (`6eec1db14d0c`).
- A two-row adjudication with one arm identical to the baseline yields
  `holm_family_size 2`, `holm_family_includes_degenerate_arms True`,
  `is_degenerate [False, True]`, `correction_k [2, 2]`.
- `rows=()` yields `holm_family_size 0` and still renders the `| _none_ |` fallback.
- `LEADERBOARD_SCHEMA_VERSION` prints `1`.

## Mutation testing

`if stored is not None and …` was mutated to `if False and stored is not None and …`,
which disables the comparison while leaving every grep gate satisfied — a stricter
mutation than deleting the block.

| Mutation | Tests failed |
|---|---|
| comparison disabled in `_spec_from_payload` | 1 method — `test_a_drifted_reconstruction_is_refused`, failing in **both** subTests (`spec_from_record` and `entry_from_record`) |

Reverted with `git checkout -- arena/leaderboard.py`; `git diff --stat
arena/leaderboard.py` confirmed empty afterwards. The non-vacuity direction is covered by
`test_a_matching_record_is_admitted` — a check that refused everything would still pass
the refusal test.

## Deviations from Plan

None. All three tasks executed as written; no deviation rule fired.

One observation recorded rather than acted on, per the plan-gate hazard brief: Task 1's
`grep -c 'def _spec_from_payload'` criterion is not two-sided — it returns `1` against
unmodified source, so it cannot distinguish a correct implementation from an untouched
one. It is still worth keeping as a "the check was not duplicated into a second
reconstruction" assertion, which is what the plan's accompanying clause ("and the check
appears exactly once in the file") actually asks for. No code change was made for it.

## Known Stubs

None. No `TODO`, `FIXME` or `PLACEHOLDER` marker was introduced in either file, and no
hardcoded empty value flows to a consumer.
`holm_family_includes_degenerate_arms` is a literal `True` by explicit design — it states
the project's standing policy, not an observation about the current rows — and is
documented as such both in the source comment and in the plan.

## Threat Flags

None. No new network endpoint, credential, filesystem write, deserialization path or
trust boundary. The plan's `mitigate` dispositions are implemented and each has a named
test: T-01-33 (spoofed record identity) by the mutation-verified
`test_a_drifted_reconstruction_is_refused` across both readers; T-01-34 (unauditable
family size) by `test_the_assumptions_block_states_the_holm_family_composition`; T-01-16
(drifted rendered report) unchanged and re-confirmed by
`test_the_committed_markdown_matches_the_committed_payload`; T-01-16b unchanged and
re-confirmed by `test_the_synthetic_control_is_labelled_as_a_fixture`. T-01-SC holds:
zero packages installed, `dependencies = []` unchanged, one name added to an existing
`arena.store` import and nothing else.

## Handoff to plan 01-15

The committed `experiments/baselines/leaderboard.json` does not yet carry
`holm_family_size` or `holm_family_includes_degenerate_arms` (nor `is_degenerate` on its
adjudication rows, from plan 01-10). The suite is unaffected — `render_markdown` selects
keys by name and the committed payload is read from disk, so
`test_the_committed_markdown_matches_the_committed_payload` still passes. Plan 01-15 owns
regenerating both artifacts and adding the prose disclosure of this policy to
`HOW_TO_READ`, which was deliberately left untouched here.

## Self-Check: PASSED

- `arena/leaderboard.py` — FOUND, modified
- `tests/test_arena_leaderboard.py` — FOUND, modified
- Commit `75f0c67` — FOUND
- Commit `ef7f1d9` — FOUND
- Commit `9ad5dfa` — FOUND

STATE.md and ROADMAP.md deliberately not modified — worktree mode; the orchestrator owns
those writes after the wave merges.
</content>
</invoke>
