"""What happens after the attempt cap is spent: drop the constraint, record everything.

The property under test is not "the run survives". It is that the reduction is
accounted for completely enough that a reader of the committed corpus can see the
shortfall and its causes without re-running anything -- which is the only reason
dropping is admissible at all (docs/STATUS.md, under `AUTHORING_ATTEMPT_CAP`). So
every test here checks one half of that account: the cap really was exhausted, the
drop reached every arm, a pair that lost a whole list was refused rather than
emitted half-formed, the ledger carries the verbatim reason, and the registry's
numbers equal the rows and the ledger on disk.

The fixtures come from `tests/test_datasets_detached_authoring.py` rather than
being written again. That module already owns a hand-written catalog builder and a
stand-in author whose phrases clear all four gates, and a second copy would drift
from it the first time either was tuned -- the same argument D-54 makes for reusing
STOPWORDS. What is added here is a larger corpus size and one deliberately failing
phrase.

Nothing here spawns a subprocess, opens a catalog artifact, or touches `data/`.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from arena.datasets.authoring import AUTHORING_ATTEMPT_CAP, AuthoringResponse
from arena.datasets.divergence import DivergenceReport, measure_text, preserves_bucket
from arena.datasets.drops import (
    CONSTRAINT_KIND,
    DROP_LOG_SCHEMA_VERSION,
    PAIR_KIND,
    DroppedConstraint,
    RefusedPair,
    drop_log_path,
    load_drop_log,
)
from arena.datasets.generate import (
    AuthoredConstraint,
    ConstraintSlot,
    GenerateError,
    assert_arms_match_on_constraint_ids,
)
from arena.datasets.registry import (
    RegistryError,
    check_pairing,
    check_recorded_counts,
    load_registry,
    load_target_snapshot,
)
from arena.datasets.schema import load_corpus
from tests.test_datasets_detached_authoring import (
    answered_items,
    catalog_lines,
    generate,
    inline_response,
    spawn_is_allowed,
)


# A LARGER corpus than the sibling module's 20 pairs, and the size is load-bearing
# rather than incidental. Refusing a pair removes rows, which moves the corpus's
# scenario mix; at 20 pairs over 44 rows no pair at all can be removed without
# `check_scenario_mix` refusing the result, so a refusal test at that size could
# only ever assert a mix failure. At 40 pairs over 88 rows, 27 of the 40 stay
# inside the 0.02 tolerance. That is a real constraint on the drop mechanism and
# not a fixture detail: a corpus that loses many pairs can still be refused by the
# mix check, which is why nothing here weakens it.
PAIRS = 40
CROSS_CHECK = 8
PRODUCTS = 48

# Two content tokens the fixture catalog puts on EVERY product ("Flexible sole"),
# so appending them makes a phrase fail the D-34 divergence gate against whichever
# target it was written for -- on every one of the three attempts, which is what
# makes the cap genuinely trip rather than trip by luck. Neither token contains a
# `classify_constraint` keyword substring, so the bucket is untouched and the
# rejection is unambiguously D-34's.
OVERLAP_SUFFIX = ", and a flexible sole"

# Item ids are `{pair_id}:{slot code}{position}`. These fixture products all yield
# a four-constraint card -- material and colour hard, two features soft -- so h0/h1
# and s0/s1 exist for every pair.
DROPPED_ITEM = "probe_v1_0000:h0"

# One of the 27 pairs this corpus can lose while still clearing the mix check.
REFUSED_PAIR_ID = "probe_v1_0002"
REFUSED_ITEMS = frozenset({f"{REFUSED_PAIR_ID}:s0", f"{REFUSED_PAIR_ID}:s1"})


def response_for(
    request, *, failing: frozenset[str], alias: str | None = None
) -> AuthoringResponse:
    """The stand-in author, with the named items answered so they cannot pass D-34."""

    base = inline_response(request)
    if request.kind != "author":
        # A failing item never reaches review -- it dies at the local gates -- so
        # the reviewer is left exactly as the baseline has it.
        return base
    items = []
    for entry in answered_items(request):
        identifier = str(entry["id"])
        phrase = str(entry["phrase"])
        if identifier in failing and (alias is None or request.model_alias == alias):
            phrase = f"{phrase}{OVERLAP_SUFFIX}"
        items.append({"id": identifier, "phrase": phrase})
    corrupted = replace(
        base, items=tuple(tuple(sorted(item.items())) for item in items)
    )
    corrupted.validate()
    return corrupted


class Published:
    """One published corpus and every artifact that describes it."""

    def __init__(self, root: Path, stdout: str) -> None:
        self.root = root
        self.stdout = stdout
        self.rows = load_corpus(root / "probe.v1.jsonl")
        self.ledger = load_drop_log(root / "drops.jsonl")
        self.entry = next(
            entry
            for entry in load_registry(root / "datasets.json")
            if entry.name == "probe.v1"
        )
        self.snapshot = dict(load_target_snapshot(root / "targets.json")[2])

    def cards(self, pair_id: str) -> dict[str, dict[str, list[str]]]:
        return {
            str(row["arm"]): {
                "hard_constraints": list(row["intent_card"]["hard_constraints"]),
                "soft_preferences": list(row["intent_card"]["soft_preferences"]),
            }
            for row in self.rows
            if str(row["pair_id"]) == pair_id
        }

    def pair_ids(self) -> set[str]:
        return {str(row["pair_id"]) for row in self.rows}

    def constraint_rows(self) -> tuple[dict[str, object], ...]:
        return tuple(
            row for row in self.ledger if row.get("kind") == CONSTRAINT_KIND
        )

    def pair_rows(self) -> tuple[dict[str, object], ...]:
        return tuple(row for row in self.ledger if row.get("kind") == PAIR_KIND)


class PartialCorpusTest(unittest.TestCase):
    def overrides(self, root: Path) -> tuple[str, ...]:
        """Size this module's corpus, and write the catalog it needs first.

        `generate` writes its own 24-product catalog only if none is present, and
        argparse takes the last `--pairs` it sees, so both overrides land without
        the sibling module having to know about them.
        """
        (root / "catalog.jsonl").write_text(
            catalog_lines(PRODUCTS), encoding="utf-8"
        )
        return (
            "--pairs", str(PAIRS),
            "--cross-check-pairs", str(CROSS_CHECK),
            "--replay", str(root / "unused-log.jsonl"),
        )

    def publish(
        self,
        *,
        failing: frozenset[str] = frozenset(),
        alias: str | None = None,
        expect: int = 0,
    ) -> tuple[Published | None, str, str]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)

        def runner(request):
            return response_for(request, failing=failing, alias=alias)

        code, out, err, spawned = generate(
            root, self.overrides(root), runner=runner
        )
        self.assertEqual(code, expect, err)
        forbidden = [argv for argv in spawned if not spawn_is_allowed(argv)]
        self.assertEqual(forbidden, [], "the run spawned an authoring subprocess")
        if code != 0:
            return None, out, err
        return Published(root, out), out, err

    # ----------------------------------------------------------------- baseline

    def test_a_clean_run_drops_nothing_and_still_writes_the_ledger(self) -> None:
        # The control on every test below. If the fixture dropped constraints on
        # its own, every "the drop was recorded" assertion would pass without the
        # failing phrase doing any work.
        published, out, _ = self.publish()
        assert published is not None
        self.assertEqual(published.constraint_rows(), ())
        self.assertEqual(published.pair_rows(), ())
        self.assertEqual(published.entry.dropped_constraint_count, 0)
        self.assertEqual(published.entry.refused_pair_count, 0)
        self.assertEqual(len(published.pair_ids()), PAIRS)
        # The ledger exists even so: "this corpus lost nothing" is a claim the
        # artifact makes, not an absence a reader has to interpret.
        self.assertTrue((published.root / "drops.jsonl").is_file())
        self.assertTrue(published.entry.drop_log_path)
        self.assertTrue(published.entry.drop_log_sha256)
        self.assertIn("dropped_constraints=0", out)

    # -------------------------------------------------------------- the cap

    def test_the_cap_is_genuinely_exhausted_before_a_constraint_is_dropped(
        self,
    ) -> None:
        published, _, _ = self.publish(failing=frozenset({DROPPED_ITEM}))
        assert published is not None
        rows = [
            row
            for row in published.constraint_rows()
            if row["item_id"] == DROPPED_ITEM
        ]
        # This pair carries the cross-check arm, so BOTH authored arms exhausted
        # the same slot and each recorded its own attempt. One row per arm, one
        # dropped constraint: the ledger keeps both verbatim reasons while the
        # registry counts the slot once, because the corpus lost it once.
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sorted(str(row["arm"]) for row in rows),
            ["probe_haiku", "probe_sonnet"],
        )
        self.assertEqual(published.entry.dropped_constraint_count, 1)
        for row in rows:
            with self.subTest(arm=row["arm"]):
                # The assertion that stops this fixture from being generous: the
                # item was re-authored the full cap and rejected every time. A
                # test whose fixture never actually exhausted the cap would prove
                # nothing about the drop.
                self.assertEqual(row["attempts"], AUTHORING_ATTEMPT_CAP)
                self.assertIn("lexical overlap", str(row["reason"]))
                self.assertIn("flexible sole", str(row["reason"]))

    def test_the_ledger_carries_the_provenance_a_reader_would_need(self) -> None:
        published, _, _ = self.publish(failing=frozenset({DROPPED_ITEM}))
        assert published is not None
        row = published.constraint_rows()[0]
        self.assertEqual(row["kind"], CONSTRAINT_KIND)
        self.assertEqual(row["schema_version"], DROP_LOG_SCHEMA_VERSION)
        self.assertEqual(row["pair_id"], "probe_v1_0000")
        self.assertEqual(row["slot"], "hard_constraints")
        self.assertEqual(row["position"], 0)
        self.assertIn(row["arm"], ("probe_sonnet", "probe_haiku"))
        for field in ("target", "bucket", "gist_attribute", "gist_value", "reason"):
            with self.subTest(field=field):
                self.assertTrue(str(row[field]), f"{field} is empty in the ledger")

    # ------------------------------------------------------------- symmetry

    def test_a_dropped_constraint_leaves_every_arm_of_its_pair(self) -> None:
        baseline, _, _ = self.publish()
        published, _, _ = self.publish(failing=frozenset({DROPPED_ITEM}))
        assert baseline is not None and published is not None
        before = baseline.cards("probe_v1_0000")
        after = published.cards("probe_v1_0000")
        self.assertEqual(sorted(before), sorted(after), "an arm disappeared")
        for arm in sorted(after):
            with self.subTest(arm=arm):
                # Every arm lost exactly one hard constraint, and the soft list is
                # untouched. An asymmetric drop would show as one arm keeping two.
                self.assertEqual(len(before[arm]["hard_constraints"]), 2)
                self.assertEqual(len(after[arm]["hard_constraints"]), 1)
                self.assertEqual(
                    after[arm]["soft_preferences"], before[arm]["soft_preferences"]
                )
        # And the corpus-level pairing invariant still holds over the whole file.
        check_pairing(published.rows)

    def test_a_constraint_only_the_cross_check_arm_failed_leaves_all_three_arms(
        self,
    ) -> None:
        # The strongest form of the symmetry claim. Sonnet authored this
        # constraint successfully; only Haiku exhausted the cap on it. It must
        # still vanish from the control and the Sonnet arm, because the arms are
        # matched on constraint ids and a constraint present in two arms of three
        # is not a matched pair.
        baseline, _, _ = self.publish()
        assert baseline is not None
        cross_check = sorted(
            {
                str(row["pair_id"])
                for row in baseline.rows
                if str(row["arm"]) == "probe_haiku"
            }
        )
        self.assertEqual(len(cross_check), CROSS_CHECK)
        item = f"{cross_check[0]}:h1"
        published, _, _ = self.publish(
            failing=frozenset({item}), alias="haiku"
        )
        assert published is not None
        cards = published.cards(cross_check[0])
        self.assertEqual(sorted(cards), ["control", "probe_haiku", "probe_sonnet"])
        for arm in sorted(cards):
            with self.subTest(arm=arm):
                self.assertEqual(len(cards[arm]["hard_constraints"]), 1)
        rows = published.constraint_rows()
        self.assertEqual([row["arm"] for row in rows], ["probe_haiku"])
        self.assertEqual(published.entry.dropped_constraint_count, 1)

    def test_arm_matching_is_checked_rather_than_assumed(self) -> None:
        # The guard's own failing direction, on a hand-built mismatch: without one
        # of these, `assert_arms_match_on_constraint_ids` is a function nobody has
        # seen refuse anything.
        def constraint(arm: str, position: int) -> AuthoredConstraint:
            return AuthoredConstraint(
                slot=ConstraintSlot(
                    pair_id="probe_v1_0000",
                    target="T000000000",
                    slot="hard_constraints",
                    position=position,
                    control_phrase="leather",
                    bucket="material",
                    gist_attribute="material",
                    gist_value="leather",
                    gist_payload="material=leather",
                ),
                arm=arm,
                phrase="leathery",
                report=DivergenceReport(
                    bucket="material",
                    content_token_count=1,
                    overlap_ratio=0.0,
                    overlapping_tokens=(),
                    shared_bigrams=(),
                    passes=True,
                ),
            )

        matched = (constraint("control", 0), constraint("probe_sonnet", 0))
        assert_arms_match_on_constraint_ids(matched)
        with self.assertRaises(GenerateError) as raised:
            assert_arms_match_on_constraint_ids(
                matched + (constraint("probe_sonnet", 1),)
            )
        self.assertIn("not matched on constraint ids", str(raised.exception))

    # ------------------------------------------------------- pair viability

    def test_a_pair_that_loses_a_whole_list_is_refused_rather_than_emitted(
        self,
    ) -> None:
        published, out, _ = self.publish(failing=REFUSED_ITEMS)
        assert published is not None
        # Refused means absent from EVERY arm. A pair emitted with an empty soft
        # list is not a smaller pair; `IntentCard.validate()` refuses it outright,
        # so the only alternatives were refusing the pair or failing the corpus.
        self.assertNotIn(REFUSED_PAIR_ID, published.pair_ids())
        self.assertEqual(published.cards(REFUSED_PAIR_ID), {})
        self.assertEqual(len(published.pair_ids()), PAIRS - 1)
        row = published.pair_rows()[0]
        self.assertEqual(row["pair_id"], REFUSED_PAIR_ID)
        self.assertEqual(row["missing_slots"], ["soft_preferences"])
        self.assertEqual(sorted(row["dropped_item_ids"]), sorted(REFUSED_ITEMS))
        self.assertTrue(row["arms"])
        self.assertEqual(published.entry.refused_pair_count, 1)
        self.assertIn("refused_pairs=1", out)
        # The pair took its target with it, so the committed snapshot cannot name
        # a target the corpus no longer holds.
        self.assertEqual(
            set(published.snapshot),
            {str(row["ground_truth"]["parent_asin"]) for row in published.rows},
        )
        check_pairing(published.rows)

    # -------------------------------------------------------- the arithmetic

    def test_the_registry_states_the_shortfall_and_it_equals_the_ledger(
        self,
    ) -> None:
        published, _, _ = self.publish(
            failing=REFUSED_ITEMS | {DROPPED_ITEM}
        )
        assert published is not None
        entry = published.entry
        self.assertEqual(entry.session_count, len(published.rows))
        self.assertEqual(
            entry.distinct_target_count,
            len({str(row["ground_truth"]["parent_asin"]) for row in published.rows}),
        )
        self.assertEqual(
            entry.dropped_constraint_count,
            len({str(row["item_id"]) for row in published.constraint_rows()}),
        )
        self.assertEqual(entry.refused_pair_count, len(published.pair_rows()))
        self.assertEqual(entry.refused_pair_count, 1)
        # Three constraint slots were dropped: the refused pair's two, plus the
        # one that only shortened its card.
        self.assertEqual(entry.dropped_constraint_count, 3)
        self.assertEqual(len(published.pair_ids()), PAIRS - 1)
        check_recorded_counts(
            entry,
            published.rows,
            published.ledger,
            sampled_pair_count=PAIRS,
        )

    def test_recorded_counts_that_disagree_with_the_rows_are_refused(self) -> None:
        published, _, _ = self.publish(failing=REFUSED_ITEMS | {DROPPED_ITEM})
        assert published is not None
        entry, rows, ledger = published.entry, published.rows, published.ledger
        for field, value, needle in (
            ("session_count", entry.session_count + 1, "rows were written"),
            (
                "distinct_target_count",
                entry.distinct_target_count + 1,
                "distinct targets were written",
            ),
            ("dropped_constraint_count", 0, "its ledger accounts for"),
            ("refused_pair_count", 0, "refused pair(s)"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(RegistryError) as raised:
                    check_recorded_counts(
                        replace(entry, **{field: value}),
                        rows,
                        ledger,
                        sampled_pair_count=PAIRS,
                    )
                # The needle matters: four of these raise the same exception TYPE
                # from four different branches, and asserting only the type would
                # let one branch cover for another.
                self.assertIn(needle, str(raised.exception))
        with self.assertRaises(RegistryError) as stale:
            check_recorded_counts(
                entry, rows, ledger, sampled_pair_count=PAIRS + 1
            )
        self.assertIn("does not account for", str(stale.exception))

    def test_a_refused_pair_that_is_also_published_is_refused_by_the_check(
        self,
    ) -> None:
        published, _, _ = self.publish(failing=REFUSED_ITEMS)
        assert published is not None
        # Re-file the refusal against a pair the corpus DOES hold. Nothing else
        # changes, so the only thing that can catch it is the disjointness check.
        survivor = sorted(published.pair_ids())[0]
        tampered = tuple(
            {**row, "pair_id": survivor} if row.get("kind") == PAIR_KIND else row
            for row in published.ledger
        )
        with self.assertRaises(RegistryError) as raised:
            check_recorded_counts(
                published.entry,
                published.rows,
                tampered,
                sampled_pair_count=PAIRS,
            )
        self.assertIn("its drop ledger refuses", str(raised.exception))

    def test_a_recorded_shortfall_with_no_ledger_is_refused(self) -> None:
        published, _, _ = self.publish(failing=frozenset({DROPPED_ITEM}))
        assert published is not None
        with self.assertRaises(ValueError) as raised:
            replace(
                published.entry, drop_log_path="", drop_log_sha256=""
            ).validate()
        self.assertIn("names no drop ledger", str(raised.exception))

    # ---------------------------------------------------------- the reporting

    def test_the_run_prints_the_shortfall_to_stdout(self) -> None:
        published, out, _ = self.publish(failing=REFUSED_ITEMS | {DROPPED_ITEM})
        assert published is not None
        printed = dict(
            line.split("=", 1) for line in out.splitlines() if "=" in line
        )
        # Checked against the corpus rather than against literals copied out of an
        # earlier run: the claim is that the summary describes what was written,
        # and a hardcoded expectation would agree with a stale summary just as
        # happily.
        sizes = [
            len(row["intent_card"]["hard_constraints"])
            + len(row["intent_card"]["soft_preferences"])
            for row in published.rows
            if str(row["arm"]) == "control"
        ]
        self.assertEqual(
            printed["dropped_constraints"],
            str(len({str(row["item_id"]) for row in published.constraint_rows()})),
        )
        self.assertEqual(printed["refused_pairs"], str(len(published.pair_rows())))
        self.assertEqual(printed["sampled_pairs"], str(PAIRS))
        self.assertEqual(printed["surviving_pairs"], str(len(published.pair_ids())))
        self.assertEqual(printed["surviving_constraints"], str(sum(sizes)))
        self.assertEqual(
            printed["constraints_per_pair"], f"{sum(sizes) / len(sizes):.4f}"
        )
        self.assertTrue(printed["drop_log"].endswith("drops.jsonl"))
        # And the summary is not vacuous: this run really did lose something.
        self.assertEqual(printed["dropped_constraints"], "3")
        self.assertEqual(printed["refused_pairs"], "1")

    # ------------------------------------------------------------ discipline

    def test_the_same_failures_produce_the_same_corpus_and_the_same_ledger(
        self,
    ) -> None:
        first, _, _ = self.publish(failing=REFUSED_ITEMS | {DROPPED_ITEM})
        second, _, _ = self.publish(failing=REFUSED_ITEMS | {DROPPED_ITEM})
        assert first is not None and second is not None
        self.assertEqual(
            (first.root / "probe.v1.jsonl").read_bytes(),
            (second.root / "probe.v1.jsonl").read_bytes(),
        )
        self.assertEqual(
            (first.root / "drops.jsonl").read_bytes(),
            (second.root / "drops.jsonl").read_bytes(),
        )

    def test_the_surviving_constraints_still_clear_the_gates(self) -> None:
        # The drop must not become a way past a gate. Every constraint that
        # survived is swept again, from the committed snapshot, exactly as plan
        # 02-11 sweeps the real corpus.
        published, _, _ = self.publish(failing=REFUSED_ITEMS | {DROPPED_ITEM})
        assert published is not None
        control = {
            str(row["pair_id"]): row["intent_card"]
            for row in published.rows
            if str(row["arm"]) == "control"
        }
        swept = 0
        for row in published.rows:
            if str(row["arm"]) == "control":
                continue
            target = published.snapshot[str(row["ground_truth"]["parent_asin"])]
            for name in ("hard_constraints", "soft_preferences"):
                probe = list(row["intent_card"][name])
                reference = list(control[str(row["pair_id"])][name])
                self.assertEqual(len(probe), len(reference))
                for phrase, control_phrase in zip(probe, reference):
                    with self.subTest(phrase=phrase):
                        self.assertTrue(preserves_bucket(control_phrase, phrase))
                        self.assertTrue(measure_text(phrase, target).passes)
                        swept += 1
        self.assertGreater(swept, 0, "the sweep found nothing to check")

    def test_an_item_nobody_authored_is_not_droppable(self) -> None:
        # The detached path's protection. An unanswered request makes its items
        # look exhausted, and dropping them would publish a corpus short by
        # whatever the queue still held -- with a ledger blaming the gates for it.
        def silent(request):
            base = inline_response(request)
            if request.kind != "author":
                return base
            kept = tuple(
                tuple(sorted(item.items()))
                for item in answered_items(request)
                if str(item["id"]) != DROPPED_ITEM
            )
            response = replace(base, items=kept)
            response.validate()
            return response

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        code, _, err, _ = generate(
            root, ("--replay", str(root / "unused-log.jsonl")), runner=silent
        )
        self.assertEqual(code, 1)
        self.assertIn("were never authored", err)
        self.assertIn(DROPPED_ITEM, err)
        self.assertFalse((root / "probe.v1.jsonl").is_file())


class DropLedgerRecordTest(unittest.TestCase):
    """The record types' own refusals, at the boundary rather than through a run."""

    def constraint(self, **overrides: object) -> DroppedConstraint:
        fields: dict[str, object] = {
            "schema_version": DROP_LOG_SCHEMA_VERSION,
            "item_id": "probe_v1_0000:h0",
            "pair_id": "probe_v1_0000",
            "arm": "probe_sonnet",
            "target": "T000000000",
            "slot": "hard_constraints",
            "position": 0,
            "bucket": "material",
            "gist_attribute": "material",
            "gist_value": "leather",
            "attempts": AUTHORING_ATTEMPT_CAP,
            "reason": "lexical overlap 0.5000 on ['sole'] and shared 2-grams []",
        }
        fields.update(overrides)
        return DroppedConstraint(**fields)  # type: ignore[arg-type]

    def test_the_baseline_record_validates(self) -> None:
        self.constraint().validate()

    def test_a_drop_with_no_reason_is_refused(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self.constraint(reason="").validate()
        self.assertIn("no rejection reason", str(raised.exception))

    def test_a_drop_that_was_never_attempted_is_refused(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self.constraint(attempts=0).validate()
        self.assertIn("attempted at least once", str(raised.exception))

    def test_an_unknown_arm_is_refused(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self.constraint(arm="probe_opus").validate()
        self.assertIn("arm must be one of", str(raised.exception))

    def test_a_refused_pair_must_name_the_list_it_lost(self) -> None:
        with self.assertRaises(ValueError) as raised:
            RefusedPair(
                schema_version=DROP_LOG_SCHEMA_VERSION,
                pair_id="probe_v1_0011",
                target="T000000011",
                arms=("control", "probe_sonnet"),
                missing_slots=(),
                dropped_item_ids=("probe_v1_0011:s0",),
            ).validate()
        self.assertIn("must name the list it lost", str(raised.exception))

    def test_a_refused_pair_must_name_the_constraints_that_emptied_it(self) -> None:
        with self.assertRaises(ValueError) as raised:
            RefusedPair(
                schema_version=DROP_LOG_SCHEMA_VERSION,
                pair_id="probe_v1_0011",
                target="T000000011",
                arms=("control", "probe_sonnet"),
                missing_slots=("soft_preferences",),
                dropped_item_ids=(),
            ).validate()
        self.assertIn("must name the dropped constraints", str(raised.exception))

    def test_the_log_path_is_versioned_with_its_corpus(self) -> None:
        self.assertEqual(
            drop_log_path("probe.v1"), Path("data") / "drops.probe.v1.jsonl"
        )
        self.assertNotEqual(drop_log_path("probe.v1"), drop_log_path("probe.v2"))

    def test_a_malformed_ledger_line_names_the_path_and_the_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "drops.jsonl"
            path.write_text(
                json.dumps(self.constraint().as_record()) + "\n{not json\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as raised:
                load_drop_log(path)
            self.assertIn("at line 2", str(raised.exception))

    def test_a_row_with_an_unknown_kind_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "drops.jsonl"
            record = dict(self.constraint().as_record())
            record["kind"] = "note"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                load_drop_log(path)
            self.assertIn("unknown kind", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
