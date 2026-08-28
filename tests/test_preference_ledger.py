from __future__ import annotations

import unittest

from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    ConstraintStatus,
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
    intent_override: bool = False,
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
        intent_override=intent_override,
    )


class PreferenceLedgerTest(unittest.TestCase):
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
        second = ledger.apply((update(
            UpdateAction.SET,
            Attribute.COLOR,
            "black",
            turn=2,
            intent_override=True,
        ),))

        self.assertEqual(second.intent_version, first.intent_version + 1)


if __name__ == "__main__":
    unittest.main()
