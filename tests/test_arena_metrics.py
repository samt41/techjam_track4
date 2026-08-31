from __future__ import annotations

import json
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena.metrics import (
    MAX_TURNS,
    MetricSummary,
    SessionOutcome,
    binomial_standard_error,
    efficiency,
    hit_rate_curve,
    metric_summary,
    scenario_breakout,
    technical_score,
)
from arena.store import (
    ArenaStoreError,
    load_sessions,
    publish,
    resolve_run_directory,
    sha256_file,
    validate_run_id,
    write_json,
    write_sessions,
)
from tests.arena_fixtures import (
    ANCHOR_RECORD_DIR,
    load_anchor_sessions,
    promote_hits_to_rank_one,
    session,
    sessions_from_ranks,
)


ANCHOR_SUMMARY = MetricSummary(
    sample_count=200,
    hit_rate_at_10=0.92,
    mrr=0.524466,
    mttc=3.425,
)


class MetricChainTest(unittest.TestCase):
    def test_technical_score_reproduces_the_anchor_score(self) -> None:
        # Every input here is a 6-dp-rounded value and the output is rounded to 6 dp,
        # so exact equality is correct.
        self.assertEqual(technical_score(ANCHOR_SUMMARY), 0.76884)

    def test_efficiency_is_returned_unrounded(self) -> None:
        # efficiency() deliberately returns the unrounded value, mirroring
        # local_evaluator.py:279-280 where the unrounded number feeds the score and is
        # rounded only at output (:286). An exact == 0.7575 assertion here is a
        # guaranteed false failure -- the actual float is 0.7575000000000001.
        value = efficiency(ANCHOR_SUMMARY)
        self.assertAlmostEqual(value, 0.7575, places=12)
        self.assertEqual(round(value, 6), 0.7575)

    def test_missed_session_contributes_max_turns_plus_one_to_mttc(self) -> None:
        outcomes = (
            session("s000", best_rank=2, first_hit_turn=3),
            session("s001"),
        )
        # mean(3, 11) == 7.0 -- the miss is charged MAX_TURNS + 1, not dropped.
        self.assertEqual(metric_summary(outcomes).mttc, 7.0)
        self.assertEqual(MAX_TURNS + 1, 11)

    def test_metric_summary_rejects_an_empty_session_set(self) -> None:
        # The evaluator returns mttc=None here; the arena fails closed instead.
        with self.assertRaises(ValueError):
            metric_summary(())

    def test_technical_score_is_not_the_mean_of_per_session_scores(self) -> None:
        # D-17: the bootstrap must RECOMPUTE the statistic on each resample rather
        # than average per-session scores. This set proves the two paths differ.
        #
        # The divergence is driven by TechnicalScore's 6 dp output rounding, not by a
        # large structural non-linearity: efficiency's clamp cannot bind, because mttc
        # is confined to [1, 11] by construction, so the score is otherwise affine in
        # the three component means. The gap is therefore small (~7e-7) but real and
        # fully deterministic -- and it is exactly the gap an averaging shortcut would
        # silently introduce into every bootstrap replicate.
        outcomes = sessions_from_ranks((2, 3, 9))
        mean_of_per_session = statistics.fmean(
            technical_score(metric_summary((item,))) for item in outcomes
        )
        recomputed = technical_score(metric_summary(outcomes))
        self.assertNotEqual(mean_of_per_session, recomputed)

    def test_session_outcome_validation_rejects_out_of_range_values(self) -> None:
        base = dict(
            sample_id="s000",
            scenario_type="buying",
            hit=True,
            first_hit_turn=2,
            best_rank=2,
            reciprocal_rank=0.5,
        )
        for invalid in (
            {"best_rank": 0},
            {"best_rank": 11},
            {"reciprocal_rank": 1.5},
            {"first_hit_turn": None},
            {"sample_id": ""},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    SessionOutcome(**{**base, **invalid}).validate()

    def test_session_outcome_validation_rejects_incoherent_metric_rows(self) -> None:
        base = dict(
            sample_id="s000",
            scenario_type="buying",
            hit=True,
            first_hit_turn=2,
            best_rank=2,
            reciprocal_rank=0.5,
        )
        for invalid in (
            {"hit": False},
            {"hit": "true"},
            {"first_hit_turn": None},
            {"best_rank": None},
            {"best_rank": True},
            {"first_hit_turn": 2.5},
            {"reciprocal_rank": 1.0},
            {"reciprocal_rank": "0.5"},
            {"scenario_type": ""},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    SessionOutcome(**{**base, **invalid}).validate()

    def test_miss_fields_must_be_coherent(self) -> None:
        SessionOutcome(
            sample_id="s000",
            scenario_type="buying",
            hit=False,
            first_hit_turn=None,
            best_rank=None,
            reciprocal_rank=0.0,
        ).validate()
        for invalid in (
            {"best_rank": 1},
            {"first_hit_turn": 1},
            {"reciprocal_rank": 0.1},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    SessionOutcome(
                        **{
                            "sample_id": "s000",
                            "scenario_type": "buying",
                            "hit": False,
                            "first_hit_turn": None,
                            "best_rank": None,
                            "reciprocal_rank": 0.0,
                            **invalid,
                        }
                    ).validate()

    def test_binomial_standard_error_uses_the_bucket_p_and_n(self) -> None:
        self.assertAlmostEqual(
            binomial_standard_error(0.9, 10), 0.09486832980505137, places=12
        )
        self.assertAlmostEqual(
            binomial_standard_error(0.9, 30), 0.054772255750516606, places=12
        )
        self.assertAlmostEqual(
            binomial_standard_error(0.92, 200), 0.01918332609325088, places=12
        )

    def test_binomial_standard_error_rejects_an_empty_bucket(self) -> None:
        with self.assertRaises(ValueError):
            binomial_standard_error(0.9, 0)


class HitRateCurveTest(unittest.TestCase):
    def test_curve_matches_the_anchor(self) -> None:
        # These four are exact quotients of small integers by 200 and ARE exactly
        # representable, so exact equality is correct here.
        self.assertEqual(
            hit_rate_curve(load_anchor_sessions()),
            {1: 0.385, 3: 0.59, 5: 0.715, 10: 0.92},
        )

    def test_curve_counts_match_the_anchor(self) -> None:
        sessions = load_anchor_sessions()
        self.assertEqual(len(sessions), 200)
        counts = {
            depth: sum(
                1
                for item in sessions
                if item.best_rank is not None and item.best_rank <= depth
            )
            for depth in (1, 3, 5, 10)
        }
        self.assertEqual(counts, {1: 77, 3: 118, 5: 143, 10: 184})

    def test_curve_is_monotone_non_decreasing(self) -> None:
        curve = hit_rate_curve(load_anchor_sessions())
        values = list(curve.values())
        self.assertEqual(values, sorted(values))

    def test_curve_at_ten_equals_the_headline_hit_rate(self) -> None:
        # A free internal-consistency check: the curve and the headline metric are
        # computed from different fields (best_rank vs hit) and must still agree.
        sessions = load_anchor_sessions()
        self.assertEqual(
            hit_rate_curve(sessions)[10], metric_summary(sessions).hit_rate_at_10
        )


class ScenarioBreakoutTest(unittest.TestCase):
    def test_breakout_rows_are_sorted_and_complete(self) -> None:
        rows = scenario_breakout(load_anchor_sessions())
        self.assertEqual(
            tuple(row.scenario_type for row in rows),
            ("boundary", "browsing", "buying", "intent_override"),
        )
        self.assertEqual(
            tuple(row.summary.sample_count for row in rows), (10, 80, 80, 30)
        )
        self.assertEqual(
            tuple(row.summary.hit_rate_at_10 for row in rows), (0.9, 0.95, 0.9, 0.9)
        )

    def test_per_scenario_mrr_and_mttc_match_the_evaluator(self) -> None:
        # MEAS-03: per-scenario MRR and MTTC recovered from the committed record.
        # These are the evaluator's own 6-dp-rounded outputs, so exact equality holds.
        rows = scenario_breakout(load_anchor_sessions())
        self.assertEqual(
            tuple(row.summary.mrr for row in rows),
            (0.404444, 0.527862, 0.464296, 0.715873),
        )
        self.assertEqual(
            tuple(row.summary.mttc for row in rows), (3.6, 3.125, 3.2875, 4.533333)
        )

    def test_per_scenario_sigma_and_decision_grade(self) -> None:
        # MEAS-09 / D-15: each row carries its own n and its own sigma computed from
        # that bucket's OWN observed p. The n=10 and n=30 buckets are flagged not
        # decision-grade.
        rows = scenario_breakout(load_anchor_sessions())
        expected = (
            0.09486832980505137,
            0.02436698586202242,
            0.03354101966249684,
            0.054772255750516606,
        )
        for row, sigma in zip(rows, expected):
            with self.subTest(scenario=row.scenario_type):
                self.assertAlmostEqual(row.binomial_standard_error, sigma, places=12)
        self.assertEqual(
            tuple(row.decision_grade for row in rows), (False, True, True, False)
        )


class AnchorReproductionTest(unittest.TestCase):
    """The MEAS-16 gate: the arena reproduces run A from the committed rows alone."""

    def test_anchor_aggregates(self) -> None:
        summary = metric_summary(load_anchor_sessions())
        self.assertEqual(summary.sample_count, 200)
        self.assertEqual(summary.hit_rate_at_10, 0.92)
        self.assertEqual(summary.mrr, 0.524466)
        self.assertEqual(summary.mttc, 3.425)
        self.assertEqual(technical_score(summary), 0.76884)
        # Compared to places=12 because it is deliberately returned unrounded.
        self.assertAlmostEqual(efficiency(summary), 0.7575, places=12)

    def test_runs_md_four_decimal_values_after_rounding(self) -> None:
        # experiments/RUNS.md records MRR 0.5245 and TechnicalScore 0.7688. That pair
        # is NOT self-consistent read as exact: 0.5*0.92 + 0.3*0.5245 + 0.2*0.7575 is
        # 0.76885, which displays as 0.7689. So agreement is asserted only after
        # explicitly rounding the full-precision values; an exact-equality assertion
        # against the 4 dp figures would be a guaranteed false failure.
        summary = metric_summary(load_anchor_sessions())
        self.assertEqual(round(summary.mrr, 4), 0.5245)
        self.assertEqual(round(technical_score(summary), 4), 0.7688)

    def test_recomputed_aggregates_agree_with_committed_summary(self) -> None:
        # D-06: a second, independent code path agreeing on the same six figures is
        # the validation evidence. The committed file was produced from the harness
        # output; these numbers were recomputed here from the session rows alone.
        committed = json.loads(
            (ANCHOR_RECORD_DIR / "summary.json").read_text(encoding="utf-8")
        )
        summary = metric_summary(load_anchor_sessions())
        self.assertEqual(summary.sample_count, committed["sample_count"])
        self.assertEqual(summary.hit_rate_at_10, committed["hit_rate_at_10"])
        self.assertEqual(summary.mrr, committed["mrr"])
        self.assertEqual(summary.mttc, committed["mttc"])
        self.assertEqual(
            technical_score(summary), committed["recommended_technical_score"]
        )
        # The file carries the evaluator's OUTPUT-rounded efficiency
        # (local_evaluator.py:286), so the comparison rounds to 6 dp first.
        self.assertEqual(round(efficiency(summary), 6), committed["efficiency"])

    def test_committed_per_scenario_metrics_agree(self) -> None:
        committed = json.loads(
            (ANCHOR_RECORD_DIR / "summary.json").read_text(encoding="utf-8")
        )["scenario_metrics"]
        for row in scenario_breakout(load_anchor_sessions()):
            with self.subTest(scenario=row.scenario_type):
                self.assertEqual(
                    row.summary.as_record(), committed[row.scenario_type]
                )

    def test_promotion_control_delta_at_ten(self) -> None:
        # The deterministic synthetic large-effect control. The delta is a difference
        # of two independently 6-dp-rounded scores, so residual binary float error is
        # guaranteed: the actual value is 0.011931000000000025. An exact-equality
        # assertion is forbidden.
        sessions = load_anchor_sessions()
        baseline = technical_score(metric_summary(sessions))
        promoted = technical_score(
            metric_summary(promote_hits_to_rank_one(sessions, 10))
        )
        self.assertAlmostEqual(promoted - baseline, 0.011931, places=9)

    def test_promotion_control_delta_at_seventy_seven(self) -> None:
        # Actual value 0.08521400000000001 -- see the note above on why places=9.
        sessions = load_anchor_sessions()
        baseline = technical_score(metric_summary(sessions))
        promoted = technical_score(
            metric_summary(promote_hits_to_rank_one(sessions, 77))
        )
        self.assertAlmostEqual(promoted - baseline, 0.085214, places=9)

    def test_promotion_leaves_hit_rate_and_mttc_invariant(self) -> None:
        # Promoting a hit to rank 1 changes neither hit nor first_hit_turn, so the
        # control moves MRR alone. That is what makes its answer analytically known.
        sessions = load_anchor_sessions()
        baseline = metric_summary(sessions)
        for count in (1, 10, 77, 107):
            with self.subTest(count=count):
                promoted = metric_summary(promote_hits_to_rank_one(sessions, count))
                self.assertEqual(promoted.hit_rate_at_10, baseline.hit_rate_at_10)
                self.assertEqual(promoted.mttc, baseline.mttc)

    def test_promotion_delta_equals_three_tenths_of_mrr_delta(self) -> None:
        # places=5 rather than exact: TechnicalScore is rounded to 6 dp on both sides
        # of the subtraction.
        sessions = load_anchor_sessions()
        baseline = metric_summary(sessions)
        for count in (10, 77):
            with self.subTest(count=count):
                promoted = metric_summary(promote_hits_to_rank_one(sessions, count))
                self.assertAlmostEqual(
                    technical_score(promoted) - technical_score(baseline),
                    0.30 * (promoted.mrr - baseline.mrr),
                    places=5,
                )

    def test_promotion_beyond_available_sessions_raises(self) -> None:
        with self.assertRaises(ValueError):
            promote_hits_to_rank_one(load_anchor_sessions(), 10_000)


class StoreTest(unittest.TestCase):
    def test_validate_run_id_accepts_a_plain_id(self) -> None:
        self.assertEqual(validate_run_id("run-a"), "run-a")

    def test_validate_run_id_rejects_traversal_and_absolute_forms(self) -> None:
        for invalid in ("../escape", "/abs", "a:b", ""):
            with self.subTest(run_id=invalid):
                with self.assertRaises(ValueError):
                    validate_run_id(invalid)

    def test_resolve_run_directory_contains_the_run(self) -> None:
        root = Path("experiments/baselines")
        resolved = resolve_run_directory(root, "run-a")
        self.assertTrue(resolved.is_relative_to(root.resolve()))

    def test_resolve_run_directory_rejects_an_escaping_id(self) -> None:
        # Defence in depth (T-01-06): with the allow-list widened, the resolved-path
        # containment check must still refuse an id that leaves the output root.
        import re

        with patch("arena.store._RUN_ID_RE", re.compile(r"^.*$")):
            with self.assertRaises(ArenaStoreError):
                resolve_run_directory(Path("experiments/baselines"), "../escape")

    def test_session_round_trip(self) -> None:
        rows = (
            session("s000", best_rank=3, first_hit_turn=2),
            session("s001", scenario_type="browsing"),
            session("s002", scenario_type="boundary", best_rank=1, first_hit_turn=1),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.jsonl"
            write_sessions(path, rows)
            self.assertEqual(load_sessions(path), rows)

    def test_missing_field_raises_and_names_file_and_line(self) -> None:
        row = {
            "sample_id": "s000",
            "scenario_type": "buying",
            "hit": True,
            "first_hit_turn": 2,
            "best_rank": 3,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(ArenaStoreError) as caught:
                load_sessions(path)
        message = str(caught.exception)
        self.assertIn("sessions.jsonl", message)
        self.assertIn("line 1", message)

    def test_invalid_row_raises_at_the_boundary(self) -> None:
        row = {
            "sample_id": "s000",
            "scenario_type": "buying",
            "hit": True,
            "first_hit_turn": 2,
            "best_rank": 11,
            "reciprocal_rank": 0.1,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(ArenaStoreError):
                load_sessions(path)

    def test_write_json_is_canonical(self) -> None:
        payload = {"b": 2, "a": 1}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            write_json(path, payload)
            text = path.read_text(encoding="utf-8")
        self.assertEqual(text, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        self.assertTrue(text.endswith("}\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_sha256_file_matches_the_immutable_evaluator_digest(self) -> None:
        # Also a standing check that the immutable scoring harness is unmodified.
        self.assertEqual(
            sha256_file(Path("evaluator/local_evaluator.py")),
            "84ea899707452de249ca62abee77c4b40ab7a3139b5cc798ac30c9f521f91b30",
        )


class PublishFailureTest(unittest.TestCase):
    def test_a_non_directory_oserror_does_not_delete_the_destination(self) -> None:
        # The exact scenario in which the pre-fix handler called shutil.rmtree on
        # whatever sat at destination (T-01-28): the replace failed for a reason
        # that has nothing to do with a stale corpse.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            working = root / "working"
            working.mkdir()
            destination = root / "committed-record"
            destination.write_text("committed", encoding="utf-8")
            with patch("arena.store.os.replace", side_effect=OSError("denied")):
                with self.assertRaises(ArenaStoreError) as caught:
                    publish(working, destination)
            self.assertTrue(destination.exists())
            self.assertEqual(destination.read_text(encoding="utf-8"), "committed")
        self.assertIsInstance(caught.exception.__cause__, OSError)

    def test_a_stale_destination_is_cleared_and_the_publish_retried(self) -> None:
        # run_candidate's crashed-corpse recovery. Only the outcome is asserted:
        # POSIX replaces an empty directory outright while Windows raises and takes
        # the clear-and-retry arm, and pinning either would pin a platform.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            working = root / "working"
            working.mkdir()
            (working / "fresh.txt").write_text("fresh", encoding="utf-8")
            destination = root / "record"
            destination.mkdir()
            (destination / "stale.txt").write_text("stale", encoding="utf-8")
            publish(working, destination)
            self.assertEqual(
                sorted(item.name for item in destination.iterdir()),
                ["fresh.txt"],
            )

    def test_a_failed_retry_reports_the_destination_and_preserves_the_cause(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            working = root / "working"
            working.mkdir()
            destination = root / "record"
            destination.mkdir()
            with patch("arena.store.os.replace", side_effect=OSError("denied")):
                with self.assertRaises(ArenaStoreError) as caught:
                    publish(working, destination)
            self.assertIn(str(destination), str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, OSError)


if __name__ == "__main__":
    unittest.main()
