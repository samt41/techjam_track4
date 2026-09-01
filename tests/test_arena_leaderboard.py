from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from arena.adjudication import CandidateArm, Verdict, adjudicate
from arena.candidate import CandidateSpec
from arena.leaderboard import (
    CORPUS_BASELINES_SCHEMA_VERSION,
    HOW_TO_READ,
    LEADERBOARD_SCHEMA_VERSION,
    CandidateEntry,
    build_corpus_baselines,
    build_leaderboard,
    entry_from_record,
    render_corpus_baselines_markdown,
    render_markdown,
    spec_from_record,
)
from arena.metrics import SessionOutcome, metric_summary, technical_score
from arena.store import (
    ArenaStoreError,
    SESSIONS_FILENAME,
    SUMMARY_FILENAME,
    write_json,
    write_sessions,
)
from tests.arena_fixtures import ANCHOR_RECORD_DIR, session, sessions_from_ranks


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_JSON = REPOSITORY_ROOT / "experiments" / "baselines" / "leaderboard.json"
COMMITTED_MARKDOWN = REPOSITORY_ROOT / "experiments" / "LEADERBOARD.md"

# This module's job is payload shape and rendering, never resampling. A production-scale
# adjudication belongs to the operator step that generates the committed report; running
# one here would put a ~60 s job inside a suite whose whole value is a sub-5 s feedback
# loop (T-01-20). Two hundred replicates are ample to produce a well-formed row.
FAST_RESAMPLES = 200


def _spec(name: str) -> CandidateSpec:
    spec = CandidateSpec(
        name=name,
        code_revision="unknown_revision",
        code_revision_dirty=True,
        overrides=(),
        catalog_sha256="unknown",
        dataset_sha256="unknown",
    )
    spec.validate()
    return spec


def _entry(
    name: str,
    sessions: tuple[SessionOutcome, ...],
    *,
    provenance: str = "synthetic unit fixture",
) -> CandidateEntry:
    spec = _spec(name)
    return CandidateEntry(
        name=spec.name,
        fingerprint=spec.fingerprint,
        run_id=name,
        code_revision=spec.code_revision,
        code_revision_dirty=spec.code_revision_dirty,
        overrides=spec.overrides,
        sessions=sessions,
        provenance=provenance,
    )


def _score(sessions: tuple[SessionOutcome, ...]) -> float:
    return technical_score(metric_summary(sessions))


# Ten sessions each, every rank and turn fixed, so each TechnicalScore is a closed-form
# number a reader can check by hand rather than a value the rig asserts against itself.
#   rank 1 / turn 1  -> HR 1.0, MRR 1.0, MTTC 1.0, Eff 1.0 -> TS 1.00
#   rank 2 / turn 2  -> HR 1.0, MRR 0.5, MTTC 2.0, Eff 0.9 -> TS 0.83
#   rank 5 / turn 5  -> HR 1.0, MRR 0.2, MTTC 5.0, Eff 0.6 -> TS 0.68
_PERFECT = sessions_from_ranks((1,) * 10, turn=1)
_MIDDLE = sessions_from_ranks((2,) * 10, turn=2)
_WORST = sessions_from_ranks((5,) * 10, turn=5)

# The HR@10-is-not-the-sort-key pair.
#   wide-recall  : every session hits, but at rank 10 on turn 10 -> HR 1.0, TS 0.55
#   sharp-ranking: two sessions miss, the other eight hit at rank 1 on turn 1
#                                                          -> HR 0.8, TS 0.80
_WIDE_RECALL = sessions_from_ranks((10,) * 10, turn=10)
_SHARP_RANKING = sessions_from_ranks((1,) * 8 + (None,) * 2, turn=1)


def _mixed_bucket_sessions() -> tuple[SessionOutcome, ...]:
    # A boundary bucket of ten at p=0.90 (sigma 0.09486832980505137, the same figure the
    # anchor's boundary row carries) beside a browsing bucket of forty-five, so one
    # bucket falls below the n=40 decision-grade floor and the other clears it.
    boundary = tuple(
        session(
            f"b{index:03d}",
            scenario_type="boundary",
            best_rank=None if index == 9 else 1,
            first_hit_turn=None if index == 9 else 1,
        )
        for index in range(10)
    )
    browsing = tuple(
        session(f"w{index:03d}", scenario_type="browsing", best_rank=1, first_hit_turn=1)
        for index in range(45)
    )
    return boundary + browsing


def _anchor_entry() -> CandidateEntry:
    return entry_from_record(ANCHOR_RECORD_DIR)


# The name every identity fixture is written under, so _spec() below derives exactly the
# digest a reader will derive from the written record.
_RECORD_NAME = "identity-fixture"


# D-58: FOUR corpora, not five. D-45 and D-48 both say "five", which predates D-46
# consolidating the probe's three arms (control, probe_sonnet, probe_haiku) into a
# single data/probe.v1.jsonl. Listed deliberately unsorted so the builder's explicit
# sort is exercised rather than inherited from this tuple.
_CORPUS_NAMES = ("probe.v1", "public", "expanded_confirm.v1", "expanded_dev.v1")

# One configuration measured four times, so every row shares this name. A second name
# in the table is the conflation the builder refuses.
_CORPUS_CANDIDATE_NAME = "baseline-auto-disabled"


def _corpus_entry(
    dataset_name: str,
    sessions: tuple[SessionOutcome, ...],
    *,
    name: str = _CORPUS_CANDIDATE_NAME,
) -> CandidateEntry:
    """One candidate as measured against one corpus.

    The specs differ ONLY in dataset_sha256, which is what mints four distinct
    fingerprints for one configuration and is exactly why adjudicate() refuses these
    four as arms of a single comparison (D-45, adjudication.py:208-216). Deriving the
    digest from the corpus name keeps the fixture content-seeded rather than
    hand-assigned, so a renamed corpus cannot silently reuse another's identity.
    """
    spec = CandidateSpec(
        name=name,
        code_revision="unknown_revision",
        code_revision_dirty=True,
        overrides=(),
        catalog_sha256="unknown",
        dataset_sha256=hashlib.sha256(dataset_name.encode("utf-8")).hexdigest(),
    )
    spec.validate()
    return CandidateEntry(
        name=spec.name,
        fingerprint=spec.fingerprint,
        run_id=f"corpus-{dataset_name}",
        code_revision=spec.code_revision,
        code_revision_dirty=spec.code_revision_dirty,
        overrides=spec.overrides,
        sessions=sessions,
        provenance="synthetic unit fixture",
    )


def _corpus_rows() -> tuple[tuple[str, CandidateEntry], ...]:
    # Distinct session sets per corpus so the rendered rows are distinguishable and a
    # transposed pairing would show up as a wrong TechnicalScore rather than as a tie.
    outcomes = (_PERFECT, _MIDDLE, _WORST, _mixed_bucket_sessions())
    return tuple(
        (dataset_name, _corpus_entry(dataset_name, sessions))
        for dataset_name, sessions in zip(_CORPUS_NAMES, outcomes)
    )


def _write_record(directory: Path, *, fingerprint: str | None = None) -> None:
    """Write a minimal valid record; `fingerprint=None` omits the key entirely.

    One builder for all three identity cases -- drifted, absent and matching -- so the
    only thing that varies between them is the stored digest.
    """
    write_sessions(directory / SESSIONS_FILENAME, sessions_from_ranks((2,) * 4))
    record: dict[str, object] = {
        "run_id": _RECORD_NAME,
        "candidate_name": _RECORD_NAME,
        "code_revision": "unknown_revision",
        "code_revision_dirty": True,
        "overrides": {},
        "catalog_sha256": "unknown",
        "dataset_sha256": "unknown",
    }
    if fingerprint is not None:
        record["fingerprint"] = fingerprint
    write_json(directory / SUMMARY_FILENAME, record)


class LeaderboardPayloadTest(unittest.TestCase):
    def test_top_level_keys_are_exactly_the_four_tables_plus_metadata(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        self.assertEqual(
            sorted(payload),
            [
                "adjudication",
                "assumptions",
                "baseline_fingerprint",
                "candidates",
                "hit_rate_curve",
                "scenario_breakout",
                "schema_version",
            ],
        )
        self.assertEqual(payload["schema_version"], LEADERBOARD_SCHEMA_VERSION)
        self.assertEqual(LEADERBOARD_SCHEMA_VERSION, 1)

    def test_duplicate_entry_fingerprints_are_rejected(self) -> None:
        entry = _entry("duplicate", _PERFECT)
        with self.assertRaises(ArenaStoreError) as raised:
            build_leaderboard((entry, entry), (), baseline_fingerprint=None)
        self.assertIn("unique fingerprints", str(raised.exception))

    def test_empty_adjudication_reports_no_resample_count(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        self.assertIsNone(payload["assumptions"]["resample_count"])

    def test_mixed_adjudication_resample_counts_are_rejected(self) -> None:
        baseline = _entry("base", sessions_from_ranks((2,) * 12))
        first = _entry("first", sessions_from_ranks((1,) + (2,) * 11))
        second = _entry("second", sessions_from_ranks((1, 1) + (2,) * 10))
        first_row = adjudicate(
            CandidateArm(_spec("base"), baseline.sessions),
            (CandidateArm(_spec("first"), first.sessions),),
            resamples=40,
        )[0]
        second_row = adjudicate(
            CandidateArm(_spec("base"), baseline.sessions),
            (CandidateArm(_spec("second"), second.sessions),),
            resamples=FAST_RESAMPLES,
        )[0]
        with self.assertRaises(ArenaStoreError) as raised:
            build_leaderboard(
                (baseline, first, second),
                (first_row, second_row),
                baseline_fingerprint=baseline.fingerprint,
            )
        self.assertIn("resample count", str(raised.exception))

    def test_efficiency_is_rounded_at_output_like_the_evaluator(self) -> None:
        # arena.metrics.efficiency returns 0.7575000000000001 on the anchor because the
        # unrounded term is what reproduces the TechnicalScore. The evaluator rounds the
        # same value to 6 dp for OUTPUT, so the committed payload must read 0.7575
        # exactly. A payload carrying the float tail fails this test (T-01-16c).
        payload = build_leaderboard(
            (_anchor_entry(),), (), baseline_fingerprint=None
        )
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["efficiency"], 0.7575)
        self.assertEqual(repr(candidate["efficiency"]), "0.7575")
        self.assertEqual(candidate["technical_score"], 0.76884)

    def test_scenario_sigma_is_written_unrounded(self) -> None:
        # The opposite rule to efficiency above, and the two must never be harmonised:
        # the per-bucket sigma is an analysis quantity asserted at places=12 elsewhere in
        # this phase, not a figure the evaluator also emits.
        payload = build_leaderboard(
            (_entry("mixed", _mixed_bucket_sessions()),), (), baseline_fingerprint=None
        )
        boundary = payload["scenario_breakout"][0]
        self.assertEqual(boundary["scenario_type"], "boundary")
        self.assertAlmostEqual(
            boundary["binomial_standard_error"], 0.09486832980505137, places=12
        )
        self.assertNotEqual(boundary["binomial_standard_error"], 0.094868)

    def test_scenario_rows_carry_a_technical_score(self) -> None:
        # SC1: TechnicalScore is a column per scenario, not only overall. Asserted
        # against technical_score(metric_summary(<that bucket's sessions>)) recomputed
        # from the sessions rather than against the row's own numbers, so the row cannot
        # satisfy this by being internally consistent with a wrong grouping.
        sessions = _mixed_bucket_sessions()
        payload = build_leaderboard(
            (_entry("mixed", sessions),), (), baseline_fingerprint=None
        )
        rows = payload["scenario_breakout"]
        self.assertEqual(
            sorted(rows[0]),
            [
                "binomial_standard_error",
                "decision_grade",
                "fingerprint",
                "hit_rate_at_10",
                "mrr",
                "mttc",
                "sample_count",
                "scenario_type",
                "technical_score",
            ],
        )
        for row in rows:
            bucket = tuple(
                item for item in sessions if item.scenario_type == row["scenario_type"]
            )
            with self.subTest(scenario=row["scenario_type"]):
                self.assertEqual(
                    row["technical_score"], technical_score(metric_summary(bucket))
                )

    def test_the_scenario_technical_score_is_bucket_local(self) -> None:
        # The bucket score is computed from the bucket's OWN metrics, so recombining the
        # four into the overall score requires SAMPLE-SIZE weighting. Every term is
        # n-weighted-linear across a partition -- HR@10 and MRR are means, mean MTTC is a
        # mean, and Efficiency is affine in it with an inactive clip -- so n-weighting
        # reproduces the overall score up to 6-dp rounding, while a FLAT average does
        # not. Both directions are asserted: the equality is what makes the column
        # coherent, and the inequality is the misreading HOW_TO_READ item 5 warns about.
        entry = _anchor_entry()
        payload = build_leaderboard((entry,), (), baseline_fingerprint=None)
        rows = payload["scenario_breakout"]
        self.assertEqual(len(rows), 4)
        self.assertNotEqual(
            len({row["sample_count"] for row in rows}),
            1,
            "buckets must differ in size or the weighting distinction is vacuous",
        )
        overall = technical_score(metric_summary(entry.sessions))
        total = sum(row["sample_count"] for row in rows)
        n_weighted = (
            sum(row["sample_count"] * row["technical_score"] for row in rows) / total
        )
        flat = sum(row["technical_score"] for row in rows) / len(rows)
        # Rounding only: each bucket score and the overall score are each 6-dp rounded.
        self.assertAlmostEqual(n_weighted, overall, places=6)
        # The flat average is wrong by far more than rounding, and materially so -- it
        # exceeds the 0.01 practical floor's own order of magnitude.
        self.assertNotAlmostEqual(flat, overall, places=6)
        self.assertGreater(abs(flat - overall), 0.001)
        # Non-vacuity guard: still the same score to within a loose bound, so the test
        # cannot pass on a nonsense value.
        self.assertLess(abs(flat - overall), 0.05)

    def test_decision_grade_is_false_below_forty_samples(self) -> None:
        payload = build_leaderboard(
            (_entry("mixed", _mixed_bucket_sessions()),), (), baseline_fingerprint=None
        )
        grades = {
            row["scenario_type"]: (row["sample_count"], row["decision_grade"])
            for row in payload["scenario_breakout"]
        }
        self.assertEqual(grades["boundary"], (10, False))
        self.assertEqual(grades["browsing"], (45, True))

    def test_hit_rate_curve_keys_are_strings(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        curve = payload["hit_rate_curve"][0]["curve"]
        self.assertEqual(sorted(curve), ["1", "10", "3", "5"])
        self.assertEqual(curve["1"], 1.0)

    def test_assumptions_block_states_the_methodology(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        assumptions = payload["assumptions"]
        self.assertIs(assumptions["per_scenario_holm_corrected"], False)
        self.assertIn("local_evaluator.py:286", assumptions["efficiency_rounding"])
        self.assertIn("D-15", assumptions["per_bucket_sigma_source"])
        self.assertIn("paired-difference", assumptions["winners_curse_sigma_source"])
        self.assertIn("common baseline", assumptions["holm_family"])
        self.assertEqual(assumptions["practical_floor"], 0.01)

    def test_payload_is_json_serializable_with_sorted_keys(self) -> None:
        # No tuple-keyed mapping, no enum and no dataclass instance may survive into the
        # payload; each would raise here rather than at the operator's write step.
        baseline = _entry("base", sessions_from_ranks((2,) * 12))
        candidate = _entry("cand", sessions_from_ranks((1,) + (2,) * 11))
        rows = adjudicate(
            CandidateArm(_spec("base"), baseline.sessions),
            (CandidateArm(_spec("cand"), candidate.sessions),),
            resamples=FAST_RESAMPLES,
        )
        payload = build_leaderboard(
            (baseline, candidate), rows, baseline_fingerprint=baseline.fingerprint
        )
        serialized = json.dumps(payload, sort_keys=True)
        self.assertIn('"verdict"', serialized)
        self.assertEqual(json.loads(serialized)["schema_version"], 1)

    def test_baseline_fingerprint_is_carried_at_the_top_level(self) -> None:
        entry = _entry("solo", _PERFECT)
        payload = build_leaderboard(
            (entry,), (), baseline_fingerprint=entry.fingerprint
        )
        self.assertEqual(payload["baseline_fingerprint"], entry.fingerprint)


class LeaderboardOrderingTest(unittest.TestCase):
    def test_candidates_are_sorted_by_technical_score_descending(self) -> None:
        self.assertEqual((_score(_PERFECT), _score(_MIDDLE), _score(_WORST)),
                         (1.0, 0.83, 0.68))
        # Fed in deliberately scrambled order so a pass cannot come from input order.
        payload = build_leaderboard(
            (
                _entry("worst", _WORST),
                _entry("perfect", _PERFECT),
                _entry("middle", _MIDDLE),
            ),
            (),
            baseline_fingerprint=None,
        )
        self.assertEqual(
            [item["technical_score"] for item in payload["candidates"]],
            [1.0, 0.83, 0.68],
        )
        self.assertEqual(
            [item["name"] for item in payload["candidates"]],
            ["perfect", "middle", "worst"],
        )

    def test_dependent_tables_follow_the_candidate_order(self) -> None:
        payload = build_leaderboard(
            (_entry("worst", _WORST), _entry("perfect", _PERFECT)),
            (),
            baseline_fingerprint=None,
        )
        order = [item["fingerprint"] for item in payload["candidates"]]
        self.assertEqual([item["fingerprint"] for item in payload["hit_rate_curve"]], order)
        # Scenario rows are grouped per entry, sorted() within each entry.
        seen: list[str] = []
        for row in payload["scenario_breakout"]:
            if row["fingerprint"] not in seen:
                seen.append(row["fingerprint"])
        self.assertEqual(seen, order)

    def test_equal_scores_tie_break_on_ascending_fingerprint(self) -> None:
        # Identical sessions, different names -> identical score, different fingerprints.
        first = _entry("alpha", _MIDDLE)
        second = _entry("bravo", _MIDDLE)
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        for order in ((first, second), (second, first)):
            payload = build_leaderboard(order, (), baseline_fingerprint=None)
            scores = [item["technical_score"] for item in payload["candidates"]]
            self.assertEqual(scores[0], scores[1])
            fingerprints = [item["fingerprint"] for item in payload["candidates"]]
            self.assertEqual(fingerprints, sorted(fingerprints))

    def test_highest_hit_rate_is_not_first_when_its_score_is_not(self) -> None:
        # The tripwire for D-14 / T-01-17. experiments/RUNS.md is sorted by HR@10
        # throughout and PROJECT.md names that as actively misleading about the score;
        # this asserts the leaderboard does not repeat it.
        wide = _entry("wide-recall", _WIDE_RECALL)
        sharp = _entry("sharp-ranking", _SHARP_RANKING)
        payload = build_leaderboard((wide, sharp), (), baseline_fingerprint=None)
        candidates = payload["candidates"]
        self.assertEqual(candidates[0]["name"], "sharp-ranking")
        self.assertEqual(candidates[0]["hit_rate_at_10"], 0.8)
        self.assertEqual(candidates[1]["name"], "wide-recall")
        # The entry that IS first on HR@10 is last on the score that decides anything.
        self.assertEqual(candidates[1]["hit_rate_at_10"], 1.0)
        self.assertGreater(
            candidates[1]["hit_rate_at_10"], candidates[0]["hit_rate_at_10"]
        )
        self.assertGreater(
            candidates[0]["technical_score"], candidates[1]["technical_score"]
        )


class LeaderboardMarkdownTest(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        baseline = _entry("base", sessions_from_ranks((2,) * 12))
        candidate = _entry("cand", sessions_from_ranks((1,) + (2,) * 11))
        rows = adjudicate(
            CandidateArm(_spec("base"), baseline.sessions),
            (CandidateArm(_spec("cand"), candidate.sessions),),
            resamples=FAST_RESAMPLES,
        )
        return build_leaderboard(
            (baseline, candidate), rows, baseline_fingerprint=baseline.fingerprint
        )

    def test_render_is_deterministic(self) -> None:
        payload = self._payload()
        self.assertEqual(render_markdown(payload), render_markdown(payload))

    def test_required_headings_are_present(self) -> None:
        rendered = render_markdown(self._payload())
        for heading in (
            "## How to read this report",
            "## Candidates",
            "## HitRate@K curve",
            "## Per-scenario breakout",
            "## Pairwise adjudication",
        ):
            self.assertIn(heading, rendered)

    def test_required_substrings_are_present(self) -> None:
        rendered = render_markdown(self._payload())
        for needed in (
            "0.094868",
            "0.054772",
            "paired-difference",
            "not Holm-corrected",
            "two best-case session flips",
            "local_evaluator.py:286",
            "experiments/baselines/leaderboard.json",
            "experiments/RUNS.md",
        ):
            self.assertIn(needed, rendered)

    def test_the_illustrative_sigma_is_only_ever_named_as_illustrative(self) -> None:
        # 0.086 is MEAS-09's figure from applying the OVERALL p to a bucket n. It may
        # appear once, in the sentence that says so, and never as a printed sigma.
        rendered = render_markdown(self._payload())
        occurrences = [line for line in rendered.splitlines() if "0.086" in line]
        self.assertEqual(len(occurrences), 1)
        self.assertIn("illustrative", occurrences[0])

    def test_all_four_verdicts_are_defined_in_the_how_to_read_block(self) -> None:
        rendered = render_markdown(self._payload())
        start = rendered.index("## How to read this report")
        block = rendered[start : rendered.index("## Candidates")]
        for value in Verdict:
            self.assertIn(value.value, block)
        self.assertEqual(
            sorted(item.value for item in Verdict),
            ["no difference", "not detectable", "significant, below ship bar", "win"],
        )
        self.assertIn(HOW_TO_READ, rendered)

    def test_numeric_separator_columns_are_right_aligned(self) -> None:
        rendered = render_markdown(self._payload())
        separators = [
            line
            for line in rendered.splitlines()
            if line.startswith("| ---") and set(line) <= set("| -:")
        ]
        self.assertEqual(len(separators), 4)
        for line in separators:
            self.assertIn("---:", line)

    def test_the_scenario_table_renders_a_technical_score_column(self) -> None:
        # SC1 in the rendered view. The column sits between MTTC and binomial sigma so
        # the metric quartet reads in the same order as the Candidates table.
        rendered = render_markdown(self._payload())
        section = rendered[
            rendered.index("## Per-scenario breakout") : rendered.index(
                "## Pairwise adjudication"
            )
        ]
        lines = [line for line in section.splitlines() if line.startswith("|")]
        header, separator = lines[0], lines[1]
        self.assertIn("TechnicalScore", header)
        self.assertIn("| MTTC | TechnicalScore | binomial sigma |", header)

        def cells(line: str) -> list[str]:
            return [part.strip() for part in line.strip().strip("|").split("|")]

        self.assertEqual(len(cells(header)), 9)
        self.assertEqual(len(cells(separator)), 9)
        self.assertEqual(cells(separator)[6], "---:")
        for line in lines[2:]:
            with self.subTest(row=line):
                self.assertEqual(len(cells(line)), 9)

    def test_the_render_ends_with_exactly_one_newline(self) -> None:
        rendered = render_markdown(self._payload())
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))

    def test_an_empty_adjudication_renders_the_none_fallback(self) -> None:
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        rendered = render_markdown(payload)
        adjudication = rendered[rendered.index("## Pairwise adjudication") :]
        self.assertIn("| _none_ |", adjudication)
        self.assertIn("_not set_", rendered)

    def test_the_adjudication_row_prints_its_audit_columns(self) -> None:
        # T-01-13: sigma-hat, k and E[max k] are separate columns so a reader can
        # re-derive corrected dTS rather than trust it.
        rendered = render_markdown(self._payload())
        header = next(
            line for line in rendered.splitlines() if line.startswith("| Candidate | Baseline |")
        )
        for column in ("sigma-hat", "k", "E[max k]", "corrected dTS", "MDD", "verdict"):
            self.assertIn(column, header)
        self.assertNotIn("| _none_ | _none_ |", rendered)

    def test_a_small_probability_never_renders_as_zero(self) -> None:
        # Upstream: a permutation p has a hard Phipson-Smyth floor at 1/(R+1) and can
        # never honestly be 0. At R=10,000 that floor is 9.999e-05, which a flat 6-dp
        # format would print as 0.000000.
        payload = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        payload["adjudication"] = [
            {
                "candidate_name": "tiny",
                "candidate_fingerprint": "f" * 64,
                "baseline_fingerprint": "e" * 64,
                "delta": 0.02,
                "ci_lower": 0.01,
                "ci_upper": 0.03,
                "standard_error": 0.005,
                "permutation_p": 1.0 / 10001.0,
                "holm_p": 1.0 / 10001.0,
                "minimum_detectable_difference": 0.014,
                "candidate_count": 1,
                "correction_k": 1,
                "expected_max_of_k": 0.0,
                "corrected_delta": 0.02,
                "clears_practical_floor": True,
                "is_champion": True,
                "hit_rate_delta": 0.0,
                "mrr_delta": 0.0,
                "mttc_delta": 0.0,
                "exchange_rate_ok": True,
                "verdict": "win",
                "failed_criteria": [],
                "resamples": 10000,
            }
        ]
        rendered = render_markdown(payload)
        self.assertIn("9.9990e-05", rendered)
        self.assertNotIn("`0.000000`", rendered)


class RecordIdentityTest(unittest.TestCase):
    """A record that cannot identify itself is refused when READ, not after commit.

    Every fixture here is built in a temporary directory. The committed records are
    covered by test_every_record_derives_the_fingerprint_it_stores, which can only
    speak for records that already exist -- the gap these methods close.
    """

    def test_a_drifted_reconstruction_is_refused(self) -> None:
        drifted = "0" * 64
        derived = _spec(_RECORD_NAME).fingerprint
        self.assertNotEqual(drifted, derived)
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "drifted-record"
            directory.mkdir()
            _write_record(directory, fingerprint=drifted)
            # Both public readers, not just the one this test happened to reach for:
            # they share a mapping today, and a future edit that gave either its own
            # reconstruction would reopen exactly the divergence this guards.
            for reader in (spec_from_record, entry_from_record):
                with self.subTest(reader=reader.__name__):
                    with self.assertRaises(ArenaStoreError) as raised:
                        reader(directory)
                    message = str(raised.exception)
                    self.assertIn(directory.name, message)
                    self.assertIn(drifted, message)
                    self.assertIn(derived, message)

    def test_a_record_storing_no_fingerprint_is_still_admitted(self) -> None:
        # The rescued anchor-legacy case. That record stores no fingerprint at all --
        # it is a rescue of a provenance-free file and its provenance_complete is
        # false -- so there is nothing for it to diverge from. Hardening the absent-key
        # branch into a refusal would reject the MEAS-16 anchor, which is why the legal
        # case is pinned here beside the illegal one.
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "unfingerprinted-record"
            directory.mkdir()
            _write_record(directory)
            spec = spec_from_record(directory)
            self.assertEqual(len(spec.fingerprint), 64)
            self.assertLessEqual(set(spec.fingerprint), set("0123456789abcdef"))

    def test_a_matching_record_is_admitted(self) -> None:
        # The non-vacuity guard: a check that refused every record, or one that never
        # fired at all, would still pass the refusal test above.
        derived = _spec(_RECORD_NAME).fingerprint
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "matching-record"
            directory.mkdir()
            _write_record(directory, fingerprint=derived)
            self.assertEqual(spec_from_record(directory).fingerprint, derived)
            self.assertEqual(entry_from_record(directory).fingerprint, derived)

    def test_the_assumptions_block_states_the_holm_family_composition(self) -> None:
        # Plan 01-10's WR-05 decision, pinned end to end: a genuinely degenerate arm
        # stays in the family and in correction_k, so the size a reader finds in the
        # payload is the multiplier that was actually applied to every permutation p.
        baseline_sessions = sessions_from_ranks((2,) * 12)
        baseline = _entry("base", baseline_sessions)
        improved = _entry("cand", sessions_from_ranks((1,) + (2,) * 11))
        # Identical to the baseline on every session, so its delta and SE are both zero.
        identical = _entry("null", baseline_sessions)
        rows = adjudicate(
            CandidateArm(_spec("base"), baseline_sessions),
            (
                CandidateArm(_spec("cand"), improved.sessions),
                CandidateArm(_spec("null"), identical.sessions),
            ),
            resamples=FAST_RESAMPLES,
        )
        payload = build_leaderboard(
            (baseline, improved, identical),
            rows,
            baseline_fingerprint=baseline.fingerprint,
        )
        assumptions = payload["assumptions"]
        self.assertEqual(assumptions["holm_family_size"], 2)
        self.assertIs(assumptions["holm_family_includes_degenerate_arms"], True)
        self.assertIn("correction_k", assumptions["holm_family"])
        adjudication = {row["candidate_name"]: row for row in payload["adjudication"]}
        self.assertIs(adjudication["null"]["is_degenerate"], True)
        self.assertIs(adjudication["cand"]["is_degenerate"], False)
        # The degenerate arm did not shrink the family it belongs to.
        self.assertEqual(
            [row["correction_k"] for row in payload["adjudication"]], [2, 2]
        )


class CommittedLeaderboardTest(unittest.TestCase):
    """ROADMAP Success Criteria 1, 2 and 4 asserted against the committed artifact.

    Reads JSON and Markdown only, so it costs milliseconds. The 10,000-replicate
    generation that produced these files is an operator command, never a test.
    """

    def setUp(self) -> None:
        self.payload = json.loads(COMMITTED_JSON.read_text(encoding="utf-8"))

    def _anchor(self) -> dict[str, object]:
        return next(
            item
            for item in self.payload["candidates"]
            if item["run_id"] == "anchor-legacy"
        )

    def test_the_committed_payload_reports_the_anchor_aggregates(self) -> None:
        self.assertEqual(self.payload["schema_version"], 1)
        self.assertGreaterEqual(len(self.payload["candidates"]), 1)
        anchor = self._anchor()
        self.assertEqual(
            (
                anchor["hit_rate_at_10"],
                anchor["mrr"],
                anchor["mttc"],
                anchor["efficiency"],
                anchor["technical_score"],
            ),
            (0.92, 0.524466, 3.425, 0.7575, 0.76884),
        )
        self.assertEqual(anchor["sample_count"], 200)

    def test_the_committed_payload_carries_the_anchor_curve(self) -> None:
        anchor = self._anchor()
        curve = next(
            item["curve"]
            for item in self.payload["hit_rate_curve"]
            if item["fingerprint"] == anchor["fingerprint"]
        )
        self.assertEqual(curve, {"1": 0.385, "3": 0.59, "5": 0.715, "10": 0.92})

    def test_the_committed_payload_carries_the_anchor_scenario_breakout(self) -> None:
        anchor = self._anchor()
        rows = [
            item
            for item in self.payload["scenario_breakout"]
            if item["fingerprint"] == anchor["fingerprint"]
        ]
        self.assertEqual(
            [item["scenario_type"] for item in rows],
            ["boundary", "browsing", "buying", "intent_override"],
        )
        self.assertEqual([item["sample_count"] for item in rows], [10, 80, 80, 30])
        self.assertEqual(
            [item["hit_rate_at_10"] for item in rows], [0.9, 0.95, 0.9, 0.9]
        )
        self.assertEqual(
            [item["decision_grade"] for item in rows], [False, True, True, False]
        )
        for row, expected in zip(
            rows,
            (
                0.09486832980505137,
                0.02436698586202242,
                0.03354101966249684,
                0.054772255750516606,
            ),
        ):
            self.assertAlmostEqual(
                row["binomial_standard_error"], expected, places=12
            )

    def test_the_committed_payload_carries_a_per_scenario_technical_score(self) -> None:
        # SC1 asserted against the COMMITTED artifact, which is what a judge reads.
        rows = self.payload["scenario_breakout"]
        self.assertEqual(len(rows), 20)
        # Reported as the set of offending rows rather than row by row, so a missing key
        # surfaces as ONE failure naming every bucket that lacks it.
        missing = [
            (row["fingerprint"][:12], row["scenario_type"])
            for row in rows
            if "technical_score" not in row
        ]
        self.assertEqual(missing, [])
        anchor = self._anchor()
        anchor_rows = [
            row for row in rows if row["fingerprint"] == anchor["fingerprint"]
        ]
        self.assertEqual(len(anchor_rows), 4)
        implausible = [
            (row["scenario_type"], row["technical_score"])
            for row in anchor_rows
            if not (
                isinstance(row["technical_score"], float)
                and math.isfinite(row["technical_score"])
                and 0.0 < row["technical_score"] < 1.0
            )
        ]
        self.assertEqual(implausible, [])

    def test_the_committed_adjudication_was_generated_at_production_scale(self) -> None:
        rows = self.payload["adjudication"]
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(row["resamples"], 10000)
            for field in (
                "minimum_detectable_difference",
                "standard_error",
                "correction_k",
                "expected_max_of_k",
            ):
                self.assertIsNotNone(row[field])
            # The identity plan 01-09 asserts, checked here too so a regression in
            # classify_verdict cannot reach the committed report unnoticed.
            self.assertEqual(row["verdict"] == "win", row["failed_criteria"] == [])
        self.assertIsNotNone(self.payload["baseline_fingerprint"])

    def test_the_committed_markdown_states_its_conventions(self) -> None:
        rendered = COMMITTED_MARKDOWN.read_text(encoding="utf-8")
        for needed in (
            "## How to read this report",
            "## Candidates",
            "## HitRate@K curve",
            "## Per-scenario breakout",
            "## Pairwise adjudication",
            "synthetic-",
            "never hand-edit",
            "experiments/baselines/leaderboard.json",
        ):
            self.assertIn(needed, rendered)
        for value in Verdict:
            self.assertIn(value.value, rendered)

    def test_the_committed_markdown_matches_the_committed_payload(self) -> None:
        # D-12 and T-01-16: the Markdown is a generated view. A hand-edit or a drifted
        # renderer shows up here rather than in a judge's reading of a stale report.
        self.assertEqual(
            COMMITTED_MARKDOWN.read_text(encoding="utf-8"),
            render_markdown(self.payload),
        )

    def test_every_record_derives_the_fingerprint_it_stores(self) -> None:
        # The regression this pins: arena/arena.py hashed the --name value into the
        # stored fingerprint while arena/leaderboard.py rebuilt the spec from run_id,
        # so a record carried TWO identities and the digest in its own summary.json
        # appeared nowhere in the report. Asserted over the committed records rather
        # than a fixture, because the divergence was only visible on a record whose
        # candidate_name and run_id actually differ -- which no fixture had.
        roots = sorted(
            path
            for path in (REPOSITORY_ROOT / "experiments" / "baselines").iterdir()
            if path.is_dir() and (path / SUMMARY_FILENAME).is_file()
        )
        self.assertGreaterEqual(len(roots), 1)
        checked = 0
        for directory in roots:
            record = json.loads(
                (directory / "summary.json").read_text(encoding="utf-8")
            )
            stored = record.get("fingerprint")
            if stored is None:
                continue  # the rescued anchor stores none, so nothing can diverge
            self.assertEqual(
                stored,
                spec_from_record(directory).fingerprint,
                f"{directory.name} stores a fingerprint it does not derive",
            )
            checked += 1
        # Guards the guard: a loop that silently checked nothing would pass.
        self.assertGreaterEqual(checked, 3)

    def test_the_synthetic_control_is_labelled_as_a_fixture(self) -> None:
        # T-01-16b: a validation control must never be mistaken for a measured result.
        synthetic = [
            item
            for item in self.payload["candidates"]
            if item["name"].startswith("synthetic-")
        ]
        self.assertEqual(len(synthetic), 1)
        self.assertIn("fixture", synthetic[0]["provenance"])
        self.assertIn("promote_hits_to_rank_one", synthetic[0]["provenance"])


class CorpusBaselinesTest(unittest.TestCase):
    """D-53: corpus baselines and leaderboard candidates must not be conflatable.

    Both directions are asserted. A separator that only ever admits its valid input
    is not a separator -- the three conflation routes (a repeated corpus, a repeated
    configuration, and a second candidate name) each have to raise, or the table
    would silently become the same-corpus comparison D-45 refuses.
    """

    def test_rows_are_ordered_by_ascending_dataset_name(self) -> None:
        payload = build_corpus_baselines(_corpus_rows())
        self.assertEqual(
            [row["dataset_name"] for row in payload["corpora"]],
            ["expanded_confirm.v1", "expanded_dev.v1", "probe.v1", "public"],
        )
        # Non-vacuity: the fixture is handed over unsorted, so a pass cannot come
        # from the caller's insertion order.
        self.assertNotEqual(
            [name for name, _ in _corpus_rows()],
            [row["dataset_name"] for row in payload["corpora"]],
        )

    def test_every_row_names_its_own_corpus_and_carries_its_own_score(self) -> None:
        rows = _corpus_rows()
        payload = build_corpus_baselines(rows)
        self.assertEqual(payload["schema_version"], CORPUS_BASELINES_SCHEMA_VERSION)
        self.assertEqual(payload["candidate_name"], _CORPUS_CANDIDATE_NAME)
        by_name = {name: entry for name, entry in rows}
        for row in payload["corpora"]:
            with self.subTest(corpus=row["dataset_name"]):
                entry = by_name[row["dataset_name"]]
                self.assertEqual(row["fingerprint"], entry.fingerprint)
                self.assertEqual(row["run_id"], entry.run_id)
                self.assertEqual(row["name"], _CORPUS_CANDIDATE_NAME)
                # Recomputed from the sessions rather than read back off the row, so a
                # row cannot satisfy this by being internally consistent with the
                # wrong corpus's outcomes.
                self.assertEqual(
                    row["technical_score"], technical_score(metric_summary(entry.sessions))
                )
        # Four distinct configurations by fingerprint -- one per dataset_sha256 -- which
        # is precisely why adjudicate() refuses them as arms.
        self.assertEqual(len({row["fingerprint"] for row in payload["corpora"]}), 4)

    def test_the_render_names_every_corpus_and_states_the_holm_omission(self) -> None:
        rendered = render_corpus_baselines_markdown(
            build_corpus_baselines(_corpus_rows())
        )
        for dataset_name in _CORPUS_NAMES:
            with self.subTest(corpus=dataset_name):
                self.assertIn(dataset_name, rendered)
        # T-02-14: a report that does not say what it omitted is a repudiation
        # surface, so the absent Holm family has to be named in prose rather than
        # merely absent from the numbers.
        self.assertIn("Holm", rendered)
        self.assertIn("winner's-curse", rendered)
        # Both tables are populated, so the `_none_` fallback must not appear at all.
        self.assertNotIn("_none_", rendered)

    def test_the_render_is_deterministic(self) -> None:
        payload = build_corpus_baselines(_corpus_rows())
        self.assertEqual(
            render_corpus_baselines_markdown(payload),
            render_corpus_baselines_markdown(payload),
        )

    def test_the_corpus_count_is_four_and_equals_the_rendered_row_count(self) -> None:
        # D-58 machine-checked rather than left to prose. D-45 and D-48 both say
        # "five", which predates D-46 consolidating the probe's three arms into one
        # file; the payload states the count so the question is answered by the record.
        payload = build_corpus_baselines(_corpus_rows())
        self.assertEqual(payload["corpus_count"], 4)
        self.assertEqual(len(payload["corpora"]), 4)
        rendered = render_corpus_baselines_markdown(payload)
        section = rendered[
            rendered.index("## Per-corpus baseline") : rendered.index(
                "## Per-scenario breakout"
            )
        ]
        table_lines = [line for line in section.splitlines() if line.startswith("|")]
        # Minus the header and the alignment separator.
        self.assertEqual(len(table_lines) - 2, payload["corpus_count"])

    def test_a_duplicate_dataset_name_is_rejected(self) -> None:
        first = _corpus_entry("public", _PERFECT)
        second = _corpus_entry("expanded_dev.v1", _MIDDLE)
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        with self.assertRaises(ArenaStoreError) as raised:
            build_corpus_baselines((("public", first), ("public", second)))
        self.assertIn("unique dataset names", str(raised.exception))

    def test_a_duplicate_fingerprint_is_rejected(self) -> None:
        # Two corpus labels over ONE configuration: the same run reported twice under
        # different corpus names would fabricate a comparison out of one measurement.
        entry = _corpus_entry("public", _PERFECT)
        with self.assertRaises(ArenaStoreError) as raised:
            build_corpus_baselines((("public", entry), ("probe.v1", entry)))
        self.assertIn("unique fingerprints", str(raised.exception))

    def test_a_second_candidate_name_is_rejected(self) -> None:
        # The D-45 misreading arriving by a different door: rows differing in BOTH the
        # corpus and the configuration can be attributed to neither.
        # The fourth corpus name is the one _corpus_rows()[:3] leaves unused, so the
        # dataset names and the fingerprints both stay unique and the ONLY thing wrong
        # with this input is the second candidate name. Reusing an already-present
        # corpus name here would trip the duplicate-name refusal first and leave the
        # mixed-name guard unexercised.
        rows = _corpus_rows()[:3] + (
            (
                "expanded_dev.v1",
                _corpus_entry("expanded_dev.v1", _WORST, name="other-candidate"),
            ),
        )
        self.assertEqual(len({name for name, _ in rows}), 4)
        self.assertEqual(len({entry.fingerprint for _, entry in rows}), 4)
        with self.assertRaises(ArenaStoreError) as raised:
            build_corpus_baselines(rows)
        self.assertIn("one candidate", str(raised.exception))

    def test_an_empty_report_is_refused_rather_than_rendered_empty(self) -> None:
        # The deliberate choice between `_table`'s `_none_` fallback and a refusal.
        # Refusal, because this file's only claim is "one candidate, measured across
        # these corpora"; a header with an empty body would publish that claim with no
        # evidence under it. The fallback stays correct for the leaderboard's
        # adjudication section, which can legitimately have adjudicated nothing.
        with self.assertRaises(ArenaStoreError) as raised:
            build_corpus_baselines(())
        self.assertIn("at least one corpus row", str(raised.exception))

    def test_the_payload_carries_none_of_the_leaderboard_identity_keys(self) -> None:
        # The structural half of the separation. `baseline_fingerprint` and
        # `adjudication` are the leaderboard's identity -- one names the arm every
        # delta is measured against, the other holds the tested family -- and neither
        # has any meaning here, where nothing is tested against anything. Their absence
        # is what makes the two payloads unmixable rather than merely differently
        # named, and it is also proof that build_leaderboard was not called to produce
        # this one.
        payload = build_corpus_baselines(_corpus_rows())
        self.assertEqual(
            sorted(payload),
            ["candidate_name", "corpora", "corpus_count", "reading", "schema_version"],
        )
        self.assertNotIn("adjudication", payload)
        self.assertNotIn("baseline_fingerprint", payload)
        # And the inverse, so the assertion is two-sided rather than a claim about one
        # payload: the leaderboard does carry both, and carries no corpus table.
        leaderboard = build_leaderboard(
            (_entry("solo", _PERFECT),), (), baseline_fingerprint=None
        )
        self.assertIn("adjudication", leaderboard)
        self.assertIn("baseline_fingerprint", leaderboard)
        self.assertNotIn("corpora", leaderboard)
        self.assertNotIn("corpus_count", leaderboard)

    def test_the_payload_is_json_serializable_with_sorted_keys(self) -> None:
        payload = build_corpus_baselines(_corpus_rows())
        serialized = json.dumps(payload, sort_keys=True)
        self.assertEqual(json.loads(serialized)["corpus_count"], 4)


if __name__ == "__main__":
    unittest.main()
