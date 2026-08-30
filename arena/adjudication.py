from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arena.candidate import CandidateSpec
from arena.metrics import SessionOutcome, metric_summary
from arena.statistics import (
    RESAMPLE_COUNT,
    ZERO_VARIANCE_TOLERANCE,
    expected_max_of_k,
    holm_bonferroni,
    minimum_detectable_difference,
    pair_seed,
    paired_bootstrap,
    paired_permutation,
    winners_curse_correction,
)

# At n=200 the most a SINGLE session can move TechnicalScore is 0.005 -- a miss whose
# first hit would have been at turn 11 becoming a rank-1 hit at turn 1:
#   0.50 * (1/200) + 0.30 * (1/200) + 0.20 * ((10/200) / 10)
# = 0.0025          + 0.0015         + 0.0010                = 0.005
# So the floor is exactly two best-case session flips out of two hundred. Small enough
# to be reachable by a real improvement, large enough that no single session can carry
# a candidate over it on its own.
PRACTICAL_FLOOR = 0.01

SIGNIFICANCE_ALPHA = 0.05

# One turn of MTTC is worth 0.20 * (1/10) = 0.02 of TechnicalScore, while one point of
# HR@10 is worth 0.50 -- HR@10 is roughly 25x more sensitive per point than MTTC. The
# D-23 exchange rate spends that budget through MRR: an HR@10 regression is forgiven
# only when the MRR gain exceeds 0.0667 x the MTTC movement it was traded for.
EXCHANGE_RATE_PER_MTTC = 0.0667

# The fixed REPORT order for `failed_criteria`. Building the tuple by filtering this
# constant, rather than by appending as each check runs, is what stops two runs from
# disagreeing on ordering when control flow changes.
CRITERION_ORDER = ("holm_significance", "practical_floor", "hr10_exchange_rate")


class Verdict(StrEnum):
    # All three D-23 criteria passed jointly.
    WIN = "win"
    # The difference IS statistically detected (holm_p < alpha) but fails the CORRECTED
    # practical floor and/or the HR@10 exchange-rate check. This member exists so that a
    # Holm-significant +0.006 gain is never printed as "no difference", which would be
    # exactly the kind of dishonest summary this phase is built to prevent.
    # `failed_criteria` names which bar it missed.
    BELOW_SHIP_BAR = "significant, below ship bar"
    # Not significant, AND the test was powered to see an effect of the observed size
    # (abs(delta) >= mdd), so this null carries information.
    NO_DIFFERENCE = "no difference"
    # Not significant, and the observed delta sits BELOW the minimum detectable
    # difference, so the null is uninformative and must not be read as evidence of
    # equivalence (D-22, MEAS-06).
    NOT_DETECTABLE = "not detectable"


@dataclass(frozen=True, slots=True)
class CandidateArm:
    spec: CandidateSpec
    sessions: tuple[SessionOutcome, ...]


@dataclass(frozen=True, slots=True)
class AdjudicationRow:
    candidate_name: str
    candidate_fingerprint: str
    baseline_fingerprint: str
    delta: float
    ci_lower: float
    ci_upper: float
    standard_error: float
    permutation_p: float
    holm_p: float
    minimum_detectable_difference: float
    candidate_count: int
    correction_k: int
    expected_max_of_k: float
    corrected_delta: float
    clears_practical_floor: bool
    is_champion: bool
    hit_rate_delta: float
    mrr_delta: float
    mttc_delta: float
    exchange_rate_ok: bool
    verdict: Verdict
    failed_criteria: tuple[str, ...]
    resamples: int

    def as_record(self) -> dict[str, object]:
        # sigma-hat, k and E[max of k] are separate columns on purpose (T-01-13): a
        # reader must be able to re-derive `corrected_delta` rather than trust it.
        return {
            "candidate_name": self.candidate_name,
            "candidate_fingerprint": self.candidate_fingerprint,
            "baseline_fingerprint": self.baseline_fingerprint,
            "delta": self.delta,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "standard_error": self.standard_error,
            "permutation_p": self.permutation_p,
            "holm_p": self.holm_p,
            "minimum_detectable_difference": self.minimum_detectable_difference,
            "candidate_count": self.candidate_count,
            "correction_k": self.correction_k,
            "expected_max_of_k": self.expected_max_of_k,
            "corrected_delta": self.corrected_delta,
            "clears_practical_floor": self.clears_practical_floor,
            "is_champion": self.is_champion,
            "hit_rate_delta": self.hit_rate_delta,
            "mrr_delta": self.mrr_delta,
            "mttc_delta": self.mttc_delta,
            "exchange_rate_ok": self.exchange_rate_ok,
            "verdict": self.verdict.value,
            "failed_criteria": list(self.failed_criteria),
            "resamples": self.resamples,
        }


def classify_verdict(
    *,
    holm_p: float,
    delta: float,
    minimum_detectable_difference: float,
    failed_criteria: tuple[str, ...],
) -> Verdict:
    """The whole D-22/D-23 verdict rule, as four ordered clauses over injected values.

    Two properties a future reader will otherwise mis-diagnose as bugs:

    Clause 1 is an EQUIVALENCE, not an implication. The returned verdict is WIN if and
    only if `failed_criteria` is empty. Plan 01-09 asserts that identity against the
    committed leaderboard, so no branch anywhere may return WIN with a non-empty tuple,
    nor a non-WIN verdict with an empty one.

    Clause 4 is rare by construction and that is expected. MDD is 2.801585218112968 x
    SE, a multiplier bundling the two-sided alpha with 80% power, so abs(delta) >= MDD
    is roughly a 2.8-sigma effect whose two-sided permutation p is around 0.005.
    Reaching clause 4 non-degenerately therefore needs a Holm family large enough to
    inflate 0.005 past 0.05 -- possible, but not constructible from a small session
    fixture. That is exactly why this rule lives in an injectable pure function: the
    suite exercises clause 4 by injection rather than by attempting to build a session
    pair that cannot exist at realistic family sizes. The degenerate zero-variance path
    also lands on clause 4, and does so through this general rule rather than through a
    special case.
    """
    if not failed_criteria:
        return Verdict.WIN
    if holm_p < SIGNIFICANCE_ALPHA:
        return Verdict.BELOW_SHIP_BAR
    if abs(delta) < minimum_detectable_difference:
        return Verdict.NOT_DETECTABLE
    return Verdict.NO_DIFFERENCE


def adjudicate(
    baseline: CandidateArm,
    candidates: tuple[CandidateArm, ...],
    *,
    resamples: int = RESAMPLE_COUNT,
) -> tuple[AdjudicationRow, ...]:
    if not candidates:
        raise ValueError("adjudication requires at least one candidate")
    baseline_fingerprint = baseline.spec.fingerprint
    for candidate in candidates:
        if candidate.spec.fingerprint == baseline_fingerprint:
            raise ValueError("a candidate must not share the baseline's fingerprint")

    baseline_summary = metric_summary(baseline.sessions)

    # --- D-20 step 1: paired bootstrap, plus the jointly reported metric deltas ---
    # D-16 makes TechnicalScore the ONLY hypothesis tested. HR@10, MRR and MTTC are
    # always reported beside it and never tested separately: three tests would triple
    # the family size for no gain and invite cherry-picking whichever term moved.
    bootstraps = []
    metric_deltas = []
    for candidate in candidates:
        bootstraps.append(
            paired_bootstrap(
                baseline.sessions,
                candidate.sessions,
                seed=pair_seed(
                    baseline_fingerprint,
                    candidate.spec.fingerprint,
                    "bootstrap",
                ),
                resamples=resamples,
            )
        )
        candidate_summary = metric_summary(candidate.sessions)
        metric_deltas.append(
            (
                candidate_summary.hit_rate_at_10 - baseline_summary.hit_rate_at_10,
                candidate_summary.mrr - baseline_summary.mrr,
                candidate_summary.mttc - baseline_summary.mttc,
            )
        )

    # Two arms that agree on every session collapse delta, SE, both CI bounds and the
    # MDD to zero simultaneously, and a naive `abs(delta) >= mdd` detectability check
    # then evaluates 0 >= 0 as True -- a rig without this guard reports a DETECTABLE
    # difference between a candidate and itself (Pitfall 5). That is a plausible real
    # outcome for a near-null ablation, not a hypothetical.
    degenerate = tuple(
        result.standard_error <= ZERO_VARIANCE_TOLERANCE for result in bootstraps
    )

    # --- D-20 step 2: paired permutation, same pair, a separate RNG stream ---
    permutation_p_values = []
    for index, candidate in enumerate(candidates):
        if degenerate[index]:
            permutation_p_values.append(1.0)
            continue
        permutation_p_values.append(
            paired_permutation(
                baseline.sessions,
                candidate.sessions,
                seed=pair_seed(
                    baseline_fingerprint,
                    candidate.spec.fingerprint,
                    "permutation",
                ),
                resamples=resamples,
            ).p_value
        )

    # --- D-20 step 3: Holm across the candidates only ---
    # The family is exactly these candidates against the common baseline (D-19).
    # Per-scenario results are descriptive and are NEVER folded in here.
    holm_p_values = holm_bonferroni(tuple(permutation_p_values))

    # --- D-20 step 4: winner's-curse correction, at the family's k ---
    # correction_k is the number of NON-BASELINE candidates whose delta was compared
    # when choosing the champion; the baseline's delta against itself is not a selection
    # option, so it is not counted. The correction is applied to EVERY row at that same
    # k: doing so is never anti-conservative, so no row can clear the floor on selection
    # bias, whereas correcting only the champion would leave every other row reporting an
    # uncorrected gain that a later reader could promote by mistake. With a single
    # candidate expected_max_of_k(1) is 0.0, so no selection happened and no correction
    # is applied -- which is correct.
    candidate_count = len(candidates)
    correction_k = candidate_count
    expected_maximum = expected_max_of_k(correction_k)
    champion_index = min(
        range(candidate_count),
        # Descending delta, then ASCENDING fingerprint -- a stable content tie-break,
        # matching the ordering discipline in ranking.py:96-113. Ties are common here:
        # the delta lattice has a 1e-6 pitch because TechnicalScore is rounded.
        key=lambda index: (
            -bootstraps[index].delta,
            candidates[index].spec.fingerprint,
        ),
    )

    rows = []
    for index, candidate in enumerate(candidates):
        bootstrap = bootstraps[index]
        hit_rate_delta, mrr_delta, mttc_delta = metric_deltas[index]
        is_degenerate = degenerate[index]

        if is_degenerate:
            holm_p = 1.0
            detectable_difference = 0.0
            corrected_delta = bootstrap.delta
            clears_practical_floor = False
            exchange_rate_ok = True
            # Stated explicitly rather than left to fall out of the general path: plan
            # 01-09 asserts `verdict == "win"` if and only if `failed_criteria` is empty,
            # so a short-circuit leaving the tuple empty while returning a non-win verdict
            # would violate that identity against the committed leaderboard. The general
            # path agrees exactly -- holm_p 1.0 fails significance, a 0.0 delta fails the
            # floor, and two identical arms have hit_rate_delta == 0.0 so the
            # exchange-rate criterion correctly does not appear.
            failed_criteria = ("holm_significance", "practical_floor")
        else:
            holm_p = holm_p_values[index]
            detectable_difference = minimum_detectable_difference(
                bootstrap.standard_error
            )
            corrected_delta = bootstrap.delta - winners_curse_correction(
                bootstrap.standard_error,
                correction_k,
            )
            # --- D-20 step 5: the floor is tested against the CORRECTED delta ---
            # Applying it to the raw delta is the specific anti-pattern this whole
            # ordering exists to prevent: at the 0.022-0.030 selection inflation
            # PROJECT.md warns about, a candidate could clear 0.01 on selection bias
            # alone -- more than the entire remaining recall headroom this project has.
            clears_practical_floor = corrected_delta >= PRACTICAL_FLOOR
            # D-23: an HR@10 regression is disqualifying unless the exchange-rate math
            # clears. No regression means nothing to trade, so the check passes.
            exchange_rate_ok = hit_rate_delta >= 0.0 or (
                mrr_delta > EXCHANGE_RATE_PER_MTTC * mttc_delta
            )
            failures = {
                "holm_significance": holm_p < SIGNIFICANCE_ALPHA,
                "practical_floor": clears_practical_floor,
                "hr10_exchange_rate": exchange_rate_ok,
            }
            # Filtered from the constant, so the order is fixed by CRITERION_ORDER and
            # never by the order the checks happened to run in.
            failed_criteria = tuple(
                name for name in CRITERION_ORDER if not failures[name]
            )

        # The single verdict call site. The rule lives in one place so the degenerate
        # branch is adjudicated by the SAME logic as every other row -- a deliberate
        # consistency check rather than a hard-coded answer. With holm_p 1.0,
        # delta 0.0 and mdd 0.0: clause 2 fails, `abs(0.0) < 0.0` is False so clause 3
        # fails, and clause 4 returns NO_DIFFERENCE, which is the correct answer reached
        # through the general rule.
        verdict = classify_verdict(
            holm_p=holm_p,
            delta=bootstrap.delta,
            minimum_detectable_difference=detectable_difference,
            failed_criteria=failed_criteria,
        )

        rows.append(
            AdjudicationRow(
                candidate_name=candidate.spec.name,
                candidate_fingerprint=candidate.spec.fingerprint,
                baseline_fingerprint=baseline_fingerprint,
                delta=bootstrap.delta,
                ci_lower=bootstrap.lower,
                ci_upper=bootstrap.upper,
                standard_error=bootstrap.standard_error,
                permutation_p=permutation_p_values[index],
                holm_p=holm_p,
                minimum_detectable_difference=detectable_difference,
                candidate_count=candidate_count,
                correction_k=correction_k,
                expected_max_of_k=expected_maximum,
                corrected_delta=corrected_delta,
                clears_practical_floor=clears_practical_floor,
                is_champion=index == champion_index,
                hit_rate_delta=hit_rate_delta,
                mrr_delta=mrr_delta,
                mttc_delta=mttc_delta,
                exchange_rate_ok=exchange_rate_ok,
                verdict=verdict,
                failed_criteria=failed_criteria,
                resamples=resamples,
            )
        )
    # Input candidate order, so the caller owns presentation; the only ordering decision
    # made in here is the champion tie-break.
    return tuple(rows)
