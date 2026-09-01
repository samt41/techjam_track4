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
  the whole control-vs-probe contrast stops meaning what it says. The one
  reduction D-31 does admit is `authorable_pair`'s, and it is admitted because
  refusing it would break the same contrast from the other side: a constraint
  whose bucket the target's gist cannot supply is removed from EVERY arm of the
  pair at once. Each retained string is still evaluator output verbatim, and both
  arms still disclose the same constraints in the same positions. Removing it from
  the probe arm alone would leave the control disclosing four constraints against
  the probe's three, and the measured delta would then be information content
  rather than vocabulary.
* `measure_solvability` exists for the expanded corpora and REFUSES the probe.
  See its own body for why; the short version is that a retrieval-backed filter
  deletes exactly the sessions carrying the vocabulary gap (D-35, L-3).

There is a THIRD reduction, and it happens after the gates rather than before
them. A constraint that spends `AUTHORING_ATTEMPT_CAP` attempts without clearing
D-33, D-34 and D-35 is DROPPED rather than taken as a reason to abandon the
corpus -- symmetrically, from every arm of its pair, and a pair that thereby loses
a whole constraint list is refused outright, because `IntentCard.validate()`
requires both lists to be non-empty and a half-formed pair is not a smaller pair.
That is admissible only because it is recorded completely: `arena/datasets/drops.py`
writes a committed ledger naming every dropped constraint with its attempt count
and verbatim final rejection reason, every refused pair with the list it lost, the
counts ride in the registry entry, and `check_recorded_counts` refuses an entry
whose numbers disagree with the rows and the ledger on disk. `--drop-log` names
the ledger; it defaults beside the corpus. What is NOT admissible is dropping an
item nobody authored -- see `author_arm` -- because that is an unanswered queue
rather than a measured outcome.

Two operator notes:

* L-11: the D-48 baseline runs that consume these corpora must type
  `--exploration disabled --lexical-mode auto` explicitly. `arena/run_arena.py`
  omits unset flags from the candidate fingerprint, so a flag-free invocation
  records `{}` while configuring a byte-identical agent -- two runs that differ
  only in what the operator typed then mint two different fingerprints for one
  configuration, and the leaderboard shows them as separate candidates.
* Smoke runs write to the repo-relative `.scratch/` root, never `$TMPDIR` or
  `/tmp`. This repository documents Windows 11 / PowerShell, where `$TMPDIR`
  expands to the empty string and the artifact lands on the drive root:

      uv run python -m arena.datasets.generate --corpus probe.v1 --pairs 4 \
          --response-log .scratch/probe-smoke.jsonl \
          --registry .scratch/datasets.json --corpus-root .scratch \
          --divergence-log .scratch/divergence.probe.v1.jsonl \
          --drop-log .scratch/drops.probe.v1.jsonl \
          --target-snapshot .scratch/targets.probe.v1.json \
          --markdown .scratch/datasets.md

* `--emit-pending` is the DETACHED authoring path, for a machine with no `claude`
  on PATH. It answers from `--replay` where it can and writes the requests it
  cannot answer to a queue file, exiting `PENDING_REQUESTS_EXIT_STATUS`. An
  operator has the queue answered elsewhere, appends the answers to the same log
  with `authoring.external_response_record` plus `authoring.append_response_log`,
  and runs the identical command again. Repeat until it exits 0, at which point
  the normal gated publish has already run. Nothing downstream is aware of the
  difference: the D-33 bucket gate, the D-34 divergence gate, the D-35
  faithfulness review, the D-45 publish validation and the D-50 replay
  reproducibility all execute exactly as they do on the subprocess path, because
  the substitution is only in who produces the text.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from arena.candidate import current_revision
from arena.datasets.authoring import (
    AUTHORING_ATTEMPT_CAP,
    NO_PHRASE_REASON,
    AuthoringError,
    AuthoringRequest,
    AuthoringRunner,
    PendingRequestCollector,
    ReviewPayload,
    attempt_outcome,
    claude_runner,
    collecting_runner,
    load_prompt,
    log_record,
    prompt_revision,
    replay_runner,
    resolved_model_ids,
    response_log_path,
    write_response_log,
)
from arena.datasets.divergence import (
    DivergenceRecord,
    DivergenceReport,
    bucket_summary,
    contradicts,
    divergence_log_path,
    measure,
    preserves_bucket,
    record_from_report,
    write_divergence_log,
)
from arena.datasets.drops import (
    DROP_LOG_SCHEMA_VERSION,
    DroppedConstraint,
    RefusedPair,
    drop_log_path,
    drop_summary,
    load_drop_log,
    write_drop_log,
)
from arena.datasets.gist import (
    GistPair,
    GistVocabulary,
    gist_for_target,
    load_vocabulary,
    prompt_payload_strings,
)
from arena.datasets.registry import (
    DATASETS_MARKDOWN_PATH,
    REGISTRY_PATH,
    CORPUS_ROOT,
    DatasetEntry,
    RegistryError,
    check_cross_check_subset,
    check_pairing,
    check_recorded_counts,
    check_scenario_mix,
    divergence_from_summary,
    load_registry,
    publish_corpus,
    render_markdown,
    resolve_entry_path,
    target_snapshot_path,
    upsert_entry,
    write_registry,
    write_target_snapshot,
)
from arena.datasets.schema import (
    CATEGORY_BUCKET,
    CORPUS_SCHEMA_VERSION,
    DIFFICULTY_BY_SCENARIO,
    MAX_CONSTRAINT_LENGTH,
    SCENARIO_MIX_TARGET,
    Behavior,
    CorpusSchemaError,
    IntentCard,
    OverrideBehavior,
    SampleProfile,
    SampleRow,
    assert_authored_branch,
    corpus_stem,
    distinct_targets,
    load_corpus,
    validate_corpus,
)
from arena.evaluator_bridge import catalog_index, classify_constraint, intent_card, searchable_text
from arena.statistics import pair_seed
from arena.store import sha256_file
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

# Price bands for the D-30 stratified draw. Round numbers rather than measured
# quantiles: the band only has to spread the draw across the price range so a
# corpus cannot skew cheap or dear, and quantiles computed from the catalog would
# make the strata depend on the catalog file, which is one more thing that has to
# hold still for a corpus to be reproducible.
_PRICE_BANDS = (("under_20", 20.0), ("under_50", 50.0), ("under_100", 100.0))

# The exit status `--emit-pending` uses when the round wrote work to the queue.
# Distinct from 1 on purpose: a driving script has to tell "answer these and run
# me again", which is the normal state of a converging detached run, apart from
# "this corpus cannot be built", which is not. Anything that treated both as
# failure would abandon the corpus after the first round.
PENDING_REQUESTS_EXIT_STATUS = 3


@dataclass(frozen=True, slots=True)
class CorpusPlan:
    """The shape D-25/D-28/D-49 fix for one corpus, in one place."""

    name: str
    paired: bool
    default_size: int
    default_cross_check: int
    model_alias: str
    prompt_name: str
    probe_arm: str
    size_flag: str


# D-25's own table is the authority for every number here: the probe is 300 pairs
# with a 100-pair cross-check arm (700 sessions, 300 targets), `expanded_dev` is
# 2,000 sessions over 2,000 targets, `expanded_confirm` 800 over 800.
#
# `paired` follows directly from that table and is worth stating, because it is
# the one place where a plausible reading goes wrong. The probe is 700 sessions
# on 300 targets, so it is paired: every target carries a control arm plus at
# least one authored arm. The expanded corpora are 2,000 sessions on 2,000
# targets -- one session per target -- so they are NOT paired, and
# `check_pairing` / `check_cross_check_subset` are skipped for them because both
# structurally require two or more arms under one pair id. They are still
# authored (D-49 sends the 2,800 bulk-paraphrase sessions to Haiku); their
# statistical use is candidate-vs-candidate joined on `sample_id`, which needs no
# second arm.
_CORPUS_PLANS = (
    CorpusPlan(
        name="probe.v1",
        paired=True,
        default_size=300,
        default_cross_check=100,
        model_alias="sonnet",
        prompt_name="author_probe.md",
        probe_arm="probe_sonnet",
        size_flag="pairs",
    ),
    CorpusPlan(
        name="expanded_dev.v1",
        paired=False,
        default_size=2_000,
        default_cross_check=0,
        model_alias="haiku",
        prompt_name="author_expanded.md",
        probe_arm="probe_haiku",
        size_flag="sessions",
    ),
    CorpusPlan(
        name="expanded_confirm.v1",
        paired=False,
        default_size=800,
        default_cross_check=0,
        model_alias="haiku",
        prompt_name="author_expanded.md",
        probe_arm="probe_haiku",
        size_flag="sessions",
    ),
)

# D-39/D-40: the cross-check arm is Haiku, a different scale and generation from
# the Sonnet primary, so the Sonnet-vs-Haiku delta on matched targets is
# generator affinity and nothing else.
_CROSS_CHECK_ALIAS = "haiku"
_CROSS_CHECK_ARM = "probe_haiku"


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
    """Everything one authored arm produced: what landed, what did not, and the calls."""

    constraints: tuple[AuthoredConstraint, ...]
    calls: tuple[dict[str, object], ...]
    # Returned rather than raised on, and returned as a RECORD rather than as a
    # count. The caller drops these constraints from every arm and writes them to
    # the committed ledger; a bare count would account for the shortfall while
    # discarding the reasons, which is the failure docs/STATUS.md names.
    dropped: tuple[DroppedConstraint, ...]


def _gist_bucket(attribute: str) -> str:
    return attribute if attribute in _STRUCTURED_GIST_BUCKETS else "feature"


def constraint_slots(
    pair: PairTarget,
    *,
    vocabulary: GistVocabulary,
    products: dict[str, dict[str, object]],
) -> tuple[ConstraintSlot, ...]:
    """Pair every AUTHORABLE control constraint with the gist pair it must denote."""

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
    # Grouped once, and every list below is read in `catalogue` order -- which
    # `gist_for_target` sorted on (attribute, value) -- so each choice is a stable
    # tie-break rather than an insertion-order accident. Grouping also makes the
    # supply question a lookup rather than a scan, which is what lets the
    # omission below be expressed as "this bucket has no supply" instead of as a
    # chain of fallbacks that quietly ends somewhere else.
    by_bucket: dict[str, list[tuple[GistPair, str]]] = {}
    for entry in catalogue:
        by_bucket.setdefault(_gist_bucket(entry[0].attribute), []).append(entry)
    available = list(catalogue)
    slots: list[ConstraintSlot] = []
    for name in _SLOTS:
        emitted = 0
        for phrase in getattr(pair.card, name):
            bucket = classify_constraint(phrase)
            supply = by_bucket.get(bucket)
            if supply is None:
                # NO SLOT IS EMITTED. This is the whole of the fix, and it is an
                # omission rather than a fallback because the gates downstream
                # want two things at once that no phrase can satisfy at the same
                # time. D-33 `preserves_bucket` requires the authored phrase to
                # classify back into `bucket`; D-35 faithfulness requires it to
                # mean the gist pair it was shown, and the committed author
                # prompt forbids inventing an attribute the pair does not state.
                # When the target's gist holds nothing in `bucket` at all, a
                # `color` slot can only be shown something like
                # `entry_method=toothed_fastener`: naming a colour fails
                # faithfulness, not naming one fails the bucket gate, and the
                # item burns every one of AUTHORING_ATTEMPT_CAP attempts and
                # takes the whole corpus run down with it. Measured on the 300-
                # pair probe, 141 of 1,197 constraints were in exactly that
                # flatly-unsatisfiable position.
                #
                # Emitting nothing is what `authorable_pair` then removes from
                # every arm at once, so the constraint is absent symmetrically
                # rather than only from the arm that could not author it.
                continue
            # Preference order, now only two branches because a third could not
            # run: an unspent pair in this constraint's own bucket, then a SPENT
            # pair back in the right bucket. `supply` is non-empty by
            # construction, so `supply[0]` always answers and there is no
            # cross-bucket branch left to reach -- which is the point. The old
            # third and fourth branches existed solely for the buckets the gist
            # cannot reach (`classify_constraint` can return `use_case` and
            # `budget`; gist.py's `_GIST_ATTRIBUTES` maps to neither), and those
            # are precisely the constraints now omitted.
            #
            # Reuse is admitted deliberately rather than refused. A control card
            # carries up to four constraints while a thin product's gist may hold
            # two or three, so refusing reuse would drop every attribute-poor
            # target from the pool -- and attribute-poor products are not
            # randomly distributed, so the corpus would skew toward richly
            # described listings. That is precisely the silent skew D-30's
            # stratification exists to prevent, and it is a far worse defect than
            # a card stating one attribute twice in two different wordings. The
            # two phrases are still forced apart by the pair-uniqueness gate in
            # `author_arm`.
            chosen = next(
                (entry for entry in supply if entry in available), supply[0]
            )
            if chosen in available:
                available.remove(chosen)
            gist_pair, payload = chosen
            slots.append(
                ConstraintSlot(
                    pair_id=pair.pair_id,
                    target=pair.target,
                    slot=name,
                    position=emitted,
                    control_phrase=phrase,
                    bucket=bucket,
                    gist_attribute=gist_pair.attribute,
                    gist_value=gist_pair.value,
                    gist_payload=payload,
                )
            )
            # Numbered by EMISSION, not by the constraint's index in the control
            # card, so positions stay contiguous through an omission. That is
            # what keeps `control_constraints`' own `enumerate` over the reduced
            # card in step with these ids: the committed divergence log keys on
            # (pair_id, arm, slot, position), and a gap on one arm only would
            # file two arms of one pair under different keys.
            emitted += 1
        if emitted == 0:
            # REFUSED, not emitted short. `IntentCard.validate()` requires both
            # lists to be non-empty, so a card that lost a whole list is not a
            # smaller card -- it is not a card. Raising here rather than
            # resampling later is what keeps the draw reproducible: `_run`
            # filters the candidate pool with this same call BEFORE
            # `sample_targets` runs, so the pool is fully determined before any
            # random number is drawn. Topping up after the draw would make the
            # corpus depend on which targets happened to fail.
            wanted = sorted(
                {classify_constraint(value) for value in getattr(pair.card, name)}
            )
            raise GenerateError(
                f"target {pair.target!r} would lose every {name} constraint:"
                f" they need a gist pair in {wanted} and its gist reaches only"
                f" {sorted(by_bucket)}. A card with an empty {name} list is not a"
                " card, so the target is excluded from the pool"
            )
    return tuple(slots)


def authorable_pair(
    pair: PairTarget,
    *,
    vocabulary: GistVocabulary,
    products: dict[str, dict[str, object]],
) -> PairTarget:
    """Reduce a pair's card to the constraints EVERY arm of it can carry."""

    # The reduction is applied to the PAIR, once, before any arm is built, which
    # is the only way both arms provably carry the same constraints: the control
    # row takes its card from here, `control_constraints` enumerates the same
    # card, and every authored arm re-derives its slots from it. Reducing inside
    # `author_arm` instead would shorten the authored arms and leave the control
    # disclosing constraints the probe never states -- an information asymmetry
    # dressed as a wording contrast.
    #
    # Idempotent by construction, and that is load-bearing rather than tidy:
    # `author_arm` calls `constraint_slots` again on the card this returns, and a
    # second reduction that removed anything further would renumber the positions
    # out from under the divergence log. It cannot, because a constraint is
    # dropped on a property of the TARGET's gist, which this function does not
    # touch.
    slots = constraint_slots(pair, vocabulary=vocabulary, products=products)
    card = IntentCard(
        target_category=pair.card.target_category,
        hard_constraints=tuple(
            slot.control_phrase for slot in slots if slot.slot == "hard_constraints"
        ),
        soft_preferences=tuple(
            slot.control_phrase for slot in slots if slot.slot == "soft_preferences"
        ),
    )
    # Validated before it is used to build anything. Every retained string came
    # verbatim from a card that already validated and a subset cannot introduce a
    # duplicate, so this is an assertion on the reduction rather than a filter --
    # a failure here means the reduction itself is wrong and must stop the run.
    card.validate()
    return PairTarget(
        pair_id=pair.pair_id,
        target=pair.target,
        scenario_type=pair.scenario_type,
        card=card,
    )


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

    outcome = attempt_outcome(
        item_ids, produce, accept, cap=AUTHORING_ATTEMPT_CAP
    )
    # An item nobody wrote a phrase for is not a constraint the gates rejected,
    # and it must not be dropped as though it were. On the detached path it is a
    # queued request waiting to be answered, and a run that dropped it would
    # publish a corpus that is short by however much of the queue was outstanding
    # -- silently, since every other signal says the round succeeded. The
    # collector normally stops such a run when the next attempt's items overlap
    # the queue, but a request first queued on the FINAL attempt has no next
    # attempt to be stopped by, and this is the refusal that covers it.
    unanswered = tuple(
        item for item in outcome.exhausted if item.reason == NO_PHRASE_REASON
    )
    if unanswered:
        raise AuthoringError(
            f"{len(unanswered)} item(s) in the {arm!r} arm were never authored:"
            f" {[item.item_id for item in unanswered]}. Nothing judged them, so"
            " there is no rejection to record and they are not droppable"
        )
    constraints = tuple(
        AuthoredConstraint(
            slot=slot_by_id[item_id],
            arm=arm,
            phrase=phrase,
            report=reports[item_id],
        )
        for item_id, phrase in outcome.accepted
    )
    dropped = tuple(
        DroppedConstraint(
            schema_version=DROP_LOG_SCHEMA_VERSION,
            item_id=item.item_id,
            pair_id=slot_by_id[item.item_id].pair_id,
            arm=arm,
            target=slot_by_id[item.item_id].target,
            slot=slot_by_id[item.item_id].slot,
            position=slot_by_id[item.item_id].position,
            bucket=slot_by_id[item.item_id].bucket,
            gist_attribute=slot_by_id[item.item_id].gist_attribute,
            gist_value=slot_by_id[item.item_id].gist_value,
            attempts=item.attempts,
            # VERBATIM, never a category. "lexical overlap 0.1250 on ['made'] and
            # shared 2-grams ['it s']" is what lets a later reader re-derive the
            # decision; "divergence" is a summary somebody has already
            # interpreted, and the interpretation is the part worth checking.
            reason=item.reason,
        )
        for item in outcome.exhausted
    )
    return ArmAuthoring(
        constraints=constraints, calls=tuple(calls), dropped=dropped
    )


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


def slot_item_ids(pair: PairTarget, slot: str) -> tuple[str, ...]:
    """The item ids one pair's card occupies in one slot, in card order."""

    # Derived from the CARD rather than re-derived from the gist, so it needs no
    # vocabulary and no catalog: `constraint_slots` numbers by emission over the
    # reduced card, so position i in the card is item id i in the slot. This is
    # the one identity the whole symmetric drop rests on, which is why it is a
    # named function rather than an f-string at three call sites.
    code = dict(_SLOT_CODES)[slot]
    return tuple(
        f"{pair.pair_id}:{code}{position}"
        for position in range(len(getattr(pair.card, slot)))
    )


def refused_pairs(
    pairs: tuple[PairTarget, ...],
    *,
    dropped_item_ids: frozenset[str],
    arms_by_pair: dict[str, tuple[str, ...]],
) -> tuple[RefusedPair, ...]:
    """Refuse every pair that lost a WHOLE constraint list to the drops.

    `IntentCard.validate()` requires a non-empty hard list and a non-empty soft
    list, so a pair that lost either is not a smaller pair -- it is not a card.
    Emitting it half-formed is not available; the choice is between refusing the
    pair and refusing the corpus, and refusing the pair is what the recorded
    shortfall then has to explain.

    The refusal is a property of the PAIR, not of an arm, because the drop is
    symmetric: the same item ids are removed from control, `probe_sonnet` and
    `probe_haiku` alike, so all three lose the same list at the same moment. That
    is exactly what keeps the arms matched on constraint ids, which is the
    property the entire paired contrast rests on.
    """
    refused: list[RefusedPair] = []
    for pair in pairs:
        missing: list[str] = []
        lost: list[str] = []
        for name in _SLOTS:
            identifiers = slot_item_ids(pair, name)
            gone = tuple(
                identifier
                for identifier in identifiers
                if identifier in dropped_item_ids
            )
            lost.extend(gone)
            if identifiers and len(gone) == len(identifiers):
                missing.append(name)
        if not missing:
            continue
        record = RefusedPair(
            schema_version=DROP_LOG_SCHEMA_VERSION,
            pair_id=pair.pair_id,
            target=pair.target,
            arms=arms_by_pair.get(pair.pair_id, ()),
            missing_slots=tuple(sorted(missing)),
            dropped_item_ids=tuple(sorted(set(lost))),
        )
        record.validate()
        refused.append(record)
    return tuple(refused)


def surviving_positions(
    pairs: tuple[PairTarget, ...], *, dropped_item_ids: frozenset[str]
) -> dict[tuple[str, str], dict[int, int]]:
    """Map each surviving `(pair, slot)` position to its post-drop position.

    Positions are RENUMBERED contiguously rather than left with a gap, for the
    same reason `constraint_slots` numbers by emission: the committed divergence
    log keys on `(pair_id, arm, slot, position)`, and the corpus-wide sweep reads
    control position i against probe position i. One map is built here and applied
    to every arm, so the arms cannot be renumbered differently -- alignment is
    structural rather than a coincidence of two loops agreeing.
    """
    mapping: dict[tuple[str, str], dict[int, int]] = {}
    for pair in pairs:
        for name in _SLOTS:
            kept = [
                position
                for position, identifier in enumerate(slot_item_ids(pair, name))
                if identifier not in dropped_item_ids
            ]
            mapping[(pair.pair_id, name)] = {
                old: new for new, old in enumerate(kept)
            }
    return mapping


def apply_drops(
    constraints: tuple[AuthoredConstraint, ...],
    *,
    dropped_item_ids: frozenset[str],
    refused_pair_ids: frozenset[str],
    positions: dict[tuple[str, str], dict[int, int]],
) -> tuple[AuthoredConstraint, ...]:
    """Remove the dropped constraints and the refused pairs, then renumber.

    Applied to the control arm with the same arguments as to every authored arm.
    Running one function over all of them is what makes the symmetry a property of
    the code rather than of three call sites that currently agree.
    """
    kept: list[AuthoredConstraint] = []
    for constraint in constraints:
        slot = constraint.slot
        if slot.pair_id in refused_pair_ids:
            continue
        if slot.item_id() in dropped_item_ids:
            continue
        renumbered = positions.get((slot.pair_id, slot.slot), {})
        if slot.position not in renumbered:
            raise GenerateError(
                f"constraint {slot.item_id()!r} survived the drop but has no"
                " renumbered position; the arms would disagree about which"
                " constraint sits where"
            )
        kept.append(
            replace(
                constraint,
                slot=replace(slot, position=renumbered[slot.position]),
            )
        )
    return tuple(kept)


def assert_arms_match_on_constraint_ids(
    constraints: tuple[AuthoredConstraint, ...],
) -> None:
    """Every arm of a pair must carry the identical `(slot, position)` set.

    Asserted rather than assumed, and asserted AFTER the drop, because the drop is
    the only step that could break it. `paired_contrast` joins the arms on
    `pair_id` and the sweep reads control position i against probe position i, so
    two arms disagreeing here would produce a contrast between constraints that
    are not counterparts -- a comparison that still computes and no longer means
    anything.

    The cross-check arm covers a SUBSET of pairs (D-40), so the check is per pair
    across the arms that pair actually carries, never a corpus-wide arm equality.
    """
    by_pair: dict[str, dict[str, set[tuple[str, int]]]] = {}
    for constraint in constraints:
        by_pair.setdefault(constraint.slot.pair_id, {}).setdefault(
            constraint.arm, set()
        ).add((constraint.slot.slot, constraint.slot.position))
    for pair_id in sorted(by_pair):
        arms = by_pair[pair_id]
        reference = arms[sorted(arms)[0]]
        for arm in sorted(arms):
            if arms[arm] != reference:
                raise GenerateError(
                    f"pair {pair_id} is not matched on constraint ids after the"
                    f" drop: arm {arm!r} carries {sorted(arms[arm])} against"
                    f" {sorted(reference)}"
                )


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
    observe: Callable[[SampleRow, bool], None] | None = None,
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
            hit = any(
                candidate.parent_asin == row.ground_truth_parent_asin
                for candidate in result.hits
            )
            if hit:
                reachable += 1
            # The per-row verdict is handed to the caller rather than acted on
            # here, so `--drop-unsolvable` stays a decision an operator typed and
            # this function stays a measurement. The counts below are the whole
            # of its own return.
            if observe is not None:
                observe(row, hit)
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


def corpus_plan(name: str) -> CorpusPlan:
    plan = next((entry for entry in _CORPUS_PLANS if entry.name == name), None)
    if plan is None:
        raise GenerateError(
            f"unknown corpus {name!r}; expected one of"
            f" {[entry.name for entry in _CORPUS_PLANS]}"
        )
    return plan


def stratum_for(product: dict[str, object], categories: list[str]) -> str:
    """The `{department}|{price band}` stratum one target is drawn within (D-30)."""

    values = [str(value).strip() for value in (categories or []) if str(value).strip()]
    # The SECOND category value, not the first and not the last: the first is the
    # store-wide "Clothing, Shoes & Jewelry" on essentially every product and
    # stratifies nothing, while the last is a leaf so specific that the strata
    # outnumber the targets and the allocation degenerates to an unstratified
    # draw. The second is the department, which is the level that actually
    # partitions the catalog.
    department = values[1] if len(values) > 1 else (values[0] if values else "unknown")
    price = product.get("price")
    try:
        value = float(price)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"{department.lower()}|unknown"
    for label, ceiling in _PRICE_BANDS:
        if value < ceiling:
            return f"{department.lower()}|{label}"
    return f"{department.lower()}|over_100"


def cross_check_pairs(
    scenario_by_pair: tuple[tuple[str, str], ...], *, count: int
) -> tuple[str, ...]:
    """Pick the D-40 three-arm subset, stratified so the scenario mix is preserved."""

    if count <= 0:
        return ()
    grouped: dict[str, list[str]] = {}
    for pair_id, scenario in scenario_by_pair:
        grouped.setdefault(scenario, []).append(pair_id)
    if sum(len(members) for members in grouped.values()) < count:
        raise GenerateError(
            f"cannot draw {count} cross-check pairs from"
            f" {sum(len(members) for members in grouped.values())} pairs"
        )
    # Drawn proportionally per scenario rather than as a flat sample: the
    # cross-check pairs carry a third row each, so a subset skewed toward one
    # scenario would move the whole corpus's mix off 40/40/15/5 and
    # `check_scenario_mix` would refuse a corpus whose PAIRS were correctly
    # allocated.
    allocation = _proportional_allocation(
        tuple(sorted((scenario, len(members)) for scenario, members in grouped.items())),
        count,
    )
    rng = random.Random(
        pair_seed(
            "\0".join(pair_id for pair_id, _ in sorted(scenario_by_pair)),
            str(count),
            _CROSS_CHECK_LABEL,
        )
    )
    drawn: list[str] = []
    for scenario, quota in allocation:
        drawn.extend(rng.sample(sorted(grouped[scenario]), quota))
    return tuple(sorted(drawn))


def _frozen_targets(registry_path: Path, *, exclude: str, root: Path) -> frozenset[str]:
    """Every target already spent by another registered corpus (D-27)."""

    if not Path(registry_path).is_file():
        return frozenset()
    spent: set[str] = set()
    for entry in load_registry(Path(registry_path)):
        if entry.name == exclude:
            continue
        path = resolve_entry_path(entry, root=root)
        if not path.is_file():
            # A registered corpus that is not on disk cannot be proven disjoint
            # from the one being built, and D-27 makes disjointness a property
            # enforced by construction rather than assumed. Refuse rather than
            # quietly sample a target another corpus may already hold.
            raise GenerateError(
                f"corpus {entry.name!r} is registered at {path} but the file is"
                " missing, so target disjointness cannot be established (D-27)"
            )
        for record in load_corpus(path):
            spent.add(str(record["ground_truth"]["parent_asin"]))
    return frozenset(spent)


def _claude_cli_version() -> str:
    try:
        completed = subprocess.run(
            ("claude", "--version"),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        # Recorded as unavailable rather than as an empty string: an empty
        # provenance field is indistinguishable from one nobody filled in.
        return "unavailable"
    return completed.stdout.strip() or "unavailable"


def _resolved_for_alias(
    calls: tuple[dict[str, object], ...], alias: str
) -> str:
    """Pitfall 7 / MEAS-13, scoped to one arm rather than to the whole corpus."""

    # The check is per ARM, not per corpus, because the probe corpus deliberately
    # spends TWO aliases: Sonnet authors the primary arm and Haiku the D-40
    # cross-check. A corpus-wide single-id assertion would refuse that by design.
    # What T-02-28 actually forbids is one arm silently changing generator
    # mid-run, and that is exactly what this refuses.
    identifiers = resolved_model_ids(
        tuple(record for record in calls if record.get("model_alias") == alias)
    )
    if len(identifiers) != 1:
        raise GenerateError(
            f"expected exactly one resolved model id for the {alias!r} arm,"
            f" got {list(identifiers)}; a corpus whose arm changed generator"
            " mid-run has a confounded generator-affinity finding (MEAS-13)"
        )
    return identifiers[0]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arena.datasets.generate",
        description="Generate and freeze a versioned paraphrase-probe or expanded corpus.",
    )
    parser.add_argument(
        "--corpus", required=True, choices=[plan.name for plan in _CORPUS_PLANS]
    )
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.jsonl"))
    parser.add_argument(
        "--artifact-path", type=Path, default=Path("data/catalog.artifacts")
    )
    parser.add_argument(
        "--pairs", type=int, default=None, help="probe corpus size, in matched pairs"
    )
    parser.add_argument(
        "--sessions", type=int, default=None, help="expanded corpus size, in sessions"
    )
    parser.add_argument("--cross-check-pairs", type=int, default=None)
    parser.add_argument("--model", default=None, choices=("haiku", "sonnet"))
    parser.add_argument(
        "--seed-label",
        default=None,
        help="D-27: expanded_confirm must use a DIFFERENT label from expanded_dev",
    )
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--response-log", type=Path, default=None)
    parser.add_argument("--divergence-log", type=Path, default=None)
    parser.add_argument("--drop-log", type=Path, default=None)
    parser.add_argument("--target-snapshot", type=Path, default=None)
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="replay a committed response log; no subprocess is spawned",
    )
    parser.add_argument(
        "--emit-pending",
        type=Path,
        default=None,
        help=(
            "detached authoring: answer from --replay where possible and write the"
            " requests it cannot answer to this queue file, exiting"
            f" {PENDING_REQUESTS_EXIT_STATUS}. No subprocess is spawned"
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="A5: 8-way fan-out is untested and 429s would force it back down",
    )
    parser.add_argument("--batch-size", type=int, default=_AUTHOR_BATCH_SIZE)
    parser.add_argument("--solvability-check", action="store_true")
    parser.add_argument("--drop-unsolvable", action="store_true")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--corpus-root", type=Path, default=CORPUS_ROOT)
    parser.add_argument("--markdown", type=Path, default=DATASETS_MARKDOWN_PATH)
    return parser


def main(argv: tuple[str, ...] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)

    if arguments.solvability_check and is_probe_corpus(arguments.corpus):
        # The same sentence `measure_solvability` raises, and deliberately a
        # second copy rather than a shared constant: the CLI refusal is what an
        # operator meets, and the function's own is what survives a refactor that
        # bypasses the CLI. It is checked FIRST, before any file is opened, so it
        # holds on a machine with no catalog and no artifact (L-3).
        print(
            "--solvability-check is forbidden for the probe corpus: a"
            " retrieval-backed filter would delete exactly the sessions that"
            " carry the vocabulary gap and launder the finding out of the"
            " measurement before it is measured (D-35)",
            file=sys.stderr,
        )
        return 1

    if arguments.emit_pending is not None and arguments.replay is None:
        # The queue and the log it is filling are two halves of one file pair, and
        # --replay already names that log. A second replay flag would let an
        # operator collect against one log and answer into another, which
        # converges only by luck.
        print(
            "--emit-pending requires --replay <log>: the queue is collected"
            " against the same response log the answers are appended to",
            file=sys.stderr,
        )
        return 1

    collector: PendingRequestCollector | None = None
    try:
        if arguments.emit_pending is not None:
            # Built INSIDE the try: a malformed or ambiguous response log makes the
            # collector refuse at construction, and that is an ordinary generation
            # failure rather than a pending round. Constructing it outside would
            # let that refusal escape `main` uncaught.
            collector = collecting_runner(
                replay_path=Path(arguments.replay),
                pending_path=Path(arguments.emit_pending),
            )
        return _run(arguments, collector)
    except (
        GenerateError,
        RegistryError,
        AuthoringError,
        CorpusSchemaError,
        OSError,
        ValueError,
        FileExistsError,
    ) as error:
        if collector is not None and collector.pending:
            # A collecting round that queued anything ALWAYS ends in an exception:
            # a queued request leaves its items with no phrase, `attempt_until`
            # refuses to return, and the collector itself stops the run at the
            # wave boundary. So the exception is the expected terminator here, not
            # a failure, and the queue is what the round produced. A round that
            # queued NOTHING falls through to the failure path below, which is
            # what must happen -- a genuine gate failure with a complete log is a
            # real failure and repeating the round would not fix it.
            print(f"pending_requests={len(collector.pending)}")
            print(f"pending_path={collector.pending_path.as_posix()}")
            print(f"response_log={Path(arguments.replay).as_posix()}")
            return PENDING_REQUESTS_EXIT_STATUS
        print(f"corpus generation failed: {error}", file=sys.stderr)
        return 1


def _run(
    arguments: argparse.Namespace,
    collector: PendingRequestCollector | None = None,
) -> int:
    plan = corpus_plan(arguments.corpus)
    stem = corpus_stem(plan.name)
    size = arguments.pairs if plan.paired else arguments.sessions
    wrong = arguments.sessions if plan.paired else arguments.pairs
    if wrong is not None:
        raise GenerateError(
            f"{plan.name} is sized in {plan.size_flag}; use --{plan.size_flag}"
        )
    if size is None:
        size = plan.default_size
    if size < 1:
        raise GenerateError(f"corpus size must be positive, got {size}")
    cross_check = (
        plan.default_cross_check
        if arguments.cross_check_pairs is None
        else arguments.cross_check_pairs
    )
    if not plan.paired and cross_check:
        raise GenerateError(
            f"{plan.name} carries one session per target and has no second arm to"
            " cross-check against (D-25)"
        )
    model_alias = arguments.model or plan.model_alias
    prompt_name = arguments.prompt or plan.prompt_name
    seed_label = arguments.seed_label or plan.name
    response_log = arguments.response_log or response_log_path(plan.name)
    divergence_log = arguments.divergence_log or divergence_log_path(plan.name)
    drop_log = arguments.drop_log or drop_log_path(plan.name)
    snapshot = arguments.target_snapshot
    if snapshot is None and is_probe_corpus(plan.name):
        # Probe corpus only. A snapshot for the 2,800 expanded sessions would add
        # megabytes of committed catalog text no test reads, and L-16 names repo
        # weight as this phase's real risk.
        snapshot = target_snapshot_path(plan.name)

    # The collector is a runner: on a hit it IS replay, and on a miss it queues
    # instead of guessing. Substituting it changes only who produces the text --
    # every gate, the publish sequence and the registry freeze are untouched.
    runner: AuthoringRunner = collector if collector is not None else (
        replay_runner(arguments.replay) if arguments.replay else claude_runner
    )
    vocabulary = load_vocabulary()
    catalog_sha256 = sha256_file(Path(arguments.catalog))
    _, categories, products = catalog_index(Path(arguments.catalog))

    # The candidate pool is filtered before the draw, not after it. A target
    # dropped after sampling would leave the corpus short of its recorded session
    # count, and topping up afterwards would make the draw depend on which
    # targets happened to fail -- neither is reproducible.
    candidates: list[str] = []
    strata: list[tuple[str, str]] = []
    for parent_asin in sorted(products):
        product = products[parent_asin]
        try:
            card = control_card(product)
            # `authorable_pair`, not `constraint_slots`: the filter has to run the
            # SAME call the build runs, or a target admitted here can still fail
            # at assembly. It is what refuses a target whose card would lose a
            # whole constraint list to the gist-supply omission.
            authorable_pair(
                PairTarget(
                    pair_id=pair_id_for(0, corpus_stem=stem),
                    target=parent_asin,
                    scenario_type="buying",
                    card=card,
                ),
                vocabulary=vocabulary,
                products={parent_asin: product},
            )
        except GenerateError:
            continue
        candidates.append(parent_asin)
        strata.append((parent_asin, stratum_for(product, categories.get(parent_asin, []))))

    excluded = public_target_ids() | _frozen_targets(
        Path(arguments.registry), exclude=plan.name, root=Path(arguments.corpus_root)
    )
    targets = sample_targets(
        tuple(candidates),
        count=size,
        seed_label=seed_label,
        excluded=excluded,
        strata=tuple(strata),
    )
    seed = pair_seed(seed_label, str(size), _SAMPLING_LABEL)

    pair_id_by_target = {
        target: pair_id_for(index, corpus_stem=stem)
        for index, target in enumerate(targets)
    }
    scenario_by_pair = assign_scenarios(tuple(pair_id_by_target.values()))
    scenarios = dict(scenario_by_pair)
    # Reduced ONCE, here, before any row or arm is built. Every downstream reader
    # -- the control row, `control_constraints`, and each `author_arm` call --
    # takes its card from this one tuple, so the arms cannot disagree about which
    # constraints the pair carries.
    pairs = tuple(
        authorable_pair(
            PairTarget(
                pair_id=pair_id_by_target[target],
                target=target,
                scenario_type=scenarios[pair_id_by_target[target]],
                card=control_card(products[target]),
            ),
            vocabulary=vocabulary,
            products=products,
        )
        for target in targets
    )

    calls: list[dict[str, object]] = []

    arms: list[tuple[str, str, str, tuple[PairTarget, ...]]] = [
        (plan.probe_arm, model_alias, prompt_name, pairs)
    ]
    if plan.paired and cross_check:
        selected = frozenset(cross_check_pairs(scenario_by_pair, count=cross_check))
        arms.append(
            (
                _CROSS_CHECK_ARM,
                _CROSS_CHECK_ALIAS,
                prompt_name,
                tuple(pair for pair in pairs if pair.pair_id in selected),
            )
        )

    # AUTHORED FIRST, ASSEMBLED SECOND. The two used to be one loop, which cannot
    # express the symmetric drop: a constraint the cross-check arm exhausts has to
    # come out of the control and primary rows too, and those rows were already
    # built by the time the cross-check arm ran. Nothing about the authoring
    # changed -- only the point at which a row is minted.
    authored_arms: list[tuple[str, tuple[PairTarget, ...], tuple[AuthoredConstraint, ...]]] = []
    dropped: list[DroppedConstraint] = []
    for arm, alias, arm_prompt, arm_pairs in arms:
        if not arm_pairs:
            continue
        authored = author_arm(
            arm_pairs,
            arm=arm,
            runner=runner,
            vocabulary=vocabulary,
            products=products,
            prompt_name=arm_prompt,
            model_alias=alias,
            batch_size=arguments.batch_size,
        )
        calls.extend(authored.calls)
        dropped.extend(authored.dropped)
        authored_arms.append((arm, arm_pairs, authored.constraints))

    if collector is not None and collector.pending:
        # Nothing may be published from a round that still has work in the queue.
        # An unanswered request makes its items look exhausted, and a placeholder
        # review verdict makes an answered item look rejected -- both would now be
        # DROPPED rather than raised on, so the corpus would come out short by
        # whatever the queue still holds with a ledger blaming the gates for it.
        # `main` turns this into the pending-requests exit status, which is the
        # normal state of a converging detached run.
        raise GenerateError(
            f"{len(collector.pending)} request(s) are still queued at"
            f" {collector.pending_path}; a corpus published now would be short by"
            " whatever the queue holds and its drop ledger would misattribute the"
            " shortfall to the gates"
        )

    arms_by_pair: dict[str, tuple[str, ...]] = {}
    for pair in pairs:
        carried = (("control",) if plan.paired else ()) + tuple(
            arm
            for arm, arm_pairs, _ in authored_arms
            if any(member.pair_id == pair.pair_id for member in arm_pairs)
        )
        arms_by_pair[pair.pair_id] = carried

    dropped_ids = frozenset(constraint.item_id for constraint in dropped)
    refused = refused_pairs(
        pairs, dropped_item_ids=dropped_ids, arms_by_pair=arms_by_pair
    )
    refused_ids = frozenset(record.pair_id for record in refused)
    positions = surviving_positions(pairs, dropped_item_ids=dropped_ids)

    rows: list[SampleRow] = []
    measured: list[AuthoredConstraint] = []
    surviving = tuple(pair for pair in pairs if pair.pair_id not in refused_ids)
    # The control arm is reduced by the SAME call as every authored arm, and its
    # row is built from the reduced constraints rather than from `pair.card`. A
    # control that kept a constraint the probe could not author would disclose
    # something the probe never states, and the measured delta would then be
    # information content rather than vocabulary -- the asymmetry `authorable_pair`
    # already refuses, arriving by a different door. Each retained string is still
    # the evaluator's own output verbatim (D-31); only the subset changed.
    staged: list[tuple[str, tuple[PairTarget, ...], tuple[AuthoredConstraint, ...]]] = []
    if plan.paired:
        staged.append(
            ("control", surviving, control_constraints(pairs, products=products))
        )
    staged.extend(authored_arms)

    for arm, arm_pairs, constraints in staged:
        retained = apply_drops(
            constraints,
            dropped_item_ids=dropped_ids,
            refused_pair_ids=refused_ids,
            positions=positions,
        )
        measured.extend(retained)
        by_pair: dict[str, list[AuthoredConstraint]] = {}
        for constraint in retained:
            by_pair.setdefault(constraint.slot.pair_id, []).append(constraint)
        for pair in arm_pairs:
            if pair.pair_id in refused_ids:
                continue
            rows.append(
                build_row(
                    pair_id=pair.pair_id,
                    arm=arm,
                    scenario_type=pair.scenario_type,
                    target=pair.target,
                    card=card_from_constraints(
                        tuple(by_pair[pair.pair_id]),
                        target_category=pair.card.target_category,
                    ),
                    profile=profile_for_target(products[pair.target], pair_id=pair.pair_id),
                )
            )
    assert_arms_match_on_constraint_ids(tuple(measured))

    solvability: dict[str, int] = {}
    # `--drop-unsolvable` is a THIRD reduction, taken by an operator who typed the
    # flag rather than by the gates, and it is subtracted here so the drop
    # ledger's arithmetic stays about the drops it actually describes. Rolling the
    # two together would let one reduction absorb the other's shortfall unnoticed,
    # which is the whole failure mode `check_recorded_counts` exists to catch.
    unsolvable_pairs = 0
    if arguments.solvability_check:
        unreachable: list[str] = []
        solvability = measure_solvability(
            tuple(rows),
            corpus_name=plan.name,
            artifact_path=Path(arguments.artifact_path),
            catalog_path=Path(arguments.catalog),
            observe=lambda row, hit: None if hit else unreachable.append(row.sample_id),
        )
        if arguments.drop_unsolvable:
            unsolvable = frozenset(unreachable)
            before = {row.pair_id for row in rows}
            rows = [row for row in rows if row.sample_id not in unsolvable]
            unsolvable_pairs = len(before - {row.pair_id for row in rows})

    ordered = tuple(sorted(rows, key=lambda row: (row.pair_id, row.arm)))
    records = tuple(row.as_record() for row in ordered)
    # The corpus name the OPERATOR asked for, never a stem recomputed from the
    # rows: the whole point of the check is to catch rows that disagree with the
    # corpus they are being published into, and a stem derived from those same
    # rows would agree with itself by construction.
    validate_corpus(records, corpus_name=plan.name)
    for record in records:
        assert_authored_branch(record)
    check_scenario_mix(records)
    if plan.paired:
        check_pairing(records)
        check_cross_check_subset(records)

    destination = publish_corpus(
        ordered, name=plan.name, root=Path(arguments.corpus_root)
    )
    Path(response_log).parent.mkdir(parents=True, exist_ok=True)
    write_response_log(Path(response_log), tuple(calls))
    Path(divergence_log).parent.mkdir(parents=True, exist_ok=True)
    divergence = divergence_records(
        tuple(measured), pair_id_by_target=pair_id_by_target
    )
    write_divergence_log(Path(divergence_log), divergence)
    Path(drop_log).parent.mkdir(parents=True, exist_ok=True)
    # Written on every run, including one that dropped nothing: an empty ledger is
    # a corpus stating that it lost nothing, while an absent file is something a
    # reader has to interpret.
    write_drop_log(Path(drop_log), tuple(dropped), refused)

    snapshot_targets = 0
    if snapshot is not None:
        Path(snapshot).parent.mkdir(parents=True, exist_ok=True)
        # The targets actually PUBLISHED, not the targets sampled. A refused pair
        # contributes no row, and a snapshot that still carried its text would
        # record a target the corpus does not hold -- and plan 02-11's sweep
        # asserts the snapshot's key set equals the corpus's target set.
        published = sorted({row.ground_truth_parent_asin for row in ordered})
        pairs_out = tuple(
            (target, searchable_text(products[target])) for target in published
        )
        write_target_snapshot(
            Path(snapshot),
            corpus_name=plan.name,
            catalog_sha256=catalog_sha256,
            targets=pairs_out,
        )
        snapshot_targets = len(pairs_out)

    revision, dirty = current_revision()
    resolved = _resolved_for_alias(tuple(calls), model_alias)
    prompts = {prompt_name: prompt_revision(prompt_name)}
    prompts[_REVIEW_PROMPT_NAME] = prompt_revision(_REVIEW_PROMPT_NAME)
    entry = DatasetEntry(
        name=plan.name,
        path=destination.as_posix(),
        sha256=sha256_file(destination),
        schema_version=CORPUS_SCHEMA_VERSION,
        session_count=len(ordered),
        distinct_target_count=len(distinct_targets(records)),
        scenario_mix=tuple(sorted(dict(_count_scenarios(records)).items())),
        generator_model_alias=model_alias,
        generator_model_resolved=resolved,
        claude_cli_version=_claude_cli_version(),
        prompt_pack=tuple(sorted(prompts.items())),
        seed=seed,
        code_revision=revision,
        code_revision_dirty=dirty,
        frozen_commit=revision,
        response_log_path=Path(response_log).as_posix(),
        response_log_sha256=sha256_file(Path(response_log)),
        call_count=len(calls),
        cost_usd=sum(float(record["cost_usd"]) for record in calls),
        divergence=divergence_from_summary(
            bucket_summary(
                tuple(
                    constraint.report
                    for constraint in measured
                    if constraint.arm != "control"
                )
            )
        ),
        divergence_log_path=Path(divergence_log).as_posix(),
        divergence_log_sha256=sha256_file(Path(divergence_log)),
        divergence_pair_count=len({record.pair_id for record in divergence}),
        target_snapshot_path=Path(snapshot).as_posix() if snapshot is not None else "",
        target_snapshot_sha256=sha256_file(Path(snapshot)) if snapshot is not None else "",
        target_snapshot_count=snapshot_targets,
        drop_log_path=Path(drop_log).as_posix(),
        drop_log_sha256=sha256_file(Path(drop_log)),
        # The shortfall, in the provenance record rather than only in the ledger.
        # `data/datasets.json` is what a reader of the corpus opens first, and a
        # registry that stated only how much survived would let the reduction pass
        # unnoticed exactly as an unexplained row count would.
        dropped_constraint_count=len(dropped_ids),
        refused_pair_count=len(refused),
    )
    # The recorded counts against the rows actually written, before the entry is
    # frozen. This is the invariant the docs/STATUS.md warning exists to protect,
    # and it is checked rather than argued: an entry describing a corpus other
    # than the published one is the failure mode, and it is silent by nature.
    check_recorded_counts(
        entry,
        records,
        load_drop_log(Path(drop_log)),
        sampled_pair_count=len(pairs) - unsolvable_pairs,
    )
    registry_path = Path(arguments.registry)
    existing = load_registry(registry_path) if registry_path.is_file() else ()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    entries = upsert_entry(existing, entry)
    write_registry(registry_path, entries)
    Path(arguments.markdown).parent.mkdir(parents=True, exist_ok=True)
    Path(arguments.markdown).write_text(render_markdown(entries), encoding="utf-8")

    surviving_pairs = len({row.pair_id for row in ordered})
    per_pair = _constraints_by_pair(tuple(measured))
    print(f"corpus={plan.name}")
    print(f"sessions={entry.session_count}")
    print(f"targets={entry.distinct_target_count}")
    print(f"sha256={entry.sha256}")
    print(f"divergence_pairs={entry.divergence_pair_count}")
    print(f"snapshot_targets={snapshot_targets}")
    print(f"calls={entry.call_count}")
    print(f"cost_usd={entry.cost_usd}")
    print(f"model_resolved={entry.generator_model_resolved}")
    # Printed unconditionally, including the all-zero case. A summary that appeared
    # only when something was dropped would train an operator to read its absence
    # as "nothing to see", which is indistinguishable from a run that forgot to
    # emit it.
    for name, value in drop_summary(tuple(dropped), refused):
        print(f"{name}={value}")
    print(f"sampled_pairs={len(pairs)}")
    print(f"surviving_pairs={surviving_pairs}")
    print(f"surviving_constraints={sum(per_pair)}")
    # `per_pair` cannot be empty here -- a corpus with no constraints does not
    # reach this line, because `card_from_constraints` and `validate_corpus` both
    # refuse one long before. Calling fmean straight is therefore honest rather
    # than unguarded; a `0.0` fallback would print a measured mean of zero
    # constraints for a case that cannot occur, and 0.0 is a real value some reader
    # would eventually quote.
    print(f"constraints_per_pair={statistics.fmean(per_pair):.4f}")
    print(f"drop_log={Path(drop_log).as_posix()}")
    if solvability:
        print(f"solvability_checked={solvability['checked']}")
        print(f"solvability_unreachable={solvability['unreachable']}")
    return 0


def _constraints_by_pair(
    constraints: tuple[AuthoredConstraint, ...],
) -> tuple[int, ...]:
    # Counted as DISTINCT (slot, position) per pair, not as rows: every arm
    # measures the same constraint set, so counting rows would multiply the card
    # size by the number of arms and report 2.4 constraints per pair as 5.6.
    by_pair: dict[str, set[tuple[str, int]]] = {}
    for constraint in constraints:
        by_pair.setdefault(constraint.slot.pair_id, set()).add(
            (constraint.slot.slot, constraint.slot.position)
        )
    return tuple(len(by_pair[pair_id]) for pair_id in sorted(by_pair))


def _count_scenarios(records: tuple[dict, ...]) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for record in records:
        scenario = str(record["scenario_type"])
        counts[scenario] = counts.get(scenario, 0) + 1
    return tuple(sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())
