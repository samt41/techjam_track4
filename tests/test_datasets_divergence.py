from __future__ import annotations

import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from arena.datasets.divergence import (
    DIVERGENCE_LOG_SCHEMA_VERSION,
    DivergenceRecord,
    DivergenceReport,
    _ARMS,
    _CLASSIFIER_KEYWORDS,
    bucket_summary,
    contradicts,
    coverage,
    divergence_log_path,
    load_divergence_log,
    measure,
    measure_text,
    ordered_tokens,
    pinned_tokens,
    preserves_bucket,
    record_from_report,
    write_divergence_log,
)
from arena.evaluator_bridge import classify_constraint, searchable_text
from starter.shopping_agent.text_normalization import search_terms


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

DIVERGENCE_MODULE = REPOSITORY_ROOT / "arena" / "datasets" / "divergence.py"

# The eleven measured phrases from 02-RESEARCH § "F-06". They are checked against
# the real classifier, never against the transcribed table, so a drift between
# the two shows up as a failure here rather than as a silently wrong pin.
CLASSIFIER_TRAPS: tuple[tuple[str, str], ...] = (
    ("good for everyday work", "use_case"),
    ("no fitting room needed", "style"),
    ("worksite tough", "use_case"),
    ("something narrow-ish", "size"),
    ("my budget is tight", "budget"),
    ("a fabric that breathes", "material"),
    ("a leathery finish", "material"),
    ("blackout curtains vibe", "color"),
    ("the greenery print", "color"),
    ("cottony soft", "material"),
    ("a quiet weekend staple", "feature"),
)


def leather_boot() -> dict[str, object]:
    # Built inline, with the six SEARCH_FIELDS keys plus price. Deliberately not
    # imported from a shared fixture module: this suite must stay runnable with
    # no database, no catalog, and no dependency on a sibling plan's file.
    return {
        "title": "Leather Ankle Boot",
        "features": ["Rubber sole", "Lace up closure"],
        "details": {"Origin": "Imported"},
        "description": "A sturdy boot for everyday wear.",
        "categories": ["Clothing, Shoes & Jewelry", "Women", "Shoes", "Boots"],
        "store": "Northgate Footwear",
        "price": 89.0,
    }


def report(
    *,
    bucket: str = "feature",
    content_token_count: int = 2,
    overlap_ratio: float = 0.0,
    overlapping_tokens: tuple[str, ...] = (),
    shared_bigrams: tuple[str, ...] = (),
    passes: bool = True,
) -> DivergenceReport:
    return DivergenceReport(
        bucket=bucket,
        content_token_count=content_token_count,
        overlap_ratio=overlap_ratio,
        overlapping_tokens=overlapping_tokens,
        shared_bigrams=shared_bigrams,
        passes=passes,
    )


def record(
    *,
    pair_id: str = "probe_v1_0007",
    arm: str = "probe_haiku",
    position: int = 0,
    slot: str = "hard_constraints",
    phrase: str = "a leathery finish",
    **overrides: object,
) -> DivergenceRecord:
    return record_from_report(
        report(**overrides),  # type: ignore[arg-type]
        pair_id=pair_id,
        arm=arm,
        position=position,
        slot=slot,
        phrase=phrase,
    )


class ClassifierAgreementTest(unittest.TestCase):
    def test_transcribed_table_agrees_with_the_real_classifier(self) -> None:
        # T-02-21: _CLASSIFIER_KEYWORDS is a local copy of the harness's clause
        # table. If it drifts, pinned_tokens excludes the wrong substring and
        # every divergence ratio in that bucket is quietly wrong. Pinning the
        # copy to the authority on eleven measured phrases is what makes the copy
        # safe to keep.
        #
        # Spelled out one phrase per line rather than looped, so a failure names
        # the offending phrase directly and so the pinned set is readable as a
        # table. The tuple below is asserted to hold the same eleven pairs, which
        # is what stops the two from drifting apart.
        self.assertEqual(classify_constraint("good for everyday work"), "use_case")
        self.assertEqual(classify_constraint("no fitting room needed"), "style")
        self.assertEqual(classify_constraint("worksite tough"), "use_case")
        self.assertEqual(classify_constraint("something narrow-ish"), "size")
        self.assertEqual(classify_constraint("my budget is tight"), "budget")
        self.assertEqual(classify_constraint("a fabric that breathes"), "material")
        self.assertEqual(classify_constraint("a leathery finish"), "material")
        self.assertEqual(classify_constraint("blackout curtains vibe"), "color")
        self.assertEqual(classify_constraint("the greenery print"), "color")
        self.assertEqual(classify_constraint("cottony soft"), "material")
        self.assertEqual(classify_constraint("a quiet weekend staple"), "feature")
        self.assertEqual(
            CLASSIFIER_TRAPS,
            (
                ("good for everyday work", "use_case"),
                ("no fitting room needed", "style"),
                ("worksite tough", "use_case"),
                ("something narrow-ish", "size"),
                ("my budget is tight", "budget"),
                ("a fabric that breathes", "material"),
                ("a leathery finish", "material"),
                ("blackout curtains vibe", "color"),
                ("the greenery print", "color"),
                ("cottony soft", "material"),
                ("a quiet weekend staple", "feature"),
            ),
        )

    def test_pinned_tokens_are_present_exactly_for_the_routed_buckets(self) -> None:
        for phrase, expected in CLASSIFIER_TRAPS:
            with self.subTest(phrase=phrase):
                pinned = pinned_tokens(phrase)
                if expected == "feature":
                    # The residual default routes on no keyword, so it pins none
                    # and every one of its tokens stays chargeable.
                    self.assertEqual(pinned, frozenset())
                else:
                    self.assertNotEqual(pinned, frozenset())

    def test_the_substring_pin_covers_the_whole_token(self) -> None:
        # The classifier matches by containment, so the token carrying the
        # keyword is what has to be excused -- excusing only the keyword would
        # leave "leathery" chargeable and put a floor under the material bucket.
        self.assertIn("leathery", pinned_tokens("a leathery finish"))
        self.assertIn("blackout", pinned_tokens("blackout curtains vibe"))
        self.assertIn("greenery", pinned_tokens("the greenery print"))

    def test_the_colour_clause_is_the_seven_substring_list(self) -> None:
        # D-51/L-4. The twelve-entry COLOR_RE serves intent_card, not
        # classify_constraint, and its extra colour words route to `feature`.
        clauses = dict(_CLASSIFIER_KEYWORDS)
        self.assertEqual(
            clauses["color"],
            ("color", "black", "white", "blue", "red", "pink", "green"),
        )
        # Two-sided: the five COLOR_RE-only words must NOT reach the colour
        # bucket. If the twelve-entry list were transcribed here instead, this
        # assertion fails rather than passing vacuously.
        for word in ("brown", "gray", "purple", "yellow", "orange"):
            with self.subTest(word=word):
                self.assertNotEqual(classify_constraint(f"a {word} upper"), "color")
                self.assertNotIn(word, clauses["color"])

    def test_the_module_never_names_a_colour_re_only_word(self) -> None:
        source = DIVERGENCE_MODULE.read_text(encoding="utf-8")
        leaked = [
            word
            for word in ("brown", "gray", "grey", "purple", "yellow", "orange")
            if word in source
        ]
        self.assertEqual(
            leaked,
            [],
            "the twelve-colour COLOR_RE list leaked into the gate (D-51/L-4); "
            f"found {leaked}",
        )


class BucketGateTest(unittest.TestCase):
    def test_a_faithful_paraphrase_keeps_its_bucket(self) -> None:
        self.assertTrue(preserves_bucket("100% leather upper", "a leathery finish"))

    def test_a_feature_control_rewritten_into_style_is_rejected(self) -> None:
        # Exactly the F-05 confound the gate exists to reject: the probe would be
        # unlocked by a different asked attribute than its control, so the
        # arm-to-arm delta would mix disclosure mechanics with vocabulary.
        self.assertEqual(classify_constraint("rubber sole"), "feature")
        self.assertEqual(classify_constraint("no fitting room needed"), "style")
        self.assertFalse(preserves_bucket("rubber sole", "no fitting room needed"))

    def test_a_colour_control_rewritten_without_the_word_color_is_rejected(
        self,
    ) -> None:
        # D-51's measured consequence. "color: brown" routes to `color` only
        # because the literal substring `color` is present; drop that word and
        # the paraphrase falls through six clauses to the residual default.
        self.assertEqual(classify_constraint("color: brown"), "color")
        self.assertEqual(classify_constraint("a warm chestnut tone"), "feature")
        self.assertFalse(preserves_bucket("color: brown", "a warm chestnut tone"))


class DivergenceGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.product = leather_boot()

    def test_a_zero_overlap_material_paraphrase_passes(self) -> None:
        # F-06 error 2: zero overlap IS attainable in `material`, because the
        # classifier matches by containment and the token `leathery` appears in
        # 0 of the 50,000 products. The gate is therefore not floor-bounded per
        # bucket, and a passing case has to exist or the gate would be a
        # rejection machine rather than a measurement.
        measured = measure("i want something with a leathery finish", self.product)
        self.assertTrue(measured.passes)
        # assertIs as well as assertTrue: `passes` is a serialized field, and a
        # truthy non-bool would round-trip into the committed log as something
        # other than JSON true.
        self.assertIs(measured.passes, True)
        self.assertEqual(measured.overlapping_tokens, ())
        self.assertEqual(measured.shared_bigrams, ())
        self.assertEqual(measured.bucket, "material")

    def test_token_overlap_fails_the_gate(self) -> None:
        measured = measure("i want a leather boot", self.product)
        self.assertFalse(measured.passes)
        self.assertIs(measured.passes, False)
        self.assertIn("boot", measured.overlapping_tokens)
        self.assertGreater(measured.overlap_ratio, 0.0)

    def test_a_shared_bigram_fails_the_gate(self) -> None:
        measured = measure("must have a rubber sole underneath", self.product)
        self.assertFalse(measured.passes)
        self.assertIs(measured.passes, False)
        self.assertIn("rubber sole", measured.shared_bigrams)

    def test_deduplicated_terms_cannot_express_adjacency(self) -> None:
        # L-15, pinned as a test rather than left in a comment: search_terms
        # collapses repeats, so the token sequence a 2-gram is built from cannot
        # be recovered from it. This is why the adjacency half uses
        # ordered_tokens.
        text = "a boot is a boot"
        self.assertGreater(len(ordered_tokens(text)), len(search_terms(text)))

    def test_adjacency_survives_a_repeat_earlier_in_the_target(self) -> None:
        # The case that makes L-15 bite rather than merely be true. In this
        # target "a" occurs twice, so de-duplication drops the second one and
        # welds "with" to "rubber" -- the verbatim span "with a" then vanishes
        # from the target's 2-grams and a copied phrase scores clean.
        #
        # It also isolates the adjacency half: every content token of the phrase
        # is absent from the target, so the ONLY thing failing this gate is the
        # shared span. Building bigrams from search_terms turns this case green.
        target = "a sturdy boot with a rubber sole"
        measured = measure_text("made with a leathery finish", target)
        self.assertEqual(measured.overlapping_tokens, ())
        self.assertIn("with a", measured.shared_bigrams)
        self.assertFalse(measured.passes)
        deduplicated = search_terms(target)
        self.assertNotIn(
            ("with", "a"),
            set(zip(deduplicated, deduplicated[1:])),
        )

    def test_a_verbatim_title_phrase_scores_full_overlap(self) -> None:
        # The control-arm shape: the harness's own intent_card reuses the
        # target's catalog vocabulary, which is why the measured control mean is
        # 0.9857. A ratio of 1.0 here is the contrast the probe is read against.
        measured = measure("leather ankle boot", self.product)
        self.assertEqual(measured.overlap_ratio, 1.0)
        self.assertFalse(measured.passes)

    def test_an_all_stopword_phrase_does_not_divide_by_zero(self) -> None:
        measured = measure("it is a leather", self.product)
        self.assertEqual(measured.content_token_count, 0)
        self.assertEqual(measured.overlap_ratio, 0.0)

    def test_every_report_satisfies_its_own_invariant(self) -> None:
        for phrase in (
            "i want something with a leathery finish",
            "i want a leather boot",
            "must have a rubber sole underneath",
            "leather ankle boot",
            "it is a leather",
        ):
            with self.subTest(phrase=phrase):
                measure(phrase, self.product).validate()


class ContradictionGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.product = leather_boot()
        self.admitted = frozenset({"leather", "wool", "cotton", "suede"})

    def test_an_asserted_value_the_target_lacks_is_a_contradiction(self) -> None:
        self.assertTrue(contradicts("a woollen upper", self.product, self.admitted))

    def test_an_asserted_value_the_target_has_is_not_a_contradiction(self) -> None:
        self.assertFalse(contradicts("a leathery finish", self.product, self.admitted))

    def test_a_phrase_asserting_nothing_admitted_is_not_a_contradiction(self) -> None:
        self.assertFalse(
            contradicts("a quiet weekend staple", self.product, self.admitted)
        )


class DivergenceLogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.records = (
            record(pair_id="probe_v1_0007", arm="control", position=0),
            record(pair_id="probe_v1_0007", arm="probe_haiku", position=1),
            record(
                pair_id="probe_v1_0001",
                arm="probe_sonnet",
                position=0,
                slot="soft_preferences",
            ),
        )

    def test_log_path_is_versioned_with_its_corpus(self) -> None:
        self.assertEqual(
            divergence_log_path("probe.v1").as_posix(),
            "data/divergence.probe.v1.jsonl",
        )

    def test_round_trip_preserves_every_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "divergence.probe.v1.jsonl"
            write_divergence_log(path, self.records)
            loaded = load_divergence_log(path)
        self.assertEqual(len(loaded), len(self.records))
        expected = sorted(
            (item.as_record() for item in self.records),
            key=lambda row: (
                row["pair_id"],
                row["arm"],
                row["slot"],
                row["position"],
            ),
        )
        self.assertEqual(list(loaded), expected)

    def test_input_order_does_not_change_the_bytes(self) -> None:
        # The log is committed, so a re-derivation that reordered rows would show
        # as a diff and be indistinguishable from a changed measurement.
        shuffled = (self.records[2], self.records[0], self.records[1])
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.jsonl"
            second = Path(directory) / "b.jsonl"
            write_divergence_log(first, self.records)
            write_divergence_log(second, shuffled)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_coverage_returns_one_sorted_key_per_record(self) -> None:
        keys = coverage(self.records)
        self.assertEqual(len(keys), len(self.records))
        self.assertEqual(list(keys), sorted(keys))
        self.assertIn(("probe_v1_0007", "control", "hard_constraints", 0), keys)

    def test_coverage_refuses_a_duplicated_key(self) -> None:
        # An inflated coverage count reads as complete while leaving a real
        # constraint unmeasured, which is worse than a missing one.
        duplicated = (*self.records, self.records[0])
        with self.assertRaises(ValueError) as caught:
            coverage(duplicated)
        message = str(caught.exception)
        self.assertIn("probe_v1_0007", message)
        self.assertIn("2 times", message)

    def test_a_malformed_line_names_the_path_and_the_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "divergence.probe.v1.jsonl"
            write_divergence_log(path, self.records)
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[1] = "{not json"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                load_divergence_log(path)
        message = str(caught.exception)
        self.assertIn(str(path), message)
        self.assertIn("line 2", message)

    def test_a_non_object_line_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "divergence.probe.v1.jsonl"
            path.write_text(json.dumps([1, 2, 3]) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_divergence_log(path)

    def test_validate_refuses_a_ratio_below_zero(self) -> None:
        with self.assertRaises(ValueError):
            record(overlap_ratio=-0.1).validate()

    def test_validate_refuses_a_ratio_above_one(self) -> None:
        with self.assertRaises(ValueError):
            record(overlap_ratio=1.1).validate()

    def test_validate_refuses_a_pass_that_names_an_overlapping_token(self) -> None:
        # T-02-41: the one shape a committed record must not be able to express,
        # because it reads green in the log and is a failed gate in fact.
        with self.assertRaises(ValueError):
            record(passes=True, overlapping_tokens=("boot",)).validate()

    def test_validate_refuses_a_pass_that_names_a_shared_bigram(self) -> None:
        with self.assertRaises(ValueError):
            record(passes=True, shared_bigrams=("rubber sole",)).validate()

    def test_validate_refuses_an_unknown_arm(self) -> None:
        with self.assertRaises(ValueError):
            record(arm="probe_v2").validate()

    def test_validate_refuses_an_unknown_slot(self) -> None:
        with self.assertRaises(ValueError):
            record(slot="constraints").validate()

    def test_validate_refuses_a_negative_position(self) -> None:
        with self.assertRaises(ValueError):
            record(position=-1).validate()

    def test_writing_an_incoherent_record_is_refused(self) -> None:
        broken = DivergenceRecord(
            schema_version=DIVERGENCE_LOG_SCHEMA_VERSION,
            pair_id="probe_v1_0007",
            arm="control",
            position=0,
            slot="hard_constraints",
            phrase="leather ankle boot",
            bucket="material",
            content_token_count=2,
            overlap_ratio=1.0,
            overlapping_tokens=("ankle", "boot"),
            shared_bigrams=(),
            passes=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "divergence.probe.v1.jsonl"
            with self.assertRaises(ValueError):
                write_divergence_log(path, (broken,))

    def test_the_control_arm_is_a_writable_arm(self) -> None:
        # D-34 requires the control arm's overlap to be measured and reported,
        # not merely asserted; a log that could only hold probe rows could not
        # carry the contrast the phase reports.
        record(arm="control").validate()
        self.assertIn("control", _ARMS)

    def test_measure_and_measure_text_agree(self) -> None:
        # The assertion that lets plan 02-11 substitute a committed
        # searchable_text snapshot for the catalog without weakening the sweep.
        product = leather_boot()
        for phrase in (
            "i want something with a leathery finish",
            "i want a leather boot",
            "must have a rubber sole underneath",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    measure(phrase, product),
                    measure_text(phrase, searchable_text(product)),
                )


class ArmVocabularyTest(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("arena.datasets.schema") is not None,
        "arena/datasets/schema.py lands in a sibling plan in the same wave",
    )
    def test_the_local_arm_tuple_matches_the_schema_authority(self) -> None:
        # _ARMS is a transcription of plan 02-03's contract, kept only because
        # the two modules are built in parallel. This becomes a live gate the
        # moment schema.py exists, so the transcription cannot outlive the wave
        # undetected.
        from arena.datasets.schema import ARMS

        self.assertEqual(_ARMS, ARMS)


class BucketSummaryTest(unittest.TestCase):
    def test_an_empty_input_returns_an_empty_summary(self) -> None:
        # L-18: never hand an empty sequence to a statistic, and never fabricate
        # a zero-n row to avoid doing so.
        self.assertEqual(bucket_summary(()), ())

    def test_only_populated_buckets_are_reported(self) -> None:
        reports = (
            report(bucket="material", overlap_ratio=0.0, passes=True),
            report(
                bucket="material",
                overlap_ratio=0.5,
                overlapping_tokens=("boot",),
                passes=False,
            ),
            report(
                bucket="color",
                overlap_ratio=1.0,
                overlapping_tokens=("red",),
                passes=False,
            ),
            report(
                bucket="feature",
                overlap_ratio=0.25,
                overlapping_tokens=("sole",),
                passes=False,
            ),
        )
        summary = bucket_summary(reports)
        self.assertEqual(
            [row["bucket"] for row in summary],
            ["color", "feature", "material"],
        )
        self.assertEqual(len(summary), 3)
        # The three unreported buckets are absent, not present with n == 0.
        reported = {row["bucket"] for row in summary}
        for absent in ("budget", "size", "style", "use_case"):
            with self.subTest(bucket=absent):
                self.assertNotIn(absent, reported)

    def test_each_row_carries_its_own_statistics(self) -> None:
        reports = (
            report(bucket="material", overlap_ratio=0.0, passes=True),
            report(
                bucket="material",
                overlap_ratio=0.5,
                overlapping_tokens=("boot",),
                passes=False,
            ),
        )
        (row,) = bucket_summary(reports)
        self.assertEqual(row["n"], 2)
        self.assertEqual(row["mean_overlap_ratio"], 0.25)
        self.assertEqual(row["median_overlap_ratio"], 0.25)
        self.assertEqual(row["min_overlap_ratio"], 0.0)
        self.assertEqual(row["pass_count"], 1)


RETRIEVAL_NAMES = ("Agent", "LocalProductSearchBackend", "SearchRequest")


def retrieval_references(path: Path) -> tuple[str, ...]:
    # Takes a path rather than hard-coding the module under test, so the scanner
    # can be proven to fire against a synthetic violation in a temporary
    # directory. A scanner that is never shown to fail is not a gate.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in RETRIEVAL_NAMES:
            found.append(f"line {node.lineno}: name {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr in RETRIEVAL_NAMES or node.attr == "search":
                found.append(f"line {node.lineno}: attribute .{node.attr}")
        elif isinstance(node, ast.alias) and node.name in RETRIEVAL_NAMES:
            found.append(f"imported name {node.name}")
    return tuple(sorted(found))


class SolvabilityAbsenceTest(unittest.TestCase):
    def test_the_divergence_module_never_reaches_retrieval(self) -> None:
        # D-35/L-3, machine-checked: solvability is guaranteed by construction
        # because the control arm is the harness's own intent_card over a real
        # catalog product. Re-checking it through retrieval would launder the
        # vocabulary gap the probe exists to expose out of the corpus before
        # anything was measured.
        self.assertEqual(
            retrieval_references(DIVERGENCE_MODULE),
            (),
            "the divergence gate must never construct an agent or call a search "
            "backend; solvability is guaranteed by construction, not re-checked",
        )

    def test_the_scanner_fires_on_a_synthetic_violation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                "from starter.agent import Agent\n"
                "\n"
                "\n"
                "def run(backend: object) -> object:\n"
                "    return backend.search(None)\n",
                encoding="utf-8",
            )
            references = retrieval_references(probe)
        self.assertNotEqual(references, ())
        self.assertTrue(any("Agent" in item for item in references), references)
        self.assertTrue(any(".search" in item for item in references), references)

    def test_the_scanner_passes_a_clean_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                "import json\n\nvalue = json.dumps({})\n", encoding="utf-8"
            )
            self.assertEqual(retrieval_references(probe), ())


if __name__ == "__main__":
    unittest.main()
