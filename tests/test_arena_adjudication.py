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
from arena.metrics import SessionOutcome
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

# A hundred sessions at rank 3 reached on turn 8. HR@10 1.00, MRR 0.333333, MTTC 8.00.
# The eight turns of MTTC headroom are what make an MTTC IMPROVEMENT expressible at all:
# every pre-existing _TRADE_* fixture adds misses without pulling anything forward, so
# all of them have mttc_delta > 0 and none of them can reach the sign-inverted half of
# the D-23 branch.
_MTTC_TRADE_BASELINE = sessions_from_ranks((3,) * 100, turn=8)

# 01-VERIFICATION.md's executed CR-02 reproducer, reconstructed to its measured values:
# hit_rate_delta -0.03, mrr_delta -0.01, mttc_delta -4.11. Three sessions become misses
# (HR@10 and MRR both regress) and sixty survivors are pulled forward to turn 1, so the
# candidate is worse on BOTH headline retrieval metrics while looking four turns faster.
_MTTC_TRADE_DOUBLE_REGRESSION = tuple(
    dataclasses.replace(
        item,
        hit=False,
        best_rank=None,
        first_hit_turn=None,
        reciprocal_rank=0.0,
    )
    if index < 3
    else dataclasses.replace(
        item,
        first_hit_turn=1 if index < 63 else item.first_hit_turn,
    )
    for index, item in enumerate(_MTTC_TRADE_BASELINE)
)


def _traded(promoted: int, pulled_forward: int) -> tuple[SessionOutcome, ...]:
    """One miss bought back with `promoted` rank-1 lifts and `pulled_forward` turn-1 hits.

    Built with dataclasses.replace OVER _MTTC_TRADE_BASELINE rather than from a fresh
    sessions_from_ranks call: a fresh call restarts the s000 numbering, and
    _require_paired would then refuse the comparison.
    """
    traded: list[SessionOutcome] = []
    for index, item in enumerate(_MTTC_TRADE_BASELINE):
        if index == 0:
            # Session 0 is always the miss, so every candidate from this factory carries
            # the same -0.01 HR@10 regression and the same 11-turn MTTC penalty on it.
            traded.append(
                dataclasses.replace(
                    item,
                    hit=False,
                    best_rank=None,
                    first_hit_turn=None,
                    reciprocal_rank=0.0,
                )
            )
            continue
        best_rank = 1 if index <= promoted else item.best_rank
        traded.append(
            dataclasses.replace(
                item,
                best_rank=best_rank,
                reciprocal_rank=1.0 / best_rank,
                first_hit_turn=1 if index <= pulled_forward else item.first_hit_turn,
            )
        )
    return tuple(traded)


# Five sessions pulled to turn 1 give mttc_delta -0.32, so the magnitude bar sits at
# 0.0667 * 0.32 = 0.021344 for both fixtures below. Only the MRR side differs.
#
# Two rank-1 lifts: mrr_delta +0.010000, BELOW the bar -- so the trade is underpaid and
# the HR@10 regression is not forgiven. This is the fixture that proves abs() is
# load-bearing: without it the bar is -0.021344 and a +0.010000 gain sails over it.
_MTTC_TRADE_UNDERPAID_GAIN = _traded(promoted=2, pulled_forward=5)
# Six rank-1 lifts: mrr_delta +0.036667, ABOVE the same bar -- the mirror, confirming
# the criterion still forgives a genuinely paid-for trade rather than having been
# switched off in the other direction.
_MTTC_TRADE_PAID_GAIN = _traded(promoted=6, pulled_forward=5)

# 01-VERIFICATION.md's executed CR-01 reproducer. A uniform rank-2 -> rank-1 promotion:
# HR@10 and MTTC are invariant under a rank move, so delta is exactly 0.30 * 0.5 = 0.15
# up to TechnicalScore's 6-dp rounding, and the bootstrap SE is exactly 0.0 because the
# delta does not depend on WHICH sessions are resampled. Zero SE on a real +0.15 effect
# is the whole point: SE alone never meant "degenerate".
_UNIFORM_BASELINE = sessions_from_ranks((2,) * 200)
_UNIFORM_PROMOTED = sessions_from_ranks((1,) * 200)

# The same zero-SE-on-a-real-effect shape at fifty sessions, so it can be adjudicated in
# one family alongside _WIN_CANDIDATE and a clone of the baseline.
_WIN_UNIFORM_PROMOTED = sessions_from_ranks((1,) * 50)


class OrderingTest(unittest.TestCase):
    def test_empty_candidate_tuple_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as raised:
            adjudicate(arm("baseline", _FLOOR_BASELINE), (), resamples=FAST_RESAMPLES)
        self.assertIn("at least one candidate", str(raised.exception))

    def test_candidate_matching_baseline_fingerprint_is_rejected(self) -> None:
        baseline = arm("baseline", _FLOOR_BASELINE)
        with self.assertRaises(ValueError) as raised:
            adjudicate(
                baseline,
                (CandidateArm(baseline.spec, _FLOOR_CANDIDATE),),
                resamples=FAST_RESAMPLES,
            )
        self.assertIn("baseline", str(raised.exception))

    def test_duplicate_candidate_fingerprints_are_rejected(self) -> None:
        baseline = arm("baseline", _FLOOR_BASELINE)
        candidate = arm("candidate", _FLOOR_CANDIDATE)
        with self.assertRaises(ValueError) as raised:
            adjudicate(
                baseline,
                (candidate, candidate),
                resamples=FAST_RESAMPLES,
            )
        self.assertIn("unique", str(raised.exception))

    def test_compared_arms_must_share_catalog_and_dataset_digests(self) -> None:
        baseline = arm("baseline", _FLOOR_BASELINE)
        candidate = arm("candidate", _FLOOR_CANDIDATE)
        for digest_field in ("catalog_sha256", "dataset_sha256"):
            with self.subTest(digest_field=digest_field):
                mismatched = CandidateArm(
                    dataclasses.replace(candidate.spec, **{digest_field: "c" * 64}),
                    candidate.sessions,
                )
                with self.assertRaises(ValueError) as raised:
                    adjudicate(
                        baseline,
                        (mismatched,),
                        resamples=FAST_RESAMPLES,
                    )
                self.assertIn(digest_field, str(raised.exception))

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


class ExchangeRateSignTest(unittest.TestCase):
    """D-23 in the direction Phase 3 actually moves: an MTTC IMPROVEMENT, mttc_delta < 0.

    mttc_delta = candidate_mttc - baseline_mttc, so getting faster makes it negative and
    the un-absoluted `EXCHANGE_RATE_PER_MTTC * mttc_delta` bar drops below zero. Every
    pre-existing exchange-rate fixture has mttc_delta > 0, which is why this half of the
    branch had no coverage and shipped vacuous.
    """

    def test_double_regression_with_an_mttc_gain_is_not_a_win(self) -> None:
        # 01-VERIFICATION.md's executed CR-02 reproducer, inverted into a test. Against
        # the checked-in pre-fix code this exact input was adjudicated `verdict = win`
        # with `failed_criteria = ()`, while regressing BOTH headline retrieval metrics.
        row = adjudicate(
            arm("baseline", _MTTC_TRADE_BASELINE),
            (arm("double-regression", _MTTC_TRADE_DOUBLE_REGRESSION),),
            resamples=FAST_RESAMPLES,
        )[0]
        # Non-vacuity first: a mis-calibrated fixture must not be able to pass this test
        # by failing the criterion for some unrelated reason.
        self.assertAlmostEqual(row.hit_rate_delta, -0.03, places=6)
        self.assertAlmostEqual(row.mrr_delta, -0.01, places=6)
        self.assertAlmostEqual(row.mttc_delta, -4.11, places=6)
        self.assertIs(row.exchange_rate_ok, False)
        self.assertIn("hr10_exchange_rate", row.failed_criteria)
        self.assertIsNot(row.verdict, Verdict.WIN)

    def test_an_mrr_gain_below_the_magnitude_bar_does_not_buy_an_hr10_regression(
        self,
    ) -> None:
        # The SOLE mutation guard for `abs(` -- verified by executing that mutation,
        # which fails this test and no other. This candidate's mrr_delta is genuinely
        # POSITIVE, so the `mrr_delta > 0.0` clause cannot rescue the assertion: the only
        # thing standing between +0.010000 and a forgiven HR@10 regression is comparing
        # against the MAGNITUDE of a -0.32 MTTC movement rather than its signed value.
        # The double-regression test above does NOT cover this mutation: its mrr_delta is
        # -0.01, which fails the magnitude comparison whether or not abs() is present.
        row = adjudicate(
            arm("baseline", _MTTC_TRADE_BASELINE),
            (arm("underpaid-gain", _MTTC_TRADE_UNDERPAID_GAIN),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertLess(row.hit_rate_delta, 0.0)
        self.assertLess(row.mttc_delta, 0.0)
        self.assertGreater(row.mrr_delta, 0.0)
        self.assertLess(row.mrr_delta, EXCHANGE_RATE_PER_MTTC * abs(row.mttc_delta))
        self.assertIs(row.exchange_rate_ok, False)
        self.assertIn("hr10_exchange_rate", row.failed_criteria)

    def test_an_mrr_gain_above_the_magnitude_bar_does_buy_an_hr10_regression(
        self,
    ) -> None:
        # The mirror. D-23 was repaired, not disabled: a trade that actually pays the
        # magnitude-scaled price is still forgiven.
        row = adjudicate(
            arm("baseline", _MTTC_TRADE_BASELINE),
            (arm("paid-gain", _MTTC_TRADE_PAID_GAIN),),
            resamples=FAST_RESAMPLES,
        )[0]
        self.assertLess(row.hit_rate_delta, 0.0)
        self.assertLess(row.mttc_delta, 0.0)
        self.assertGreater(row.mrr_delta, 0.0)
        self.assertGreater(row.mrr_delta, EXCHANGE_RATE_PER_MTTC * abs(row.mttc_delta))
        self.assertIs(row.exchange_rate_ok, True)
        self.assertNotIn("hr10_exchange_rate", row.failed_criteria)


class ZeroVarianceTest(unittest.TestCase):
    """A zero bootstrap SE is not the same fact as a zero delta, and only one is degenerate."""

    def test_uniform_improvement_is_not_reported_as_no_difference(self) -> None:
        # 01-VERIFICATION.md's executed CR-01 reproducer, inverted into a test. Against
        # the pre-fix code this +0.15 delta -- fifteen times the ship floor -- was
        # reported `no difference`, on a permutation_p asserted as 1.0 rather than
        # measured, beside a `clears_practical_floor = False` that contradicted the
        # `corrected_delta = 0.15` printed on the same row.
        row = adjudicate(
            arm("base", _UNIFORM_BASELINE),
            (arm("promoted", _UNIFORM_PROMOTED),),
            resamples=STABLE_RESAMPLES,
        )[0]
        self.assertAlmostEqual(row.delta, 0.15, places=9)
        self.assertEqual(row.standard_error, 0.0)
        # Zero SE, non-zero delta: real, and never degenerate.
        self.assertIs(row.is_degenerate, False)
        # Every sign flip that moves any session changes the statistic, so the count of
        # at-least-as-extreme resamples is zero and the measured p lands exactly on the
        # Phipson-Smyth floor.
        self.assertEqual(row.permutation_p, 1.0 / (STABLE_RESAMPLES + 1))
        self.assertIs(row.clears_practical_floor, True)
        self.assertEqual(row.failed_criteria, ())
        self.assertIs(row.verdict, Verdict.WIN)
        self.assertIsNot(row.verdict, Verdict.NO_DIFFERENCE)

    def test_identical_arms_remain_no_difference_on_measured_statistics(self) -> None:
        # The truth-8 REGRESSION GUARD, not a re-derivation: the answer is unchanged,
        # but every value below is now produced by the general path instead of being
        # asserted by a branch. Deleting that branch must not have moved any of them.
        row = adjudicate(
            arm("base", _WIN_BASELINE),
            (arm("clone", _WIN_BASELINE),),
            resamples=STABLE_RESAMPLES,
        )[0]
        self.assertIs(row.is_degenerate, True)
        self.assertEqual(row.delta, 0.0)
        self.assertEqual(row.standard_error, 0.0)
        self.assertEqual(row.permutation_p, 1.0)
        self.assertEqual(row.holm_p, 1.0)
        self.assertEqual(row.minimum_detectable_difference, 0.0)
        self.assertEqual(row.corrected_delta, 0.0)
        self.assertIs(row.clears_practical_floor, False)
        self.assertIs(row.exchange_rate_ok, True)
        self.assertEqual(row.failed_criteria, ("holm_significance", "practical_floor"))
        self.assertIs(row.verdict, Verdict.NO_DIFFERENCE)
        self.assertIsNot(row.verdict, Verdict.WIN)

    def test_degenerate_arms_stay_in_the_holm_family_and_correction_k(self) -> None:
        # Pins the WR-05 decision. The family and k are properties of the experimental
        # DESIGN, so dropping an arm after seeing that it turned out degenerate would be
        # a data-dependent family definition. Concretely, it would take k from 2 to 1,
        # expected_max_of_k(1) is 0.0, and the D-20 floor-ordering tripwire would then
        # pass on the raw delta.
        rows = adjudicate(
            arm("base", _WIN_BASELINE),
            (
                arm("strong", _WIN_CANDIDATE),
                arm("clone", _WIN_BASELINE),
            ),
            resamples=STABLE_RESAMPLES,
        )
        self.assertEqual(len(rows), 2)
        self.assertIs(rows[0].is_degenerate, False)
        self.assertIs(rows[1].is_degenerate, True)
        for row in rows:
            self.assertEqual(row.candidate_count, 2)
            self.assertEqual(row.correction_k, 2)
            self.assertEqual(row.expected_max_of_k, expected_max_of_k(2))
        # The degenerate arm's 1.0 is a MEASURED member of the family, so Holm over the
        # rows' own permutation_p column must reproduce the rows' own holm_p column.
        adjusted = holm_bonferroni(tuple(row.permutation_p for row in rows))
        for row, expected in zip(rows, adjusted):
            self.assertEqual(row.holm_p, expected)

    def test_no_row_field_is_a_fabricated_constant(self) -> None:
        # Three shapes in one family: a real effect, an exactly-uniform effect (zero SE,
        # non-zero delta) and an identical arm (zero SE, zero delta). Each identity below
        # re-derives a printed column from other printed columns on the SAME row. Before
        # this plan the degenerate row failed the third one, printing
        # clears_practical_floor = False beside a corrected_delta of 0.15.
        rows = adjudicate(
            arm("base", _WIN_BASELINE),
            (
                arm("strong", _WIN_CANDIDATE),
                arm("uniform", _WIN_UNIFORM_PROMOTED),
                arm("clone", _WIN_BASELINE),
            ),
            resamples=FAST_RESAMPLES,
        )
        self.assertEqual(len(rows), 3)
        # Non-vacuity: the family really does contain a degenerate arm.
        self.assertTrue(any(row.is_degenerate for row in rows))
        self.assertTrue(any(not row.is_degenerate for row in rows))
        for row in rows:
            self.assertEqual(
                row.minimum_detectable_difference,
                arena.statistics.minimum_detectable_difference(row.standard_error),
            )
            self.assertAlmostEqual(
                row.corrected_delta,
                row.delta - row.standard_error * row.expected_max_of_k,
                places=12,
            )
            self.assertEqual(
                row.clears_practical_floor,
                row.corrected_delta >= PRACTICAL_FLOOR,
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


class CrossCorpusRefusalTest(unittest.TestCase):
    """D-45: adjudicate refuses two arms measured against different corpora.

    This refusal path was UNREACHABLE in Phase 1, because only one corpus existed and
    every retained record therefore carried the same `dataset_sha256`. Phase 2 mints four
    distinct corpus digests (D-58: `public`, `expanded_dev.v1`, `expanded_confirm.v1` and
    `probe.v1`), so the branch becomes reachable for the first time and gets its first
    test here. The pre-existing digest test above sweeps both digest fields structurally;
    this one is the D-45 case specifically, and it asserts on the MESSAGE, because a
    refusal a reader cannot attribute to the corpus is a refusal they will work around.

    Note the deliberate asymmetry with arena/paired_contrast.py, which faces the mirror
    problem: `adjudicate` compares candidates and so requires ONE corpus, while
    `paired_contrast` compares corpus ARMS and so permits -- indeed expects -- a shared
    digest across its two arms while refusing a differing one.
    """

    def test_a_differing_dataset_digest_is_refused(self) -> None:
        baseline = arm("baseline", _FLOOR_BASELINE)
        candidate = CandidateArm(
            dataclasses.replace(
                arm("candidate", _FLOOR_CANDIDATE).spec,
                dataset_sha256="d" * 64,
            ),
            _FLOOR_CANDIDATE,
        )
        with self.assertRaises(ValueError) as raised:
            adjudicate(baseline, (candidate,), resamples=FAST_RESAMPLES)
        message = str(raised.exception)
        self.assertIn("dataset_sha256", message)
        self.assertIn("candidate", message)

    def test_a_shared_dataset_digest_proceeds(self) -> None:
        # The positive companion, so the guard is proven in BOTH directions: a refusal
        # test alone would still pass against a function that refused everything.
        baseline = arm("baseline", _FLOOR_BASELINE)
        candidate = arm("candidate", _FLOOR_CANDIDATE)
        self.assertEqual(
            baseline.spec.dataset_sha256,
            candidate.spec.dataset_sha256,
        )
        rows = adjudicate(baseline, (candidate,), resamples=FAST_RESAMPLES)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].candidate_name, "candidate")


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
