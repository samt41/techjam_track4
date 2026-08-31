from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arena.import_legacy_results import SESSION_FIELDS, import_legacy_results


def _session(
    sample_id: str,
    *,
    scenario_type: str = "buying",
    best_rank: int | None = None,
    first_hit_turn: int | None = None,
) -> dict[str, object]:
    # Carries every harness field plus one analysis-added key, so the projection
    # has something to drop.
    return {
        "sample_id": sample_id,
        "scenario_type": scenario_type,
        "hit": first_hit_turn is not None,
        "first_hit_turn": first_hit_turn,
        "best_rank": best_rank,
        "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
        "first_miss_reason": None if first_hit_turn is not None else "no_candidate",
    }


def _payload(
    *,
    sample_count: int = 2,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    # Shaped after the committed anchor-legacy record: a legacy results.json carries
    # the aggregates and the sessions and no provenance at all. Nothing in this
    # module reads or writes that record -- every assertion is over a temporary tree.
    payload: dict[str, object] = {
        "sample_count": sample_count,
        "hit_rate_at_10": 0.5,
        "mrr": 0.375,
        "mttc": 3.0,
        "efficiency": 0.8,
        "recommended_technical_score": 0.5225,
        "scenario_metrics": {
            "buying": {
                "sample_count": 1,
                "hit_rate_at_10": 1.0,
                "mrr": 0.75,
                "mttc": 2.0,
            },
        },
        "reported_token_usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "sessions": [
            _session("s000", best_rank=2, first_hit_turn=2),
            _session("s001", scenario_type="browsing"),
        ],
    }
    if extra is not None:
        payload.update(extra)
    return payload


class LegacyImportTest(unittest.TestCase):
    def _results(self, root: Path, payload: dict[str, object]) -> Path:
        path = root / "results.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_an_existing_destination_is_refused(self) -> None:
        # CR-03 inverted: the pre-fix writer replaced this file without a word.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = self._results(root, _payload())
            destination = root / "baselines" / "run-a"
            destination.mkdir(parents=True)
            sentinel = destination / "summary.json"
            sentinel.write_text("sentinel", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                import_legacy_results(results, destination, provenance="unit test")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "sentinel")

    def test_a_successful_import_writes_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = self._results(root, _payload())
            destination = root / "baselines" / "rescued"
            sessions_path, summary_path = import_legacy_results(
                results,
                destination,
                provenance="unit test",
            )
            self.assertEqual(sessions_path.parent, destination)
            self.assertEqual(summary_path.parent, destination)
            self.assertTrue(sessions_path.exists())
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertFalse(summary["provenance_complete"])
        self.assertEqual(summary["code_revision"], "unknown_revision")
        self.assertEqual(summary["catalog_sha256"], "unknown")
        self.assertEqual(summary["dataset_sha256"], "unknown")
        self.assertEqual(summary["provenance"], "unit test")
        self.assertEqual(summary["run_id"], "rescued")
        self.assertRegex(summary["source_sha256"], r"^[0-9a-f]{64}$")

    def test_a_failed_import_leaves_no_partial_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = self._results(root, _payload(sample_count=5))
            parent = root / "baselines"
            parent.mkdir()
            destination = parent / "rescued"
            with self.assertRaises(ValueError):
                import_legacy_results(results, destination, provenance="unit test")
            self.assertFalse(destination.exists())
            # The second half is the part that proves the staging directory was
            # cleaned up rather than merely left unpublished.
            self.assertEqual(
                [item.name for item in parent.iterdir() if item.name.startswith(".")],
                [],
            )

    def test_the_staging_directory_is_removed_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = self._results(root, _payload())
            destination = root / "baselines" / "rescued"
            import_legacy_results(results, destination, provenance="unit test")
            self.assertEqual(
                [item.name for item in destination.parent.iterdir()],
                ["rescued"],
            )

    def test_provenance_collision_is_still_refused(self) -> None:
        # Pins the pre-existing _build_summary guard against being lost in the
        # rewrite of the write half.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = self._results(
                root,
                _payload(extra={"code_revision": "deadbeef"}),
            )
            destination = root / "baselines" / "rescued"
            with self.assertRaises(ValueError):
                import_legacy_results(results, destination, provenance="unit test")
            self.assertFalse(destination.exists())

    def test_session_rows_are_projected_to_the_harness_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = self._results(root, _payload())
            destination = root / "baselines" / "rescued"
            sessions_path, _ = import_legacy_results(
                results,
                destination,
                provenance="unit test",
            )
            rows = [
                json.loads(line)
                for line in sessions_path.read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(set(row), set(SESSION_FIELDS))


if __name__ == "__main__":
    unittest.main()
