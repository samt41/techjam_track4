from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena.arena import _SampleMappingAgent, build_candidate_spec, run_candidate
from arena.candidate import CandidateSpec
from arena.metrics import SessionOutcome
from arena.run_arena import main
from arena.store import SESSIONS_FILENAME, SUMMARY_FILENAME, load_sessions
from starter.shopping_agent.search_backend import LexicalMode


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


if __name__ == "__main__":
    unittest.main()
