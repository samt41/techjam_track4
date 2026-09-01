"""Prove the two properties `arena/datasets/generate.py` claims and cannot self-check.

The control arm is only "the public path" if it is compared to the public path. For
`buying`, `browsing` and `boundary` this module builds one target twice -- once as an
authored control row (branch 1 of `materialize_hidden_fields`) and once as a bare
six-key row (branch 2) -- and asserts the evaluator's own customer simulation emits
byte-identical utterances from both. D-31's most valuable output is that comparison,
not the corpus: Phase 7 frames the probe delta as "public-set phrasing vs customer
phrasing", and that framing rests entirely on the control arm really being the
former rather than an approximation of it.

`intent_override` is deliberately OUT of the byte comparison and gets the weaker
assertion it can honestly hold (D-55, L-2). See `OverrideArmFidelityTest`, which
measures the disagreement rather than asserting a rate it cannot control.

`SolvabilityAbsenceTest` is the L-3 guard: `.planning/research/ARCHITECTURE.md:258`
recommends a solvability check in general terms, and a diligent implementer who
follows that recommendation into the probe pipeline would delete precisely the
sessions carrying the vocabulary gap, report a delta of ~0, and leave every other
gate in this phase green. Plan 02-05's `tests/test_datasets_divergence.py` carries
its own narrower copy of that scan over `divergence.py` alone. The duplication is
deliberate and cheap: 02-05 lands two waves earlier than this module and must not be
able to regress in the gap.

Every product here is a hand-written dict from `tests/dataset_fixtures.py`. Nothing
in this module opens the built SQLite database or reads the 61 MB catalog file.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import random
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from arena.datasets.generate import (
    GenerateError,
    behavior_for_arm,
    build_row,
    control_card,
    is_probe_corpus,
    main,
    measure_solvability,
    override_turn_for_pair,
    pair_id_for,
    profile_for_target,
)
from arena.datasets.schema import (
    MAX_OVERRIDE_TURN,
    MIN_OVERRIDE_TURN,
    SCENARIO_TYPES,
    IntentCard,
)

# Reached through the D-08 seam rather than the harness package, because this is
# exactly the name the seam exists to expose (arena/evaluator_bridge.py:36).
from arena.evaluator_bridge import materialize_hidden_fields

# `initial_message`, `customer_reply` and `coarse_category` are NOT bridge names and
# must not become bridge names: `tests/test_arena_boundary.py` pins the seam at
# exactly eight exports, and widening it for a test's convenience is the "ninth name"
# that file refuses. A test module is outside the `arena/**` scan, so it may import
# the harness directly, exactly as `tests/test_evaluator.py` already does.
from evaluator.local_evaluator import (
    behavior_for,
    coarse_category,
    customer_reply,
    initial_message,
)
from tests.dataset_fixtures import pair_id, product, violating_row


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

_CORPUS_STEM = "probe_v1"

# Everything except `intent_override`. Scoping the byte comparison is the whole
# point of D-55: `behavior_for_arm` returns `Behavior(scenario_type, None)` here, and
# `Behavior.as_record()` emits a bare {"scenario_type": s} that matches `behavior_for`
# at local_evaluator.py:74-87 byte for byte. `intent_override` cannot match, because
# D-36 pins the turn from `pair_id` while the fallback draws from `sample_id`.
_SCENARIOS_WITHOUT_OVERRIDE = ("boundary", "browsing", "buying")

# One ask per reachable branch of `customer_reply`: a bucket the card answers, a
# bucket it does not, `None` (the "ask me about one specific attribute" branch), a
# name outside ALLOWED_ATTRIBUTES (which the harness folds to "other" at :172-173),
# and "other" itself. Ten turns, the evaluator's own MAX_TURNS.
_ASK_SEQUENCE = (
    "material",
    "color",
    None,
    "brand",
    "feature",
    "style",
    "size",
    "use_case",
    "budget",
    "an_attribute_the_harness_does_not_allow",
)

# Three hand-written products spanning the three shapes `intent_card` actually takes
# over the catalog: material + color matched out of the searchable text, neither
# matched but a price present (so the card carries a `budget` constraint), and colour
# only. A single product would leave two of the three `intent_card` branches untested
# and the identity claim narrower than it reads.
_PRODUCTS: dict[str, dict[str, object]] = {
    "B0CTRL0001": product(
        "B0CTRL0001",
        title="Women's Merino Wool Crew Neck Pullover",
        features=(
            "Machine washable and quick drying",
            "Relaxed fit through the shoulders",
        ),
        details=(("Closure Type", "Pull On"), ("Sleeve Type", "Long Sleeve")),
        description="A black wool pullover for winter commutes.",
        categories=("Clothing, Shoes & Jewelry", "Women", "Sweaters"),
        store="Northfell",
    ),
    "B0CTRL0002": product(
        "B0CTRL0002",
        title="Canvas Low Top Sneaker",
        features=("Cushioned insole for all day wear", "Reinforced toe cap"),
        details=(("Sole Material", "Rubber"),),
        description="Everyday sneaker built for the gym and the sidewalk.",
        categories=("Clothing, Shoes & Jewelry", "Men", "Shoes"),
        store="Tallgrass",
        price=39.99,
    ),
    "B0CTRL0003": product(
        "B0CTRL0003",
        title="Pleated Midi Skirt",
        features=("Side zip closure", "Lined for opacity"),
        details=(("Fit Type", "A-Line"), ("Care", "Hand wash cold")),
        description="A navy blue midi skirt that runs true to size.",
        categories=("Clothing, Shoes & Jewelry", "Women", "Skirts"),
        store="Vaurien",
    ),
}

_PRODUCT_IDS = tuple(sorted(_PRODUCTS))

# The prefix `customer_reply` emits at local_evaluator.py:185 when it actually
# discloses something. A transcript containing none of these disclosed nothing, and a
# byte-identity assertion over two such transcripts is vacuously true -- which is the
# failure mode two other plans in this phase shipped, so it is asserted rather than
# assumed.
_DISCLOSURE_PREFIX = "For that, what matters is:"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _control_record(
    parent_asin: str, *, scenario_type: str, index: int
) -> dict[str, object]:
    """One authored control row, built the way the generator builds one."""

    item = _PRODUCTS[parent_asin]
    identifier = pair_id_for(index, corpus_stem=_CORPUS_STEM)
    row = build_row(
        pair_id=identifier,
        arm="control",
        scenario_type=scenario_type,
        target=parent_asin,
        card=control_card(item),
        profile=profile_for_target(item, pair_id=identifier),
    )
    return row.as_record()


def _bare_record(control_record: dict[str, object]) -> dict[str, object]:
    """The same session with the authored fields stripped, so branch 2 must fire."""

    record = violating_row("bare")
    # Only the fields the two paths MUST share are copied across. The card is
    # emphatically not copied: branch 2 has to rebuild it from the product, which is
    # the entire content of the comparison. Copying it would make the assertion
    # compare one object with itself.
    for key in (
        "category_bucket",
        "difficulty_bucket",
        "ground_truth",
        "sample_id",
        "scenario_type",
        "user_profile",
    ):
        record[key] = control_record[key]
    return record


def _simulate(
    record: dict[str, object],
    card: dict,
    behavior: dict,
    *,
    asks: tuple[str | None, ...] = _ASK_SEQUENCE,
) -> dict[str, object]:
    """Drive the evaluator's own customer simulation and return everything it emitted."""

    # Assembled exactly as `evaluate` assembles it at local_evaluator.py:231, so the
    # simulation runs against the same dict shape the scored path runs against.
    sample = {**record, "intent_card": card, "behavior": behavior}
    target = str(sample["ground_truth"]["parent_asin"])  # type: ignore[index]
    category = coarse_category(
        [str(value) for value in _PRODUCTS[target]["categories"]]  # type: ignore[union-attr]
    )
    disclosed: set[str] = set()
    boundary_used = False
    transcript = [initial_message(sample, category, disclosed)]
    for ask in asks:
        message, boundary_used = customer_reply(sample, ask, disclosed, boundary_used)
        transcript.append(message)
    # `disclosed` and `boundary_used` travel with the transcript because they are the
    # simulator's carried state: two runs could emit the same sentences while leaving
    # the harness in different states, and the next turn would then diverge.
    return {
        "boundary_used": boundary_used,
        "disclosed": sorted(disclosed),
        "transcript": transcript,
    }


class ControlArmFidelityTest(unittest.TestCase):
    """D-31/D-55: the control arm IS the public path, for the three scenarios where
    that claim is expressible."""

    def test_the_scenario_split_covers_every_scenario_type(self) -> None:
        # Without this, adding a fifth scenario would silently leave it unchecked by
        # both this class and OverrideArmFidelityTest, and the coverage claim in the
        # module docstring would quietly stop being true.
        self.assertEqual(
            sorted((*_SCENARIOS_WITHOUT_OVERRIDE, "intent_override")),
            sorted(SCENARIO_TYPES),
        )
        self.assertNotIn("intent_override", _SCENARIOS_WITHOUT_OVERRIDE)

    def test_the_bare_record_really_takes_the_fallback_branch(self) -> None:
        # The non-vacuity guard for every assertion below. `materialize_hidden_fields`
        # branches on membership alone (local_evaluator.py:205); a bare record that
        # gained an `intent_card` key would take branch 1, and the whole class would
        # compare the control row against itself and pass for the wrong reason.
        record = _bare_record(_control_record(_PRODUCT_IDS[0], scenario_type="buying", index=0))
        self.assertNotIn("intent_card", record)
        self.assertNotIn("behavior", record)

    def test_the_fallback_branch_reads_the_product_it_is_handed(self) -> None:
        # Proves branch 2 is a real derivation rather than a lookup that would agree
        # with the control arm however the product changed: handing the SAME bare
        # record a different product must change the card it comes back with.
        record = _bare_record(_control_record(_PRODUCT_IDS[0], scenario_type="buying", index=0))
        own_card, _ = materialize_hidden_fields(record, _PRODUCTS)
        target = str(record["ground_truth"]["parent_asin"])  # type: ignore[index]
        foreign_card, _ = materialize_hidden_fields(
            record, {target: _PRODUCTS[_PRODUCT_IDS[1]]}
        )
        self.assertNotEqual(_canonical(own_card), _canonical(foreign_card))

    def test_control_and_fallback_materialize_the_same_card_and_behavior(self) -> None:
        for scenario_type in _SCENARIOS_WITHOUT_OVERRIDE:
            for index, parent_asin in enumerate(_PRODUCT_IDS):
                with self.subTest(scenario_type=scenario_type, target=parent_asin):
                    control = _control_record(
                        parent_asin, scenario_type=scenario_type, index=index
                    )
                    bare = _bare_record(control)
                    self.assertEqual(
                        _canonical(materialize_hidden_fields(control, _PRODUCTS)),
                        _canonical(materialize_hidden_fields(bare, _PRODUCTS)),
                        "D-31: the control arm must be the evaluator's own"
                        " intent_card verbatim. A re-clean, a re-order or a repair"
                        " makes the control-vs-probe contrast stop being exactly"
                        " 'public-set phrasing vs customer phrasing'.",
                    )

    def test_control_and_fallback_drive_byte_identical_customer_turns(self) -> None:
        # The assertion that turns "our control reproduces the public-set phrasing"
        # from a claim into evidence. Comparing the materialized dicts above is
        # necessary but not sufficient: what is actually scored is the sentences the
        # simulator speaks, so the sentences are what get compared.
        for scenario_type in _SCENARIOS_WITHOUT_OVERRIDE:
            for index, parent_asin in enumerate(_PRODUCT_IDS):
                with self.subTest(scenario_type=scenario_type, target=parent_asin):
                    control = _control_record(
                        parent_asin, scenario_type=scenario_type, index=index
                    )
                    bare = _bare_record(control)
                    control_run = _simulate(
                        control, *materialize_hidden_fields(control, _PRODUCTS)
                    )
                    bare_run = _simulate(
                        bare, *materialize_hidden_fields(bare, _PRODUCTS)
                    )
                    self.assertEqual(_canonical(control_run), _canonical(bare_run))

    def test_the_simulated_transcripts_actually_disclose_something(self) -> None:
        # Two transcripts of nothing but "I don't have an additional preference for
        # X." are byte-identical no matter how badly the control card is broken. This
        # is the assertion that stops the class above from passing vacuously.
        for scenario_type in _SCENARIOS_WITHOUT_OVERRIDE:
            for index, parent_asin in enumerate(_PRODUCT_IDS):
                with self.subTest(scenario_type=scenario_type, target=parent_asin):
                    control = _control_record(
                        parent_asin, scenario_type=scenario_type, index=index
                    )
                    run = _simulate(
                        control, *materialize_hidden_fields(control, _PRODUCTS)
                    )
                    self.assertTrue(
                        any(
                            _DISCLOSURE_PREFIX in message
                            for message in run["transcript"]  # type: ignore[union-attr]
                        ),
                        run,
                    )
                    self.assertNotEqual(run["disclosed"], [])

    def test_the_transcript_comparison_can_fail(self) -> None:
        # The second half of the two-sided check, and the one that needs no mutation
        # of the module under test: grafting a different product's card onto the same
        # session must change what the customer says. If it does not, the comparison
        # above is measuring nothing.
        for scenario_type in _SCENARIOS_WITHOUT_OVERRIDE:
            with self.subTest(scenario_type=scenario_type):
                control = _control_record(
                    _PRODUCT_IDS[0], scenario_type=scenario_type, index=0
                )
                own_card, behavior = materialize_hidden_fields(control, _PRODUCTS)
                foreign_card = control_card(_PRODUCTS[_PRODUCT_IDS[1]]).as_record()
                self.assertNotEqual(
                    _canonical(_simulate(control, own_card, behavior)),
                    _canonical(_simulate(control, foreign_card, behavior)),
                )


class OverrideArmFidelityTest(unittest.TestCase):
    """D-55/L-2: the honest, deliberately weaker `intent_override` assertion."""

    def _control(self, parent_asin: str, index: int) -> dict[str, object]:
        return _control_record(
            parent_asin, scenario_type="intent_override", index=index
        )

    def test_the_override_card_is_identical_across_the_two_branches(self) -> None:
        # Card identity DOES hold for intent_override -- `control_card` is the same
        # verbatim wrap whatever the scenario -- so it is asserted at full strength.
        for index, parent_asin in enumerate(_PRODUCT_IDS):
            with self.subTest(target=parent_asin):
                control = self._control(parent_asin, index)
                bare = _bare_record(control)
                control_card_record, _ = materialize_hidden_fields(control, _PRODUCTS)
                bare_card_record, _ = materialize_hidden_fields(bare, _PRODUCTS)
                self.assertEqual(
                    _canonical(control_card_record), _canonical(bare_card_record)
                )

    def test_the_override_behavior_matches_on_everything_except_the_turn(self) -> None:
        # D-36 is the ONLY licensed difference. `old_value`, `new_value` and the
        # message are all derived by `behavior_for_arm` the way `behavior_for` derives
        # them at local_evaluator.py:79-86, so a divergence in any of those three is a
        # real defect and is asserted at full strength.
        for index, parent_asin in enumerate(_PRODUCT_IDS):
            with self.subTest(target=parent_asin):
                control = self._control(parent_asin, index)
                bare = _bare_record(control)
                _, control_behavior = materialize_hidden_fields(control, _PRODUCTS)
                _, bare_behavior = materialize_hidden_fields(bare, _PRODUCTS)
                self.assertEqual(
                    control_behavior["scenario_type"], bare_behavior["scenario_type"]
                )
                for key in ("message", "new_value", "old_value"):
                    self.assertEqual(
                        control_behavior["override"][key],
                        bare_behavior["override"][key],
                        f"only override['turn'] may differ (D-36); {key} diverged",
                    )
                self.assertIn(control_behavior["override"]["turn"], (3, 4))
                self.assertIn(bare_behavior["override"]["turn"], (3, 4))

    def test_an_unscoped_byte_identity_assertion_would_be_flaky(self) -> None:
        # D-55/L-2, measured rather than quoted. The control arm pins the turn from
        # `pair_id` (D-36) while the fallback draws `rng.choice([3, 4])` from
        # `f"{sample_id}\0{scenario_type}"` (local_evaluator.py:210-212), so the two
        # agree only by coincidence. This asserts the coincidence rate is strictly
        # inside (0, 1): a rate of 0 would mean the seeds are secretly the same and
        # the scoping is unnecessary, a rate of 1 would mean they never agree and the
        # weaker assertion above is testing nothing.
        #
        # Measured on this tree: 101 of 200 pairs disagree. D-55's "~15% flaky" is the
        # corpus-incidence framing -- intent_override is 15% of the D-30 mix -- not the
        # rate conditional on an override row, which is a coin flip.
        card = control_card(_PRODUCTS[_PRODUCT_IDS[0]]).as_record()
        disagreements = 0
        for index in range(200):
            identifier = pair_id(index, corpus_stem=_CORPUS_STEM)
            pinned = override_turn_for_pair(identifier, "intent_override")
            # The harness's OWN `behavior_for`, handed the seed
            # `materialize_hidden_fields` builds at :210-212 for the control arm's
            # sample_id. Transcribing `rng.choice([3, 4])` here instead would let the
            # measurement drift away from the draw it claims to be measuring.
            fallback = behavior_for(
                "intent_override",
                card,
                random.Random(f"{identifier}_control\0intent_override"),
            )["override"]["turn"]
            if pinned != fallback:
                disagreements += 1
        self.assertGreater(
            disagreements,
            0,
            "the pinned and fallback turns never disagree over 200 pairs, so either"
            " the seeds have been made identical or this measurement is not"
            " measuring the draw D-55 scopes the byte comparison around",
        )
        self.assertLess(disagreements, 200)


class PairPinningTest(unittest.TestCase):
    """D-36: the property the pinning actually guarantees, and nothing weaker."""

    def _probe_card(self, parent_asin: str) -> IntentCard:
        # A hand-written customer-language card for the same target: different
        # wording in every slot, which is what a probe arm carries. Without it the
        # cross-arm test would build both arms from one card and prove nothing --
        # the degenerate-fixture failure two other plans in this phase shipped.
        control = control_card(_PRODUCTS[parent_asin])
        return IntentCard(
            target_category=control.target_category,
            hard_constraints=tuple(
                f"honestly I just want {value}" for value in control.hard_constraints
            ),
            soft_preferences=tuple(
                f"and ideally {value}" for value in control.soft_preferences
            ),
        )

    def test_both_arms_of_one_pair_agree_on_the_override_turn(self) -> None:
        for index, parent_asin in enumerate(_PRODUCT_IDS):
            with self.subTest(target=parent_asin):
                identifier = pair_id_for(index, corpus_stem=_CORPUS_STEM)
                control = control_card(_PRODUCTS[parent_asin])
                probe = self._probe_card(parent_asin)
                # The fixture must be capable of exhibiting the violation: if the two
                # cards were equal, an arm-dependent draw would be undetectable here.
                self.assertNotEqual(_canonical(control.as_record()), _canonical(probe.as_record()))
                control_behavior = behavior_for_arm(
                    control, scenario_type="intent_override", pair_id=identifier
                )
                probe_behavior = behavior_for_arm(
                    probe, scenario_type="intent_override", pair_id=identifier
                )
                assert control_behavior.override is not None
                assert probe_behavior.override is not None
                self.assertEqual(
                    control_behavior.override.turn,
                    probe_behavior.override.turn,
                    "D-36: an arm-dependent override turn plants a confound inside"
                    " the one scenario the probe is most interested in, because the"
                    " turn decides how much the agent has already seen when the"
                    " intent flips",
                )
                # ...while the vocabulary under test genuinely differs, so the
                # agreement above is a property of the seeding and not of the inputs.
                self.assertNotEqual(
                    control_behavior.override.new_value,
                    probe_behavior.override.new_value,
                )

    def test_the_pinned_turn_cannot_take_an_arm_or_a_sample_id(self) -> None:
        # Structural, and the cheapest guard there is on the D-36 reasoning: the two
        # arms of a pair carry different `sample_id`s, so a signature that accepted
        # either one would make an arm-dependent draw expressible. It is not.
        parameters = list(inspect.signature(override_turn_for_pair).parameters)
        self.assertEqual(parameters, ["pair_id", "scenario_type"])

    def test_the_override_turn_distribution_is_not_degenerate(self) -> None:
        # A constant function satisfies "identical across arms" perfectly. This is
        # what stops that from passing (T-02-45).
        turns = [
            override_turn_for_pair(pair_id(index, corpus_stem=_CORPUS_STEM), "intent_override")
            for index in range(200)
        ]
        self.assertEqual(sorted(set(turns)), [3, 4])
        for value in (3, 4):
            self.assertGreaterEqual(
                turns.count(value),
                40,
                f"turn {value} appears {turns.count(value)} times in 200 draws;"
                f" the distribution is effectively constant: {turns[:20]}",
            )

    def test_every_pinned_turn_actually_fires(self) -> None:
        # Both choices sit inside the reachable 2..10 window; a turn outside it never
        # triggers and the row silently scores as a plain browsing session.
        for scenario_type in SCENARIO_TYPES:
            for index in range(50):
                turn = override_turn_for_pair(
                    pair_id(index, corpus_stem=_CORPUS_STEM), scenario_type
                )
                self.assertTrue(MIN_OVERRIDE_TURN <= turn <= MAX_OVERRIDE_TURN, turn)

    def test_the_pinned_turn_is_reproducible_across_calls(self) -> None:
        # `random.Random(...)` is constructed per call; a module-level generator would
        # make the second call for the same pair return something else, and the two
        # arms would then be built from different draws in the same run.
        for index in range(50):
            identifier = pair_id(index, corpus_stem=_CORPUS_STEM)
            first = override_turn_for_pair(identifier, "intent_override")
            second = override_turn_for_pair(identifier, "intent_override")
            self.assertEqual(first, second)


_MODULE_SCOPE = "<module>"

# The four modules the probe corpus is generated by. `schema.py` and `registry.py`
# are excluded because they are consumed by the loader rather than the pipeline; if
# a fifth generating module appears it belongs on this list.
_PROBE_PIPELINE_MODULES = (
    "arena/datasets/authoring.py",
    "arena/datasets/divergence.py",
    "arena/datasets/generate.py",
    "arena/datasets/gist.py",
)

# Naming any of these anywhere in the probe pipeline means a conversation is being
# simulated or a retrieval plan built at corpus-build time. There is no legitimate
# site for them, so they carry no exemption at all.
_FORBIDDEN_EVERYWHERE = ("Agent", "RetrievalPlanner", "TurnCoordinator")

# These have exactly one legitimate use each and are confined to it by path AND by
# enclosing function, never by name alone.
_CONFINED_NAMES = ("LocalProductSearchBackend", "RetrievalRoute", "SearchRequest")

# `backend.search(...)` is the actual laundering instrument -- the call that decides
# whether a target is retrievable and therefore which sessions could be dropped.
_SEARCH_CALL = ".search"

_WATCHED_NAMES = (*_FORBIDDEN_EVERYWHERE, *_CONFINED_NAMES)

# Keyed by repository-relative path, enclosing function and name. Anchoring to the
# full path rather than the basename is `tests/test_arena_boundary.py`'s L-1 lesson:
# under a basename key a second `arena/datasets/gist.py` elsewhere in the tree would
# silently inherit the exemption.
#
# `gist.py::main` is a deliberate, narrow exemption rather than an oversight. It is
# the one-off offline vocabulary builder: it opens the backend to read catalog facets
# through `CatalogIndex` and never issues a `SearchRequest` or calls `.search`, so it
# cannot express "is this target retrievable?" and therefore cannot filter on it.
# `test_the_gist_exemption_cannot_grow_into_a_retrieval_call` pins that distinction.
_PERMITTED_SITES = frozenset(
    {
        ("arena/datasets/generate.py", "measure_solvability", "LocalProductSearchBackend"),
        ("arena/datasets/generate.py", "measure_solvability", "RetrievalRoute"),
        ("arena/datasets/generate.py", "measure_solvability", "SearchRequest"),
        ("arena/datasets/generate.py", "measure_solvability", _SEARCH_CALL),
        ("arena/datasets/gist.py", "main", "LocalProductSearchBackend"),
    }
)

# The L-3 refusal, quoted once here so deleting it from either site in generate.py
# turns this module red.
_REFUSAL = "forbidden for the probe corpus"


@dataclass(frozen=True, slots=True)
class RetrievalReference:
    """One naming of a retrieval symbol, with the function that names it."""

    module: str
    function: str
    name: str
    lineno: int

    def as_site(self) -> tuple[str, str, str]:
        return (self.module, self.function, self.name)

    def __str__(self) -> str:
        return f"{self.module}:{self.lineno} names {self.name} inside {self.function}"


def _nodes_with_scope(tree: ast.AST):
    """Every node paired with the name of the function lexically enclosing it."""

    # Scope tracking is what makes the confinement checkable at all: a scan that only
    # reported "generate.py mentions SearchRequest" could not tell the one legitimate
    # site from a solvability filter bolted onto the authoring loop.
    stack: list[tuple[ast.AST, str]] = [(tree, _MODULE_SCOPE)]
    while stack:
        node, scope = stack.pop()
        for child in ast.iter_child_nodes(node):
            child_scope = (
                child.name
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                else scope
            )
            yield child, child_scope
            stack.append((child, child_scope))


def _referenced_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id in _WATCHED_NAMES:
        return node.id
    if isinstance(node, ast.Attribute):
        if node.attr in _WATCHED_NAMES:
            # Catches `starter.agent.Agent(...)`, which an import walk alone misses.
            return node.attr
        if node.attr == _SEARCH_CALL.lstrip("."):
            return _SEARCH_CALL
    if isinstance(node, ast.alias) and node.name in _WATCHED_NAMES:
        return node.name
    return None


def retrieval_references(
    path: Path, *, module: str | None = None
) -> tuple[RetrievalReference, ...]:
    # Takes a path and a label rather than hard-coding the modules under test, so the
    # scanner can be proven to fire against synthetic files in a temporary directory.
    # A scanner that has never been shown to fail is not a scanner.
    label = module or path.as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = [
        RetrievalReference(
            module=label,
            function=scope,
            name=name,
            lineno=getattr(node, "lineno", 0),
        )
        for node, scope in _nodes_with_scope(tree)
        if (name := _referenced_name(node)) is not None
    ]
    return tuple(sorted(found, key=lambda item: (item.module, item.lineno, item.name)))


def refusal_sites(path: Path, needle: str) -> tuple[tuple[str, int], ...]:
    """Every string constant containing `needle`, with its enclosing function."""

    # Adjacent string literals are folded by the parser, so a refusal split across
    # source lines still arrives here as one constant carrying the whole sentence.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        sorted(
            (scope, node.lineno)
            for node, scope in _nodes_with_scope(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and needle in node.value
        )
    )


def _cli(corpus: str) -> tuple[int, str, list[str]]:
    """Run the generator CLI with every output path inside a temporary directory."""

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            code = main(
                (
                    "--corpus", corpus,
                    "--solvability-check",
                    # Deliberately absent. The L-3 guard is claimed to run before any
                    # file is opened, so it must hold on a machine with no catalog and
                    # no built database -- which is also what keeps this test offline.
                    "--catalog", str(root / "absent.jsonl"),
                    "--artifact-path", str(root / "absent"),
                    "--registry", str(root / "datasets.json"),
                    "--corpus-root", str(root),
                    "--markdown", str(root / "datasets.md"),
                    "--response-log", str(root / "responses.jsonl"),
                    "--divergence-log", str(root / "divergence.jsonl"),
                    "--target-snapshot", str(root / "targets.json"),
                )
            )
        return code, stream.getvalue(), sorted(entry.name for entry in root.iterdir())


class SolvabilityAbsenceTest(unittest.TestCase):
    """L-3/D-35: the probe pipeline cannot reach retrieval, machine-checked."""

    def _live_references(self) -> tuple[RetrievalReference, ...]:
        references: list[RetrievalReference] = []
        for relative in _PROBE_PIPELINE_MODULES:
            path = REPOSITORY_ROOT / relative
            self.assertTrue(path.is_file(), f"{relative} is missing; the scan would "
                            "pass vacuously over a module that no longer exists")
            references.extend(retrieval_references(path, module=relative))
        return tuple(references)

    def test_no_probe_pipeline_module_reaches_retrieval_outside_one_permitted_site(
        self,
    ) -> None:
        violations = [
            str(reference)
            for reference in self._live_references()
            if reference.as_site() not in _PERMITTED_SITES
        ]
        self.assertEqual(
            violations,
            [],
            "D-35/L-3: a retrieval-backed solvability filter in the probe pipeline "
            "would delete exactly the sessions carrying the vocabulary gap and "
            "launder the finding out of the measurement before it is measured. "
            f"Unpermitted sites: {violations}",
        )

    def test_no_probe_pipeline_module_names_an_agent_at_all(self) -> None:
        # Stated separately from the site check so the failure names the symbol. These
        # three carry no exemption anywhere, at module scope or inside any function.
        offenders = [
            str(reference)
            for reference in self._live_references()
            if reference.name in _FORBIDDEN_EVERYWHERE
        ]
        self.assertEqual(offenders, [])

    def test_the_confinement_is_not_vacuous(self) -> None:
        # Without this, renaming or deleting `measure_solvability` would make the site
        # check above pass over a module that no longer contains what it confines --
        # protection that reads well and cannot fail.
        sites = {
            reference.as_site()
            for reference in retrieval_references(
                REPOSITORY_ROOT / "arena/datasets/generate.py",
                module="arena/datasets/generate.py",
            )
        }
        for name in ("LocalProductSearchBackend", "SearchRequest", _SEARCH_CALL):
            self.assertIn(
                ("arena/datasets/generate.py", "measure_solvability", name),
                sites,
                f"{name} is no longer named inside measure_solvability, so the "
                "confinement assertion is checking an empty set",
            )

    def test_the_gist_exemption_cannot_grow_into_a_retrieval_call(self) -> None:
        # `gist.py::main` may open the backend to read catalog facets; it may not
        # acquire the ability to ask whether a target is retrievable.
        references = retrieval_references(
            REPOSITORY_ROOT / "arena/datasets/gist.py", module="arena/datasets/gist.py"
        )
        named = sorted({reference.name for reference in references})
        self.assertEqual(named, ["LocalProductSearchBackend"])

    def test_the_scanner_fires_on_a_synthetic_violation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                "from starter.agent import Agent\n"
                "\n"
                "\n"
                "def run(backend: object) -> object:\n"
                "    return backend.search(None)\n",
                encoding="utf-8",
            )
            references = retrieval_references(probe, module="probe.py")
        names = [reference.name for reference in references]
        self.assertIn("Agent", names)
        self.assertIn(_SEARCH_CALL, names)
        self.assertTrue(
            all(reference.as_site() not in _PERMITTED_SITES for reference in references)
        )

    def test_the_scanner_separates_the_permitted_site_from_every_other_scope(
        self,
    ) -> None:
        # The two-sided half of the confinement logic itself: the same symbol, in the
        # same file, must be permitted in one function and refused in another and at
        # module scope. A scan keyed on the file alone cannot tell these apart.
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                "REQUEST = SearchRequest\n"
                "\n"
                "\n"
                "def measure_solvability() -> object:\n"
                "    return SearchRequest()\n"
                "\n"
                "\n"
                "def drop_unsolvable_sessions() -> object:\n"
                "    return SearchRequest()\n",
                encoding="utf-8",
            )
            references = retrieval_references(
                probe, module="arena/datasets/generate.py"
            )
        scopes = {
            reference.function: reference.as_site() in _PERMITTED_SITES
            for reference in references
        }
        self.assertEqual(
            scopes,
            {
                _MODULE_SCOPE: False,
                "measure_solvability": True,
                "drop_unsolvable_sessions": False,
            },
        )

    def test_the_scanner_passes_a_clean_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                "import json\n\nvalue = json.dumps({})\n", encoding="utf-8"
            )
            self.assertEqual(retrieval_references(probe, module="probe.py"), ())

    def test_the_refusal_is_stated_at_the_cli_and_inside_the_function(self) -> None:
        # Two copies, deliberately, and asserted by SITE rather than by count: a count
        # of two is satisfied by two copies in the same place. The CLI refusal is what
        # an operator meets; the function's own is what survives a refactor that
        # bypasses the CLI and calls `measure_solvability` directly.
        sites = refusal_sites(
            REPOSITORY_ROOT / "arena/datasets/generate.py", _REFUSAL
        )
        self.assertGreaterEqual(len(sites), 2, sites)
        self.assertEqual(
            sorted({scope for scope, _ in sites}), ["main", "measure_solvability"]
        )

    def test_measure_solvability_refuses_a_probe_corpus(self) -> None:
        with self.assertRaises(GenerateError) as caught:
            measure_solvability(
                (),
                corpus_name="probe.v1",
                artifact_path=Path("no-such-artifact"),
                catalog_path=Path("no-such-catalog.jsonl"),
            )
        # The branch's own sentence, not merely the exception type: `GenerateError` is
        # raised from a dozen other places in this module, so a type-only assertion
        # would pass on an unrelated failure and report a guard that never ran.
        self.assertIn(_REFUSAL, str(caught.exception))

    def test_the_function_refusal_is_scoped_to_the_probe(self) -> None:
        # The negative half. An expanded corpus must get PAST the guard -- it fails
        # later, on the database this test deliberately does not have. The type is
        # left unpinned on purpose: what is being asserted is that the corpus-name
        # guard did not fire, not which storage error the artifact layer chooses.
        with self.assertRaises(Exception) as caught:  # noqa: B017
            measure_solvability(
                (),
                corpus_name="expanded_dev.v1",
                artifact_path=Path("no-such-artifact"),
                catalog_path=Path("no-such-catalog.jsonl"),
            )
        self.assertNotIn(_REFUSAL, str(caught.exception))

    def test_the_corpus_classifier_separates_the_probe_from_the_expanded_corpora(
        self,
    ) -> None:
        self.assertTrue(is_probe_corpus("probe.v1"))
        self.assertFalse(is_probe_corpus("expanded_dev.v1"))
        self.assertFalse(is_probe_corpus("expanded_confirm.v1"))

    def test_the_cli_refuses_the_probe_before_opening_anything(self) -> None:
        code, stderr, written = _cli("probe.v1")
        self.assertEqual(code, 1)
        self.assertIn(_REFUSAL, stderr)
        self.assertEqual(written, [], "the refusal must precede every file open")

    def test_the_cli_refusal_is_scoped_to_the_probe(self) -> None:
        code, stderr, written = _cli("expanded_dev.v1")
        self.assertEqual(code, 1)
        self.assertNotIn(_REFUSAL, stderr)
        self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
