from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena.datasets.authoring import (
    AUTHORING_ATTEMPT_CAP,
    CALL_TIMEOUT_SECONDS,
    PROMPTS_DIRECTORY,
    RESPONSE_LOG_SCHEMA_VERSION,
    AuthoringError,
    AuthoringRequest,
    ReviewPayload,
    assert_single_resolved_model,
    attempt_until,
    build_argv,
    claude_runner,
    load_prompt,
    load_response_log,
    log_record,
    prompt_revision,
    replay_runner,
    request_digest,
    resolved_model_ids,
    write_response_log,
)
from arena.datasets.divergence import ordered_tokens
from arena.evaluator_bridge import searchable_text
from tests.dataset_fixtures import fake_authoring_response, product


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

# The exact key set a committed response log line may carry. Written out as a
# literal rather than imported from the module under test: importing the module's
# own tuple would make this assertion circular, and a widened whitelist would
# then widen its own test alongside it.
EXPECTED_LOG_KEYS = {
    "cost_usd",
    "duration_ms",
    "item_ids",
    "items",
    "kind",
    "model_alias",
    "model_resolved",
    "prompt_name",
    "prompt_revision",
    "request_digest",
    "schema_version",
    "session_id",
    "usage",
}

# Substrings that would indicate a credential or an environment dump reached a
# committed record. Deliberately NOT the bare word "token": the four legitimate
# usage counters are named input_tokens, output_tokens, cache_creation_input_tokens
# and cache_read_input_tokens, so scanning for "token" would fail on the very
# fields the log is supposed to carry and would have to be relaxed away. The key
# set is pinned exactly above instead, which is the stronger of the two checks.
CREDENTIAL_MARKERS = (
    "anthropic",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "environ",
    "oauth",
    "secret",
)

# The five substrings no top-level record key may contain (V7).
FORBIDDEN_KEY_SUBSTRINGS = ("env", "settings", "token", "key", "secret")

SCHEMA_JSON = json.dumps(
    {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "phrase": {"type": "string"}},
            "required": ["id", "phrase"],
        },
    }
)


def authoring_request(
    *,
    kind: str = "author",
    model_alias: str = "haiku",
    prompt_name: str = "author_probe.md",
    prompt: str = "write one requirement per item",
    item_ids: tuple[str, ...] = ("probe_v1_0001", "probe_v1_0002"),
) -> AuthoringRequest:
    request = AuthoringRequest(
        kind=kind,
        model_alias=model_alias,
        prompt_name=prompt_name,
        prompt=prompt,
        schema_json=SCHEMA_JSON,
        item_ids=item_ids,
    )
    request.validate()
    return request


def authored_items(item_ids: tuple[str, ...]) -> tuple[dict, ...]:
    return tuple(
        {"id": item_id, "phrase": f"a leathery finish, option {index}"}
        for index, item_id in enumerate(item_ids)
    )


def completed(envelope: dict, *, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=("claude", "-p"),
        returncode=returncode,
        stdout=json.dumps(envelope),
        stderr=stderr,
    )


def setting_sources_is_empty(argv: tuple[str, ...]) -> bool:
    """Exactly one --setting-sources, and the element after it is exactly ''."""
    if argv.count("--setting-sources") != 1:
        return False
    return argv[argv.index("--setting-sources") + 1] == ""


class ArgvHygieneTest(unittest.TestCase):
    """D-57 and D-35, asserted by argv introspection rather than hoped for."""

    def setUp(self) -> None:
        self.argv = build_argv(model_alias="sonnet", schema_json=SCHEMA_JSON)

    def test_argv_is_a_tuple_leading_with_the_headless_invocation(self) -> None:
        self.assertIsInstance(self.argv, tuple)
        self.assertEqual(self.argv[:2], ("claude", "-p"))

    def test_setting_sources_is_present_and_empty(self) -> None:
        self.assertTrue(setting_sources_is_empty(self.argv))

    def test_the_setting_sources_check_can_actually_fail(self) -> None:
        # The two-sided half. Without this the assertion above would still pass
        # if the predicate were vacuous, and a driver that quietly dropped the
        # pair -- reloading this project's brief into the authoring context --
        # would ship green.
        index = self.argv.index("--setting-sources")
        removed = self.argv[:index] + self.argv[index + 2 :]
        self.assertFalse(setting_sources_is_empty(removed))

        non_empty = self.argv[:index] + ("--setting-sources", "user") + self.argv[index + 2 :]
        self.assertFalse(setting_sources_is_empty(non_empty))

        duplicated = self.argv + ("--setting-sources", "")
        self.assertFalse(setting_sources_is_empty(duplicated))

    def test_no_session_resuming_flag_appears(self) -> None:
        # D-35: a resumed session shares context between authoring and review,
        # which is the one thing the decision forbids outright.
        for flag in ("-c", "--continue", "-r", "--resume"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, self.argv)

    def test_max_turns_is_absent(self) -> None:
        # L-14: --max-turns 1 makes structured output fail with error_max_turns
        # after the output tokens are already spent.
        self.assertNotIn("--max-turns", self.argv)

    def test_bare_is_absent(self) -> None:
        # --bare would be stronger isolation but excludes the OAuth login that is
        # the only credential available here.
        self.assertNotIn("--bare", self.argv)

    def test_the_prompt_is_not_in_argv(self) -> None:
        # The prompt goes on stdin. An argument is the interpolation surface a
        # prompt must never touch (T-02-01).
        request = authoring_request(prompt="a distinctive prompt body")
        argv = build_argv(model_alias=request.model_alias, schema_json=request.schema_json)
        self.assertNotIn(request.prompt, argv)
        for element in argv:
            self.assertNotIn("a distinctive prompt body", element)

    def test_json_schema_value_is_inline_json(self) -> None:
        value = self.argv[self.argv.index("--json-schema") + 1]
        self.assertEqual(json.loads(value)["type"], "array")

    def test_a_schema_path_is_refused_locally(self) -> None:
        # The measured failure: a Windows path's drive letter parses as an
        # identifier and the CLI rejects it. Refusing here costs nothing; letting
        # it through costs a spawned call.
        with self.assertRaises(AuthoringError):
            build_argv(model_alias="sonnet", schema_json=r"C:\schemas\probe.json")

    def test_an_unknown_model_alias_is_refused(self) -> None:
        with self.assertRaises(AuthoringError):
            build_argv(model_alias="opus", schema_json=SCHEMA_JSON)


class CleanCwdTest(unittest.TestCase):
    """D-57: the call runs from a working directory holding no project brief."""

    def test_the_call_is_made_from_a_brief_free_directory_on_stdin(self) -> None:
        request = authoring_request()
        envelope = fake_authoring_response(authored_items(request.item_ids))
        observed: dict[str, object] = {}

        def side_effect(*args, **kwargs):
            observed["args"] = args
            observed["kwargs"] = kwargs
            # Asserted while the temporary directory is still alive, so this is a
            # statement about the directory the process actually ran in.
            cwd = kwargs["cwd"]
            self.assertIsNotNone(cwd)
            self.assertFalse((Path(cwd) / "CLAUDE.md").exists())
            self.assertNotEqual(Path(cwd).resolve(), REPOSITORY_ROOT)
            return completed(envelope)

        with patch("arena.datasets.authoring.subprocess.run", side_effect=side_effect):
            response = claude_runner(request)

        self.assertEqual(len(response.items), len(request.item_ids))
        self.assertIsInstance(observed["args"][0], (list, tuple))
        self.assertNotIsInstance(observed["args"][0], str)
        kwargs = observed["kwargs"]
        self.assertEqual(kwargs["input"], request.prompt)
        self.assertEqual(kwargs["timeout"], CALL_TIMEOUT_SECONDS)
        self.assertTrue(setting_sources_is_empty(tuple(observed["args"][0])))

    def test_the_repository_root_would_have_failed_that_check(self) -> None:
        # Without this the CLAUDE.md assertion above would be vacuous on a
        # checkout that happened not to have the file: it has to be the case that
        # running from the repository root WOULD have loaded a brief.
        self.assertTrue((REPOSITORY_ROOT / "CLAUDE.md").exists())


class ErrorBranchingTest(unittest.TestCase):
    """L-14: exit code 0 is not evidence the call succeeded."""

    def test_is_error_true_with_returncode_zero_raises(self) -> None:
        request = authoring_request()
        envelope = fake_authoring_response(authored_items(request.item_ids))
        envelope["is_error"] = True
        with patch(
            "arena.datasets.authoring.subprocess.run",
            return_value=completed(envelope, returncode=0),
        ):
            with self.assertRaises(AuthoringError):
                claude_runner(request)

    def test_error_max_turns_with_a_null_result_raises(self) -> None:
        request = authoring_request()
        envelope = fake_authoring_response(authored_items(request.item_ids))
        envelope["subtype"] = "error_max_turns"
        envelope["result"] = None
        with patch(
            "arena.datasets.authoring.subprocess.run",
            return_value=completed(envelope, returncode=0),
        ):
            with self.assertRaises(AuthoringError):
                claude_runner(request)

    def test_a_timeout_becomes_an_authoring_error(self) -> None:
        request = authoring_request()
        failure = subprocess.TimeoutExpired(("claude", "-p"), CALL_TIMEOUT_SECONDS)
        with patch("arena.datasets.authoring.subprocess.run", side_effect=failure):
            with self.assertRaises(AuthoringError):
                claude_runner(request)

    def test_unparseable_stdout_becomes_an_authoring_error(self) -> None:
        request = authoring_request()
        broken = subprocess.CompletedProcess(
            args=("claude", "-p"), returncode=0, stdout="not json at all", stderr=""
        )
        with patch("arena.datasets.authoring.subprocess.run", return_value=broken):
            with self.assertRaises(AuthoringError):
                claude_runner(request)

    def test_an_unrequested_item_id_is_refused(self) -> None:
        # Untrusted model output crossing the boundary. An id nobody asked for
        # cannot be matched to a target, and filing it would attach one item's
        # phrase to another item's identity.
        request = authoring_request()
        envelope = fake_authoring_response(
            ({"id": "probe_v1_9999", "phrase": "a leathery finish"},)
        )
        with patch(
            "arena.datasets.authoring.subprocess.run", return_value=completed(envelope)
        ):
            with self.assertRaises(AuthoringError):
                claude_runner(request)

    def test_two_resolved_ids_inside_one_call_are_refused(self) -> None:
        request = authoring_request()
        envelope = fake_authoring_response(authored_items(request.item_ids))
        envelope["modelUsage"] = {
            "claude-haiku-4-5-20251001": {"costUSD": 0.01},
            "claude-sonnet-5": {"costUSD": 0.02},
        }
        with patch(
            "arena.datasets.authoring.subprocess.run", return_value=completed(envelope)
        ):
            with self.assertRaises(AuthoringError):
                claude_runner(request)


class ProvenanceWhitelistTest(unittest.TestCase):
    """V7 and MEAS-13: what a committed record may carry, and what it may not."""

    def _response_and_record(self):
        request = authoring_request()
        envelope = fake_authoring_response(authored_items(request.item_ids))
        with patch(
            "arena.datasets.authoring.subprocess.run", return_value=completed(envelope)
        ):
            response = claude_runner(request)
        return request, response, log_record(request, response)

    def test_the_resolved_model_id_is_recorded_never_the_alias(self) -> None:
        request, response, record = self._response_and_record()
        self.assertEqual(response.model_resolved, "claude-haiku-4-5-20251001")
        self.assertNotEqual(response.model_resolved, request.model_alias)
        self.assertEqual(record["model_alias"], "haiku")
        self.assertEqual(record["model_resolved"], "claude-haiku-4-5-20251001")

    def test_the_record_key_set_is_exactly_the_documented_set(self) -> None:
        _, _, record = self._response_and_record()
        self.assertEqual(set(record), EXPECTED_LOG_KEYS)
        self.assertEqual(record["schema_version"], RESPONSE_LOG_SCHEMA_VERSION)

    def test_no_record_key_names_a_credential_or_the_environment(self) -> None:
        _, _, record = self._response_and_record()
        offenders = {
            key
            for key in record
            for marker in FORBIDDEN_KEY_SUBSTRINGS
            if marker in key.lower()
        }
        self.assertEqual(offenders, set())

    def test_the_serialized_record_carries_no_credential_marker(self) -> None:
        _, _, record = self._response_and_record()
        serialized = json.dumps(record, sort_keys=True).lower()
        for marker in CREDENTIAL_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, serialized)

    def test_usage_is_exactly_the_four_integer_counters(self) -> None:
        _, response, record = self._response_and_record()
        self.assertEqual(
            tuple(name for name, _ in response.usage),
            (
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
                "input_tokens",
                "output_tokens",
            ),
        )
        self.assertTrue(all(isinstance(value, int) for _, value in response.usage))
        self.assertEqual(set(record["usage"]), {name for name, _ in response.usage})


class ReviewPayloadTest(unittest.TestCase):
    """D-35: the reviewer's whole input is three fields."""

    def test_the_payload_is_exactly_three_fields(self) -> None:
        payload = ReviewPayload("material", "wool", "a warm woolly layer")
        self.assertEqual(
            set(payload.as_record()), {"gist_attribute", "gist_value", "phrase"}
        )
        self.assertEqual(
            list(payload.as_record()), ["gist_attribute", "gist_value", "phrase"]
        )

    def test_no_catalog_text_can_reach_the_reviewer_through_this_surface(self) -> None:
        target = product(
            "B000000001",
            title="Cascade Ridge Waterproof Leather Hiking Boot",
            features=("rubber sole", "imported", "lace up closure"),
            details=(("material", "full grain leather"), ("color", "brown")),
            description="A rugged boot built for long days on rough ground.",
            store="Cascade Ridge",
        )
        payload = ReviewPayload("material", "wool", "a warm woolly layer")
        serialized = json.dumps(payload.as_record(), sort_keys=True)

        def spans(text: str) -> set[tuple[str, ...]]:
            tokens = ordered_tokens(text)
            return set(zip(tokens, tokens[1:], tokens[2:], tokens[3:]))

        self.assertEqual(spans(serialized) & spans(searchable_text(target)), set())

    def test_the_span_check_can_actually_fail(self) -> None:
        # Two-sided: the assertion above is only evidence if a payload that DID
        # carry catalog phrasing would be caught by the same comparison.
        target = product(
            "B000000001",
            title="Cascade Ridge Waterproof Leather Hiking Boot",
            features=("rubber sole",),
        )

        def spans(text: str) -> set[tuple[str, ...]]:
            tokens = ordered_tokens(text)
            return set(zip(tokens, tokens[1:], tokens[2:], tokens[3:]))

        leaked = ReviewPayload(
            "material", "leather", "cascade ridge waterproof leather hiking boot"
        )
        serialized = json.dumps(leaked.as_record(), sort_keys=True)
        self.assertNotEqual(spans(serialized) & spans(searchable_text(target)), set())

    def test_an_empty_payload_field_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            ReviewPayload("material", "", "a warm woolly layer").validate()


class ReplayTest(unittest.TestCase):
    """D-50: the corpus is re-derivable from committed bytes, byte for byte."""

    def _log_with_two_records(self, directory: Path) -> tuple[Path, tuple[AuthoringRequest, ...]]:
        first = authoring_request(item_ids=("probe_v1_0001", "probe_v1_0002"))
        second = authoring_request(
            kind="review",
            model_alias="sonnet",
            prompt_name="review_faithfulness.md",
            prompt="review each item",
            item_ids=("probe_v1_0003",),
        )
        records = []
        for request in (first, second):
            envelope = fake_authoring_response(authored_items(request.item_ids))
            with patch(
                "arena.datasets.authoring.subprocess.run", return_value=completed(envelope)
            ):
                response = claude_runner(request)
            records.append(log_record(request, response))
        path = directory / "responses.probe_v1.jsonl"
        write_response_log(path, tuple(records))
        return path, (first, second)

    def test_replay_returns_the_logged_parsed_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, requests = self._log_with_two_records(Path(directory))
            runner = replay_runner(path)
            logged = {
                str(record["request_digest"]): record
                for record in load_response_log(path)
            }
            for request in requests:
                response = runner(request)
                expected = logged[request_digest(request)]["items"]
                self.assertEqual(list(response.item_records()), list(expected))

    def test_an_absent_digest_raises_and_names_the_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self._log_with_two_records(Path(directory))
            runner = replay_runner(path)
            stranger = authoring_request(prompt="a prompt that was never frozen")
            with self.assertRaises(AuthoringError) as raised:
                runner(stranger)
            self.assertIn(request_digest(stranger), str(raised.exception))

    def test_two_replay_passes_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, requests = self._log_with_two_records(Path(directory))

            def render() -> str:
                runner = replay_runner(path)
                return json.dumps(
                    [
                        log_record(request, runner(request))
                        for request in requests
                    ],
                    sort_keys=True,
                )

            self.assertEqual(render(), render())

    def test_a_duplicated_digest_makes_replay_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self._log_with_two_records(Path(directory))
            records = load_response_log(path)
            write_response_log(path, records + (records[0],))
            with self.assertRaises(AuthoringError):
                replay_runner(path)

    def test_a_malformed_log_line_is_refused_with_its_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.broken.jsonl"
            path.write_text('{"schema_version": 1}\nnot json\n', encoding="utf-8")
            with self.assertRaises(AuthoringError) as raised:
                load_response_log(path)
            self.assertIn("line 2", str(raised.exception))

    def test_a_record_with_an_unexpected_key_is_refused_at_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self._log_with_two_records(Path(directory))
            record = dict(load_response_log(path)[0])
            record["anthropic_api_key"] = "sk-should-never-be-here"
            with self.assertRaises(AuthoringError):
                write_response_log(path, (record,))


class ModelIdUniquenessTest(unittest.TestCase):
    """MEAS-13 and Pitfall 7: one corpus, one generator."""

    def _records(self, *model_ids: str) -> tuple[dict[str, object], ...]:
        records = []
        for index, model_id in enumerate(model_ids):
            request = authoring_request(item_ids=(f"probe_v1_{index:04d}",))
            envelope = fake_authoring_response(
                authored_items(request.item_ids), model_resolved=model_id
            )
            with patch(
                "arena.datasets.authoring.subprocess.run", return_value=completed(envelope)
            ):
                response = claude_runner(request)
            records.append(log_record(request, response))
        return tuple(records)

    def test_a_single_generator_log_reports_one_id(self) -> None:
        records = self._records("claude-haiku-4-5-20251001", "claude-haiku-4-5-20251001")
        self.assertEqual(resolved_model_ids(records), ("claude-haiku-4-5-20251001",))
        self.assertEqual(
            assert_single_resolved_model(records), "claude-haiku-4-5-20251001"
        )

    def test_a_mid_run_generator_change_is_rejected(self) -> None:
        records = self._records("claude-haiku-4-5-20251001", "claude-sonnet-5")
        self.assertEqual(
            resolved_model_ids(records),
            ("claude-haiku-4-5-20251001", "claude-sonnet-5"),
        )
        with self.assertRaises(AuthoringError) as raised:
            assert_single_resolved_model(records)
        self.assertIn("claude-sonnet-5", str(raised.exception))


class AttemptCapTest(unittest.TestCase):
    """T-02-06: bounded re-authoring, then a loud failure naming what failed."""

    def test_a_persistently_rejected_item_fails_after_exactly_the_cap(self) -> None:
        calls: list[tuple[str, ...]] = []

        def produce(pending: tuple[str, ...], attempt_index: int) -> dict[str, str]:
            calls.append(pending)
            return {item_id: f"attempt {attempt_index}" for item_id in pending}

        def accept(item_id: str, phrase: str) -> tuple[bool, str]:
            return False, "bucket flipped to style"

        with self.assertRaises(AuthoringError) as raised:
            attempt_until(("probe_v1_0001", "probe_v1_0002"), produce, accept)

        self.assertEqual(len(calls), AUTHORING_ATTEMPT_CAP)
        message = str(raised.exception)
        self.assertIn("probe_v1_0001", message)
        self.assertIn("probe_v1_0002", message)
        self.assertIn("bucket flipped to style", message)

    def test_success_on_the_second_attempt_stops_there(self) -> None:
        calls: list[tuple[str, ...]] = []

        def produce(pending: tuple[str, ...], attempt_index: int) -> dict[str, str]:
            calls.append(pending)
            return {item_id: f"attempt {attempt_index}" for item_id in pending}

        def accept(item_id: str, phrase: str) -> tuple[bool, str]:
            return phrase == "attempt 1", "not yet"

        result = attempt_until(("probe_v1_0001",), produce, accept)

        self.assertEqual(len(calls), 2)
        self.assertEqual(result, (("probe_v1_0001", "attempt 1"),))

    def test_a_missing_phrase_counts_as_a_rejection(self) -> None:
        def produce(pending: tuple[str, ...], attempt_index: int) -> dict[str, str]:
            return {}

        with self.assertRaises(AuthoringError) as raised:
            attempt_until(("probe_v1_0001",), produce, lambda _id, _phrase: (True, ""))
        self.assertIn("no phrase returned", str(raised.exception))

    def test_the_result_preserves_the_requested_order(self) -> None:
        item_ids = ("probe_v1_0003", "probe_v1_0001", "probe_v1_0002")

        def produce(pending: tuple[str, ...], attempt_index: int) -> dict[str, str]:
            return {item_id: item_id.upper() for item_id in pending}

        result = attempt_until(item_ids, produce, lambda _id, _phrase: (True, ""))
        self.assertEqual(tuple(item_id for item_id, _ in result), item_ids)


class PromptPackTest(unittest.TestCase):
    """The committed prompt pack, and the revision that is recorded against it."""

    def test_every_prompt_loads_and_the_revisions_are_distinct(self) -> None:
        names = ("author_expanded.md", "author_probe.md", "review_faithfulness.md")
        revisions = {name: prompt_revision(name) for name in names}
        self.assertEqual(len(set(revisions.values())), len(names))
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(load_prompt(name).strip())

    def test_the_revision_survives_a_line_ending_change(self) -> None:
        # This repository is developed with core.autocrlf enabled and ships no
        # .gitattributes, so the same committed prompt is CRLF in one checkout and
        # LF in another. A raw byte digest would report a different revision for
        # text nobody edited, which is exactly backwards.
        source = (PROMPTS_DIRECTORY / "author_probe.md").read_bytes()
        unix = source.replace(b"\r\n", b"\n")
        windows = unix.replace(b"\n", b"\r\n")
        self.assertNotEqual(unix, windows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unix.md").write_bytes(unix)
            (root / "windows.md").write_bytes(windows)
            with patch("arena.datasets.authoring.PROMPTS_DIRECTORY", root):
                self.assertEqual(prompt_revision("unix.md"), prompt_revision("windows.md"))

    def test_an_edit_still_changes_the_revision(self) -> None:
        # The two-sided half: normalizing line endings must not have flattened the
        # digest into something a real edit could slip past.
        source = (PROMPTS_DIRECTORY / "author_probe.md").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "original.md").write_bytes(source)
            (root / "edited.md").write_bytes(source + b"\nand one more rule\n")
            with patch("arena.datasets.authoring.PROMPTS_DIRECTORY", root):
                self.assertNotEqual(
                    prompt_revision("original.md"), prompt_revision("edited.md")
                )

    def test_maintainer_notes_never_reach_the_model(self) -> None:
        # The note explains that the framing is deliberately narrow. Telling an
        # author that something is being withheld invites it to guess, which is
        # the contamination D-57 exists to prevent, so the note is stripped.
        for name in ("author_expanded.md", "author_probe.md", "review_faithfulness.md"):
            with self.subTest(name=name):
                raw = (PROMPTS_DIRECTORY / name).read_text(encoding="utf-8")
                sent = load_prompt(name)
                self.assertIn("Maintainer note", raw)
                self.assertNotIn("Maintainer note", sent)
                self.assertNotIn("<!--", sent)
                self.assertIn("## Revision", sent)

    def test_a_missing_prompt_fails_loudly(self) -> None:
        with self.assertRaises(AuthoringError):
            prompt_revision("no_such_prompt.md")


class RuntimePurityTest(unittest.TestCase):
    """The driver is build-time only, and that is a property of the import graph."""

    def _top_level_imports(self, path: Path) -> frozenset[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module and not node.level:
                    found.add(node.module.split(".")[0])
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Closes the importlib.import_module("arena...") hole, exactly as
                # the arena boundary scan does for the harness package.
                if node.value.split(".")[0] == "arena":
                    found.add("arena")
        return frozenset(found)

    def _starter_modules(self) -> list[Path]:
        return [
            path
            for path in sorted((REPOSITORY_ROOT / "starter").rglob("*.py"))
            if "__pycache__" not in path.parts
        ]

    def test_no_shipped_agent_module_can_reach_the_driver(self) -> None:
        modules = self._starter_modules()
        self.assertGreaterEqual(
            len(modules), 1, "the scan would pass vacuously on an empty starter package"
        )
        offenders = {
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in modules
            if "arena" in self._top_level_imports(path)
        }
        self.assertEqual(
            offenders,
            set(),
            "starter/ must not import arena/: arena/datasets/authoring.py drives an "
            f"external process and may never be reachable at agent runtime. {offenders}",
        )

    def test_the_reachability_scan_actually_fires(self) -> None:
        # Two-sided. A scan that cannot detect the import it forbids is not
        # evidence of anything, and this one is the whole runtime-purity claim.
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                "from arena.datasets.authoring import claude_runner\n", encoding="utf-8"
            )
            self.assertIn("arena", self._top_level_imports(probe))

            dynamic = Path(directory) / "dynamic.py"
            dynamic.write_text(
                "import importlib\n"
                'module = importlib.import_module("arena.datasets.authoring")\n',
                encoding="utf-8",
            )
            self.assertIn("arena", self._top_level_imports(dynamic))

    def test_the_driver_itself_imports_no_agent_code(self) -> None:
        driver = REPOSITORY_ROOT / "arena" / "datasets" / "authoring.py"
        self.assertNotIn("starter", self._top_level_imports(driver))


class NoNetworkInTestsTest(unittest.TestCase):
    """No case in this module may spawn the external tool."""

    def _tree(self) -> ast.Module:
        path = Path(__file__).resolve()
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def _patched_line_ranges(self, tree: ast.Module) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            patched = any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "patch"
                for item in node.items
            )
            if patched:
                ranges.append((node.lineno, node.end_lineno or node.lineno))
        return ranges

    def test_every_runner_call_sits_inside_a_patch_block(self) -> None:
        tree = self._tree()
        ranges = self._patched_line_ranges(tree)
        self.assertGreaterEqual(len(ranges), 4)
        unguarded = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "claude_runner"
            and not any(start <= node.lineno <= end for start, end in ranges)
        ]
        self.assertEqual(
            unguarded,
            [],
            "an unpatched claude_runner() call would spawn the external tool; "
            f"offending lines: {unguarded}",
        )

    def test_the_guard_detects_an_unpatched_call(self) -> None:
        # Two-sided: proves the scan above is not vacuous.
        source = "response = claude_runner(request)\n"
        tree = ast.parse(source)
        ranges = self._patched_line_ranges(tree)
        self.assertEqual(ranges, [])
        found = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "claude_runner"
            and not any(start <= node.lineno <= end for start, end in ranges)
        ]
        self.assertEqual(found, [1])

    def test_this_module_imports_no_networking(self) -> None:
        tree = self._tree()
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module.split(".")[0])
        for name in ("http", "requests", "socket", "ssl", "urllib"):
            with self.subTest(name=name):
                self.assertNotIn(name, imported)


if __name__ == "__main__":
    unittest.main()
