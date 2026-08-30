from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import math
import statistics
import time
import unittest
from statistics import NormalDist

import arena.statistics
from arena.metrics import metric_summary, technical_score
from arena.statistics import (
    MDD_MULTIPLIER,
    RESAMPLE_COUNT,
    Z_ALPHA_TWO_SIDED,
    Z_POWER_80,
    exact_paired_sign_flip_p_value,
    expected_max_of_k,
    holm_bonferroni,
    minimum_detectable_difference,
    pair_seed,
    paired_bootstrap,
    paired_permutation,
    winners_curse_correction,
)
from tests.arena_fixtures import (
    load_anchor_sessions,
    promote_hits_to_rank_one,
    session,
    sessions_from_ranks,
)


# Resample budget for this module. Every test below asserts a structural or analytic
# property that does not depend on R, so 500 is enough and keeps the module inside a
# sub-8-second budget. The two exceptions are called out at their definitions.
#
# 500 is not merely convenient. At R=500 the bootstrap SE estimate carries roughly
# 1/sqrt(2R) ~ 3.2% relative noise, while the m=10 synthetic control's headroom over
# its MDD is 0.011931 / (2.801585218112968 * 0.003715) - 1 ~ 14.6%, so the
# `delta > MDD` assertion sits about 4.5 sigma clear of flipping. (Measured here at
# R=500 the SE is 0.003593, giving an even wider margin than the reference 0.003715.)
# The two production paths, arena/run_arena.py and arena/leaderboard.py, never pass
# `resamples` and therefore always run at RESAMPLE_COUNT = 10,000.
TEST_RESAMPLES = 500


def constant_reciprocal_rank_arm(
    values: tuple[float, ...],
) -> tuple[object, ...]:
    """Sessions that differ only in reciprocal rank, so HR@10 and MTTC are invariant."""
    # reciprocal_rank is set directly rather than derived from best_rank: this fixture
    # exists to exercise the estimator's variance structure, and a constant per-session
    # improvement has no expression in reciprocal ranks (1/r is not closed under +0.05).
    return tuple(
        session(
            f"s{index:03d}",
            best_rank=2,
            first_hit_turn=2,
            reciprocal_rank=value,
        )
        for index, value in enumerate(values)
    )


# Baseline alternates a strong and a weak session so its OWN resampling variance is
# non-zero -- without that, an unpaired implementation would also produce a narrow
# interval and the Pitfall 3 tripwire would not bite.
_PAIRING_BASELINE_VALUES = tuple(0.90 if i % 2 == 0 else 0.05 for i in range(200))
# Perfectly correlated: every session improves by exactly the same 0.05.
_PAIRING_CORRELATED_VALUES = tuple(v + 0.05 for v in _PAIRING_BASELINE_VALUES)
# Uncorrelated with the SAME observed delta of +0.05 MRR: the strong sessions collapse
# and the weak ones are promoted, so which sessions a replicate happens to draw now
# dominates the statistic.
_PAIRING_UNCORRELATED_VALUES = tuple(
    0.05 if i % 2 == 0 else 1.00 for i in range(200)
)


def improve_one_session(sessions: tuple, from_rank: int = 4) -> tuple:
    """The near-null pair: exactly one session moves from rank 4 to rank 3."""
    improved = []
    done = False
    for item in sessions:
        if not done and item.best_rank == from_rank:
            improved.append(
                dataclasses.replace(
                    item,
                    best_rank=from_rank - 1,
                    reciprocal_rank=1.0 / (from_rank - 1),
                )
            )
            done = True
        else:
            improved.append(item)
    if not done:
        raise ValueError(f"no session at rank {from_rank}")
    return tuple(improved)


class PairingTest(unittest.TestCase):
    def test_bootstrap_rejects_mismatched_sample_ids(self) -> None:
        left = sessions_from_ranks((2, 3, 4))
        right = tuple(
            dataclasses.replace(item, sample_id=f"x{index:03d}")
            for index, item in enumerate(left)
        )
        with self.assertRaises(ValueError):
            paired_bootstrap(left, right, seed=1, resamples=TEST_RESAMPLES)

    def test_permutation_rejects_mismatched_sample_ids(self) -> None:
        left = sessions_from_ranks((2, 3, 4))
        right = tuple(reversed(left))
        with self.assertRaises(ValueError):
            paired_permutation(left, right, seed=1, resamples=TEST_RESAMPLES)

    def test_unequal_lengths_are_rejected(self) -> None:
        left = sessions_from_ranks((2, 3, 4))
        for procedure in (paired_bootstrap, paired_permutation):
            with self.subTest(procedure=procedure.__name__):
                with self.assertRaises(ValueError):
                    procedure(left, left[:2], seed=1, resamples=TEST_RESAMPLES)

    def test_pairing_shrinks_the_confidence_interval(self) -> None:
        # The Pitfall 3 tripwire. Two independent index vectors would silently discard
        # the pairing and inflate the SE roughly sevenfold on real data (0.003715 paired
        # vs 0.025922 unpaired), turning every candidate this project can build into
        # "not detectable" while every aggregate assertion still passes. Verified during
        # planning: under a two-vector implementation the correlated width becomes
        # 0.0484 against an uncorrelated 0.0494, and this assertion fails.
        baseline = constant_reciprocal_rank_arm(_PAIRING_BASELINE_VALUES)
        correlated = constant_reciprocal_rank_arm(_PAIRING_CORRELATED_VALUES)
        uncorrelated = constant_reciprocal_rank_arm(_PAIRING_UNCORRELATED_VALUES)

        tight = paired_bootstrap(
            baseline,
            correlated,
            seed=pair_seed("baseline", "correlated", "bootstrap"),
            resamples=TEST_RESAMPLES,
        )
        loose = paired_bootstrap(
            baseline,
            uncorrelated,
            seed=pair_seed("baseline", "uncorrelated", "bootstrap"),
            resamples=TEST_RESAMPLES,
        )

        # Apples to apples: the comparison is only meaningful because the two pairs
        # carry the same observed effect.
        self.assertAlmostEqual(tight.delta, loose.delta, places=12)
        self.assertAlmostEqual(tight.delta, 0.015, places=12)
        self.assertLess(
            tight.upper - tight.lower,
            (loose.upper - loose.lower) / 3.0,
        )

    def test_stdlib_statistics_is_not_shadowed(self) -> None:
        # The module is deliberately named statistics.py. Python 3 uses absolute
        # imports, so `import statistics` inside it resolves to the stdlib module --
        # answered here by a check rather than by a reader's confidence.
        self.assertIs(arena.statistics.statistics, importlib.import_module("statistics"))


class BootstrapTest(unittest.TestCase):
    def test_identical_candidates_collapse_to_zero(self) -> None:
        # The guaranteed true negative. These are exact zeros, so exact equality is
        # correct here and only here.
        sessions = sessions_from_ranks((1, 2, 3, 4, 5, None))
        result = paired_bootstrap(
            sessions, sessions, seed=1, resamples=TEST_RESAMPLES
        )
        self.assertEqual(result.delta, 0.0)
        self.assertEqual((result.lower, result.upper), (0.0, 0.0))
        self.assertEqual(result.standard_error, 0.0)
        self.assertEqual(minimum_detectable_difference(result.standard_error), 0.0)

    def test_synthetic_control_delta_at_m10(self) -> None:
        # assertAlmostEqual, never ==: the delta subtracts two independently 6-dp-rounded
        # TechnicalScores, so the actual float is 0.011931000000000025.
        baseline = load_anchor_sessions()
        candidate = promote_hits_to_rank_one(baseline, 10)
        result = paired_bootstrap(
            baseline,
            candidate,
            seed=pair_seed("anchor", "m10", "bootstrap"),
            resamples=TEST_RESAMPLES,
        )
        self.assertAlmostEqual(result.delta, 0.011931, places=9)

    def test_synthetic_control_delta_at_m77(self) -> None:
        # Actual float here is 0.08521400000000001.
        baseline = load_anchor_sessions()
        candidate = promote_hits_to_rank_one(baseline, 77)
        result = paired_bootstrap(
            baseline,
            candidate,
            seed=pair_seed("anchor", "m77", "bootstrap"),
            resamples=TEST_RESAMPLES,
        )
        self.assertAlmostEqual(result.delta, 0.085214, places=9)

    def test_promotion_moves_only_the_ranking_term(self) -> None:
        baseline = load_anchor_sessions()
        candidate = promote_hits_to_rank_one(baseline, 10)
        before = metric_summary(baseline)
        after = metric_summary(candidate)
        self.assertEqual(before.hit_rate_at_10, after.hit_rate_at_10)
        self.assertEqual(before.mttc, after.mttc)
        self.assertGreater(after.mrr, before.mrr)

    def test_synthetic_control_is_detectable_at_m10(self) -> None:
        # The guaranteed true positive: a real ranking improvement on 10 of 200 sessions
        # must clear its own MDD, or the rig cannot decide anything the bake-off asks it.
        baseline = load_anchor_sessions()
        candidate = promote_hits_to_rank_one(baseline, 10)
        result = paired_bootstrap(
            baseline,
            candidate,
            seed=pair_seed("anchor", "m10", "bootstrap"),
            resamples=TEST_RESAMPLES,
        )
        self.assertGreater(
            result.delta,
            minimum_detectable_difference(result.standard_error),
        )

    def test_confidence_interval_excludes_zero_at_m10(self) -> None:
        baseline = load_anchor_sessions()
        candidate = promote_hits_to_rank_one(baseline, 10)
        result = paired_bootstrap(
            baseline,
            candidate,
            seed=pair_seed("anchor", "m10", "bootstrap"),
            resamples=TEST_RESAMPLES,
        )
        self.assertGreater(result.lower, 0.0)

    def test_technical_score_is_not_a_mean_of_per_session_scores(self) -> None:
        # The D-17 tripwire against an averaging shortcut inside the replicate loop.
        # The gap is small -- about 7e-7 -- because TechnicalScore is affine in the three
        # component means and efficiency's clamp cannot bind (mttc is confined to
        # [1, 11] by construction), so 6-dp output rounding is the sole source of
        # divergence. It is small but real, fully deterministic, and it is exactly what
        # an averaging shortcut would inject into every one of 10,000 replicates.
        outcomes = sessions_from_ranks((2, 3, 9))
        mean_of_per_session = statistics.fmean(
            technical_score(metric_summary((item,))) for item in outcomes
        )
        self.assertNotEqual(mean_of_per_session, technical_score(metric_summary(outcomes)))


class PermutationTest(unittest.TestCase):
    def test_identical_candidates_give_p_of_one(self) -> None:
        sessions = sessions_from_ranks((1, 2, 3, 4, 5, None))
        result = paired_permutation(
            sessions, sessions, seed=1, resamples=TEST_RESAMPLES
        )
        self.assertEqual(result.p_value, 1.0)

    def test_permutation_floor(self) -> None:
        # The one test that pins R, because the Phipson-Smyth floor 1/(R+1) is a function
        # of R. m=77 is as extreme as this data gets, so if any input could drive the
        # p-value to a dishonest 0.0 it is this one.
        resamples = 2000
        baseline = load_anchor_sessions()
        candidate = promote_hits_to_rank_one(baseline, 77)
        result = paired_permutation(
            baseline,
            candidate,
            seed=pair_seed("anchor", "m77", "permutation"),
            resamples=resamples,
        )
        self.assertGreaterEqual(result.p_value, 1.0 / (resamples + 1))
        self.assertNotEqual(result.p_value, 0.0)

    def test_exact_sign_flip_pins_the_two_sided_convention(self) -> None:
        # Hand-checkable: of the 16 sign assignments, only {}, {-0.05}, {0.10,0.20,0.30}
        # and the full set are at least as extreme as the observed mean of 0.1375.
        self.assertEqual(
            exact_paired_sign_flip_p_value((0.10, 0.20, 0.30, -0.05)), 0.25
        )

    def test_exact_sign_flip_on_a_symmetric_pair(self) -> None:
        # Observed mean is 0.0, so every one of the four assignments ties it in absolute
        # value and the exact p is 1.0.
        self.assertEqual(exact_paired_sign_flip_p_value((0.10, -0.10)), 1.0)

    def test_exact_sign_flip_rejects_intractable_input(self) -> None:
        with self.assertRaises(ValueError):
            exact_paired_sign_flip_p_value(())
        with self.assertRaises(ValueError):
            exact_paired_sign_flip_p_value(tuple(0.01 * n for n in range(21)))

    def test_production_constant_is_ten_thousand(self) -> None:
        # D-24 fixes this as a module constant and not a CLI flag, so no caller can make
        # the rig cheap enough to be wrong (T-01-10). At R=10,000 the floor is 9.999e-5.
        self.assertEqual(RESAMPLE_COUNT, 10_000)


class HolmTest(unittest.TestCase):
    def assertAdjusted(
        self,
        p_values: tuple[float, ...],
        expected: tuple[float, ...],
    ) -> None:
        actual = holm_bonferroni(p_values)
        self.assertEqual(len(actual), len(expected))
        for index, (got, want) in enumerate(zip(actual, expected)):
            with self.subTest(index=index):
                self.assertAlmostEqual(got, want, places=10)

    def test_textbook_case(self) -> None:
        # The sharpest fixture: naive Holm gives 0.04 * 1 = 0.04 for the third element,
        # which the running maximum correctly raises to 0.06.
        self.assertAdjusted((0.01, 0.04, 0.03), (0.03, 0.06, 0.06))

    def test_one_strong_result(self) -> None:
        self.assertAdjusted((0.001, 0.30, 0.40), (0.003, 0.60, 0.60))

    def test_exact_ties(self) -> None:
        self.assertAdjusted((0.02, 0.02, 0.02), (0.06, 0.06, 0.06))

    def test_monotonicity_bites(self) -> None:
        self.assertAdjusted((0.60, 0.01, 0.02), (0.60, 0.03, 0.04))

    def test_adjusted_values_never_decrease_as_raw_p_increases(self) -> None:
        # Fixed literal vector in a deliberately scrambled order, not an RNG draw.
        raw = (0.60, 0.01, 0.31, 0.02, 0.04, 0.31, 0.001)
        adjusted = holm_bonferroni(raw)
        ordered = sorted(zip(raw, adjusted), key=lambda pair: pair[0])
        for earlier, later in zip(ordered, ordered[1:]):
            with self.subTest(raw=later[0]):
                self.assertGreaterEqual(later[1], earlier[1])

    def test_rejects_invalid_input(self) -> None:
        with self.assertRaises(ValueError):
            holm_bonferroni(())
        with self.assertRaises(ValueError):
            holm_bonferroni((1.5,))
        with self.assertRaises(ValueError):
            holm_bonferroni((-0.1,))


class MinimumDetectableDifferenceTest(unittest.TestCase):
    def test_multiplier_constants(self) -> None:
        self.assertAlmostEqual(Z_ALPHA_TWO_SIDED, 1.9599639845400536, places=15)
        self.assertAlmostEqual(Z_POWER_80, 0.8416212335729144, places=15)
        self.assertAlmostEqual(MDD_MULTIPLIER, 2.801585218112968, places=15)

    def test_closed_form_identity(self) -> None:
        for standard_error in (0.0, 0.003779, 0.007961, 0.020429):
            with self.subTest(standard_error=standard_error):
                self.assertEqual(
                    minimum_detectable_difference(standard_error),
                    2.801585218112968 * standard_error,
                )
        self.assertAlmostEqual(
            minimum_detectable_difference(0.003779), 0.010587, places=6
        )

    def test_rejects_negative_standard_error(self) -> None:
        with self.assertRaises(ValueError):
            minimum_detectable_difference(-0.1)

    def test_mdd_is_reported_even_when_the_result_is_null(self) -> None:
        # This pair of assertions IS MEAS-06: "no significant difference" and "we could
        # not have detected one" must be visibly distinct. One session moving from rank
        # 4 to rank 3 is not significant, and the MDD is what says how far short it fell.
        baseline = load_anchor_sessions()
        candidate = improve_one_session(baseline)
        permutation = paired_permutation(
            baseline,
            candidate,
            seed=pair_seed("anchor", "near-null", "permutation"),
            resamples=TEST_RESAMPLES,
        )
        bootstrap = paired_bootstrap(
            baseline,
            candidate,
            seed=pair_seed("anchor", "near-null", "bootstrap"),
            resamples=TEST_RESAMPLES,
        )
        self.assertGreater(permutation.p_value, 0.05)
        self.assertGreater(
            minimum_detectable_difference(bootstrap.standard_error), 0.0
        )


class ExpectedMaximumTest(unittest.TestCase):
    def test_closed_form_anchors(self) -> None:
        self.assertEqual(expected_max_of_k(1), 0.0)
        self.assertAlmostEqual(
            expected_max_of_k(2), 1.0 / math.sqrt(math.pi), places=12
        )
        self.assertAlmostEqual(
            expected_max_of_k(3), 3.0 / (2.0 * math.sqrt(math.pi)), places=12
        )

    def test_tabulated_values(self) -> None:
        self.assertAlmostEqual(expected_max_of_k(5), 1.1629644736405196, places=10)
        self.assertAlmostEqual(expected_max_of_k(10), 1.5387527308351732, places=10)

    def test_strictly_increasing_in_k(self) -> None:
        values = [expected_max_of_k(k) for k in range(1, 11)]
        for earlier, later in zip(values, values[1:]):
            self.assertLess(earlier, later)

    def test_rejects_invalid_arguments(self) -> None:
        with self.assertRaises(ValueError):
            expected_max_of_k(0)
        with self.assertRaises(ValueError):
            expected_max_of_k(2, panels=1999)

    def test_blom_is_a_cross_check_and_not_the_implementation(self) -> None:
        # Blom agrees to ~1e-2, which is why it is a useful independent check; it does
        # NOT agree to 1e-6, which is why Simpson is the implementation. At sigma-hat
        # 0.02 Blom's 2.5e-2 relative error at k=2 is ~5e-4 TechnicalScore, 5% of the
        # entire MEAS-07 floor.
        for k in range(2, 11):
            blom = NormalDist().inv_cdf((k - 0.375) / (k + 0.25))
            with self.subTest(k=k):
                self.assertAlmostEqual(blom, expected_max_of_k(k), delta=3e-2)
        self.assertNotAlmostEqual(
            NormalDist().inv_cdf((2 - 0.375) / (2 + 0.25)),
            expected_max_of_k(2),
            places=6,
        )

    def test_integration_uses_no_randomness_and_stays_cheap(self) -> None:
        # Byte-reproducibility is an acceptance property, so the correction must contain
        # no RNG at all -- asserted against the source, not against a sampled output.
        self.assertNotIn("random", inspect.getsource(expected_max_of_k))
        best = min(
            self._elapsed_milliseconds(lambda: expected_max_of_k(10)) for _ in range(3)
        )
        # Measured at 0.7 ms during planning; the 10 ms bound leaves 13x headroom.
        self.assertLess(best, 10.0)

    @staticmethod
    def _elapsed_milliseconds(call) -> float:
        start = time.perf_counter()
        call()
        return (time.perf_counter() - start) * 1000.0

    def test_winners_curse_correction(self) -> None:
        self.assertEqual(winners_curse_correction(0.003, 1), 0.0)
        self.assertAlmostEqual(
            winners_curse_correction(0.003, 5),
            0.003 * 1.1629644736405196,
            places=12,
        )


class SeedDeterminismTest(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_anchor_sessions()
        self.candidate = promote_hits_to_rank_one(self.baseline, 10)

    def test_bootstrap_is_reproducible(self) -> None:
        seed = pair_seed("anchor", "m10", "bootstrap")
        first = paired_bootstrap(
            self.baseline, self.candidate, seed=seed, resamples=TEST_RESAMPLES
        )
        second = paired_bootstrap(
            self.baseline, self.candidate, seed=seed, resamples=TEST_RESAMPLES
        )
        self.assertEqual(first, second)

    def test_permutation_is_reproducible(self) -> None:
        seed = pair_seed("anchor", "m10", "permutation")
        first = paired_permutation(
            self.baseline, self.candidate, seed=seed, resamples=TEST_RESAMPLES
        )
        second = paired_permutation(
            self.baseline, self.candidate, seed=seed, resamples=TEST_RESAMPLES
        )
        self.assertEqual(first.p_value, second.p_value)

    def test_serialized_records_are_byte_identical(self) -> None:
        seed = pair_seed("anchor", "m10", "bootstrap")
        records = [
            json.dumps(
                paired_bootstrap(
                    self.baseline,
                    self.candidate,
                    seed=seed,
                    resamples=TEST_RESAMPLES,
                ).as_record(),
                sort_keys=True,
            )
            for _ in range(2)
        ]
        self.assertEqual(records[0], records[1])

    def test_labels_produce_different_replicate_streams(self) -> None:
        # The label keeps the two procedures off a shared RNG stream; a different seed
        # must therefore produce a different replicate draw on a non-degenerate pair.
        self.assertNotEqual(
            pair_seed("a", "b", "bootstrap"), pair_seed("a", "b", "permutation")
        )
        # The seed is deliberately not symmetric in its two arguments.
        self.assertNotEqual(
            pair_seed("a", "b", "bootstrap"), pair_seed("b", "a", "bootstrap")
        )
        first = paired_bootstrap(
            self.baseline,
            self.candidate,
            seed=pair_seed("anchor", "m10", "bootstrap"),
            resamples=TEST_RESAMPLES,
        )
        second = paired_bootstrap(
            self.baseline,
            self.candidate,
            seed=pair_seed("anchor", "m10", "permutation"),
            resamples=TEST_RESAMPLES,
        )
        self.assertEqual(first.delta, second.delta)
        self.assertNotEqual(first.standard_error, second.standard_error)


if __name__ == "__main__":
    unittest.main()
