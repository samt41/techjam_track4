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

import random
from pathlib import Path

from arena.datasets.schema import (
    CATEGORY_BUCKET,
    DIFFICULTY_BY_SCENARIO,
    SCENARIO_MIX_TARGET,
    Behavior,
    IntentCard,
    OverrideBehavior,
    SampleProfile,
    SampleRow,
    load_corpus,
)
from arena.evaluator_bridge import intent_card
from arena.statistics import pair_seed


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
