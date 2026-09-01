"""Prove `constraint_slots` only ever emits a slot its target's gist can satisfy.

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

Two properties are asserted, and they are not the same property:

* **Assignment.** While the gist holds a pair in the constraint's bucket, the slot
  gets one -- spending a fresh pair where it can and reusing a spent one where it
  cannot. `SlotExhaustionTest` is the half that matters, because agreement is free
  until the same-bucket pool empties.
* **Supply.** When the gist holds NO pair in that bucket, no slot is emitted at
  all, and `authorable_pair` then removes the constraint from every arm of the
  pair at once. `SupplyOmissionTest` and `AuthorablePairTest` own this half.

Every fixture here is sized so the branch it names is unavoidable, and each class
carries the guard that fails if a future edit makes it vacuous:
`test_the_fixture_really_exhausts_the_pool` for the assignment half and
`test_the_fixture_really_omits_something` for the supply half. A fixture whose gist
serves every bucket can never reach either branch, and every assertion in this
module would then pass over a card that exercises nothing.

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
    GenerateError,
    PairTarget,
    _gist_bucket,
    authorable_pair,
    constraint_slots,
    control_constraints,
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
# past its first choice and into the reuse branch the 02-09a defect lived in.
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
# not something the assignment can repair -- so it is the cheapest constraint to
# fixture the omission with, and it is unsuppliable for EVERY target rather than
# only for the thin ones.
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
# without ever reaching the reuse branch OR the omission. This is the control
# against which the two thinner fixtures below are read.
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

# Three pairs against four slots. Deliberately holds NO feature pair, NO style
# pair and NO second material pair, so a card with two material constraints must
# reuse one and a card naming style or feature must lose it.
_THIN_VOCABULARY = _vocabulary(
    values=(
        ("color", ("black",)),
        ("material", ("leather",)),
        ("size", ("medium",)),
    ),
)

# One pair against four slots: the attribute-poor target the reuse policy exists
# to keep in the pool, and the one that shows where reuse stops being enough.
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

# Carries no admitted attribute at all, so `gist_for_target` returns nothing. Its
# only job is to keep the empty-gist refusal distinguishable from the new one.
_GISTLESS_TARGET = product("B0SLOT0004", title="Plain Jacket")


def _pair(
    card: IntentCard, *, target: dict[str, object]
) -> PairTarget:
    card.validate()
    return PairTarget(
        pair_id=pair_id(1),
        target=str(target["parent_asin"]),
        scenario_type="buying",
        card=card,
    )


def _slots(
    card: IntentCard,
    *,
    target: dict[str, object],
    vocabulary: GistVocabulary,
) -> tuple[ConstraintSlot, ...]:
    parent_asin = str(target["parent_asin"])
    return constraint_slots(
        _pair(card, target=target),
        vocabulary=vocabulary,
        products={parent_asin: target},
    )


def _reduced(
    card: IntentCard,
    *,
    target: dict[str, object],
    vocabulary: GistVocabulary,
) -> PairTarget:
    parent_asin = str(target["parent_asin"])
    return authorable_pair(
        _pair(card, target=target),
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


def bucket_violations(slots: tuple[ConstraintSlot, ...]) -> tuple[str, ...]:
    """Every slot handed a gist from a bucket other than its own. No exemptions.

    Unconditional since 02-09b. Before the supply omission this checker had to
    exempt slots whose bucket the gist could not supply, because such a slot was
    emitted anyway and necessarily carried a foreign gist. Now it is not emitted
    at all, so the exemption would be dead code that reads as protection -- and a
    checker with a clause that can never fire is exactly how the next defect of
    this class would ship unseen.
    """

    return tuple(
        f"{slot.item_id()} bucket={slot.bucket} gist={slot.gist_attribute}"
        for slot in slots
        if _gist_bucket(slot.gist_attribute) != slot.bucket
    )


def unsuppliable_slots(
    slots: tuple[ConstraintSlot, ...], suppliable: frozenset[str]
) -> tuple[str, ...]:
    """Every emitted slot asking for a bucket the target's gist cannot serve."""

    return tuple(
        f"{slot.item_id()} bucket={slot.bucket}"
        for slot in slots
        if slot.bucket not in suppliable
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
        self.assertEqual(
            _suppliable_buckets(_GISTLESS_TARGET, _POOR_VOCABULARY), frozenset()
        )


class SlotBucketAgreementTest(unittest.TestCase):
    """The property: every emitted slot gets a gist from its own bucket."""

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
        self.assertEqual(len(slots), 4)
        self.assertEqual(bucket_violations(slots), ())

    def test_a_thin_gist_still_matches_every_slot_it_can_supply(self) -> None:
        # Four slots, three pairs, and two slots competing for the single material
        # pair. This is the exact shape the 02-09a ordering defect got wrong.
        slots = _slots(
            IntentCard(
                target_category="jacket",
                hard_constraints=(_MATERIAL_COTTON, _MATERIAL_WOOL),
                soft_preferences=(_COLOR, _SIZE),
            ),
            target=_THIN_TARGET,
            vocabulary=_THIN_VOCABULARY,
        )
        self.assertEqual(len(slots), 4)
        self.assertEqual(bucket_violations(slots), ())


class SupplyOmissionTest(unittest.TestCase):
    """The 02-09b property: an unsuppliable bucket yields no slot, on either arm."""

    def setUp(self) -> None:
        # `use_case` is unsuppliable for every target, and `style` is unsuppliable
        # for this one, so the card loses two of its four constraints while both
        # lists still keep one. That is the shape the fix has to produce: shorter,
        # not refused.
        self.card = IntentCard(
            target_category="jacket",
            hard_constraints=(_MATERIAL_COTTON, _USE_CASE),
            soft_preferences=(_COLOR, _STYLE),
        )
        self.slots = _slots(
            self.card, target=_THIN_TARGET, vocabulary=_THIN_VOCABULARY
        )
        self.suppliable = _suppliable_buckets(_THIN_TARGET, _THIN_VOCABULARY)

    def test_the_fixture_really_omits_something(self) -> None:
        # The non-vacuity guard, and the single biggest risk in this module. A
        # fixture whose gist serves every bucket emits every slot, and every
        # assertion in this class would then pass without the omission ever
        # running. If a future edit widens `_THIN_VOCABULARY` or re-points a
        # fixture phrase, this fails first and says why.
        declared = len(self.card.hard_constraints) + len(self.card.soft_preferences)
        self.assertEqual(declared, 4)
        self.assertLess(len(self.slots), declared)
        self.assertFalse(
            self.suppliable.issuperset({"style", "use_case"}),
            "the fixture gist can serve every bucket, so nothing is omitted",
        )

    def test_no_emitted_slot_carries_a_bucket_the_gist_cannot_supply(self) -> None:
        # The whole point. Before the fix the `use_case` and `style` constraints
        # were emitted anyway, each handed a gist pair from a foreign bucket, and
        # each then burned every AUTHORING_ATTEMPT_CAP attempt.
        self.assertEqual(unsuppliable_slots(self.slots, self.suppliable), ())
        self.assertEqual(len(self.slots), 2)
        self.assertEqual(
            tuple(slot.control_phrase for slot in self.slots),
            (_MATERIAL_COTTON, _COLOR),
        )

    def test_the_surviving_slots_still_get_their_own_bucket(self) -> None:
        # An omission must not drag its neighbours off their buckets: the
        # assignment property and the supply property have to hold at once.
        self.assertEqual(bucket_violations(self.slots), ())

    def test_positions_stay_contiguous_across_an_omission(self) -> None:
        # `_USE_CASE` sits at hard position 1 and `_STYLE` at soft position 1, so
        # a position copied from the control card's index would leave gaps. The
        # committed divergence log keys on (pair_id, arm, slot, position) and
        # `control_constraints` numbers the reduced card with a plain `enumerate`,
        # so a gap on one arm only would file two arms of one pair under different
        # keys.
        by_slot: dict[str, list[int]] = {}
        for slot in self.slots:
            by_slot.setdefault(slot.slot, []).append(slot.position)
        for name, positions in sorted(by_slot.items()):
            with self.subTest(slot=name):
                self.assertEqual(positions, list(range(len(positions))))

    def test_every_fixture_emits_only_suppliable_buckets(self) -> None:
        cases = (
            ("rich", _RICH_TARGET, _RICH_VOCABULARY),
            ("thin", _THIN_TARGET, _THIN_VOCABULARY),
        )
        card = IntentCard(
            target_category="jacket",
            hard_constraints=(_MATERIAL_COTTON, _USE_CASE),
            soft_preferences=(_COLOR, _FEATURE),
        )
        for name, target, vocabulary in cases:
            with self.subTest(fixture=name):
                slots = _slots(card, target=target, vocabulary=vocabulary)
                suppliable = _suppliable_buckets(target, vocabulary)
                self.assertEqual(unsuppliable_slots(slots, suppliable), ())
                self.assertEqual(bucket_violations(slots), ())

    def test_omission_is_deterministic(self) -> None:
        repeated = _slots(
            self.card, target=_THIN_TARGET, vocabulary=_THIN_VOCABULARY
        )
        self.assertEqual(self.slots, repeated)


class SlotRefusalTest(unittest.TestCase):
    """A card that would lose a whole list is refused, and refused for its reason."""

    def test_losing_every_soft_preference_refuses_the_target(self) -> None:
        # `IntentCard.validate()` requires both lists to be non-empty, so a card
        # that lost one is not a smaller card -- it is not a card. The target is
        # excluded from the candidate pool BEFORE the draw, never resampled after,
        # because `_run` filters the pool with this same call.
        card = IntentCard(
            target_category="jacket",
            hard_constraints=(_MATERIAL_COTTON, _MATERIAL_WOOL),
            soft_preferences=(_COLOR, _SIZE),
        )
        with self.assertRaises(GenerateError) as raised:
            _slots(card, target=_POOR_TARGET, vocabulary=_POOR_VOCABULARY)
        # Asserted on the MESSAGE, not only on the type. `constraint_slots` raises
        # GenerateError from three different places, and a test satisfied by the
        # type alone would pass on the empty-gist branch or the missing-target
        # branch while the branch it names never ran.
        self.assertIn("would lose every soft_preferences", str(raised.exception))

    def test_losing_every_hard_constraint_refuses_the_target(self) -> None:
        # The mirror, so the refusal is not accidentally keyed to one list.
        card = IntentCard(
            target_category="jacket",
            hard_constraints=(_COLOR, _SIZE),
            soft_preferences=(_MATERIAL_COTTON, _MATERIAL_WOOL),
        )
        with self.assertRaises(GenerateError) as raised:
            _slots(card, target=_POOR_TARGET, vocabulary=_POOR_VOCABULARY)
        self.assertIn("would lose every hard_constraints", str(raised.exception))

    def test_the_same_card_survives_when_each_list_keeps_one(self) -> None:
        # The non-vacuity guard for the two refusals above: the refusal must be a
        # property of what the gist supplies, not of this fixture being too poor
        # to build anything at all. Same target, same one-pair gist, constraints
        # rearranged so each list retains a material -- and it builds.
        slots = _slots(
            IntentCard(
                target_category="jacket",
                hard_constraints=(_MATERIAL_COTTON, _COLOR),
                soft_preferences=(_MATERIAL_WOOL, _SIZE),
            ),
            target=_POOR_TARGET,
            vocabulary=_POOR_VOCABULARY,
        )
        self.assertEqual(
            tuple(slot.control_phrase for slot in slots),
            (_MATERIAL_COTTON, _MATERIAL_WOOL),
        )
        # And the single material pair is REUSED across the two lists rather than
        # one of them going without: the anti-skew policy survives the omission.
        self.assertEqual(
            {(slot.gist_attribute, slot.gist_value) for slot in slots},
            {("material", "leather")},
        )
        self.assertEqual(bucket_violations(slots), ())

    def test_the_other_refusals_keep_their_own_reasons(self) -> None:
        # Guards the assertions above from the "same exception type, different
        # branch" trap by showing the other two branches say something else.
        card = IntentCard(
            target_category="jacket",
            hard_constraints=(_MATERIAL_COTTON,),
            soft_preferences=(_COLOR,),
        )
        with self.assertRaises(GenerateError) as empty:
            _slots(card, target=_GISTLESS_TARGET, vocabulary=_POOR_VOCABULARY)
        self.assertIn("empty attribute gist", str(empty.exception))
        with self.assertRaises(GenerateError) as absent:
            constraint_slots(
                _pair(card, target=_POOR_TARGET),
                vocabulary=_POOR_VOCABULARY,
                products={},
            )
        self.assertIn("absent from the catalog", str(absent.exception))


class AuthorablePairTest(unittest.TestCase):
    """The omission reaches BOTH arms, because it is applied to the pair."""

    def setUp(self) -> None:
        self.card = IntentCard(
            target_category="jacket",
            hard_constraints=(_MATERIAL_COTTON, _USE_CASE),
            soft_preferences=(_COLOR, _STYLE),
        )
        self.pair = _reduced(
            self.card, target=_THIN_TARGET, vocabulary=_THIN_VOCABULARY
        )

    def test_the_fixture_really_reduces_the_card(self) -> None:
        # Non-vacuity again, at the pair level: a card that came back unchanged
        # would make every assertion below true of the untouched control card.
        self.assertEqual(self.pair.card.hard_constraints, (_MATERIAL_COTTON,))
        self.assertEqual(self.pair.card.soft_preferences, (_COLOR,))
        self.assertNotEqual(self.pair.card, self.card)

    def test_the_reduced_card_keeps_the_evaluator_phrasing_verbatim(self) -> None:
        # D-31: the reduction removes constraints, it never rewords, reorders or
        # repairs one. Every surviving string is the control card's own, in the
        # control card's order.
        for name in ("hard_constraints", "soft_preferences"):
            with self.subTest(slot=name):
                kept = getattr(self.pair.card, name)
                declared = getattr(self.card, name)
                self.assertEqual(
                    kept, tuple(value for value in declared if value in kept)
                )

    def test_both_arms_carry_identical_constraint_ids(self) -> None:
        # The load-bearing cross-arm assertion. The control arm is measured by
        # `control_constraints`, which enumerates the pair's card directly, while
        # every authored arm re-derives its slots through `constraint_slots`. If
        # the reduction reached only one of the two, these id sets would differ
        # and `align_on_pair_id` would contrast two cards of different lengths --
        # an information asymmetry wearing a vocabulary contrast's clothes.
        authored = constraint_slots(
            self.pair,
            vocabulary=_THIN_VOCABULARY,
            products={str(_THIN_TARGET["parent_asin"]): _THIN_TARGET},
        )
        control = control_constraints(
            (self.pair,), products={str(_THIN_TARGET["parent_asin"]): _THIN_TARGET}
        )
        self.assertEqual(
            tuple(slot.item_id() for slot in authored),
            tuple(entry.slot.item_id() for entry in control),
        )
        self.assertEqual(
            tuple(slot.control_phrase for slot in authored),
            tuple(entry.phrase for entry in control),
        )
        self.assertEqual(len(authored), 2)

    def test_the_reduction_is_idempotent(self) -> None:
        # Load-bearing rather than tidy: `author_arm` calls `constraint_slots`
        # again on the card this produced, and a second reduction that removed
        # anything further would renumber the positions out from under the
        # committed divergence log.
        again = _reduced(
            self.pair.card, target=_THIN_TARGET, vocabulary=_THIN_VOCABULARY
        )
        self.assertEqual(again.card, self.pair.card)

    def test_a_fully_suppliable_card_is_returned_unchanged(self) -> None:
        card = IntentCard(
            target_category="jacket",
            hard_constraints=(_MATERIAL_COTTON, _FEATURE),
            soft_preferences=(_COLOR, _STYLE),
        )
        reduced = _reduced(card, target=_RICH_TARGET, vocabulary=_RICH_VOCABULARY)
        self.assertEqual(reduced.card, card)

    def test_a_pair_that_cannot_keep_a_whole_list_is_refused(self) -> None:
        card = IntentCard(
            target_category="jacket",
            hard_constraints=(_MATERIAL_COTTON, _MATERIAL_WOOL),
            soft_preferences=(_COLOR, _SIZE),
        )
        with self.assertRaises(GenerateError) as raised:
            _reduced(card, target=_POOR_TARGET, vocabulary=_POOR_VOCABULARY)
        self.assertIn("would lose every soft_preferences", str(raised.exception))

    def test_the_pair_identity_survives_the_reduction(self) -> None:
        # A reduction that minted a new pair id or re-pointed the target would
        # break the join the whole corpus is assembled on.
        self.assertEqual(self.pair.pair_id, pair_id(1))
        self.assertEqual(self.pair.target, str(_THIN_TARGET["parent_asin"]))
        self.assertEqual(self.pair.scenario_type, "buying")


class SlotExhaustionTest(unittest.TestCase):
    """Under exhaustion the assignment must reuse a bucket, not spend a fresh one."""

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
        # The non-vacuity guard for the assignment half. Bucket agreement is free
        # while unspent same-bucket pairs remain, so a comfortable gist never
        # reaches the reuse branch and every other assertion in this class would
        # pass without exercising the branch it names.
        self.assertGreater(len(self.slots), len(self.pairs))
        used = [(slot.gist_attribute, slot.gist_value) for slot in self.slots]
        self.assertGreater(
            len(used), len(set(used)), "no pair was reused, so no fallback ran"
        )

    def test_the_second_same_bucket_slot_reuses_rather_than_crossing_buckets(self) -> None:
        first, second = self.slots[0], self.slots[1]
        self.assertEqual(first.bucket, "material")
        self.assertEqual(second.bucket, "material")
        # Under the 02-09 ordering `second` took the first UNSPENT pair --
        # `color=black` -- because unspent outranked same-bucket. That item could
        # not be authored at all, and it also stole the pair the colour slot
        # needed, so one defect produced two broken items.
        self.assertEqual(
            (second.gist_attribute, second.gist_value),
            (first.gist_attribute, first.gist_value),
        )
        self.assertEqual(second.gist_attribute, "material")

    def test_reuse_does_not_steal_the_pair_a_later_slot_needs(self) -> None:
        by_bucket = {slot.bucket: slot.gist_attribute for slot in self.slots}
        self.assertEqual(by_bucket["color"], "color")
        self.assertEqual(by_bucket["size"], "size")

    def test_assignment_is_deterministic(self) -> None:
        repeated = _slots(
            self.card, target=_THIN_TARGET, vocabulary=_THIN_VOCABULARY
        )
        self.assertEqual(self.slots, repeated)


class DefectiveOrderingTest(unittest.TestCase):
    """The negative half: show `bucket_violations` reports the ordering it must."""

    def test_preferring_unspent_over_same_bucket_is_reported(self) -> None:
        violations = bucket_violations(_defectively_assigned_slots())
        # Two items, not one: the wrongly-assigned material slot AND the colour
        # slot whose pair it consumed. That second-order damage is why the 02-09
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

    def test_emitting_an_unsuppliable_slot_is_reported(self) -> None:
        # The negative half of the SUPPLY property. Without this a
        # `unsuppliable_slots` that returned `()` unconditionally would make every
        # omission assertion in this module pass.
        suppliable = _suppliable_buckets(_THIN_TARGET, _THIN_VOCABULARY)
        emitted = ConstraintSlot(
            pair_id=pair_id(1),
            target=str(_THIN_TARGET["parent_asin"]),
            slot="hard_constraints",
            position=1,
            control_phrase=_USE_CASE,
            bucket=classify_constraint(_USE_CASE),
            gist_attribute="color",
            gist_value="black",
            gist_payload="color=black",
        )
        self.assertEqual(
            unsuppliable_slots((emitted,), suppliable),
            ("probe_v1_0001:h1 bucket=use_case",),
        )


def _defectively_assigned_slots() -> tuple[ConstraintSlot, ...]:
    """The 02-09 preference order, reproduced to be refused.

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
