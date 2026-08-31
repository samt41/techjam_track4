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


def write_response_log(path: Path, records: tuple[dict[str, object], ...]) -> None:
    # Canonical form is not cosmetic: the log is committed, so a re-derivation
    # that reordered keys would show as a diff indistinguishable from a changed
    # measurement. Record order is the call order and is preserved.
    for number, record in enumerate(records, 1):
        missing = sorted(set(_RESPONSE_LOG_FIELDS) - set(record))
        extra = sorted(set(record) - set(_RESPONSE_LOG_FIELDS))
        if missing or extra:
            raise AuthoringError(
                f"response log record {number} has missing={missing} extra={extra}"
            )
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


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


def replay_runner(path: Path) -> AuthoringRunner:
    """A runner backed by the frozen log. A production path, not only a test path.

    Replay is what makes corpus regeneration offline and byte-reproducible, which
    is the whole of the determinism claim on this surface (D-50). It is keyed on
    the request digest, so a prompt edit, a model change, or a different item
    batch all miss the log loudly instead of silently replaying the wrong call.
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

    def runner(request: AuthoringRequest) -> AuthoringResponse:
        digest = request_digest(request)
        if digest not in index:
            raise AuthoringError(
                f"request digest {digest} is absent from the response log at {path}; "
                f"the prompt, model alias, or item batch has changed since it was frozen"
            )
        return index[digest]

    return runner


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
