from __future__ import annotations

import json
from pathlib import Path

from arena.datasets.schema import (
    ARMS,
    DIFFICULTY_BY_SCENARIO,
    MAX_CONSTRAINT_LENGTH,
    SCENARIO_MIX_TARGET,
    Behavior,
    IntentCard,
    OverrideBehavior,
    SampleProfile,
    SampleRow,
)


# Derived from this file's location rather than the process working directory, so
# the fixtures resolve identically however unittest is invoked.
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

# Deliberately no catalog dependency anywhere in this module: no built artifact,
# no 61 MB product file, and none of the temporary 12-product builders the older
# agent tests use. The D-37 dynamic sweep runs branch 1, which returns before the
# evaluator ever indexes a product, so every corpus test in this phase can run on
# hand-written dicts alone.

# One string per reachable `classify_constraint` bucket, in the evaluator's own
# precedence order (local_evaluator.py:137-151). `budget` is absent on purpose:
# it was measured 0/798 over the public cards (L-7), so a control card cannot
# produce it and a fixture that did would test a path the corpus never takes.
_MATERIAL_CONSTRAINT = "soft cotton knit throughout"
_COLOR_CONSTRAINT = "color: black"
_SIZE_CONSTRAINT = "runs true to size on the shoulders"
_STYLE_CONSTRAINT = "relaxed fit with a crew neck"
_USE_CASE_CONSTRAINT = "warm enough for winter commutes"
_FEATURE_CONSTRAINT = "machine washable and quick drying"

_CONSTRAINT_POOL = (
    _MATERIAL_CONSTRAINT,
    _COLOR_CONSTRAINT,
    _SIZE_CONSTRAINT,
    _STYLE_CONSTRAINT,
    _USE_CASE_CONSTRAINT,
    _FEATURE_CONSTRAINT,
)

DEFAULT_HARD = (_MATERIAL_CONSTRAINT, _COLOR_CONSTRAINT)
DEFAULT_SOFT = (_STYLE_CONSTRAINT, _USE_CASE_CONSTRAINT)

# Customer-language rewordings of the pool above, each preserving the bucket its
# control counterpart classifies into, because `customer_reply` only discloses a
# constraint when the asked attribute matches its bucket (local_evaluator.py:180).
# A paraphrase that moved buckets would make the probe arm unanswerable for
# reasons that have nothing to do with vocabulary.
_PROBE_PHRASING = {
    _MATERIAL_CONSTRAINT: "cotton, nothing scratchy against the skin",
    _COLOR_CONSTRAINT: "ideally black so it goes with everything",
    _SIZE_CONSTRAINT: "I usually take my normal size in this sort of thing",
    _STYLE_CONSTRAINT: "not tight through the neck, easy to throw on",
    _USE_CASE_CONSTRAINT: "something I can wear outdoor in winter",
    _FEATURE_CONSTRAINT: "I do not want to hand wash it",
}

_DEFAULT_PROFILE = {
    "purchase_frequency": "3-4 prior purchases",
    "average_prior_rating": 5.0,
    "rating_style": "usually positive",
    "summary": "Prior purchases emphasize fit, comfort, durability;"
    " ratings are usually positive.",
    "preference_tags": ("fit", "comfort", "durability"),
}


def product(
    parent_asin: str,
    *,
    title: str,
    features: tuple[str, ...] = (),
    details: tuple[tuple[str, str], ...] = (),
    description: str = "",
    categories: tuple[str, ...] = ("Clothing, Shoes & Jewelry", "Women"),
    store: str = "",
    price: float | None = None,
) -> dict[str, object]:
    """A hand-written product carrying exactly the six evaluator search fields."""

    # The six fields are `SEARCH_FIELDS` at local_evaluator.py:22, and their
    # dict/list shapes are what `searchable_text` flattens at :31-34. Carrying all
    # six means a fixture product behaves under `searchable_text` and
    # `intent_card` exactly as a real record does, without opening anything.
    return {
        "categories": list(categories),
        "description": description,
        "details": dict(details),
        "features": list(features),
        # Not a search field: the identity the harness keys products by.
        "parent_asin": parent_asin,
        "price": price,
        "store": store,
        "title": title,
    }


def profile(**overrides: object) -> SampleProfile:
    values = {**_DEFAULT_PROFILE, **overrides}
    tags = values["preference_tags"]
    return SampleProfile(
        purchase_frequency=str(values["purchase_frequency"]),
        average_prior_rating=values["average_prior_rating"],
        rating_style=str(values["rating_style"]),
        summary=str(values["summary"]),
        preference_tags=tuple(str(tag) for tag in tags),
    )


def pair_id(index: int, *, corpus_stem: str = "probe_v1") -> str:
    """The one place fixtures mint a `PAIR_ID_RE`-valid id."""

    # Every helper below takes this function's output rather than formatting an id
    # itself, so a fixture cannot accidentally build a bare-counter pair id that
    # the real schema would reject -- and the `corpus_stem` argument is what lets a
    # test build a provably disjoint SECOND corpus (D-45).
    return f"{corpus_stem}_{index:04d}"


def sample_row(
    pair_id: str,
    *,
    arm: str = "control",
    scenario_type: str = "buying",
    parent_asin: str = "B000000001",
    hard: tuple[str, ...] = DEFAULT_HARD,
    soft: tuple[str, ...] = DEFAULT_SOFT,
    override_turn: int | None = None,
) -> SampleRow:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    is_override = scenario_type == "intent_override"
    if override_turn is not None and not is_override:
        raise ValueError(
            f"override_turn is meaningless on a {scenario_type} row; the trigger at"
            " local_evaluator.py:259 only runs while override_applied is False"
        )
    override = None
    if is_override:
        # Mirrors `behavior_for`'s own idiom at local_evaluator.py:76-86: the new
        # value is the first hard constraint and the old value the last soft one,
        # so the override references constraints the card actually declares.
        new_value = hard[0]
        override = OverrideBehavior(
            turn=3 if override_turn is None else override_turn,
            old_value=soft[-1],
            new_value=new_value,
            message=(
                "Actually, ignore my earlier preference."
                f" What I need is: {new_value}."
            ),
        )
    return SampleRow(
        sample_id=f"{pair_id}_{arm}",
        scenario_type=scenario_type,
        category_bucket="clothing",
        difficulty_bucket=dict(DIFFICULTY_BY_SCENARIO)[scenario_type],
        ground_truth_parent_asin=parent_asin,
        profile=profile(),
        intent_card=IntentCard(
            target_category="womens pullover",
            hard_constraints=tuple(hard),
            soft_preferences=tuple(soft),
        ),
        behavior=Behavior(scenario_type=scenario_type, override=override),
        pair_id=pair_id,
        arm=arm,
    )


def _probe_phrasing(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_PROBE_PHRASING.get(value, f"ideally {value}") for value in values)


def matched_pair(pair_id: str, **kwargs: object) -> tuple[SampleRow, SampleRow]:
    """A control row and a probe_sonnet row on the same target and the same pair."""

    hard = tuple(kwargs.pop("hard", DEFAULT_HARD))  # type: ignore[arg-type]
    soft = tuple(kwargs.pop("soft", DEFAULT_SOFT))  # type: ignore[arg-type]
    kwargs.pop("arm", None)
    control = sample_row(pair_id, arm="control", hard=hard, soft=soft, **kwargs)  # type: ignore[arg-type]
    probe = sample_row(
        pair_id,
        arm="probe_sonnet",
        hard=_probe_phrasing(hard),
        soft=_probe_phrasing(soft),
        **kwargs,  # type: ignore[arg-type]
    )
    # The pair-level override turn is identical across arms by construction (D-36):
    # both rows are built from the same `override_turn` keyword, so the two arms
    # cannot diverge on the turn the override fires and then be compared as if the
    # only difference between them were wording.
    return control, probe


def three_arm_pair(
    pair_id: str,
    **kwargs: object,
) -> tuple[SampleRow, SampleRow, SampleRow]:
    """A control row plus both probe arms, for the D-40 cross-model check."""

    hard = tuple(kwargs.pop("hard", DEFAULT_HARD))  # type: ignore[arg-type]
    soft = tuple(kwargs.pop("soft", DEFAULT_SOFT))  # type: ignore[arg-type]
    kwargs.pop("arm", None)
    control, sonnet = matched_pair(pair_id, hard=hard, soft=soft, **kwargs)
    haiku = sample_row(
        pair_id,
        arm="probe_haiku",
        hard=_probe_phrasing(hard),
        soft=_probe_phrasing(soft),
        **kwargs,  # type: ignore[arg-type]
    )
    return control, haiku, sonnet


def _scenario_counts(total: int) -> dict[str, int]:
    # Largest remainder, tie-broken on the scenario name, so one `total` always
    # yields one allocation and the fixture stays byte-stable across runs.
    ideal = {name: total * share for name, share in SCENARIO_MIX_TARGET}
    counts = {name: int(value) for name, value in ideal.items()}
    remainder = total - sum(counts.values())
    order = sorted(ideal, key=lambda name: (-(ideal[name] - counts[name]), name))
    for name in order[:remainder]:
        counts[name] += 1
    return counts


def _scenario_sequence(pair_count: int) -> tuple[str, ...]:
    # Interleaved rather than blocked: whichever scenario is furthest behind its
    # target rate takes the next slot. That keeps any prefix of the sequence
    # roughly proportional, which is what makes a strided sub-selection (the
    # cross-check pairs below) representative instead of all-of-one-scenario.
    counts = _scenario_counts(pair_count)
    shares = dict(SCENARIO_MIX_TARGET)
    remaining = dict(counts)
    sequence: list[str] = []
    for position in range(pair_count):
        best: tuple[tuple[float, str], str] | None = None
        for name in sorted(remaining):
            if remaining[name] <= 0:
                continue
            emitted = counts[name] - remaining[name]
            deficit = (position + 1) * shares[name] - emitted
            key = (-deficit, name)
            if best is None or key < best[0]:
                best = (key, name)
        if best is None:
            break
        sequence.append(best[1])
        remaining[best[1]] -= 1
    return tuple(sequence)


def synthetic_corpus(
    pair_count: int = 20,
    *,
    cross_check_count: int = 5,
    corpus_stem: str = "probe_v1",
) -> tuple[SampleRow, ...]:
    """A scenario-proportioned catalog-free corpus covering every reachable bucket."""

    if pair_count < len(_CONSTRAINT_POOL):
        raise ValueError(
            f"pair_count must be at least {len(_CONSTRAINT_POOL)} for the corpus to"
            " cover every reachable classify_constraint bucket"
        )
    if not 0 <= cross_check_count <= pair_count:
        raise ValueError(
            f"cross_check_count must be between 0 and {pair_count},"
            f" got {cross_check_count}"
        )
    sequence = _scenario_sequence(pair_count)
    # The third arm is allocated by the SAME largest-remainder rule as the corpus
    # itself, so adding cross-check rows cannot skew the 40/40/15/5 row mix.
    third_arm_budget = _scenario_counts(cross_check_count)
    rows: list[SampleRow] = []
    for index, scenario in enumerate(sequence):
        # Zero-padded to four digits so lexicographic order equals positional
        # order, exactly as tests/arena_fixtures.py:45-46 does with three.
        identifier = pair_id(index, corpus_stem=corpus_stem)
        hard = (
            _CONSTRAINT_POOL[index % len(_CONSTRAINT_POOL)],
            _CONSTRAINT_POOL[(index + 1) % len(_CONSTRAINT_POOL)],
        )
        soft = (
            _CONSTRAINT_POOL[(index + 2) % len(_CONSTRAINT_POOL)],
            _CONSTRAINT_POOL[(index + 3) % len(_CONSTRAINT_POOL)],
        )
        extra: dict[str, object] = {}
        if scenario == "intent_override":
            # Spread across the reachable window rather than pinned to one turn,
            # and derived from the PAIR index so both arms of a pair agree (D-36).
            extra["override_turn"] = 2 + (index % 3)
        arms = ["control", "probe_sonnet"]
        if third_arm_budget.get(scenario, 0) > 0:
            third_arm_budget[scenario] -= 1
            arms.append("probe_haiku")
        for arm in sorted(arms):
            probe = arm != "control"
            rows.append(
                sample_row(
                    identifier,
                    arm=arm,
                    scenario_type=scenario,
                    parent_asin=f"B{index:09d}",
                    hard=_probe_phrasing(hard) if probe else hard,
                    soft=_probe_phrasing(soft) if probe else soft,
                    **extra,  # type: ignore[arg-type]
                )
            )
    return tuple(rows)


_VIOLATION_KINDS = (
    "bare",
    "bare_pair_id",
    "duplicate_sample_id",
    "empty_hard",
    "foreign_stem",
    "long_constraint",
    "missing_override",
    "null_card",
    "override_turn_1",
    "override_turn_11",
    "sample_id_mismatch",
    "scenario_mismatch",
)


def violating_row(kind: str) -> dict[str, object]:
    """One record dict that deliberately breaks one invariant, selected by `kind`."""

    if kind not in _VIOLATION_KINDS:
        # Mirrors promote_hits_to_rank_one's refusal at arena_fixtures.py:80-83: a
        # typo'd kind must fail loudly, never silently return a valid row and turn
        # an assertRaises case into a vacuous pass.
        raise ValueError(
            f"unknown violating row kind: {kind!r};"
            f" expected one of {list(_VIOLATION_KINDS)}"
        )
    if kind in ("missing_override", "override_turn_1", "override_turn_11"):
        record = sample_row(
            pair_id(7), scenario_type="intent_override"
        ).as_record()
        behavior = dict(record["behavior"])  # type: ignore[arg-type]
        if kind == "missing_override":
            behavior.pop("override")
        else:
            override = dict(behavior["override"])  # type: ignore[arg-type]
            override["turn"] = 1 if kind == "override_turn_1" else 11
            behavior["override"] = override
        record["behavior"] = behavior
        return record
    record = sample_row(pair_id(7)).as_record()
    if kind == "duplicate_sample_id":
        # Intentionally VALID on its own: a duplicate is a corpus-level property,
        # so this record proves the refusal only when passed to validate_corpus
        # twice. Returning a per-row violation here would test the wrong check.
        return record
    if kind == "null_card":
        # Takes branch 1 at local_evaluator.py:205 -- membership is the whole
        # predicate -- and then crashes at :156 when the simulator reads it.
        record["intent_card"] = None
        return record
    if kind == "empty_hard":
        card = dict(record["intent_card"])  # type: ignore[arg-type]
        card["hard_constraints"] = []
        record["intent_card"] = card
        return record
    if kind == "long_constraint":
        card = dict(record["intent_card"])  # type: ignore[arg-type]
        card["hard_constraints"] = ["c" * (MAX_CONSTRAINT_LENGTH + 1)]
        record["intent_card"] = card
        return record
    if kind == "scenario_mismatch":
        behavior = dict(record["behavior"])  # type: ignore[arg-type]
        behavior["scenario_type"] = "browsing"
        record["behavior"] = behavior
        return record
    if kind == "bare_pair_id":
        # A bare counter: the cross-corpus collision hazard D-45 exists for.
        record["pair_id"] = "0007"
        record["sample_id"] = "0007_control"
        return record
    if kind == "foreign_stem":
        # PAIR_ID_RE-valid, sample_id correctly coupled, every per-row invariant
        # satisfied -- and destined for the probe.v1 corpus. Only
        # validate_corpus's corpus_name stem check can refuse this record, which
        # is what makes it the proof that the loader gate does work the regex
        # cannot: shape is a per-row property, ownership is not.
        record["pair_id"] = "expanded_dev_v1_0007"
        record["sample_id"] = "expanded_dev_v1_0007_control"
        return record
    if kind == "sample_id_mismatch":
        record["sample_id"] = "probe_v1_0007_probe_sonnet"
        return record
    # "bare": the six shipped keys only, with no authored fields at all. This is
    # the fallback-branch row the D-55 control-fidelity comparison is made
    # against, and the negative half of the dynamic D-37 check.
    return {
        key: value
        for key, value in record.items()
        if key
        in (
            "category_bucket",
            "difficulty_bucket",
            "ground_truth",
            "sample_id",
            "scenario_type",
            "user_profile",
        )
    }


def fake_authoring_response(
    items: tuple[dict, ...],
    *,
    model_resolved: str = "claude-haiku-4-5-20251001",
) -> dict[str, object]:
    """A recorded `claude -p` JSON envelope, shaped exactly as measured."""

    return {
        "duration_ms": 4321,
        "is_error": False,
        "modelUsage": {
            model_resolved: {
                "costUSD": 0.0123,
                "inputTokens": 1234,
                "outputTokens": 567,
                "webSearchRequests": 0,
            },
        },
        "num_turns": 1,
        # A JSON STRING, never a nested object: `result` stays a string even under
        # --json-schema (L-14), so every consumer must json.loads it. A fixture
        # that returned a parsed list here would let a missing loads() ship.
        "result": json.dumps(list(items)),
        "session_id": "00000000-0000-4000-8000-000000000000",
        "subtype": "success",
        "total_cost_usd": 0.0123,
        "usage": {
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "input_tokens": 1234,
            "output_tokens": 567,
        },
    }
