from __future__ import annotations

import re

from starter.shopping_agent.catalog_index import CatalogIndex
from starter.shopping_agent.models import (
    Attribute,
    ComparisonOperator,
    DialogueAct,
    EvidenceKind,
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
    r"(?:\bi need\b|\bmake it\b|\binstead(?: i (?:need|want))?\b)"
    r"\s+(?:to be\s+)?([a-z0-9][a-z0-9 -]*)"
)
_SCOPE_BOUNDARY_RE = re.compile(r"[;,.!?]|\b(?:but|however|instead|rather|although)\b")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SLATE_FEEDBACK_RE = re.compile(
    r"^(?:show me (?:others|more|something else)|more options|other options|next)$"
)
_INTENT_OVERRIDE_RE = re.compile(
    r"^(?:actually|instead|change|switch|rather|ignore my earlier preference)\b"
)
_ATTRIBUTE_PRIORITY = (
    Attribute.CATEGORY,
    Attribute.MATERIAL,
    Attribute.COLOR,
    Attribute.SIZE,
    Attribute.STYLE,
    Attribute.BRAND,
    Attribute.FEATURE,
    Attribute.USE_CASE,
)
# Single-word values that also appear as junk metadata in the catalog (a brand
# literally named "key", a color "m", a feature "no"). Matching these from
# incidental sentence words manufactures false constraints that pollute the
# lexical query, so they are never extracted as standalone metadata mentions.
# SIZE is exempted at the call site, so "a"/"m"/"s"/"l"/"xl" still parse as sizes.
_UNSAFE_METADATA_TOKENS = frozenset({
    # articles, conjunctions, prepositions, pronouns
    "a", "an", "and", "but", "for", "i", "in", "is", "it", "me", "my",
    "of", "on", "or", "the", "to", "at", "as", "be", "by", "if", "so",
    "no", "not", "with", "without", "that", "this", "these", "those",
    # single letters that are junk catalog values outside SIZE
    "m", "s", "l", "b", "c", "d", "e", "f", "g", "h", "j", "k", "n",
    "o", "p", "q", "r", "t", "u", "v", "w", "x", "y", "z",
    # common request words that collide with junk brand/feature values
    "key", "new", "set", "one", "two", "need", "want", "looking",
    "requirement", "prefer", "preference", "additional", "specific",
    "matters", "quality", "please", "judgment", "something", "options",
})


class ConstraintExtractor:
    def __init__(self, catalog_index: CatalogIndex) -> None:
        self._catalog_index = catalog_index
        mention_by_phrase: dict[str, tuple[str, Attribute]] = {}
        max_tokens = 1
        for attribute in _ATTRIBUTE_PRIORITY:
            for value in catalog_index.values_for(attribute):
                canonical_phrase = " ".join(_TOKEN_RE.findall(value))
                if (
                    not canonical_phrase
                    or (
                        attribute is not Attribute.SIZE
                        and canonical_phrase in _UNSAFE_METADATA_TOKENS
                    )
                ):
                    continue
                mention_by_phrase.setdefault(canonical_phrase, (value, attribute))
                max_tokens = max(max_tokens, len(canonical_phrase.split()))
        self._mention_by_phrase = mention_by_phrase
        self._max_mention_tokens = max_tokens

    def extract(
        self,
        message: str,
        turn: int,
        asked_attribute: Attribute | None,
    ) -> tuple[PreferenceUpdate, ...]:
        normalized = normalize_text(message)
        dialogue_act = self.dialogue_act(message, asked_attribute)
        if not normalized:
            return ()
        if _SLATE_FEEDBACK_RE.fullmatch(normalized):
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
                evidence_kind=EvidenceKind.CLARIFICATION_ANSWER,
                preference_group_id=self._group_id(turn, 0),
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
                    evidence_kind=EvidenceKind.CLARIFICATION_ANSWER,
                    preference_group_id=self._group_id(turn, 0),
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
                        evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
                        preference_group_id=self._group_id(turn, 0),
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
                    evidence_kind=EvidenceKind.PROVISIONAL_PREFERENCE,
                    preference_group_id=self._group_id(turn, 0),
                ))
        if dialogue_act is DialogueAct.INTENT_OVERRIDE:
            updates.insert(0, self._update(
                action=UpdateAction.RETRACT_PROVISIONAL,
                attribute=None,
                operator=ComparisonOperator.EQUALS,
                value=None,
                excluded=False,
                strength=Strength.SOFT,
                confidence=0.98,
                turn=turn,
                source_text=message,
                evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
                preference_group_id=f"t{turn}:override",
            ))
        return tuple(updates)

    @staticmethod
    def dialogue_act(
        message: str,
        asked_attribute: Attribute | None,
    ) -> DialogueAct:
        normalized = normalize_text(message)
        if not normalized:
            return DialogueAct.EMPTY
        if _SLATE_FEEDBACK_RE.fullmatch(normalized):
            return DialogueAct.SLATE_FEEDBACK
        if _INTENT_OVERRIDE_RE.search(normalized):
            return DialogueAct.INTENT_OVERRIDE
        if asked_attribute is not None and _DECLINE_RE.fullmatch(normalized):
            return DialogueAct.DECLINE
        if asked_attribute is not None:
            return DialogueAct.CLARIFICATION_ANSWER
        return DialogueAct.REQUEST

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
                    evidence_kind=EvidenceKind.EXPLICIT_REQUIREMENT,
                    preference_group_id=self._group_id(
                        turn,
                        self._clause_ordinal(normalized, match.start()),
                    ),
                ))
        return tuple(updates)

    def _catalog_updates(
        self,
        normalized: str,
        source_text: str,
        turn: int,
    ) -> tuple[tuple[PreferenceUpdate, ...], tuple[tuple[int, int], ...]]:
        tokens = tuple(_TOKEN_RE.finditer(normalized))
        possible: list[tuple[int, int, str, Attribute]] = []
        for start_index, start_token in enumerate(tokens):
            last_index = min(len(tokens), start_index + self._max_mention_tokens)
            phrase_tokens: list[str] = []
            for end_index in range(start_index, last_index):
                phrase_tokens.append(tokens[end_index].group())
                mention = self._mention_by_phrase.get(" ".join(phrase_tokens))
                if mention is not None:
                    value, attribute = mention
                    possible.append((
                        start_token.start(),
                        tokens[end_index].end(),
                        value,
                        attribute,
                    ))

        occupied: list[tuple[int, int]] = []
        found: list[tuple[int, int, str, Attribute]] = []
        for start, end, value, attribute in sorted(
            possible,
            key=lambda item: (-(item[1] - item[0]), item[0], item[3].value),
        ):
            if self._span_is_covered((start, end), tuple(occupied)):
                continue
            occupied.append((start, end))
            found.append((start, end, value, attribute))
        found.sort(key=lambda item: item[0])

        updates: list[PreferenceUpdate] = []
        for start, _, value, attribute in found:
            scope = self._scope_prefix(normalized, start)
            removal = _REMOVAL_CUE_RE.search(scope) is not None
            excluded = not removal and _NEGATION_CUE_RE.search(scope) is not None
            hard = excluded or _HARD_CUE_RE.search(scope) is not None
            if excluded:
                evidence_kind = EvidenceKind.EXCLUSION
            elif removal or _INTENT_OVERRIDE_RE.search(normalized):
                evidence_kind = EvidenceKind.EXPLICIT_REQUIREMENT
            elif attribute is Attribute.CATEGORY:
                evidence_kind = EvidenceKind.CATEGORY_ANCHOR
            elif hard:
                evidence_kind = EvidenceKind.EXPLICIT_REQUIREMENT
            else:
                evidence_kind = EvidenceKind.PROVISIONAL_PREFERENCE
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
                evidence_kind=evidence_kind,
                preference_group_id=(
                    self._group_id(
                        turn,
                        self._clause_ordinal(normalized, start),
                    )
                    + (
                        ":category-anchor"
                        if evidence_kind is EvidenceKind.CATEGORY_ANCHOR
                        else ""
                    )
                ),
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
    def _clause_ordinal(normalized: str, position: int) -> int:
        return 1 + sum(
            1 for match in _SCOPE_BOUNDARY_RE.finditer(normalized[:position])
        )

    @staticmethod
    def _group_id(turn: int, clause_ordinal: int) -> str:
        return f"t{turn}:clause{clause_ordinal}"

    @staticmethod
    def _update(
        *,
        action: UpdateAction,
        attribute: Attribute | None,
        operator: ComparisonOperator,
        value: str | None,
        excluded: bool,
        strength: Strength,
        confidence: float,
        turn: int,
        source_text: str,
        evidence_kind: EvidenceKind,
        preference_group_id: str,
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
            evidence_kind=evidence_kind,
            preference_group_id=preference_group_id,
        )


def _canonical_number(value: str) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)
