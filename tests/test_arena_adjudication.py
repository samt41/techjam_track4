from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import arena.statistics
from arena.adjudication import (
    CRITERION_ORDER,
    EXCHANGE_RATE_PER_MTTC,
    PRACTICAL_FLOOR,
    AdjudicationRow,
    CandidateArm,
    Verdict,
    adjudicate,
    classify_verdict,
)
from arena.candidate import CandidateSpec
from arena.statistics import expected_max_of_k, holm_bonferroni, pair_seed
from tests.arena_fixtures import (
    load_anchor_sessions,
    promote_hits_to_rank_one,
    sessions_from_ranks,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


# Resample budget for this module. FAST_RESAMPLES covers every structural and win-rule
# test: those assert control flow over small synthetic session sets, and none of them
# depends on the precision of the bootstrap SE. STABLE_RESAMPLES covers the two places
# where an assertion DOES depend on that estimate -- the floor-ordering test below and
# the Layer-3 anchor controls.
#
# 500 is not merely convenient. At R=500 the SE estimate carries roughly 1/sqrt(2R) ~
# 3.2% relative noise, comfortably inside the margins each of those fixtures is
# constructed to hold (the floor fixture's corrected delta sits 44% below the floor;
# the m=10 anchor control's headroom over its MDD is ~13%).
#
# RESAMPLE_COUNT stays at 10,000 for every production path and no test here passes it.
FAST_RESAMPLES = 200
STABLE_RESAMPLES = 500


def arm(
    name: str,
    sessions: tuple[object, ...],
    *,
    overrides: tuple[tuple[str, str], ...] = (),
) -> CandidateArm:
    # A distinct `name` per arm is what makes the fingerprints differ, which is what
    # makes the seeds differ; every other field is held fixed so nothing else can.
    return CandidateArm(
        spec=CandidateSpec(
            name=name,
            code_revision="0" * 40,
            code_revision_dirty=False,
            overrides=overrides,
            catalog_sha256="a" * 64,
            dataset_sha256="b" * 64,
        ),
        sessions=sessions,  # type: ignore[arg-type]
    )


# Twelve sessions at rank 2, one of them promoted to rank 1. The effect is concentrated
# in a SINGLE session, so the bootstrap SE is roughly the size of the delta itself and
# the winner's-curse correction at k=2 removes 56% of it: delta 0.0125 clears the 0.01
# floor, corrected delta ~0.0056 does not.
_FLOOR_BASELINE = sessions_from_ranks((2,) * 12)
_FLOOR_CANDIDATE = sessions_from_ranks((1,) + (2,) * 11)

# Fifty sessions at rank 3, thirty promoted to rank 1: a large effect spread widely
# enough to be strongly significant. HR@10 and MTTC are invariant under a rank promotion.
_WIN_BASELINE = sessions_from_ranks((3,) * 50)
_WIN_CANDIDATE = sessions_from_ranks((1,) * 30 + (3,) * 20)

# A hundred sessions at rank 4, twenty-four nudged to rank 3. Deliberately calibrated to
# delta = +0.006: a real, strongly detected gain that is still too small to ship.
_SMALL_BASELINE = sessions_from_ranks((4,) * 100)
_SMALL_CANDIDATE = sessions_from_ranks((3,) * 24 + (4,) * 76)

# A hundred sessions at rank 2. Each candidate drops two of them to a miss (HR@10
# regression, MTTC penalty) while promoting some others to rank 1 to buy MRR back.
_TRADE_BASELINE = sessions_from_ranks((2,) * 100)
# +0.010 MRR against 0.0667 * 0.180 = 0.012006 -- the trade does NOT clear.
_TRADE_UNDERPAID = sessions_from_ranks((None, None) + (1,) * 4 + (2,) * 94)
# +0.030 MRR against the same 0.012006 -- the trade clears.
_TRADE_PAID = sessions_from_ranks((None, None) + (1,) * 8 + (2,) * 90)

# Two hundred sessions at rank 4, exactly one moved to rank 3: delta 0.000125 against an
# MDD of ~0.00036, so the null here is uninformative rather than evidence of equivalence.
_NEAR_NULL_BASELINE = sessions_from_ranks((4,) * 200)
_NEAR_NULL_CANDIDATE = sessions_from_ranks((3,) + (4,) * 199)


class OrderingTest(unittest.TestCase):
    def test_floor_is_applied_to_the_corrected_delta(self) -> None:
        # The single ordering error D-20 exists to prevent. This test fails outright if
        # `clears_practical_floor` is computed from the raw delta.
        rows = adjudicate(
            arm("baseline", _FLOOR_BASELINE),
            (
                arm("promoted", _FLOOR_CANDIDATE),
                arm("null", _FLOOR_BASELINE),
            ),
            resamples=STABLE_RESAMPLES,
        )
        row = rows[0]
        self.assertGreaterEqual(row.delta, PRACTICAL_FLOOR)
        self.assertLess(row.corrected_delta, PRACTICAL_FLOOR)
        # At least 20% of clear air below the floor, so the ~3.2% SE noise at
        # STABLE_RESAMPLES cannot flip the assertion.
        self.assertLess(row.corrected_delta, 0.8 * PRACTICAL_FLOOR)
        self.assertIs(row.clears_practical_floor, False)
        self.assertIn("practical_floor", row.failed_criteria)

    def test_correction_k_equals_the_non_baseline_candidate_count(self) -> None:
        rows = adjudicate(
            arm("baseline", _FLOOR_BASELINE),
            (
                arm("one", _FLOOR_CANDIDATE),
                arm("two", sessions_from_ranks((1, 1) + (2,) * 10)),
                arm("three", sessions_from_ranks((1, 1, 1) + (2,) * 9)),
            ),
            resamples=FAST_RESAMPLES,
        )
        self.assertEqual(len(rows), 3)
        for row in rows:
            # The baseline's delta against itself is not a selection option, so k counts
            # the non-baseline candidates only.
            self.assertEqual(row.candidate_count, 3)
            self.assertEqual(row.correction_k, 3)
            self.assertEqual(row.expected_max_of_k, expected_max_of_k(3))

    def test_single_candidate_receives_no_correction(self) -> None:
        rows = adjudicate(
            arm("baseline", _FLOOR_BASELINE),
            (arm("only", _FLOOR_CANDIDATE),),
            resamples=FAST_RESAMPLES,
        )
        row = rows[0]
        self.assertEqual(row.correction_k, 1)
        # No selection happened, so there is no selection bias to remove.
        self.assertEqual(row.expected_max_of_k, 0.0)
        self.assertEqual(row.corrected_delta, row.delta)

    def test_champion_is_the_maximum_delta_row(self) -> None:
        rows = adjudicate(
            arm("baseline", _FLOOR_BASELINE),
            (
                arm("one", _FLOOR_CANDIDATE),
                arm("three", sessions_from_ranks((1, 1, 1) + (2,) * 9)),
                arm("two", sessions_from_ranks((1, 1) + (2,) * 10)),
            ),
            resamples=FAST_RESAMPLES,
        )
        champions = [row for row in rows if row.is_champion]
        self.assertEqual(len(champions), 1)
        self.assertEqual(champions[0].candidate_name, "three")
        self.assertEqual(champions[0].delta, max(row.delta for row in rows))

        # Two arms built from the SAME sessions have an exactly equal delta, so the
        # champion can only be resolved by the stable content tie-break.
        tied = adjudicate(
            arm("baseline", _FLOOR_BASELINE),
            (
                arm("alpha", _FLOOR_CANDIDATE),
                arm("omega", _FLOOR_CANDIDATE),
            ),
            resamples=FAST_RESAMPLES,
        )
        self.assertEqual(tied[0].delta, tied[1].delta)
        expected = min(row.candidate_fingerprint for row in tied)
        winner = [row for row in tied if row.is_champion]
        self.assertEqual(len(winner), 1)
        self.assertEqual(winner[0].candidate_fingerprint, expected)

    def test_holm_family_excludes_scenarios(self) -> None:
        # The family is exactly the candidates against the common baseline (D-19).
        # Per-scenario numbers are descriptive and are never Holm-corrected.
        rows = adjudicate(
            arm("baseline", _FLOOR_BASELINE),
            (
                arm("one", _FLOOR_CANDIDATE),
                arm("two", sessions_from_ranks((1, 1) + (2,) * 10)),
                arm("three", sessions_from_ranks((1, 1, 1) + (2,) * 9)),
            ),
            resamples=FAST_RESAMPLES,
        )
        adjusted = holm_bonferroni(tuple(row.permutation_p for row in rows))
        self.assertEqual(len(adjusted), len(rows))
        for row, expected in zip(rows, adjusted):
            self.assertEqual(row.holm_p, expected)


class WinRuleTest(unittest.TestCase):
    def test_win_requires_all_three_criteria(self) -> None:
        row = adjudicate(
            arm("baseline", _WIN_BASELINE),
            (arm("strong", _WIN_CANDIDATE),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertLess(row.holm_p, 0.05)
        self.assertIs(row.clears_practical_floor, True)
        self.assertIs(row.exchange_rate_ok, True)
        self.assertEqual(row.failed_criteria, ())
        self.assertIs(row.verdict, Verdict.WIN)

    def test_significant_but_below_floor_is_below_ship_bar(self) -> None:
        row = adjudicate(
            arm("baseline", _SMALL_BASELINE),
            (arm("small", _SMALL_CANDIDATE),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertLess(row.holm_p, 0.05)
        self.assertIs(row.clears_practical_floor, False)
        self.assertEqual(row.failed_criteria, ("practical_floor",))
        self.assertIs(row.verdict, Verdict.BELOW_SHIP_BAR)
        # A detected +0.006 gain reported as "no difference" would be precisely the
        # dishonest summary this phase exists to prevent.
        self.assertIsNot(row.verdict, Verdict.NO_DIFFERENCE)

    def test_hr10_regression_without_exchange_rate_clearance_is_not_a_win(self) -> None:
        row = adjudicate(
            arm("baseline", _TRADE_BASELINE),
            (arm("underpaid", _TRADE_UNDERPAID),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertLess(row.hit_rate_delta, 0.0)
        self.assertGreater(row.mrr_delta, 0.0)
        self.assertLessEqual(row.mrr_delta, EXCHANGE_RATE_PER_MTTC * row.mttc_delta)
        self.assertIs(row.exchange_rate_ok, False)
        self.assertIn("hr10_exchange_rate", row.failed_criteria)
        self.assertIsNot(row.verdict, Verdict.WIN)

    def test_hr10_regression_with_exchange_rate_clearance_passes_that_criterion(
        self,
    ) -> None:
        row = adjudicate(
            arm("baseline", _TRADE_BASELINE),
            (arm("paid", _TRADE_PAID),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertLess(row.hit_rate_delta, 0.0)
        self.assertGreater(row.mrr_delta, EXCHANGE_RATE_PER_MTTC * row.mttc_delta)
        self.assertIs(row.exchange_rate_ok, True)
        self.assertNotIn("hr10_exchange_rate", row.failed_criteria)

    def test_failed_criteria_order_is_fixed(self) -> None:
        row = adjudicate(
            arm("baseline", _TRADE_BASELINE),
            (arm("underpaid", _TRADE_UNDERPAID),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertGreaterEqual(len(row.failed_criteria), 2)
        # The tuple is CRITERION_ORDER filtered to the failures -- never the order the
        # checks happened to run in.
        self.assertEqual(
            row.failed_criteria,
            tuple(name for name in CRITERION_ORDER if name in set(row.failed_criteria)),
        )


class VerdictRuleTest(unittest.TestCase):
    """The four clauses of the verdict rule, on injected values.

    Every branch is reached deterministically and in microseconds, including the one
    that cannot be built from session data at realistic family sizes.
    """

    def test_empty_failed_criteria_is_a_win(self) -> None:
        self.assertIs(
            classify_verdict(
                holm_p=0.001,
                delta=0.05,
                minimum_detectable_difference=0.01,
                failed_criteria=(),
            ),
            Verdict.WIN,
        )

    def test_significant_with_a_failed_criterion_is_below_ship_bar(self) -> None:
        self.assertIs(
            classify_verdict(
                holm_p=0.001,
                delta=0.006,
                minimum_detectable_difference=0.002,
                failed_criteria=("practical_floor",),
            ),
            Verdict.BELOW_SHIP_BAR,
        )

    def test_underpowered_null_is_not_detectable(self) -> None:
        self.assertIs(
            classify_verdict(
                holm_p=0.40,
                delta=0.001,
                minimum_detectable_difference=0.01,
                failed_criteria=("holm_significance", "practical_floor"),
            ),
            Verdict.NOT_DETECTABLE,
        )

    def test_powered_null_is_no_difference(self) -> None:
        # Rare by construction: abs(delta) >= MDD is roughly a 2.8-sigma effect whose
        # two-sided permutation p is near 0.005, so reaching this clause non-degenerately
        # needs a Holm family large enough to inflate that past 0.05. Injecting the
        # values is deliberate -- attempting to construct a session-level fixture for
        # this branch would be attempting to construct something that essentially cannot
        # occur at realistic family sizes, and would stall execution.
        self.assertIs(
            classify_verdict(
                holm_p=0.20,
                delta=0.05,
                minimum_detectable_difference=0.01,
                failed_criteria=("holm_significance",),
            ),
            Verdict.NO_DIFFERENCE,
        )

    def test_win_is_exactly_equivalent_to_empty_failed_criteria(self) -> None:
        # The identity plan 01-09 asserts against the committed leaderboard.
        for holm_p in (0.0, 0.001, 0.049, 0.05, 0.5, 1.0):
            for delta in (-0.05, 0.0, 0.006, 0.05):
                for detectable in (0.0, 0.002, 0.01):
                    for failed in ((), ("practical_floor",), CRITERION_ORDER):
                        verdict = classify_verdict(
                            holm_p=holm_p,
                            delta=delta,
                            minimum_detectable_difference=detectable,
                            failed_criteria=failed,
                        )
                        self.assertEqual(verdict is Verdict.WIN, failed == ())


class DegenerateTest(unittest.TestCase):
    def test_identical_candidates_are_no_difference_never_a_win(self) -> None:
        row = adjudicate(
            arm("baseline", _WIN_BASELINE),
            (arm("clone", _WIN_BASELINE),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertEqual(row.delta, 0.0)
        self.assertEqual((row.ci_lower, row.ci_upper), (0.0, 0.0))
        self.assertEqual(row.standard_error, 0.0)
        self.assertEqual(row.minimum_detectable_difference, 0.0)
        self.assertEqual(row.permutation_p, 1.0)
        self.assertEqual(row.holm_p, 1.0)
        self.assertIs(row.clears_practical_floor, False)
        self.assertIs(row.exchange_rate_ok, True)
        self.assertEqual(row.failed_criteria, ("holm_significance", "practical_floor"))
        self.assertIs(row.verdict, Verdict.NO_DIFFERENCE)
        # Without the zero-variance guard, `abs(delta) >= mdd` reads 0 >= 0 as True and
        # the rig reports a detectable difference between a candidate and itself.
        self.assertIsNot(row.verdict, Verdict.WIN)

    def test_mdd_is_reported_on_every_row(self) -> None:
        rows = adjudicate(
            arm("baseline", _FLOOR_BASELINE),
            (
                arm("promoted", _FLOOR_CANDIDATE),
                arm("clone", _FLOOR_BASELINE),
                arm("two", sessions_from_ranks((1, 1) + (2,) * 10)),
            ),
            resamples=FAST_RESAMPLES,
        )
        for row in rows:
            self.assertIsInstance(row, AdjudicationRow)
            # D-22 and MEAS-06 in one assertion: the MDD sits on EVERY row, null ones
            # included, and is exactly the statistics module's own function of the SE.
            self.assertEqual(
                row.minimum_detectable_difference,
                arena.statistics.minimum_detectable_difference(row.standard_error),
            )
            self.assertAlmostEqual(
                row.minimum_detectable_difference,
                2.801585218112968 * row.standard_error,
                places=12,
            )

    def test_not_detectable_is_reachable_end_to_end(self) -> None:
        row = adjudicate(
            arm("baseline", _NEAR_NULL_BASELINE),
            (arm("near-null", _NEAR_NULL_CANDIDATE),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertGreater(row.standard_error, 0.0)
        self.assertLess(abs(row.delta), row.minimum_detectable_difference)
        self.assertIs(row.verdict, Verdict.NOT_DETECTABLE)


class Layer3ControlTest(unittest.TestCase):
    """D-01 Layer 3 adjudication controls, on synthetic arms with known answers.

    Every arm here is derived from the committed anchor record, so the class needs no
    evaluation run. Comparison discipline for the two synthetic-control deltas: the
    delta subtracts two independently 6-dp-rounded TechnicalScores, so residual binary
    float error is guaranteed -- the computed values are 0.011931000000000025 (m=10) and
    0.08521400000000001 (m=77). An exact equality assertion on either is a guaranteed
    false failure. The literals are correct; only the comparison operator is at issue.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.anchor = load_anchor_sessions()

    def test_guaranteed_true_positive(self) -> None:
        # Adjudicated as a SINGLE candidate, so k=1 and no winner's-curse subtraction
        # applies. This synthetic control replaces a real evaluation run as the
        # true-positive check: its answer is analytically known, whereas a real run's
        # true effect is not, which makes it a strictly stronger control.
        row = adjudicate(
            arm("baseline", self.anchor),
            (arm("promote-10", promote_hits_to_rank_one(self.anchor, 10)),),
            resamples=STABLE_RESAMPLES,
        )[0]
        self.assertAlmostEqual(row.delta, 0.011931, places=9)
        self.assertLess(row.holm_p, 0.05)
        self.assertEqual(row.corrected_delta, row.delta)
        self.assertIs(row.clears_practical_floor, True)
        self.assertIs(row.exchange_rate_ok, True)
        self.assertEqual(row.failed_criteria, ())
        self.assertIs(row.verdict, Verdict.WIN)
        self.assertGreater(row.delta, row.minimum_detectable_difference)

    def test_true_positive_at_larger_effect(self) -> None:
        row = adjudicate(
            arm("baseline", self.anchor),
            (arm("promote-77", promote_hits_to_rank_one(self.anchor, 77)),),
            resamples=STABLE_RESAMPLES,
        )[0]
        self.assertAlmostEqual(row.delta, 0.085214, places=9)
        self.assertIs(row.verdict, Verdict.WIN)

    def test_guaranteed_true_negative(self) -> None:
        # A rig that has only ever been shown a real effect cannot be trusted to say
        # "no", and saying that honestly is the entire point of MEAS-06.
        row = adjudicate(
            arm("baseline", self.anchor),
            (arm("clone", self.anchor),),
            resamples=STABLE_RESAMPLES,
        )[0]
        self.assertIs(row.verdict, Verdict.NO_DIFFERENCE)
        self.assertEqual(row.permutation_p, 1.0)
        self.assertEqual(row.minimum_detectable_difference, 0.0)

    def test_near_null_reports_a_legible_mdd(self) -> None:
        # Exactly one session moved from rank 4 to rank 3: delta 0.000125 at n=200.
        moved = tuple(
            dataclasses.replace(item, best_rank=3, reciprocal_rank=1.0 / 3.0)
            if index == self._first_rank_four_index()
            else item
            for index, item in enumerate(self.anchor)
        )
        row = adjudicate(
            arm("baseline", self.anchor),
            (arm("near-null", moved),),
            resamples=STABLE_RESAMPLES,
        )[0]
        self.assertIsNot(row.verdict, Verdict.WIN)
        self.assertGreater(row.minimum_detectable_difference, 0.0)
        # The null is correctly reported as uninformative rather than as evidence of
        # equivalence.
        self.assertGreater(row.minimum_detectable_difference, abs(row.delta))

    def _first_rank_four_index(self) -> int:
        for index, item in enumerate(self.anchor):
            if item.best_rank == 4:
                return index
        raise AssertionError("the anchor record has no rank-4 session to move")


# The child prints one serialized adjudication of a small fixed fixture. The resample
# count is interpolated EXPLICITLY so the child cannot fall back to the 10,000 default
# and blow this module's time budget.
_ADJUDICATION_PROGRAM = (
    "import json;"
    "from arena.adjudication import CandidateArm, adjudicate;"
    "from arena.candidate import CandidateSpec;"
    "from tests.arena_fixtures import sessions_from_ranks;"
    "spec=lambda name: CandidateSpec(name=name, code_revision='0'*40,"
    " code_revision_dirty=False, overrides=(), catalog_sha256='a'*64,"
    " dataset_sha256='b'*64);"
    "baseline=CandidateArm(spec=spec('baseline'), sessions=sessions_from_ranks((2,)*12));"
    "candidate=CandidateArm(spec=spec('promoted'),"
    " sessions=sessions_from_ranks((1,)+(2,)*11));"
    f"rows=adjudicate(baseline, (candidate,), resamples={FAST_RESAMPLES});"
    "print(json.dumps([row.as_record() for row in rows], sort_keys=True))"
)


def _adjudication_in_child(hash_seed: str) -> str:
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        (sys.executable, "-c", _ADJUDICATION_PROGRAM),
        capture_output=True,
        text=True,
        check=True,
        cwd=str(_REPOSITORY_ROOT),
        env=environment,
    )
    return result.stdout.strip()


class ReproducibilityTest(unittest.TestCase):
    """D-24: the same inputs must adjudicate byte-identically, in two processes."""

    def _serialized(self, rows: tuple[AdjudicationRow, ...]) -> str:
        return json.dumps([row.as_record() for row in rows], sort_keys=True)

    def test_two_adjudications_serialize_identically(self) -> None:
        baseline = arm("baseline", _FLOOR_BASELINE)
        candidate = arm("promoted", _FLOOR_CANDIDATE)
        first = adjudicate(baseline, (candidate,), resamples=FAST_RESAMPLES)
        second = adjudicate(baseline, (candidate,), resamples=FAST_RESAMPLES)
        self.assertEqual(self._serialized(first), self._serialized(second))

    def test_reproducible_across_processes(self) -> None:
        # Seeds derive from the candidate fingerprints, never from the clock, so two
        # interpreters started with different hash seeds must still agree byte for byte.
        first = _adjudication_in_child("0")
        second = _adjudication_in_child("1")
        # Guard against a vacuous pass: two empty stdouts are also byte-identical.
        self.assertIn('"verdict"', first)
        self.assertEqual(first, second)

    def test_argument_order_is_fixed_not_symmetric(self) -> None:
        baseline = arm("baseline", _FLOOR_BASELINE)
        candidate = arm("promoted", _FLOOR_CANDIDATE)
        self.assertNotEqual(
            pair_seed(
                baseline.spec.fingerprint, candidate.spec.fingerprint, "bootstrap"
            ),
            pair_seed(
                candidate.spec.fingerprint, baseline.spec.fingerprint, "bootstrap"
            ),
        )
        forward = adjudicate(baseline, (candidate,), resamples=FAST_RESAMPLES)[0]
        reverse = adjudicate(candidate, (baseline,), resamples=FAST_RESAMPLES)[0]
        # The statistic itself is order-antisymmetric...
        self.assertEqual(reverse.delta, -forward.delta)
        # ...but the replicate stream is not a mirror of the forward one, because the
        # seed is not symmetric in its two arguments. The property under test is
        # reproducibility, never order invariance.
        self.assertNotEqual(reverse.standard_error, forward.standard_error)


if __name__ == "__main__":
    unittest.main()
