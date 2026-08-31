from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path

from arena.datasets.schema import CorpusSchemaError, assert_authored_branch
from arena.evaluator_bridge import materialize_hidden_fields
from tests.dataset_fixtures import synthetic_corpus, violating_row


# Nothing here may reach the catalog. Branch 1 of `materialize_hidden_fields`
# returns at local_evaluator.py:206 before it touches `products`, so the whole
# sweep runs with an empty mapping and needs neither the 61 MB product file nor
# the 580 MB built artifact.
NO_PRODUCTS: dict[str, dict] = {}

FORBIDDEN_IMPORT_ROOTS = (
    "tests.fixtures",
    "starter.shopping_agent.local_search_backend",
)


class AuthoredBranchSweepTest(unittest.TestCase):
    def test_every_synthetic_row_takes_the_authored_branch(self) -> None:
        records = tuple(row.as_record() for row in synthetic_corpus())
        self.assertTrue(records, "the sweep would pass vacuously on an empty corpus")
        for record in records:
            with self.subTest(sample_id=record["sample_id"]):
                assert_authored_branch(record)

    def test_a_bare_row_fails_the_authored_branch_check(self) -> None:
        # The two-sided proof: the check measures which branch fired, not merely
        # the absence of an exception. A row carrying only the six shipped keys
        # takes branch 2 and regenerates its card from the target's catalog text.
        bare = violating_row("bare")
        self.assertNotIn("intent_card", bare)
        with self.assertRaises(CorpusSchemaError) as context:
            assert_authored_branch(bare)
        self.assertIn("fallback branch", str(context.exception))


class BranchIdentityTest(unittest.TestCase):
    def test_the_evaluator_returns_the_rows_own_objects(self) -> None:
        # Identity, never equality. An equal-but-not-identical card would satisfy
        # `==` even if branch 2 had synthesized it, so a future refactor of
        # assert_authored_branch from `is` to `==` has to fail here.
        record = synthetic_corpus()[0].as_record()
        equal_but_separate = copy.deepcopy(record["intent_card"])
        card, behavior = materialize_hidden_fields(record, NO_PRODUCTS)
        self.assertIs(card, record["intent_card"])
        self.assertIs(behavior, record["behavior"])
        self.assertEqual(card, equal_but_separate)
        self.assertIsNot(card, equal_but_separate)


def _comparison_ops(source: str, function_name: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Compare):
                    found.extend(type(op).__name__ for op in inner.ops)
    return tuple(found)


class IdentityComparisonGuardTest(unittest.TestCase):
    # `is` versus `==` cannot be distinguished behaviourally without a catalog:
    # branch 1 returns the row's own objects, so both operators agree on every
    # input reachable here, and branch 2 needs a real product to synthesize an
    # equal-looking card. The distinction is therefore guarded at the source, the
    # way tests/test_arena_boundary.py guards the evaluator seam.

    def test_the_authored_branch_check_compares_by_identity(self) -> None:
        schema_source = (
            Path(__file__).resolve().parent.parent
            / "arena"
            / "datasets"
            / "schema.py"
        ).read_text(encoding="utf-8")
        ops = _comparison_ops(schema_source, "assert_authored_branch")
        self.assertIn(
            "IsNot",
            ops,
            "identity is what proves branch 1 fired; equality would also pass if "
            "branch 2 happened to synthesize an equal card",
        )
        self.assertNotIn("Eq", ops)
        self.assertNotIn("NotEq", ops)

    def test_the_guard_fires_on_an_equality_comparison(self) -> None:
        # The negative half, on a synthetic source rather than by editing the live
        # module: without this the assertion above would pass on a function that
        # contained no comparison at all.
        ops = _comparison_ops(
            "def assert_authored_branch(record):\n"
            "    card = record['intent_card']\n"
            "    if card != record['intent_card']:\n"
            "        raise ValueError('no')\n",
            "assert_authored_branch",
        )
        self.assertIn("NotEq", ops)
        self.assertNotIn("IsNot", ops)


class CatalogIndependenceTest(unittest.TestCase):
    def test_this_module_imports_nothing_catalog_side(self) -> None:
        # Asserted by scanning this module's own imports rather than by trusting
        # the import block above to stay clean: the sweep's catalog-free property
        # is a sign-off item, and an added import is exactly how it would be lost.
        path = Path(__file__).resolve()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = sorted(
            name
            for name in imported
            for root in FORBIDDEN_IMPORT_ROOTS
            if name == root or name.startswith(f"{root}.")
        )
        self.assertEqual(
            offenders,
            [],
            "the D-37 sweep must stay runnable without a built artifact; "
            f"offending imports: {offenders}",
        )

    def test_the_scan_would_notice_a_catalog_import(self) -> None:
        # The negative half: prove the detector fires, otherwise the check above
        # would pass on any module at all, including one that does open a backend.
        offenders = [
            name
            for name in ("starter.shopping_agent.local_search_backend",)
            for root in FORBIDDEN_IMPORT_ROOTS
            if name == root or name.startswith(f"{root}.")
        ]
        self.assertNotEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
