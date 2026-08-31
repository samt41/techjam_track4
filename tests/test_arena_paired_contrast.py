from __future__ import annotations

import ast
import dataclasses
import json
import unittest
from pathlib import Path

from arena.candidate import CandidateSpec
from arena.metrics import binomial_standard_error
from arena.paired_contrast import (
    PairedArm,
    PairedContrastError,
    PairedContrastResult,
    align_on_pair_id,
    arm_from_run,
    mcnemar_exact,
    mcnemar_from_arms,
    paired_contrast,
    render_markdown,
    require_comparable_arms,
    restrict_to_shared_pairs,
    sessions_by_pair,
)
from arena.statistics import minimum_detectable_difference, paired_bootstrap
from tests.arena_fixtures import session

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# Same budget discipline as tests/test_arena_statistics.py and
# tests/test_arena_adjudication.py: every bootstrap in this module runs at a REDUCED
# resample count, and RESAMPLE_COUNT's 10,000 is never passed here. Both values sit well
# above MINIMUM_RESAMPLES, so the percentile interval stays representable.
FAST_RESAMPLES = 200
STABLE_RESAMPLES = 500

_CATALOG = "a" * 64
_PROBE_CORPUS = "b" * 64
_OTHER_CORPUS = "c" * 64
_REVISION = "0" * 40

# The `{corpus_stem}_{index:04d}` form plan 02-03's PAIR_ID_RE shapes and its
# validate_corpus stem check enforces. Written as literals here rather than imported from
# tests/dataset_fixtures.py, which lands in a sibling plan in the same wave.
_PROBE_PAIRS = tuple(f"probe_v1_{index:04d}" for index in range(300))
_FOREIGN_PAIRS = tuple(f"expanded_dev_v1_{index:04d}" for index in range(60))


def spec(
    name: str,
    *,
    dataset_sha256: str = _PROBE_CORPUS,
    catalog_sha256: str = _CATALOG,
    code_revision: str = _REVISION,
    code_revision_dirty: bool = False,
    overrides: tuple[tuple[str, str], ...] = (),
) -> CandidateSpec:
    built = CandidateSpec(
        name=name,
        code_revision=code_revision,
        code_revision_dirty=code_revision_dirty,
        overrides=overrides,
        catalog_sha256=catalog_sha256,
        dataset_sha256=dataset_sha256,
    )
    built.validate()
    return built


def paired_arm(
    label: str,
    *,
    arm: str,
    prefix: str,
    pair_ids: tuple[str, ...],
    ranks: tuple[int | None, ...],
    scenarios: tuple[str, ...] | None = None,
    candidate_spec: CandidateSpec | None = None,
) -> PairedArm:
    """One arm, with a DISTINCT sample_id prefix per arm.

    The prefix is what makes the two arms' `sample_id` sets disjoint, which is both the
    D-46 reality (control and probe rows are different corpus rows) and the reason
    `_require_paired` rejects the arms until they are re-keyed on `pair_id`.
    """
    if scenarios is None:
        scenarios = ("buying",) * len(pair_ids)
    sessions = tuple(
        session(
            f"{prefix}{index:04d}",
            scenario_type=scenarios[index],
            best_rank=rank,
            first_hit_turn=None if rank is None else 2,
        )
        for index, rank in enumerate(ranks)
    )
    built = PairedArm(
        label=label,
        arm=arm,
        spec=candidate_spec if candidate_spec is not None else spec(label),
        corpus_path=Path("data/probe.v1.jsonl"),
        sessions=sessions,
        pair_by_sample=tuple(
            (f"{prefix}{index:04d}", pair_ids[index]) for index in range(len(pair_ids))
        ),
    )
    built.validate()
    return built


# Sixty pairs with a CONSTRUCTED discordance: five where control hits and the probe does
# not (b = 5), three the other way (c = 3), and fifty-two agreements. The exact two-sided
# p is hand-checkable at n = 8: 2 * (1 + 8 + 28 + 56) / 256 = 186/256 = 0.7265625.
_SIXTY = _PROBE_PAIRS[:60]
_CONTROL_60_RANKS = (2,) * 5 + (None,) * 3 + (2,) * 52
_CONTROL_60 = paired_arm(
    "control",
    arm="control",
    prefix="c",
    pair_ids=_SIXTY,
    ranks=_CONTROL_60_RANKS,
)
_PROBE_60 = paired_arm(
    "probe-sonnet",
    arm="probe_sonnet",
    prefix="p",
    pair_ids=_SIXTY,
    ranks=(None,) * 5 + (2,) * 3 + (2,) * 52,
)

# The real D-40 shape for the MEAS-13 cross-check: 300 Sonnet pairs against 100 Haiku
# pairs drawn from the SAME 300 targets. Deliberately NOT a pre-matched 100/100 fixture,
# which would hide the orphan refusal this arrangement exists to exercise.
_SONNET_300 = paired_arm(
    "probe-sonnet",
    arm="probe_sonnet",
    prefix="s",
    pair_ids=_PROBE_PAIRS,
    ranks=(2,) * 300,
)
_HAIKU_100 = paired_arm(
    "probe-haiku",
    arm="probe_haiku",
    prefix="h",
    pair_ids=_PROBE_PAIRS[:100],
    ranks=(None,) * 12 + (2,) * 88,
)


class McNemarTest(unittest.TestCase):
    """The exact two-sided binomial test, against hand-checkable published values."""

    def test_research_verified_table(self) -> None:
        # 02-RESEARCH.md § 7's verified table at n = 300 pairs, psi ~ 8% (b + c = 24).
        # Independently reproduced from exact rationals during execution: e.g. (20, 4) is
        # 2 * 12951 / 2**24 = 12951/8388608 = 0.001543880...
        for b, c, expected in (
            (20, 4, 0.00154),
            (19, 5, 0.00661),
            (18, 6, 0.02266),
            (17, 7, 0.06391),
            (16, 8, 0.15159),
            (14, 10, 0.54126),
        ):
            with self.subTest(b=b, c=c):
                self.assertAlmostEqual(mcnemar_exact(b, c), expected, places=5)

    def test_no_discordant_pairs_is_no_evidence(self) -> None:
        self.assertEqual(mcnemar_exact(0, 0), 1.0)

    def test_symmetric_discordance_is_clamped_to_one(self) -> None:
        # At b == c the doubled tail EXCEEDS 1, so without the clamp the function would
        # return a number that is not a probability while every `p <= alpha` gate still
        # passed. This is also the exchangeability guard: perfectly balanced discordance
        # is the null, and it must never be reported as significant.
        self.assertEqual(mcnemar_exact(5, 5), 1.0)
        self.assertEqual(mcnemar_exact(3, 3), 1.0)
        for count in range(1, 30):
            with self.subTest(count=count):
                self.assertEqual(mcnemar_exact(count, count), 1.0)

    def test_negative_counts_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            mcnemar_exact(-1, 4)
        with self.assertRaises(ValueError):
            mcnemar_exact(4, -1)

    def test_arms_readout_matches_the_bare_function(self) -> None:
        control, probe = align_on_pair_id(
            sessions_by_pair(_CONTROL_60),
            sessions_by_pair(_PROBE_60),
        )
        result = mcnemar_from_arms(control, probe)
        self.assertEqual(result.favouring_control, 5)
        self.assertEqual(result.favouring_probe, 3)
        self.assertEqual(result.discordant, 8)
        self.assertAlmostEqual(result.discordance_rate, 8 / 60, places=12)
        # Sign convention: probe minus control, matching paired_bootstrap's
        # candidate-minus-baseline delta. The probe found two FEWER targets.
        self.assertAlmostEqual(result.hit_rate_delta, -2 / 60, places=12)
        self.assertAlmostEqual(result.p_value, 0.7265625, places=12)
        self.assertEqual(result.p_value, mcnemar_exact(5, 3))


class AlignmentTest(unittest.TestCase):
    """MEAS-11: the re-key happens at the call site and orphans are refused."""

    def test_alignment_reorders_and_rekeys_onto_pair_id(self) -> None:
        control, probe = align_on_pair_id(
            sessions_by_pair(_CONTROL_60),
            sessions_by_pair(_PROBE_60),
        )
        self.assertEqual(len(control), 60)
        self.assertEqual(
            [item.sample_id for item in control],
            sorted(_SIXTY),
        )
        # Both arms now carry the SAME identifiers, which is exactly what _require_paired
        # demands and what the raw arms could never satisfy.
        self.assertEqual(
            [item.sample_id for item in control],
            [item.sample_id for item in probe],
        )

    def test_an_orphan_on_either_side_is_refused(self) -> None:
        control = sessions_by_pair(_CONTROL_60)
        probe = sessions_by_pair(_PROBE_60)
        orphaned_probe = dict(probe)
        del orphaned_probe[_SIXTY[7]]
        with self.assertRaises(ValueError) as raised:
            align_on_pair_id(control, orphaned_probe)
        self.assertIn(_SIXTY[7], str(raised.exception))

        orphaned_control = dict(control)
        del orphaned_control[_SIXTY[11]]
        with self.assertRaises(ValueError) as raised:
            align_on_pair_id(orphaned_control, probe)
        self.assertIn(_SIXTY[11], str(raised.exception))

    def test_raw_arms_are_rejected_by_the_paired_guard(self) -> None:
        # The L-8 proof, and the reason the fix belongs at the call site. The arms as
        # handed in carry different sample_ids by construction (D-46), so the MEAS-04
        # guard refuses them. It is never weakened to make them fit.
        with self.assertRaises(ValueError) as raised:
            paired_bootstrap(
                _CONTROL_60.sessions,
                _PROBE_60.sessions,
                seed=1,
                resamples=FAST_RESAMPLES,
            )
        self.assertIn(
            "paired comparison requires identical sample_id ordering",
            str(raised.exception),
        )

    def test_a_session_without_a_pair_id_is_refused(self) -> None:
        broken = dataclasses.replace(
            _CONTROL_60,
            pair_by_sample=_CONTROL_60.pair_by_sample[:-1],
        )
        with self.assertRaises(PairedContrastError) as raised:
            sessions_by_pair(broken)
        self.assertIn("carries no pair_id", str(raised.exception))


class ArmPartitionTest(unittest.TestCase):
    """`arm_from_run`: one 700-session run becomes three arms, and says so when it cannot."""

    _ROWS = (
        {"sample_id": "r0000", "arm": "control", "pair_id": "probe_v1_0000"},
        {"sample_id": "r0001", "arm": "probe_sonnet", "pair_id": "probe_v1_0000"},
        {"sample_id": "r0002", "arm": "probe_haiku", "pair_id": "probe_v1_0000"},
    )
    _SESSIONS = tuple(
        session(f"r{index:04d}", best_rank=2, first_hit_turn=2) for index in range(3)
    )

    def test_partition_keeps_only_the_requested_arm(self) -> None:
        built = arm_from_run(
            "probe-sonnet",
            arm="probe_sonnet",
            spec=spec("probe-sonnet"),
            corpus_path=Path("data/probe.v1.jsonl"),
            corpus_rows=self._ROWS,
            sessions=self._SESSIONS,
        )
        self.assertEqual([item.sample_id for item in built.sessions], ["r0001"])
        self.assertEqual(built.pair_by_sample, (("r0001", "probe_v1_0000"),))

    def test_an_absent_arm_names_the_arms_that_are_present(self) -> None:
        with self.assertRaises(PairedContrastError) as raised:
            arm_from_run(
                "probe-opus",
                arm="probe_opus",
                spec=spec("probe-opus"),
                corpus_path=Path("data/probe.v1.jsonl"),
                corpus_rows=self._ROWS,
                sessions=self._SESSIONS,
            )
        message = str(raised.exception)
        self.assertIn("probe_opus", message)
        self.assertIn("probe_sonnet", message)
        self.assertIn("control", message)


class GuardTest(unittest.TestCase):
    """The D-45 inverse guard, corrected for D-46's single-corpus three-arm design.

    THE RECONCILIATION, stated here because a future reader will find the contradiction.
    `02-RESEARCH.md:754` and `02-VALIDATION.md`'s "D-45 inverse" row both assume control
    and probe live in SEPARATE corpora and therefore carry DIFFERENT `dataset_sha256`
    values, which would make an equal digest a refusal. D-46 and D-25 lock the opposite
    design -- one 700-session `probe.v1` corpus carrying all three arms in its sample
    rows -- so the same-digest case must PASS, not raise. Requiring differing digests
    would make the phase's primary contrast impossible to express.

    But permitting a shared digest is not permitting a DIFFERENT one. A DIFFERING digest
    must raise by default, because two corpora joined on `pair_id` is precisely the
    silently bogus contrast D-45 exists to prevent. Seven refusals, two passes.
    """

    _CONTROL = _CONTROL_60
    _PROBE = _PROBE_60

    def test_a_differing_configuration_field_is_refused(self) -> None:
        # Any of these differing would confound a VOCABULARY delta with a CONFIGURATION
        # delta, which is the one thing this contrast is built to isolate.
        for field_name, value in (
            ("catalog_sha256", "d" * 64),
            ("code_revision", "1" * 40),
            ("code_revision_dirty", True),
            ("overrides", (("exploration", "tail-only"),)),
        ):
            with self.subTest(field_name=field_name):
                mismatched = dataclasses.replace(
                    self._PROBE,
                    spec=dataclasses.replace(self._PROBE.spec, **{field_name: value}),
                )
                with self.assertRaises(PairedContrastError) as raised:
                    require_comparable_arms(self._CONTROL, mismatched)
                self.assertIn(field_name, str(raised.exception))

    def test_two_arms_on_the_same_arm_label_are_refused(self) -> None:
        same = dataclasses.replace(self._PROBE, arm=self._CONTROL.arm)
        with self.assertRaises(PairedContrastError) as raised:
            require_comparable_arms(self._CONTROL, same)
        self.assertIn("contrasted with itself", str(raised.exception))

    def test_intersecting_sample_ids_are_refused_with_the_count(self) -> None:
        # Overlapping sample ids mean one arm is being contrasted with itself, whatever
        # the labels say.
        overlapping = dataclasses.replace(
            self._PROBE,
            pair_by_sample=self._CONTROL.pair_by_sample,
        )
        with self.assertRaises(PairedContrastError) as raised:
            require_comparable_arms(self._CONTROL, overlapping)
        message = str(raised.exception)
        self.assertIn("60", message)
        self.assertIn("sample_id", message)

    def test_the_same_corpus_case_passes(self) -> None:
        # The D-46 PRIMARY case: identical dataset_sha256, differing arm, disjoint
        # sample ids. This is the phase's headline contrast and it must not raise.
        self.assertEqual(
            self._CONTROL.spec.dataset_sha256,
            self._PROBE.spec.dataset_sha256,
        )
        self.assertIsNone(require_comparable_arms(self._CONTROL, self._PROBE))

    def test_a_differing_dataset_digest_is_refused_by_default(self) -> None:
        foreign = dataclasses.replace(
            self._PROBE,
            spec=dataclasses.replace(self._PROBE.spec, dataset_sha256=_OTHER_CORPUS),
        )
        with self.assertRaises(PairedContrastError) as raised:
            require_comparable_arms(self._CONTROL, foreign)
        message = str(raised.exception)
        self.assertIn(_PROBE_CORPUS, message)
        self.assertIn(_OTHER_CORPUS, message)
        self.assertIn("D-45", message)

    def test_an_explicit_override_permits_a_differing_dataset_digest(self) -> None:
        # The escape hatch exists so the refusal reads as DELIBERATE at the guard. The
        # CLI never sets it without the operator asking for it.
        foreign = dataclasses.replace(
            self._PROBE,
            spec=dataclasses.replace(self._PROBE.spec, dataset_sha256=_OTHER_CORPUS),
        )
        self.assertIsNone(
            require_comparable_arms(
                self._CONTROL,
                foreign,
                allow_cross_corpus=True,
            )
        )


class SharedPairRestrictionTest(unittest.TestCase):
    """MEAS-13 / D-40: narrowing is opt-in, explicit, and counted. Both directions."""

    def test_narrowing_returns_both_sides_and_the_dropped_ids(self) -> None:
        control = sessions_by_pair(_SONNET_300)
        probe = sessions_by_pair(_HAIKU_100)
        narrow_control, narrow_probe, dropped = restrict_to_shared_pairs(control, probe)
        self.assertEqual(len(narrow_control), 100)
        self.assertEqual(len(narrow_probe), 100)
        self.assertEqual(len(dropped), 200)
        self.assertEqual(set(narrow_control), set(narrow_probe))
        self.assertEqual(set(dropped), set(control) - set(probe))

    def test_disjoint_mappings_raise_rather_than_returning_empties(self) -> None:
        control = sessions_by_pair(_SONNET_300)
        foreign = {
            _FOREIGN_PAIRS[index]: item
            for index, item in enumerate(_HAIKU_100.sessions[: len(_FOREIGN_PAIRS)])
        }
        with self.assertRaises(PairedContrastError) as raised:
            restrict_to_shared_pairs(control, foreign)
        self.assertIn("share no pair ids", str(raised.exception))

    def test_the_strict_default_refuses_the_unequal_arms(self) -> None:
        # THE honest default. A silent inner join here would report n = 100 from a corpus
        # of 300 with nothing in the record to say so.
        with self.assertRaises(ValueError) as raised:
            paired_contrast(_SONNET_300, _HAIKU_100, resamples=FAST_RESAMPLES)
        self.assertIn("unmatched pair ids", str(raised.exception))

    def test_opting_in_narrows_and_records_both_counts(self) -> None:
        result = paired_contrast(
            _SONNET_300,
            _HAIKU_100,
            resamples=STABLE_RESAMPLES,
            restrict_to_shared=True,
        )
        self.assertEqual(result.pair_count, 100)
        self.assertEqual(result.dropped_pair_count, 200)
        self.assertEqual(result.restriction, "shared-pairs")
        markdown = render_markdown(result.as_record())
        self.assertIn("100 of 300 matched pairs", markdown)
        self.assertIn("200 pairs carry no", markdown)

    def test_a_strict_result_states_no_drop_in_prose(self) -> None:
        # The negative direction of the same gate: the dropped-count prose must be ABSENT
        # when nothing was dropped, or it would read as boilerplate rather than as a
        # disclosure.
        result = paired_contrast(
            _CONTROL_60,
            _PROBE_60,
            resamples=FAST_RESAMPLES,
        )
        self.assertEqual(result.restriction, "strict")
        self.assertEqual(result.dropped_pair_count, 0)
        self.assertNotIn("matched pairs.**", render_markdown(result.as_record()))


class CrossCorpusPairIdTest(unittest.TestCase):
    """D-45's STRUCTURAL half: the flag is the belt, the id namespacing is the braces."""

    def test_foreign_pair_ids_cannot_be_joined_even_with_the_flag(self) -> None:
        # Plan 02-03 namespaces every pair_id as `{corpus_stem}_{index:04d}` and its
        # validate_corpus REFUSES at load any row whose stem disagrees with its corpus.
        # So two corpora share NO pair id, and the join is unreachable by construction --
        # not merely by policy. That is the half that cannot be forgotten.
        foreign = paired_arm(
            "expanded-dev",
            arm="probe_sonnet",
            prefix="e",
            pair_ids=_FOREIGN_PAIRS,
            ranks=(2,) * 60,
            candidate_spec=spec("expanded-dev", dataset_sha256=_OTHER_CORPUS),
        )
        # The guard is satisfied by the explicit override...
        self.assertIsNone(
            require_comparable_arms(_CONTROL_60, foreign, allow_cross_corpus=True)
        )
        # ...and the join still refuses, because the two id sets are disjoint.
        with self.assertRaises(ValueError) as raised:
            align_on_pair_id(
                sessions_by_pair(_CONTROL_60),
                sessions_by_pair(foreign),
            )
        self.assertIn("unmatched pair ids", str(raised.exception))

        with self.assertRaises(ValueError):
            paired_contrast(
                _CONTROL_60,
                foreign,
                resamples=FAST_RESAMPLES,
                allow_cross_corpus=True,
            )


class ScenarioBreakoutTest(unittest.TestCase):
    """D-30 / L-18: descriptive rows with their sigma, and NO zero-filled scenarios."""

    _MIXED = ("buying",) * 20 + ("browsing",) * 20 + ("intent_override",) * 20

    def test_absent_scenarios_produce_no_row_at_all(self) -> None:
        control = paired_arm(
            "control",
            arm="control",
            prefix="c",
            pair_ids=_SIXTY,
            ranks=(2,) * 60,
            scenarios=self._MIXED,
        )
        probe = paired_arm(
            "probe-sonnet",
            arm="probe_sonnet",
            prefix="p",
            pair_ids=_SIXTY,
            ranks=(None,) * 6 + (2,) * 54,
            scenarios=self._MIXED,
        )
        result = paired_contrast(control, probe, resamples=FAST_RESAMPLES)
        rows = result.scenario_breakout
        self.assertEqual(
            [row["scenario"] for row in rows],
            ["browsing", "buying", "intent_override"],
        )
        # `boundary` is 5% of the official mix and simply absent here. It must produce no
        # row, not a zero-n row -- metric_summary raises on an empty tuple (L-18), and a
        # zero-n row would invite a reader to compare an empty bucket.
        self.assertNotIn("boundary", [row["scenario"] for row in rows])
        for row in rows:
            self.assertEqual(row["pairs"], 20)
            self.assertIn("hit_rate_delta", row)
            self.assertIn("discordant", row)
            self.assertIn("binomial_standard_error", row)
        buying = next(row for row in rows if row["scenario"] == "buying")
        # Six probe misses, all in the first twenty pairs, so `buying` carries all of
        # them. Control hit every pair in the bucket, so its sigma is exactly 0.0.
        self.assertEqual(buying["discordant"], 6)
        self.assertAlmostEqual(buying["hit_rate_delta"], -6 / 20, places=12)
        self.assertEqual(
            buying["binomial_standard_error"],
            binomial_standard_error(1.0, 20),
        )

    def test_a_single_scenario_fixture_produces_exactly_one_row(self) -> None:
        # The negative direction: the other three scenarios are ABSENT, not zero-filled.
        result = paired_contrast(_CONTROL_60, _PROBE_60, resamples=FAST_RESAMPLES)
        rows = result.scenario_breakout
        self.assertEqual([row["scenario"] for row in rows], ["buying"])
        self.assertEqual(rows[0]["pairs"], 60)
        self.assertEqual(rows[0]["discordant"], 8)


class ReadoutTest(unittest.TestCase):
    """D-44: the record states what it is and what it deliberately did not compute."""

    def test_the_readout_reports_its_constructed_discordance(self) -> None:
        result = paired_contrast(_CONTROL_60, _PROBE_60, resamples=STABLE_RESAMPLES)
        self.assertIsInstance(result, PairedContrastResult)
        self.assertEqual(result.pair_count, 60)
        self.assertEqual(result.restriction, "strict")
        self.assertEqual(result.dropped_pair_count, 0)
        self.assertEqual(result.mcnemar.discordant, 8)
        self.assertAlmostEqual(result.mcnemar.p_value, 0.7265625, places=12)
        self.assertEqual(result.bootstrap.resamples, STABLE_RESAMPLES)

    def test_the_mdd_comes_from_the_bootstrap_standard_error(self) -> None:
        # D-25's 0.882/sqrt(n) table is an a-priori SIZING heuristic built on the
        # per-session-difference model arena/statistics.py rejects. The reported number is
        # the measured one.
        result = paired_contrast(_CONTROL_60, _PROBE_60, resamples=STABLE_RESAMPLES)
        self.assertEqual(
            result.minimum_detectable_difference,
            minimum_detectable_difference(result.bootstrap.standard_error),
        )

    def test_both_omitted_corrections_are_named_by_the_record(self) -> None:
        result = paired_contrast(_CONTROL_60, _PROBE_60, resamples=FAST_RESAMPLES)
        self.assertEqual(
            result.corrections_omitted,
            ("holm_bonferroni", "winners_curse_correction"),
        )
        markdown = render_markdown(result.as_record())
        for name in result.corrections_omitted:
            self.assertIn(name, markdown)

    def test_an_identical_probe_is_never_reported_as_a_difference(self) -> None:
        # The exchangeability control. A paired test that reports significance on data
        # that carries no effect is the failure this whole module would otherwise hide.
        clone = paired_arm(
            "probe-clone",
            arm="probe_sonnet",
            prefix="p",
            pair_ids=_SIXTY,
            ranks=_CONTROL_60_RANKS,
        )
        result = paired_contrast(_CONTROL_60, clone, resamples=STABLE_RESAMPLES)
        self.assertEqual(result.bootstrap.delta, 0.0)
        self.assertEqual(result.mcnemar.discordant, 0)
        self.assertEqual(result.mcnemar.p_value, 1.0)
        self.assertEqual(result.mcnemar.hit_rate_delta, 0.0)


class DeterminismTest(unittest.TestCase):
    """D-24: content-seeded, never clock-seeded."""

    def test_two_contrasts_serialize_identically(self) -> None:
        first = paired_contrast(_CONTROL_60, _PROBE_60, resamples=STABLE_RESAMPLES)
        second = paired_contrast(_CONTROL_60, _PROBE_60, resamples=STABLE_RESAMPLES)
        self.assertEqual(
            json.dumps(first.as_record(), sort_keys=True),
            json.dumps(second.as_record(), sort_keys=True),
        )
        # Guard against a vacuous pass on two empty payloads.
        self.assertIn("mcnemar", first.as_record())

    def test_the_markdown_view_is_a_pure_function_of_the_payload(self) -> None:
        result = paired_contrast(_CONTROL_60, _PROBE_60, resamples=FAST_RESAMPLES)
        payload = result.as_record()
        self.assertEqual(render_markdown(payload), render_markdown(payload))


class NoCorrectionTest(unittest.TestCase):
    """The AST proof that neither correction is imported OR called -- and it fires."""

    _FORBIDDEN = frozenset({"holm_bonferroni", "winners_curse_correction"})

    def _referenced(self, relative: str) -> set[str]:
        tree = ast.parse(
            (_REPOSITORY_ROOT / relative).read_text(encoding="utf-8"),
            filename=relative,
        )
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                found.update(
                    alias.name for alias in node.names if alias.name in self._FORBIDDEN
                )
            elif isinstance(node, ast.Name) and node.id in self._FORBIDDEN:
                found.add(node.id)
        return found

    def test_paired_contrast_references_neither_correction(self) -> None:
        self.assertEqual(self._referenced("arena/paired_contrast.py"), set())

    def test_the_scanner_fires_on_a_module_that_does_use_them(self) -> None:
        # The two-sided half. A scanner that has only ever returned an empty set is
        # indistinguishable from one that cannot detect anything, and this module's
        # entire D-44 claim rests on it. arena/adjudication.py both imports and CALLS
        # both functions, so it must come back with both names.
        self.assertEqual(
            self._referenced("arena/adjudication.py"),
            set(self._FORBIDDEN),
        )


class CrossCheckContrastTest(unittest.TestCase):
    """MEAS-13: the generator-affinity cross-check, on the real 300/100 shape."""

    def test_the_cross_check_record_and_report_state_both_counts(self) -> None:
        result = paired_contrast(
            _SONNET_300,
            _HAIKU_100,
            resamples=STABLE_RESAMPLES,
            restrict_to_shared=True,
        )
        self.assertEqual(result.pair_count, 100)
        self.assertEqual(result.dropped_pair_count, 200)
        self.assertEqual(result.control_arm, "probe_sonnet")
        self.assertEqual(result.probe_arm, "probe_haiku")
        self.assertGreater(result.minimum_detectable_difference, 0.0)
        self.assertAlmostEqual(result.mcnemar.discordance_rate, 12 / 100, places=12)
        markdown = render_markdown(result.as_record())
        # Roadmap SC4: the D-39/D-49 scoped limitation must appear in the GENERATED
        # report text, not only in the planning documents.
        self.assertIn("Anthropic-family", markdown)
        self.assertIn("100", markdown)
        self.assertIn("200", markdown)

    def test_the_scoped_limitation_is_absent_for_a_non_generator_pair(self) -> None:
        # The negative direction. Claiming a model-family limitation on a control-vs-probe
        # contrast would be a caveat about something the rows do not measure.
        result = paired_contrast(_CONTROL_60, _PROBE_60, resamples=FAST_RESAMPLES)
        self.assertNotIn("Anthropic-family", render_markdown(result.as_record()))


class EmptyBucketTest(unittest.TestCase):
    """L-18: a clear domain error, never metric_summary's bare exception."""

    def test_zero_pairs_raises_a_named_error(self) -> None:
        empty_control = PairedArm(
            label="control",
            arm="control",
            spec=spec("control"),
            corpus_path=Path("data/probe.v1.jsonl"),
            sessions=(),
            pair_by_sample=(),
        )
        empty_probe = dataclasses.replace(
            empty_control,
            label="probe-sonnet",
            arm="probe_sonnet",
            spec=spec("probe-sonnet"),
        )
        with self.assertRaises(PairedContrastError) as raised:
            paired_contrast(empty_control, empty_probe, resamples=FAST_RESAMPLES)
        self.assertIn("at least one matched pair", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
