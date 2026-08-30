from __future__ import annotations

import hashlib
import itertools
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
    if resamples < 1:
        raise ValueError("resample count must be at least one")


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
    return BootstrapResult(
        delta=_delta(baseline, candidate),
        lower=deltas[int(0.025 * resamples)],
        upper=deltas[int(0.975 * resamples) - 1],
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
