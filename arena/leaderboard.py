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
