---
phase: 02-expanded-dataset-paraphrase-probe
plan: 07
subsystem: tooling
tags: [authoring, subprocess, claude-cli, replay, provenance, prompt-pack, isolation]

# Dependency graph
requires:
  - phase: 02-03
    provides: "tests/dataset_fixtures.py fake_authoring_response(...) -- the recorded claude -p envelope with `result` as a JSON string"
  - phase: 02-04
    provides: "arena/datasets/gist.py prompt_payload_strings -- the attribute=value form the author prompts interpolate"
  - phase: 02-05
    provides: "arena/datasets/divergence.py _FEATURE_TRIGGER_SUBSTRINGS (the 33 substrings the probe prompt forbids) and ordered_tokens"
provides:
  - "arena/datasets/authoring.py -- the build-time claude -p driver: build_argv, claude_runner, replay_runner, response log, provenance whitelist, attempt cap"
  - "Three committed revision-hashed prompt files (author_probe, author_expanded, review_faithfulness)"
  - "prompt_revision / load_prompt -- the D-43 revision digest and the maintainer-note-stripped prompt body"
  - "log_record / write_response_log / load_response_log / response_log_path -- the D-50 frozen replay log"
  - "assert_single_resolved_model -- the MEAS-13 corpus-close alias-drift check"
  - "attempt_until -- the bounded re-authoring loop"
  - "AuthoringRunner Protocol -- the injection seam that keeps claude out of the test suite"
affects: [02-08, 02-09, 02-10, 02-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Injected runner behind a typing.Protocol; replay is a production path, not a test-only path"
    - "argv construction split into a pure function so process-hygiene properties are asserted without spawning anything"
    - "Content-normalized digests for committed text assets, because core.autocrlf makes raw working-tree bytes checkout-dependent"
    - "Maintainer rationale committed inside the prompt file as an HTML comment and stripped before send, so the note reaches editors but never the model"
    - "Mutation sweep as acceptance evidence: 10 mutations of the driver, each required to turn the suite red"

key-files:
  created:
    - arena/datasets/authoring.py
    - arena/datasets/assets/prompts/author_probe.md
    - arena/datasets/assets/prompts/author_expanded.md
    - arena/datasets/assets/prompts/review_faithfulness.md
    - tests/test_datasets_authoring.py
  modified:
    - docs/STATUS.md

key-decisions:
  - "prompt_revision hashes newline-normalized content, NOT sha256_file's raw bytes as the plan specified: core.autocrlf is on and no .gitattributes exists, so the same committed prompt is CRLF in one checkout and LF in another and a raw digest would report a spurious revision change (measured on this worktree)"
  - "Maintainer notes live in the prompt files but are stripped by load_prompt before send; telling an author that a purpose is being withheld invites it to guess, which is the contamination D-57 exists to prevent"
  - "claude_runner refuses a modelUsage carrying more than one resolved id: one call attributed to two generators would misattribute part of its own batch (T-02-28)"
  - "claude_runner refuses a result item whose id was not requested; a subset is fine because that is exactly what attempt_until re-authors, but an unrequested id would file one item's phrase under another item's identity"
  - "build_argv validates schema_json parses as JSON, so the measured Windows-drive-letter failure is caught locally instead of after a spawned call"
  - "replay_runner refuses a log with a duplicated request digest rather than picking one: two records under one key make replay a coin flip dressed up as reproduction"
  - "The credential scan in the provenance test looks for credential markers (anthropic, api_key, oauth, bearer, environ, secret), never the bare word `token`, because the four legitimate usage counters are named *_tokens; the key set is pinned to a literal instead, which is the stronger check"

patterns-established:
  - "Absence gates are proven by mutation: a grep asserting `count == 0` passes on any file, including an empty one, so it is only evidence once a deliberately broken copy is shown to fail it"
  - "Runtime purity is asserted as an import-graph property over starter/**, with the scanner itself shown to fire on both a static and a dynamic import"

requirements-completed: [MEAS-12, MEAS-13]

# Metrics
duration: 70min
completed: 2026-09-01
---

# Phase 02 Plan 07: LLM Authoring Driver Summary

**A build-time `claude -p` driver whose D-35 context isolation and D-57 anti-contamination properties are asserted by argv and cwd introspection rather than hoped for, backed by a committed prompt pack, a digest-plus-parsed-result replay log, and a test module that never spawns the tool — verified green with the `claude` binary removed from PATH.**

## Performance

- **Duration:** ~70 min
- **Tasks:** 3 of 3
- **Tests:** 594 total (50 new), all green in 5.1 s
- **Deviations:** 4 (all auto-fixed under Rules 1-3)

## What Was Built

### Task 1 — the committed prompt pack (`f3ad569`)

Three revision-hashed Markdown files under `arena/datasets/assets/prompts/`.

`author_probe.md` (Sonnet) and `author_expanded.md` (Haiku bulk) carry the same
five hard rules, deliberately identical so that a difference between the probe
and expanded corpora cannot be a difference in instructions. Both embed the full
33-substring `classify_constraint` trigger list inline (L-5) and both measured
traps as worked examples: `no fitting room needed` rejected on `fit`,
`good for everyday work` rejected on `work`. Rule 4 carries the measured
`a leathery finish` example — the routing keyword survives as a fragment while
`leathery` is a word a listing never prints.

Neither author prompt names the probe, the hypothesis, the Innovation narrative,
or the anti-circularity goal. `review_faithfulness.md` is scoped to exactly
`gist_attribute`, `gist_value`, `phrase`, states the three verdicts, and treats
negation as `wrong` with the `nothing woollen` / `material=wool` worked case,
because the lexical gate cannot see negation at all (`no` and `not` are
stopwords).

### Task 2 — `arena/datasets/authoring.py` (`56df5fe`)

606 lines. `build_argv` is a pure function precisely so the hygiene properties
are testable without spawning a process; it emits `--setting-sources ""`, no
`--max-turns`, no `--bare`, no resume flag, and never the prompt. `claude_runner`
spawns a tuple argv from a fresh brief-free temporary directory with the prompt
on stdin and a timeout, parses two `json.loads` levels, and branches on
`is_error` / `subtype` rather than returncode, because exit code 0 alongside
`is_error: true` was measured.

Provenance is opt-in by name: `_PROVENANCE_FIELDS` plus the four `usage` counters
plus the resolved `modelUsage` key. The module reads no environment variable at
all. The replay log commits request digests and parsed results, never raw
envelopes, and the accepted cost of that — a reviewer can re-derive the corpus
but cannot re-audit the parse — is stated in the module docstring, which is why
the parse is kept small and tested rather than trusted.

`docs/STATUS.md` gained tier-2 entries for `AUTHORING_ATTEMPT_CAP` and
`CALL_TIMEOUT_SECONDS`, each naming its basis. The cap entry says plainly that
the number is a judgement rather than a measurement — no re-authoring pass has
run, so there is no acceptance-rate curve to tune against — and that what is
measured is the cost of the unbounded alternative.

### Task 3 — `tests/test_datasets_authoring.py` (`0985979`)

50 tests, 0.17 s, no case spawns `claude`. Beyond the nine classes the plan
named, two were added: `PromptPackTest` (revision stability, maintainer-note
stripping) and `RuntimePurityTest` (the driver is unreachable from `starter/`,
asserted over the import graph).

## Verification

### Two-sided proof of every grep-style gate

Per the phase's standing instruction, each gate was measured in both directions.
Absence gates (`count == 0`) are the dangerous class: they pass on any file,
including an empty one, so each was run against a deliberately broken copy.

| Gate | Real source | Mutated source |
|---|---|---|
| `shell=True\|os.system` count is 0 | 0 | 1 |
| `os.environ\|getenv` count is 0 | 0 | 1 |
| `timeout=CALL_TIMEOUT_SECONDS` non-comment count ≥ 1 | 1 | 0 |
| banned framing phrases absent from author prompts | exits 0 | exits 1 (`vocabulary gap` inserted) |

All four are genuinely two-sided. **No one-sided gate was found in this plan** —
the first plan this phase for which that is true, other than 02-04.

### Mutation sweep against the driver

Ten mutations, each breaking one property the plan calls load-bearing. Every one
turned the suite red; none survived.

| Mutation | Cases that caught it |
|---|---:|
| drop `--setting-sources` from argv (D-57) | 3 |
| drop the clean cwd, run from the repository root (D-57) | 1 |
| branch on returncode instead of `is_error`/`subtype` (L-14) | 1 |
| drop the subprocess timeout (T-02-06) | 1 |
| record the alias instead of the resolved model id (T-02-28) | 13 |
| deliver the prompt as an argument instead of stdin (T-02-01) | 1 |
| leak an environment-shaped field into the committed record (V7) | 7 |
| make the attempt cap unbounded (T-02-06) | 1 |
| hash raw bytes so a line-ending change moves the revision (D-43) | 1 |
| stop stripping maintainer notes from the sent prompt (D-57) | 3 |

### Runtime purity, proven rather than asserted

The executor brief warned that a test asserting "authoring is build-time only"
is worthless if it would still pass when the module were imported at runtime.
`RuntimePurityTest` therefore asserts an import-graph property over every module
under `starter/**` (no top-level `arena` import, including via a string constant
handed to `importlib`), **and** proves the scanner fires on both a static
`from arena.datasets.authoring import claude_runner` and a dynamic
`importlib.import_module("arena.datasets.authoring")`. The mutation sweep is the
other half: the scan is not merely non-vacuous, it is load-bearing.

Empirically, the full 594-test suite passes with the `claude` binary removed from
`PATH` (`claude before filtering: C:\nvm4w\nodejs\claude.CMD` →
`claude after filtering: None`, `returncode=0`) and with a sentinel
`ANTHROPIC_API_KEY` set that nothing reads.

### Plan verification items

1. `uv run python -m unittest tests.test_datasets_authoring -v` — 50 tests, OK, 0.17 s.
2. `uv run python -m unittest tests.test_arena_boundary -v` — 10 tests, OK.
3. `grep -rn "shell=True\|os.system\|os.environ\|getenv" arena/datasets/` — no matches.
4. `grep -rn "starter" arena/datasets/authoring.py` — one docstring sentence, no import. See "Plan gate that is factually stale" below for the reverse direction.
5. `uv run python -m unittest` — 594 tests, OK, 5.1 s (budget 45 s).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `prompt_revision` specified as `sha256_file` is not reproducible across checkouts**

- **Found during:** Task 2
- **Issue:** The plan specifies `prompt_revision(name) -> sha256_file(PROMPTS_DIRECTORY / name)`, hashing raw working-tree bytes. This repository has `core.autocrlf=true` and ships no `.gitattributes`. Measured on this worktree: the file I authored was LF on disk; after a `git checkout --` it came back with 125 CRLF of 125 newlines, and the raw digest changed (`1f1e14bf…` → `174fb3e1…`) for text nobody edited. Since `prompt_revision` is the `prompt_revision` recorded per corpus in `data/datasets.json` (D-43), the plan's implementation would report a revision change on a checkout, which inverts the mechanism's purpose: it exists to make a real edit visible, and line-ending noise would bury real edits among false positives.
- **Fix:** `prompt_revision` hashes the file content with `\r\n` normalized to `\n`. The digest still changes on any real edit, asserted in both directions (`test_the_revision_survives_a_line_ending_change` and `test_an_edit_still_changes_the_revision`), and the mutation sweep confirms reverting to raw-byte hashing turns the suite red.
- **Rejected alternative:** adding a `.gitattributes` forcing LF. That would alter the checked-out bytes of `evaluator/local_evaluator.py` and break `EvaluatorIntegrityTest`'s pinned SHA-256 — a repository-wide change with a hard-invariant blast radius, to fix a problem contained in one function.
- **Files modified:** `arena/datasets/authoring.py`
- **Commit:** `56df5fe`

**2. [Rule 2 - Missing critical functionality] Maintainer notes would have been sent to the authoring model**

- **Found during:** Task 1
- **Issue:** The plan instructs that the "an author that knows what the measurement is for is the self-preference hazard" rationale be commented in the prompt file itself. The driver sends the whole file, so that note would reach the model — and a note saying *a purpose is being deliberately withheld from you* is itself an invitation to guess at it, which is the D-57 contamination in miniature.
- **Fix:** Added `load_prompt(name)`, which strips HTML comment blocks and normalizes newlines before returning the prompt body. The rationale stays committed beside the text it governs, where a future editor reads it, and never reaches the model. `prompt_revision` still hashes the whole file, so editing the note is correctly a revision change.
- **Files modified:** `arena/datasets/authoring.py`, all three prompt files
- **Commit:** `f3ad569`, `56df5fe`

**3. [Rule 3 - Blocking] Three symbols the plan's Task 3 requires but its Task 2 artifact list omits**

- **Found during:** Task 2
- **Issue:** Task 3 specifies `ModelIdUniquenessTest` asserting that "the corpus-close check that consumes it must be shown to reject the 2-tuple case", but Task 2's symbol list has only `resolved_model_ids`, which returns a tuple and rejects nothing. Separately, the plan's response-log record carries `kind`, `model_alias`, `prompt_name` and `item_ids`, none of which are fields of `AuthoringResponse` as specified, so no function existed that could build the record.
- **Fix:** Added `assert_single_resolved_model(records)` (the corpus-close check), `log_record(request, response)` (builds the committed line from the request/response pair), and `response_log_path(corpus_name)` (mirrors `divergence.divergence_log_path`, and gives the otherwise-unused `RESPONSE_LOG_ROOT` a consumer instead of leaving it as dead configuration).
- **Files modified:** `arena/datasets/authoring.py`
- **Commit:** `56df5fe`

**4. [Rule 2 - Missing critical functionality] Three unvalidated boundaries on untrusted model output**

- **Found during:** Task 2
- **Issue:** The threat register assigns `mitigate` to T-02-01 and T-02-11 at the "untrusted model output crosses here" boundary, but the plan's parse specification (`json.loads` twice, extract whitelisted fields) validates nothing about the decoded items. Three gaps: (a) a returned item `id` that was never requested would be carried into the corpus, filing one item's phrase under another item's identity; (b) `next(iter(payload["modelUsage"]))` silently discards a second resolved id, which is precisely the T-02-28 confound it exists to catch, and raises `StopIteration` on an empty mapping; (c) `build_argv` accepts a filesystem path as `schema_json`, deferring the measured Windows-drive-letter failure to a spawned call.
- **Fix:** `_parse_items` refuses an unrequested or repeated id (a subset is still fine, since a short batch is exactly what `attempt_until` re-authors); `claude_runner` refuses a `modelUsage` whose length is not 1; `build_argv` validates `schema_json` parses as JSON. Each has a test.
- **Files modified:** `arena/datasets/authoring.py`
- **Commit:** `56df5fe`

### Plan gate that is factually stale (no action taken)

Plan verification item 4 asks that `grep -rn "arena" starter/` return nothing. It
returns one line: `starter/shopping_agent/constraint_extractor.py:80`, a comment
added by plan 02-05 recording that `arena/datasets/divergence.py` consumes the
now-public `STOPWORDS` (D-54). It is a comment, not an import, so the layering
invariant the gate protects is intact — and `RuntimePurityTest` asserts that
invariant properly, as an import-graph property rather than a text match. Left
alone deliberately: the file belongs to no plan in this wave, and rewording a
correct comment to satisfy a text gate would be the wrong direction of fix.

## Known Stubs

None. Every symbol this plan created is implemented and exercised.

## Threat Flags

None. The three trust boundaries this module introduces (`claude -p` stdout,
driver argv/stdin, the operator's OAuth session) are all in the plan's own
register, and no new network endpoint, auth path, or schema surface was added.

## Notes for Downstream Plans

- **02-08 (registry) and 02-10 (generator)** consume `load_prompt(name)` for the
  prompt body and `prompt_revision(name)` for the D-43 record. Use `load_prompt`,
  not a raw `read_text`: the raw file carries maintainer notes that must not be
  sent.
- The generator is responsible for making each re-authoring attempt produce a
  *different* request digest (the `attempt_index` argument to `produce` exists
  for this). Two attempts with an identical prompt and item batch would collide
  on one digest, and `replay_runner` refuses a log with a duplicated digest.
- `assert_single_resolved_model` is the corpus-close check; call it before
  freezing a corpus, not after.
- Response logs belong at `response_log_path(corpus_name)` →
  `data/responses/responses.<corpus>.jsonl`. `data/` is committable — `.gitignore`
  excludes only `catalog.jsonl`, `*.artifacts/` and `releases/`.

## Self-Check: PASSED

All five created files and one modified file exist on disk; all three commit
hashes (`f3ad569`, `56df5fe`, `0985979`) are present in this worktree's history;
the working tree is clean after every mutation revert; and the full suite is
green both normally and with `claude` absent from `PATH`.
