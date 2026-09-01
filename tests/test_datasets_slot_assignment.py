"""Prove `constraint_slots` hands every slot a gist its authored phrase can satisfy.

A `ConstraintSlot` is a contract between two gates that never see each other. D-33
`preserves_bucket` requires the authored phrase to classify back into the CONTROL
phrase's bucket; D-35 faithfulness requires the same phrase to mean the GIST pair,
and the committed author prompt forbids inventing an attribute the pair does not
state. When the two disagree -- a `color` slot shown `entry_method=toothed_fastener`
-- no phrase satisfies both. Naming a colour fails faithfulness, omitting one fails
the bucket gate, and the item burns every one of `AUTHORING_ATTEMPT_CAP` attempts
before the whole run fails. The defect is invisible at every other layer: the slot
validates, the prompt renders, the call succeeds, and only the accumulated rejection
count says anything is wrong.

So the property asserted here is bucket AGREEMENT at assignment time, measured
against what the target's gist can actually supply. `SlotExhaustionTest` is the half
that matters: agreement is free while unspent same-bucket pairs remain, and the
ordering only becomes observable once that pool is empty. Its fixture is sized so
exhaustion is unavoidable -- four constraints against three gist pairs -- and
`test_the_fixture_really_exhausts_the_pool` fails if a future edit makes the gist
generous enough for the fallback never to run, because a fixture that cannot reach
the branch under test would assert the property vacuously.

`DefectiveOrderingTest` is the negative half. It reproduces the shipped-and-wrong
preference order locally and asserts `bucket_violations` reports it. Without that,
a helper that returned `()` unconditionally would make every test above pass.

Every product here is a hand-written dict and every vocabulary is built inline.
Nothing in this module opens the built SQLite database or reads the 61 MB catalog.
"""

from __future__ import annotations

import unittest

from arena.datasets.generate import (
    ConstraintSlot,
    PairTarget,
    _gist_bucket,
    constraint_slots,
)
from arena.datasets.gist import (
    GIST_SCHEMA_VERSION,
    GistVocabulary,
    gist_for_target,
)
from arena.datasets.schema import IntentCard
from arena.evaluator_bridge import classify_constraint
from tests.dataset_fixtures import pair_id, product


# One phrase per bucket this module needs, each verified by `classify_constraint`
# in `BucketFixtureTest` rather than assumed. Two land in `material`, which is the
# whole point: a card carrying the same bucket twice is what forces the assignment
# past its first choice and into the fallback the defect lived in.
_MATERIAL_COTTON = "soft cotton knit throughout"
_MATERIAL_WOOL = "warm wool lining inside"
_COLOR = "color: black"
_SIZE = "runs true to size on the shoulders"
_STYLE = "relaxed fit with a crew neck"
_FEATURE = "machine washable and quick drying"
# `use_case` is reachable from `classify_constraint` and unreachable from the gist:
# `gist.py`'s `_GIST_ATTRIBUTES` admits colour, feature, material, size and style
# and nothing else. A slot in this bucket therefore has no satisfiable pair
# anywhere in its target's catalogue, which is a supply property of the corpus and
# not something the assignment can repair. It is fixtured so the "whenever the
# vocabulary can supply one" qualifier is exercised rather than merely written.
_USE_CASE = "warm enough for winter commutes"

# The floors are inert here -- `admits` consults the hand-written `values` and
# `abstractions` directly -- so they carry the smallest values `validate` accepts
# rather than copies of the production constants they must not be read as.
_INERT_DF_FLOOR = 1


def _vocabulary(
    values: tuple[tuple[str, tuple[str, ...]], ...],
    abstractions: tuple[tuple[str, tuple[str, str]], ...] = (),
) -> GistVocabulary:
    vocabulary = GistVocabulary(
        schema_version=GIST_SCHEMA_VERSION,
        df_floor=_INERT_DF_FLOOR,
        feature_abstraction_df_floor=_INERT_DF_FLOOR,
        catalog_sha256="0" * 64,
        values=values,
        abstractions=abstractions,
    )
    vocabulary.validate()
    return vocabulary


# Five pairs, one per gist attribute, so a four-constraint card can be satisfied
# without ever reaching the fallback. This is the control against which the
# exhaustion fixture below is read.
_RICH_VOCABULARY = _vocabulary(
    values=(
        ("color", ("black",)),
        ("material", ("leather",)),
        ("size", ("medium",)),
        ("style", ("casual",)),
    ),
    # An ABSTRACT attribute name, exactly as the committed D-52 table produces:
    # the catalog string is the lookup key and is discarded, and `_gist_bucket`
    # routes the abstract attribute to the residual `feature` bucket.
    abstractions=(("moisture wicking mesh panels", ("breathability", "wicking")),),
)

# Three pairs against four slots. Deliberately holds NO feature pair and NO second
# material pair, so a card with two material constraints must reuse one.
_THIN_VOCABULARY = _vocabulary(
    values=(
        ("color", ("black",)),
        ("material", ("leather",)),
        ("size", ("medium",)),
    ),
)

# One pair against four slots: the attribute-poor target the reuse policy exists
# to keep in the pool.
_POOR_VOCABULARY = _vocabulary(values=(("material", ("leather",)),))

_RICH_TARGET = product(
    "B0SLOT0001",
    title="Leather Jacket",
    features=("Moisture wicking mesh panels",),
    details=(
        ("Color", "Black"),
        ("Material", "Leather"),
        ("Size", "Medium"),
        ("Style", "Casual"),
    ),
)

_THIN_TARGET = product(
    "B0SLOT0002",
    title="Leather Jacket",
    details=(("Color", "Black"), ("Material", "Leather"), ("Size", "Medium")),
)

_POOR_TARGET = product("B0SLOT0003", title="Leather Jacket", details=(("Material", "Leather"),))


def _slots(
    card: IntentCard,
    *,
    target: dict[str, object],
    vocabulary: GistVocabulary,
) -> tuple[ConstraintSlot, ...]:
    parent_asin = str(target["parent_asin"])
    card.validate()
    return constraint_slots(
        PairTarget(
            pair_id=pair_id(1),
            target=parent_asin,
            scenario_type="buying",
            card=card,
        ),
        vocabulary=vocabulary,
        products={parent_asin: target},
    )


def _suppliable_buckets(
    target: dict[str, object], vocabulary: GistVocabulary
) -> frozenset[str]:
    """The buckets this target's gist can actually name, read off the gist itself."""

    # Derived from `gist_for_target`, never from the slots under test: a set built
    # from the assignment's own output would agree with the assignment by
    # construction and the comparison would prove nothing.
    return frozenset(
        _gist_bucket(pair.attribute)
        for pair in gist_for_target(target, vocabulary)
    )


def bucket_violations(
    slots: tuple[ConstraintSlot, ...], suppliable: frozenset[str]
) -> tuple[str, ...]:
    """Every slot handed a gist from a bucket other than its own, where one existed."""

    return tuple(
        f"{slot.item_id()} bucket={slot.bucket} gist={slot.gist_attribute}"
        for slot in slots
        if slot.bucket in suppliable
        and _gist_bucket(slot.gist_attribute) != slot.bucket
    )


class BucketFixtureTest(unittest.TestCase):
    """The fixtures claim a bucket each. The harness is the authority, so ask it."""

    def test_every_fixture_phrase_classifies_where_this_module_says(self) -> None:
        expected = (
            (_MATERIAL_COTTON, "material"),
            (_MATERIAL_WOOL, "material"),
            (_COLOR, "color"),
            (_SIZE, "size"),
            (_STYLE, "style"),
            (_FEATURE, "feature"),
            (_USE_CASE, "use_case"),
        )
        for phrase, bucket in expected:
            with self.subTest(phrase=phrase):
                # A drifted classifier would otherwise silently re-point a fixture
                # at another bucket and leave every assertion below passing over a
                # card that no longer exercises what its name says it does.
                self.assertEqual(classify_constraint(phrase), bucket)

    def test_the_gist_fixtures_hold_the_pairs_this_module_relies_on(self) -> None:
        rich = _suppliable_buckets(_RICH_TARGET, _RICH_VOCABULARY)
        self.assertEqual(rich, frozenset({"color", "feature", "material", "size", "style"}))
        thin = _suppliable_buckets(_THIN_TARGET, _THIN_VOCABULARY)
        self.assertEqual(thin, frozenset({"color", "material", "size"}))
        self.assertEqual(
            _suppliable_buckets(_POOR_TARGET, _POOR_VOCABULARY), frozenset({"material"})
        )


class SlotBucketAgreementTest(unittest.TestCase):
    """The property: a slot gets its own bucket whenever the gist holds one."""

    def test_a_rich_gist_matches_every_slot(self) -> None:
        slots = _slots(
            IntentCard(
                target_category="jacket",
                hard_constraints=(_MATERIAL_COTTON, _FEATURE),
                soft_preferences=(_COLOR, _STYLE),
            ),
            target=_RICH_TARGET,
            vocabulary=_RICH_VOCABULARY,
        )
        self.assertEqual(
            bucket_violations(
                slots, _suppliable_buckets(_RICH_TARGET, _RICH_VOCABULARY)
            ),
            (),
        )

    def test_a_thin_gist_still_matches_every_slot_it_can_supply(self) -> None:
        # Four slots, three pairs, and two slots competing for the single material
        # pair. This is the exact shape the shipped ordering got wrong.
        slots = _slots(
            IntentCard(
                target_category="jacket",
                hard_constraints=(_MATERIAL_COTTON, _MATERIAL_WOOL),
                soft_preferences=(_COLOR, _SIZE),
            ),
            target=_THIN_TARGET,
            vocabulary=_THIN_VOCABULARY,
        )
        self.assertEqual(
            bucket_violations(
                slots, _suppliable_buckets(_THIN_TARGET, _THIN_VOCABULARY)
            ),
            (),
        )

    def test_a_bucket_the_gist_cannot_supply_still_yields_a_slot(self) -> None:
        # `use_case` has no gist attribute at all, so the slot is unsatisfiable by
        # supply rather than by ordering. It must still be EMITTED: dropping it
        # would leave the authored card short a constraint that the control card
        # carries, and the two arms would then no longer be the same card reworded.
        slots = _slots(
            IntentCard(
                target_category="jacket",
                hard_constraints=(_MATERIAL_COTTON, _USE_CASE),
                soft_preferences=(_COLOR, _SIZE),
            ),
            target=_THIN_TARGET,
            vocabulary=_THIN_VOCABULARY,
        )
        self.assertEqual(len(slots), 4)
        use_case = next(slot for slot in slots if slot.bucket == "use_case")
        self.assertTrue(use_case.gist_attribute)
        self.assertNotIn(
            "use_case", _suppliable_buckets(_THIN_TARGET, _THIN_VOCABULARY)
        )
        # Every OTHER slot is suppliable and must still agree, so an unsatisfiable
        # slot does not get to drag its neighbours off their buckets.
        self.assertEqual(
            bucket_violations(
                slots, _suppliable_buckets(_THIN_TARGET, _THIN_VOCABULARY)
            ),
            (),
        )


class SlotExhaustionTest(unittest.TestCase):
    """Under exhaustion the fallback must reuse a bucket, not spend a fresh one."""

    def setUp(self) -> None:
        self.card = IntentCard(
            target_category="jacket",
            hard_constraints=(_MATERIAL_COTTON, _MATERIAL_WOOL),
            soft_preferences=(_COLOR, _SIZE),
        )
        self.slots = _slots(
            self.card, target=_THIN_TARGET, vocabulary=_THIN_VOCABULARY
        )
        self.pairs = gist_for_target(_THIN_TARGET, _THIN_VOCABULARY)

    def test_the_fixture_really_exhausts_the_pool(self) -> None:
        # The non-vacuity guard. A fixture whose gist is large enough to cover
        # every slot never reaches the fallback, and every other assertion in this
        # class would then pass without exercising the branch it names. If a future
        # edit widens `_THIN_VOCABULARY` or shortens the card, this fails first and
        # says why.
        self.assertGreater(len(self.slots), len(self.pairs))
        used = [(slot.gist_attribute, slot.gist_value) for slot in self.slots]
        self.assertGreater(
            len(used), len(set(used)), "no pair was reused, so no fallback ran"
        )

    def test_the_second_same_bucket_slot_reuses_rather_than_crossing_buckets(self) -> None:
        first, second = self.slots[0], self.slots[1]
        self.assertEqual(first.bucket, "material")
        self.assertEqual(second.bucket, "material")
        # The load-bearing assertion. Under the shipped ordering `second` took the
        # first UNSPENT pair -- `color=black` -- because unspent outranked
        # same-bucket. That item cannot be authored at all, and it also stole the
        # pair the colour slot needed, so one defect produced two broken items.
        self.assertEqual(
            (second.gist_attribute, second.gist_value),
            (first.gist_attribute, first.gist_value),
        )
        self.assertEqual(second.gist_attribute, "material")

    def test_reuse_does_not_steal_the_pair_a_later_slot_needs(self) -> None:
        by_bucket = {slot.bucket: slot.gist_attribute for slot in self.slots}
        self.assertEqual(by_bucket["color"], "color")
        self.assertEqual(by_bucket["size"], "size")

    def test_an_attribute_poor_target_keeps_every_constraint(self) -> None:
        # The anti-skew property the reuse policy exists for, asserted rather than
        # left to the comment: a one-pair gist against a four-constraint card must
        # still emit four slots. Refusing reuse would drop this target from the
        # pool, and attribute-poor products are not randomly distributed, so the
        # corpus would skew toward richly described listings -- the silent skew
        # D-30's stratification exists to prevent.
        slots = _slots(
            self.card, target=_POOR_TARGET, vocabulary=_POOR_VOCABULARY
        )
        self.assertEqual(len(slots), 4)
        self.assertEqual(
            tuple(slot.control_phrase for slot in slots),
            (_MATERIAL_COTTON, _MATERIAL_WOOL, _COLOR, _SIZE),
        )
        # Both material slots are suppliable and both must agree; the colour and
        # size slots are not suppliable here and are exempt by the same rule the
        # `use_case` case documents.
        self.assertEqual(
            bucket_violations(
                slots, _suppliable_buckets(_POOR_TARGET, _POOR_VOCABULARY)
            ),
            (),
        )

    def test_assignment_is_deterministic(self) -> None:
        repeated = _slots(
            self.card, target=_THIN_TARGET, vocabulary=_THIN_VOCABULARY
        )
        self.assertEqual(self.slots, repeated)


class DefectiveOrderingTest(unittest.TestCase):
    """The negative half: show `bucket_violations` reports the ordering it must."""

    def test_preferring_unspent_over_same_bucket_is_reported(self) -> None:
        suppliable = _suppliable_buckets(_THIN_TARGET, _THIN_VOCABULARY)
        violations = bucket_violations(
            _defectively_assigned_slots(), suppliable
        )
        # Two items, not one: the wrongly-assigned material slot AND the colour
        # slot whose pair it consumed. That second-order damage is why the shipped
        # ordering mismatched 393 of 1,197 probe constraints rather than a handful.
        self.assertEqual(len(violations), 2)
        self.assertTrue(
            any("bucket=material gist=color" in item for item in violations),
            violations,
        )
        self.assertTrue(
            any("bucket=color gist=size" in item for item in violations),
            violations,
        )


def _defectively_assigned_slots() -> tuple[ConstraintSlot, ...]:
    """The shipped-and-wrong preference order, reproduced to be refused.

    A local copy of a KNOWN-BAD algorithm, not a second implementation of the live
    one: its only job is to give `bucket_violations` something it must report, so a
    helper that returned `()` unconditionally cannot pass the class above. Steps 2
    and 3 are swapped relative to `constraint_slots`, which is the entire defect.
    """

    pairs = gist_for_target(_THIN_TARGET, _THIN_VOCABULARY)
    available = list(pairs)
    slots: list[ConstraintSlot] = []
    phrases = (_MATERIAL_COTTON, _MATERIAL_WOOL, _COLOR, _SIZE)
    for position, phrase in enumerate(phrases):
        bucket = classify_constraint(phrase)
        chosen = next(
            (pair for pair in available if _gist_bucket(pair.attribute) == bucket),
            None,
        )
        if chosen is None and available:
            chosen = available[0]
        if chosen is None:
            chosen = next(
                (pair for pair in pairs if _gist_bucket(pair.attribute) == bucket),
                pairs[0],
            )
        if chosen in available:
            available.remove(chosen)
        slots.append(
            ConstraintSlot(
                pair_id=pair_id(1),
                target=str(_THIN_TARGET["parent_asin"]),
                slot="hard_constraints",
                position=position,
                control_phrase=phrase,
                bucket=bucket,
                gist_attribute=chosen.attribute,
                gist_value=chosen.value,
                gist_payload=f"{chosen.attribute}={chosen.value}",
            )
        )
    return tuple(slots)


if __name__ == "__main__":
    unittest.main()
