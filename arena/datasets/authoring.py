"""The build-time LLM authoring driver: prompt pack, `claude -p` runner, replay log.

Nothing here is on the agent's inference path. The shipped agent is standard
library only, offline, and byte-deterministic; this module drives an external
interactive tool and is reachable only from corpus generation. `starter/` must
never import it, and the test suite must never spawn the tool -- the runner is a
`Protocol` so tests inject the replay path instead.

The reproducibility unit is not the call, it is the frozen artifact plus its
provenance. LLM authoring is not byte-reproducible, so the committed evidence is
the prompt pack, the response log, and the corpus. Re-running generation in
replay mode over the log reproduces the corpus byte for byte, which is the only
form of determinism available on this surface (D-50).

One cost of that choice is stated plainly rather than hidden: the log commits the
request digest and the PARSED result, not the raw response envelope. That keeps
the log at roughly 2-4 MiB instead of 10-40 MiB (L-16, where the repo-weight risk
is the log and not the 3.2 MiB of corpora), and it means a reviewer can re-derive
the corpus from committed bytes but cannot re-audit the parse step itself. The
parse is therefore kept small, total, and tested rather than trusted.

There is a SECOND way to answer a request, and its provenance is weaker in one
specific, documented respect. `claude_runner` spawns the tool and reads a metered
envelope back. The DETACHED path -- `collecting_runner` plus
`external_response_record` -- emits the unanswered requests to a queue file, an
operator has them answered outside this process, and the answers are appended to
the same log. Everything downstream is identical: the same digest key, the same
gates, the same `replay_runner`. What is NOT identical is the metering. No
subprocess ran here, so no `total_cost_usd`, no `duration_ms` and no `usage`
counters exist to record. Those fields are written as `0.0` / `0` because that is
the true amount this repository observed, never as a plausible-looking estimate:
a fabricated cost would make the corpus's recorded spend a fiction, and a
fabricated latency would corrupt the throughput measurement the next corpus is
planned against. `session_id` carries `DETACHED_SESSION_ID` so a reader of a
committed log can tell a subagent-authored record from a metered one at a glance
rather than having to infer it from a suspicious run of zeros. `docs/STATUS.md`
records the same caveat for a reader who never opens this module.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol


# Anchored on this file's location, never the process working directory, so the
# prompt pack resolves identically however the driver is invoked (gist.py:42-45).
PROMPTS_DIRECTORY = Path(__file__).resolve().parent / "assets" / "prompts"

# Committed, not generated-and-discarded (L-13): anything written under
# experiments/ outside baselines/ is silently gitignored and would vanish, while
# .gitignore excludes only catalog.jsonl, *.artifacts/ and releases/ from data/.
RESPONSE_LOG_ROOT = Path("data/responses")

RESPONSE_LOG_SCHEMA_VERSION = 1

PENDING_REQUEST_SCHEMA_VERSION = 1

# The `session_id` a detached record carries. A sentinel rather than an empty
# string for the same reason `_claude_cli_version` records "unavailable": an empty
# provenance field is indistinguishable from one nobody filled in, whereas this
# value says which path produced the record and is greppable across a committed
# log.
DETACHED_SESSION_ID = "detached-external-authoring"

# What a detached response records for the three metered fields. Zero is the
# measured truth on this path -- no process ran, so nothing was billed, timed, or
# counted -- and inventing a plausible number would turn the corpus's recorded
# spend and latency into fiction. See the module docstring and docs/STATUS.md.
DETACHED_COST_USD = 0.0
DETACHED_DURATION_MS = 0

# The `model_resolved` on the placeholder returned for an unanswered request. It
# is deliberately not a real id and deliberately not an alias, because
# `AuthoringResponse.validate()` refuses an alias and a real id here would be a
# lie. It cannot reach a committed log: a run that recorded even one pending
# request leaves those items unaccepted, and `attempt_until` refuses to return.
PENDING_MODEL_RESOLVED = "pending-external-authoring"

# Re-authoring cap per constraint, then fail loudly. An unbounded retry loop is
# the denial-of-service path (T-02-06), and a silent give-up is worse than a
# crash: dropping an item would leave the corpus smaller than its recorded
# session count with nothing in the log to say why.
AUTHORING_ATTEMPT_CAP = 3

# Every call carries it (T-02-06). The measured 10-item Sonnet call took 49.3 s,
# so 300 s is roughly 6x headroom -- generous enough that a legitimate slow call
# is never killed, bounded enough that a hung process cannot stall a batch.
CALL_TIMEOUT_SECONDS = 300

# D-35 forbids shared context between authoring and faithfulness review. A
# resumed session is exactly that, so these four flags may never appear in argv.
_FORBIDDEN_FLAGS: tuple[str, ...] = ("-c", "--continue", "-r", "--resume")

# The provenance whitelist, sorted (V7). Recording is opt-in by name: a field the
# response envelope grows later is ignored until someone adds it here
# deliberately. Never an environment dump, never the raw settings blob, never a
# credential. `usage` and the resolved model id are recorded separately below
# because each needs its own extraction, not because either is exempt.
_PROVENANCE_FIELDS: tuple[str, ...] = ("duration_ms", "session_id", "total_cost_usd")

# The four integer counters the envelope reports. A whitelist rather than a copy
# of whatever `usage` happens to contain, for the same reason as above.
_USAGE_COUNTERS: tuple[str, ...] = (
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "input_tokens",
    "output_tokens",
)

_KINDS: tuple[str, ...] = ("author", "review")

# The two aliases D-38/D-49 spend. Deliberately the ALIAS set: the resolved id is
# never an input, it is only ever read back off the response (Pitfall 7).
_MODEL_ALIASES: tuple[str, ...] = ("haiku", "sonnet")

_PENDING_REQUEST_FIELDS: tuple[str, ...] = (
    "item_ids",
    "kind",
    "model_alias",
    "prompt",
    "prompt_name",
    "prompt_revision",
    "request_digest",
    "schema_json",
    "schema_version",
)

_RESPONSE_LOG_FIELDS: tuple[str, ...] = (
    "cost_usd",
    "duration_ms",
    "items",
    "item_ids",
    "kind",
    "model_alias",
    "model_resolved",
    "prompt_name",
    "prompt_revision",
    "request_digest",
    "schema_version",
    "session_id",
    "usage",
)

# Maintainer notes live in the committed prompt files so a future editor reads the
# rationale beside the text it governs, and are stripped before the prompt is sent
# so the model never does. The note in each file explains that the framing is
# deliberately narrow; telling the author that something is being withheld would
# invite it to guess, which is the contamination D-57 exists to prevent.
_MAINTAINER_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class AuthoringError(RuntimeError):
    """Raised when an authoring call, its parse, or its replay cannot be trusted."""


class PendingRequestsError(AuthoringError):
    """Raised when a collecting run has gathered every request this wave can offer.

    Not a failure: it is the wave boundary. `collecting_runner` keeps going for as
    long as the requests it cannot answer are independent of one another, and
    raises here the moment it meets one whose existence depends on an answer it
    has just queued. The caller turns this into the pending-requests exit status.
    """


@dataclass(frozen=True, slots=True)
class AuthoringRequest:
    kind: str
    model_alias: str
    prompt_name: str
    prompt: str
    schema_json: str
    item_ids: tuple[str, ...]

    def validate(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, got {self.kind!r}")
        if self.model_alias not in _MODEL_ALIASES:
            raise ValueError(
                f"model alias must be one of {_MODEL_ALIASES}, got {self.model_alias!r}"
            )
        if not self.prompt_name:
            raise ValueError("authoring request requires a prompt name")
        if not self.prompt.strip():
            raise ValueError("authoring request requires a non-empty prompt")
        if not self.item_ids:
            # An empty batch would spend a call and a cache prefix to author
            # nothing, and would log a record no corpus row could ever claim.
            raise ValueError("authoring request requires at least one item id")
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError(f"authoring request item ids must be unique: {self.item_ids}")


@dataclass(frozen=True, slots=True)
class ReviewPayload:
    gist_attribute: str
    gist_value: str
    phrase: str

    def validate(self) -> None:
        if not self.gist_attribute or not self.gist_value:
            raise ValueError("review payload requires an attribute and a value")
        if not self.phrase:
            raise ValueError("review payload requires a phrase")

    def as_record(self) -> dict[str, str]:
        # EXACTLY these three keys, in sorted order (D-35). The reviewer's whole
        # input is this record, so there is no catalog text on the surface to
        # leak and no tool surface to hijack. Widening it is the one change that
        # would quietly undo the isolation, which is why the shape is asserted
        # rather than merely intended.
        return {
            "gist_attribute": self.gist_attribute,
            "gist_value": self.gist_value,
            "phrase": self.phrase,
        }


@dataclass(frozen=True, slots=True)
class AuthoringResponse:
    # Ordered pairs, never dicts: this structure is serialized and compared byte
    # for byte, and a dict would make the comparison depend on insertion order.
    items: tuple[tuple[tuple[str, object], ...], ...]
    model_resolved: str
    session_id: str
    usage: tuple[tuple[str, int], ...]
    cost_usd: float
    duration_ms: int
    request_digest: str
    prompt_revision: str

    def validate(self) -> None:
        if not self.model_resolved:
            raise ValueError("authoring response requires a resolved model id")
        if self.model_resolved in _MODEL_ALIASES:
            # The alias is a floating pointer; recording it in place of the
            # resolved id is what makes a mid-corpus generator change invisible
            # and confounds the affinity finding (T-02-28, Pitfall 7).
            raise ValueError(
                f"model_resolved must be a resolved id, not the alias "
                f"{self.model_resolved!r}"
            )
        if not self.request_digest or not self.prompt_revision:
            raise ValueError("authoring response requires its digest and prompt revision")
        if self.cost_usd < 0.0 or self.duration_ms < 0:
            raise ValueError("authoring response cost and duration must not be negative")
        counters = tuple(name for name, _ in self.usage)
        if counters != _USAGE_COUNTERS:
            raise ValueError(
                f"usage counters must be exactly {_USAGE_COUNTERS}, got {counters}"
            )

    def item_records(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(pairs) for pairs in self.items)


class AuthoringRunner(Protocol):
    def __call__(self, request: AuthoringRequest) -> AuthoringResponse: ...


def prompt_revision(name: str) -> str:
    """The committed prompt's content digest, recorded per corpus (D-43).

    Hashes the file with newlines normalized rather than its raw working-tree
    bytes. This repository is developed with core.autocrlf enabled and ships no
    .gitattributes, so an identical committed file is CRLF in one checkout and LF
    in another. A raw byte digest would then report a different revision for text
    nobody edited, which is precisely backwards: the revision exists to make a
    real edit visible, and line-ending noise would bury a real edit in false
    positives while telling a reader the prompt changed when it did not.
    """
    try:
        raw = (PROMPTS_DIRECTORY / name).read_bytes()
    except OSError as error:
        raise AuthoringError(f"cannot read prompt {name}: {error}") from error
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def load_prompt(name: str) -> str:
    """The prompt text as sent: maintainer notes stripped, newlines normalized."""
    try:
        text = (PROMPTS_DIRECTORY / name).read_text(encoding="utf-8")
    except OSError as error:
        raise AuthoringError(f"cannot read prompt {name}: {error}") from error
    body = _MAINTAINER_COMMENT_RE.sub("", text.replace("\r\n", "\n")).strip()
    if not body:
        raise AuthoringError(f"prompt {name} is empty once maintainer notes are stripped")
    return body + "\n"


def request_digest(request: AuthoringRequest) -> str:
    """The replay key: a content digest over everything that shapes the call.

    Canonical JSON with pinned separators, mirroring CandidateSpec.fingerprint's
    discipline at candidate.py:86-107, and never the builtin hash(), which is
    salted per process and so cannot identify a request across two runs.
    """
    payload = json.dumps(
        {
            "item_ids": list(request.item_ids),
            "kind": request.kind,
            "model_alias": request.model_alias,
            "prompt": request.prompt,
            "prompt_name": request.prompt_name,
            "schema_json": request.schema_json,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_argv(*, model_alias: str, schema_json: str) -> tuple[str, ...]:
    """The exact argv the driver spawns. Split out so hygiene is testable.

    Every element here is a measured fact, and several are absences:

    * `--json-schema` takes INLINE JSON, not a path. A path was rejected with
      `not valid JSON: JSON Parse error: Unexpected identifier "C"` -- the
      Windows drive letter parsed as an identifier. The value is validated below
      so a path fails here, locally and free, instead of after a spawned call.
    * `--max-turns` is absent on purpose. `--max-turns 1` makes structured output
      fail with `error_max_turns` and `result: null` AFTER burning the output
      tokens; structured output needs two turns (L-14).
    * `--bare` is absent on purpose. It would be stronger isolation, but its own
      help text says Anthropic auth is strictly the API key or apiKeyHelper and
      that OAuth and keychain are never read -- so it cannot work with the
      operator's login, which is the only credential this repository has.
    * The prompt is NOT in argv. It is delivered on stdin, because a positional
      prompt argument errored, and because an argument is the interpolation
      surface a prompt must never touch (T-02-01).
    * `--setting-sources ""` plus the clean working directory in `claude_runner`
      is the D-57 requirement. This project's brief is auto-discovered otherwise,
      which costs ~31k prefix tokens and, far worse, tells the authoring model
      what the measurement is for.
    """
    if model_alias not in _MODEL_ALIASES:
        raise AuthoringError(
            f"model alias must be one of {_MODEL_ALIASES}, got {model_alias!r}"
        )
    try:
        json.loads(schema_json)
    except ValueError as error:
        raise AuthoringError(
            f"schema must be inline JSON, not a path or a fragment: {error}"
        ) from error
    return (
        "claude",
        "-p",
        "--model",
        model_alias,
        "--output-format",
        "json",
        "--json-schema",
        schema_json,
        "--setting-sources",
        "",
    )


def _require_mapping(payload: object, label: str) -> dict:
    if not isinstance(payload, dict):
        raise AuthoringError(f"{label} must be an object, got {type(payload).__name__}")
    return payload


def _parse_items(
    raw_result: object, item_ids: tuple[str, ...]
) -> tuple[tuple[tuple[str, object], ...], ...]:
    if not isinstance(raw_result, str):
        # `result` stays a JSON STRING even under --json-schema (L-14). Anything
        # else means the envelope shape changed and the parse below is guesswork.
        raise AuthoringError(
            f"result must be a JSON string, got {type(raw_result).__name__}"
        )
    parsed = json.loads(raw_result)
    if not isinstance(parsed, list):
        raise AuthoringError(
            f"result must decode to an array, got {type(parsed).__name__}"
        )
    items: list[tuple[tuple[str, object], ...]] = []
    seen: list[str] = []
    for entry in parsed:
        record = _require_mapping(entry, "result item")
        identifier = record.get("id")
        # Untrusted output crosses the boundary here. An id that was never
        # requested is refused rather than carried: it cannot be matched to a
        # target, and accepting it would let one item's phrase be filed under
        # another item's identity. A SUBSET is fine -- a short batch is exactly
        # what attempt_until re-authors.
        if not isinstance(identifier, str) or identifier not in item_ids:
            raise AuthoringError(
                f"result item carries an id that was not requested: {identifier!r}"
            )
        if identifier in seen:
            raise AuthoringError(f"result repeats item id {identifier!r}")
        seen.append(identifier)
        items.append(tuple(sorted(record.items(), key=lambda pair: pair[0])))
    return tuple(items)


def claude_runner(request: AuthoringRequest) -> AuthoringResponse:
    """The production runner. One process, one fresh session, one clean directory."""
    request.validate()
    argv = build_argv(model_alias=request.model_alias, schema_json=request.schema_json)
    try:
        # The working directory deliberately holds no project brief: the tool
        # auto-discovers one from the cwd, and loading this project's brief is an
        # anti-circularity breach and not merely a token cost (D-57, L-12). The
        # temporary directory is created fresh per call and removed after it.
        with tempfile.TemporaryDirectory() as clean_cwd:
            completed = subprocess.run(
                argv,
                input=request.prompt,
                capture_output=True,
                text=True,
                cwd=clean_cwd,
                timeout=CALL_TIMEOUT_SECONDS,
                check=False,
            )
        payload = _require_mapping(json.loads(completed.stdout), "response envelope")
        # Never branch on returncode alone: exit code 0 alongside `is_error: true`
        # was measured, so a returncode check would accept a failed call as a
        # successful one and log its empty result as provenance (L-14).
        if payload.get("is_error") or payload.get("subtype") != "success":
            raise AuthoringError(
                f"call failed: subtype={payload.get('subtype')!r} "
                f"is_error={payload.get('is_error')!r} "
                f"stderr={completed.stderr.strip()[:200]!r}"
            )
        model_usage = _require_mapping(payload["modelUsage"], "modelUsage")
        if len(model_usage) != 1:
            # One call, one generator. Two resolved ids inside a single call
            # means the id recorded against these items would describe only some
            # of them (T-02-28).
            raise AuthoringError(
                f"expected exactly one resolved model id, got {sorted(model_usage)}"
            )
        provenance = {field: payload[field] for field in _PROVENANCE_FIELDS}
        usage = _require_mapping(payload["usage"], "usage")
        response = AuthoringResponse(
            items=_parse_items(payload["result"], request.item_ids),
            model_resolved=next(iter(model_usage)),
            session_id=str(provenance["session_id"]),
            usage=tuple((name, int(usage[name])) for name in _USAGE_COUNTERS),
            cost_usd=float(provenance["total_cost_usd"]),
            duration_ms=int(provenance["duration_ms"]),
            request_digest=request_digest(request),
            prompt_revision=prompt_revision(request.prompt_name),
        )
        response.validate()
    except (
        OSError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise AuthoringError(f"authoring call failed: {error}") from error
    return response


def response_log_path(corpus_name: str, *, root: Path = RESPONSE_LOG_ROOT) -> Path:
    # Versioned with the corpus it describes, exactly as the divergence log is:
    # one shared filename would silently mix two corpora's calls, and replay
    # would then reproduce a corpus from another corpus's responses.
    return root / f"responses.{corpus_name}.jsonl"


def log_record(request: AuthoringRequest, response: AuthoringResponse) -> dict[str, object]:
    """The committed line: digests and parsed results, never the raw envelope."""
    return {
        "cost_usd": response.cost_usd,
        "duration_ms": response.duration_ms,
        "item_ids": list(request.item_ids),
        "items": list(response.item_records()),
        "kind": request.kind,
        "model_alias": request.model_alias,
        "model_resolved": response.model_resolved,
        "prompt_name": request.prompt_name,
        "prompt_revision": response.prompt_revision,
        "request_digest": response.request_digest,
        "schema_version": RESPONSE_LOG_SCHEMA_VERSION,
        "session_id": response.session_id,
        "usage": dict(response.usage),
    }


def _assert_log_fields(records: tuple[dict[str, object], ...]) -> None:
    # Extracted so `write_response_log` and `append_response_log` cannot drift
    # apart. The wording and the 1-based numbering are `write_response_log`'s own
    # and are preserved verbatim: a detached path that widened the whitelist for
    # its own convenience is exactly the regression this check exists to stop.
    for number, record in enumerate(records, 1):
        missing = sorted(set(_RESPONSE_LOG_FIELDS) - set(record))
        extra = sorted(set(record) - set(_RESPONSE_LOG_FIELDS))
        if missing or extra:
            raise AuthoringError(
                f"response log record {number} has missing={missing} extra={extra}"
            )


def _serialize_log(records: tuple[dict[str, object], ...]) -> str:
    return "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)


def write_response_log(path: Path, records: tuple[dict[str, object], ...]) -> None:
    # Canonical form is not cosmetic: the log is committed, so a re-derivation
    # that reordered keys would show as a diff indistinguishable from a changed
    # measurement. Record order is the call order and is preserved.
    _assert_log_fields(records)
    path.write_text(_serialize_log(records), encoding="utf-8")


def load_response_log(path: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise AuthoringError(f"cannot read response log at {path}: {error}") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        # json.loads only -- never pickle, eval or yaml (T-02-11).
        try:
            record = json.loads(line)
        except ValueError as error:
            raise AuthoringError(
                f"invalid response record in {path} at line {number}: {error}"
            ) from error
        if not isinstance(record, dict):
            raise AuthoringError(
                f"invalid response record in {path} at line {number}: "
                f"expected an object, got {type(record).__name__}"
            )
        version = record.get("schema_version")
        if version != RESPONSE_LOG_SCHEMA_VERSION:
            raise AuthoringError(
                f"invalid response record in {path} at line {number}: "
                f"unsupported schema version {version!r}"
            )
        rows.append(record)
    return tuple(rows)


def _response_from_record(record: dict[str, object]) -> AuthoringResponse:
    items = record["items"]
    if not isinstance(items, list):
        raise AuthoringError(f"logged items must be an array, got {type(items).__name__}")
    usage = _require_mapping(record["usage"], "logged usage")
    response = AuthoringResponse(
        items=tuple(
            tuple(sorted(_require_mapping(item, "logged item").items(), key=lambda p: p[0]))
            for item in items
        ),
        model_resolved=str(record["model_resolved"]),
        session_id=str(record["session_id"]),
        usage=tuple((name, int(usage[name])) for name in _USAGE_COUNTERS),
        cost_usd=float(record["cost_usd"]),
        duration_ms=int(record["duration_ms"]),
        request_digest=str(record["request_digest"]),
        prompt_revision=str(record["prompt_revision"]),
    )
    response.validate()
    return response


def _response_index(path: Path) -> dict[str, AuthoringResponse]:
    """Load a log into its digest-keyed replay index, refusing ambiguity.

    Shared by `replay_runner` and `collecting_runner` so the two cannot diverge on
    what they consider a usable log. Both the duplicate refusal and the wrapping
    of a malformed record are the replay runner's own, moved rather than rewritten.
    """
    index: dict[str, AuthoringResponse] = {}
    try:
        for record in load_response_log(path):
            digest = str(record["request_digest"])
            if digest in index:
                # Two records under one key make replay ambiguous, and picking
                # either would be a coin flip dressed up as reproduction.
                raise AuthoringError(
                    f"response log at {path} repeats request digest {digest}"
                )
            index[digest] = _response_from_record(record)
    except (KeyError, TypeError, ValueError) as error:
        raise AuthoringError(f"malformed response log at {path}: {error}") from error
    return index


def replay_runner(path: Path) -> AuthoringRunner:
    """A runner backed by the frozen log. A production path, not only a test path.

    Replay is what makes corpus regeneration offline and byte-reproducible, which
    is the whole of the determinism claim on this surface (D-50). It is keyed on
    the request digest, so a prompt edit, a model change, or a different item
    batch all miss the log loudly instead of silently replaying the wrong call.
    """
    index = _response_index(path)

    def runner(request: AuthoringRequest) -> AuthoringResponse:
        digest = request_digest(request)
        if digest not in index:
            raise AuthoringError(
                f"request digest {digest} is absent from the response log at {path}; "
                f"the prompt, model alias, or item batch has changed since it was frozen"
            )
        return index[digest]

    return runner


@dataclass(frozen=True, slots=True)
class PendingRequest:
    """One request the log cannot answer, carrying everything needed to answer it.

    Self-sufficiency is the whole contract. Whoever answers this record does so
    with no access to this repository, so the record must hold the prompt itself
    rather than a pointer to it -- and it holds the prompt EXACTLY as
    `claude_runner` would have written it to stdin, that is, after `load_prompt`
    has stripped the maintainer notes and normalized the newlines. Handing over
    the prompt NAME and letting the answerer re-read the file is the failure mode
    worth naming: the maintainer note tells the author what the measurement is for
    (D-57), and a single re-derived byte of whitespace mints a different
    `request_digest`, so the answer would be filed under a key the generator never
    looks up and replay would miss it with nothing to say why.
    """

    schema_version: int
    request_digest: str
    kind: str
    model_alias: str
    prompt_name: str
    prompt_revision: str
    schema_json: str
    item_ids: tuple[str, ...]
    prompt: str

    def validate(self) -> None:
        if self.schema_version != PENDING_REQUEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported pending request schema version {self.schema_version}"
            )
        if not self.request_digest or not self.prompt_revision:
            raise ValueError("pending request requires its digest and prompt revision")
        if self.kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, got {self.kind!r}")
        if self.model_alias not in _MODEL_ALIASES:
            raise ValueError(
                f"model alias must be one of {_MODEL_ALIASES}, got {self.model_alias!r}"
            )
        if not self.prompt.strip():
            raise ValueError("pending request requires a non-empty prompt")
        if not self.item_ids:
            raise ValueError("pending request requires at least one item id")

    def as_record(self) -> dict[str, object]:
        return {
            "item_ids": list(self.item_ids),
            "kind": self.kind,
            "model_alias": self.model_alias,
            "prompt": self.prompt,
            "prompt_name": self.prompt_name,
            "prompt_revision": self.prompt_revision,
            "request_digest": self.request_digest,
            "schema_json": self.schema_json,
            "schema_version": self.schema_version,
        }


def pending_request(request: AuthoringRequest) -> PendingRequest:
    """Describe an unanswered `AuthoringRequest` for whoever will answer it."""

    record = PendingRequest(
        schema_version=PENDING_REQUEST_SCHEMA_VERSION,
        # Computed from the request in hand, exactly as `claude_runner` computes
        # it, so the queue and the generator agree on the key by construction.
        request_digest=request_digest(request),
        kind=request.kind,
        model_alias=request.model_alias,
        prompt_name=request.prompt_name,
        prompt_revision=prompt_revision(request.prompt_name),
        schema_json=request.schema_json,
        item_ids=tuple(request.item_ids),
        prompt=request.prompt,
    )
    record.validate()
    return record


def write_pending_requests(path: Path, records: tuple[PendingRequest, ...]) -> None:
    """Rewrite the pending queue. One canonical JSON object per line."""

    # Rewritten whole rather than appended to, because the queue describes ONE
    # wave: a stale record left over from a previous round would ask for a request
    # the generator has already had answered, and the answer would be dead weight
    # in the log that `append_response_log` then has to refuse as a duplicate.
    for record in records:
        record.validate()
    path.write_text(
        "".join(
            json.dumps(record.as_record(), sort_keys=True) + "\n" for record in records
        ),
        encoding="utf-8",
    )


def load_pending_requests(path: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise AuthoringError(f"cannot read pending requests at {path}: {error}") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        # json.loads only -- never pickle, eval or yaml (T-02-11).
        try:
            record = json.loads(line)
        except ValueError as error:
            raise AuthoringError(
                f"invalid pending request in {path} at line {number}: {error}"
            ) from error
        if not isinstance(record, dict):
            raise AuthoringError(
                f"invalid pending request in {path} at line {number}: "
                f"expected an object, got {type(record).__name__}"
            )
        rows.append(record)
    return tuple(rows)


def _pending_placeholder(request: AuthoringRequest) -> AuthoringResponse:
    # An empty item list is a legitimate shape in this system -- it is what a model
    # that returned `[]` produces -- so nothing downstream needs a special case for
    # it. The items simply go unaccepted, which is precisely the state a queued
    # request should leave the run in.
    response = AuthoringResponse(
        items=(),
        model_resolved=PENDING_MODEL_RESOLVED,
        session_id=DETACHED_SESSION_ID,
        usage=tuple((name, 0) for name in _USAGE_COUNTERS),
        cost_usd=DETACHED_COST_USD,
        duration_ms=DETACHED_DURATION_MS,
        request_digest=request_digest(request),
        prompt_revision=prompt_revision(request.prompt_name),
    )
    response.validate()
    return response


class PendingRequestCollector:
    """A replay runner that QUEUES what the log cannot answer instead of guessing.

    Satisfies `AuthoringRunner`, and on a hit is `replay_runner` exactly: the same
    index, the same duplicate-digest refusal, the same logged response object.

    The interesting half is the miss, because authoring is adaptive. The first
    attempt's batches are enumerable up front, but a re-authoring attempt exists
    only because specific items failed their gates, and a review request's prompt
    contains phrases that do not exist until the author call has been answered. So
    the full request set is not knowable in advance and the queue has to converge
    over several rounds rather than being emitted once.

    The rule that decides how much one round may collect is dependency, expressed
    as item overlap. Two requests naming disjoint item sets cannot depend on each
    other: an author batch's prompt is built from its own items' gist payloads,
    and a review batch's from its own items' phrases. So every miss whose items
    are disjoint from all already-queued misses is genuinely needed and is queued.
    The first miss that touches an item already queued is a request whose very
    existence is conditional on an answer nobody has given yet -- re-authoring an
    item because no phrase came back is an artefact of the empty queue, not a real
    gate failure -- so it is refused, NOT queued, and the run stops. Queueing it
    would spend an author's effort on a prompt the converged run may never issue.

    That makes one run collect exactly one dependency-free wave, which is the most
    the loop structure permits: `arena/datasets/generate.py` fans an entire arm's
    author stage out before it consumes any of it, so a wave is every batch of one
    stage rather than a single batch. The probe corpus therefore converges in one
    round per stage -- author and review for each of the two arms -- rather than
    in one round per batch.
    """

    def __init__(self, *, replay_path: Path | None, pending_path: Path) -> None:
        # A missing log is the FIRST round, not an error: nothing has been answered
        # yet. A malformed or ambiguous one still raises, through the shared index.
        self._index: dict[str, AuthoringResponse] = (
            _response_index(replay_path)
            if replay_path is not None and Path(replay_path).is_file()
            else {}
        )
        self._pending_path = Path(pending_path)
        self._pending: list[PendingRequest] = []
        self._queued_digests: set[str] = set()
        self._queued_items: set[str] = set()
        self._pending_path.parent.mkdir(parents=True, exist_ok=True)
        # Written empty up front so the file always describes this run rather than
        # the last one, and so "converged" reads as an empty queue rather than as
        # an absent file a reader has to interpret.
        self._flush()

    @property
    def pending(self) -> tuple[PendingRequest, ...]:
        return tuple(self._pending)

    @property
    def pending_path(self) -> Path:
        return self._pending_path

    def _flush(self) -> None:
        write_pending_requests(self._pending_path, tuple(self._pending))

    def __call__(self, request: AuthoringRequest) -> AuthoringResponse:
        digest = request_digest(request)
        logged = self._index.get(digest)
        if logged is not None:
            return logged
        if digest in self._queued_digests:
            # An identical request repeated inside one run carries no new
            # information, so it is neither queued twice nor treated as a
            # dependency on itself. Checked BEFORE the overlap rule below, which
            # would otherwise swallow this case and leave the de-duplication a
            # branch nothing could reach.
            return _pending_placeholder(request)
        overlapping = sorted(self._queued_items.intersection(request.item_ids))
        if overlapping:
            raise PendingRequestsError(
                f"{len(self._pending)} request(s) queued at {self._pending_path};"
                f" stopping before a request that depends on an unanswered one"
                f" through item(s) {overlapping}"
            )
        record = pending_request(request)
        self._pending.append(record)
        self._queued_digests.add(digest)
        self._queued_items.update(request.item_ids)
        self._flush()
        return _pending_placeholder(request)


def collecting_runner(
    *, replay_path: Path | None, pending_path: Path
) -> PendingRequestCollector:
    """Replay what the log holds, queue what it does not. See the class docstring."""

    return PendingRequestCollector(replay_path=replay_path, pending_path=pending_path)


def _assert_items_match_schema(
    items: tuple[dict[str, object], ...], schema_json: str
) -> None:
    """Check answered items against the schema the request would have enforced.

    `claude -p --json-schema` enforces this shape inside the tool. On the detached
    path nothing does, so an answer shaped `{"id": ..., "text": ...}` would parse
    as JSON, carry a requested id, and then silently produce no phrase -- costing a
    whole round trip to rediscover. The check is deliberately narrow: key sets and
    the two value forms this repository's two schemas actually use.
    """
    try:
        schema = json.loads(schema_json)
        item_schema = schema["items"]
        properties = item_schema["properties"]
        required = sorted(item_schema["required"])
    except (KeyError, TypeError, ValueError) as error:
        raise AuthoringError(
            f"pending request carries an unreadable item schema: {error}"
        ) from error
    for position, item in enumerate(items, 1):
        keys = sorted(item)
        if keys != required:
            raise AuthoringError(
                f"answered item {position} has keys {keys}, expected {required}"
            )
        for name in required:
            expected = properties[name]
            value = item[name]
            if "enum" in expected and value not in expected["enum"]:
                raise AuthoringError(
                    f"answered item {position} field {name!r} is {value!r},"
                    f" expected one of {sorted(expected['enum'])}"
                )
            if expected.get("type") == "string" and not isinstance(value, str):
                raise AuthoringError(
                    f"answered item {position} field {name!r} must be a string,"
                    f" got {type(value).__name__}"
                )


def external_response_record(
    pending: dict[str, object],
    items: tuple[dict[str, object], ...],
    *,
    model_resolved: str,
) -> dict[str, object]:
    """Turn an externally-produced answer into a response-log record.

    The digest is the pending record's own, VERBATIM. The request is rebuilt from
    the queue only to check that it agrees -- a disagreement means the queue file
    was edited in transit, and the answer would then be filed under a key the
    generator never looks up. Recomputing the digest from the rebuilt request
    instead of checking against the recorded one is the quiet version of that same
    bug: it would always "agree", and replay would miss with nothing to say why.
    """
    missing = sorted(set(_PENDING_REQUEST_FIELDS) - set(pending))
    extra = sorted(set(pending) - set(_PENDING_REQUEST_FIELDS))
    if missing or extra:
        raise AuthoringError(
            f"pending request has missing={missing} extra={extra}"
        )
    if pending["schema_version"] != PENDING_REQUEST_SCHEMA_VERSION:
        raise AuthoringError(
            f"unsupported pending request schema version"
            f" {pending['schema_version']!r}"
        )
    recorded_digest = str(pending["request_digest"])
    try:
        item_ids = tuple(str(value) for value in pending["item_ids"])  # type: ignore[union-attr]
        request = AuthoringRequest(
            kind=str(pending["kind"]),
            model_alias=str(pending["model_alias"]),
            prompt_name=str(pending["prompt_name"]),
            prompt=str(pending["prompt"]),
            schema_json=str(pending["schema_json"]),
            item_ids=item_ids,
        )
        request.validate()
    except (TypeError, ValueError) as error:
        raise AuthoringError(f"pending request is malformed: {error}") from error
    if request_digest(request) != recorded_digest:
        raise AuthoringError(
            f"pending request {recorded_digest} does not hash to its own contents;"
            " the queue file was edited after it was written, so an answer to it"
            " would be filed under a key the generator never looks up"
        )
    _assert_items_match_schema(items, request.schema_json)
    response = AuthoringResponse(
        # The same untrusted-boundary parse `claude_runner` uses, so an id nobody
        # requested is refused here too rather than filing one item's phrase under
        # another item's identity.
        items=_parse_items(json.dumps(list(items)), item_ids),
        model_resolved=model_resolved,
        session_id=DETACHED_SESSION_ID,
        usage=tuple((name, 0) for name in _USAGE_COUNTERS),
        cost_usd=DETACHED_COST_USD,
        duration_ms=DETACHED_DURATION_MS,
        request_digest=recorded_digest,
        prompt_revision=str(pending["prompt_revision"]),
    )
    response.validate()
    record = log_record(request, response)
    _assert_log_fields((record,))
    return record


def append_response_log(path: Path, records: tuple[dict[str, object], ...]) -> None:
    """Append answered records to a response log, keeping it replayable.

    Refuses a digest the log already carries. `replay_runner` would refuse it too,
    but only at the next regeneration, long after the round trip that produced the
    duplicate is over and with nothing left to say which of the two answers was
    meant.
    """
    _assert_log_fields(records)
    existing = load_response_log(path) if path.is_file() else ()
    seen = {str(record["request_digest"]) for record in existing}
    for record in records:
        digest = str(record["request_digest"])
        if digest in seen:
            raise AuthoringError(
                f"response log at {path} already carries request digest {digest}"
            )
        seen.add(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    # No `newline` argument, deliberately: `write_response_log` goes through
    # `Path.write_text`, which applies the platform's newline translation, and an
    # append that pinned "\n" would leave one file carrying two line-ending
    # conventions on Windows.
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_serialize_log(records))


def resolved_model_ids(records: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    return tuple(sorted({str(record["model_resolved"]) for record in records}))


def assert_single_resolved_model(records: tuple[dict[str, object], ...]) -> str:
    """The corpus-close check (MEAS-13, Pitfall 7).

    A corpus whose log contains two distinct resolved ids has silently changed
    generator mid-run, and its generator-affinity finding is confounded: part of
    the arm was written by one model and part by another, while the corpus claims
    one. Refusing here is the only place that is detectable, because the alias
    that was requested looks identical in both halves.
    """
    identifiers = resolved_model_ids(records)
    if len(identifiers) != 1:
        raise AuthoringError(
            f"expected exactly one resolved model id across the corpus, "
            f"got {list(identifiers)}"
        )
    return identifiers[0]


def attempt_until(
    item_ids: tuple[str, ...],
    produce: Callable[[tuple[str, ...], int], Mapping[str, str]],
    accept: Callable[[str, str], tuple[bool, str]],
    *,
    cap: int = AUTHORING_ATTEMPT_CAP,
) -> tuple[tuple[str, str], ...]:
    """Re-author the rejected items, bounded, then fail loudly with the reasons.

    Failing loudly is the requirement, not a stylistic choice: silently dropping
    an item would leave the corpus smaller than its recorded session count, and
    the shortfall would surface much later as an unexplained row-count mismatch
    rather than here, where the rejection reasons are still in hand.
    """
    if cap < 1:
        raise ValueError(f"attempt cap must be at least 1, got {cap}")
    pending = tuple(item_ids)
    accepted: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for attempt_index in range(cap):
        if not pending:
            break
        produced = produce(pending, attempt_index)
        still: list[str] = []
        for item_id in pending:
            phrase = produced.get(item_id)
            if phrase is None:
                reasons[item_id] = "no phrase returned"
                still.append(item_id)
                continue
            ok, reason = accept(item_id, phrase)
            if ok:
                accepted[item_id] = phrase
                continue
            reasons[item_id] = reason
            still.append(item_id)
        pending = tuple(still)
    if pending:
        detail = ", ".join(
            f"{item_id} ({reasons.get(item_id, 'no reason recorded')})"
            for item_id in pending
        )
        raise AuthoringError(
            f"authoring failed after {cap} attempts for {len(pending)} item(s): {detail}"
        )
    return tuple((item_id, accepted[item_id]) for item_id in item_ids)
