from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.run_public import run_experiment
from starter.agent import Agent
from starter.shopping_agent.diagnostics import (
    JsonlEvaluationTrace,
    NoOpEvaluationTrace,
    RetrievalTrace,
    RuntimeTrace,
)
from starter.shopping_agent.models import RetrievalRoute
from starter.shopping_agent.search_backend import SearchReason, TotalRelation
from tests.fixtures import build_test_artifacts, sample_products


REQUIRED_EVENT_TYPES = {
    "interpretation",
    "retrieval",
    "constraint",
    "belief",
    "question",
    "slate",
    "runtime",
}


def traced_agent_turn(root: Path, message: str) -> tuple[dict, ...]:
    catalog_path, _ = build_test_artifacts(root, sample_products())
    trace_path = root / "turn.jsonl"
    agent = Agent(catalog_path, trace=JsonlEvaluationTrace(trace_path))
    try:
        agent.reset("trace-session", {"summary": "test"})
        agent.respond("trace-session", message, 1, 10)
    finally:
        agent.close()
    return tuple(
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    )


class TraceEventTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_noop_trace_does_not_create_files(self) -> None:
        NoOpEvaluationTrace().record(RuntimeTrace(
            session_id="s1",
            turn=1,
            startup_ms=0.0,
            turn_ms=0.0,
            peak_python_bytes=0,
            rss_bytes=None,
            rss_reason="rss_unavailable",
            catalog_sha256="abc",
            database_sha256="def",
            catalog_size_bytes=1,
            database_size_bytes=1,
        ))

        self.assertEqual(list(self.root.iterdir()), [])

    def test_trace_explains_complete_turn_without_arbitrary_payloads(self) -> None:
        events = traced_agent_turn(self.root, "I need black boots")

        self.assertEqual(
            {event["event_type"] for event in events},
            REQUIRED_EVENT_TYPES,
        )
        self.assertTrue(all("payload" not in event for event in events))
        self.assertTrue(all(event["session_id"] == "trace-session" for event in events))
        self.assertTrue(all(event["turn"] == 1 for event in events))

    def test_retrieval_trace_serializes_fixed_fields(self) -> None:
        trace_path = self.root / "retrieval.jsonl"
        trace = JsonlEvaluationTrace(trace_path)

        trace.record(RetrievalTrace(
            session_id="s1",
            turn=1,
            intent_version=1,
            route=RetrievalRoute.EXACT_FTS,
            terms=("winter", "boot"),
            filter_constraint_ids=("t1:material:equals:leather:include:1",),
            total_matches=5,
            total_relation=TotalRelation.EXACT,
            returned_matches=5,
            work_consumed=10,
            elapsed_ms=1.5,
            reason=SearchReason.COMPLETED,
        ))

        payload = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(payload["event_type"], "retrieval")
        self.assertEqual(payload["route"], "exact_fts")
        self.assertEqual(payload["reason"], "completed")
        self.assertEqual(payload["terms"], ["winter", "boot"])
        self.assertNotIn("payload", payload)

    def test_fallback_reason_is_visible_in_retrieval_traces(self) -> None:
        from starter.shopping_agent.search_backend import LexicalMode

        catalog_path, artifact_path = build_test_artifacts(self.root, sample_products())
        trace_path = self.root / "fallback.jsonl"
        agent = Agent(
            catalog_path,
            artifact_path=artifact_path,
            lexical_mode=LexicalMode.FALLBACK,
            trace=JsonlEvaluationTrace(trace_path),
        )
        self.addCleanup(agent.close)
        agent.reset("fallback", {"summary": "test"})

        agent.respond("fallback", "winter boots", 1, 10)

        events = tuple(
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
        )
        retrieval_reasons = {
            event["reason"]
            for event in events
            if event["event_type"] == "retrieval"
        }
        self.assertIn("fallback_completed", retrieval_reasons)

    def test_public_experiment_writes_exactly_five_artifacts_and_refuses_overwrite(self) -> None:
        catalog_path, _ = build_test_artifacts(self.root, sample_products())
        dataset_path = self.root / "public.jsonl"
        dataset_path.write_text(json.dumps({
            "sample_id": "sample-1",
            "scenario_type": "buying",
            "user_profile": {"summary": "test"},
            "ground_truth": {"parent_asin": "BOOT-1"},
        }) + "\n", encoding="utf-8")
        output_root = self.root / "experiments"

        run_directory = run_experiment(
            run_id="test-run",
            catalog_path=catalog_path,
            dataset_path=dataset_path,
            output_root=output_root,
        )

        self.assertEqual(
            {path.name for path in run_directory.iterdir()},
            {
                "summary.json",
                "sessions.jsonl",
                "failures.jsonl",
                "retrieval_routes.jsonl",
                "ablation.md",
            },
        )
        summary = json.loads(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["hit_rate_at_10"], 1.0)
        self.assertTrue(
            (run_directory / "retrieval_routes.jsonl").read_text(encoding="utf-8")
        )
        with self.assertRaises(FileExistsError):
            run_experiment(
                run_id="test-run",
                catalog_path=catalog_path,
                dataset_path=dataset_path,
                output_root=output_root,
            )


if __name__ == "__main__":
    unittest.main()
