from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Attribute(StrEnum):
    CATEGORY = "category"
    MATERIAL = "material"
    COLOR = "color"
    SIZE = "size"
    STYLE = "style"
    BRAND = "brand"
    BUDGET = "budget"
    FEATURE = "feature"
    USE_CASE = "use_case"
    OTHER = "other"


class Strength(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class ComparisonOperator(StrEnum):
    EQUALS = "equals"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"


class ConstraintStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"
    SUPERSEDED = "superseded"


class UpdateAction(StrEnum):
    SET = "set"
    ADD = "add"
    REMOVE = "remove"
    DECLINE = "decline"


class RetrievalRoute(StrEnum):
    METADATA = "metadata"
    EXACT_FTS = "exact_fts"
    EXPANDED_FTS = "expanded_fts"
    CATEGORY_FALLBACK = "category_fallback"
    COUNTERFACTUAL = "counterfactual"


@dataclass(frozen=True, slots=True)
class UserProfile:
    purchase_frequency: str
    average_prior_rating: float | None
    rating_style: str
    preference_tags: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class ProductRecord:
    parent_asin: str
    title: str
    categories: tuple[str, ...]
    features: tuple[str, ...]
    description: str
    details: tuple[tuple[str, str], ...]
    store: str
    price: float | None
    average_rating: float | None
    rating_number: int
    searchable_text: str


@dataclass(frozen=True, slots=True)
class PreferenceConstraint:
    constraint_id: str
    attribute: Attribute
    operator: ComparisonOperator
    value: str
    excluded: bool
    strength: Strength
    confidence: float
    source_turn: int
    source_text: str
    status: ConstraintStatus

    def validate(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("constraint confidence must be between 0 and 1")
        if self.strength is Strength.HARD and self.confidence < 0.90:
            raise ValueError("hard constraint confidence must be at least 0.90")


@dataclass(frozen=True, slots=True)
class PreferenceUpdate:
    action: UpdateAction
    attribute: Attribute
    operator: ComparisonOperator
    value: str | None
    excluded: bool
    strength: Strength
    confidence: float
    source_turn: int
    source_text: str
    intent_override: bool = False


@dataclass(frozen=True, slots=True)
class WeightedConcept:
    value: str
    weight: float
    source_turn: int


@dataclass(frozen=True, slots=True)
class ShoppingIntent:
    active_constraints: tuple[PreferenceConstraint, ...]
    constraint_history: tuple[PreferenceConstraint, ...]
    weighted_concepts: tuple[WeightedConcept, ...]
    declined_attributes: frozenset[Attribute]
    asked_attributes: tuple[Attribute, ...]
    intent_version: int


@dataclass(slots=True)
class RecommendationHistory:
    _intent_version: int | None = None
    _shown_product_ids: frozenset[str] = frozenset()

    def shown_for(self, intent_version: int) -> frozenset[str]:
        if self._intent_version != intent_version:
            return frozenset()
        return self._shown_product_ids

    def record(self, intent_version: int, product_ids: tuple[str, ...]) -> None:
        if self._intent_version != intent_version:
            self._intent_version = intent_version
            self._shown_product_ids = frozenset(product_ids)
            return
        self._shown_product_ids = self._shown_product_ids.union(product_ids)


@dataclass(frozen=True, slots=True)
class RouteEvidence:
    route: RetrievalRoute
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    route: RetrievalRoute
    query_terms: tuple[str, ...]
    attribute: Attribute | None
    attribute_value: str | None
    required_constraint_ids: tuple[str, ...]
    relaxed_constraint_ids: tuple[str, ...]
    limit: int


@dataclass(frozen=True, slots=True)
class ProductCandidate:
    parent_asin: str
    evidence: tuple[RouteEvidence, ...]
    relaxed_constraint_id: str | None


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuestionCandidate:
    attribute: Attribute
    information_gain: float
    effective_possibilities: float
    answerability: float
    coverage: float
    relevance: float
    score: float
    focus_value: str | None


@dataclass(frozen=True, slots=True)
class ClarificationDecision:
    attribute: Attribute
    prompt: str
    expected_information_gain: float


@dataclass(frozen=True, slots=True)
class RankedRecommendation:
    parent_asin: str
    score: float
    exact_match: bool
    relaxed_constraint_id: str | None


@dataclass(frozen=True, slots=True)
class TurnResponse:
    message: str
    ask_attribute: Attribute | None
    recommendations: tuple[RankedRecommendation, ...]
