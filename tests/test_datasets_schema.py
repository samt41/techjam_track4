from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arena.datasets.schema import (
    MAX_OVERRIDE_TURN,
    MIN_OVERRIDE_TURN,
    PAIR_ID_RE,
    SCENARIO_MIX_TARGET,
    CorpusSchemaError,
    corpus_stem,
    distinct_targets,
    load_corpus,
    scenario_mix,
    validate_corpus,
    write_corpus,
)
from tests.dataset_fixtures import synthetic_corpus, violating_row


OWNING_CORPUS = "probe.v1"
FOREIGN_CORPUS = "expanded_dev.v1"


def corpus_records() -> tuple[dict, ...]:
    return tuple(row.as_record() for row in synthetic_corpus())


class PairIdShapeTest(unittest.TestCase):
    def test_accepts_a_namespaced_zero_padded_id(self) -> None:
        for value in ("probe_v1_0007", "expanded_dev_v1_1999"):
            with self.subTest(value=value):
                self.assertTrue(
                    PAIR_ID_RE.fullmatch(value),
                    "a pair id is {corpus_stem}_{index:04d}; this one is well formed",
                )

    def test_rejects_ids_that_would_collide_across_corpora(self) -> None:
        # A gate that only ever accepts is not a gate. `0007` is the bare counter
        # two corpora would share; the rest are shapes that would break the
        # lexicographic-equals-positional ordering or the stem derivation.
        for value in ("0007", "probe_v1_7", "Probe_v1_0007", "probe.v1_0007"):
            with self.subTest(value=value):
                self.assertIsNone(
                    PAIR_ID_RE.fullmatch(value),
                    "an id without a lowercase corpus stem and four zero-padded "
                    "digits must be refused",
                )

    def test_corpus_stem_is_the_single_derivation(self) -> None:
        self.assertEqual(corpus_stem("probe.v1"), "probe_v1")
        self.assertEqual(corpus_stem("expanded_dev.v1"), "expanded_dev_v1")

    def test_corpus_stem_refuses_an_unversioned_name(self) -> None:
        with self.assertRaises(ValueError) as context:
            corpus_stem("probe")
        self.assertIn("probe", str(context.exception))


class CorpusAcceptanceTest(unittest.TestCase):
    def test_the_owning_corpus_accepts_its_own_rows(self) -> None:
        validate_corpus(corpus_records(), corpus_name=OWNING_CORPUS)

    def test_the_same_rows_are_refused_by_a_foreign_corpus(self) -> None:
        # The loader-side D-45 gate measured in the other direction. Without this
        # half the acceptance above would pass even if validate_corpus ignored
        # corpus_name entirely, leaving the cross-corpus join hole wide open.
        records = corpus_records()
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus(records, corpus_name=FOREIGN_CORPUS)
        message = str(context.exception)
        self.assertIn("probe_v1_", message)
        self.assertIn("expanded_dev_v1", message)

    def test_corpus_name_cannot_be_omitted(self) -> None:
        # Keyword-only with no default, so the stem check cannot be skipped by
        # omission at any call site now or later.
        with self.assertRaises(TypeError):
            validate_corpus(corpus_records())  # type: ignore[call-arg]


class CanonicalSerializationTest(unittest.TestCase):
    def test_write_then_load_round_trips_to_identical_records(self) -> None:
        rows = synthetic_corpus()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            write_corpus(path, rows)
            self.assertEqual(load_corpus(path), tuple(row.as_record() for row in rows))

    def test_writing_the_same_rows_twice_is_byte_identical(self) -> None:
        # sort_keys=True and one trailing newline per row, so sha256_file over the
        # corpus is a stable identity (D-43) rather than a dict-ordering accident.
        rows = synthetic_corpus()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.jsonl"
            second = Path(directory) / "second.jsonl"
            write_corpus(first, rows)
            write_corpus(second, rows)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_load_corpus_names_the_path_and_the_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            path.write_text(
                '{"sample_id": "probe_v1_0000_control"}\n{ not json\n',
                encoding="utf-8",
            )
            with self.assertRaises(CorpusSchemaError) as context:
                load_corpus(path)
            message = str(context.exception)
            self.assertIn(str(path), message)
            self.assertIn("line 2", message)


class BehaviorShapeTest(unittest.TestCase):
    def test_a_non_override_row_carries_no_override_key(self) -> None:
        # `behavior_for` returns a bare {"scenario_type": s} for the other three
        # scenarios (local_evaluator.py:74-87). An explicit "override": null would
        # be a different dict and would break the D-55 byte-identity comparison.
        for record in corpus_records():
            if record["scenario_type"] == "intent_override":
                continue
            self.assertNotIn("override", record["behavior"])

    def test_an_override_row_carries_exactly_the_four_keys(self) -> None:
        overrides = [
            record
            for record in corpus_records()
            if record["scenario_type"] == "intent_override"
        ]
        self.assertTrue(overrides, "the fixture corpus must contain override rows")
        for record in overrides:
            override = record["behavior"]["override"]
            self.assertEqual(
                set(override),
                {"turn", "old_value", "new_value", "message"},
                "the override block must match behavior_for's own four keys",
            )
            self.assertGreaterEqual(override["turn"], MIN_OVERRIDE_TURN)
            self.assertLessEqual(override["turn"], MAX_OVERRIDE_TURN)
            self.assertEqual(
                record["behavior"]["scenario_type"],
                record["scenario_type"],
                "override_applied reads the row's scenario_type while "
                "customer_reply reads the behavior's; they must agree",
            )


class CorpusSummaryTest(unittest.TestCase):
    def test_scenario_mix_matches_the_official_proportions(self) -> None:
        records = corpus_records()
        counts = dict(scenario_mix(records))
        self.assertEqual(sorted(counts), sorted(name for name, _ in SCENARIO_MIX_TARGET))
        for name, share in SCENARIO_MIX_TARGET:
            expected = share * len(records)
            self.assertLessEqual(
                abs(counts[name] - expected),
                1.0,
                f"{name} is {counts[name]} rows against a 40/40/15/5 target of "
                f"{expected:.2f}",
            )

    def test_distinct_targets_is_sorted_and_deduplicated(self) -> None:
        targets = distinct_targets(corpus_records())
        self.assertEqual(list(targets), sorted(set(targets)))
        # Each pair shares one target across its arms, so the corpus has strictly
        # fewer targets than rows.
        self.assertLess(len(targets), len(corpus_records()))


class RowRefusalTest(unittest.TestCase):
    # Each case spells out its own assertRaises rather than sharing a helper: a
    # refusal hidden behind a helper reads as one negative case when it is eight,
    # and the invariant each one closes is different.

    def test_a_null_card_is_refused(self) -> None:
        # Branch 1's predicate at local_evaluator.py:205 is membership only, so a
        # null card takes the authored branch and then crashes at :156. The static
        # validator is load-bearing rather than belt-and-braces.
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus((violating_row("null_card"),), corpus_name=OWNING_CORPUS)
        self.assertIn("intent_card", str(context.exception))

    def test_empty_hard_constraints_are_refused(self) -> None:
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus((violating_row("empty_hard"),), corpus_name=OWNING_CORPUS)
        self.assertIn("hard_constraints", str(context.exception))

    def test_an_over_long_constraint_is_refused(self) -> None:
        # 181 characters: the harness would silently truncate it and the committed
        # corpus would no longer describe what was scored.
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus(
                (violating_row("long_constraint"),), corpus_name=OWNING_CORPUS
            )
        self.assertIn("180", str(context.exception))

    def test_an_override_before_the_reachable_window_is_refused(self) -> None:
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus(
                (violating_row("override_turn_1"),), corpus_name=OWNING_CORPUS
            )
        self.assertIn("between 2 and 10", str(context.exception))

    def test_an_override_after_the_reachable_window_is_refused(self) -> None:
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus(
                (violating_row("override_turn_11"),), corpus_name=OWNING_CORPUS
            )
        self.assertIn("between 2 and 10", str(context.exception))

    def test_an_override_row_without_an_override_block_is_refused(self) -> None:
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus(
                (violating_row("missing_override"),), corpus_name=OWNING_CORPUS
            )
        self.assertIn("override", str(context.exception))

    def test_a_scenario_mismatch_between_row_and_behavior_is_refused(self) -> None:
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus(
                (violating_row("scenario_mismatch"),), corpus_name=OWNING_CORPUS
            )
        self.assertIn("scenario_type", str(context.exception))

    def test_an_override_block_on_a_non_override_row_is_refused(self) -> None:
        # The iff, not merely the if: an override block that can never fire would
        # otherwise sit in a browsing row looking like an authored intent.
        record = violating_row("duplicate_sample_id")
        record["behavior"] = {
            "scenario_type": "buying",
            "override": {
                "turn": 3,
                "old_value": "color: black",
                "new_value": "soft cotton knit throughout",
                "message": "Actually, ignore my earlier preference.",
            },
        }
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus((record,), corpus_name=OWNING_CORPUS)
        self.assertIn("override", str(context.exception))

    def test_an_override_value_absent_from_its_own_card_is_refused(self) -> None:
        # `new_value` is added to `disclosed` at local_evaluator.py:263, so a value
        # the card never declared makes the disclosure bookkeeping diverge from the
        # public path.
        record = violating_row("override_turn_1")
        override = dict(record["behavior"]["override"])
        override["turn"] = 3
        override["new_value"] = "a phrase this card never declares"
        record["behavior"] = {
            "scenario_type": "intent_override",
            "override": override,
        }
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus((record,), corpus_name=OWNING_CORPUS)
        self.assertIn("new_value", str(context.exception))

    def test_a_duplicate_sample_id_is_refused(self) -> None:
        # A corpus-level property: the record is valid alone and only the second
        # occurrence is the violation. `arena/arena.py:149` keys the session to
        # sample join on this field, so a duplicate silently mis-maps it.
        record = violating_row("duplicate_sample_id")
        validate_corpus((record,), corpus_name=OWNING_CORPUS)
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus((record, record), corpus_name=OWNING_CORPUS)
        self.assertIn(str(record["sample_id"]), str(context.exception))


class PairIdNamespacingRefusalTest(unittest.TestCase):
    # The W1 structural guard. Three holes, three separate cases: they are closed
    # by different checks and folding them together would hide which one regressed.

    def test_a_bare_counter_pair_id_is_refused_by_the_row_itself(self) -> None:
        record = violating_row("bare_pair_id")
        self.assertIsNone(
            PAIR_ID_RE.fullmatch(str(record["pair_id"])),
            "a bare counter cannot match PAIR_ID_RE, so the row alone refuses it",
        )
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus((record,), corpus_name=OWNING_CORPUS)
        self.assertIn("0007", str(context.exception))

    def test_a_decoupled_sample_id_is_refused_by_the_row_itself(self) -> None:
        record = violating_row("sample_id_mismatch")
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus((record,), corpus_name=OWNING_CORPUS)
        message = str(context.exception)
        self.assertIn(str(record["sample_id"]), message)
        self.assertIn(
            "sample_id",
            message,
            "sample_id == f'{pair_id}_{arm}' is what makes sample_id uniqueness "
            "and pair_id uniqueness the same property",
        )

    def test_a_foreign_stem_is_refused_only_by_the_loader(self) -> None:
        record = violating_row("foreign_stem")
        # The first half is what makes this case meaningful. Without it the test
        # would still pass if the refusal came from the regex, which would leave
        # the cross-corpus hole open while the suite stayed green.
        self.assertIsNotNone(
            PAIR_ID_RE.fullmatch(str(record["pair_id"])),
            "this row is PAIR_ID_RE-valid and satisfies every per-row invariant; "
            "shape is a per-row property and corpus ownership is not, so no "
            "amount of regex tightening could refuse it",
        )
        self.assertEqual(record["sample_id"], f"{record['pair_id']}_{record['arm']}")
        # Refused only because validate_corpus compares the id's stem against the
        # corpus that owns it. This is the whole reason the loader check exists.
        with self.assertRaises(CorpusSchemaError) as context:
            validate_corpus((record,), corpus_name=OWNING_CORPUS)
        message = str(context.exception)
        self.assertIn("expanded_dev_v1_0007", message)
        self.assertIn("probe_v1", message)

    def test_the_two_corpora_pair_id_sets_are_disjoint(self) -> None:
        # The fixture-level proof of what namespacing buys align_on_pair_id: an
        # inner join across corpora is empty by construction, not by a flag.
        owning = {row.pair_id for row in synthetic_corpus()}
        foreign = {
            row.pair_id for row in synthetic_corpus(corpus_stem="expanded_dev_v1")
        }
        self.assertEqual(owning & foreign, set())


if __name__ == "__main__":
    unittest.main()
