from __future__ import annotations

import hashlib
import itertools
import math
import random
import statistics
from dataclasses import dataclass

from arena.metrics import SessionOutcome, metric_summary, technical_score

# `import statistics` above resolves to the STDLIB module, not to this file: Python 3
# uses absolute imports, so a submodule named `arena.statistics` never shadows a
# top-level `statistics`. The module keeps the name RESEARCH and PATTERNS assign it,
# and `test_stdlib_statistics_is_not_shadowed` turns that reasoning into a check.

# D-24 fixes the replicate count as a MODULE CONSTANT and deliberately not as a CLI
# flag, so no caller can make the rig cheap enough to be wrong (threat T-01-10). The
# `resamples` KEYWORD ARGUMENT exists solely so the unit-test suite can run at a lower
# R and keep its sub-10-second feedback loop; every production path
# (`arena/run_arena.py`, `arena/leaderboard.py`) takes the default.
RESAMPLE_COUNT = 10_000

# A 2.5% tail is REPRESENTABLE only when 1 / (resamples + 1) <= 0.025, i.e. only when
# resamples >= 39. Below that `(resamples + 1) * 0.025` falls under 1, both indices
# clamp to the extremes, and the function returns the full replicate range whatever
# confidence was requested -- a silently WRONG answer rather than an honestly wide one.
# That is the failure mode the pre-fix arithmetic exhibited at R=2, where the "97.5th
# percentile" was literally the minimum replicate. 40 sits one above the
# representability threshold. Note the interval legitimately remains the full replicate
# range up to R=78 and the lower bound first leaves index 0 at R=79; that is expected
# and honest at those counts, not a defect, which is why this floor is about
# REPRESENTABILITY and not about the span. The suite's FAST_RESAMPLES=200,
# STABLE_RESAMPLES=500, TEST_RESAMPLES=500 and the pinned 2000 in
# `test_permutation_floor` all sit comfortably above it.
MINIMUM_RESAMPLES = 40

# The interval's confidence level appears once here rather than as four magic numbers
# buried inside an index expression.
_LOWER_QUANTILE = 0.025
_UPPER_QUANTILE = 0.975

# Float-noise slack when testing whether a permuted statistic is at least as extreme
# as the observed one. TechnicalScore is rounded to 6 dp, so an exact tie is common
# and a bare `>=` on raw floats would drop roughly half of them.
_TIE_TOLERANCE = 1e-12

# Below this the two candidates are indistinguishable on every resample, and every
# ratio comparison built on the SE becomes vacuous (Pitfall 5).
ZERO_VARIANCE_TOLERANCE = 1e-12

# Exhaustive sign-flip enumeration is 2**n; past 20 it stops being a unit test.
_MAX_EXACT_ENUMERATION = 20


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    delta: float
    lower: float
    upper: float
    standard_error: float
    resamples: int

    def as_record(self) -> dict[str, object]:
        return {
            "delta": self.delta,
            "lower": self.lower,
            "upper": self.upper,
            "standard_error": self.standard_error,
            "resamples": self.resamples,
        }


@dataclass(frozen=True, slots=True)
class PermutationResult:
    observed: float
    p_value: float
    resamples: int

    def as_record(self) -> dict[str, object]:
        return {
            "observed": self.observed,
            "p_value": self.p_value,
            "resamples": self.resamples,
        }


def pair_seed(
    baseline_fingerprint: str,
    candidate_fingerprint: str,
    label: str,
) -> int:
    """Content-seeded, never clock-seeded -- two runs must agree byte for byte."""
    # Takes plain fingerprint strings rather than CandidateSpec objects so this module
    # carries no dependency on arena.candidate. The label ("bootstrap" / "permutation")
    # keeps the two procedures off a shared RNG stream.
    #
    # The seed is deliberately NOT symmetric in its two arguments. The call site fixes
    # the order as (baseline, candidate); the property under test is reproducibility,
    # not order invariance.
    digest = hashlib.sha256(
        f"{baseline_fingerprint}\0{candidate_fingerprint}\0{label}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _require_paired(
    baseline: tuple[SessionOutcome, ...],
    candidate: tuple[SessionOutcome, ...],
) -> None:
    # MEAS-04's join-on-sample_id made structural: an independent-sample comparison
    # becomes impossible to EXPRESS rather than merely discouraged. Pitfall 3 is silent
    # by construction, so the guard has to sit at the entry of every paired routine.
    if len(baseline) != len(candidate) or tuple(
        item.sample_id for item in baseline
    ) != tuple(item.sample_id for item in candidate):
        raise ValueError("paired comparison requires identical sample_id ordering")


def _require_resamples(resamples: int) -> None:
    if resamples < MINIMUM_RESAMPLES:
        raise ValueError(f"resample count must be at least {MINIMUM_RESAMPLES}")


def percentile_indices(resamples: int) -> tuple[int, int]:
    """Zero-based (lower, upper) order statistics of a 95% percentile interval."""
    # PUBLIC, pure and side-effect-free specifically so the suite and a future auditor
    # can assert the indices directly instead of inferring them from an interval --
    # the same auditability discipline arena/adjudication.py:93-95 states for the
    # correction columns.
    #
    # Two properties this (R+1) convention buys, both asserted in
    # tests/test_arena_statistics.py::PercentileIntervalTest. Do not "simplify" them
    # away:
    #
    #   SYMMETRY. lower == resamples - 1 - upper at every admissible R, so the two
    #   tails are equally far from their ends. The pre-fix arithmetic had no such
    #   property: at R=10,000 it took order statistic 251 from the bottom and 9750
    #   from the top.
    #
    #   COVERAGE AT OR ABOVE NOMINAL. The interval spans upper - lower + 1 of the
    #   `resamples` order statistics, which is at least 0.95 * resamples at every
    #   admissible R. (R + 1) is the Efron-Tibshirani denominator: with R replicates
    #   there are R+1 gaps between and outside them, so the alpha/2 quantile is the
    #   (R+1) * alpha/2-th order statistic. The pre-fix code used `resamples` as the
    #   denominator AND dropped one index on the upper side, which is where the
    #   94.99% came from.
    #
    # Worked values, checkable by eye: R=10,000 -> (249, 9750), spanning 9,502 of
    # 10,000 (95.02%); R=500 -> (11, 488), spanning 478 (95.6%); R=200 -> (4, 195),
    # spanning 192 (96.0%); R=40 -> (0, 39), the full range.
    #
    # The clamps are defensive only: above MINIMUM_RESAMPLES neither can bind, since
    # floor(0.025 * (R + 1)) >= 1 for R >= 39.
    _require_resamples(resamples)
    lower_index = max(0, math.floor(_LOWER_QUANTILE * (resamples + 1)) - 1)
    upper_index = min(resamples - 1, math.ceil(_UPPER_QUANTILE * (resamples + 1)) - 1)
    return (lower_index, upper_index)


def _delta(
    baseline: tuple[SessionOutcome, ...],
    candidate: tuple[SessionOutcome, ...],
) -> float:
    # Recomputed from scratch on whatever sample is handed in. TechnicalScore is not a
    # mean of per-session scores (D-17) -- Efficiency depends on the mean MTTC, not on
    # a mean of per-session efficiencies -- so it can never be averaged session-wise.
    return technical_score(metric_summary(candidate)) - technical_score(
        metric_summary(baseline)
    )


def paired_bootstrap(
    baseline: tuple[SessionOutcome, ...],
    candidate: tuple[SessionOutcome, ...],
    *,
    seed: int,
    resamples: int = RESAMPLE_COUNT,
) -> BootstrapResult:
    _require_paired(baseline, candidate)
    _require_resamples(resamples)
    rng = random.Random(seed)  # an instance, never the module-global RNG (D-24)
    count = len(baseline)
    deltas: list[float] = []
    for _ in range(resamples):
        # ONE index vector, applied to BOTH arms. Drawing two independent vectors
        # silently discards the pairing and inflates the standard error roughly
        # sevenfold on this repository's data (0.003715 paired vs 0.025922 unpaired),
        # which turns every candidate this project can build into "not detectable"
        # while every aggregate assertion still passes (Pitfall 3).
        indices = [rng.randrange(count) for _ in range(count)]
        deltas.append(
            _delta(
                tuple(baseline[index] for index in indices),
                tuple(candidate[index] for index in indices),
            )
        )
    deltas.sort()
    # PERCENTILE interval, and BCa is rejected rather than merely unimplemented, so a
    # future reader does not "upgrade" it. BCa needs z0 = NormalDist().inv_cdf(p) where
    # p is the proportion of replicates below the observed value; for two identical
    # candidates that proportion is 0.0 and inv_cdf raises StatisticsError -- BCa
    # crashes on exactly the degenerate fixture D-01 Layer 1 requires. On a near-null
    # pair the delta distribution is lattice-valued (26 distinct values in 5,000
    # replicates, 19.1% exact ties), so z0 swings nineteen-fold on a `<` versus `<=`
    # choice with no principled answer. Percentile degrades gracefully to (0.0, 0.0).
    lower_index, upper_index = percentile_indices(resamples)
    return BootstrapResult(
        delta=_delta(baseline, candidate),
        lower=deltas[lower_index],
        upper=deltas[upper_index],
        standard_error=statistics.pstdev(deltas),
        resamples=resamples,
    )


def paired_permutation(
    baseline: tuple[SessionOutcome, ...],
    candidate: tuple[SessionOutcome, ...],
    *,
    seed: int,
    resamples: int = RESAMPLE_COUNT,
) -> PermutationResult:
    _require_paired(baseline, candidate)
    _require_resamples(resamples)
    rng = random.Random(seed)
    observed = _delta(baseline, candidate)
    threshold = abs(observed) - _TIE_TOLERANCE
    count = 0
    for _ in range(resamples):
        left: list[SessionOutcome] = []
        right: list[SessionOutcome] = []
        for index in range(len(baseline)):
            # The swap is WITHIN a pair and never across candidates (D-18). An
            # independent-sample permutation over the same rows would look entirely
            # plausible and be wrong.
            if rng.getrandbits(1):
                left.append(candidate[index])
                right.append(baseline[index])
            else:
                left.append(baseline[index])
                right.append(candidate[index])
        if abs(_delta(tuple(left), tuple(right))) >= threshold:
            count += 1
    # +1 in BOTH terms (Phipson-Smyth): the observed assignment is itself a member of
    # the permutation null under exchangeability, so a Monte-Carlo permutation p can
    # never honestly be 0.0 -- only at most 1/(R+1). Omitting it produces
    # anti-conservative p-values and, at the extreme, a literal 0.0 that would sail
    # through a `p < 0.05` gate on zero evidence.
    return PermutationResult(
        observed=observed,
        p_value=(count + 1) / (resamples + 1),
        resamples=resamples,
    )


def exact_paired_sign_flip_p_value(differences: tuple[float, ...]) -> float:
    """Exhaustive two-sided sign-flip p-value -- the reference `paired_permutation` approximates."""
    total = len(differences)
    if total == 0:
        raise ValueError("sign-flip enumeration requires at least one difference")
    if total > _MAX_EXACT_ENUMERATION:
        raise ValueError("sign-flip enumeration is only tractable up to 20 differences")
    threshold = abs(statistics.fmean(differences)) - _TIE_TOLERANCE
    count = 0
    for signs in itertools.product((1, -1), repeat=total):
        flipped = [sign * value for sign, value in zip(signs, differences)]
        if abs(statistics.fmean(flipped)) >= threshold:
            count += 1
    # No `+1` here, deliberately: exhaustive enumeration ALREADY contains the observed
    # assignment, so adding it again would double-count. This function is what pins the
    # two-sided tail convention that paired_permutation applies at Monte-Carlo scale,
    # against a hand-checkable answer.
    return count / 2**total


# Computed at import from NormalDist rather than hard-coded; the expected literal sits
# in the trailing comment so a reader can check each by eye.
Z_ALPHA_TWO_SIDED = statistics.NormalDist().inv_cdf(0.975)  # 1.9599639845400536
Z_POWER_80 = statistics.NormalDist().inv_cdf(0.80)  # 0.8416212335729144
MDD_MULTIPLIER = Z_ALPHA_TWO_SIDED + Z_POWER_80  # 2.801585218112968

_SIMPSON_PANELS = 2000
_SIMPSON_BOUND = 9.0


def holm_bonferroni(p_values: tuple[float, ...]) -> tuple[float, ...]:
    # The Holm family is the k-1 comparisons of candidates against a COMMON BASELINE in
    # one adjudication event, never candidates crossed with scenarios (D-19). Folding
    # four scenarios in would inflate the family fourfold, destroy power on the one
    # comparison that decides anything, and add power to a Boundary bucket of n=10 that
    # can detect nothing regardless. The caller in plan 01-06 must not get this wrong.
    total = len(p_values)
    if total == 0:
        raise ValueError("holm-bonferroni requires at least one p-value")
    for value in p_values:
        if not 0.0 <= value <= 1.0:
            raise ValueError("p-values must be between 0 and 1")
    # Stable final tie-break on the input index, matching the ordering discipline in
    # ranking.py:96-113 -- ties must never resolve on iteration order.
    order = sorted(range(total), key=lambda index: (p_values[index], index))
    adjusted = [0.0] * total
    running = 0.0
    for rank, index in enumerate(order):
        # The RUNNING MAXIMUM is the monotonicity enforcement and is the step most
        # commonly omitted. Without it an adjusted p can DECREASE as the raw p
        # increases, which is incoherent and can make a weaker result look stronger than
        # a stronger one: the textbook (0.01, 0.04, 0.03) case would return
        # (0.03, 0.04, 0.06) instead of the correct (0.03, 0.06, 0.06).
        running = max(running, min(1.0, (total - rank) * p_values[index]))
        adjusted[index] = running
    return tuple(adjusted)


def minimum_detectable_difference(standard_error: float) -> float:
    """Smallest true delta detectable at 80% power, alpha=0.05 two-sided, given this SE."""
    if standard_error < 0.0:
        raise ValueError("standard error must be non-negative")
    # The input is the BOOTSTRAP SE of the delta, not sd_d / sqrt(n). TechnicalScore is
    # not a mean of per-session values (D-17), so there is no per-session difference
    # whose standard deviation could be taken; the bootstrap SE is the SE of the
    # statistic actually being tested, is already computed by paired_bootstrap at zero
    # extra cost, and inherits the pairing benefit automatically.
    #
    # This value must be reported beside EVERY adjudication row including null ones
    # (D-22, MEAS-06). Reporting it is the entire mechanism that makes "no significant
    # difference" visibly distinct from "we could not have detected one".
    #
    # One further consequence of the 2.801585218112968 multiplier, which plan 01-06
    # depends on: the multiplier bundles the two-sided alpha with 80% power, so
    # abs(delta) >= MDD is roughly a 2.8-sigma effect, whose two-sided permutation p is
    # around 0.005. A non-degenerate result that is simultaneously at-or-above its MDD
    # and Holm-non-significant is therefore rare by construction -- it needs a Holm
    # family large enough to inflate 0.005 past 0.05. That is why 01-06 exposes its
    # verdict decision as an injectable pure helper instead of trying to construct such
    # a fixture from session data.
    return MDD_MULTIPLIER * standard_error


def expected_max_of_k(
    k: int,
    *,
    panels: int = _SIMPSON_PANELS,
    bound: float = _SIMPSON_BOUND,
) -> float:
    """E[max of k iid standard normals], by composite Simpson integration on NormalDist."""
    # No RNG anywhere in here: the winner's-curse correction has to be byte-reproducible.
    # Blom's approximation inv_cdf((k - 0.375) / (k + 0.25)) errs by 2.5e-2 at k=2
    # against Simpson's 3.8e-15, so it is kept only as an independent cross-check in a
    # test and is never the implementation.
    if k < 1:
        raise ValueError("k must be at least 1")
    if k == 1:
        return 0.0
    if panels % 2:
        raise ValueError("simpson's rule requires an even panel count")
    normal = statistics.NormalDist()
    width = (2.0 * bound) / panels

    def integrand(x: float) -> float:
        return x * k * (normal.cdf(x) ** (k - 1)) * normal.pdf(x)

    terms = [integrand(-bound), integrand(bound)]
    for step in range(1, panels):
        weight = 4.0 if step % 2 else 2.0
        terms.append(weight * integrand(-bound + step * width))
    # math.fsum, not sum: 2,001 terms spanning nine orders of magnitude accumulate
    # visible drift under naive addition, and the closed-form anchors are asserted to
    # twelve places.
    return math.fsum(terms) * width / 3.0


def winners_curse_correction(standard_error: float, k: int) -> float:
    """Expected upward selection bias from taking the best of k candidates."""
    # The sigma fed here is the PAIRED-DIFFERENCE bootstrap SE of the delta (D-21),
    # typically 0.002 to 0.008 on this data -- NOT the 0.019 absolute binomial SE of
    # HR@10 quoted in PROJECT.md and PITFALLS.md. Those are different quantities and the
    # distinction changes the printed number by roughly an order of magnitude, which is
    # why plan 01-07 prints sigma-hat, k and E[max of k] as separate audited columns.
    # At SE = 0.003 the correction is 0.0035 at k=5 and 0.0046 at k=10, both the same
    # order as Phase 5's ~0.005 stopping threshold (POS-04), so this decides a go/no-go
    # rather than being cosmetic.
    return standard_error * expected_max_of_k(k)
