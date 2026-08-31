from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from arena.evaluator_bridge import materialize_hidden_fields


CORPUS_SCHEMA_VERSION = 1

SCENARIO_TYPES = ("boundary", "browsing", "buying", "intent_override")

# The official 40/40/15/5 mix (D-30), sorted by key so the constant reads in the
# same order the counts do.
SCENARIO_MIX_TARGET = (
    ("boundary", 0.05),
    ("browsing", 0.40),
    ("buying", 0.40),
    ("intent_override", 0.15),
)

ARMS = ("control", "probe_haiku", "probe_sonnet")

# The evaluator's own `_clean_constraint` limit at local_evaluator.py:48-49. A
# longer authored constraint would be silently truncated by the harness, and the
# committed corpus would then not describe what was actually scored.
MAX_CONSTRAINT_LENGTH = 180

# The override trigger is `turn + 1 == int(override.get("turn", 3))` at
# local_evaluator.py:259, evaluated inside `for turn in range(1, 11)` AFTER the
# `turn == MAX_TURNS` break at :256-257 — so `turn` is 1..9 where the comparison
# runs and the only reachable override turns are 2..10. A turn outside that range
# never fires, and the row would silently score as a plain browsing session.
MIN_OVERRIDE_TURN = 2
MAX_OVERRIDE_TURN = 10

# Measured perfectly collinear with `scenario_type` over all 200 public rows.
# Reproduced for schema fidelity only: `difficulty_bucket` is inert per F-07, so
# this table exists to keep a generated corpus shaped like the shipped one, not
# because anything downstream reads it.
DIFFICULTY_BY_SCENARIO = (
    ("boundary", "medium"),
    ("browsing", "medium"),
    ("buying", "easy"),
    ("intent_override", "hard"),
)

# Measured 200/200 in the shipped set.
CATEGORY_BUCKET = "clothing"

# A `pair_id` is `{corpus_stem}_{index:04d}`, where `corpus_stem` is the registry
# name with its dot replaced by an underscore, computed by `corpus_stem()` below
# and nowhere else (`probe.v1` -> `probe_v1`, so `probe_v1_0007`).
#
# What this regex does NOT do, because it is the easy misreading: it constrains
# the SHAPE of one id and says nothing whatsoever about the DISJOINTNESS of two
# corpora's id sets. `expanded_dev_v1_0007` matches it perfectly and is
# catastrophic inside a `probe.v1` corpus. That is why `validate_corpus` below
# takes the owning corpus name and refuses a foreign stem — the regex cannot.
#
# Why the namespacing is load-bearing rather than cosmetic:
# `paired_contrast.align_on_pair_id` joins two arms on `pair_id`. If pair ids
# were bare counters (`0007`), two arms drawn from DIFFERENT corpora would share
# ids and inner-join into a silently bogus contrast — the exact misreading D-45
# exists to prevent. Namespacing makes that join structurally impossible: the
# intersection of two corpora's pair-id sets is empty, so `align_on_pair_id`
# raises on every id instead of quietly producing a comparison of unrelated
# sessions. A flag the CLI merely declines to set would be weaker, because a
# caller can forget a flag and cannot forget a namespace.
#
# Four digits, zero-padded, so lexicographic order equals positional order at
# 2,000 sessions (the `tests/arena_fixtures.py:45-46` precedent).
PAIR_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_v[0-9]+_[0-9]{4}$")

# A corpus stem must itself be legal as the leading segment of a PAIR_ID_RE id,
# otherwise `corpus_stem()` would happily mint a prefix no generated id can match.
_CORPUS_STEM_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class CorpusSchemaError(ValueError):
    """Raised when a corpus row or file cannot be read or validated safely."""


def _require_mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(
            f"{name} must be a json object, got {type(value).__name__}"
        )
    return value


def _require_sequence(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(
            f"{name} must be a json array, got {type(value).__name__}"
        )
    return tuple(str(item) for item in value)


@dataclass(frozen=True, slots=True)
class SampleProfile:
    """The five measured `user_profile` keys of a shipped public-set row."""

    purchase_frequency: str
    average_prior_rating: float | None
    rating_style: str
    summary: str
    # A tuple, never a list: a list field breaks `frozen=True` hashability and
    # admits in-place mutation after validate() has already approved the row.
    preference_tags: tuple[str, ...]

    def validate(self) -> None:
        for name, value in (
            ("purchase_frequency", self.purchase_frequency),
            ("rating_style", self.rating_style),
            ("summary", self.summary),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"profile {name} must be a non-empty string")
        rating = self.average_prior_rating
        if rating is not None:
            # bool is a subclass of int, so it must be excluded explicitly or
            # `True` would validate as a 1.0 star rating.
            if not isinstance(rating, (int, float)) or isinstance(rating, bool):
                raise ValueError("profile average_prior_rating must be numeric or null")
            if not 0.0 <= float(rating) <= 5.0:
                raise ValueError("profile average_prior_rating must be between 0 and 5")
        if not isinstance(self.preference_tags, tuple):
            raise ValueError("profile preference_tags must be a tuple")
        for tag in self.preference_tags:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError("profile preference_tags entries must be non-empty")

    def as_record(self) -> dict[str, object]:
        return {
            "average_prior_rating": self.average_prior_rating,
            # A list, not a tuple: `starter/agent.py:79-83` accepts a list or a
            # tuple in memory, but this record is serialized to JSON first, and
            # anything that is not a JSON array is silently dropped on the way in.
            "preference_tags": list(self.preference_tags),
            "purchase_frequency": self.purchase_frequency,
            "rating_style": self.rating_style,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class IntentCard:
    """The authored card the evaluator's branch-1 path hands to the simulator."""

    target_category: str
    hard_constraints: tuple[str, ...]
    soft_preferences: tuple[str, ...]

    def validate(self) -> None:
        if not isinstance(self.target_category, str) or not self.target_category.strip():
            raise ValueError("intent_card target_category must be a non-empty string")
        if len(self.target_category) > MAX_CONSTRAINT_LENGTH:
            raise ValueError(
                "intent_card target_category exceeds the evaluator's"
                f" {MAX_CONSTRAINT_LENGTH}-character clean limit"
            )
        for name, values in (
            ("hard_constraints", self.hard_constraints),
            ("soft_preferences", self.soft_preferences),
        ):
            if not isinstance(values, tuple) or not values:
                raise ValueError(f"intent_card {name} must be a non-empty tuple")
            for entry in values:
                if not isinstance(entry, str) or not entry.strip():
                    raise ValueError(f"intent_card {name} entries must be non-empty")
                if entry != entry.strip():
                    raise ValueError(
                        f"intent_card {name} entries must be stripped of"
                        " surrounding whitespace"
                    )
                if len(entry) > MAX_CONSTRAINT_LENGTH:
                    raise ValueError(
                        f"intent_card {name} entry exceeds the evaluator's"
                        f" {MAX_CONSTRAINT_LENGTH}-character clean limit: {entry!r}"
                    )
        combined = [*self.hard_constraints, *self.soft_preferences]
        if len(set(combined)) != len(combined):
            # `customer_reply` adds a disclosed constraint to one shared set
            # (local_evaluator.py:184), so a value repeated across the two lists is
            # disclosed once and is then undiscoverable through the other list.
            raise ValueError(
                "intent_card duplicate constraint across hard_constraints and"
                " soft_preferences"
            )

    def as_record(self) -> dict[str, object]:
        return {
            "hard_constraints": list(self.hard_constraints),
            "soft_preferences": list(self.soft_preferences),
            "target_category": self.target_category,
        }


@dataclass(frozen=True, slots=True)
class OverrideBehavior:
    """The four-key override block an `intent_override` row must carry."""

    turn: int
    old_value: str
    new_value: str
    message: str

    def validate(self) -> None:
        # bool is a subclass of int; `True` would otherwise pass as turn 1.
        if not isinstance(self.turn, int) or isinstance(self.turn, bool):
            raise ValueError("override turn must be an integer")
        if not MIN_OVERRIDE_TURN <= self.turn <= MAX_OVERRIDE_TURN:
            raise ValueError(
                "override turn must be between"
                f" {MIN_OVERRIDE_TURN} and {MAX_OVERRIDE_TURN}, got {self.turn}"
            )
        for name, value in (
            ("old_value", self.old_value),
            ("new_value", self.new_value),
            ("message", self.message),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"override {name} must be a non-empty string")
        # `initial_message` reads behavior["override"]["old_value"] without a
        # `.get` at local_evaluator.py:161, so an override row with a missing or
        # empty old_value crashes the harness mid-run rather than scoring badly.

    def as_record(self) -> dict[str, object]:
        return {
            "message": self.message,
            "new_value": self.new_value,
            "old_value": self.old_value,
            "turn": self.turn,
        }


@dataclass(frozen=True, slots=True)
class Behavior:
    """The authored behavior block, shaped exactly like `behavior_for`'s output."""

    scenario_type: str
    override: OverrideBehavior | None

    def validate(self) -> None:
        if self.scenario_type not in SCENARIO_TYPES:
            raise ValueError(
                f"behavior scenario_type must be one of {list(SCENARIO_TYPES)},"
                f" got {self.scenario_type!r}"
            )
        wants_override = self.scenario_type == "intent_override"
        if wants_override and self.override is None:
            raise ValueError("behavior missing override block for intent_override")
        if not wants_override and self.override is not None:
            raise ValueError(
                "behavior carries an override block for a"
                f" {self.scenario_type} scenario, which never fires"
            )
        if self.override is not None:
            self.override.validate()

    def as_record(self) -> dict[str, object]:
        # The `override` key is OMITTED entirely when None, because the
        # evaluator's own `behavior_for` returns a bare {"scenario_type": s} for
        # the other three scenarios (local_evaluator.py:74-87). Matching it
        # exactly is what makes the D-55 byte-identity assertion possible; an
        # explicit "override": null would be a different dict.
        record: dict[str, object] = {"scenario_type": self.scenario_type}
        if self.override is not None:
            record["override"] = self.override.as_record()
        return record


@dataclass(frozen=True, slots=True)
class SampleRow:
    """One corpus row: the six shipped keys plus the authored branch-1 fields."""

    sample_id: str
    scenario_type: str
    category_bucket: str
    difficulty_bucket: str
    ground_truth_parent_asin: str
    profile: SampleProfile
    intent_card: IntentCard
    behavior: Behavior
    pair_id: str
    arm: str

    def validate(self) -> None:
        if not isinstance(self.sample_id, str) or not self.sample_id:
            raise ValueError("sample_id must not be empty")
        if self.scenario_type not in SCENARIO_TYPES:
            raise ValueError(
                f"scenario_type must be one of {list(SCENARIO_TYPES)},"
                f" got {self.scenario_type!r}"
            )
        if not isinstance(self.category_bucket, str) or not self.category_bucket:
            raise ValueError("category_bucket must not be empty")
        expected_difficulty = dict(DIFFICULTY_BY_SCENARIO)[self.scenario_type]
        if self.difficulty_bucket != expected_difficulty:
            raise ValueError(
                f"difficulty_bucket for a {self.scenario_type} row must be"
                f" {expected_difficulty!r}, got {self.difficulty_bucket!r}"
            )
        if (
            not isinstance(self.ground_truth_parent_asin, str)
            or not self.ground_truth_parent_asin
        ):
            raise ValueError("ground_truth parent_asin must not be empty")
        if self.arm not in ARMS:
            raise ValueError(
                f"arm must be one of {list(ARMS)}, got {self.arm!r}"
            )
        if not isinstance(self.pair_id, str) or not PAIR_ID_RE.fullmatch(self.pair_id):
            raise ValueError(
                "pair_id must be {corpus_stem}_{index:04d}, e.g. probe_v1_0007;"
                f" got {self.pair_id!r}"
            )
        if self.sample_id != f"{self.pair_id}_{self.arm}":
            # The coupling is what makes `sample_id` uniqueness and `pair_id`
            # uniqueness the same property, and it is why `arena/arena.py:149`'s
            # sample_id join and `align_on_pair_id`'s pair_id join cannot
            # disagree about which rows belong together.
            raise ValueError(
                "sample_id must be f'{pair_id}_{arm}':"
                f" expected {self.pair_id}_{self.arm}, got {self.sample_id!r}"
            )
        if self.behavior.scenario_type != self.scenario_type:
            # `override_applied` at local_evaluator.py:234 reads the ORIGINAL
            # sample's scenario_type while `customer_reply` reads behavior's, so a
            # disagreement makes the two mechanisms disagree silently: the row
            # can be gated as an override while never being replied to as one.
            raise ValueError(
                "behavior scenario_type must equal the row's scenario_type:"
                f" row says {self.scenario_type!r},"
                f" behavior says {self.behavior.scenario_type!r}"
            )
        self.profile.validate()
        self.intent_card.validate()
        self.behavior.validate()
        if self.behavior.override is not None:
            declared = (
                *self.intent_card.hard_constraints,
                *self.intent_card.soft_preferences,
            )
            if self.behavior.override.new_value not in declared:
                # `new_value` is added to `disclosed` at local_evaluator.py:263, so
                # a value absent from the card makes the disclosure bookkeeping
                # diverge from the public path: the harness marks a constraint as
                # told to the agent that the card never contained.
                raise ValueError(
                    "override new_value must appear verbatim in the intent_card:"
                    f" {self.behavior.override.new_value!r} is in neither"
                    " hard_constraints nor soft_preferences"
                )

    def as_record(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "behavior": self.behavior.as_record(),
            "category_bucket": self.category_bucket,
            "difficulty_bucket": self.difficulty_bucket,
            "ground_truth": {"parent_asin": self.ground_truth_parent_asin},
            "intent_card": self.intent_card.as_record(),
            "pair_id": self.pair_id,
            "sample_id": self.sample_id,
            "scenario_type": self.scenario_type,
            "user_profile": self.profile.as_record(),
        }


def write_corpus(path: Path, rows: tuple[SampleRow, ...]) -> None:
    # Canonical form is not cosmetic: `sha256_file` over this file becomes the
    # corpus's frozen identity (D-43), so `sort_keys=True` and a single trailing
    # newline per row are what make two builds of one corpus byte-comparable.
    # Mirrors arena/store.py:63-71 exactly.
    path.write_text(
        "".join(
            json.dumps(row.as_record(), sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def load_corpus(path: Path) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        # json.loads only -- never pickle, eval or yaml (T-02-11), mirroring
        # arena/store.py:80-81. The line number travels with the error because a
        # 2,000-row corpus is not greppable by eye.
        try:
            record = json.loads(line)
            _require_mapping(record, "corpus row")
        except (KeyError, TypeError, ValueError) as error:
            raise CorpusSchemaError(
                f"invalid corpus row in {path} at line {number}: {error}"
            ) from error
        records.append(record)
    return tuple(records)


def row_from_record(record: dict) -> SampleRow:
    profile_record = _require_mapping(record["user_profile"], "user_profile")
    card_record = _require_mapping(record["intent_card"], "intent_card")
    behavior_record = _require_mapping(record["behavior"], "behavior")
    ground_truth = _require_mapping(record["ground_truth"], "ground_truth")
    override_record = behavior_record.get("override")
    override = None
    if override_record is not None:
        override_record = _require_mapping(override_record, "behavior override")
        override = OverrideBehavior(
            turn=override_record["turn"],
            old_value=str(override_record["old_value"]),
            new_value=str(override_record["new_value"]),
            message=str(override_record["message"]),
        )
    row = SampleRow(
        sample_id=str(record["sample_id"]),
        scenario_type=str(record["scenario_type"]),
        category_bucket=str(record["category_bucket"]),
        difficulty_bucket=str(record["difficulty_bucket"]),
        ground_truth_parent_asin=str(ground_truth["parent_asin"]),
        profile=SampleProfile(
            purchase_frequency=str(profile_record["purchase_frequency"]),
            average_prior_rating=profile_record.get("average_prior_rating"),
            rating_style=str(profile_record["rating_style"]),
            summary=str(profile_record["summary"]),
            preference_tags=_require_sequence(
                profile_record["preference_tags"], "preference_tags"
            ),
        ),
        intent_card=IntentCard(
            target_category=str(card_record["target_category"]),
            hard_constraints=_require_sequence(
                card_record["hard_constraints"], "hard_constraints"
            ),
            soft_preferences=_require_sequence(
                card_record["soft_preferences"], "soft_preferences"
            ),
        ),
        behavior=Behavior(
            scenario_type=str(behavior_record["scenario_type"]),
            override=override,
        ),
        pair_id=str(record["pair_id"]),
        arm=str(record["arm"]),
    )
    row.validate()
    return row


def corpus_stem(name: str) -> str:
    """The registry name with its dot replaced by an underscore (`probe.v1` -> `probe_v1`)."""

    # One function because three call sites need the derivation -- PAIR_ID_RE's
    # documented form, validate_corpus's refusal below, and the generator's
    # pair_id_for -- and three inline replace(".", "_") expressions are three
    # places to drift apart.
    if "." not in name:
        raise ValueError(
            f"corpus name must carry a version suffix, e.g. probe.v1; got {name!r}"
        )
    stem = name.replace(".", "_")
    if not _CORPUS_STEM_RE.fullmatch(stem):
        raise ValueError(
            "corpus stem must be lowercase letters, digits and underscores"
            f" starting with a letter; {name!r} yields {stem!r}"
        )
    return stem


def validate_corpus(records: tuple[dict, ...], *, corpus_name: str) -> None:
    # `corpus_name` is keyword-only with NO default so that no caller anywhere can
    # skip the stem check by omission -- an omitted argument is a TypeError, not a
    # silently unnamespaced corpus.
    expected_stem = corpus_stem(corpus_name)
    expected_prefix = f"{expected_stem}_"
    seen: dict[str, int] = {}
    for index, record in enumerate(records):
        try:
            row = row_from_record(record)
        except (KeyError, TypeError, ValueError) as error:
            raise CorpusSchemaError(
                f"invalid row at index {index} of corpus {corpus_name}: {error}"
            ) from error
        if not row.pair_id.startswith(expected_prefix):
            # The load-bearing half of D-45, and it belongs HERE, at the loader,
            # not only in the generator that mints ids. PAIR_ID_RE gives an id a
            # legal shape and says nothing about which corpus owns it, so a
            # probe.v1 file carrying `expanded_dev_v1_0007` passes every other
            # check in this module and then inner-joins against the real
            # expanded_dev.v1 corpus in align_on_pair_id -- precisely the silently
            # bogus contrast D-45 exists to prevent. Enforcing it here converts
            # "the generator is supposed to namespace" into "a mis-namespaced
            # corpus cannot load", which no future generator refactor can drop.
            raise CorpusSchemaError(
                f"pair_id {row.pair_id!r} does not belong to corpus"
                f" {corpus_name!r}: expected the stem {expected_stem!r}"
            )
        if row.sample_id in seen:
            # `arena/arena.py:149` reads sample["sample_id"] to build
            # _SampleMappingAgent's ordering tuple, so a duplicate id silently
            # mis-maps the session -> sample join and every downstream paired
            # statistic is then computed over the wrong pairing.
            raise CorpusSchemaError(
                f"duplicate sample_id {row.sample_id!r} at index {index}"
                f" of corpus {corpus_name} (first seen at index {seen[row.sample_id]})"
            )
        seen[row.sample_id] = index


def assert_authored_branch(record: dict) -> None:
    """Prove the evaluator took its authored branch for this row (D-37)."""

    # products={} is safe because branch 1 returns at local_evaluator.py:206
    # before touching the mapping at all -- which is exactly why the full
    # 3,500-row sweep needs neither the 61 MB catalog nor the 580 MB artifact.
    try:
        card, behavior = materialize_hidden_fields(record, {})
    except (KeyError, TypeError) as error:
        # Empty products, so any lookup failure IS the fallback branch running.
        raise CorpusSchemaError(
            f"row {record.get('sample_id')!r} took the fallback branch:"
            f" the evaluator regenerated its card from catalog text ({error!r})"
        ) from error
    # `is`, not `==`: identity is what proves branch 1 fired, because equality
    # would also pass if branch 2 happened to synthesize an equal card.
    if card is not record.get("intent_card") or behavior is not record.get("behavior"):
        raise CorpusSchemaError(
            f"row {record.get('sample_id')!r} did not take the authored branch:"
            " materialize_hidden_fields returned objects that are not the row's own"
        )


def scenario_mix(records: tuple[dict, ...]) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {name: 0 for name in SCENARIO_TYPES}
    for record in records:
        scenario = str(record["scenario_type"])
        counts[scenario] = counts.get(scenario, 0) + 1
    return tuple(sorted(counts.items()))


def distinct_targets(records: tuple[dict, ...]) -> tuple[str, ...]:
    return tuple(
        sorted({str(record["ground_truth"]["parent_asin"]) for record in records})
    )
