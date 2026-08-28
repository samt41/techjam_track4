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
    TraceEvent,
    TraceEventType,
    TraceReason,
)
from starter.shopping_agent.models import Attribute, RetrievalRoute
from tests.fixtures import sample_products, write_catalog


def route_event(reason: TraceReason = TraceReason.STRICT_RESULTS) -> TraceEvent:
    return TraceEvent(
        session_id="s1",
        turn=1,
        event_type=TraceEventType.ROUTE,
        reason=reason,
        route=RetrievalRoute.EXACT_FTS,
        attribute=Attribute.CATEGORY,
        candidate_count=10,
        recommendation_count=0,
        intent_version=1,
        elapsed_ms=0.0,
    )


class EvaluationTraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_noop_trace_does_not_create_files(self) -> None:
        NoOpEvaluationTrace().record(route_event())

        self.assertEqual(list(self.root.iterdir()), [])

    def test_jsonl_trace_uses_fixed_reason_fields(self) -> None:
        trace_path = self.root / "trace.jsonl"
        trace = JsonlEvaluationTrace(trace_path)

        trace.record(route_event(reason=TraceReason.EMPTY_STRICT_POOL))

        payload = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(payload["reason"], "empty_strict_pool")
        self.assertEqual(payload["event_type"], "route")
        self.assertEqual(payload["route"], "exact_fts")
        self.assertEqual(payload["product_ids"], [])
        self.assertEqual(
            set(payload),
            {
                "session_id",
                "turn",
                "event_type",
                "reason",
                "route",
                "attribute",
                "candidate_count",
                "recommendation_count",
                "intent_version",
                "elapsed_ms",
                "product_ids",
            },
        )

    def test_public_experiment_writes_exactly_five_artifacts_and_refuses_overwrite(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())
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

    def test_agent_emits_required_turn_event_types(self) -> None:
        catalog_path = write_catalog(self.root, sample_products())
        trace_path = self.root / "turn.jsonl"
        agent = Agent(catalog_path, trace=JsonlEvaluationTrace(trace_path))
        self.addCleanup(agent.close)
        agent.reset("trace-session", {"summary": "test"})

        response = agent.respond("trace-session", "I need boots", 1, 10)

        events = tuple(
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
        )
        event_types = {event["event_type"] for event in events}
        self.assertTrue(
            {"route", "filtering", "question", "slate", "latency"}
            <= event_types
        )
        slate = next(event for event in events if event["event_type"] == "slate")
        self.assertEqual(
            slate["product_ids"],
            [item["parent_asin"] for item in response["recommendations"]],
        )


if __name__ == "__main__":
    unittest.main()
