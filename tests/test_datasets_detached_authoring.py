"""The detached authoring path: emit a queue, answer it elsewhere, replay it back.

A dedicated module rather than more cases in `tests/test_datasets_authoring.py`,
because the property that matters here spans two modules and cannot be asserted
inside either. `collecting_runner` lives in `arena/datasets/authoring.py` and the
`--emit-pending` flag in `arena/datasets/generate.py`, but the claim being tested
is about the corpus they jointly produce: a corpus assembled through
emit -> answer -> append -> replay must be byte-identical to one a runner answered
inline. If that is not true the whole path is unsound, so it is proven end to end
on a real 44-session corpus rather than asserted.

Everything here is offline and hand-written. The catalog is 24 dicts, the
authoring model is a lookup table, and `subprocess.run` is patched to record what
it was asked to spawn and then refuse -- so a fall-through to `claude_runner`
fails loudly instead of silently costing money, and the recorded argv proves no
`claude -p` call was attempted.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import arena.datasets.authoring as authoring_module
import arena.datasets.generate as generate_module
from arena.datasets.authoring import (
    DETACHED_SESSION_ID,
    PENDING_REQUEST_SCHEMA_VERSION,
    PENDING_MODEL_RESOLVED,
    AuthoringError,
    AuthoringRequest,
    AuthoringResponse,
    PendingRequestsError,
    append_response_log,
    collecting_runner,
    external_response_record,
    load_pending_requests,
    load_response_log,
    log_record,
    prompt_revision,
    replay_runner,
    request_digest,
    write_response_log,
)
from arena.datasets.generate import PENDING_REQUESTS_EXIT_STATUS, main


# The exact key set a pending-queue line may carry. A literal rather than an
# import of the module's own tuple, for the reason EXPECTED_LOG_KEYS gives in
# tests/test_datasets_authoring.py: importing it would make the assertion
# circular and a widened whitelist would widen its own test alongside it.
EXPECTED_PENDING_KEYS = {
    "item_ids",
    "kind",
    "model_alias",
    "prompt",
    "prompt_name",
    "prompt_revision",
    "request_digest",
    "schema_json",
    "schema_version",
}

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

# 20 pairs with a 4-pair cross-check arm is the smallest shape that clears the
# registry's 0.02 scenario-mix tolerance in ROWS rather than in pairs: at 20 pairs
# the intent_override share is 1/20 of the pairs but 2/44 of the rows, and the
# 4-pair third arm is what pulls every share back onto 40/40/15/5. A smaller
# corpus fails `check_scenario_mix` for a reason that has nothing to do with this
# path, and a corpus that could not be published would make every assertion below
# vacuous.
PAIR_COUNT = 20
CROSS_CHECK_COUNT = 4

# The wave count the loop structure implies, and the number the convergence test
# pins: one round for each arm's author stage and one for each arm's review
# stage. Author batches within a stage are independent, so a round collects the
# whole stage; a review prompt embeds phrases the author stage has not produced
# yet, so it cannot be collected in the same round.
EXPECTED_ROUNDS = 4
EXPECTED_CALLS = 8

_DEPARTMENTS = ("Women", "Men", "Girls", "Boys")
_PRICES = (12.5, 34.0, 74.0, 140.0)

# Product vocabulary, kept deliberately disjoint from the phrase table below so
# the D-34 divergence gate has something real to pass. Nonsense place names
# rather than apparel words, because a shared token would be measured as lexical
# reuse and the gate would reject the authored phrase.
_TITLE_WORDS = (
    "harbour",
    "meadow",
    "quarry",
    "lantern",
    "thistle",
    "orchard",
    "juniper",
    "cobble",
    "willow",
    "marsh",
    "beacon",
    "hollow",
)

# The stand-in author's whole vocabulary: one phrase per (bucket, slot code). The
# phrases are not decorative -- each one has to clear four real gates.
#
# * D-33 wants the control phrase's bucket back, so a material phrase keeps a
#   MATERIALS substring ("leathery" contains "leather") and a colour phrase keeps
#   a colour-clause substring ("blackish" contains "black").
# * D-34 wants zero content-token overlap and zero shared 2-grams with the
#   target's own searchable_text, which is why none of these words appears in a
#   fixture product.
# * The D-35 contradiction guard refuses a phrase asserting admitted vocabulary
#   the target lacks. "plasticky" was the first draft here and fails, because
#   `plastic` is an admitted material and no fixture product carries it.
# * The pair-uniqueness gate refuses a phrase repeated inside one pair, which is
#   why the table is keyed on the slot code and not on the bucket alone.
_PHRASES: dict[str, dict[str, str]] = {
    "material": {
        "h0": "leathery to the touch, never stiff",
        "h1": "leathery all over, nothing squeaky",
        "s0": "leathery enough to age well",
        "s1": "leathery but supple",
    },
    "color": {
        "h0": "blackish, nothing showy",
        "h1": "blackish through and through",
        "s0": "blackish tones only",
        "s1": "blackish, muted",
    },
    "feature": {
        "h0": "kind to my heels on paving",
        "h1": "easy to pull on quickly",
        "s0": "kind to my heels on paving",
        "s1": "easy to pull on quickly",
    },
}

# The only two spawns a generation run legitimately attempts, both local and
# offline: `_claude_cli_version`'s provenance probe and `current_revision`'s two
# git calls. `("claude", "-p", ...)` -- the authoring call itself -- is what must
# never appear, because reaching it would mean the detached path fell through to
# the subprocess runner.
_ALLOWED_SPAWNS = (("claude", "--version"),)


def spawn_is_allowed(argv: tuple[str, ...]) -> bool:
    return argv[:1] == ("git",) or argv in _ALLOWED_SPAWNS


_USAGE_ZEROS = (
    ("cache_creation_input_tokens", 0),
    ("cache_read_input_tokens", 0),
    ("input_tokens", 0),
    ("output_tokens", 0),
)


def catalog_lines(count: int = 24) -> str:
    """A hand-written catalog: every product a valid control card and a real gist."""

    lines = []
    for index in range(count):
        first = _TITLE_WORDS[index % len(_TITLE_WORDS)]
        second = _TITLE_WORDS[(index + 5) % len(_TITLE_WORDS)]
        product = {
            "parent_asin": f"T{index:09d}",
            "title": f"{first.title()} {second.title()} Ankle Boot",
            # Two feature strings and two structured details, which is what makes
            # `intent_card` yield four distinct cleaned constraints -- the shape
            # `IntentCard.validate()` requires and a thinner product cannot give.
            #
            # Both feature strings are KEYS IN THE COMMITTED D-52 ABSTRACTION
            # TABLE, and that is a requirement rather than a detail. `intent_card`
            # puts the recovered material and colour in `hard_constraints` and the
            # two raw features in `soft_preferences`, so the soft list is entirely
            # `feature`-bucket. Since 02-09b a constraint whose bucket the target's
            # gist cannot supply is not emitted at all, and `feature` is suppliable
            # only through this table -- the DF floor admits nothing for it (L-6).
            # The previous strings ("cushioned midsole", "quick lace hardware") are
            # in no table row, so every product here lost its whole soft list and
            # the pool went to zero. These two abstract to `ground_contact`
            # (pliant_tread) and `entry_method` (prong_strap), and they stay
            # lexically disjoint from `_PHRASES` so the D-34 gate still has
            # something real to pass.
            "features": ["Flexible sole", "Buckle closure"],
            "details": {"material": "leather", "color": "black"},
            "description": "Built for long days on rough ground.",
            "categories": ["Clothing, Shoes & Jewelry", _DEPARTMENTS[index % 4], "Boots"],
            "store": f"{first.title()} Supply",
            "price": _PRICES[index % 4],
        }
        lines.append(json.dumps(product, sort_keys=True))
    return "\n".join(lines) + "\n"


def answered_items(
    request: AuthoringRequest, *, perturb: str = ""
) -> tuple[dict[str, object], ...]:
    """The stand-in author and reviewer, reading only what the prompt carries.

    Deliberately parses the request body rather than closing over the generator's
    state: whoever answers a queued request has the prompt and nothing else, so a
    stand-in that consulted anything wider would prove a weaker property than the
    one this module claims.
    """
    body = json.loads(request.prompt.strip().splitlines()[-1])
    if request.kind == "review":
        return tuple(
            {"id": str(item["id"]), "verdict": "faithful"} for item in body["items"]
        )
    items = []
    for item in body["items"]:
        code = str(item["id"]).split(":")[1]
        phrase = _PHRASES[str(item["bucket"])][code]
        items.append({"id": str(item["id"]), "phrase": phrase + perturb})
    return tuple(items)


def inline_response(
    request: AuthoringRequest, *, perturb: str = ""
) -> AuthoringResponse:
    """The baseline: the same answers, handed straight back as a runner would."""

    request.validate()
    response = AuthoringResponse(
        items=tuple(
            tuple(sorted(item.items()))
            for item in answered_items(request, perturb=perturb)
        ),
        model_resolved=f"fake-{request.model_alias}-1",
        session_id="",
        usage=_USAGE_ZEROS,
        cost_usd=0.0,
        duration_ms=0,
        request_digest=request_digest(request),
        prompt_revision=prompt_revision(request.prompt_name),
    )
    response.validate()
    return response


def answer_the_queue(pending_path: Path, log_path: Path) -> int:
    """The operator step: read the queue, answer it, append the answers."""

    records = load_pending_requests(pending_path)
    for record in records:
        request = AuthoringRequest(
            kind=str(record["kind"]),
            model_alias=str(record["model_alias"]),
            prompt_name=str(record["prompt_name"]),
            prompt=str(record["prompt"]),
            schema_json=str(record["schema_json"]),
            item_ids=tuple(str(value) for value in record["item_ids"]),
        )
        appended = external_response_record(
            dict(record),
            answered_items(request),
            model_resolved=f"fake-{record['model_alias']}-1",
        )
        append_response_log(log_path, (appended,))
    return len(records)


def generate(
    root: Path, extra: tuple[str, ...], *, runner=None
) -> tuple[int, str, str, list[tuple[str, ...]]]:
    """Run the generator CLI with every path inside `root`, spawning nothing."""

    catalog = root / "catalog.jsonl"
    if not catalog.is_file():
        catalog.write_text(catalog_lines(), encoding="utf-8")
    spawned: list[tuple[str, ...]] = []

    def refuse(*args, **kwargs):
        spawned.append(tuple(args[0]))
        raise FileNotFoundError("claude is not on PATH in this test")

    argv = (
        "--corpus", "probe.v1",
        "--pairs", str(PAIR_COUNT),
        "--cross-check-pairs", str(CROSS_CHECK_COUNT),
        "--catalog", str(catalog),
        "--registry", str(root / "datasets.json"),
        "--corpus-root", str(root),
        "--markdown", str(root / "datasets.md"),
        "--response-log", str(root / "responses.jsonl"),
        "--divergence-log", str(root / "divergence.jsonl"),
        "--drop-log", str(root / "drops.jsonl"),
        "--target-snapshot", str(root / "targets.json"),
    ) + extra
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        # `generate` and `authoring` both do a plain `import subprocess`, so this
        # patches the one shared module attribute and covers the claude_runner
        # call site as well as the --version probe. SubprocessIsolationTest pins
        # that the two names really are the same object.
        stack.enter_context(
            patch("arena.datasets.generate.subprocess.run", side_effect=refuse)
        )
        if runner is not None:
            # Patched where the name is LOOKED UP: generate.py did
            # `from ...authoring import replay_runner`, so patching the authoring
            # module's attribute would leave this binding untouched and the patch
            # would silently do nothing.
            stack.enter_context(
                patch("arena.datasets.generate.replay_runner", return_value=runner)
            )
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    return code, out.getvalue(), err.getvalue(), spawned


def build_inline(root: Path, *, perturb: str = "") -> list[AuthoringRequest]:
    """Publish a corpus with a runner that answers inline. The baseline."""

    seen: list[AuthoringRequest] = []

    def runner(request: AuthoringRequest) -> AuthoringResponse:
        seen.append(request)
        return inline_response(request, perturb=perturb)

    code, _, err, spawned = generate(
        root, ("--replay", str(root / "unused-log.jsonl")), runner=runner
    )
    if code != 0:
        raise AssertionError(f"inline generation failed: {err}")
    forbidden = [argv for argv in spawned if not spawn_is_allowed(argv)]
    if forbidden:
        raise AssertionError(f"inline generation spawned {forbidden}")
    return seen


def build_detached(root: Path) -> tuple[int, list[int], list[tuple[str, ...]]]:
    """Publish a corpus through emit -> answer -> append -> replay. The path itself."""

    log = root / "log.jsonl"
    queue = root / "pending.jsonl"
    per_round: list[int] = []
    spawned: list[tuple[str, ...]] = []
    while True:
        code, _, err, attempts = generate(
            root, ("--replay", str(log), "--emit-pending", str(queue))
        )
        spawned.extend(attempts)
        if code == 0:
            return len(per_round), per_round, spawned
        if code != PENDING_REQUESTS_EXIT_STATUS:
            raise AssertionError(f"detached round {len(per_round)} failed: {err}")
        per_round.append(answer_the_queue(queue, log))
        if len(per_round) > EXPECTED_ROUNDS + 4:
            raise AssertionError(f"detached path did not converge: {per_round}")


SCHEMA_JSON = json.dumps(
    {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "phrase": {"type": "string"}},
            "required": ["id", "phrase"],
            "additionalProperties": False,
        },
    },
    sort_keys=True,
    separators=(",", ":"),
)


def unit_request(
    *,
    kind: str = "author",
    prompt: str = "write one requirement per item",
    item_ids: tuple[str, ...] = ("probe_v1_0001:h0", "probe_v1_0001:h1"),
) -> AuthoringRequest:
    request = AuthoringRequest(
        kind=kind,
        model_alias="sonnet",
        prompt_name="author_probe.md",
        prompt=prompt,
        schema_json=SCHEMA_JSON,
        item_ids=item_ids,
    )
    request.validate()
    return request


def logged(request: AuthoringRequest, phrase: str = "a leathery finish") -> dict:
    response = AuthoringResponse(
        items=tuple(
            (("id", item_id), ("phrase", phrase)) for item_id in request.item_ids
        ),
        model_resolved="fake-sonnet-1",
        session_id="",
        usage=_USAGE_ZEROS,
        cost_usd=0.0,
        duration_ms=0,
        request_digest=request_digest(request),
        prompt_revision=prompt_revision(request.prompt_name),
    )
    response.validate()
    return log_record(request, response)


class CollectingRunnerTest(unittest.TestCase):
    """The runner's own contract, without the generator around it."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)
        self.log = self.root / "log.jsonl"
        self.queue = self.root / "pending.jsonl"

    def _collector(self, *, with_log: bool = True):
        return collecting_runner(
            replay_path=self.log if with_log else None, pending_path=self.queue
        )

    def test_a_logged_digest_replays_exactly_as_replay_runner_would(self) -> None:
        request = unit_request()
        write_response_log(self.log, (logged(request),))
        collected = self._collector()(request)
        replayed = replay_runner(self.log)(request)
        self.assertEqual(collected.item_records(), replayed.item_records())
        self.assertEqual(collected.request_digest, replayed.request_digest)
        self.assertEqual(collected.model_resolved, replayed.model_resolved)
        self.assertEqual(load_pending_requests(self.queue), ())

    def test_an_absent_log_is_the_first_round_rather_than_an_error(self) -> None:
        self.assertFalse(self.log.is_file())
        collector = self._collector()
        collector(unit_request())
        self.assertEqual(len(collector.pending), 1)

    def test_a_duplicated_digest_in_the_log_is_refused_as_replay_refuses_it(
        self,
    ) -> None:
        record = logged(unit_request())
        write_response_log(self.log, (record, record))
        with self.assertRaises(AuthoringError) as collecting:
            self._collector()
        with self.assertRaises(AuthoringError) as replaying:
            replay_runner(self.log)
        self.assertEqual(str(collecting.exception), str(replaying.exception))

    def test_a_miss_queues_the_request_and_returns_no_items(self) -> None:
        request = unit_request()
        collector = self._collector()
        response = collector(request)
        self.assertEqual(response.items, ())
        self.assertEqual(response.model_resolved, PENDING_MODEL_RESOLVED)
        queued = load_pending_requests(self.queue)
        self.assertEqual(len(queued), 1)
        self.assertEqual(set(queued[0]), EXPECTED_PENDING_KEYS)
        self.assertEqual(queued[0]["schema_version"], PENDING_REQUEST_SCHEMA_VERSION)
        self.assertEqual(queued[0]["request_digest"], request_digest(request))

    def test_the_queued_prompt_is_the_prompt_that_would_have_been_sent(self) -> None:
        # The single most load-bearing field. An answer produced against a
        # re-derived prompt would be filed under a digest the generator never
        # looks up, and the miss would surface only at the next round with
        # nothing to say why.
        request = unit_request(prompt="an unmistakable prompt body\n")
        collector = self._collector()
        collector(request)
        queued = load_pending_requests(self.queue)[0]
        self.assertEqual(queued["prompt"], request.prompt)
        self.assertEqual(queued["schema_json"], request.schema_json)
        self.assertEqual(list(queued["item_ids"]), list(request.item_ids))
        self.assertEqual(
            queued["prompt_revision"], prompt_revision(request.prompt_name)
        )

    def test_disjoint_misses_are_all_collected_in_one_run(self) -> None:
        # The throughput half of the wave rule: stopping at the first miss would
        # force one round per batch, which at probe scale is ~160 rounds.
        collector = self._collector()
        for index in range(5):
            collector(unit_request(item_ids=(f"probe_v1_{index:04d}:h0",)))
        self.assertEqual(len(collector.pending), 5)
        self.assertEqual(len(load_pending_requests(self.queue)), 5)

    def test_a_miss_sharing_an_item_with_a_queued_one_stops_the_run(self) -> None:
        collector = self._collector()
        collector(unit_request(item_ids=("probe_v1_0001:h0", "probe_v1_0001:h1")))
        with self.assertRaises(PendingRequestsError) as raised:
            collector(
                unit_request(
                    prompt="a second attempt at the same item",
                    item_ids=("probe_v1_0001:h1", "probe_v1_0002:h0"),
                )
            )
        # The branch's OWN message, not merely its type: the collector raises
        # AuthoringError subclasses from more than one place.
        self.assertIn("probe_v1_0001:h1", str(raised.exception))
        self.assertIn("depends on an unanswered one", str(raised.exception))
        self.assertEqual(len(collector.pending), 1)

    def test_the_stop_rule_is_dependency_and_not_simply_the_second_miss(
        self,
    ) -> None:
        # Two-sided companion to the case above. Without this the stop rule would
        # be satisfied by a collector that halted on every second miss, which is
        # the degenerate behaviour the throughput case exists to forbid.
        collector = self._collector()
        collector(unit_request(item_ids=("probe_v1_0001:h0",)))
        collector(unit_request(item_ids=("probe_v1_0002:h0",)))
        self.assertEqual(len(collector.pending), 2)

    def test_an_identical_request_is_queued_once_and_does_not_stop_the_run(
        self,
    ) -> None:
        # Reachable only because the digest check precedes the overlap check: a
        # repeat trivially overlaps itself, so the other order would make this
        # de-duplication a branch nothing could ever enter.
        request = unit_request()
        collector = self._collector()
        collector(request)
        response = collector(request)
        self.assertEqual(response.items, ())
        self.assertEqual(len(collector.pending), 1)
        self.assertEqual(len(load_pending_requests(self.queue)), 1)

    def test_the_queue_file_describes_this_run_and_not_the_last_one(self) -> None:
        first = self._collector()
        first(unit_request(item_ids=("probe_v1_0001:h0",)))
        self.assertEqual(len(load_pending_requests(self.queue)), 1)
        self._collector()
        self.assertEqual(load_pending_requests(self.queue), ())

    def test_the_collector_satisfies_the_runner_protocol(self) -> None:
        request = unit_request()
        write_response_log(self.log, (logged(request),))
        collector = self._collector()
        self.assertTrue(callable(collector))
        self.assertIsInstance(collector(request), AuthoringResponse)


class ExternalResponseRecordTest(unittest.TestCase):
    """The writer for answers this repository did not produce."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)
        self.request = unit_request()
        collector = collecting_runner(
            replay_path=None, pending_path=self.root / "pending.jsonl"
        )
        collector(self.request)
        self.pending = dict(load_pending_requests(self.root / "pending.jsonl")[0])
        self.items = tuple(
            {"id": item_id, "phrase": f"a leathery finish, {index}"}
            for index, item_id in enumerate(self.request.item_ids)
        )

    def _record(self, **overrides) -> dict:
        arguments = {
            "pending": self.pending,
            "items": self.items,
            "model_resolved": "fake-sonnet-1",
        }
        arguments.update(overrides)
        return external_response_record(
            arguments["pending"],
            arguments["items"],
            model_resolved=arguments["model_resolved"],
        )

    def test_the_record_carries_exactly_the_response_log_key_set(self) -> None:
        self.assertEqual(set(self._record()), EXPECTED_LOG_KEYS)

    def test_replay_accepts_the_appended_record_for_the_original_request(self) -> None:
        path = self.root / "log.jsonl"
        append_response_log(path, (self._record(),))
        response = replay_runner(path)(self.request)
        self.assertEqual(list(response.item_records()), list(self.items))

    def test_the_digest_is_the_queued_one_verbatim(self) -> None:
        self.assertEqual(
            self._record()["request_digest"], self.pending["request_digest"]
        )

    def test_an_edited_queue_entry_is_refused_rather_than_rehashed(self) -> None:
        # The failure this guards is silent by nature: a recomputed digest would
        # always agree with itself, the record would look valid, and replay would
        # miss it at the next round with no explanation.
        tampered = dict(self.pending)
        tampered["prompt"] = str(tampered["prompt"]) + " one more rule"
        with self.assertRaises(AuthoringError) as raised:
            self._record(pending=tampered)
        self.assertIn("does not hash to its own contents", str(raised.exception))

    def test_an_alias_model_id_is_refused(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self._record(model_resolved="sonnet")
        self.assertIn("must be a resolved id", str(raised.exception))

    def test_an_unrequested_item_id_is_refused(self) -> None:
        with self.assertRaises(AuthoringError) as raised:
            self._record(items=({"id": "probe_v1_9999:h0", "phrase": "a finish"},))
        self.assertIn("was not requested", str(raised.exception))

    def test_an_item_shaped_against_a_different_schema_is_refused(self) -> None:
        # `claude -p --json-schema` enforces this inside the tool; on this path
        # nothing does, and a `text` key would parse cleanly, carry a requested
        # id, and then yield no phrase at all.
        with self.assertRaises(AuthoringError) as raised:
            self._record(
                items=({"id": self.request.item_ids[0], "text": "a finish"},)
            )
        self.assertIn("expected ['id', 'phrase']", str(raised.exception))

    def test_a_review_verdict_outside_the_enum_is_refused(self) -> None:
        review_schema = json.dumps(
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "verdict": {"enum": ["drifted", "faithful", "wrong"]},
                    },
                    "required": ["id", "verdict"],
                    "additionalProperties": False,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        pending = dict(self.pending)
        pending["kind"] = "review"
        pending["schema_json"] = review_schema
        request = AuthoringRequest(
            kind="review",
            model_alias=str(pending["model_alias"]),
            prompt_name=str(pending["prompt_name"]),
            prompt=str(pending["prompt"]),
            schema_json=review_schema,
            item_ids=tuple(str(value) for value in pending["item_ids"]),
        )
        pending["request_digest"] = request_digest(request)
        with self.assertRaises(AuthoringError) as raised:
            self._record(
                pending=pending,
                items=({"id": self.request.item_ids[0], "verdict": "approved"},),
            )
        self.assertIn("expected one of ['drifted', 'faithful', 'wrong']", str(raised.exception))
        # The same pending record with a legal verdict must pass, or the case
        # above would be evidence about the reconstruction rather than the enum.
        record = self._record(
            pending=pending,
            items=({"id": self.request.item_ids[0], "verdict": "faithful"},),
        )
        self.assertEqual(record["kind"], "review")

    def test_a_pending_record_missing_a_field_is_refused(self) -> None:
        incomplete = dict(self.pending)
        incomplete.pop("prompt_revision")
        with self.assertRaises(AuthoringError) as raised:
            self._record(pending=incomplete)
        self.assertIn("missing=['prompt_revision']", str(raised.exception))

    def test_the_provenance_it_cannot_observe_is_recorded_as_zero(self) -> None:
        # The honesty requirement, asserted rather than trusted. No process ran,
        # so nothing was billed, timed or counted, and a plausible-looking number
        # here would make the corpus's recorded spend and latency a fiction.
        record = self._record()
        self.assertEqual(record["cost_usd"], 0.0)
        self.assertEqual(record["duration_ms"], 0)
        self.assertEqual(record["usage"], {name: 0 for name, _ in _USAGE_ZEROS})
        self.assertEqual(record["session_id"], DETACHED_SESSION_ID)

    def test_the_record_carries_no_credential_marker(self) -> None:
        serialized = json.dumps(self._record(), sort_keys=True).lower()
        for marker in ("anthropic", "api_key", "authorization", "bearer", "oauth", "secret"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, serialized)


class AppendResponseLogTest(unittest.TestCase):
    """Appending must leave the log exactly as replayable as writing it would."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)
        self.path = self.root / "log.jsonl"

    def test_appended_records_load_back_in_order(self) -> None:
        first = logged(unit_request(item_ids=("probe_v1_0001:h0",)))
        second = logged(unit_request(item_ids=("probe_v1_0002:h0",)))
        append_response_log(self.path, (first,))
        append_response_log(self.path, (second,))
        loaded = load_response_log(self.path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(
            [record["request_digest"] for record in loaded],
            [first["request_digest"], second["request_digest"]],
        )

    def test_a_digest_the_log_already_carries_is_refused(self) -> None:
        record = logged(unit_request())
        append_response_log(self.path, (record,))
        with self.assertRaises(AuthoringError) as raised:
            append_response_log(self.path, (record,))
        self.assertIn("already carries request digest", str(raised.exception))
        # And the refusal left the log usable rather than half-written.
        self.assertEqual(len(load_response_log(self.path)), 1)

    def test_a_record_with_an_unexpected_key_is_refused(self) -> None:
        record = dict(logged(unit_request()))
        record["anthropic_api_key"] = "sk-should-never-be-here"
        with self.assertRaises(AuthoringError) as raised:
            append_response_log(self.path, (record,))
        self.assertIn("extra=['anthropic_api_key']", str(raised.exception))
        self.assertFalse(self.path.is_file())

    def test_appending_matches_what_writing_the_same_records_produces(self) -> None:
        first = logged(unit_request(item_ids=("probe_v1_0001:h0",)))
        second = logged(unit_request(item_ids=("probe_v1_0002:h0",)))
        append_response_log(self.path, (first,))
        append_response_log(self.path, (second,))
        written = self.root / "written.jsonl"
        write_response_log(written, (first, second))
        self.assertEqual(self.path.read_bytes(), written.read_bytes())


class DetachedCorpusEquivalenceTest(unittest.TestCase):
    """The property the whole path rests on, proven on a real published corpus."""

    ARTIFACTS = ("probe.v1.jsonl", "divergence.jsonl", "targets.json")

    @classmethod
    def setUpClass(cls) -> None:
        cls._inline_directory = tempfile.TemporaryDirectory()
        cls._detached_directory = tempfile.TemporaryDirectory()
        cls.inline_root = Path(cls._inline_directory.name)
        cls.detached_root = Path(cls._detached_directory.name)
        cls.inline_requests = build_inline(cls.inline_root)
        cls.rounds, cls.per_round, cls.spawned = build_detached(cls.detached_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._inline_directory.cleanup()
        cls._detached_directory.cleanup()

    def test_the_corpus_is_byte_identical_to_the_inline_one(self) -> None:
        for name in self.ARTIFACTS:
            with self.subTest(artifact=name):
                self.assertEqual(
                    (self.inline_root / name).read_bytes(),
                    (self.detached_root / name).read_bytes(),
                )

    def test_the_corpus_being_compared_is_not_degenerate(self) -> None:
        # Without this the comparison above could hold over two empty files.
        rows = [
            json.loads(line)
            for line in (self.detached_root / "probe.v1.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 2 * PAIR_COUNT + CROSS_CHECK_COUNT)
        self.assertEqual(
            {row["arm"] for row in rows},
            {"control", "probe_haiku", "probe_sonnet"},
        )
        self.assertEqual(
            len({row["ground_truth"]["parent_asin"] for row in rows}), PAIR_COUNT
        )

    def test_the_byte_comparison_can_actually_fail(self) -> None:
        # Two-sided. A comparison that cannot distinguish two different corpora
        # would pass no matter what the detached path produced.
        with tempfile.TemporaryDirectory() as directory:
            perturbed = Path(directory)
            build_inline(perturbed, perturb=" and roomy")
            self.assertNotEqual(
                (self.inline_root / "probe.v1.jsonl").read_bytes(),
                (perturbed / "probe.v1.jsonl").read_bytes(),
            )

    def test_the_response_log_differs_only_in_its_honest_provenance(self) -> None:
        inline = load_response_log(self.inline_root / "responses.jsonl")
        detached = load_response_log(self.detached_root / "responses.jsonl")
        self.assertEqual(len(inline), EXPECTED_CALLS)
        self.assertEqual(len(detached), EXPECTED_CALLS)
        differing = {
            key
            for left, right in zip(inline, detached)
            for key in left
            if left[key] != right[key]
        }
        self.assertEqual(differing, {"session_id"})
        self.assertEqual(
            {record["session_id"] for record in detached}, {DETACHED_SESSION_ID}
        )
        self.assertEqual(
            {record["cost_usd"] for record in detached}, {0.0}
        )

    def test_the_placeholder_model_id_never_reaches_the_committed_log(self) -> None:
        text = (self.detached_root / "responses.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(PENDING_MODEL_RESOLVED, text)

    def test_convergence_takes_one_round_per_dependency_wave(self) -> None:
        # Four waves: each arm's author stage, then each arm's review stage. A
        # regression to one round per BATCH would show here as 8 rounds and would
        # otherwise be invisible, because both counts still converge.
        self.assertEqual(self.rounds, EXPECTED_ROUNDS)
        self.assertEqual(sum(self.per_round), EXPECTED_CALLS)
        self.assertTrue(
            all(count >= 1 for count in self.per_round), self.per_round
        )
        self.assertGreater(max(self.per_round), 1, self.per_round)

    def test_the_queue_is_empty_once_the_corpus_is_published(self) -> None:
        self.assertEqual(load_pending_requests(self.detached_root / "pending.jsonl"), ())

    def test_no_authoring_subprocess_was_spawned(self) -> None:
        self.assertTrue(self.spawned, "the spawn recorder never observed a call")
        self.assertEqual([argv for argv in self.spawned if not spawn_is_allowed(argv)], [])
        # Named explicitly as well as filtered, because the allow-list is the
        # thing a future edit would widen and the `claude -p` call is the one
        # spawn this whole path exists to avoid.
        for argv in self.spawned:
            with self.subTest(argv=argv):
                self.assertNotEqual(argv[:2], ("claude", "-p"))

    def test_the_spawn_allow_list_would_reject_the_authoring_call(self) -> None:
        # Two-sided: an allow-list that admitted everything would make the case
        # above pass however the path behaved.
        self.assertFalse(spawn_is_allowed(("claude", "-p", "--model", "sonnet")))
        self.assertTrue(spawn_is_allowed(("claude", "--version")))

    def test_the_registry_records_the_corpus_that_was_published(self) -> None:
        registry = json.loads(
            (self.detached_root / "datasets.json").read_text(encoding="utf-8")
        )
        entry = next(
            item for item in registry["datasets"] if item["name"] == "probe.v1"
        )
        self.assertEqual(entry["session_count"], 2 * PAIR_COUNT + CROSS_CHECK_COUNT)
        self.assertEqual(entry["distinct_target_count"], PAIR_COUNT)
        self.assertNotIn(entry["generator_model_resolved"], ("sonnet", "haiku"))
        self.assertEqual(entry["call_count"], EXPECTED_CALLS)


class PendingExitStatusTest(unittest.TestCase):
    """The CLI contract a driving script reads."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)

    def test_emit_pending_without_a_replay_log_is_refused(self) -> None:
        code, _, err, spawned = generate(
            self.root, ("--emit-pending", str(self.root / "pending.jsonl"))
        )
        self.assertEqual(code, 1)
        self.assertIn("--emit-pending requires --replay", err)
        self.assertEqual(spawned, [])

    def test_the_first_round_queues_work_and_publishes_nothing(self) -> None:
        queue = self.root / "pending.jsonl"
        code, out, _, _ = generate(
            self.root,
            ("--replay", str(self.root / "log.jsonl"), "--emit-pending", str(queue)),
        )
        self.assertEqual(code, PENDING_REQUESTS_EXIT_STATUS)
        self.assertIn("pending_requests=", out)
        self.assertTrue(load_pending_requests(queue))
        self.assertFalse((self.root / "probe.v1.jsonl").is_file())
        self.assertFalse((self.root / "datasets.json").is_file())

    def test_a_failure_with_nothing_queued_is_not_reported_as_pending(self) -> None:
        # The two-sided half of the pending status. Re-running a converged round
        # answers every request from the log, queues nothing, and then meets
        # `publish_corpus`'s refuse-if-exists -- a real failure, and one a driving
        # script must not mistake for "answer these and run me again".
        build_detached(self.root)
        code, _, err, _ = generate(
            self.root,
            (
                "--replay",
                str(self.root / "log.jsonl"),
                "--emit-pending",
                str(self.root / "pending.jsonl"),
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("corpus generation failed", err)

    def test_a_malformed_response_log_fails_rather_than_queueing(self) -> None:
        log = self.root / "log.jsonl"
        record = logged(unit_request())
        write_response_log(log, (record, record))
        code, _, err, _ = generate(
            self.root,
            ("--replay", str(log), "--emit-pending", str(self.root / "pending.jsonl")),
        )
        self.assertEqual(code, 1)
        self.assertIn("repeats request digest", err)

    def test_the_pending_status_is_distinct_from_the_failure_status(self) -> None:
        self.assertNotIn(PENDING_REQUESTS_EXIT_STATUS, (0, 1))


def digest_argument_source(module_source: str) -> str:
    """How `external_response_record` fills the response's `request_digest`."""

    tree = ast.parse(module_source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "external_response_record"
    )
    call = next(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "AuthoringResponse"
    )
    keyword = next(
        entry for entry in call.keywords if entry.arg == "request_digest"
    )
    return ast.dump(keyword.value)


class DigestProvenanceTest(unittest.TestCase):
    """The digest is TAKEN from the queue, never re-derived from a rebuild.

    Asserted on the source because the two are observationally identical while the
    tamper guard holds -- the guard proves the rebuild agrees, so a recomputing
    version passes every behavioural test in this module. That equivalence is
    exactly why the distinction is worth pinning: someone who later relaxed the
    guard would silently be left with a recomputed digest, and a recomputed digest
    always agrees with itself. The failure mode is then a replay miss with nothing
    to say why, which is unrecoverable without re-authoring the whole queue.
    """

    def test_the_response_takes_the_recorded_digest(self) -> None:
        source = Path(authoring_module.__file__).read_text(encoding="utf-8")
        self.assertEqual(
            digest_argument_source(source),
            ast.dump(ast.Name(id="recorded_digest", ctx=ast.Load())),
        )

    def test_the_scan_would_notice_a_recomputed_digest(self) -> None:
        # Two-sided: a scan that could not tell the two apart would pass on the
        # very mutation it exists to forbid.
        rewritten = (
            "def external_response_record(pending, items, *, model_resolved):\n"
            "    response = AuthoringResponse(\n"
            "        request_digest=request_digest(request),\n"
            "    )\n"
        )
        self.assertNotEqual(
            digest_argument_source(rewritten),
            ast.dump(ast.Name(id="recorded_digest", ctx=ast.Load())),
        )


class SubprocessIsolationTest(unittest.TestCase):
    """The spawn guard above is only evidence if it covers both call sites."""

    def test_both_modules_share_the_one_subprocess_module(self) -> None:
        self.assertIs(authoring_module.subprocess, subprocess)
        self.assertIs(generate_module.subprocess, subprocess)

    def test_the_claude_runner_is_not_reachable_on_the_detached_path(self) -> None:
        # `generate._run` picks the collector when one is supplied, so the
        # subprocess runner is not merely unused, it is unreachable. Asserted on
        # the source rather than hoped for.
        source = Path(generate_module.__file__).read_text(encoding="utf-8")
        self.assertIn("collector if collector is not None else", source)


if __name__ == "__main__":
    unittest.main()
