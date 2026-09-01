from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from arena.datasets.gist import (
    FEATURE_ABSTRACTIONS_PATH,
    GIST_SCHEMA_VERSION,
    GistPair,
    GistVocabulary,
    _GIST_DF_FLOOR,
    build_vocabulary,
    gist_for_target,
    load_feature_abstractions,
    load_vocabulary,
    prompt_payload_strings,
)
from arena.evaluator_bridge import searchable_text
from starter.shopping_agent.text_normalization import normalize_text


# Hand-written raw catalog payloads. This module opens no database: every assertion
# runs against the committed gist assets and the dicts below, which is the point --
# the 580 MB artifact is gitignored and an operator-machine dependency, so a test
# that needed it could not run in a clean checkout.
#
# Declared locally rather than imported from the shared dataset fixtures, because
# that module is authored by a sibling plan in the same wave and does not exist at
# this plan's base commit. The helper is module-private so the two cannot collide
# when the shared one lands.
def _product(
    parent_asin: str,
    *,
    title: str,
    features: tuple[str, ...] = (),
    details: dict[str, str] | None = None,
    description: str = "",
    categories: tuple[str, ...] = ("Clothing, Shoes & Jewelry",),
    store: str = "Example Store",
) -> dict[str, object]:
    return {
        "parent_asin": parent_asin,
        "title": title,
        "features": list(features),
        "details": dict(details or {}),
        "description": description,
        "categories": list(categories),
        "store": store,
    }


# Covers all five gist attributes at once: material, color, size and style from
# structured details, plus three feature values that the abstraction table maps.
LEATHER_BOOT = _product(
    "B00BOOT001",
    title="Trailmaster Hiking Boot",
    features=("imported", "rubber sole", "leather upper"),
    details={
        "Material": "Leather",
        "Color": "Brown",
        "Size": "Medium",
        "Style": "Classic",
    },
    description="A sturdy everyday boot for long walks.",
    categories=("Clothing, Shoes & Jewelry", "Men", "Shoes"),
    store="Trailmaster",
)

# The boilerplate-heavy case D-52 exists for: three of the highest-frequency
# verbatim catalog feature strings in the whole catalog, on one product.
BOILERPLATE_TEE = _product(
    "B00TEE0001",
    title="Everyday Crew Tee",
    features=(
        "imported",
        "machine wash",
        "rubber sole",
        "100% cotton",
        "pull on closure",
    ),
    details={"Color": "Black", "Size": "Large"},
    description="A soft crew-neck tee.",
    categories=("Clothing, Shoes & Jewelry", "Women", "Clothing"),
    store="Everyday",
)

# Exercises the mis-filed "key: value" feature recovery path alongside two more
# abstraction rows.
KEYED_SUNGLASSES = _product(
    "B00SUN0001",
    title="Harbour Aviator Sunglasses",
    features=("color: black", "style: modern", "polarized", "metal frame"),
    details={"Material": "Metal"},
    description="Lightweight aviators.",
    categories=("Clothing, Shoes & Jewelry", "Women", "Accessories"),
    store="Harbour",
)

# Every attribute value on this product is idiosyncratic to it, so the floor must
# exclude all of them rather than crash.
BELOW_FLOOR = _product(
    "B00RARE001",
    title="Handforged Curio",
    features=("shaped over three days in a lakeside workshop",),
    details={
        "Material": "Unobtainium",
        "Color": "Iridescent Aubergine",
        "Size": "Teacup",
        "Style": "Whimsical",
    },
    description="An unusual object.",
)

ALL_PRODUCTS = (LEATHER_BOOT, BOILERPLATE_TEE, KEYED_SUNGLASSES, BELOW_FLOOR)


def span_violations(
    pairs: tuple[GistPair, ...],
    payload: dict[str, object],
    abstract_attributes: frozenset[str],
) -> tuple[str, ...]:
    """Report every feature-abstraction pair that is a verbatim span of the target.

    Reports rather than asserts, so the same function can be pointed at a
    deliberately poisoned vocabulary and shown to fire. A check that can only be
    observed passing is not a gate.

    Scoped to `abstract_attributes` on purpose. D-32 guarantees that no catalog span
    the target OWNS reaches the prompt, not that no catalog token does: DF-gated
    canonical values are admitted verbatim by design, and D-32's own worked example
    is `material=leather` on a leather boot, whose catalog text necessarily contains
    the token `leather`. The anti-circularity mechanism for canonical values is the
    document-frequency floor -- a value on at least ten of fifty thousand products
    cannot identify one target -- while span novelty is a `feature`-only property
    that D-52's abstraction table supplies. Widening this scope to all attributes
    makes MEAS-12 permanently red rather than stricter; `ScopingCompanionTest` below
    pins that so a future reader finds out from a failing test, not from a corpus.
    """
    corpus = normalize_text(searchable_text(payload))
    violations: list[str] = []
    for pair in pairs:
        if pair.attribute not in abstract_attributes:
            continue
        if normalize_text(pair.value.replace("_", " ")) in corpus:
            violations.append(f"value {pair.attribute}={pair.value}")
        if normalize_text(pair.attribute.replace("_", " ")) in corpus:
            violations.append(f"attribute {pair.attribute}={pair.value}")
    return tuple(violations)


def abstraction_echoes(rows: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    """Report abstraction rows whose abstract half appears inside its own source value.

    An echoing abstraction is not an abstraction: it puts the catalog's own word
    straight back into the authoring prompt, which is the exact hole D-52 closes.
    """
    echoing: list[str] = []
    for row in rows:
        attribute = row.get("attribute")
        token = row.get("token")
        if attribute is None or token is None:
            continue
        source = normalize_text(row["value"])
        if normalize_text(str(attribute).replace("_", " ")) in source:
            echoing.append(f"attribute {attribute} echoes {row['value']}")
        if normalize_text(str(token).replace("_", " ")) in source:
            echoing.append(f"token {token} echoes {row['value']}")
    return tuple(echoing)


class GistVocabularyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.vocabulary = load_vocabulary()

    def test_committed_vocabulary_covers_exactly_the_five_gist_attributes(self) -> None:
        names = {name for name, _ in self.vocabulary.values}
        self.assertEqual(names, {"color", "feature", "material", "size", "style"})

    def test_committed_vocabulary_records_the_module_floor_and_schema(self) -> None:
        self.assertEqual(self.vocabulary.df_floor, _GIST_DF_FLOOR)
        self.assertEqual(self.vocabulary.schema_version, GIST_SCHEMA_VERSION)

    def test_admits_a_value_the_asset_lists(self) -> None:
        self.assertTrue(self.vocabulary.admits("material", "leather"))

    def test_rejects_a_value_the_asset_does_not_list(self) -> None:
        self.assertFalse(self.vocabulary.admits("material", "unobtainium"))
        self.assertFalse(self.vocabulary.admits("brand", "trailmaster"))

    def test_the_committed_feature_vocabulary_holds_no_catalog_string(self) -> None:
        # The asset is a build product, so the builder test alone would not catch a
        # hand-edited or stale asset. Every source value in the abstraction table is
        # a verbatim catalog string; none of them may appear as an admitted value.
        admitted = dict(self.vocabulary.values)["feature"]
        for source, _ in self.vocabulary.abstractions:
            with self.subTest(source=source):
                self.assertNotIn(source, admitted)
        self.assertEqual(
            set(admitted),
            {token for _, (_, token) in self.vocabulary.abstractions},
        )

    def test_pair_fields_cannot_carry_the_payload_separator(self) -> None:
        # Backs the one-'=' structural clause at construction rather than at
        # serialization, so no caller can build a pair that breaks the parse.
        with self.assertRaises(ValueError):
            GistPair(attribute="material", value="leather=brown").validate()


class GistExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.vocabulary = load_vocabulary()

    def test_leather_boot_carries_the_canonical_material_pair(self) -> None:
        pairs = gist_for_target(LEATHER_BOOT, self.vocabulary)
        self.assertIn(GistPair(attribute="material", value="leather"), pairs)

    def test_pairs_are_sorted_and_deduplicated(self) -> None:
        for payload in ALL_PRODUCTS:
            with self.subTest(parent_asin=payload["parent_asin"]):
                pairs = gist_for_target(payload, self.vocabulary)
                keys = [(pair.attribute, pair.value) for pair in pairs]
                self.assertEqual(keys, sorted(keys))
                self.assertEqual(len(keys), len(set(keys)))

    def test_every_feature_pair_comes_from_the_abstraction_table(self) -> None:
        abstract_pairs = self.vocabulary.abstract_pairs()
        abstract_attributes = self.vocabulary.abstract_attributes()
        for payload in ALL_PRODUCTS:
            raw_features = {
                normalize_text(item) for item in payload["features"]  # type: ignore[union-attr]
            }
            for pair in gist_for_target(payload, self.vocabulary):
                with self.subTest(pair=pair):
                    # No pair carries a raw catalog feature string in either half.
                    self.assertNotIn(pair.value, raw_features)
                    self.assertNotIn(pair.attribute, raw_features)
                    if pair.attribute in abstract_attributes:
                        self.assertIn((pair.attribute, pair.value), abstract_pairs)

    def test_a_product_below_the_floor_yields_an_empty_gist(self) -> None:
        self.assertEqual(gist_for_target(BELOW_FLOOR, self.vocabulary), ())

    def test_an_empty_gist_produces_an_empty_payload(self) -> None:
        self.assertEqual(prompt_payload_strings(()), ())


class DataFlowTest(unittest.TestCase):
    """MEAS-12's core claim, in the three clauses 02-VALIDATION.md states."""

    def setUp(self) -> None:
        self.vocabulary = load_vocabulary()

    def test_clause_one_every_pair_is_drawn_from_the_closed_vocabulary(self) -> None:
        # Nothing outside the committed vocabulary can reach prompt_payload_strings,
        # so a one-off catalog phrase cannot enter the payload by any route.
        self.assertEqual(self.vocabulary.df_floor, _GIST_DF_FLOOR)
        for payload in ALL_PRODUCTS:
            for pair in gist_for_target(payload, self.vocabulary):
                with self.subTest(parent_asin=payload["parent_asin"], pair=pair):
                    self.assertTrue(
                        self.vocabulary.admits(pair.attribute, pair.value),
                        f"{pair} escaped the closed vocabulary",
                    )

    def test_clause_two_no_feature_pair_is_a_verbatim_catalog_span(self) -> None:
        abstract_attributes = self.vocabulary.abstract_attributes()
        for payload in ALL_PRODUCTS:
            with self.subTest(parent_asin=payload["parent_asin"]):
                pairs = gist_for_target(payload, self.vocabulary)
                self.assertEqual(
                    span_violations(pairs, payload, abstract_attributes),
                    (),
                )

    def test_clause_two_actually_inspects_feature_pairs(self) -> None:
        # Without this the clause above could pass vacuously on a product set that
        # happens to produce no feature pairs at all.
        abstract_attributes = self.vocabulary.abstract_attributes()
        inspected = [
            pair
            for payload in ALL_PRODUCTS
            for pair in gist_for_target(payload, self.vocabulary)
            if pair.attribute in abstract_attributes
        ]
        self.assertGreaterEqual(len(inspected), 5, inspected)

    def test_clause_three_payload_is_structural_and_deterministic(self) -> None:
        for payload in ALL_PRODUCTS:
            with self.subTest(parent_asin=payload["parent_asin"]):
                first = prompt_payload_strings(
                    gist_for_target(payload, self.vocabulary)
                )
                second = prompt_payload_strings(
                    gist_for_target(payload, self.vocabulary)
                )
                self.assertEqual(first, second)
                for item in first:
                    self.assertEqual(item.count("="), 1, item)


class GateFiresTest(unittest.TestCase):
    """The negative half: each check is shown to report the violation it claims to."""

    def setUp(self) -> None:
        self.vocabulary = load_vocabulary()

    def test_a_vocabulary_admitting_raw_boilerplate_is_reported(self) -> None:
        # An identity "abstraction" -- the catalog string mapped to itself. This is
        # exactly what a DF floor alone would admit for `feature`, and clause 2 must
        # catch it rather than wave it through.
        poisoned = GistVocabulary(
            schema_version=GIST_SCHEMA_VERSION,
            df_floor=_GIST_DF_FLOOR,
            feature_abstraction_df_floor=100,
            catalog_sha256="0" * 64,
            values=(("feature", ("rubber sole",)),),
            abstractions=(("rubber sole", ("feature", "rubber sole")),),
        )
        poisoned.validate()
        pairs = gist_for_target(BOILERPLATE_TEE, poisoned)
        self.assertIn(GistPair(attribute="feature", value="rubber sole"), pairs)
        violations = span_violations(
            pairs, BOILERPLATE_TEE, poisoned.abstract_attributes()
        )
        self.assertIn("value feature=rubber sole", violations)

    def test_the_production_vocabulary_reports_nothing_on_the_same_product(self) -> None:
        pairs = gist_for_target(BOILERPLATE_TEE, self.vocabulary)
        self.assertFalse(
            span_violations(
                pairs, BOILERPLATE_TEE, self.vocabulary.abstract_attributes()
            )
        )

    def test_an_echoing_abstraction_row_is_reported(self) -> None:
        # The illustrative mapping research suggested, and the reason it was not
        # used: both halves echo the source value.
        echoing = abstraction_echoes(
            (
                {
                    "value": "rubber sole",
                    "attribute": "sole_material",
                    "token": "rubber",
                    "document_frequency": 5616,
                },
            )
        )
        self.assertIn("token rubber echoes rubber sole", echoing)

    def test_the_committed_abstraction_table_has_no_echoes(self) -> None:
        rows = tuple(
            json.loads(FEATURE_ABSTRACTIONS_PATH.read_text(encoding="utf-8"))[
                "abstractions"
            ]
        )
        self.assertGreaterEqual(len(rows), 80)
        self.assertEqual(abstraction_echoes(rows), ())

    def test_the_committed_table_and_the_loader_agree_on_the_admitted_rows(self) -> None:
        rows = json.loads(FEATURE_ABSTRACTIONS_PATH.read_text(encoding="utf-8"))[
            "abstractions"
        ]
        admitted = [row for row in rows if row["token"] is not None]
        self.assertEqual(len(load_feature_abstractions()), len(admitted))


class _StubIndex:
    """Stands in for CatalogIndex. build_vocabulary calls value_counts and nothing else."""

    def __init__(self, counts: dict[str, dict[str, int]]) -> None:
        self._counts = counts

    def value_counts(self, attribute: str) -> dict[str, int]:
        return dict(self._counts.get(str(attribute), {}))


class BuildVocabularyFloorTest(unittest.TestCase):
    """Measures the DF floor directly, in both directions.

    The extraction tests above show that a below-floor product produces no gist, but
    that alone would still pass if the floor were deleted and the exclusion were
    coming from somewhere else. These assert against a stub index whose counts are
    known, so removing `count >= _GIST_DF_FLOOR` from build_vocabulary turns them red.
    """

    def setUp(self) -> None:
        self.abstractions = load_feature_abstractions()
        self.counts = {
            "material": {
                "leather": 4818,
                "atfloor": _GIST_DF_FLOOR,
                "belowfloor": _GIST_DF_FLOOR - 1,
                "oneoff": 1,
            },
            "color": {"black": 440, "iridescent aubergine": 1},
            "size": {"medium": 90, "teacup": 2},
            "style": {"classic": 91, "whimsical": 3},
            # Present, high-frequency, and verbatim catalog boilerplate. It must not
            # reach the vocabulary by the DF path, because for `feature` the floor is
            # not the admission rule (L-6, D-52).
            "feature": {"rubber sole": 5616, "imported": 13832},
        }
        self.vocabulary = build_vocabulary(
            _StubIndex(self.counts),  # type: ignore[arg-type]
            catalog_sha256="1" * 64,
            abstractions=self.abstractions,
        )
        self.admitted = dict(self.vocabulary.values)

    def test_a_value_at_the_floor_is_admitted(self) -> None:
        self.assertIn("atfloor", self.admitted["material"])

    def test_a_value_one_below_the_floor_is_excluded(self) -> None:
        # Two-sided: the value is demonstrably present in the source counts, and
        # demonstrably absent from the vocabulary the floor produced.
        self.assertIn("belowfloor", self.counts["material"])
        self.assertNotIn("belowfloor", self.admitted["material"])
        self.assertNotIn("oneoff", self.admitted["material"])
        self.assertFalse(self.vocabulary.admits("material", "belowfloor"))

    def test_every_below_floor_value_across_all_attributes_is_excluded(self) -> None:
        for attribute in ("material", "color", "size", "style"):
            for value, count in self.counts[attribute].items():
                with self.subTest(attribute=attribute, value=value, count=count):
                    self.assertEqual(
                        value in self.admitted[attribute],
                        count >= _GIST_DF_FLOOR,
                    )

    def test_feature_admits_nothing_from_the_document_frequency_path(self) -> None:
        self.assertIn("rubber sole", self.counts["feature"])
        self.assertNotIn("rubber sole", self.admitted["feature"])
        self.assertNotIn("imported", self.admitted["feature"])
        self.assertEqual(
            self.admitted["feature"],
            tuple(sorted({token for _, (_, token) in self.abstractions})),
        )

    def test_admitted_values_are_ordered_by_descending_document_frequency(self) -> None:
        # value_counts returns an unsorted dict (L-17); an explicit key is what makes
        # the committed asset byte-reproducible.
        self.assertEqual(self.admitted["material"], ("leather", "atfloor"))


class ScopingCompanionTest(unittest.TestCase):
    """Pins clause 2's scope from the other side, so it cannot be quietly widened."""

    def test_widening_clause_two_to_all_attributes_would_fire(self) -> None:
        vocabulary = load_vocabulary()
        pairs = gist_for_target(LEATHER_BOOT, vocabulary)
        # The positive case: D-32 admits this DF-gated canonical value verbatim.
        self.assertIn(GistPair(attribute="material", value="leather"), pairs)
        # Production scope reports nothing, because the span check is feature-only.
        self.assertFalse(
            span_violations(pairs, LEATHER_BOOT, vocabulary.abstract_attributes())
        )
        # The same check widened to every attribute reports the canonical pair. A
        # future reader who "strengthens" clause 2 turns this test red instead of
        # turning MEAS-12 permanently red.
        widened = span_violations(
            pairs, LEATHER_BOOT, frozenset(pair.attribute for pair in pairs)
        )
        self.assertIn("value material=leather", widened)


# Assembled from fragments rather than written out, because this module is itself
# gated by a grep that forbids the literal spelling of either name anywhere in the
# file -- that grep is what keeps "no test touches the 580 MB database" checkable
# by eye as well as by AST.
_FORBIDDEN_MODULE = "local" + "_search_" + "backend"
_FORBIDDEN_PATH_FRAGMENT = "catalog" + "." + "artifacts"


def database_references(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if _FORBIDDEN_MODULE in alias.name
            )
        elif isinstance(node, ast.ImportFrom):
            if _FORBIDDEN_MODULE in (node.module or ""):
                found.append(f"line {node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A pure import walk would miss an artifact path opened as data.
            if (
                _FORBIDDEN_MODULE in node.value
                or _FORBIDDEN_PATH_FRAGMENT in node.value
            ):
                found.append(f"line {node.lineno}: string constant")
    return tuple(sorted(found))


class CatalogFreedomTest(unittest.TestCase):
    def test_this_module_reaches_no_database(self) -> None:
        self.assertEqual(database_references(Path(__file__)), ())

    def test_the_scanner_fires_on_a_backend_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                f"import starter.shopping_agent.{_FORBIDDEN_MODULE}\n",
                encoding="utf-8",
            )
            self.assertNotEqual(database_references(probe), ())

    def test_the_scanner_fires_on_an_artifact_path_constant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                f'PATH = "data/{_FORBIDDEN_PATH_FRAGMENT}/db"\n',
                encoding="utf-8",
            )
            self.assertNotEqual(database_references(probe), ())

    def test_the_scanner_passes_a_clean_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text("import json\n\nvalue = json.dumps({})\n", encoding="utf-8")
            self.assertEqual(database_references(probe), ())


if __name__ == "__main__":
    unittest.main()
