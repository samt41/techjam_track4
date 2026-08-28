from __future__ import annotations

from dataclasses import replace

from starter.shopping_agent.models import (
    Attribute,
    ConstraintStatus,
    EvidenceKind,
    PreferenceConstraint,
    PreferenceUpdate,
    ShoppingIntent,
    Strength,
    UpdateAction,
    WeightedConcept,
)


_MULTI_VALUE_ATTRIBUTES = frozenset({
    Attribute.BUDGET,
    Attribute.FEATURE,
    Attribute.OTHER,
})


class PreferenceLedger:
    def __init__(self) -> None:
        self._intent = ShoppingIntent(
            active_constraints=(),
            constraint_history=(),
            weighted_concepts=(),
            declined_attributes=frozenset(),
            asked_attributes=(),
            intent_version=0,
        )

    @property
    def intent(self) -> ShoppingIntent:
        return self._intent

    def apply(self, updates: tuple[PreferenceUpdate, ...]) -> ShoppingIntent:
        history = list(self._intent.constraint_history)
        declined = set(self._intent.declined_attributes)
        concepts = list(self._intent.weighted_concepts)
        active_changed = False
        explicit_override = any(
            update.action is UpdateAction.RETRACT_PROVISIONAL
            for update in updates
        )
        # Attributes the override newly constrains. A provisional preference on a
        # DIFFERENT attribute survives as a soft scoring tie-breaker (the user
        # replaced one axis, not their whole intent); one on the SAME attribute
        # is a genuine correction and is retracted. An override with no added
        # constraint is a pure retraction, so everything in the group goes.
        override_added_attributes = frozenset(
            update.attribute
            for update in updates
            if update.action in (UpdateAction.SET, UpdateAction.ADD)
            and update.attribute is not None
        )

        for update in updates:
            update.validate()
            if update.action is UpdateAction.RETRACT_PROVISIONAL:
                provisional_group_id = next(
                    (
                        constraint.preference_group_id
                        for constraint in reversed(history)
                        if constraint.status is ConstraintStatus.ACTIVE
                        and constraint.evidence_kind
                        is EvidenceKind.PROVISIONAL_PREFERENCE
                    ),
                    None,
                )
                if provisional_group_id is not None:
                    for index, constraint in enumerate(history):
                        if (
                            constraint.status is ConstraintStatus.ACTIVE
                            and constraint.preference_group_id
                            == provisional_group_id
                            and (
                                not override_added_attributes
                                or constraint.attribute
                                in override_added_attributes
                            )
                        ):
                            history[index] = replace(
                                constraint,
                                status=ConstraintStatus.RETRACTED,
                            )
                    active_changed = True
                continue
            if update.action is UpdateAction.DECLINE:
                assert update.attribute is not None
                declined.add(update.attribute)
                continue
            if update.value is None:
                continue
            assert update.attribute is not None
            if update.action is UpdateAction.REMOVE:
                removed = False
                for index, constraint in enumerate(history):
                    if (
                        constraint.status is ConstraintStatus.ACTIVE
                        and constraint.attribute is update.attribute
                        and constraint.value == update.value
                    ):
                        history[index] = replace(
                            constraint,
                            status=ConstraintStatus.REMOVED,
                        )
                        removed = True
                active_changed = active_changed or removed
                continue

            identical = any(
                constraint.status is ConstraintStatus.ACTIVE
                and constraint.attribute is update.attribute
                and constraint.operator is update.operator
                and constraint.value == update.value
                and constraint.excluded is update.excluded
                for constraint in history
            )
            if identical:
                continue

            if (
                update.action is UpdateAction.SET
                and update.attribute not in _MULTI_VALUE_ATTRIBUTES
                and not update.excluded
            ):
                for index, constraint in enumerate(history):
                    if (
                        constraint.status is ConstraintStatus.ACTIVE
                        and constraint.attribute is update.attribute
                        and not constraint.excluded
                    ):
                        history[index] = replace(
                            constraint,
                            status=ConstraintStatus.SUPERSEDED,
                        )

            constraint = PreferenceConstraint(
                constraint_id=self._constraint_id(update, len(history) + 1),
                attribute=update.attribute,
                operator=update.operator,
                value=update.value,
                excluded=update.excluded,
                strength=update.strength,
                confidence=update.confidence,
                source_turn=update.source_turn,
                source_text=update.source_text,
                evidence_kind=update.evidence_kind,
                preference_group_id=update.preference_group_id,
                status=ConstraintStatus.ACTIVE,
            )
            constraint.validate()
            history.append(constraint)
            declined.discard(update.attribute)
            if not update.excluded:
                concepts.append(WeightedConcept(
                    value=update.value,
                    weight=self._concept_weight(update),
                    source_turn=update.source_turn,
                    preference_group_id=update.preference_group_id,
                ))
            active_changed = True

        active_constraints = tuple(
            constraint
            for constraint in history
            if constraint.status is ConstraintStatus.ACTIVE
        )
        active_group_ids = {
            constraint.preference_group_id for constraint in active_constraints
        }
        concepts = [
            concept
            for concept in concepts
            if concept.preference_group_id in active_group_ids
        ]
        self._intent = ShoppingIntent(
            active_constraints=active_constraints,
            constraint_history=tuple(history),
            weighted_concepts=tuple(concepts),
            declined_attributes=(
                frozenset() if explicit_override else frozenset(declined)
            ),
            asked_attributes=(
                () if explicit_override else self._intent.asked_attributes
            ),
            intent_version=(
                self._intent.intent_version + 1
                if active_changed or explicit_override
                else self._intent.intent_version
            ),
        )
        return self._intent

    def record_question(self, attribute: Attribute) -> ShoppingIntent:
        if attribute in self._intent.asked_attributes:
            return self._intent
        self._intent = replace(
            self._intent,
            asked_attributes=(*self._intent.asked_attributes, attribute),
        )
        return self._intent

    @staticmethod
    def _constraint_id(update: PreferenceUpdate, ordinal: int) -> str:
        assert update.attribute is not None
        value = (update.value or "none").replace(" ", "-")
        polarity = "exclude" if update.excluded else "include"
        return (
            f"t{update.source_turn}:{update.attribute.value}:"
            f"{update.operator.value}:{value}:{polarity}:{ordinal}"
        )

    @staticmethod
    def _concept_weight(update: PreferenceUpdate) -> float:
        multiplier = 1.0 if update.strength is Strength.SOFT else 1.25
        return min(1.0, update.confidence * multiplier)
