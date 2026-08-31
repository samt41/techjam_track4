"""Sample targets, build both arms of a pair, and freeze a versioned corpus.

Nothing here runs on the agent's inference path. This module is a build-time
driver: it reads the catalog once, mints corpus-namespaced pair ids, embeds the
evaluator's own `intent_card` output as the control arm (D-31), pins the
`intent_override` turn from `pair_id` so both arms of a pair agree (D-36), drives
the authoring gates, and publishes the corpus plus its committed side artifacts.

Two asymmetries are deliberate and are the easiest things in the phase to
"correct" into a bug:

* The control arm is the evaluator's `intent_card(product)` verbatim. It is not
  re-cleaned, re-ordered or repaired. A target whose evaluator card cannot be
  expressed as a valid authored card is dropped from the candidate pool rather
  than patched, because a patched control stops being public-set phrasing and
  the whole control-vs-probe contrast stops meaning what it says.
* `measure_solvability` exists for the expanded corpora and REFUSES the probe.
  See its own body for why; the short version is that a retrieval-backed filter
  deletes exactly the sessions carrying the vocabulary gap (D-35, L-3).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from arena.datasets.authoring import (
    AUTHORING_ATTEMPT_CAP,
    AuthoringRequest,
    AuthoringRunner,
    ReviewPayload,
    attempt_until,
    load_prompt,
    log_record,
)
from arena.datasets.divergence import (
    DivergenceRecord,
    DivergenceReport,
    contradicts,
    measure,
    preserves_bucket,
    record_from_report,
)
from arena.datasets.gist import GistVocabulary, gist_for_target, prompt_payload_strings
from arena.datasets.schema import (
    CATEGORY_BUCKET,
    DIFFICULTY_BY_SCENARIO,
    MAX_CONSTRAINT_LENGTH,
    SCENARIO_MIX_TARGET,
    Behavior,
    IntentCard,
    OverrideBehavior,
    SampleProfile,
    SampleRow,
    load_corpus,
)
from arena.evaluator_bridge import classify_constraint, intent_card
from arena.statistics import pair_seed
from starter.shopping_agent.text_normalization import search_terms


# The `pair_seed` labels. Each derived quantity gets its own stream so that two
# unrelated draws over the same corpus cannot correlate: without the label a
# corpus of 300 pairs would seed target sampling and profile assignment from the
# same digest and the two would move together (D-24).
_SAMPLING_LABEL = "corpus-target-sampling"
_SCENARIO_LABEL = "corpus-scenario-assignment"
_PROFILE_LABEL = "corpus-user-profile"
_CROSS_CHECK_LABEL = "corpus-cross-check-subset"

# The evaluator's own fallback draws from exactly this pair at
# `local_evaluator.py:82`, so pinning the turn from `pair_id` keeps the generated
# corpus inside the same distribution the public set uses. Both values sit inside
# schema.MIN_OVERRIDE_TURN..MAX_OVERRIDE_TURN, so a pinned turn always fires.
_OVERRIDE_TURN_CHOICES = (3, 4)

_PUBLIC_SET_PATH = Path("data/public_set.jsonl")

# Measured over all 200 shipped `user_profile` blocks, not invented. Reproducing
# the shipped distribution matters because `starter/agent.py` reads the profile
# into its prior: a generated corpus whose profiles are shaped differently from
# the public set would move the agent's behaviour for a reason that has nothing
# to do with the vocabulary under test.
_PURCHASE_FREQUENCY = "3-4 prior purchases"

# `rating_style` and `average_prior_rating` are NOT independent in the shipped
# set -- the five combinations below are the only ones that occur, with these
# counts. Drawing the two fields separately would mint profiles the organizer's
# generator cannot produce (e.g. "critical" at 5.0).
_RATING_PROFILES = (
    ("critical", 1.0, 14),
    ("critical", 2.0, 9),
    ("critical", 3.0, 22),
    ("mixed", 4.0, 21),
    ("usually positive", 5.0, 134),
)

# Tag vocabulary and its measured document frequency across the 200 rows.
_PREFERENCE_TAGS = (
    ("comfort", 144),
    ("durability", 47),
    ("fit", 163),
    ("general shopping", 1),
    ("material", 154),
    ("performance", 26),
    ("style", 101),
    ("warmth", 18),
    ("weather", 12),
)

# Measured tag-count distribution: 6 rows carry one tag, 43 carry two, and so on.
_TAG_COUNTS = ((1, 6), (2, 43), (3, 30), (4, 121))

# Reproduced verbatim from the shipped rows: all 200 summaries match this
# template exactly, so a generated summary that departed from it would be the one
# field an inspecting reader could tell apart at a glance.
_SUMMARY_TEMPLATE = "Prior purchases emphasize {tags}; ratings are {style}."

# Four digits of zero padding bound the index, so an index that would need five
# is refused rather than silently widened.
_MAX_PAIR_INDEX = 9999

# The two card slots an authored constraint can occupy, and their one-character
# codes. The code keeps an item id short and, more importantly, keeps the
# `parent_asin` OUT of it: an item id is echoed back by the authoring model, so
# putting the target's catalog identifier there would hand the author the one
# thing D-32 withholds. An id is built from `pair_id`, which names a position in
# a corpus and nothing about the product.
_SLOTS = ("hard_constraints", "soft_preferences")
_SLOT_CODES = (("hard_constraints", "h"), ("soft_preferences", "s"))

# `classify_constraint` buckets that a gist attribute can name directly. Every
# other gist attribute -- including the D-52 abstract compounds such as
# `ground_contact` -- lands in the residual `feature` bucket, which is where the
# harness routes anything carrying none of its six keyword clauses.
_STRUCTURED_GIST_BUCKETS = ("color", "material", "size", "style")

_REVIEW_PROMPT_NAME = "review_faithfulness.md"

# The only verdict that admits a phrase. `drifted` and `wrong` are both
# rejections; they are distinguished in the reason string so a failing item's
# log says which way the phrase went.
_FAITHFUL_VERDICT = "faithful"

# Batch sizes. Authoring is 20 because a rejected batch is re-authored whole, and
# review is 40 because a review item is three short fields and its call is
# cheaper per item. Batching many REVIEW items into one call is a throughput
# choice and is fine; batching an author step and its own review into one call is
# not, and D-35 forbids it -- see `author_arm`.
_AUTHOR_BATCH_SIZE = 20
_REVIEW_BATCH_SIZE = 40

# Inline JSON, never a path: `build_argv` refuses a path because a Windows drive
# letter parses as a JSON identifier (authoring.py:262-266).
_AUTHOR_SCHEMA_JSON = json.dumps(
    {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "phrase": {"type": "string"},
            },
            "required": ["id", "phrase"],
            "additionalProperties": False,
        },
    },
    sort_keys=True,
    separators=(",", ":"),
)

_REVIEW_SCHEMA_JSON = json.dumps(
    {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "verdict": {"enum": ["drifted", "faithful", "wrong"]},
            },
            "required": ["id", "verdict"],
            "additionalProperties": False,
        },
    },
    sort_keys=True,
    separators=(",", ":"),
)

# A corpus whose name begins with this stem is a probe corpus, and the
# solvability check is refused for it. Matched on the name rather than on a flag
# a caller could forget to pass.
_PROBE_CORPUS_PREFIX = "probe"

# Bounds for the expanded-corpus solvability probe. The limit is 200 rather than
# the scored TOP_K of 10 because the question is "can retrieval reach this target
# at all", not "does it rank"; a target outside 200 exact-FTS hits is one no
# candidate is going to recover from wording alone.
_SOLVABILITY_LIMIT = 200
_SOLVABILITY_WORK_LIMIT = 1_000_000


class GenerateError(RuntimeError):
    """Raised when a corpus cannot be sampled, assembled, or published safely."""


def public_target_ids(path: Path = _PUBLIC_SET_PATH) -> frozenset[str]:
    """The 200 shipped targets every generated corpus must be disjoint from (D-27)."""

    try:
        records = load_corpus(Path(path))
    except OSError as error:
        raise GenerateError(f"cannot read the public set at {path}: {error}") from error
    try:
        return frozenset(
            str(record["ground_truth"]["parent_asin"]) for record in records
        )
    except (KeyError, TypeError) as error:
        raise GenerateError(
            f"public set at {path} carries a row without a ground_truth parent_asin:"
            f" {error}"
        ) from error


def _scenario_allocation(total: int) -> tuple[tuple[str, int], ...]:
    # Largest remainder over the official 40/40/15/5 shares. An equality check is
    # impossible at every corpus size -- 15% of 700 pairs is not a whole number --
    # so the allocation is exact by construction here and the registry's
    # `check_scenario_mix` tolerance absorbs nothing this function produces.
    raw = tuple((scenario, share * total) for scenario, share in SCENARIO_MIX_TARGET)
    allocated = {scenario: int(value) for scenario, value in raw}
    remainder = total - sum(allocated.values())
    order = sorted(raw, key=lambda item: (-(item[1] - int(item[1])), item[0]))
    for scenario, _ in order[:remainder]:
        allocated[scenario] += 1
    return tuple(sorted(allocated.items()))


def _proportional_allocation(
    sizes: tuple[tuple[str, int], ...], count: int
) -> tuple[tuple[str, int], ...]:
    # Largest remainder again, but capped by each stratum's own size and with the
    # leftover redistributed to strata that still have capacity. Without the cap a
    # thin stratum would be asked for more members than it holds and the draw
    # would raise from inside `random.sample` with no useful message.
    by_band = dict(sizes)
    total = sum(by_band.values())
    if total < count:
        raise GenerateError(
            f"cannot allocate {count} targets across strata holding {total} members"
        )
    raw = {band: size * count / total for band, size in sizes}
    quota = {band: min(int(value), by_band[band]) for band, value in raw.items()}
    order = sorted(raw, key=lambda band: (-(raw[band] - int(raw[band])), band))
    remaining = count - sum(quota.values())
    while remaining > 0:
        progressed = False
        for band in order:
            if remaining == 0:
                break
            if quota[band] < by_band[band]:
                quota[band] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            raise GenerateError(
                f"stratified allocation stalled with {remaining} targets unplaced"
            )
    return tuple(sorted(quota.items()))


def sample_targets(
    candidate_ids: tuple[str, ...],
    *,
    count: int,
    seed_label: str,
    excluded: frozenset[str],
    strata: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    """Draw `count` targets, content-seeded, stratified, and disjoint from `excluded`."""

    if count < 1:
        raise GenerateError(f"target count must be positive, got {count}")
    # Sorted before anything else: the draw must not depend on the order the
    # catalog happened to yield its products in, or two runs over the same
    # catalog written in a different order would sample different corpora.
    pool = tuple(sorted(set(candidate_ids) - set(excluded)))
    if len(pool) < count:
        raise GenerateError(
            f"cannot sample {count} targets: the pool holds {len(pool)} after"
            f" excluding {len(set(candidate_ids) & set(excluded))} of"
            f" {len(set(candidate_ids))} candidates. Returning fewer would give the"
            " corpus a session count its registry entry does not describe (D-27)"
        )
    band_by_id = dict(strata)
    grouped: dict[str, list[str]] = {}
    for identifier in pool:
        # An unstratified candidate is placed in its own band rather than dropped:
        # a missing price or category is a property of the catalog row, and
        # excluding those products would skew the corpus in exactly the direction
        # D-30's stratification exists to prevent.
        grouped.setdefault(band_by_id.get(identifier, ""), []).append(identifier)
    allocation = _proportional_allocation(
        tuple(sorted((band, len(members)) for band, members in grouped.items())),
        count,
    )
    rng = random.Random(pair_seed(seed_label, str(count), _SAMPLING_LABEL))
    drawn: list[str] = []
    for band, quota in allocation:
        drawn.extend(rng.sample(grouped[band], quota))
    return tuple(sorted(drawn))


def assign_scenarios(pair_ids: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Assign the official 40/40/15/5 mix across pairs, content-seeded (D-30)."""

    ordered = tuple(sorted(set(pair_ids)))
    if len(ordered) != len(pair_ids):
        raise GenerateError("scenario assignment requires unique pair ids")
    if not ordered:
        raise GenerateError("scenario assignment requires at least one pair")
    sequence: list[str] = []
    for scenario, quota in _scenario_allocation(len(ordered)):
        sequence.extend([scenario] * quota)
    rng = random.Random(
        pair_seed("\0".join(ordered), str(len(ordered)), _SCENARIO_LABEL)
    )
    rng.shuffle(sequence)
    return tuple(sorted(zip(ordered, sequence)))


def control_card(product: dict[str, object]) -> IntentCard:
    """The control arm: the evaluator's own `intent_card(product)`, verbatim (D-31)."""

    # Only the evaluator's own output IS public-set phrasing. Anything else -- a
    # re-clean, a re-order, a truncation, a "tidier" de-duplication -- is an
    # approximation carrying unmeasured bias, and it is what makes the
    # control-vs-probe contrast stop being exactly "public-set phrasing vs
    # customer phrasing". So the three keys are wrapped and nothing else happens.
    #
    # F-04: `target_category` is written by `intent_card` at local_evaluator.py:68
    # and read by nothing -- `initial_message` takes its category from
    # `coarse_category(categories[target])` at :235, never from the card. It is
    # populated for schema fidelity and gets no authoring or review budget.
    record = intent_card(product)
    card = IntentCard(
        target_category=str(record["target_category"]),
        hard_constraints=tuple(str(value) for value in record["hard_constraints"]),
        soft_preferences=tuple(str(value) for value in record["soft_preferences"]),
    )
    try:
        card.validate()
    except ValueError as error:
        # `intent_card` sets `soft_preferences = cleaned[2:4] or cleaned[:1]`, so a
        # product yielding fewer than three cleaned constraints repeats
        # hard_constraints[0] in soft_preferences -- which the authored-row schema
        # refuses, because `customer_reply` discloses a repeated value once and
        # leaves it undiscoverable through the other list. Such a target is
        # excluded from the candidate pool; the card is never repaired.
        raise GenerateError(
            "the evaluator's own intent_card for"
            f" {str(product.get('parent_asin', ''))!r} is not a valid authored card"
            f" ({error}); D-31 forbids repairing it, so the target is excluded"
        ) from error
    return card


def override_turn_for_pair(pair_id: str, scenario_type: str) -> int:
    """The D-36 pinned override turn: a pure function of the pair, not the arm."""

    # Control and probe necessarily carry different `sample_id`s, and the
    # evaluator's own fallback seeds from `sample_id` (local_evaluator.py:210-212).
    # An unpinned draw would therefore hand the two arms of one pair different
    # override turns -- a confound sitting inside the very scenario the probe is
    # most interested in, because the turn decides how much the agent has already
    # seen when the intent flips. Keying on `pair_id` makes both arms agree by
    # construction rather than by luck, and the seed takes no `sample_id` and no
    # `arm` so an arm-dependent draw is not expressible here.
    #
    # The string-seed shape is the evaluator's idiom verbatim rather than a
    # `pair_seed` digest, deliberately: fidelity to the harness's own draw is the
    # point, and a string seed cannot collide with the integer streams above.
    rng = random.Random(f"{pair_id}\0{scenario_type}")
    return rng.choice(_OVERRIDE_TURN_CHOICES)


def behavior_for_arm(
    card: IntentCard, *, scenario_type: str, pair_id: str
) -> Behavior:
    """Reproduce `behavior_for` for one arm, from that arm's OWN card (D-36)."""

    if scenario_type != "intent_override":
        # `Behavior.as_record()` emits a bare {"scenario_type": s} when override is
        # None, matching `behavior_for` at local_evaluator.py:74-87 byte for byte.
        return Behavior(scenario_type=scenario_type, override=None)
    # The same three derivations the harness uses at :79-86, computed from this
    # arm's own card: that vocabulary is exactly what is under test, so taking the
    # control's wording here would leak public-set phrasing into the probe arm.
    new_value = card.hard_constraints[0]
    return Behavior(
        scenario_type=scenario_type,
        override=OverrideBehavior(
            turn=override_turn_for_pair(pair_id, scenario_type),
            old_value=card.soft_preferences[-1],
            new_value=new_value,
            message=(
                "Actually, ignore my earlier preference."
                f" What I need is: {new_value}."
            ),
        ),
    )


def pair_id_for(index: int, *, corpus_stem: str) -> str:
    # The ONLY place this module mints a pair id, and the parameter deliberately
    # shadows the imported `schema.corpus_stem` helper -- callers derive the stem
    # with that helper and hand the result in, so the dot-to-underscore rule lives
    # in plan 02-03 and has exactly one implementation.
    #
    # D-45, stated in full because an inline f-string buried in `build_row` is
    # precisely how this guarantee gets lost: `paired_contrast.align_on_pair_id`
    # joins two arms on `pair_id`. If two corpora minted bare counters (0007)
    # their id sets would collide and that join would silently succeed on
    # unrelated rows -- the bogus contrast D-45 exists to prevent. Namespacing
    # every id with its corpus stem makes the intersection of two corpora's id
    # sets empty, so the join has nothing to match and raises instead.
    #
    # Four digits, zero-padded, so lexicographic order equals positional order at
    # 2,000 sessions. An index that would need five digits is refused rather than
    # silently widened, because widening breaks the ordering the padding is for.
    if not isinstance(index, int) or isinstance(index, bool):
        raise GenerateError(f"pair index must be an integer, got {index!r}")
    if index < 0 or index > _MAX_PAIR_INDEX:
        raise GenerateError(
            f"pair index must be between 0 and {_MAX_PAIR_INDEX}, got {index}"
        )
    if not corpus_stem:
        raise GenerateError("pair id requires a corpus stem")
    return f"{corpus_stem}_{index:04d}"


def profile_for_target(
    product: dict[str, object], *, pair_id: str
) -> SampleProfile:
    """A content-seeded profile drawn from the measured shipped distribution."""

    # Seeded from the pair, not the sample, so BOTH arms of a pair carry the same
    # profile. A profile that differed across arms would be a second thing varying
    # alongside the wording, and the measured delta would no longer be vocabulary.
    target = str(product.get("parent_asin", ""))
    rng = random.Random(pair_seed(target, pair_id, _PROFILE_LABEL))
    style, rating, _ = rng.choices(
        _RATING_PROFILES, weights=[weight for *_, weight in _RATING_PROFILES]
    )[0]
    size = rng.choices(
        [count for count, _ in _TAG_COUNTS],
        weights=[weight for _, weight in _TAG_COUNTS],
    )[0]
    remaining = list(_PREFERENCE_TAGS)
    tags: list[str] = []
    for _ in range(size):
        chosen = rng.choices(
            remaining, weights=[weight for _, weight in remaining]
        )[0]
        remaining.remove(chosen)
        tags.append(chosen[0])
    profile = SampleProfile(
        purchase_frequency=_PURCHASE_FREQUENCY,
        average_prior_rating=rating,
        rating_style=style,
        summary=_SUMMARY_TEMPLATE.format(tags=", ".join(tags), style=style),
        # A tuple here; `as_record()` serializes it as a JSON array, which
        # `starter/agent.py:79-83` requires -- a non-list is silently dropped.
        preference_tags=tuple(tags),
    )
    profile.validate()
    return profile


def build_row(
    *,
    pair_id: str,
    arm: str,
    scenario_type: str,
    target: str,
    card: IntentCard,
    profile: SampleProfile,
) -> SampleRow:
    """Assemble one corpus row and validate it before it is used for anything."""

    # The stem is NOT applied here. It already rides inside `pair_id`, which
    # `pair_id_for` minted, and plan 02-03's `SampleRow.validate()` makes
    # `sample_id == f"{pair_id}_{arm}"` a hard invariant. Prefixing the stem a
    # second time would both duplicate it and violate that invariant, raising
    # CorpusSchemaError on EVERY generated row -- a total failure, not a cosmetic
    # one, because no corpus could be built at all.
    sample_id = f"{pair_id}_{arm}"
    difficulty = dict(DIFFICULTY_BY_SCENARIO).get(scenario_type)
    if difficulty is None:
        raise GenerateError(f"unknown scenario type {scenario_type!r}")
    row = SampleRow(
        sample_id=sample_id,
        scenario_type=scenario_type,
        category_bucket=CATEGORY_BUCKET,
        difficulty_bucket=difficulty,
        ground_truth_parent_asin=target,
        profile=profile,
        intent_card=card,
        behavior=behavior_for_arm(
            card, scenario_type=scenario_type, pair_id=pair_id
        ),
        pair_id=pair_id,
        arm=arm,
    )
    # Validated BEFORE it is used to build anything, the ordering
    # arena/arena.py:110-113 documents. `SampleRow.__init__` does not validate.
    row.validate()
    return row


@dataclass(frozen=True, slots=True)
class PairTarget:
    """One pair: its id, its target, and the control card both arms are built on."""

    pair_id: str
    target: str
    scenario_type: str
    card: IntentCard


@dataclass(frozen=True, slots=True)
class ConstraintSlot:
    """One authorable position: which control constraint, and which gist pair."""

    pair_id: str
    target: str
    slot: str
    position: int
    control_phrase: str
    bucket: str
    gist_attribute: str
    gist_value: str
    gist_payload: str

    def item_id(self) -> str:
        return f"{self.pair_id}:{dict(_SLOT_CODES)[self.slot]}{self.position}"


@dataclass(frozen=True, slots=True)
class AuthoredConstraint:
    """An accepted phrase together with the measurement that accepted it."""

    # The DivergenceReport travels WITH the phrase rather than being recomputed
    # later. Roadmap SC3 asks for a measured overlap ratio reported for every
    # pair, and a ratio computed inside the gate loop and then dropped on the
    # floor is not reported -- it is merely checked. Retaining it here is what
    # lets `divergence_records` emit a committed per-pair log without measuring
    # anything a second time and possibly differently.
    slot: ConstraintSlot
    arm: str
    phrase: str
    report: DivergenceReport


@dataclass(frozen=True, slots=True)
class ArmAuthoring:
    """Everything one authored arm produced: its constraints and its call log."""

    constraints: tuple[AuthoredConstraint, ...]
    calls: tuple[dict[str, object], ...]


def _gist_bucket(attribute: str) -> str:
    return attribute if attribute in _STRUCTURED_GIST_BUCKETS else "feature"


def constraint_slots(
    pair: PairTarget,
    *,
    vocabulary: GistVocabulary,
    products: dict[str, dict[str, object]],
) -> tuple[ConstraintSlot, ...]:
    """Pair every control constraint with the gist pair its phrase must denote."""

    product = products.get(pair.target)
    if product is None:
        raise GenerateError(f"target {pair.target!r} is absent from the catalog")
    gist = gist_for_target(product, vocabulary)
    # `prompt_payload_strings` is the ONLY surface a gist reaches a prompt
    # through (MEAS-12). The payload string is captured here, at the one place
    # that calls it, so no later formatting step can quietly interpolate the
    # product instead.
    catalogue = list(zip(gist, prompt_payload_strings(gist)))
    if not catalogue:
        # An empty gist is the one unrecoverable case: there is nothing for the
        # author to write about, and nothing for the reviewer to check a phrase
        # against. Such a target is refused here and excluded from the pool.
        raise GenerateError(
            f"target {pair.target!r} has an empty attribute gist; there is"
            " nothing an author could be shown about it (D-32)"
        )
    available = list(catalogue)
    slots: list[ConstraintSlot] = []
    for name in _SLOTS:
        for position, phrase in enumerate(getattr(pair.card, name)):
            bucket = classify_constraint(phrase)
            # Preference order: an unspent pair in this constraint's own bucket,
            # then any unspent pair, then a spent pair back in the right bucket,
            # then any pair at all.
            #
            # Reuse is admitted deliberately rather than refused. A control card
            # carries up to four constraints while a thin product's gist may hold
            # two or three, so refusing reuse would drop every attribute-poor
            # target from the pool -- and attribute-poor products are not
            # randomly distributed, so the corpus would skew toward richly
            # described listings. That is precisely the silent skew D-30's
            # stratification exists to prevent, and it would be a far worse
            # defect than a card stating one attribute twice in two different
            # wordings. The two phrases are still forced apart by the
            # pair-uniqueness gate in `author_arm`.
            chosen = next(
                (
                    entry
                    for entry in available
                    if _gist_bucket(entry[0].attribute) == bucket
                ),
                None,
            )
            if chosen is None and available:
                chosen = available[0]
            if chosen is None:
                chosen = next(
                    (
                        entry
                        for entry in catalogue
                        if _gist_bucket(entry[0].attribute) == bucket
                    ),
                    catalogue[0],
                )
            if chosen in available:
                available.remove(chosen)
            gist_pair, payload = chosen
            slots.append(
                ConstraintSlot(
                    pair_id=pair.pair_id,
                    target=pair.target,
                    slot=name,
                    position=position,
                    control_phrase=phrase,
                    bucket=bucket,
                    gist_attribute=gist_pair.attribute,
                    gist_value=gist_pair.value,
                    gist_payload=payload,
                )
            )
    return tuple(slots)


def control_constraints(
    targets: tuple[PairTarget, ...],
    *,
    products: dict[str, dict[str, object]],
) -> tuple[AuthoredConstraint, ...]:
    """Measure the control arm too, so the contrast is quantified, not asserted."""

    # The control arm is not authored, but D-34 requires its overlap to be
    # MEASURED and reported anyway: its measured mean (~0.9857 on the 200 public
    # targets) is the number a probe ratio is read against, and a probe number
    # alone means nothing. Running the identical `measure` over both arms is also
    # what makes the two figures comparable rather than merely adjacent.
    measured: list[AuthoredConstraint] = []
    for pair in targets:
        product = products.get(pair.target)
        if product is None:
            raise GenerateError(f"target {pair.target!r} is absent from the catalog")
        for name in _SLOTS:
            for position, phrase in enumerate(getattr(pair.card, name)):
                measured.append(
                    AuthoredConstraint(
                        slot=ConstraintSlot(
                            pair_id=pair.pair_id,
                            target=pair.target,
                            slot=name,
                            position=position,
                            control_phrase=phrase,
                            bucket=classify_constraint(phrase),
                            gist_attribute="",
                            gist_value="",
                            gist_payload="",
                        ),
                        arm="control",
                        phrase=phrase,
                        report=measure(phrase, product),
                    )
                )
    return tuple(measured)


def author_arm(
    targets: tuple[PairTarget, ...],
    *,
    arm: str,
    runner: AuthoringRunner,
    vocabulary: GistVocabulary,
    products: dict[str, dict[str, object]],
    prompt_name: str,
    model_alias: str,
    batch_size: int = _AUTHOR_BATCH_SIZE,
    review_batch_size: int = _REVIEW_BATCH_SIZE,
) -> ArmAuthoring:
    """Author one arm's constraints, gated, bounded, and with every ratio kept."""

    slots: list[ConstraintSlot] = []
    for pair in targets:
        slots.extend(constraint_slots(pair, vocabulary=vocabulary, products=products))
    slot_by_id = {slot.item_id(): slot for slot in slots}
    item_ids = tuple(sorted(slot_by_id))
    if not item_ids:
        raise GenerateError("authoring requires at least one constraint slot")
    # The full admitted vocabulary, so the D-35 contradiction guard fires when a
    # phrase asserts ANY value the closed vocabulary knows and the target lacks --
    # not merely a value from its own attribute.
    admitted = frozenset(
        value for _, values in vocabulary.values for value in values
    )
    author_prompt = load_prompt(prompt_name)
    # load_prompt, never read_text: the committed prompt files carry maintainer
    # notes explaining the framing, and shipping those notes to the authoring
    # model tells it what the measurement is for. That is D-57 contamination, and
    # load_prompt strips them.
    review_prompt = load_prompt(_REVIEW_PROMPT_NAME)

    calls: list[dict[str, object]] = []
    reports: dict[str, DivergenceReport] = {}
    verdicts: dict[str, str] = {}
    local: dict[str, tuple[bool, str]] = {}
    accepted_by_pair: dict[str, set[str]] = {}

    def _call(request: AuthoringRequest) -> tuple[dict[str, object], ...]:
        request.validate()
        response = runner(request)
        calls.append(log_record(request, response))
        return response.item_records()

    def _local_gates(item_id: str, phrase: str, claimed: dict[tuple[str, str], str]) -> tuple[bool, str]:
        slot = slot_by_id[item_id]
        product = products[slot.target]
        if not phrase or phrase != phrase.strip():
            return False, "phrase is empty or carries surrounding whitespace"
        # 1. Length. Past this the harness silently truncates, and the committed
        #    corpus would then not describe what was actually scored.
        if len(phrase) > MAX_CONSTRAINT_LENGTH:
            return False, f"phrase is {len(phrase)} characters, over {MAX_CONSTRAINT_LENGTH}"
        # 2. D-33, the hard gate. A paraphrase that moves the bucket changes which
        #    asked attribute unlocks the constraint, so the arm-to-arm delta would
        #    mix disclosure mechanics with vocabulary and explain neither.
        if not preserves_bucket(slot.control_phrase, phrase):
            return False, (
                f"bucket moved from {slot.bucket!r} to"
                f" {classify_constraint(phrase)!r}"
            )
        # 3. D-34. Computed here and RETAINED: this is the report that ends up in
        #    the committed per-pair log.
        report = measure(phrase, product)
        reports[item_id] = report
        if not report.passes:
            return False, (
                f"lexical overlap {report.overlap_ratio:.4f} on"
                f" {list(report.overlapping_tokens)} and shared 2-grams"
                f" {list(report.shared_bigrams)}"
            )
        # 4. D-35's programmatic guard: the phrase must not assert admitted
        #    vocabulary the target does not carry.
        if contradicts(phrase, product, admitted) is not False:
            return False, "phrase asserts admitted vocabulary the target lacks"
        # 5. Uniqueness within the pair. Not in D-33/D-34, but a correctness
        #    requirement: `IntentCard.validate()` refuses a value repeated across
        #    hard_constraints and soft_preferences, because `customer_reply`
        #    discloses it once and leaves it undiscoverable through the other
        #    list. Without this gate such a pair fails at row assembly, after the
        #    tokens are already spent.
        if phrase in accepted_by_pair.get(slot.pair_id, set()):
            return False, "phrase duplicates one already accepted for this pair"
        key = (slot.pair_id, phrase)
        holder = claimed.get(key)
        if holder is not None and holder != item_id:
            return False, f"phrase duplicates the one produced for {holder}"
        claimed[key] = item_id
        return True, ""

    def _review(
        reviewable: tuple[str, ...], produced: dict[str, str], attempt_index: int
    ) -> None:
        # 6. The D-35 faithfulness review, in its OWN request with its own kind,
        #    its own prompt and -- through `claude_runner` -- its own process and
        #    fresh session. Batching many review items into one call is a
        #    throughput choice and is fine. Batching an author step and its own
        #    review into one call is not: the reviewer would then share context
        #    with the writer it is meant to be an independent check on.
        for start in range(0, len(reviewable), review_batch_size):
            batch = reviewable[start : start + review_batch_size]
            payload = []
            for item_id in batch:
                slot = slot_by_id[item_id]
                review = ReviewPayload(
                    gist_attribute=slot.gist_attribute,
                    gist_value=slot.gist_value,
                    phrase=produced[item_id],
                )
                review.validate()
                payload.append({"id": item_id, **review.as_record()})
            request = AuthoringRequest(
                kind="review",
                model_alias=model_alias,
                prompt_name=_REVIEW_PROMPT_NAME,
                # The attempt index rides in the review body for the same reason
                # it rides in the author body, and the case is easier to miss
                # here: a re-authored batch that comes back with the SAME phrases
                # would otherwise mint a byte-identical review request, and
                # `replay_runner` refuses a log that repeats a request digest
                # rather than coin-flipping between two records. The corpus would
                # then be unreplayable -- discovered only at regeneration time,
                # long after the calls were paid for.
                prompt=_request_body(review_prompt, payload, attempt=attempt_index),
                schema_json=_REVIEW_SCHEMA_JSON,
                item_ids=batch,
            )
            for record in _call(request):
                identifier = str(record.get("id", ""))
                if identifier in slot_by_id:
                    verdicts[identifier] = str(record.get("verdict", ""))

    def produce(pending: tuple[str, ...], attempt_index: int) -> dict[str, str]:
        produced: dict[str, str] = {}
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            payload = [
                {
                    "id": item_id,
                    "gist": slot_by_id[item_id].gist_payload,
                    "bucket": slot_by_id[item_id].bucket,
                }
                for item_id in batch
            ]
            request = AuthoringRequest(
                kind="author",
                model_alias=model_alias,
                prompt_name=prompt_name,
                # `attempt` is in the body on purpose: it is what makes each
                # re-authoring attempt carry a DIFFERENT request digest.
                # `replay_runner` refuses a log that repeats a digest rather than
                # coin-flipping between two records, so without this a second
                # attempt over the same batch could not be replayed at all.
                prompt=_request_body(author_prompt, payload, attempt=attempt_index),
                schema_json=_AUTHOR_SCHEMA_JSON,
                item_ids=batch,
            )
            for record in _call(request):
                identifier = str(record.get("id", ""))
                phrase = record.get("phrase")
                if identifier in batch and isinstance(phrase, str):
                    produced[identifier] = phrase.strip()
        local.clear()
        claimed: dict[tuple[str, str], str] = {}
        # Sorted, so which of two identical phrases wins the pair-uniqueness gate
        # is a stable property of the item ids and not of dict ordering.
        for item_id in sorted(produced):
            local[item_id] = _local_gates(item_id, produced[item_id], claimed)
        _review(
            tuple(item_id for item_id in sorted(produced) if local[item_id][0]),
            produced,
            attempt_index,
        )
        return produced

    def accept(item_id: str, phrase: str) -> tuple[bool, str]:
        passed, reason = local.get(item_id, (False, "no gate result recorded"))
        if not passed:
            return False, reason
        verdict = verdicts.get(item_id, "")
        if verdict != _FAITHFUL_VERDICT:
            return False, f"faithfulness review returned {verdict!r}"
        accepted_by_pair.setdefault(slot_by_id[item_id].pair_id, set()).add(phrase)
        return True, ""

    accepted = attempt_until(
        item_ids, produce, accept, cap=AUTHORING_ATTEMPT_CAP
    )
    constraints = tuple(
        AuthoredConstraint(
            slot=slot_by_id[item_id],
            arm=arm,
            phrase=phrase,
            report=reports[item_id],
        )
        for item_id, phrase in accepted
    )
    return ArmAuthoring(constraints=constraints, calls=tuple(calls))


def _request_body(
    prompt: str, payload: list[dict[str, object]], *, attempt: int | None = None
) -> str:
    body: dict[str, object] = {"items": payload}
    if attempt is not None:
        body["attempt"] = attempt
    return (
        prompt
        + "\n"
        + json.dumps(body, sort_keys=True, separators=(",", ":"))
        + "\n"
    )


def card_from_constraints(
    constraints: tuple[AuthoredConstraint, ...], *, target_category: str
) -> IntentCard:
    """Reassemble one arm's authored card from its accepted constraints."""

    slotted: dict[str, list[tuple[int, str]]] = {name: [] for name in _SLOTS}
    for constraint in constraints:
        slotted[constraint.slot.slot].append(
            (constraint.slot.position, constraint.phrase)
        )
    card = IntentCard(
        # F-04 again: `target_category` is inert, so the control's value is
        # carried across for schema fidelity. It is never sent to an authoring
        # model and never read by the harness, so it costs no authoring budget
        # and leaks nothing.
        target_category=target_category,
        hard_constraints=tuple(
            phrase for _, phrase in sorted(slotted["hard_constraints"])
        ),
        soft_preferences=tuple(
            phrase for _, phrase in sorted(slotted["soft_preferences"])
        ),
    )
    card.validate()
    return card


def divergence_records(
    accepted: tuple[AuthoredConstraint, ...],
    *,
    pair_id_by_target: dict[str, str],
) -> tuple[DivergenceRecord, ...]:
    """Turn every retained report into a committed per-pair record (Roadmap SC3)."""

    records: list[DivergenceRecord] = []
    for constraint in accepted:
        expected = pair_id_by_target.get(constraint.slot.target)
        if expected is None:
            raise GenerateError(
                f"target {constraint.slot.target!r} carries no pair id;"
                " the divergence log would name a pair the corpus does not hold"
            )
        if expected != constraint.slot.pair_id:
            # Not bookkeeping: `coverage()` keys the committed log on
            # (pair_id, arm, slot, position) and plan 02-11 asserts those keys
            # equal the corpus's own constraint count. A slot filed under the
            # wrong pair would satisfy that count while describing another
            # session's phrase.
            raise GenerateError(
                f"target {constraint.slot.target!r} is paired as {expected!r}"
                f" but its constraint is filed under {constraint.slot.pair_id!r}"
            )
        records.append(
            record_from_report(
                constraint.report,
                pair_id=constraint.slot.pair_id,
                arm=constraint.arm,
                position=constraint.slot.position,
                slot=constraint.slot.slot,
                phrase=constraint.phrase,
            )
        )
    return tuple(records)


def is_probe_corpus(corpus_name: str) -> bool:
    return corpus_name.split(".")[0].startswith(_PROBE_CORPUS_PREFIX)


def measure_solvability(
    rows: tuple[SampleRow, ...],
    *,
    corpus_name: str,
    artifact_path: Path,
    catalog_path: Path,
) -> dict[str, int]:
    """Report how many expanded-corpus targets exact FTS can reach. Never a filter."""

    if is_probe_corpus(corpus_name):
        # The refusal lives HERE as well as at the CLI, and the reason is in the
        # raised error rather than only in a comment, because
        # `.planning/research/ARCHITECTURE.md:258` recommends a solvability check
        # in general terms and a diligent reader will otherwise "fix" the probe
        # pipeline by calling this function directly, bypassing the CLI guard.
        #
        # The asymmetry is correct rather than inconsistent. For the expanded
        # corpora a session no candidate can win wastes evaluation budget and
        # depresses absolute scores for a reason unrelated to the candidate, so
        # reporting unreachable targets is a service. For the probe the SAME
        # filter is the exact mechanism that erases the finding: the sessions it
        # would delete are the ones whose customer wording no longer retrieves
        # the target, which is the vocabulary gap the probe exists to measure.
        raise GenerateError(
            "--solvability-check is forbidden for the probe corpus: a"
            " retrieval-backed filter would delete exactly the sessions that"
            " carry the vocabulary gap and launder the finding out of the"
            " measurement before it is measured (D-35)"
        )
    # Imported inside the function, never at module scope: this is the only code
    # path that may open the 580 MB artifact, and a module-level import would put
    # the SQLite backend into the import graph of every caller and every test.
    from starter.shopping_agent.local_search_backend import LocalProductSearchBackend
    from starter.shopping_agent.models import RetrievalRoute
    from starter.shopping_agent.search_backend import SearchRequest

    checked = 0
    reachable = 0
    backend = LocalProductSearchBackend.open(Path(catalog_path), Path(artifact_path))
    try:
        for row in rows:
            card = row.intent_card
            request = SearchRequest(
                route=RetrievalRoute.EXACT_FTS,
                lexical_terms=search_terms(
                    " ".join((*card.hard_constraints, *card.soft_preferences))
                ),
                filters=(),
                limit=_SOLVABILITY_LIMIT,
                work_limit=_SOLVABILITY_WORK_LIMIT,
            )
            request.validate()
            result = backend.search(request)
            checked += 1
            if any(
                hit.parent_asin == row.ground_truth_parent_asin
                for hit in result.hits
            ):
                reachable += 1
    finally:
        # Windows holds the 580 MB database open until the connection is closed.
        backend.close()
    # REPORTED, never applied. Dropping a row is the CLI's `--drop-unsolvable`
    # decision, made by an operator who typed it, not this function's.
    return {
        "checked": checked,
        "reachable": reachable,
        "unreachable": checked - reachable,
    }
