from __future__ import annotations

import re

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    PreferenceUpdate,
    Strength,
    UpdateAction,
)
from starter.shopping_agent.text_normalization import normalize_text


_DECLINE_RE = re.compile(
    r"^(?:no|none|any|either|no preference|doesn'?t matter|do not care)$"
)
_PRICE_PATTERNS = (
    (
        re.compile(r"(?:under|below|at most|up to|max(?:imum)?(?: of)?)\s*\$?\s*(\d+(?:\.\d+)?)"),
        ComparisonOperator.LESS_THAN_OR_EQUAL,
    ),
    (
        re.compile(r"(?:over|above|at least|min(?:imum)?(?: of)?)\s*\$?\s*(\d+(?:\.\d+)?)"),
        ComparisonOperator.GREATER_THAN_OR_EQUAL,
    ),
)
_REMOVAL_CUE_RE = re.compile(r"\b(?:ignore|remove|drop|forget|no longer)\b")
_NEGATION_CUE_RE = re.compile(r"\b(?:not|no|without|avoid|exclude)\b")
_HARD_CUE_RE = re.compile(r"\b(?:must|need|required|only|have to)\b")
_CONTEXT_VALUE_RE = re.compile(
    r"(?:\bi need\b|\bmake it\b|\binstead(?: i (?:need|want))?\b)\s+(?:to be\s+)?([a-z0-9][a-z0-9 -]*)"
)
_SCOPE_BOUNDARY_RE = re.compile(r"[;,.!?]|\b(?:but|however|instead|rather|although)\b")


class ConstraintExtractor:
    def __init__(self, catalog_index: CatalogIndex) -> None:
        self._catalog_index = catalog_index
        mentions: list[tuple[str, Attribute]] = []
        for attribute in Attribute:
            if attribute in (Attribute.BUDGET, Attribute.OTHER):
                continue
            mentions.extend(
                (value, attribute) for value in catalog_index.values_for(attribute)
            )
        self._mentions = tuple(sorted(
            set(mentions),
            key=lambda item: (-len(item[0]), item[0], item[1].value),
        ))

    def extract(
        self,
        message: str,
        turn: int,
        asked_attribute: Attribute | None,
    ) -> tuple[PreferenceUpdate, ...]:
        normalized = normalize_text(message)
        if not normalized:
            return ()
        if asked_attribute is not None and _DECLINE_RE.fullmatch(normalized):
            return (self._update(
                action=UpdateAction.DECLINE,
                attribute=asked_attribute,
                operator=ComparisonOperator.EQUALS,
                value=None,
                excluded=False,
                strength=Strength.SOFT,
                confidence=0.98,
                turn=turn,
                source_text=message,
            ),)

        price_updates = self._price_updates(normalized, message, turn)
        mention_updates, spans = self._catalog_updates(normalized, message, turn)
        updates = list(price_updates)
        updates.extend(mention_updates)

        if asked_attribute is not None and not updates:
            value = self._clean_context_value(normalized)
            if value:
                updates.append(self._update(
                    action=UpdateAction.SET,
                    attribute=asked_attribute,
                    operator=ComparisonOperator.EQUALS,
                    value=value,
                    excluded=False,
                    strength=Strength.SOFT,
                    confidence=0.98,
                    turn=turn,
                    source_text=message,
                ))

        inherited_attribute = self._removed_attribute(updates)
        if inherited_attribute is not None:
            contextual_match = _CONTEXT_VALUE_RE.search(normalized)
            if contextual_match is not None:
                value = self._clean_context_value(contextual_match.group(1))
                if value and not self._span_is_covered(contextual_match.span(1), spans):
                    updates.append(self._update(
                        action=UpdateAction.SET,
                        attribute=inherited_attribute,
                        operator=ComparisonOperator.EQUALS,
                        value=value,
                        excluded=False,
                        strength=Strength.HARD,
                        confidence=0.98,
                        turn=turn,
                        source_text=message,
                    ))

        if not updates:
            residual = self._clean_context_value(normalized)
            if residual:
                updates.append(self._update(
                    action=UpdateAction.ADD,
                    attribute=Attribute.OTHER,
                    operator=ComparisonOperator.EQUALS,
                    value=residual,
                    excluded=False,
                    strength=Strength.SOFT,
                    confidence=0.55,
                    turn=turn,
                    source_text=message,
                ))
        return tuple(updates)

    def _price_updates(
        self,
        normalized: str,
        source_text: str,
        turn: int,
    ) -> tuple[PreferenceUpdate, ...]:
        updates: list[PreferenceUpdate] = []
        for pattern, operator in _PRICE_PATTERNS:
            for match in pattern.finditer(normalized):
                updates.append(self._update(
                    action=UpdateAction.ADD,
                    attribute=Attribute.BUDGET,
                    operator=operator,
                    value=_canonical_number(match.group(1)),
                    excluded=False,
                    strength=Strength.HARD,
                    confidence=0.92,
                    turn=turn,
                    source_text=source_text,
                ))
        return tuple(updates)

    def _catalog_updates(
        self,
        normalized: str,
        source_text: str,
        turn: int,
    ) -> tuple[tuple[PreferenceUpdate, ...], tuple[tuple[int, int], ...]]:
        found: list[tuple[int, int, str, Attribute]] = []
        occupied: list[tuple[int, int]] = []
        for value, attribute in self._mentions:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])")
            for match in pattern.finditer(normalized):
                if self._span_is_covered(match.span(), tuple(occupied)):
                    continue
                occupied.append(match.span())
                found.append((match.start(), match.end(), value, attribute))
        found.sort(key=lambda item: item[0])

        updates: list[PreferenceUpdate] = []
        for start, _, value, attribute in found:
            scope = self._scope_prefix(normalized, start)
            removal = _REMOVAL_CUE_RE.search(scope) is not None
            excluded = not removal and _NEGATION_CUE_RE.search(scope) is not None
            hard = excluded or _HARD_CUE_RE.search(scope) is not None
            updates.append(self._update(
                action=(
                    UpdateAction.REMOVE
                    if removal
                    else UpdateAction.ADD if excluded else UpdateAction.SET
                ),
                attribute=attribute,
                operator=ComparisonOperator.EQUALS,
                value=value,
                excluded=excluded,
                strength=Strength.HARD if hard else Strength.SOFT,
                confidence=0.98 if removal or excluded else 0.92 if hard else 0.80,
                turn=turn,
                source_text=source_text,
            ))
        return tuple(updates), tuple(occupied)

    @staticmethod
    def _scope_prefix(normalized: str, mention_start: int) -> str:
        prefix = normalized[:mention_start]
        boundaries = tuple(_SCOPE_BOUNDARY_RE.finditer(prefix))
        return prefix[boundaries[-1].end():] if boundaries else prefix

    @staticmethod
    def _clean_context_value(value: str) -> str:
        cleaned = re.sub(r"^(?:a|an|the|to be)\s+", "", value.strip())
        cleaned = re.split(r"[;,.!?]|\b(?:but|however|instead|rather)\b", cleaned)[0]
        return cleaned.strip(" -")

    @staticmethod
    def _removed_attribute(updates: list[PreferenceUpdate]) -> Attribute | None:
        for update in updates:
            if update.action is UpdateAction.REMOVE:
                return update.attribute
        return None

    @staticmethod
    def _span_is_covered(
        span: tuple[int, int],
        occupied: tuple[tuple[int, int], ...],
    ) -> bool:
        return any(span[0] < end and start < span[1] for start, end in occupied)

    @staticmethod
    def _update(
        *,
        action: UpdateAction,
        attribute: Attribute,
        operator: ComparisonOperator,
        value: str | None,
        excluded: bool,
        strength: Strength,
        confidence: float,
        turn: int,
        source_text: str,
    ) -> PreferenceUpdate:
        return PreferenceUpdate(
            action=action,
            attribute=attribute,
            operator=operator,
            value=value,
            excluded=excluded,
            strength=strength,
            confidence=confidence,
            source_turn=turn,
            source_text=source_text,
        )


def _canonical_number(value: str) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)
