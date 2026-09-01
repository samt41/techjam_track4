from __future__ import annotations

import ast
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import run_arena
from arena.arena import _SampleMappingAgent, build_candidate_spec, run_candidate
from arena.candidate import CandidateSpec
from arena.datasets.registry import (
    DatasetEntry,
    RegistryError,
    write_registry,
)
from arena.datasets.schema import (
    CORPUS_SCHEMA_VERSION,
    SampleRow,
    distinct_targets,
    load_corpus,
    scenario_mix,
    write_corpus,
)
from arena.leaderboard import LEADERBOARD_MARKDOWN_PATH
from arena.metrics import SessionOutcome
from arena.run_arena import _build_parser, _resolve_dataset, main
from arena.store import (
    SESSIONS_FILENAME,
    SUMMARY_FILENAME,
    ArenaStoreError,
    load_sessions,
    sha256_file,
    write_sessions,
)
from starter.shopping_agent.search_backend import LexicalMode
from tests.dataset_fixtures import matched_pair, pair_id, sample_row


# Never a path under data/. Every collaborator that would touch the catalog is
# patched out, so this string is carried into the recorded Agent kwargs and never
# opened. That is the property that keeps this module runnable with no 61 MB
# catalog and no 580 MB artifact.
UNOPENED_CATALOG = "synthetic-catalog-never-opened"
UNOPENED_DATASET = "synthetic-dataset-never-opened"

# The hidden target the fake harness holds and must never hand to the Agent.
HIDDEN_TARGET = "B0HIDDENTARGET"


class _RecordingAgent:
    """Records every call it receives, so a test can assert over the log."""

    def __init__(self, log: list[tuple], on_close=None) -> None:
        self._log = log
        self._on_close = on_close
        self.closed = False

    def reset(self, session_id: str, user_profile: dict) -> None:
        self._log.append(("reset", session_id, user_profile))

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        self._log.append(("respond", session_id, user_message, turn, top_k))
        return {"message": "", "ask_attribute": None, "recommendations": []}

    def close(self) -> None:
        self._log.append(("close",))
        self.closed = True
        if self._on_close is not None:
            self._on_close()


class _AgentFactory:
    """Stands in for starter.agent.Agent and records its constructor kwargs.

    Accepts keyword arguments only, so a positional Agent construction inside
    run_candidate would raise here rather than passing silently.
    """

    def __init__(self, on_close=None) -> None:
        self.kwargs: dict | None = None
        self.log: list[tuple] = []
        self.agent: _RecordingAgent | None = None
        self._on_close = on_close

    def __call__(self, **kwargs) -> _RecordingAgent:
        self.kwargs = kwargs
        self.agent = _RecordingAgent(self.log, self._on_close)
        return self.agent


class _ReadRecordingDict(dict):
    """A dict that logs reads, so "written during, read only after" is testable."""

    def __init__(self) -> None:
        super().__init__()
        self.reads: list[str] = []

    def __getitem__(self, key):
        self.reads.append(str(key))
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.reads.append(str(key))
        return super().get(key, default)

    def items(self):
        self.reads.append("<items>")
        return super().items()


def _sample(sample_id: str) -> dict:
    # Shaped like a real public-set row: the ground truth is present in the sample,
    # exactly as the harness sees it, so a leak would be a real leak.
    return {
        "sample_id": sample_id,
        "scenario_type": "buying",
        "user_profile": {"age_group": "25-34", "style": "casual"},
        "ground_truth": {"parent_asin": HIDDEN_TARGET},
    }


def _session_row(sample_id: str, *, best_rank: int | None, turn: int | None) -> dict:
    return {
        "sample_id": sample_id,
        "scenario_type": "buying",
        "hit": turn is not None,
        "first_hit_turn": turn,
        "best_rank": best_rank,
        "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
    }


def _evaluation_result(rows: list[dict]) -> dict:
    # The aggregate keys the harness returns beside "sessions"; run_candidate copies
    # them into summary.json verbatim, so their values are irrelevant to these tests
    # and only their presence matters.
    return {
        "sample_count": len(rows),
        "hit_rate_at_10": 0.5,
        "mrr": 0.5,
        "mttc": 6.0,
        "efficiency": 0.5,
        "recommended_technical_score": 0.5,
        "reported_token_usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "scenario_metrics": {},
        "sessions": rows,
    }


def _fake_evaluate(rows: list[dict], session_ids: tuple[str, ...]):
    """A stand-in harness that drives the agent exactly as the real one does.

    It holds the ground truth, like the real harness, and hands the agent only the
    user profile and a customer message. Whether that separation actually holds is
    what test_ground_truth_never_reaches_the_agent asserts.
    """

    def evaluate(agent, samples, catalog_ids, categories, products) -> dict:
        for index, sample in enumerate(samples):
            agent.reset(session_ids[index], sample["user_profile"])
            agent.respond(session_ids[index], "I want a casual jacket", 1, 10)
        return _evaluation_result(rows)

    return evaluate


def _spec(**overrides: str) -> CandidateSpec:
    spec = CandidateSpec(
        name="synthetic-unit-candidate",
        code_revision="unknown_revision",
        code_revision_dirty=True,
        overrides=tuple(sorted(overrides.items())),
        catalog_sha256="unknown",
        dataset_sha256="unknown",
    )
    spec.validate()
    return spec


def _strings(value: object) -> list[str]:
    """Every string and mapping key reachable inside a recorded call argument."""
    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            found.append(str(key))
            found.extend(_strings(item))
        return found
    if isinstance(value, (list, tuple)):
        found = []
        for item in value:
            found.extend(_strings(item))
        return found
    if isinstance(value, str):
        return [value]
    return []


class SampleMappingTest(unittest.TestCase):
    def _wrapper(self) -> tuple[_SampleMappingAgent, list[tuple]]:
        log: list[tuple] = []
        wrapper = _SampleMappingAgent(
            _RecordingAgent(log),
            ("sample-a", "sample-b", "sample-c"),
        )
        return (wrapper, log)

    def test_reset_order_maps_uuid_to_sample_id(self) -> None:
        wrapper, _ = self._wrapper()
        for session_id in ("public_aaa", "public_bbb", "public_ccc"):
            wrapper.reset(session_id, {})
        self.assertEqual(
            wrapper.session_to_sample,
            {
                "public_aaa": "sample-a",
                "public_bbb": "sample-b",
                "public_ccc": "sample-c",
            },
        )

    def test_reset_beyond_the_sample_ids_does_not_raise_or_corrupt(self) -> None:
        wrapper, _ = self._wrapper()
        for session_id in ("public_aaa", "public_bbb", "public_ccc"):
            wrapper.reset(session_id, {})
        before = dict(wrapper.session_to_sample)
        wrapper.reset("public_ddd", {})  # one past the end of the sample-id tuple
        self.assertEqual(wrapper.session_to_sample, before)
        self.assertNotIn("public_ddd", wrapper.session_to_sample)

    def test_respond_delegates_verbatim(self) -> None:
        wrapper, log = self._wrapper()
        response = wrapper.respond("public_aaa", "a message", 3, 10)
        self.assertEqual(log, [("respond", "public_aaa", "a message", 3, 10)])
        self.assertEqual(
            response,
            {"message": "", "ask_attribute": None, "recommendations": []},
        )

    def test_close_delegates(self) -> None:
        wrapper, log = self._wrapper()
        wrapper.close()
        self.assertEqual(log, [("close",)])

    def test_mapping_is_written_during_and_read_only_after(self) -> None:
        wrapper, _ = self._wrapper()
        wrapper.session_to_sample = _ReadRecordingDict()
        for session_id in ("public_aaa", "public_bbb", "public_ccc"):
            wrapper.reset(session_id, {})
        # The in-evaluate phase writes the mapping and never consults it.
        self.assertEqual(wrapper.session_to_sample.reads, [])
        self.assertEqual(len(wrapper.session_to_sample), 3)
        # The instrument is live: a read after the fact IS recorded, so the empty
        # log above is evidence rather than a broken probe.
        self.assertEqual(wrapper.session_to_sample["public_aaa"], "sample-a")
        self.assertEqual(wrapper.session_to_sample.reads, ["public_aaa"])

    def test_ground_truth_never_reaches_the_agent(self) -> None:
        rows = [
            _session_row("sample-a", best_rank=1, turn=1),
            _session_row("sample-b", best_rank=None, turn=None),
        ]
        factory = _AgentFactory()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("arena.arena.Agent", factory),
                patch("arena.arena.load_jsonl", return_value=[_sample("sample-a"), _sample("sample-b")]),
                patch("arena.arena.catalog_index", return_value=(set(), {}, {})),
                patch(
                    "arena.arena.evaluate",
                    _fake_evaluate(rows, ("public_aaa", "public_bbb")),
                ),
            ):
                run_candidate(
                    _spec(exploration="disabled"),
                    run_id="probe",
                    catalog_path=UNOPENED_CATALOG,
                    dataset_path=UNOPENED_DATASET,
                    output_root=Path(directory),
                )

        self.assertTrue(factory.log, "the agent recorded no calls at all")
        seen: list[str] = []
        for call in factory.log:
            seen.extend(_strings(call[1:]))
        self.assertNotIn("ground_truth", seen)
        self.assertNotIn("parent_asin", seen)
        self.assertNotIn(HIDDEN_TARGET, seen)
        for value in seen:
            self.assertNotIn(HIDDEN_TARGET, value)


class SpecFidelityTest(unittest.TestCase):
    def _run(
        self,
        spec: CandidateSpec,
        directory: str,
        *,
        run_id: str = "unit-run",
        factory: _AgentFactory | None = None,
        rows: list[dict] | None = None,
    ) -> Path:
        rows = rows if rows is not None else [_session_row("sample-a", best_rank=2, turn=3)]
        factory = factory if factory is not None else _AgentFactory()
        with (
            patch("arena.arena.Agent", factory),
            patch("arena.arena.load_jsonl", return_value=[_sample("sample-a")]),
            patch("arena.arena.catalog_index", return_value=(set(), {}, {})),
            patch("arena.arena.evaluate", _fake_evaluate(rows, ("public_aaa",))),
        ):
            return run_candidate(
                spec,
                run_id=run_id,
                catalog_path=UNOPENED_CATALOG,
                dataset_path=UNOPENED_DATASET,
                output_root=Path(directory),
            )

    def test_agent_receives_exactly_the_spec_overrides(self) -> None:
        # Deliberately NON-default values on both knobs. A hard-coded
        # exploration="disabled" or lexical_mode=AUTO inside run_candidate would
        # reproduce the constructor defaults and pass a laxer assertion; against
        # these values it fails, which is the point of the test.
        spec = _spec(
            exploration="tail-only",
            lexical_mode="fallback",
            artifact_path="synthetic-artifact-directory",
        )
        factory = _AgentFactory()
        with tempfile.TemporaryDirectory() as directory:
            self._run(spec, directory, factory=factory)

        self.assertEqual(
            set(factory.kwargs),
            {"catalog_path", "trace", "exploration", "lexical_mode", "artifact_path"},
        )
        self.assertEqual(factory.kwargs["catalog_path"], UNOPENED_CATALOG)
        self.assertIsNone(factory.kwargs["trace"])
        self.assertEqual(factory.kwargs["exploration"], "tail-only")
        self.assertEqual(factory.kwargs["lexical_mode"], LexicalMode.FALLBACK)
        self.assertEqual(factory.kwargs["artifact_path"], "synthetic-artifact-directory")
        # The fingerprint therefore describes what actually ran (MEAS-14).
        self.assertEqual(dict(spec.overrides), {
            key: str(value) for key, value in factory.kwargs.items()
            if key not in ("catalog_path", "trace")
        })

    def test_published_summary_carries_the_fingerprint(self) -> None:
        spec = _spec(exploration="disabled")
        with tempfile.TemporaryDirectory() as directory:
            destination = self._run(spec, directory)
            record = json.loads(
                (destination / SUMMARY_FILENAME).read_text(encoding="utf-8")
            )
        self.assertEqual(record["fingerprint"], spec.fingerprint)
        self.assertTrue(record["provenance_complete"])
        self.assertEqual(record["candidate_name"], spec.name)
        self.assertEqual(record["overrides"], {"exploration": "disabled"})
        self.assertTrue(record["provenance"])
        digest = record["catalog_sha256"]
        self.assertEqual(digest, spec.catalog_sha256)
        self.assertIn("recommended_technical_score", record)

    def test_published_summary_records_a_64_hex_catalog_digest(self) -> None:
        # The digest travels from build_candidate_spec into the record unchanged, so
        # the 64-hex property is asserted where a real digest is actually computed.
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog-fixture.jsonl"
            catalog.write_text('{"parent_asin": "B01"}\n', encoding="utf-8")
            dataset = Path(directory) / "dataset-fixture.jsonl"
            dataset.write_text('{"sample_id": "sample-a"}\n', encoding="utf-8")
            spec = build_candidate_spec(
                "synthetic-digest-candidate",
                catalog_path=catalog,
                dataset_path=dataset,
                overrides={"exploration": "disabled"},
            )
        self.assertEqual(len(spec.catalog_sha256), 64)
        self.assertEqual(len(spec.dataset_sha256), 64)
        self.assertEqual(spec.catalog_sha256, spec.catalog_sha256.lower())
        int(spec.catalog_sha256, 16)

    def test_sessions_round_trip(self) -> None:
        rows = [
            _session_row("sample-a", best_rank=2, turn=3),
            _session_row("sample-b", best_rank=None, turn=None),
        ]
        expected = tuple(
            SessionOutcome(
                sample_id=row["sample_id"],
                scenario_type=row["scenario_type"],
                hit=row["hit"],
                first_hit_turn=row["first_hit_turn"],
                best_rank=row["best_rank"],
                reciprocal_rank=row["reciprocal_rank"],
            )
            for row in rows
        )
        with tempfile.TemporaryDirectory() as directory:
            factory = _AgentFactory()
            with (
                patch("arena.arena.Agent", factory),
                patch(
                    "arena.arena.load_jsonl",
                    return_value=[_sample("sample-a"), _sample("sample-b")],
                ),
                patch("arena.arena.catalog_index", return_value=(set(), {}, {})),
                patch(
                    "arena.arena.evaluate",
                    _fake_evaluate(rows, ("public_aaa", "public_bbb")),
                ),
            ):
                destination = run_candidate(
                    _spec(exploration="disabled"),
                    run_id="round-trip",
                    catalog_path=UNOPENED_CATALOG,
                    dataset_path=UNOPENED_DATASET,
                    output_root=Path(directory),
                )
            self.assertEqual(load_sessions(destination / SESSIONS_FILENAME), expected)

    def test_existing_destination_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "occupied").mkdir()
            with self.assertRaises(FileExistsError):
                self._run(_spec(), directory, run_id="occupied")

    def test_invalid_run_id_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                self._run(_spec(), directory, run_id="../escape")

    def test_build_candidate_spec_rejects_an_unknown_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog-fixture.jsonl"
            catalog.write_text('{"parent_asin": "B01"}\n', encoding="utf-8")
            dataset = Path(directory) / "dataset-fixture.jsonl"
            dataset.write_text('{"sample_id": "sample-a"}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                build_candidate_spec(
                    "synthetic-unit-candidate",
                    catalog_path=catalog,
                    dataset_path=dataset,
                    overrides={"belief_temperature": "1.0"},
                )

    def test_agent_is_closed_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "close-order"
            observed: list[bool] = []
            factory = _AgentFactory(on_close=lambda: observed.append(destination.exists()))
            published = self._run(
                _spec(),
                directory,
                run_id="close-order",
                factory=factory,
            )
            # On Windows os.replace on a directory raises PermissionError while a
            # handle is held inside it, so the close must precede the publish or a
            # completed 200-session run is lost at its final step.
            self.assertEqual(observed, [False])
            self.assertTrue(factory.agent.closed)
            self.assertTrue(published.exists())


class CliTest(unittest.TestCase):
    def _main(self, argv: list[str]) -> int:
        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            patch("sys.argv", argv),
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(stdout),
        ):
            with self.assertRaises(SystemExit) as raised:
                main()
        code = raised.exception.code
        return 0 if code is None else int(code)

    def test_help_exits_zero(self) -> None:
        self.assertEqual(self._main(["run_arena.py", "--help"]), 0)

    def test_run_subcommand_rejects_unknown_exploration_value(self) -> None:
        code = self._main(
            [
                "run_arena.py",
                "run",
                "--run-id",
                "x",
                "--name",
                "x",
                "--exploration",
                "bogus",
            ]
        )
        self.assertNotEqual(code, 0)

    def test_adjudicate_requires_a_candidate(self) -> None:
        code = self._main(
            ["run_arena.py", "adjudicate", "--baseline", "some/directory"]
        )
        self.assertNotEqual(code, 0)

    def test_a_subcommand_is_required(self) -> None:
        self.assertNotEqual(self._main(["run_arena.py"]), 0)


class FingerprintIdentityTest(unittest.TestCase):
    """MEAS-14's promise as assertions rather than as a comment.

    One configuration must have exactly one fingerprint no matter which entry path
    expressed it, and a knob the operator actually typed must still change it.
    Verification measured the opposite before this was closed: the
    default-everything configuration fingerprinted one way through the CLI, which
    injected argparse defaults into the hashed overrides, and another way
    programmatically, which recorded an empty mapping. Neither of those two digests
    is pinned here -- both were computed over a code_revision captured at
    verification time, so asserting them would fail on the next commit. The equality
    and the inequality are the properties; the digests were only the symptom.
    """

    def _fixtures(self, directory: str) -> tuple[Path, Path, Path]:
        # Real files, because the CLI validates both paths at its boundary before
        # anything is patched, and build_candidate_spec digests them. They stay a
        # single line each: nothing ever parses them, the seams below see to that.
        root = Path(directory)
        catalog = root / "catalog-fixture.jsonl"
        catalog.write_text('{"parent_asin": "B01"}\n', encoding="utf-8")
        dataset = root / "dataset-fixture.jsonl"
        dataset.write_text('{"sample_id": "sample-a"}\n', encoding="utf-8")
        return (catalog, dataset, root / "records")

    @contextlib.contextmanager
    def _seams(self, *, evaluate=None):
        rows = [_session_row("sample-a", best_rank=2, turn=3)]
        with (
            patch("arena.arena.Agent", _AgentFactory()),
            patch("arena.arena.load_jsonl", return_value=[_sample("sample-a")]),
            patch("arena.arena.catalog_index", return_value=(set(), {}, {})),
            patch(
                "arena.arena.evaluate",
                evaluate if evaluate is not None else _fake_evaluate(rows, ("public_aaa",)),
            ),
            # Pinned so the two entry paths can differ on nothing except the overrides
            # mapping under test. It also keeps the identity assertion off a git
            # subprocess whose answer could change between the two constructions.
            patch(
                "arena.arena.current_revision",
                return_value=("unknown_revision", True),
            ),
        ):
            yield

    def _cli_run(self, argv: list[str]) -> Path:
        # A successful `run` returns from main() rather than exiting, and prints the
        # published directory. CliTest's helper asserts SystemExit and so cannot
        # drive the success path.
        stdout = io.StringIO()
        with patch("sys.argv", argv), contextlib.redirect_stdout(stdout):
            main()
        return Path(stdout.getvalue().strip())

    def _argv(
        self,
        run_id: str,
        catalog: Path,
        dataset: Path,
        output_root: Path,
        *extra: str,
    ) -> list[str]:
        return [
            "run_arena.py",
            "run",
            "--run-id",
            run_id,
            "--name",
            "synthetic-identity-candidate",
            "--catalog",
            str(catalog),
            "--dataset",
            str(dataset),
            "--output-root",
            str(output_root),
            *extra,
        ]

    def _record(self, destination: Path) -> dict:
        return json.loads((destination / SUMMARY_FILENAME).read_text(encoding="utf-8"))

    def test_an_omitted_flag_is_absent_from_the_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog, dataset, output_root = self._fixtures(directory)
            with self._seams():
                destination = self._cli_run(
                    self._argv("default-invocation", catalog, dataset, output_root)
                )
            record = self._record(destination)
        # Before the fix this carried {"exploration": "disabled",
        # "lexical_mode": "auto"}, injected by argparse rather than by the operator.
        self.assertEqual(record["overrides"], {})

    def test_the_cli_default_invocation_agrees_with_the_programmatic_empty_overrides(
        self,
    ) -> None:
        """One configuration expressed by OMISSION, one digest, either entry path.

        What this does NOT claim: an invocation that explicitly types
        `--exploration disabled` records {"exploration": "disabled"} and still
        fingerprints differently from one that omits the flag, even though both
        configure a byte-identical Agent. That is intended -- the fingerprint
        describes the invocation -- and no test here may assert otherwise.
        """
        with tempfile.TemporaryDirectory() as directory:
            catalog, dataset, output_root = self._fixtures(directory)
            with self._seams():
                destination = self._cli_run(
                    self._argv("default-invocation", catalog, dataset, output_root)
                )
                programmatic = build_candidate_spec(
                    "synthetic-identity-candidate",
                    catalog_path=catalog,
                    dataset_path=dataset,
                    overrides={},
                )
            record = self._record(destination)
        self.assertEqual(record["overrides"], {})
        self.assertEqual(record["fingerprint"], programmatic.fingerprint)

    def test_a_passed_flag_is_recorded_verbatim(self) -> None:
        # The non-vacuity guard for the two assertions above: a filter that dropped
        # every flag would satisfy both of them and be badly wrong.
        with tempfile.TemporaryDirectory() as directory:
            catalog, dataset, output_root = self._fixtures(directory)
            with self._seams():
                default_destination = self._cli_run(
                    self._argv("default-invocation", catalog, dataset, output_root)
                )
                typed_destination = self._cli_run(
                    self._argv(
                        "typed-invocation",
                        catalog,
                        dataset,
                        output_root,
                        "--exploration",
                        "tail-only",
                        "--lexical-mode",
                        "fallback",
                    )
                )
            default_record = self._record(default_destination)
            typed_record = self._record(typed_destination)
        self.assertEqual(
            typed_record["overrides"],
            {"exploration": "tail-only", "lexical_mode": "fallback"},
        )
        self.assertNotEqual(
            typed_record["fingerprint"],
            default_record["fingerprint"],
        )

    def test_harness_output_colliding_with_a_provenance_key_is_refused(self) -> None:
        rows = [_session_row("sample-a", best_rank=2, turn=3)]

        def colliding_evaluate(agent, samples, catalog_ids, categories, products) -> dict:
            for index, sample in enumerate(samples):
                agent.reset(f"public_{index}", sample["user_profile"])
            result = _evaluation_result(rows)
            # The hazard the guard exists for: harness output that would win over an
            # arena-written provenance field and publish a record claiming a
            # fingerprint the arena never computed.
            result["fingerprint"] = "0" * 64
            return result

        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "records"
            destination = output_root / "collision"
            with self._seams(evaluate=colliding_evaluate):
                with self.assertRaises(ArenaStoreError) as raised:
                    run_candidate(
                        _spec(),
                        run_id="collision",
                        catalog_path=UNOPENED_CATALOG,
                        dataset_path=UNOPENED_DATASET,
                        output_root=output_root,
                    )
            self.assertIn("fingerprint", str(raised.exception))
            # A refusal, not a repaired record: nothing was published.
            self.assertFalse(destination.exists())

    def test_a_clean_harness_result_still_publishes(self) -> None:
        # The mirror non-vacuity guard: a check that rejected everything would pass
        # the refusal test above.
        spec = _spec()
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "records"
            with self._seams():
                destination = run_candidate(
                    spec,
                    run_id="clean",
                    catalog_path=UNOPENED_CATALOG,
                    dataset_path=UNOPENED_DATASET,
                    output_root=output_root,
                )
            record = self._record(destination)
        self.assertEqual(record["fingerprint"], spec.fingerprint)
        self.assertEqual(record["candidate_name"], spec.name)
        self.assertEqual(record["code_revision"], spec.code_revision)
        self.assertEqual(record["catalog_sha256"], spec.catalog_sha256)
        self.assertEqual(record["dataset_sha256"], spec.dataset_sha256)
        self.assertTrue(record["provenance_complete"])


# The five keys registry._DIVERGENCE_METRIC_KEYS pins, in sorted key order because
# DatasetEntry.validate refuses an unsorted metric tuple. Hand-written rather than
# derived through arena.datasets.divergence: nothing in this module measures
# divergence, and a real aggregator call here would couple these CLI tests to a
# module they do not exercise.
_DIVERGENCE = (
    (
        "material",
        (
            ("mean_overlap_ratio", 0.1),
            ("median_overlap_ratio", 0.1),
            ("min_overlap_ratio", 0.1),
            ("n", 1),
            ("pass_count", 1),
        ),
    ),
)


def _registry_entry(corpus: Path, *, name: str) -> DatasetEntry:
    """A registry entry describing `corpus` as it actually is on disk.

    The three shape fields are READ BACK from the written file rather than asserted,
    so a fixture cannot record a session count the corpus does not have and then
    "pass" a resolution test for the wrong reason.
    """
    records = load_corpus(corpus)
    entry = DatasetEntry(
        name=name,
        path=str(corpus),
        sha256=sha256_file(corpus),
        schema_version=CORPUS_SCHEMA_VERSION,
        session_count=len(records),
        distinct_target_count=len(distinct_targets(records)),
        scenario_mix=scenario_mix(records),
        generator_model_alias="sonnet",
        generator_model_resolved="claude-sonnet-4-5-20250929",
        claude_cli_version="2.0.14",
        prompt_pack=(("authoring.md", "b" * 64),),
        seed=7,
        code_revision="deadbeefcafe",
        code_revision_dirty=False,
        frozen_commit="0123456789abcdef",
        response_log_path="",
        response_log_sha256="",
        call_count=0,
        cost_usd=0.0,
        divergence=_DIVERGENCE,
        divergence_log_path="",
        divergence_log_sha256="",
        divergence_pair_count=0,
        target_snapshot_path="",
        target_snapshot_sha256="",
        target_snapshot_count=0,
    )
    entry.validate()
    return entry


def _outcome(sample_id: str, *, scenario_type: str, hit: bool) -> SessionOutcome:
    outcome = SessionOutcome(
        sample_id=sample_id,
        scenario_type=scenario_type,
        hit=hit,
        first_hit_turn=2 if hit else None,
        best_rank=1 if hit else None,
        reciprocal_rank=1.0 if hit else 0.0,
    )
    outcome.validate()
    return outcome


def _sessions_for(rows: tuple[SampleRow, ...]) -> tuple[SessionOutcome, ...]:
    # A fixed, index-derived hit pattern rather than a random one: control and probe
    # rows of one pair sit next to each other, so alternating on the index gives the
    # McNemar table discordant cells in both directions while staying byte-stable.
    return tuple(
        _outcome(
            row.sample_id,
            scenario_type=row.scenario_type,
            hit=index % 3 != 0,
        )
        for index, row in enumerate(rows)
    )


def _write_record(
    directory: Path,
    *,
    name: str,
    dataset_sha256: str,
    sessions: tuple[SessionOutcome, ...],
) -> Path:
    """A realistic run-record directory: a summary.json and a sessions.jsonl.

    The fingerprint is DERIVED from a real CandidateSpec and the record carries
    `candidate_name`, because leaderboard._spec_from_payload re-derives the
    fingerprint on the read path and refuses a record whose stored digest disagrees.
    A fixture that omitted candidate_name would resolve the spec name from run_id,
    mint a second fingerprint, and fail for a reason unrelated to the CLI.
    """
    directory.mkdir(parents=True)
    spec = CandidateSpec(
        name=name,
        code_revision="deadbeefcafe",
        code_revision_dirty=False,
        overrides=(("exploration", "disabled"),),
        catalog_sha256="a" * 64,
        dataset_sha256=dataset_sha256,
    )
    spec.validate()
    record = spec.as_record()
    record["candidate_name"] = spec.name
    record["run_id"] = directory.name
    record["provenance_complete"] = True
    (directory / SUMMARY_FILENAME).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_sessions(directory / SESSIONS_FILENAME, sessions)
    return directory


class _CliCase(unittest.TestCase):
    """Drives main(argv) directly. Nothing here spawns a process or runs an agent."""

    def _cli_failure(self, argv: tuple[str, ...]) -> str:
        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(stdout),
        ):
            with self.assertRaises(SystemExit) as raised:
                main(argv)
        code = raised.exception.code
        self.assertNotEqual(0 if code is None else int(code), 0)
        return stderr.getvalue()

    def _cli_success(self, argv: tuple[str, ...]) -> str:
        # A successful contrast or corpus-baselines RETURNS rather than exiting, so
        # this helper must not assert SystemExit -- an exit here is the failure.
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main(argv)
        return stdout.getvalue()

    def _help(self, argv: tuple[str, ...]) -> str:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(argv)
        self.assertEqual(raised.exception.code, 0)
        return stdout.getvalue()


class DatasetResolutionTest(_CliCase):
    """D-43 / Pitfall 6: a recorded digest becomes an enforced precondition."""

    @contextlib.contextmanager
    def _registry(self, directory: str, *, name: str = "probe.v1"):
        root = Path(directory) / "data"
        root.mkdir()
        corpus = root / f"{name}.jsonl"
        write_corpus(corpus, matched_pair(pair_id(0)))
        registry = root / "datasets.json"
        write_registry(registry, (_registry_entry(corpus, name=name),))
        # Patched where the name is LOOKED UP. arena/run_arena.py binds
        # REGISTRY_PATH and CORPUS_ROOT into its own module namespace and
        # _resolve_dataset reads both at CALL time, so patching the attributes on
        # arena.run_arena is what the resolver actually sees. Patching
        # arena.datasets.registry.REGISTRY_PATH instead would touch a default that
        # was already bound at def time and change nothing.
        with (
            patch.object(run_arena, "REGISTRY_PATH", registry),
            patch.object(run_arena, "CORPUS_ROOT", root),
        ):
            yield (root, corpus, registry)

    def test_a_registry_name_resolves_to_its_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._registry(directory) as (_, corpus, _registry_path):
                self.assertEqual(_resolve_dataset("probe.v1"), corpus)

    def test_the_patched_registry_is_what_makes_the_name_resolve(self) -> None:
        # The non-vacuity guard for every case in this class. Outside the patch the
        # same name is not a registry name at all and falls through to the path
        # branch, so a patch that silently did nothing would fail here rather than
        # letting the assertions above pass for the wrong reason.
        with tempfile.TemporaryDirectory() as directory:
            with self._registry(directory):
                pass
            with self.assertRaises(ValueError) as raised:
                _resolve_dataset("probe.v1")
        self.assertIn("dataset does not exist:", str(raised.exception))

    def test_a_drifted_corpus_is_refused_naming_both_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._registry(directory) as (_, corpus, registry):
                recorded = sha256_file(corpus)
                corpus.write_text(
                    corpus.read_text(encoding="utf-8").replace("black", "brown", 1),
                    encoding="utf-8",
                )
                observed = sha256_file(corpus)
                self.assertNotEqual(recorded, observed)
                with self.assertRaises(RegistryError) as raised:
                    _resolve_dataset("probe.v1")
        message = str(raised.exception)
        # Both digests, not merely "drifted": an operator has to be able to tell
        # which file changed from the message alone. This is the two-sided half --
        # a resolver that always succeeded would enforce nothing at all.
        self.assertIn(recorded, message)
        self.assertIn(observed, message)
        self.assertIn(str(registry), message)

    def test_a_registered_corpus_whose_file_vanished_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._registry(directory) as (_root, corpus, _registry_path):
                corpus.unlink()
                with self.assertRaises(RegistryError) as raised:
                    _resolve_dataset("probe.v1")
        # A distinct branch from the drift refusal, asserted on its own message: both
        # raise RegistryError, so an exception-type assertion alone would not tell
        # "the file changed" from "the file is gone".
        self.assertIn("but the file is missing", str(raised.exception))

    def test_an_unreadable_registry_is_refused_rather_than_ignored(self) -> None:
        # A malformed registry must NOT fall through to the path branch and silently
        # measure an unfrozen file: that would turn the one check standing between a
        # recorded digest and a measurement into a no-op whenever the JSON broke.
        with tempfile.TemporaryDirectory() as directory:
            with self._registry(directory) as (_root, _corpus, registry):
                registry.write_text(
                    json.dumps({"schema_version": 99, "datasets": []}) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(RegistryError) as raised:
                    _resolve_dataset("probe.v1")
        self.assertIn("unsupported registry schema version", str(raised.exception))

    def test_a_plain_filesystem_path_still_resolves(self) -> None:
        # Backward compatibility with data/public_set.jsonl, which is not and will
        # never be registry-managed.
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "public_set.jsonl"
            dataset.write_text('{"sample_id": "sample-a"}\n', encoding="utf-8")
            self.assertEqual(_resolve_dataset(str(dataset)), dataset)

    def test_a_nonexistent_path_keeps_the_existing_message_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            absent = Path(directory) / "absent.jsonl"
            with self.assertRaises(ValueError) as raised:
                _resolve_dataset(str(absent))
        self.assertIn("dataset does not exist:", str(raised.exception))

    def test_the_run_subcommand_refuses_a_drifted_name_through_parser_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self._registry(directory) as (root, corpus, _registry_path):
                catalog = root / "catalog-fixture.jsonl"
                catalog.write_text('{"parent_asin": "B01"}\n', encoding="utf-8")
                recorded = sha256_file(corpus)
                corpus.write_text(
                    corpus.read_text(encoding="utf-8").replace("black", "brown", 1),
                    encoding="utf-8",
                )
                # No seams patched: resolution happens at the CLI boundary before
                # anything is built, so this never reaches an Agent or a catalog.
                stderr = self._cli_failure(
                    (
                        "run",
                        "--run-id",
                        "drifted",
                        "--name",
                        "synthetic-drift-candidate",
                        "--catalog",
                        str(catalog),
                        "--dataset",
                        "probe.v1",
                        "--output-root",
                        str(root / "records"),
                    )
                )
        self.assertIn(recorded, stderr)
        self.assertIn("drifted from its frozen digest", stderr)


class HelpTextTest(_CliCase):
    """L-11: the warning lives in the subcommand it applies to, and nowhere else."""

    def test_the_run_help_states_the_flags_a_reproduction_must_type(self) -> None:
        text = self._help(("run", "--help"))
        self.assertIn("--exploration disabled --lexical-mode auto", text)
        self.assertIn("fingerprint", text)
        self.assertIn("registry name", text)

    def test_the_adjudicate_help_does_not_carry_the_run_warning(self) -> None:
        # The negative direction, and it is what makes the assertion above mean
        # something: a warning pasted into every subparser would satisfy the
        # positive test while telling an operator nothing about scope.
        text = self._help(("adjudicate", "--help"))
        self.assertNotIn("--exploration disabled --lexical-mode auto", text)


class _ContrastFixture(_CliCase):
    """Shared corpus and record construction for the three contrast test classes."""

    def _publish(
        self,
        directory: str,
        rows: tuple[SampleRow, ...],
        *,
        corpus_name: str = "probe.v1",
        extra_rows: tuple[SampleRow, ...] = (),
    ) -> tuple[Path, Path, Path]:
        root = Path(directory)
        corpus = root / f"{corpus_name}.jsonl"
        write_corpus(corpus, rows)
        # The record's sessions cover `extra_rows` as well, so a cross-corpus test
        # can point a second corpus at the SAME record and still reach the pair-id
        # join instead of failing earlier on an empty partition.
        record = _write_record(
            root / "records" / "probe-run",
            name="synthetic-contrast-candidate",
            dataset_sha256="b" * 64,
            sessions=_sessions_for(rows + extra_rows),
        )
        return (corpus, record, root / "out" / "baselines")


class ContrastCommandTest(_ContrastFixture):
    """D-44 through the CLI: one record, one corpus, two arms."""

    def _rows(self, pair_count: int = 8) -> tuple[SampleRow, ...]:
        rows: list[SampleRow] = []
        for index in range(pair_count):
            rows.extend(matched_pair(pair_id(index)))
        return tuple(rows)

    def test_the_default_shape_writes_both_artifacts_under_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, record, output_root = self._publish(directory, self._rows())
            stdout = self._cli_success(
                (
                    "contrast",
                    "--record",
                    str(record),
                    "--corpus",
                    str(corpus),
                    "--control-arm",
                    "control",
                    "--probe-arm",
                    "probe_sonnet",
                    "--output-root",
                    str(output_root),
                )
            )
            json_path = output_root / "paired_contrast.json"
            markdown_path = output_root.parent / "PAIRED_CONTRAST.md"
            self.assertTrue(json_path.is_file(), stdout)
            self.assertTrue(markdown_path.is_file(), stdout)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
        self.assertEqual(payload["pair_count"], 8)
        self.assertEqual(payload["restriction"], "strict")
        self.assertEqual(payload["dropped_pair_count"], 0)
        self.assertEqual(
            payload["corrections_omitted"],
            ["holm_bonferroni", "winners_curse_correction"],
        )
        self.assertIn("holm_bonferroni", markdown)
        # Both counts reach stdout, so the operator sees them without opening the
        # report they are about to cite.
        self.assertIn("pairs=8 dropped=0", stdout)

    def test_one_arm_named_twice_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, record, output_root = self._publish(directory, self._rows())
            stderr = self._cli_failure(
                (
                    "contrast",
                    "--record",
                    str(record),
                    "--corpus",
                    str(corpus),
                    "--control-arm",
                    "control",
                    "--probe-arm",
                    "control",
                    "--output-root",
                    str(output_root),
                )
            )
        # Asserted on the BRANCH's own message rather than on the exit code alone.
        # Several refusals inside _contrast funnel through the same parser.error, so
        # a bare non-zero exit would not distinguish this guard from any other.
        self.assertIn("both arms partition on arm 'control'", stderr)

    def test_an_arm_absent_from_the_corpus_lists_the_arms_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, record, output_root = self._publish(directory, self._rows())
            stderr = self._cli_failure(
                (
                    "contrast",
                    "--record",
                    str(record),
                    "--corpus",
                    str(corpus),
                    "--probe-arm",
                    "probe_haiku",
                    "--output-root",
                    str(output_root),
                )
            )
        self.assertIn("no corpus rows carry arm 'probe_haiku'", stderr)
        self.assertIn("['control', 'probe_sonnet']", stderr)

    def test_an_absent_record_directory_is_refused_at_the_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, record, output_root = self._publish(directory, self._rows())
            stderr = self._cli_failure(
                (
                    "contrast",
                    "--record",
                    str(record.parent / "absent-run"),
                    "--corpus",
                    str(corpus),
                    "--output-root",
                    str(output_root),
                )
            )
        self.assertIn("run directory does not exist:", stderr)

    def test_an_absent_corpus_is_refused_at_the_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, record, output_root = self._publish(directory, self._rows())
            stderr = self._cli_failure(
                (
                    "contrast",
                    "--record",
                    str(record),
                    "--corpus",
                    str(corpus.parent / "absent.jsonl"),
                    "--output-root",
                    str(output_root),
                )
            )
        self.assertIn("dataset does not exist:", stderr)


class PairSubsetCommandTest(_ContrastFixture):
    """MEAS-13 / D-40: the honest default refuses; the narrowing reports its drop."""

    _SONNET_PAIRS = 30
    _HAIKU_PAIRS = 10

    def _rows(self) -> tuple[SampleRow, ...]:
        # The REAL unequal shape, not a matched one scaled down: every pair carries
        # control and probe_sonnet, and only the first ten also carry probe_haiku.
        rows: list[SampleRow] = []
        for index in range(self._SONNET_PAIRS):
            identifier = pair_id(index)
            rows.extend(matched_pair(identifier))
            if index < self._HAIKU_PAIRS:
                rows.append(sample_row(identifier, arm="probe_haiku"))
        return tuple(rows)

    def _argv(self, corpus: Path, record: Path, output_root: Path, *extra: str):
        return (
            "contrast",
            "--record",
            str(record),
            "--corpus",
            str(corpus),
            "--control-arm",
            "probe_sonnet",
            "--probe-arm",
            "probe_haiku",
            "--output-root",
            str(output_root),
            *extra,
        )

    def test_the_default_refuses_and_names_the_orphan_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, record, output_root = self._publish(directory, self._rows())
            stderr = self._cli_failure(self._argv(corpus, record, output_root))
            self.assertFalse((output_root / "paired_contrast.json").exists())
        self.assertIn("unmatched pair ids between arms", stderr)
        # Names the ids, not merely the count: pair 10 is the first orphan, because
        # only pairs 0-9 carry a probe_haiku arm.
        self.assertIn("probe_v1_0010", stderr)

    def test_typing_the_default_value_behaves_exactly_like_omitting_it(self) -> None:
        # Not a tautology on this CLI. The one bug this repository has already
        # shipped in argparse defaults was exactly a flag whose declared default and
        # whose omitted behaviour diverged (L-11, and the comment block above _run),
        # so "strict is the default" has to be measured rather than read off the
        # declaration. Both spellings must produce the same refusal.
        with tempfile.TemporaryDirectory() as directory:
            corpus, record, output_root = self._publish(directory, self._rows())
            omitted = self._cli_failure(self._argv(corpus, record, output_root))
            typed = self._cli_failure(
                self._argv(corpus, record, output_root, "--pair-subset", "strict")
            )
            self.assertFalse((output_root / "paired_contrast.json").exists())
        self.assertIn("unmatched pair ids between arms", omitted)
        self.assertIn("unmatched pair ids between arms", typed)
        self.assertIn("probe_v1_0010", typed)

    def test_shared_narrows_explicitly_and_records_what_it_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, record, output_root = self._publish(directory, self._rows())
            stdout = self._cli_success(
                self._argv(
                    corpus,
                    record,
                    output_root,
                    "--pair-subset",
                    "shared",
                )
            )
            payload = json.loads(
                (output_root / "paired_contrast.json").read_text(encoding="utf-8")
            )
            markdown = (output_root.parent / "PAIRED_CONTRAST.md").read_text(
                encoding="utf-8"
            )
        self.assertEqual(payload["pair_count"], self._HAIKU_PAIRS)
        self.assertEqual(
            payload["dropped_pair_count"],
            self._SONNET_PAIRS - self._HAIKU_PAIRS,
        )
        self.assertEqual(payload["restriction"], "shared-pairs")
        self.assertIn("pairs=10 dropped=20", stdout)
        # The drop is stated in prose as well as in a cell: "10 pairs" and "10 of 30
        # pairs" support different claims (MEAS-06).
        self.assertIn("10 of 30 matched pairs", markdown)


class CrossCorpusGateTest(_ContrastFixture):
    """D-45, in both layers: the typed flag, and the disjoint pair-id namespaces."""

    def _corpora(self, directory: str) -> tuple[Path, Path, Path, Path]:
        probe_rows: list[SampleRow] = []
        foreign_rows: list[SampleRow] = []
        for index in range(6):
            probe_rows.extend(matched_pair(pair_id(index)))
            foreign_rows.extend(
                matched_pair(pair_id(index, corpus_stem="expanded_dev_v1"))
            )
        corpus, record, output_root = self._publish(
            directory,
            tuple(probe_rows),
            extra_rows=tuple(foreign_rows),
        )
        foreign = Path(directory) / "expanded_dev.v1.jsonl"
        write_corpus(foreign, tuple(foreign_rows))
        return (corpus, foreign, record, output_root)

    def _argv(self, corpus: Path, record: Path, output_root: Path, *extra: str):
        return (
            "contrast",
            "--record",
            str(record),
            "--corpus",
            str(corpus),
            "--output-root",
            str(output_root),
            *extra,
        )

    def test_probe_corpus_without_the_flag_is_refused_naming_d45(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, foreign, record, output_root = self._corpora(directory)
            stderr = self._cli_failure(
                self._argv(
                    corpus, record, output_root, "--probe-corpus", str(foreign)
                )
            )
        self.assertIn("D-45", stderr)
        self.assertIn("--allow-cross-corpus", stderr)

    def test_probe_record_without_the_flag_is_refused_naming_d45(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, _foreign, record, output_root = self._corpora(directory)
            stderr = self._cli_failure(
                self._argv(
                    corpus, record, output_root, "--probe-record", str(record)
                )
            )
        self.assertIn("D-45", stderr)

    def test_with_the_flag_the_namespaced_pair_ids_still_refuse_the_join(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus, foreign, record, output_root = self._corpora(directory)
            stderr = self._cli_failure(
                self._argv(
                    corpus,
                    record,
                    output_root,
                    "--probe-corpus",
                    str(foreign),
                    "--allow-cross-corpus",
                )
            )
            self.assertFalse((output_root / "paired_contrast.json").exists())
        # The proof that the STRUCTURAL defence is what closes the hole: the second
        # failure names pair ids from two namespaces, not the flag. Plan 02-03 makes
        # every pair_id carry its corpus stem, so two corpora intersect in nothing
        # and align_on_pair_id raises whether or not --allow-cross-corpus was typed.
        self.assertIn("unmatched pair ids between arms", stderr)
        self.assertIn("expanded_dev_v1_0000", stderr)
        # And it is NOT the flag gate that fired. The discriminator has to be "D-45"
        # rather than the flag name: argparse prints a usage banner alongside every
        # parser.error, and that banner lists --allow-cross-corpus whichever refusal
        # produced the message.
        self.assertNotIn("D-45", stderr)

    def _observe_flags(self, argv: tuple[str, ...]) -> dict[str, object]:
        """Record the keyword arguments the handler hands to paired_contrast.

        Patched on arena.run_arena, which is where the name is LOOKED UP: the module
        binds paired_contrast into its own namespace and calls that global at call
        time. The wrapper DELEGATES to the real function rather than standing in for
        it, so the contrast still has to succeed for the recorded flags to mean
        anything -- a stub would let the assertion pass over a handler that produced
        no report at all.
        """
        observed: dict[str, object] = {}
        real = run_arena.paired_contrast

        def recording(control, probe, **kwargs):
            observed.update(kwargs)
            return real(control, probe, **kwargs)

        with patch.object(run_arena, "paired_contrast", recording):
            self._cli_success(argv)
        self.assertTrue(observed, "the recording wrapper never ran")
        return observed

    def test_the_flag_is_false_unless_the_operator_types_it(self) -> None:
        # The must-have stated as a call-argument assertion, because it is not
        # otherwise observable: the CLI gate above already blocks every invocation
        # in which a differing digest could reach the guard, so a handler that
        # hard-coded allow_cross_corpus=True would behave identically from outside.
        with tempfile.TemporaryDirectory() as directory:
            corpus, _foreign, record, output_root = self._corpora(directory)
            observed = self._observe_flags(self._argv(corpus, record, output_root))
        self.assertIs(observed["allow_cross_corpus"], False)
        self.assertIs(observed["restrict_to_shared"], False)

    def test_the_typed_flag_carries_a_genuinely_cross_corpus_contrast(self) -> None:
        # The mirror direction, over the shape that actually differs on
        # dataset_sha256: two records measured against two different digests, joined
        # on ONE corpus so the pair ids still match and the digest guard is the only
        # thing standing in the way. A handler that hard-coded
        # allow_cross_corpus=False would refuse this.
        with tempfile.TemporaryDirectory() as directory:
            corpus, _foreign, record, output_root = self._corpora(directory)
            second = _write_record(
                Path(directory) / "records" / "second-run",
                name="synthetic-contrast-candidate",
                dataset_sha256="c" * 64,
                sessions=load_sessions(record / SESSIONS_FILENAME),
            )
            observed = self._observe_flags(
                self._argv(
                    corpus,
                    record,
                    output_root,
                    "--probe-record",
                    str(second),
                    "--allow-cross-corpus",
                )
            )
            payload = json.loads(
                (output_root / "paired_contrast.json").read_text(encoding="utf-8")
            )
        self.assertIs(observed["allow_cross_corpus"], True)
        self.assertNotEqual(
            payload["control_dataset_sha256"],
            payload["probe_dataset_sha256"],
        )


class CorpusBaselinesCommandTest(_CliCase):
    """D-53: four different-corpus rows get their own artifacts, never a leaderboard."""

    _NAMES = ("public", "probe.v1", "expanded_dev.v1")

    def _records(self, root: Path) -> tuple[Path, ...]:
        rows = tuple(matched_pair(pair_id(0))) + tuple(matched_pair(pair_id(1)))
        sessions = _sessions_for(rows)
        # ONE candidate name across all three, and three different dataset digests --
        # exactly the shape build_corpus_baselines admits and build_leaderboard
        # refuses.
        return tuple(
            _write_record(
                root / "records" / f"corpus-{index}",
                name="synthetic-corpus-candidate",
                dataset_sha256=str(index) * 64,
                sessions=sessions,
            )
            for index in range(len(self._NAMES))
        )

    def test_it_writes_its_own_artifacts_and_never_a_leaderboard(self) -> None:
        committed_leaderboard = (
            Path(__file__).resolve().parent.parent / LEADERBOARD_MARKDOWN_PATH
        )
        before = (
            committed_leaderboard.read_bytes()
            if committed_leaderboard.is_file()
            else None
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = self._records(root)
            output_root = root / "out" / "baselines"
            self._cli_success(
                (
                    "corpus-baselines",
                    *(
                        argument
                        for name, record in zip(self._NAMES, records)
                        for argument in ("--record", f"{name}={record}")
                    ),
                    "--output-root",
                    str(output_root),
                )
            )
            json_path = output_root / "corpus_baselines.json"
            markdown_path = output_root.parent / "CORPUS_BASELINES.md"
            self.assertTrue(json_path.is_file())
            self.assertTrue(markdown_path.is_file())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            # Asserted as an ABSENCE, which is the separation D-53 actually requires:
            # rglob over the whole temporary tree, so a handler that wrote a
            # leaderboard anywhere under --output-root would fail here.
            self.assertEqual(list(root.rglob("LEADERBOARD.md")), [])
        self.assertEqual(payload["corpus_count"], len(self._NAMES))
        self.assertEqual(payload["candidate_name"], "synthetic-corpus-candidate")
        for name in self._NAMES:
            self.assertIn(name, markdown)
        # And the committed report is untouched. The absence check above cannot see
        # a handler that called write_leaderboard with its DEFAULT paths, which
        # resolve relative to the process working directory rather than to the
        # temporary tree.
        after = (
            committed_leaderboard.read_bytes()
            if committed_leaderboard.is_file()
            else None
        )
        self.assertEqual(before, after)

    def test_a_record_without_a_name_binding_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._records(root)[0]
            stderr = self._cli_failure(
                (
                    "corpus-baselines",
                    "--record",
                    str(record),
                    "--output-root",
                    str(root / "out" / "baselines"),
                )
            )
        self.assertIn("--record must be NAME=DIRECTORY", stderr)

    def test_an_unversioned_dataset_name_is_refused(self) -> None:
        # `public` is admitted by literal; every other name must carry the D-43
        # version suffix, because the name becomes a filename (T-02-03).
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self._records(root)[0]
            stderr = self._cli_failure(
                (
                    "corpus-baselines",
                    "--record",
                    f"probe={record}",
                    "--output-root",
                    str(root / "out" / "baselines"),
                )
            )
        self.assertIn("version suffix", stderr)

    def test_two_records_naming_one_corpus_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = self._records(root)
            stderr = self._cli_failure(
                (
                    "corpus-baselines",
                    "--record",
                    f"probe.v1={records[0]}",
                    "--record",
                    f"probe.v1={records[1]}",
                    "--output-root",
                    str(root / "out" / "baselines"),
                )
            )
        self.assertIn("must have unique dataset names", stderr)

    def test_two_candidates_in_one_table_are_refused(self) -> None:
        # The D-45 misreading arriving through a different door: rows differing in
        # BOTH the corpus and the configuration can be attributed to neither, which
        # is exactly what a one-candidate-across-corpora table must not contain.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._records(root)[0]
            second = _write_record(
                root / "records" / "other-candidate",
                name="synthetic-other-candidate",
                dataset_sha256="9" * 64,
                sessions=load_sessions(first / SESSIONS_FILENAME),
            )
            stderr = self._cli_failure(
                (
                    "corpus-baselines",
                    "--record",
                    f"public={first}",
                    "--record",
                    f"probe.v1={second}",
                    "--output-root",
                    str(root / "out" / "baselines"),
                )
            )
        self.assertIn("must describe one candidate", stderr)


class DispatchTest(unittest.TestCase):
    """Every declared subcommand has its own handler, and none falls through."""

    _COMMANDS = ("adjudicate", "contrast", "corpus-baselines", "run")

    def test_every_declared_subcommand_is_bound_to_a_handler(self) -> None:
        _parser, handlers = _build_parser()
        self.assertEqual(tuple(sorted(handlers)), self._COMMANDS)

    def test_each_handler_is_a_distinct_function(self) -> None:
        # The regression this pins. Under the two-branch if/else it replaced, every
        # command that was not "run" ran _adjudicate, so a third and fourth
        # subcommand shared one handler and read attributes their Namespace did not
        # carry. Distinctness is exactly what that shape could not provide.
        _parser, handlers = _build_parser()
        handler_functions = {handler for _subparser, handler in handlers.values()}
        self.assertEqual(len(handler_functions), len(handlers))

    def test_each_handler_is_paired_with_its_own_subparser(self) -> None:
        _parser, handlers = _build_parser()
        for command, (subparser, _handler) in sorted(handlers.items()):
            self.assertTrue(
                subparser.prog.endswith(command),
                f"{command} is bound to the subparser {subparser.prog!r}",
            )

    def test_every_bound_command_is_reachable_through_argparse(self) -> None:
        _parser, handlers = _build_parser()
        for command in sorted(handlers):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(SystemExit) as raised:
                    main((command, "--help"))
            self.assertEqual(raised.exception.code, 0, command)

    def test_an_unknown_command_is_rejected_by_argparse(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(("bogus",))
        self.assertNotEqual(raised.exception.code, 0)


def _process_spawns(source: str) -> tuple[str, ...]:
    """Every import of, or attribute access on, a process-spawning module."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] == "subprocess"
            )
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "subprocess":
                found.append(f"line {node.lineno}: from subprocess import ...")
        elif isinstance(node, ast.Attribute):
            value = node.value
            if isinstance(value, ast.Name) and value.id == "subprocess":
                found.append(f"line {node.lineno}: subprocess.{node.attr}")
    return tuple(sorted(found))


class NoProcessSpawnTest(unittest.TestCase):
    """The property the plan's `grep -c subprocess` gate was reaching for.

    That grep cannot be satisfied by a correct file: line 533 of this module
    legitimately says "subprocess" in prose, explaining that the git call it
    describes is patched OUT. A text search cannot tell a comment from a call, so
    the check is made over the AST instead -- which is strictly stronger, and is
    proven below to actually fire.
    """

    def test_this_module_neither_imports_nor_calls_subprocess(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertEqual(_process_spawns(source), ())

    def test_the_scanner_fires_on_a_module_that_does(self) -> None:
        # An unfired scanner is indistinguishable from a clean module, so both
        # spellings are proven to be detected.
        self.assertNotEqual(_process_spawns("import subprocess\n"), ())
        self.assertNotEqual(
            _process_spawns("import subprocess\nsubprocess.run(('git',))\n"),
            (),
        )


if __name__ == "__main__":
    unittest.main()
