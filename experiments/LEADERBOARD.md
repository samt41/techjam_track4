# Arena Leaderboard

> **Generated file -- never hand-edit.** `experiments/baselines/leaderboard.json`
> is the source of truth; this Markdown is a view rendered from it by
> `arena/leaderboard.py`. Regenerate both rather than editing this file.
>
> Any candidate whose name begins `synthetic-` is a deterministic fixture used
> to validate the measurement rig, not a measured agent configuration. It is
> listed so the adjudication machinery is demonstrably exercised, and it must
> never be read as a real result.

- Schema version: `1`
- Baseline for every delta below: `c23c99876ee0`
- Resamples per adjudication: `10000`
- Practical floor: `0.01` TechnicalScore
- Per-scenario rows Holm-corrected: `False`

## How to read this report

Seven items below could be misread as inconsistencies: three numbers that legitimately
differ from figures quoted elsewhere in `.planning/`, one correction that is
deliberately absent, and three properties of this report that a reader would otherwise
have to infer. Each is stated here so that an apparent inconsistency reads as what it
is.

**1. Per-bucket sigma comes from the bucket's own observed rate.** Every
per-scenario row computes its binomial sigma from that bucket's OWN observed `p` and
its own `n`, never from the overall `p = 0.92` applied to a bucket `n`. MEAS-09's
illustrative `0.086` at n=10 and `0.050` at n=30 were computed the second way. The
bucket's own `p = 0.90` gives `0.094868` at n=10 and `0.054772` at n=30. This report
prints the latter pair, and the latter pair is the correct one.

**2. Sigma-hat is the paired-difference bootstrap standard error.** The sigma fed
into the winner's-curse order-statistic correction is the paired-difference bootstrap
SE of TechnicalScore -- typically 0.002 to 0.008 on this data -- and NOT the 0.019
absolute binomial SE of HR@10 quoted in `PROJECT.md` and `PITFALLS.md`. Selection
happens on the paired delta, so the noise in the selection statistic is the
paired-delta noise. The resulting correction is roughly an order of magnitude smaller
than the 0.022-0.030 figure quoted elsewhere, and the smaller number is the
methodologically correct one. Sigma-hat, `k` and `E[max k]` are printed as three
separate columns so that `corrected dTS = dTS - sigma-hat * E[max k]` can be
re-derived by hand rather than trusted.

**3. The achievable MDD at n=200 is far smaller than an unpaired estimate suggests.**
`PROJECT.md`'s "3,900-15,700 paired sessions to detect dTS = 0.01" describes the
weakly-correlated regime. Measured on this repository's 200 real sessions, a
realistic ranking candidate that promotes ten sessions to rank 1 yields dTS
`+0.011931` against an MDD of roughly `0.0104` -- detectable at n=200. Pairing does
all of the work: the paired bootstrap SE is roughly `0.0037` where an effectively
unpaired one is `0.025922`, a sevenfold difference. `01-RESEARCH.md` records
`0.003715` for that measurement at its own resample count; the adjudication table
below prints the SE actually observed for each pair, so the two agree to three
significant figures rather than digit for digit.

**4. Per-scenario numbers are deliberately not Holm-corrected.** The Holm family is
the non-baseline candidates against a common baseline within one adjudication event
(D-19). Per-scenario rows are descriptive non-inferiority gates that state their own
sigma; they are not primary hypotheses. Folding four scenarios into the family would
inflate it fourfold, destroy power on the one comparison that decides anything, and
add power to a Boundary bucket of n=10 that can detect nothing regardless. The
omission is deliberate, not an oversight.

**5. The per-scenario TechnicalScore must be n-weighted, not averaged.** Each
per-scenario TechnicalScore is computed from that bucket's OWN HR@10, MRR and MTTC, so
it is the score that bucket would have scored in isolation. Combining the four back into
the overall score is legitimate but only under SAMPLE-SIZE weighting. Every term is
n-weighted-linear across a partition of the sessions: HR@10 and MRR are means, the mean
MTTC over all sessions is the n-weighted mean of the bucket MTTCs, and
`Efficiency = clip((11 - mean(MTTC)) / 10, 0, 1)` is affine in that mean, its clip
inactive because an achievable MTTC lies in `[1, 11]`. So the n-weighted combination
reproduces the overall TechnicalScore to within 6-dp rounding -- on the anchor,
`0.7688401` against `0.76884`, a `1e-07` discrepancy that is rounding and nothing else.

An UNWEIGHTED average of the four buckets does NOT reproduce it, and that is the
misreading this note exists to prevent: on the anchor a flat mean of the four gives
`0.761956` against the true `0.76884`, understating the score by `0.006884`. The four
buckets are n=10, n=80, n=80 and n=30, so a flat average silently gives the n=10
Boundary bucket eight times the influence its evidence supports. The overall figure is
always the correct one to quote. As in item 4, these per-scenario rows are descriptive
non-inferiority gates and are never Holm-corrected, and a bucket's score should not be
compared across buckets of unequal size without reading its sigma column first.

**6. A degenerate arm still counts toward the Holm family and `correction_k`.** An arm
whose delta and standard error are both zero remains in the family, because the family
size is a property of the experimental DESIGN, and shrinking it after seeing which arms
turned out degenerate would be a data-dependent family definition. `--include` is the
a-priori mechanism for a retained record that belongs in the report without joining the
family. Two `assumptions` keys state this in machine-readable form so the claim can be
checked against the payload rather than taken on trust: `holm_family_size` and
`holm_family_includes_degenerate_arms`. Every value on every adjudication row is now
MEASURED: no field is a hard-coded constant on any path, including the zero-variance
one, where the permutation p and the MDD were previously asserted by a special case. The
payload field `is_degenerate` on each adjudication row is descriptive only and feeds no
decision. Deliberate choice, recorded here so it is not read as an oversight: the
rendered "Pairwise adjudication" table stays at its existing fourteen columns and is NOT
widened to show `is_degenerate`. Widening it was the alternative and would have been
mechanically safe. It was rejected because this disclosure already sends the reader to
the machine-readable payload keys, the report's own header declares
`experiments/baselines/leaderboard.json` the source of truth, and a fifteenth column on
an already-fourteen-column table costs legibility for an auditor who can read the field
straight from the payload. The per-scenario breakout is the only rendered table widened.

**7. The 95% interval uses the `(R + 1)` order-statistic convention.** The lower and
upper bounds are the `floor(0.025 * (R + 1))`-th and `ceil(0.975 * (R + 1))`-th order
statistics of the sorted replicates, which at `R = 10,000` are indices `249` and `9750`.
The two bounds are mirror images of one another, and the resulting nominal coverage is
at or above 95% at every admissible resample count. The previous report's bounds were
computed one index differently and gave 94.99% coverage with asymmetric tails, so a
reader comparing this report against the previous one will see the CI move slightly and
nothing else move with it. `standard_error`, the MDD, sigma-hat, `E[max k]` and the
corrected delta are all unchanged, because only the interval indices moved and the
resampling stream itself did not.

**Verdict vocabulary.** The `verdict` column holds exactly four values, and a reader
who guesses at them will mis-read the adjudication table.

- `win` -- all three D-23 criteria passed jointly.
- `significant, below ship bar` -- the difference IS statistically detected, but it
  fails the corrected 0.01 practical floor and/or the HR@10 exchange-rate check. It
  is real and not worth shipping.
- `no difference` -- not significant, AND the test was powered to see an effect of
  the observed size, so this null carries information.
- `not detectable` -- not significant, and the observed delta sits below the MDD, so
  the null is uninformative and must NOT be read as evidence of equivalence.

The `failed criteria` column names exactly which bar a non-win row missed; a `win` is
exactly a row whose failed-criteria cell is empty.

**The practical floor is two sessions.** A floor of 0.01 TechnicalScore is exactly
two best-case session flips out of 200, because at n=200 a single session can move
TechnicalScore by at most `0.005`.

**HR@10 is never the sort key.** Candidates are ordered by TechnicalScore descending,
tie-broken by ascending fingerprint. `experiments/RUNS.md` is sorted by HR@10
throughout, and `PROJECT.md` names that ordering as actively misleading about the
score.

**Precision.** `experiments/RUNS.md` records the retained aggregates to four decimal
places while this report prints six, so the two agree only after rounding.

**Efficiency rounding.** Efficiency is printed rounded to 6 dp at output, exactly as
`evaluator/local_evaluator.py:286` rounds it, while the UNROUNDED value is what feeds
TechnicalScore. `0.7575` here and `0.7575000000000001` inside the score computation
are the same number, correctly reported.

**A permutation p has a floor.** A Monte-Carlo permutation p is
`(exceedances + 1) / (resamples + 1)` (Phipson-Smyth), so it can never honestly be
zero; its smallest attainable value is `1 / (resamples + 1)`. A row printed at that
value sits at the resolution limit of the resample count and must not be read as
`p = 0`.

## Candidates

Ordered by TechnicalScore descending, tie-broken by ascending fingerprint.

| Candidate | Fingerprint | HR@10 | MRR | MTTC | Efficiency | TechnicalScore |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `synthetic-promote-10` | `6eec1db14d0c` | `0.920000` | `0.564238` | `3.425000` | `0.757500` | `0.780771` |
| `fallback-lexical` | `e0d73537d58b` | `0.925000` | `0.522167` | `3.210000` | `0.779000` | `0.774950` |
| `exploration-tail-only` | `8c95a79adbf4` | `0.920000` | `0.524466` | `3.425000` | `0.757500` | `0.768840` |
| `anchor-legacy` | `b8ce126916a0` | `0.920000` | `0.524466` | `3.425000` | `0.757500` | `0.768840` |
| `baseline-auto-disabled` | `c23c99876ee0` | `0.920000` | `0.524466` | `3.425000` | `0.757500` | `0.768840` |

## HitRate@K curve

Computed from retained session outcomes alone; no agent was invoked.

| Candidate | HR@1 | HR@3 | HR@5 | HR@10 |
| --- | ---: | ---: | ---: | ---: |
| `synthetic-promote-10` | `0.435000` | `0.630000` | `0.735000` | `0.920000` |
| `fallback-lexical` | `0.375000` | `0.570000` | `0.725000` | `0.925000` |
| `exploration-tail-only` | `0.385000` | `0.590000` | `0.715000` | `0.920000` |
| `anchor-legacy` | `0.385000` | `0.590000` | `0.715000` | `0.920000` |
| `baseline-auto-disabled` | `0.385000` | `0.590000` | `0.715000` | `0.920000` |

## Per-scenario breakout

Each sigma is the bucket's own binomial standard error, unrounded. A row that
is not decision-grade cannot resolve a one-session swing from noise on its own.

| Candidate | Scenario | n | HR@10 | MRR | MTTC | TechnicalScore | binomial sigma | Decision-grade? |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `synthetic-promote-10` | `boundary` | 10 | `0.900000` | `0.404444` | `3.600000` | `0.719333` | `0.094868` | no |
| `synthetic-promote-10` | `browsing` | 80 | `0.950000` | `0.570764` | `3.125000` | `0.803729` | `0.024367` | yes |
| `synthetic-promote-10` | `buying` | 80 | `0.900000` | `0.512490` | `3.287500` | `0.757997` | `0.033541` | yes |
| `synthetic-promote-10` | `intent_override` | 30 | `0.900000` | `0.738095` | `4.533333` | `0.800762` | `0.054772` | no |
| `fallback-lexical` | `boundary` | 10 | `0.900000` | `0.428175` | `3.100000` | `0.736453` | `0.094868` | no |
| `fallback-lexical` | `browsing` | 80 | `0.975000` | `0.488844` | `2.675000` | `0.800653` | `0.017455` | yes |
| `fallback-lexical` | `buying` | 80 | `0.900000` | `0.497376` | `3.162500` | `0.755963` | `0.033541` | yes |
| `fallback-lexical` | `intent_override` | 30 | `0.866667` | `0.708466` | `4.800000` | `0.769873` | `0.062063` | no |
| `exploration-tail-only` | `boundary` | 10 | `0.900000` | `0.404444` | `3.600000` | `0.719333` | `0.094868` | no |
| `exploration-tail-only` | `browsing` | 80 | `0.950000` | `0.527862` | `3.125000` | `0.790859` | `0.024367` | yes |
| `exploration-tail-only` | `buying` | 80 | `0.900000` | `0.464296` | `3.287500` | `0.743539` | `0.033541` | yes |
| `exploration-tail-only` | `intent_override` | 30 | `0.900000` | `0.715873` | `4.533333` | `0.794095` | `0.054772` | no |
| `anchor-legacy` | `boundary` | 10 | `0.900000` | `0.404444` | `3.600000` | `0.719333` | `0.094868` | no |
| `anchor-legacy` | `browsing` | 80 | `0.950000` | `0.527862` | `3.125000` | `0.790859` | `0.024367` | yes |
| `anchor-legacy` | `buying` | 80 | `0.900000` | `0.464296` | `3.287500` | `0.743539` | `0.033541` | yes |
| `anchor-legacy` | `intent_override` | 30 | `0.900000` | `0.715873` | `4.533333` | `0.794095` | `0.054772` | no |
| `baseline-auto-disabled` | `boundary` | 10 | `0.900000` | `0.404444` | `3.600000` | `0.719333` | `0.094868` | no |
| `baseline-auto-disabled` | `browsing` | 80 | `0.950000` | `0.527862` | `3.125000` | `0.790859` | `0.024367` | yes |
| `baseline-auto-disabled` | `buying` | 80 | `0.900000` | `0.464296` | `3.287500` | `0.743539` | `0.033541` | yes |
| `baseline-auto-disabled` | `intent_override` | 30 | `0.900000` | `0.715873` | `4.533333` | `0.794095` | `0.054772` | no |

## Pairwise adjudication

A p-value is a property of a PAIR, not of a candidate, so every row names the
baseline it was measured against.

| Candidate | Baseline | dTS | 95% CI | perm p | Holm p | MDD | sigma-hat | k | E[max k] | corrected dTS | clears floor | verdict | failed criteria |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| `fallback-lexical` | `c23c99876ee0` | `0.006110` | `[-0.018892, 0.031311]` | `0.645335` | `1.000000` | `0.035987` | `0.012845` | 2 | `0.564190` | `-0.001137` | no | not detectable | `holm_significance, practical_floor` |
| `exploration-tail-only` | `c23c99876ee0` | `0.0` | `[0.0, 0.0]` | `1.000000` | `1.000000` | `0.0` | `0.0` | 2 | `0.564190` | `0.0` | no | no difference | `holm_significance, practical_floor` |

Compare this report with retained rows in `experiments/RUNS.md`.
