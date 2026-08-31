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
# only when the MRR gain exceeds 0.0667 x the MAGNITUDE of the MTTC movement it was
# traded for.
#
# "Magnitude" is the load-bearing word, and the criterion originally omitted it.
# mttc_delta = candidate_mttc - baseline_mttc, so an MTTC IMPROVEMENT is NEGATIVE;
# multiplying the un-absoluted delta by the rate put the bar below zero, and the
# comparison then read "MRR above some negative number" -- which a negative mrr_delta
# satisfies. Measured against the pre-fix code: a candidate that regressed HR@10 by
# 0.030 AND MRR by 0.010 while improving MTTC by 4.11 turns was adjudicated
# verdict = win with an EMPTY failed_criteria. At that MTTC movement the bar sat at
# -0.274, licensing an MRR regression larger than this project's entire MRR headroom.
#
# The `mrr_delta > 0.0` clause below is, given abs(), LOGICALLY REDUNDANT and is kept
# deliberately: the bar 0.0667 * abs(mttc_delta) is non-negative, so clearing it already
# implies a positive gain. Mutation-tested -- deleting that clause fails no test, while
# deleting the abs() fails
# test_an_mrr_gain_below_the_magnitude_bar_does_not_buy_an_hr10_regression. It stays
# because it states the INTENT ("there must be a gain to spend") independently of the
# sign convention of mttc_delta, so a future change to how the bar is computed cannot
# silently reintroduce forgiveness on a regression. Do not read it as a second guard.
#
# mttc_delta < 0 is not an edge case: it is the DESIGNED direction of improvement for
# the whole Phase 3 CONV workstream, so the vacuous form was the main path. CONV-03 and
# CLAUDE.md state the principle this criterion enforces -- a recall regression cannot be
# bought with speed.
#
# Deliberately NOT added, and declined by the operator: a hard HR@10 regression floor,
# and scaling the forgiveness threshold with the SIZE of the HR@10 regression. A
# regression of any size stays forgivable once the magnitude-scaled MRR bar is cleared.
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
    # DESCRIPTIVE ONLY. Derived from two measured quantities (a zero SE AND a zero
    # delta), it is never used to fabricate or override any other field on this row. It
    # exists so a reader of the report can see which arms agreed with the baseline on
    # every session, which is the only thing the old degenerate branch was entitled to
    # say.
    is_degenerate: bool
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
            "is_degenerate": self.is_degenerate,
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

    # DESCRIPTIVE ONLY. This tuple no longer gates any computation: it is reported on
    # each row so a reader can see which arms agreed with the baseline on every session,
    # and nothing downstream branches on it.
    #
    # It is conditioned on the DELTA as well as the SE because a zero SE alone does not
    # mean what "degenerate" claims. The bootstrap SE is exactly zero for ANY
    # exactly-uniform per-session improvement -- the delta is then invariant under which
    # sessions are resampled -- so the SE-only form also captured real, large effects. A
    # measured example: a uniform rank-2 -> rank-1 promotion over 200 sessions has SE 0.0
    # at a delta of +0.15, fifteen times the ship floor.
    #
    # Pitfall 5 (a naive `abs(delta) >= mdd` reading 0 >= 0 as True, and so reporting a
    # DETECTABLE difference between a candidate and itself) is handled where it belongs,
    # in classify_verdict: with an empty-of-nothing failed_criteria the row falls through
    # clause 3 to clause 4 and returns NO_DIFFERENCE. That is the correct answer for two
    # identical arms and it is now reached through the general rule rather than through a
    # special case that asserted its own conclusion.
    degenerate = tuple(
        result.standard_error <= ZERO_VARIANCE_TOLERANCE
        and abs(result.delta) <= ZERO_VARIANCE_TOLERANCE
        for result in bootstraps
    )

    # --- D-20 step 2: paired permutation, same pair, a separate RNG stream ---
    # Run UNCONDITIONALLY, once per candidate. The former short-circuit appended a
    # literal 1.0 for degenerate arms; the permutation is cheap and returns an honest
    # Phipson-Smyth answer for identical arms anyway -- every sign-flip assignment of two
    # identical arms yields a statistic tied with the observed one, so the measured
    # p-value is exactly (resamples + 1) / (resamples + 1) = 1.0. Same number, now
    # arrived at by measurement rather than by assertion.
    permutation_p_values = []
    for index, candidate in enumerate(candidates):
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
    #
    # WR-05, decided: a genuinely degenerate arm REMAINS in the Holm family. The family
    # is a property of the experimental DESIGN -- how many arms were submitted for
    # comparison -- so shrinking it after seeing which arms turned out degenerate is a
    # data-dependent family definition. That is anti-conservative, and it is precisely
    # the selection sin the winner's-curse correction below exists to price. What WR-05
    # actually objected to was a SYNTHETIC p-value entering the family; the permutation
    # above is now measured for every arm, so the 1.0 that a degenerate arm contributes
    # is a real answer. An operator who knows in advance that a retained record is not a
    # hypothesis says so BEFORE the run, via `--include` in arena/run_arena.py, which is
    # the a-priori mechanism that makes post-hoc exclusion unnecessary.
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
    #
    # A degenerate arm is counted in k for the same design reason it stays in the Holm
    # family, and the cost of getting this wrong is concrete: the floor-ordering
    # tripwire in tests/test_arena_adjudication.py adjudicates a real arm alongside a
    # deliberately identical "null" arm and depends on k == 2. Excluding the null arm
    # post hoc would set k = 1, expected_max_of_k(1) == 0.0 would remove the correction
    # entirely, and the tripwire would then pass on the RAW delta -- silently disabling
    # the single ordering guarantee this phase exists to provide.
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

        # ONE path, for every arm. There is no degenerate branch: the governing rule is
        # that no emitted field on any row may be a fabricated constant, and the branch
        # that used to sit here set holm_p, the MDD, clears_practical_floor,
        # exchange_rate_ok and failed_criteria to literals while leaving corrected_delta
        # holding the real delta -- a row that contradicted itself, and that inverted the
        # verdict on a genuine +0.15 effect.
        #
        # Two identical arms are still adjudicated correctly here, by measurement:
        # delta 0.0, standard_error 0.0, measured permutation_p 1.0, holm_p 1.0,
        # mdd = 2.801585218112968 * 0.0 = 0.0,
        # corrected_delta = 0.0 - 0.0 * expected_max_of_k(k) = 0.0,
        # clears_practical_floor = (0.0 >= 0.01) = False, and exchange_rate_ok = True
        # because hit_rate_delta == 0.0. So failed_criteria is
        # ("holm_significance", "practical_floor") and classify_verdict returns
        # NO_DIFFERENCE at clause 4 -- identical to what the branch asserted, and now
        # derived. Plan 01-09's identity (win if and only if failed_criteria is empty)
        # therefore still holds without being hand-maintained in a second place.
        holm_p = holm_p_values[index]
        detectable_difference = minimum_detectable_difference(bootstrap.standard_error)
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
        # The third clause -- comparing against the MAGNITUDE of the MTTC movement --
        # is the one that does the work; dropping abs() restores the vacuous form
        # documented above the constant. The `mrr_delta > 0.0` clause is redundant
        # given that, and is retained as an explicit statement of intent; see the
        # comment above EXCHANGE_RATE_PER_MTTC.
        exchange_rate_ok = hit_rate_delta >= 0.0 or (
            mrr_delta > 0.0 and mrr_delta > EXCHANGE_RATE_PER_MTTC * abs(mttc_delta)
        )
        # This mapping holds PASSES, not failures: every value is True when the
        # criterion was SATISFIED. It was previously named for the opposite, in the
        # most safety-critical function in the rig, so a future `if passed[name]`
        # read in the obvious sense would have inverted every verdict in the report.
        passed = {
            "holm_significance": holm_p < SIGNIFICANCE_ALPHA,
            "practical_floor": clears_practical_floor,
            "hr10_exchange_rate": exchange_rate_ok,
        }
        # Filtered from the constant, so the order is fixed by CRITERION_ORDER and
        # never by the order the checks happened to run in.
        failed_criteria = tuple(name for name in CRITERION_ORDER if not passed[name])

        # The single verdict call site. The rule lives in one place, and now every row
        # reaches it the same way.
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
                is_degenerate=is_degenerate,
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
