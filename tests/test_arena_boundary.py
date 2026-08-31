from __future__ import annotations

import ast
import hashlib
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

# SHA-256 of evaluator/local_evaluator.py (13,836 bytes) over the working-tree
# bytes this repository checks out. Pinned during planning at HEAD b98ff27 and
# re-verified at 46a93be. Re-pinning is a deliberate act, never a convenience.
EVALUATOR_SHA256 = "84ea899707452de249ca62abee77c4b40ab7a3139b5cc798ac30c9f521f91b30"

BRIDGE_EXPORTS = (
    "behavior_for",
    "catalog_index",
    "classify_constraint",
    "evaluate",
    "intent_card",
    "load_jsonl",
    "materialize_hidden_fields",
    "searchable_text",
)

_BRIDGE_MODULE_NAME = "evaluator_bridge.py"

# The exemption is anchored to this one repository-relative path, never to the
# basename. Under rglob a basename comparison would silently exempt a second,
# entirely unguarded arena/datasets/evaluator_bridge.py (L-1).
_BRIDGE_RELATIVE_PATH = Path("arena") / _BRIDGE_MODULE_NAME


def arena_modules(root: Path) -> list[Path]:
    # rglob, not glob: the scan predates arena/datasets/ and a non-recursive
    # glob would leave every module in it unguarded. Takes a root so the live
    # scan and the TemporaryDirectory proofs below share one implementation --
    # a second copy could drift back to glob without failing anything.
    return [
        path
        for path in sorted((root / "arena").rglob("*.py"))
        if "__pycache__" not in path.parts
        and path.relative_to(root) != _BRIDGE_RELATIVE_PATH
    ]


def evaluator_references(path: Path) -> tuple[str, ...]:
    # Takes a path instead of hard-coding arena/ so ScannerTest can prove the
    # detector actually fires, on files written into a TemporaryDirectory. The
    # alternative -- editing a live arena module and reverting it -- would be
    # unrunnable in CI, invisible to a later reader, and unsafe while sibling
    # plans in the same wave run this suite against the same working tree.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "evaluator":
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] == "evaluator" or (
                node.level and "evaluator" in module.split(".")
            ):
                dots = "." * node.level
                found.append(f"line {node.lineno}: from {dots}{module} import ...")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # An import walk alone misses importlib.import_module("evaluator...")
            # and __import__("evaluator..."), because the module name reaches the
            # interpreter as data. Scanning string constants closes both holes.
            if node.value.split(".")[0] == "evaluator":
                found.append(f"line {node.lineno}: string constant {node.value!r}")
    return tuple(sorted(found))


class ScannerTest(unittest.TestCase):
    def _scan(self, source: str) -> tuple[str, ...]:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(source, encoding="utf-8")
            return evaluator_references(probe)

    def test_scan_detects_static_import(self) -> None:
        references = self._scan("import evaluator.local_evaluator\n")
        self.assertNotEqual(references, ())

    def test_scan_detects_dynamic_import(self) -> None:
        # Proves the ast.Constant arm works; a pure import walk passes this file.
        references = self._scan(
            "import importlib\n"
            "\n"
            "module = importlib.import_module(\"evaluator.local_evaluator\")\n"
        )
        self.assertNotEqual(references, ())

    def test_scan_passes_a_clean_module(self) -> None:
        references = self._scan("import json\n\nvalue = json.dumps({})\n")
        self.assertEqual(references, ())

    def test_scan_reaches_a_nested_module(self) -> None:
        # The positive half of the L-1 fix: collection must descend into
        # arena/datasets/, and the detector must still fire on what it finds.
        # Asserts on the nested path itself, not merely on a non-empty list --
        # reverting rglob to glob has to fail this, and a length check would not.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "arena" / "datasets"
            nested.mkdir(parents=True)
            probe = nested / "probe.py"
            probe.write_text("import evaluator.local_evaluator\n", encoding="utf-8")
            collected = arena_modules(root)
            self.assertIn(probe, collected)
            self.assertNotEqual(evaluator_references(probe), ())

    def test_a_nested_bridge_named_module_is_not_exempt(self) -> None:
        # The negative half: only arena/evaluator_bridge.py is exempt, by path.
        # A nested file sharing the basename stays fully guarded.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "arena" / "datasets"
            nested.mkdir(parents=True)
            top_level_bridge = root / "arena" / _BRIDGE_MODULE_NAME
            top_level_bridge.write_text(
                "import evaluator.local_evaluator\n", encoding="utf-8"
            )
            nested_bridge = nested / _BRIDGE_MODULE_NAME
            nested_bridge.write_text(
                "import evaluator.local_evaluator\n", encoding="utf-8"
            )
            collected = arena_modules(root)
            self.assertIn(nested_bridge, collected)
            self.assertNotIn(top_level_bridge, collected)


class ArenaImportBoundaryTest(unittest.TestCase):
    def _non_bridge_modules(self) -> list[Path]:
        return arena_modules(REPOSITORY_ROOT)

    def test_only_the_bridge_module_references_the_evaluator(self) -> None:
        # Keyed by repository-relative path, not basename: the scan is recursive,
        # so arena/x.py and arena/datasets/x.py would otherwise collide and one
        # offender would silently overwrite the other in the failure message.
        offenders: dict[str, tuple[str, ...]] = {}
        for path in self._non_bridge_modules():
            references = evaluator_references(path)
            if references:
                offenders[path.relative_to(REPOSITORY_ROOT).as_posix()] = references
        self.assertEqual(
            offenders,
            {},
            "D-08/MEAS-15 breach: arena/evaluator_bridge.py is the only module in "
            f"arena/ permitted to reference the evaluator package. Offenders: {offenders}",
        )

    def test_bridge_surface_is_exactly_the_declared_names(self) -> None:
        # Parsed rather than imported, so the surface assertion still holds when
        # the evaluator itself is unimportable.
        bridge = REPOSITORY_ROOT / "arena" / _BRIDGE_MODULE_NAME
        tree = ast.parse(bridge.read_text(encoding="utf-8"), filename=str(bridge))
        seams = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module != "__future__"
        ]
        self.assertEqual(
            len(seams),
            1,
            "the seam must be exactly one from-import of the evaluator",
        )
        self.assertEqual(seams[0].module, "evaluator.local_evaluator")
        self.assertEqual(
            sorted(alias.name for alias in seams[0].names),
            list(BRIDGE_EXPORTS),
            "a ninth name through the seam breaks 'evaluate() as an opaque function'",
        )
        self.assertEqual(
            [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)],
            [],
            "the seam must stay a pure re-export",
        )
        self.assertEqual(
            [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ],
            [],
            "the seam must stay a pure re-export",
        )

    def test_arena_package_has_modules_to_scan(self) -> None:
        modules = [
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in self._non_bridge_modules()
        ]
        self.assertGreaterEqual(
            len(modules),
            1,
            "the boundary scan would pass vacuously on an arena package holding "
            f"nothing but the bridge; found {modules}",
        )
        # Asserted against the real tree, not just a TemporaryDirectory: without
        # this the recursion could regress to glob and every ScannerTest proof
        # would still pass while arena/datasets/ went unguarded in practice.
        self.assertTrue(
            any(name.startswith("arena/datasets/") for name in modules),
            "the recursive scan reaches nothing under arena/datasets/; the "
            f"subpackage is unguarded. Collected: {modules}",
        )

    def test_analyze_public_does_not_reach_the_evaluator(self) -> None:
        # Plan 01-04 imports code_revision from this module. Without this guard a
        # future change there would breach D-08 transitively, invisible to a scan
        # restricted to arena/.
        module = REPOSITORY_ROOT / "experiments" / "analyze_public.py"
        self.assertEqual(evaluator_references(module), ())


class EvaluatorIntegrityTest(unittest.TestCase):
    def test_evaluator_is_byte_unmodified(self) -> None:
        # read_bytes, never read_text: a line-ending change is a modification.
        path = REPOSITORY_ROOT / "evaluator" / "local_evaluator.py"
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            EVALUATOR_SHA256,
            "evaluator/local_evaluator.py is immutable by hard invariant -- any "
            "result reported against a modified evaluator is invalid. If the "
            "organizers published a legitimate update, or this checkout normalizes "
            "line endings differently, re-pin EVALUATOR_SHA256 deliberately and "
            "record why. Never edit the constant to make a local change pass.",
        )


if __name__ == "__main__":
    unittest.main()
