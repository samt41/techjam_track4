from __future__ import annotations

import unittest

from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    ConstraintStatus,
    EvidenceKind,
    PreferenceUpdate,
    Strength,
    UpdateAction,
)
from starter.shopping_agent.preference_ledger import PreferenceLedger


def update(
    action: UpdateAction,
    attribute: Attribute,
    value: str | None,
    *,
    excluded: bool = False,
    strength: Strength = Strength.SOFT,
    confidence: float = 0.80,
    turn: int = 1,
    evidence_kind: EvidenceKind = EvidenceKind.PROVISIONAL_PREFERENCE,
    preference_group_id: str = "test-preference",
) -> PreferenceUpdate:
    return PreferenceUpdate(
        action=action,
        attribute=attribute,
        operator=ComparisonOperator.EQUALS,
        value=value,
        excluded=excluded,
        strength=strength,
        confidence=confidence,
        source_turn=turn,
        source_text=value or "no preference",
        evidence_kind=evidence_kind,
        preference_group_id=preference_group_id,
    )


def retract_provisional(*, group: str, turn: int = 2) -> PreferenceUpdate:
    return PreferenceUpdate(
        action=UpdateAction.RETRACT_PROVISIONAL,
        attribute=None,
        operator=ComparisonOperator.EQUALS,
        value=None,
        excluded=False,
        strength=Strength.SOFT,
        confidence=0.98,
        source_turn=turn,
        source_text="actually",
        evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
        preference_group_id=group,
    )


class PreferenceLedgerTest(unittest.TestCase):
    def test_generic_override_retracts_latest_provisional_group_only(self) -> None:
        ledger = PreferenceLedger()
        ledger.apply((
            update(
                UpdateAction.SET,
                Attribute.CATEGORY,
                "boots",
                evidence_kind=EvidenceKind.CATEGORY_ANCHOR,
                preference_group_id="category",
            ),
            update(
                UpdateAction.SET,
                Attribute.COLOR,
                "black",
                evidence_kind=EvidenceKind.PROVISIONAL_PREFERENCE,
                preference_group_id="initial-preference",
            ),
        ))

        intent = ledger.apply((
            retract_provisional(group="override"),
            update(
                UpdateAction.SET,
                Attribute.MATERIAL,
                "leather",
                strength=Strength.HARD,
                confidence=0.98,
                turn=2,
                evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
                preference_group_id="override",
            ),
        ))

        self.assertEqual(
            [(item.attribute, item.value) for item in intent.active_constraints],
            [(Attribute.CATEGORY, "boots"), (Attribute.MATERIAL, "leather")],
        )
        self.assertEqual(
            intent.constraint_history[1].status,
            ConstraintStatus.RETRACTED,
        )

    def test_named_same_attribute_correction_replaces_provisional_value(self) -> None:
        ledger = PreferenceLedger()
        ledger.apply((update(
            UpdateAction.SET,
            Attribute.COLOR,
            "red",
            preference_group_id="red-preference",
        ),))

        intent = ledger.apply((
            retract_provisional(group="override"),
            update(
                UpdateAction.SET,
                Attribute.COLOR,
                "blue",
                turn=2,
                evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
                preference_group_id="override",
            ),
        ))

        self.assertEqual(
            [(item.attribute, item.value) for item in intent.active_constraints],
            [(Attribute.COLOR, "blue")],
        )

    def test_override_without_provisional_referent_still_starts_new_scope(self) -> None:
        ledger = PreferenceLedger()
        ledger.record_question(Attribute.COLOR)

        intent = ledger.apply((retract_provisional(group="override"),))

        self.assertEqual(intent.intent_version, 1)
        self.assertEqual(intent.asked_attributes, ())

    def test_retraction_preserves_hard_requirement_and_exclusion(self) -> None:
        ledger = PreferenceLedger()
        ledger.apply((
            update(
                UpdateAction.SET,
                Attribute.CATEGORY,
                "boots",
                strength=Strength.HARD,
                confidence=0.98,
                evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
                preference_group_id="hard-category",
            ),
            update(
                UpdateAction.ADD,
                Attribute.MATERIAL,
                "leather",
                excluded=True,
                strength=Strength.HARD,
                confidence=0.98,
                evidence_kind=EvidenceKind.EXCLUSION,
                preference_group_id="exclusion",
            ),
            update(
                UpdateAction.SET,
                Attribute.COLOR,
                "black",
                preference_group_id="provisional-color",
            ),
        ))

        intent = ledger.apply((retract_provisional(group="override"),))

        self.assertEqual(
            {(item.attribute, item.value, item.excluded) for item in intent.active_constraints},
            {
                (Attribute.CATEGORY, "boots", False),
                (Attribute.MATERIAL, "leather", True),
            },
        )

    def test_retraction_removes_only_latest_of_multiple_provisional_groups(self) -> None:
        ledger = PreferenceLedger()
        ledger.apply((
            update(
                UpdateAction.SET,
                Attribute.COLOR,
                "black",
                preference_group_id="earlier-color",
            ),
            update(
                UpdateAction.SET,
                Attribute.MATERIAL,
                "canvas",
                preference_group_id="later-material",
            ),
        ))

        intent = ledger.apply((retract_provisional(group="override"),))

        self.assertEqual(
            [(item.attribute, item.value) for item in intent.active_constraints],
            [(Attribute.COLOR, "black")],
        )

    def test_removed_constraint_concept_does_not_resurface(self) -> None:
        ledger = PreferenceLedger()
        ledger.apply((update(
            UpdateAction.ADD,
            Attribute.FEATURE,
            "waterproof",
            preference_group_id="waterproof",
        ),))

        intent = ledger.apply((update(
            UpdateAction.REMOVE,
            Attribute.FEATURE,
            "waterproof",
            turn=2,
            evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
            preference_group_id="removal",
        ),))

        self.assertEqual(intent.active_constraints, ())
        self.assertEqual(intent.weighted_concepts, ())

    def test_set_supersedes_scalar_value_and_retains_history(self) -> None:
        ledger = PreferenceLedger()
        first = ledger.apply((update(UpdateAction.SET, Attribute.MATERIAL, "leather"),))
        second = ledger.apply((
            update(UpdateAction.SET, Attribute.MATERIAL, "canvas", turn=2),
        ))

        self.assertEqual(
            [(constraint.value, constraint.status) for constraint in second.constraint_history],
            [
                ("leather", ConstraintStatus.SUPERSEDED),
                ("canvas", ConstraintStatus.ACTIVE),
            ],
        )
        self.assertEqual(
            [constraint.value for constraint in second.active_constraints],
            ["canvas"],
        )
        self.assertEqual((first.intent_version, second.intent_version), (1, 2))

    def test_add_preserves_compatible_feature_values(self) -> None:
        ledger = PreferenceLedger()
        intent = ledger.apply((
            update(UpdateAction.ADD, Attribute.FEATURE, "waterproof"),
            update(UpdateAction.ADD, Attribute.FEATURE, "insulated"),
        ))

        self.assertEqual(
            [constraint.value for constraint in intent.active_constraints],
            ["waterproof", "insulated"],
        )
        self.assertEqual(intent.intent_version, 1)

    def test_remove_deactivates_only_matching_constraint(self) -> None:
        ledger = PreferenceLedger()
        ledger.apply((
            update(UpdateAction.ADD, Attribute.FEATURE, "waterproof"),
            update(UpdateAction.ADD, Attribute.FEATURE, "insulated"),
        ))
        intent = ledger.apply((
            update(UpdateAction.REMOVE, Attribute.FEATURE, "waterproof", turn=2),
        ))

        self.assertEqual(
            [constraint.value for constraint in intent.active_constraints],
            ["insulated"],
        )
        self.assertEqual(
            intent.constraint_history[0].status,
            ConstraintStatus.REMOVED,
        )

    def test_decline_is_recorded_without_changing_intent_version(self) -> None:
        ledger = PreferenceLedger()
        intent = ledger.apply((
            update(UpdateAction.DECLINE, Attribute.COLOR, None),
        ))

        self.assertEqual(intent.declined_attributes, frozenset({Attribute.COLOR}))
        self.assertEqual(intent.intent_version, 0)

    def test_reapplying_identical_constraint_is_idempotent(self) -> None:
        ledger = PreferenceLedger()
        first = ledger.apply((update(UpdateAction.SET, Attribute.COLOR, "black"),))
        second = ledger.apply((
            update(UpdateAction.SET, Attribute.COLOR, "black", turn=2),
        ))

        self.assertEqual(second.intent_version, first.intent_version)
        self.assertEqual(len(second.active_constraints), 1)

    def test_explicit_override_advances_version_for_history_reset(self) -> None:
        ledger = PreferenceLedger()
        first = ledger.apply((update(UpdateAction.SET, Attribute.COLOR, "black"),))
        second = ledger.apply((
            retract_provisional(group="override"),
            update(
                UpdateAction.SET,
                Attribute.COLOR,
                "black",
                turn=2,
                evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
                preference_group_id="override",
            ),
        ))

        self.assertEqual(second.intent_version, first.intent_version + 1)


if __name__ == "__main__":
    unittest.main()
