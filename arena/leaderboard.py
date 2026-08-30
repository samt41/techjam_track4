from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from arena.adjudication import AdjudicationRow
from arena.candidate import CandidateSpec, candidate_overrides
from arena.metrics import (
    SessionOutcome,
    efficiency,
    hit_rate_curve,
    metric_summary,
    scenario_breakout,
    technical_score,
)
from arena.statistics import RESAMPLE_COUNT
from arena.store import (
    BASELINES_ROOT,
    SESSIONS_FILENAME,
    SUMMARY_FILENAME,
    load_sessions,
    write_json,
)

LEADERBOARD_SCHEMA_VERSION = 1

# D-12: the JSON is the source of truth that tests assert against and that Phase 3/4/5
# append to; the Markdown is a generated view. A print-only CLI was rejected because a
# report that exists only in a terminal cannot be cited by the Innovation or Technical
# Execution narrative.
LEADERBOARD_JSON_PATH = BASELINES_ROOT / "leaderboard.json"
LEADERBOARD_MARKDOWN_PATH = Path("experiments/LEADERBOARD.md")

# Enough to identify a candidate by eye in a table cell; the full digest is always
# present in the JSON, so nothing is lost by truncating the DISPLAY column only.
_FINGERPRINT_DISPLAY_LENGTH = 12

# Below this magnitude a fixed 6-dp format would print a real, nonzero value as
# `0.000000`. The value that makes this load-bearing rather than cosmetic is the
# permutation p: its Phipson-Smyth floor is 1/(R+1), which at R=10,000 is 9.999e-05.
_SCIENTIFIC_NOTATION_BELOW = 1e-4

# Three numbers in this report differ from figures quoted elsewhere in .planning/, and
# one correction is deliberately absent. Stating why converts three apparent
# inconsistencies into three demonstrations of statistical care; leaving them unstated
# would make a careful report look careless.
HOW_TO_READ = """\
Three numbers below legitimately differ from figures quoted elsewhere in
`.planning/`, and one correction is deliberately absent. Each is stated here so that
an apparent inconsistency reads as what it is.

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
all of the work: the paired bootstrap SE is `0.003715` where an effectively unpaired
one is `0.025922`.

**4. Per-scenario numbers are deliberately not Holm-corrected.** The Holm family is
the non-baseline candidates against a common baseline within one adjudication event
(D-19). Per-scenario rows are descriptive non-inferiority gates that state their own
sigma; they are not primary hypotheses. Folding four scenarios into the family would
inflate it fourfold, destroy power on the one comparison that decides anything, and
add power to a Boundary bucket of n=10 that can detect nothing regardless. The
omission is deliberate, not an oversight.

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
"""


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    """One arena arm as the leaderboard sees it: identity, provenance, and outcomes."""

    name: str
    fingerprint: str
    run_id: str
    code_revision: str
    code_revision_dirty: bool
    # Ordered pairs rather than a dict, matching CandidateSpec: a dict admits
    # insertion-order variation, which would let one configuration mint two
    # fingerprints.
    overrides: tuple[tuple[str, str], ...]
    sessions: tuple[SessionOutcome, ...]
    # T-01-16b: a synthetic validation control sitting in the same table as a measured
    # configuration is a spoofing surface. The `synthetic-` name prefix and the report's
    # stated convention are the primary mitigation; this field carries the record's own
    # words so the JSON says it too, not only the rendered view.
    provenance: str = ""


def entry_from_record(run_directory: Path) -> CandidateEntry:
    record = json.loads(
        (run_directory / SUMMARY_FILENAME).read_text(encoding="utf-8")
    )
    sessions = load_sessions(run_directory / SESSIONS_FILENAME)
    run_id = str(record.get("run_id", run_directory.name))
    # Fail closed on an unrecorded tree state, exactly as arena.candidate's
    # code_revision_dirty() does: a clean flag that could not be established would let a
    # run with uncommitted changes masquerade as the committed revision it names.
    # The rescued anchor-legacy record reads "unknown_revision" / "unknown" with
    # provenance_complete false; CandidateSpec.validate() admits both literals by
    # design, so the anchor fingerprints through the same path as any other record.
    spec = CandidateSpec(
        name=run_id,
        code_revision=str(record.get("code_revision", "unknown_revision")),
        code_revision_dirty=bool(record.get("code_revision_dirty", True)),
        overrides=candidate_overrides(dict(record.get("overrides", {}))),
        catalog_sha256=str(record.get("catalog_sha256", "unknown")),
        dataset_sha256=str(record.get("dataset_sha256", "unknown")),
    )
    spec.validate()
    return CandidateEntry(
        name=spec.name,
        fingerprint=spec.fingerprint,
        run_id=run_id,
        code_revision=spec.code_revision,
        code_revision_dirty=spec.code_revision_dirty,
        overrides=spec.overrides,
        sessions=sessions,
        provenance=str(record.get("provenance", "")),
    )


def build_leaderboard(
    entries: tuple[CandidateEntry, ...],
    rows: tuple[AdjudicationRow, ...],
    *,
    baseline_fingerprint: str | None,
) -> dict[str, object]:
    summaries = {
        entry.fingerprint: metric_summary(entry.sessions) for entry in entries
    }
    scores = {
        fingerprint: technical_score(summary)
        for fingerprint, summary in summaries.items()
    }
    # D-14. TechnicalScore DESCENDING, tie-broken by ASCENDING fingerprint -- the stable
    # final tie-break discipline of ranking.py:96-113. HR@10 is NEVER the sort key:
    # experiments/RUNS.md is sorted by HR@10 throughout and PROJECT.md names that as
    # actively misleading about the score, because MRR and Efficiency can move a great
    # deal while HR@10 does not move at all. Ties are real here -- TechnicalScore is
    # rounded to 6 dp, so the value lattice has a 1e-6 pitch.
    ordered = sorted(
        entries,
        key=lambda entry: (-scores[entry.fingerprint], entry.fingerprint),
    )

    candidates: list[dict[str, object]] = []
    curves: list[dict[str, object]] = []
    scenarios: list[dict[str, object]] = []
    for entry in ordered:
        summary = summaries[entry.fingerprint]
        candidates.append(
            {
                "name": entry.name,
                "fingerprint": entry.fingerprint,
                "run_id": entry.run_id,
                "code_revision": entry.code_revision,
                "code_revision_dirty": entry.code_revision_dirty,
                "overrides": dict(entry.overrides),
                "provenance": entry.provenance,
                "sample_count": summary.sample_count,
                # hit_rate_at_10, mrr and mttc arrive already 6-dp rounded from
                # metric_summary, and technical_score rounds its own result. Re-rounding
                # any of them here would be a no-op at best and a second rounding step at
                # worst, so they pass through untouched.
                "hit_rate_at_10": summary.hit_rate_at_10,
                "mrr": summary.mrr,
                "mttc": summary.mttc,
                # The ONE exception. arena.metrics.efficiency deliberately returns the
                # UNROUNDED value because the unrounded term is what reproduces the
                # TechnicalScore anchor, mirroring evaluator/local_evaluator.py:279-280.
                # The evaluator applies its 6-dp rounding only at OUTPUT
                # (local_evaluator.py:286), which is why the anchor-legacy summary.json
                # legitimately reads 0.7575 while efficiency() returns
                # 0.7575000000000001. This module is an output boundary, so it rounds
                # exactly where the evaluator rounds. Nothing here may write the
                # unrounded value to a file (T-01-16c).
                "efficiency": round(efficiency(summary), 6),
                "technical_score": scores[entry.fingerprint],
            }
        )
        curves.append(
            {
                "fingerprint": entry.fingerprint,
                # JSON object keys must be strings, so the integer depths are stringified
                # here rather than surviving a json round-trip as ints that come back as
                # strings and silently break a lookup downstream.
                "curve": {
                    str(depth): value
                    for depth, value in hit_rate_curve(entry.sessions).items()
                },
            }
        )
        for scenario in scenario_breakout(entry.sessions):
            # binomial_standard_error is written UNROUNDED, unlike efficiency above.
            # The two rules differ on purpose and must not be "harmonised": the sigma is
            # an analysis quantity asserted at places=12 by plans 01-03 and 01-09
            # (0.09486832980505137 and friends), not a figure the evaluator also emits,
            # so there is no output-rounding convention to match.
            scenarios.append(
                {"fingerprint": entry.fingerprint, **scenario.as_record()}
            )

    observed_resamples = tuple(sorted({row.resamples for row in rows}))
    # Describes what actually produced these rows rather than what the constant says.
    # A committed report generated at a test resample count is exactly the failure
    # T-01-20 guards against, and it is only visible if the number is recorded.
    resample_count = (
        observed_resamples[0] if len(observed_resamples) == 1 else RESAMPLE_COUNT
    )

    return {
        "schema_version": LEADERBOARD_SCHEMA_VERSION,
        # Top level, not per row: a reader must never have to infer which arm the deltas
        # in the adjudication table are measured against (D-13).
        "baseline_fingerprint": baseline_fingerprint,
        # The machine-readable form of the HOW_TO_READ block, so a downstream consumer
        # can check the methodology claims without parsing prose.
        "assumptions": {
            "per_bucket_sigma_source": "bucket-observed p and n (D-15)",
            "winners_curse_sigma_source": (
                "paired-difference bootstrap SE of TechnicalScore (D-21)"
            ),
            "holm_family": (
                "non-baseline candidates against a common baseline (D-19)"
            ),
            "practical_floor": 0.01,
            "resample_count": resample_count,
            "efficiency_rounding": (
                "6 dp at output, matching evaluator/local_evaluator.py:286"
            ),
            "per_scenario_holm_corrected": False,
        },
        "candidates": candidates,
        "hit_rate_curve": curves,
        "scenario_breakout": scenarios,
        # Input order, so the caller owns adjudication presentation. as_record() already
        # returns a plain mapping with `verdict` as a string and `failed_criteria` as a
        # list, so the row serializes directly.
        "adjudication": [row.as_record() for row in rows],
    }


def _display_fingerprint(fingerprint: str) -> str:
    # Truncated in the DISPLAY column only; the full digest is always in the JSON.
    return fingerprint[:_FINGERPRINT_DISPLAY_LENGTH]


def _cell(value: object) -> str:
    # bool before int: bool IS an int in Python, so the int arm would print True as 1.
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    number = float(value)
    if number == 0.0:
        return "0.0"
    if abs(number) < _SCIENTIFIC_NOTATION_BELOW:
        # A permutation p at its Phipson-Smyth floor of 1/(R+1) is 9.999e-05 at
        # R=10,000. Under a flat 6-dp format that real value would print as
        # `0.000000` and read as `p = 0`, which no Monte-Carlo permutation p can be.
        return f"{number:.4e}"
    # Six decimal places throughout, which is why the assumptions block states that
    # experiments/RUNS.md's four-place aggregates agree only after rounding.
    return f"{number:.6f}"


def _table(
    header: tuple[str, ...],
    alignment: tuple[str, ...],
    rows: tuple[str, ...],
) -> str:
    # The `| _none_ |` fallback mirrors run_public.py:308: an empty body would emit a
    # header and separator with nothing under them, which renders as a malformed table
    # rather than as an honest "no rows".
    body = "\n".join(rows) or "| " + " | ".join(["_none_"] * len(header)) + " |"
    return (
        "| " + " | ".join(header) + " |\n"
        "| " + " | ".join(alignment) + " |\n"
        + body
        + "\n"
    )


def render_markdown(payload: dict[str, object]) -> str:
    """Render the committed report. A pure function of the payload -- no I/O, no clock."""
    assumptions = payload["assumptions"]
    candidates = payload["candidates"]
    baseline = payload["baseline_fingerprint"]
    baseline_cell = (
        f"`{_display_fingerprint(baseline)}`" if baseline else "_not set_"
    )
    # Built from the candidate table, which build_leaderboard has already ordered, so
    # the three dependent tables inherit that order without re-deriving it.
    names = {item["fingerprint"]: item["name"] for item in candidates}

    candidate_rows = tuple(
        "| `{name}` | `{fingerprint}` | `{hit_rate}` | `{mrr}` | `{mttc}` |"
        " `{efficiency}` | `{technical_score}` |".format(
            name=item["name"],
            fingerprint=_display_fingerprint(item["fingerprint"]),
            hit_rate=_cell(item["hit_rate_at_10"]),
            mrr=_cell(item["mrr"]),
            mttc=_cell(item["mttc"]),
            efficiency=_cell(item["efficiency"]),
            technical_score=_cell(item["technical_score"]),
        )
        for item in candidates
    )
    candidate_table = _table(
        ("Candidate", "Fingerprint", "HR@10", "MRR", "MTTC", "Efficiency", "TechnicalScore"),
        ("---", "---", "---:", "---:", "---:", "---:", "---:"),
        candidate_rows,
    )

    curve_rows = tuple(
        "| `{name}` | `{at_1}` | `{at_3}` | `{at_5}` | `{at_10}` |".format(
            name=names.get(item["fingerprint"], item["fingerprint"]),
            at_1=_cell(item["curve"]["1"]),
            at_3=_cell(item["curve"]["3"]),
            at_5=_cell(item["curve"]["5"]),
            at_10=_cell(item["curve"]["10"]),
        )
        for item in payload["hit_rate_curve"]
    )
    curve_table = _table(
        ("Candidate", "HR@1", "HR@3", "HR@5", "HR@10"),
        ("---", "---:", "---:", "---:", "---:"),
        curve_rows,
    )

    scenario_rows = tuple(
        "| `{name}` | `{scenario}` | {count} | `{hit_rate}` | `{mrr}` | `{mttc}` |"
        " `{sigma}` | {grade} |".format(
            name=names.get(item["fingerprint"], item["fingerprint"]),
            scenario=item["scenario_type"],
            count=item["sample_count"],
            hit_rate=_cell(item["hit_rate_at_10"]),
            mrr=_cell(item["mrr"]),
            mttc=_cell(item["mttc"]),
            sigma=_cell(item["binomial_standard_error"]),
            grade=_cell(item["decision_grade"]),
        )
        for item in payload["scenario_breakout"]
    )
    scenario_table = _table(
        ("Candidate", "Scenario", "n", "HR@10", "MRR", "MTTC", "binomial sigma", "Decision-grade?"),
        ("---", "---", "---:", "---:", "---:", "---:", "---:", "---"),
        scenario_rows,
    )

    adjudication_rows = tuple(
        "| `{name}` | `{baseline}` | `{delta}` | `[{lower}, {upper}]` | `{permutation_p}` |"
        " `{holm_p}` | `{mdd}` | `{sigma_hat}` | {k} | `{expected_max}` |"
        " `{corrected}` | {floor} | {verdict} | {failed} |".format(
            name=item["candidate_name"],
            baseline=_display_fingerprint(item["baseline_fingerprint"]),
            delta=_cell(item["delta"]),
            lower=_cell(item["ci_lower"]),
            upper=_cell(item["ci_upper"]),
            permutation_p=_cell(item["permutation_p"]),
            holm_p=_cell(item["holm_p"]),
            mdd=_cell(item["minimum_detectable_difference"]),
            sigma_hat=_cell(item["standard_error"]),
            k=item["correction_k"],
            expected_max=_cell(item["expected_max_of_k"]),
            corrected=_cell(item["corrected_delta"]),
            floor=_cell(item["clears_practical_floor"]),
            verdict=item["verdict"],
            failed=(
                "`" + ", ".join(item["failed_criteria"]) + "`"
                if item["failed_criteria"]
                else "_none_"
            ),
        )
        for item in payload["adjudication"]
    )
    adjudication_table = _table(
        (
            "Candidate",
            "Baseline",
            "dTS",
            "95% CI",
            "perm p",
            "Holm p",
            "MDD",
            "sigma-hat",
            "k",
            "E[max k]",
            "corrected dTS",
            "clears floor",
            "verdict",
            "failed criteria",
        ),
        (
            "---",
            "---",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---",
            "---",
            "---",
        ),
        adjudication_rows,
    )

    return (
        "# Arena Leaderboard\n"
        "\n"
        "> **Generated file -- never hand-edit.** `experiments/baselines/leaderboard.json`\n"
        "> is the source of truth; this Markdown is a view rendered from it by\n"
        "> `arena/leaderboard.py`. Regenerate both rather than editing this file.\n"
        ">\n"
        "> Any candidate whose name begins `synthetic-` is a deterministic fixture used\n"
        "> to validate the measurement rig, not a measured agent configuration. It is\n"
        "> listed so the adjudication machinery is demonstrably exercised, and it must\n"
        "> never be read as a real result.\n"
        "\n"
        f"- Schema version: `{payload['schema_version']}`\n"
        f"- Baseline for every delta below: {baseline_cell}\n"
        f"- Resamples per adjudication: `{assumptions['resample_count']}`\n"
        f"- Practical floor: `{assumptions['practical_floor']}` TechnicalScore\n"
        f"- Per-scenario rows Holm-corrected: `{assumptions['per_scenario_holm_corrected']}`\n"
        "\n"
        "## How to read this report\n"
        "\n"
        f"{HOW_TO_READ}"
        "\n"
        "## Candidates\n"
        "\n"
        "Ordered by TechnicalScore descending, tie-broken by ascending fingerprint.\n"
        "\n"
        f"{candidate_table}"
        "\n"
        "## HitRate@K curve\n"
        "\n"
        "Computed from retained session outcomes alone; no agent was invoked.\n"
        "\n"
        f"{curve_table}"
        "\n"
        "## Per-scenario breakout\n"
        "\n"
        "Each sigma is the bucket's own binomial standard error, unrounded. A row that\n"
        "is not decision-grade cannot resolve a one-session swing from noise on its own.\n"
        "\n"
        f"{scenario_table}"
        "\n"
        "## Pairwise adjudication\n"
        "\n"
        "A p-value is a property of a PAIR, not of a candidate, so every row names the\n"
        "baseline it was measured against.\n"
        "\n"
        f"{adjudication_table}"
        "\n"
        "Compare this report with retained rows in `experiments/RUNS.md`.\n"
    )


def write_leaderboard(
    payload: dict[str, object],
    *,
    json_path: Path = LEADERBOARD_JSON_PATH,
    markdown_path: Path = LEADERBOARD_MARKDOWN_PATH,
) -> tuple[Path, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(json_path, payload)
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return (json_path, markdown_path)
