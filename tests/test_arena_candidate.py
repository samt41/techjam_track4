from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from arena.candidate import (
    ALLOWED_OVERRIDES,
    CandidateSpec,
    candidate_overrides,
    code_revision_dirty,
    current_revision,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# Printed by a child interpreter so the fingerprint can be compared across two
# processes started with different PYTHONHASHSEED values. A hash()-based
# implementation differs between those children; a SHA-256 one cannot.
_FINGERPRINT_PROGRAM = (
    "from arena.candidate import CandidateSpec;"
    "print(CandidateSpec("
    "name='cross-process',"
    "code_revision='0' * 40,"
    "code_revision_dirty=False,"
    "overrides=(('artifact_path', 'x'), ('exploration', 'disabled')),"
    "catalog_sha256='a' * 64,"
    "dataset_sha256='b' * 64,"
    ").fingerprint)"
)


def _spec(**overrides: object) -> CandidateSpec:
    fields: dict[str, object] = {
        "name": "baseline",
        "code_revision": "0" * 40,
        "code_revision_dirty": False,
        "overrides": (("exploration", "disabled"),),
        "catalog_sha256": "a" * 64,
        "dataset_sha256": "b" * 64,
    }
    fields.update(overrides)
    return CandidateSpec(**fields)  # type: ignore[arg-type]


def _fingerprint_in_child(hash_seed: str) -> str:
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        (sys.executable, "-c", _FINGERPRINT_PROGRAM),
        capture_output=True,
        text=True,
        check=True,
        cwd=str(_REPOSITORY_ROOT),
        env=environment,
    )
    return result.stdout.strip()


class CandidateSpecValidationTest(unittest.TestCase):
    def test_allow_list_matches_the_shipped_constructor(self) -> None:
        self.assertEqual(
            ALLOWED_OVERRIDES,
            frozenset({"lexical_mode", "exploration", "artifact_path"}),
        )

    def test_every_allowed_override_key_validates(self) -> None:
        spec = _spec(
            overrides=(
                ("artifact_path", "data/catalog.artifacts"),
                ("exploration", "disabled"),
                ("lexical_mode", "auto"),
            ),
        )
        self.assertIsNone(spec.validate())

    def test_unknown_override_key_is_rejected(self) -> None:
        spec = _spec(overrides=(("belief_temperature", "1.0"),))
        with self.assertRaises(ValueError) as raised:
            spec.validate()
        self.assertIn("belief_temperature", str(raised.exception))

    def test_duplicate_override_key_is_rejected(self) -> None:
        spec = _spec(overrides=(("exploration", "disabled"), ("exploration", "enabled")))
        with self.assertRaises(ValueError) as raised:
            spec.validate()
        self.assertIn("duplicate", str(raised.exception))

    def test_override_values_are_validated(self) -> None:
        for overrides in (
            (("exploration", "aggressive"),),
            (("lexical_mode", "nonsense"),),
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError) as raised:
                    _spec(overrides=overrides).validate()
                self.assertIn("invalid value", str(raised.exception))

    def test_unsorted_override_keys_are_rejected(self) -> None:
        spec = _spec(overrides=(("exploration", "disabled"), ("artifact_path", "x")))
        with self.assertRaises(ValueError) as raised:
            spec.validate()
        self.assertIn("sorted key order", str(raised.exception))

    def test_empty_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _spec(name="").validate()

    def test_empty_code_revision_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _spec(code_revision="").validate()

    def test_malformed_digest_is_rejected(self) -> None:
        for field in ("catalog_sha256", "dataset_sha256"):
            for value in ("ZZZ", "a" * 63, "A" * 64, ""):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        _spec(**{field: value}).validate()

    def test_unknown_digest_literal_is_accepted(self) -> None:
        self.assertIsNone(
            _spec(catalog_sha256="unknown", dataset_sha256="unknown").validate()
        )

    def test_specification_is_hashable(self) -> None:
        self.assertEqual(len({_spec(), _spec()}), 1)

    def test_candidate_overrides_returns_sorted_pairs(self) -> None:
        self.assertEqual(
            candidate_overrides({"exploration": "disabled", "artifact_path": "x"}),
            (("artifact_path", "x"), ("exploration", "disabled")),
        )


class CandidateFingerprintTest(unittest.TestCase):
    def test_identical_inputs_produce_identical_fingerprint(self) -> None:
        self.assertEqual(_spec().fingerprint, _spec().fingerprint)

    def test_fingerprint_is_stable_across_processes(self) -> None:
        self.assertEqual(_fingerprint_in_child("0"), _fingerprint_in_child("1"))

    def test_fingerprint_changes_with_every_field(self) -> None:
        baseline = _spec()
        mutations: tuple[tuple[str, object], ...] = (
            ("name", "challenger"),
            ("code_revision", "1" * 40),
            ("code_revision_dirty", True),
            ("overrides", (("exploration", "enabled"),)),
            ("catalog_sha256", "c" * 64),
            ("dataset_sha256", "d" * 64),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                mutated = dataclasses.replace(baseline, **{field: value})
                self.assertNotEqual(baseline.fingerprint, mutated.fingerprint)

    def test_fingerprint_is_order_independent_for_the_same_configuration(self) -> None:
        first = _spec(
            overrides=candidate_overrides(
                {"exploration": "disabled", "artifact_path": "x"}
            ),
        )
        second = _spec(
            overrides=candidate_overrides(
                {"artifact_path": "x", "exploration": "disabled"}
            ),
        )
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_keyword_arguments_mirror_the_overrides(self) -> None:
        spec = _spec(overrides=(("artifact_path", "x"), ("exploration", "disabled")))
        self.assertEqual(spec.agent_kwargs(), dict(spec.overrides))

    def test_record_carries_every_field_and_the_fingerprint(self) -> None:
        spec = _spec()
        record = spec.as_record()
        self.assertEqual(
            sorted(record),
            [
                "catalog_sha256",
                "code_revision",
                "code_revision_dirty",
                "dataset_sha256",
                "fingerprint",
                "name",
                "overrides",
            ],
        )
        self.assertEqual(record["fingerprint"], spec.fingerprint)
        self.assertEqual(record["overrides"], {"exploration": "disabled"})


class RevisionCaptureTest(unittest.TestCase):
    def test_current_revision_returns_sha_and_dirty_flag(self) -> None:
        revision, dirty = current_revision()
        self.assertIsInstance(dirty, bool)
        if revision != "unknown_revision":
            self.assertEqual(len(revision), 40)
            self.assertTrue(set(revision) <= set("0123456789abcdef"))

    def test_dirty_flag_fails_closed(self) -> None:
        failures = (
            OSError("git is unavailable"),
            subprocess.CalledProcessError(128, ("git", "status", "--porcelain")),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch("arena.candidate.subprocess.run", side_effect=failure):
                    self.assertTrue(code_revision_dirty())


if __name__ == "__main__":
    unittest.main()
