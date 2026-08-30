from __future__ import annotations

import json
import unittest
from pathlib import Path

from arena.adjudication import CandidateArm, Verdict, adjudicate
from arena.candidate import CandidateSpec
from arena.leaderboard import (
    HOW_TO_READ,
    LEADERBOARD_SCHEMA_VERSION,
    CandidateEntry,
    build_leaderboard,
    entry_from_record,
    render_markdown,
)
from arena.metrics import SessionOutcome, metric_summary, technical_score
from tests.arena_fixtures import ANCHOR_RECORD_DIR, session, sessions_from_ranks


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_JSON = REPOSITORY_ROOT / "experiments" / "baselines" / "leaderboard.json"
COMMITTED_MARKDOWN = REPOSITORY_ROOT / "experiments" / "LEADERBOARD.md"

# This module's job is payload shape and rendering, never resampling. A production-scale
# adjudication belongs to the operator step that generates the committed report; running
# one here would put a ~60 s job inside a suite whose whole value is a sub-5 s feedback
# loop (T-01-20). Two hundred replicates are ample to produce a well-formed row.
FAST_RESAMPLES = 200


def _spec(name: str) -> CandidateSpec:
    spec = CandidateSpec(
        name=name,
        code_revision="unknown_revision",
        code_revision_dirty=True,
        overrides=(),
        catalog_sha256="unknown",
        dataset_sha256="unknown",
    )
    spec.validate()
    return spec


def _entry(
    name: str,
    sessions: tuple[SessionOutcome, ...],
    *,
    provenance: str = "synthetic unit fixture",
) -> CandidateEntry:
    spec = _spec(name)
    return CandidateEntry(
        name=spec.name,
        fingerprint=spec.fingerprint,
        run_id=name,
        code_revision=spec.code_revision,
        code_revision_dirty=spec.code_revision_dirty,
        overrides=spec.overrides,
        sessions=sessions,
        provenance=provenance,
    )


def _score(sessions: tuple[SessionOutcome, ...]) -> float:
    return technical_score(metric_summary(sessions))


# Ten sessions each, every rank and turn fixed, so each TechnicalScore is a closed-form
# number a reader can check by hand rather than a value the rig asserts against itself.
#   rank 1 / turn 1  -> HR 1.0, MRR 1.0, MTTC 1.0, Eff 1.0 -> TS 1.00
#   rank 2 / turn 2  -> HR 1.0, MRR 0.5, MTTC 2.0, Eff 0.9 -> TS 0.83
#   rank 5 / turn 5  -> HR 1.0, MRR 0.2, MTTC 5.0, Eff 0.6 -> TS 0.68
_PERFECT = sessions_from_ranks((1,) * 10, turn=1)
_MIDDLE = sessions_from_ranks((2,) * 10, turn=2)
_WORST = sessions_from_ranks((5,) * 10, turn=5)

# The HR@10-is-not-the-sort-key pair.
#   wide-recall  : every session hits, but at rank 10 on turn 10 -> HR 1.0, TS 0.55
#   sharp-ranking: two sessions miss, the other eight hit at rank 1 on turn 1
#                                                          -> HR 0.8, TS 0.80
_WIDE_RECALL = sessions_from_ranks((10,) * 10, turn=10)
_SHARP_RANKING = sessions_from_ranks((1,) * 8 + (None,) * 2, turn=1)


def _mixed_bucket_sessions() -> tuple[SessionOutcome, ...]:
    # A boundary bucket of ten at p=0.90 (sigma 0.09486832980505137, the same figure the
    # anchor's boundary row carries) beside a browsing bucket of forty-five, so one
    # bucket falls below the n=40 decision-grade floor and the other clears it.
    boundary = tuple(
        session(
            f"b{index:03d}",
            scenario_type="boundary",
            best_rank=None if index == 9 else 1,
            first_hit_turn=None if index == 9 else 1,
        )
        for index in range(10)
    )
    browsing = tuple(
        session(f"w{index:03d}", scenario_type="browsing", best_rank=1, first_hit_turn=1)
        for index in range(45)
    )
    return boundary + browsing


def _anchor_entry() -> CandidateEntry:
    return entry_from_record(ANCHOR_RECORD_DIR)


class LeaderboardPayloadTest(unittest.TestCase):
    def test_top_level_keys_are_exactly_the_four_tables_plus_metadata(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        self.assertEqual(
            sorted(payload),
            [
                "adjudication",
                "assumptions",
                "baseline_fingerprint",
                "candidates",
                "hit_rate_curve",
                "scenario_breakout",
                "schema_version",
            ],
        )
        self.assertEqual(payload["schema_version"], LEADERBOARD_SCHEMA_VERSION)
        self.assertEqual(LEADERBOARD_SCHEMA_VERSION, 1)

    def test_efficiency_is_rounded_at_output_like_the_evaluator(self) -> None:
        # arena.metrics.efficiency returns 0.7575000000000001 on the anchor because the
        # unrounded term is what reproduces the TechnicalScore. The evaluator rounds the
        # same value to 6 dp for OUTPUT, so the committed payload must read 0.7575
        # exactly. A payload carrying the float tail fails this test (T-01-16c).
        payload = build_leaderboard(
            (_anchor_entry(),), (), baseline_fingerprint=None
        )
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["efficiency"], 0.7575)
        self.assertEqual(repr(candidate["efficiency"]), "0.7575")
        self.assertEqual(candidate["technical_score"], 0.76884)

    def test_scenario_sigma_is_written_unrounded(self) -> None:
        # The opposite rule to efficiency above, and the two must never be harmonised:
        # the per-bucket sigma is an analysis quantity asserted at places=12 elsewhere in
        # this phase, not a figure the evaluator also emits.
        payload = build_leaderboard(
            (_entry("mixed", _mixed_bucket_sessions()),), (), baseline_fingerprint=None
        )
        boundary = payload["scenario_breakout"][0]
        self.assertEqual(boundary["scenario_type"], "boundary")
        self.assertAlmostEqual(
            boundary["binomial_standard_error"], 0.09486832980505137, places=12
        )
        self.assertNotEqual(boundary["binomial_standard_error"], 0.094868)

    def test_decision_grade_is_false_below_forty_samples(self) -> None:
        payload = build_leaderboard(
            (_entry("mixed", _mixed_bucket_sessions()),), (), baseline_fingerprint=None
        )
        grades = {
            row["scenario_type"]: (row["sample_count"], row["decision_grade"])
            for row in payload["scenario_breakout"]
        }
        self.assertEqual(grades["boundary"], (10, False))
        self.assertEqual(grades["browsing"], (45, True))

    def test_hit_rate_curve_keys_are_strings(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        curve = payload["hit_rate_curve"][0]["curve"]
        self.assertEqual(sorted(curve), ["1", "10", "3", "5"])
        self.assertEqual(curve["1"], 1.0)

    def test_assumptions_block_states_the_methodology(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        assumptions = payload["assumptions"]
        self.assertIs(assumptions["per_scenario_holm_corrected"], False)
        self.assertIn("local_evaluator.py:286", assumptions["efficiency_rounding"])
        self.assertIn("D-15", assumptions["per_bucket_sigma_source"])
        self.assertIn("paired-difference", assumptions["winners_curse_sigma_source"])
        self.assertIn("common baseline", assumptions["holm_family"])
        self.assertEqual(assumptions["practical_floor"], 0.01)

    def test_payload_is_json_serializable_with_sorted_keys(self) -> None:
        # No tuple-keyed mapping, no enum and no dataclass instance may survive into the
        # payload; each would raise here rather than at the operator's write step.
        baseline = _entry("base", sessions_from_ranks((2,) * 12))
        candidate = _entry("cand", sessions_from_ranks((1,) + (2,) * 11))
        rows = adjudicate(
            CandidateArm(_spec("base"), baseline.sessions),
            (CandidateArm(_spec("cand"), candidate.sessions),),
            resamples=FAST_RESAMPLES,
        )
        payload = build_leaderboard(
            (baseline, candidate), rows, baseline_fingerprint=baseline.fingerprint
        )
        serialized = json.dumps(payload, sort_keys=True)
        self.assertIn('"verdict"', serialized)
        self.assertEqual(json.loads(serialized)["schema_version"], 1)

    def test_baseline_fingerprint_is_carried_at_the_top_level(self) -> None:
        entry = _entry("solo", _PERFECT)
        payload = build_leaderboard(
            (entry,), (), baseline_fingerprint=entry.fingerprint
        )
        self.assertEqual(payload["baseline_fingerprint"], entry.fingerprint)


class LeaderboardOrderingTest(unittest.TestCase):
    def test_candidates_are_sorted_by_technical_score_descending(self) -> None:
        self.assertEqual((_score(_PERFECT), _score(_MIDDLE), _score(_WORST)),
                         (1.0, 0.83, 0.68))
        # Fed in deliberately scrambled order so a pass cannot come from input order.
        payload = build_leaderboard(
            (
                _entry("worst", _WORST),
                _entry("perfect", _PERFECT),
                _entry("middle", _MIDDLE),
            ),
            (),
            baseline_fingerprint=None,
        )
        self.assertEqual(
            [item["technical_score"] for item in payload["candidates"]],
            [1.0, 0.83, 0.68],
        )
        self.assertEqual(
            [item["name"] for item in payload["candidates"]],
            ["perfect", "middle", "worst"],
        )

    def test_dependent_tables_follow_the_candidate_order(self) -> None:
        payload = build_leaderboard(
            (_entry("worst", _WORST), _entry("perfect", _PERFECT)),
            (),
            baseline_fingerprint=None,
        )
        order = [item["fingerprint"] for item in payload["candidates"]]
        self.assertEqual([item["fingerprint"] for item in payload["hit_rate_curve"]], order)
        # Scenario rows are grouped per entry, sorted() within each entry.
        seen: list[str] = []
        for row in payload["scenario_breakout"]:
            if row["fingerprint"] not in seen:
                seen.append(row["fingerprint"])
        self.assertEqual(seen, order)

    def test_equal_scores_tie_break_on_ascending_fingerprint(self) -> None:
        # Identical sessions, different names -> identical score, different fingerprints.
        first = _entry("alpha", _MIDDLE)
        second = _entry("bravo", _MIDDLE)
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        for order in ((first, second), (second, first)):
            payload = build_leaderboard(order, (), baseline_fingerprint=None)
            scores = [item["technical_score"] for item in payload["candidates"]]
            self.assertEqual(scores[0], scores[1])
            fingerprints = [item["fingerprint"] for item in payload["candidates"]]
            self.assertEqual(fingerprints, sorted(fingerprints))

    def test_highest_hit_rate_is_not_first_when_its_score_is_not(self) -> None:
        # The tripwire for D-14 / T-01-17. experiments/RUNS.md is sorted by HR@10
        # throughout and PROJECT.md names that as actively misleading about the score;
        # this asserts the leaderboard does not repeat it.
        wide = _entry("wide-recall", _WIDE_RECALL)
        sharp = _entry("sharp-ranking", _SHARP_RANKING)
        payload = build_leaderboard((wide, sharp), (), baseline_fingerprint=None)
        candidates = payload["candidates"]
        self.assertEqual(candidates[0]["name"], "sharp-ranking")
        self.assertEqual(candidates[0]["hit_rate_at_10"], 0.8)
        self.assertEqual(candidates[1]["name"], "wide-recall")
        # The entry that IS first on HR@10 is last on the score that decides anything.
        self.assertEqual(candidates[1]["hit_rate_at_10"], 1.0)
        self.assertGreater(
            candidates[1]["hit_rate_at_10"], candidates[0]["hit_rate_at_10"]
        )
        self.assertGreater(
            candidates[0]["technical_score"], candidates[1]["technical_score"]
        )


class LeaderboardMarkdownTest(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        baseline = _entry("base", sessions_from_ranks((2,) * 12))
        candidate = _entry("cand", sessions_from_ranks((1,) + (2,) * 11))
        rows = adjudicate(
            CandidateArm(_spec("base"), baseline.sessions),
            (CandidateArm(_spec("cand"), candidate.sessions),),
            resamples=FAST_RESAMPLES,
        )
        return build_leaderboard(
            (baseline, candidate), rows, baseline_fingerprint=baseline.fingerprint
        )

    def test_render_is_deterministic(self) -> None:
        payload = self._payload()
        self.assertEqual(render_markdown(payload), render_markdown(payload))

    def test_required_headings_are_present(self) -> None:
        rendered = render_markdown(self._payload())
        for heading in (
            "## How to read this report",
            "## Candidates",
            "## HitRate@K curve",
            "## Per-scenario breakout",
            "## Pairwise adjudication",
        ):
            self.assertIn(heading, rendered)

    def test_required_substrings_are_present(self) -> None:
        rendered = render_markdown(self._payload())
        for needed in (
            "0.094868",
            "0.054772",
            "paired-difference",
            "not Holm-corrected",
            "two best-case session flips",
            "local_evaluator.py:286",
            "experiments/baselines/leaderboard.json",
            "experiments/RUNS.md",
        ):
            self.assertIn(needed, rendered)

    def test_the_illustrative_sigma_is_only_ever_named_as_illustrative(self) -> None:
        # 0.086 is MEAS-09's figure from applying the OVERALL p to a bucket n. It may
        # appear once, in the sentence that says so, and never as a printed sigma.
        rendered = render_markdown(self._payload())
        occurrences = [line for line in rendered.splitlines() if "0.086" in line]
        self.assertEqual(len(occurrences), 1)
        self.assertIn("illustrative", occurrences[0])

    def test_all_four_verdicts_are_defined_in_the_how_to_read_block(self) -> None:
        rendered = render_markdown(self._payload())
        start = rendered.index("## How to read this report")
        block = rendered[start : rendered.index("## Candidates")]
        for value in Verdict:
            self.assertIn(value.value, block)
        self.assertEqual(
            sorted(item.value for item in Verdict),
            ["no difference", "not detectable", "significant, below ship bar", "win"],
        )
        self.assertIn(HOW_TO_READ, rendered)

    def test_numeric_separator_columns_are_right_aligned(self) -> None:
        rendered = render_markdown(self._payload())
        separators = [
            line
            for line in rendered.splitlines()
            if line.startswith("| ---") and set(line) <= set("| -:")
        ]
        self.assertEqual(len(separators), 4)
        for line in separators:
            self.assertIn("---:", line)

    def test_the_render_ends_with_exactly_one_newline(self) -> None:
        rendered = render_markdown(self._payload())
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))

    def test_an_empty_adjudication_renders_the_none_fallback(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        rendered = render_markdown(payload)
        adjudication = rendered[rendered.index("## Pairwise adjudication") :]
        self.assertIn("| _none_ |", adjudication)
        self.assertIn("_not set_", rendered)

    def test_the_adjudication_row_prints_its_audit_columns(self) -> None:
        # T-01-13: sigma-hat, k and E[max k] are separate columns so a reader can
        # re-derive corrected dTS rather than trust it.
        rendered = render_markdown(self._payload())
        header = next(
            line for line in rendered.splitlines() if line.startswith("| Candidate | Baseline |")
        )
        for column in ("sigma-hat", "k", "E[max k]", "corrected dTS", "MDD", "verdict"):
            self.assertIn(column, header)
        self.assertNotIn("| _none_ | _none_ |", rendered)

    def test_a_small_probability_never_renders_as_zero(self) -> None:
        # Upstream: a permutation p has a hard Phipson-Smyth floor at 1/(R+1) and can
        # never honestly be 0. At R=10,000 that floor is 9.999e-05, which a flat 6-dp
        # format would print as 0.000000.
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        payload["adjudication"] = [
            {
                "candidate_name": "tiny",
                "candidate_fingerprint": "f" * 64,
                "baseline_fingerprint": "e" * 64,
                "delta": 0.02,
                "ci_lower": 0.01,
                "ci_upper": 0.03,
                "standard_error": 0.005,
                "permutation_p": 1.0 / 10001.0,
                "holm_p": 1.0 / 10001.0,
                "minimum_detectable_difference": 0.014,
                "candidate_count": 1,
                "correction_k": 1,
                "expected_max_of_k": 0.0,
                "corrected_delta": 0.02,
                "clears_practical_floor": True,
                "is_champion": True,
                "hit_rate_delta": 0.0,
                "mrr_delta": 0.0,
                "mttc_delta": 0.0,
                "exchange_rate_ok": True,
                "verdict": "win",
                "failed_criteria": [],
                "resamples": 10000,
            }
        ]
        rendered = render_markdown(payload)
        self.assertIn("9.9990e-05", rendered)
        self.assertNotIn("`0.000000`", rendered)


class CommittedLeaderboardTest(unittest.TestCase):
    """ROADMAP Success Criteria 1, 2 and 4 asserted against the committed artifact.

    Reads JSON and Markdown only, so it costs milliseconds. The 10,000-replicate
    generation that produced these files is an operator command, never a test.
    """

    def setUp(self) -> None:
        self.payload = json.loads(COMMITTED_JSON.read_text(encoding="utf-8"))

    def _anchor(self) -> dict[str, object]:
        return next(
            item
            for item in self.payload["candidates"]
            if item["run_id"] == "anchor-legacy"
        )

    def test_the_committed_payload_reports_the_anchor_aggregates(self) -> None:
        self.assertEqual(self.payload["schema_version"], 1)
        self.assertGreaterEqual(len(self.payload["candidates"]), 1)
        anchor = self._anchor()
        self.assertEqual(
            (
                anchor["hit_rate_at_10"],
                anchor["mrr"],
                anchor["mttc"],
                anchor["efficiency"],
                anchor["technical_score"],
            ),
            (0.92, 0.524466, 3.425, 0.7575, 0.76884),
        )
        self.assertEqual(anchor["sample_count"], 200)

    def test_the_committed_payload_carries_the_anchor_curve(self) -> None:
        anchor = self._anchor()
        curve = next(
            item["curve"]
            for item in self.payload["hit_rate_curve"]
            if item["fingerprint"] == anchor["fingerprint"]
        )
        self.assertEqual(curve, {"1": 0.385, "3": 0.59, "5": 0.715, "10": 0.92})

    def test_the_committed_payload_carries_the_anchor_scenario_breakout(self) -> None:
        anchor = self._anchor()
        rows = [
            item
            for item in self.payload["scenario_breakout"]
            if item["fingerprint"] == anchor["fingerprint"]
        ]
        self.assertEqual(
            [item["scenario_type"] for item in rows],
            ["boundary", "browsing", "buying", "intent_override"],
        )
        self.assertEqual([item["sample_count"] for item in rows], [10, 80, 80, 30])
        self.assertEqual(
            [item["hit_rate_at_10"] for item in rows], [0.9, 0.95, 0.9, 0.9]
        )
        self.assertEqual(
            [item["decision_grade"] for item in rows], [False, True, True, False]
        )
        for row, expected in zip(
            rows,
            (
                0.09486832980505137,
                0.02436698586202242,
                0.03354101966249684,
                0.054772255750516606,
            ),
        ):
            self.assertAlmostEqual(
                row["binomial_standard_error"], expected, places=12
            )

    def test_the_committed_adjudication_was_generated_at_production_scale(self) -> None:
        rows = self.payload["adjudication"]
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(row["resamples"], 10000)
            for field in (
                "minimum_detectable_difference",
                "standard_error",
                "correction_k",
                "expected_max_of_k",
            ):
                self.assertIsNotNone(row[field])
            # The identity plan 01-09 asserts, checked here too so a regression in
            # classify_verdict cannot reach the committed report unnoticed.
            self.assertEqual(row["verdict"] == "win", row["failed_criteria"] == [])
        self.assertIsNotNone(self.payload["baseline_fingerprint"])

    def test_the_committed_markdown_states_its_conventions(self) -> None:
        rendered = COMMITTED_MARKDOWN.read_text(encoding="utf-8")
        for needed in (
            "## How to read this report",
            "## Candidates",
            "## HitRate@K curve",
            "## Per-scenario breakout",
            "## Pairwise adjudication",
            "synthetic-",
            "never hand-edit",
            "experiments/baselines/leaderboard.json",
        ):
            self.assertIn(needed, rendered)
        for value in Verdict:
            self.assertIn(value.value, rendered)

    def test_the_committed_markdown_matches_the_committed_payload(self) -> None:
        # D-12 and T-01-16: the Markdown is a generated view. A hand-edit or a drifted
        # renderer shows up here rather than in a judge's reading of a stale report.
        self.assertEqual(
            COMMITTED_MARKDOWN.read_text(encoding="utf-8"),
            render_markdown(self.payload),
        )

    def test_the_synthetic_control_is_labelled_as_a_fixture(self) -> None:
        # T-01-16b: a validation control must never be mistaken for a measured result.
        synthetic = [
            item
            for item in self.payload["candidates"]
            if item["name"].startswith("synthetic-")
        ]
        self.assertEqual(len(synthetic), 1)
        self.assertIn("fixture", synthetic[0]["provenance"])
        self.assertIn("promote_hits_to_rank_one", synthetic[0]["provenance"])


if __name__ == "__main__":
    unittest.main()
