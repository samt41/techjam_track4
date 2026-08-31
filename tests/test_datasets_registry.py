"""Freeze enforcement, name allow-listing, and the corpus-shape invariants.

Every case writes into a `tempfile.TemporaryDirectory()`. Nothing here touches
the real `data/` tree and nothing opens a product catalog: the corpus-shape
checks read record dicts, and the D-34 substitution case is proved on two
hand-written products from `tests/dataset_fixtures.py`.

The sweeps over the REAL committed corpora are appended to this module by later
plans, once those artifacts exist: MEAS-10 scenario mix over the committed
corpora, MEAS-11 pairing over `data/probe.v1.jsonl`, MEAS-13's three-arm subset,
and the D-56/D-58 baseline-record check. That last one covers FOUR corpora, not
five -- D-45's and D-48's "five" predates D-46's consolidation of the probe's
three arms into one file, and D-58 corrects it. Those cases are deliberately
absent rather than present-and-inert, because a gate that passes by not running
is not a gate.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arena.datasets import divergence, registry
from arena.datasets.registry import (
    DatasetEntry,
    RegistryError,
    check_cross_check_subset,
    check_pairing,
    check_scenario_mix,
    describe_corpus,
    divergence_from_summary,
    load_registry,
    load_target_snapshot,
    publish_corpus,
    render_markdown,
    resolve_corpus_path,
    resolve_dataset,
    target_snapshot_path,
    upsert_entry,
    validate_dataset_name,
    write_registry,
    write_target_snapshot,
)
from arena.datasets.schema import CORPUS_SCHEMA_VERSION, write_corpus
from arena.evaluator_bridge import searchable_text
from arena.store import sha256_file
from tests.dataset_fixtures import (
    matched_pair,
    pair_id,
    product,
    sample_row,
    synthetic_corpus,
    three_arm_pair,
)


_CORPUS_NAME = "probe.v1"
_TARGET_TEXT = "a soft cotton knit pullover"

# Built from real DivergenceReports through the real aggregator, so the registry's
# table shape stays pinned to the one plan 02-05 actually emits rather than to a
# hand-written imitation of it.
_REPORTS = (
    divergence.measure_text("soft cotton knit throughout", _TARGET_TEXT),
    divergence.measure_text("machine washable and quick drying", _TARGET_TEXT),
)
_DIVERGENCE = divergence_from_summary(divergence.bucket_summary(_REPORTS))


def _records(rows: tuple[object, ...]) -> tuple[dict, ...]:
    return tuple(row.as_record() for row in rows)  # type: ignore[attr-defined]


def _entry(**overrides: object) -> DatasetEntry:
    values: dict[str, object] = {
        "name": _CORPUS_NAME,
        "path": "data/probe.v1.jsonl",
        "sha256": "0" * 64,
        "schema_version": CORPUS_SCHEMA_VERSION,
        "session_count": 4,
        "distinct_target_count": 2,
        "scenario_mix": (
            ("boundary", 0),
            ("browsing", 2),
            ("buying", 2),
            ("intent_override", 0),
        ),
        "generator_model_alias": "sonnet",
        "generator_model_resolved": "claude-sonnet-4-5-20250929",
        "claude_cli_version": "2.0.14",
        "prompt_pack": (("authoring.md", "b" * 64),),
        "seed": 7,
        "code_revision": "deadbeefcafe",
        "code_revision_dirty": False,
        "frozen_commit": "0123456789abcdef",
        "response_log_path": "data/responses/probe.v1.jsonl",
        "response_log_sha256": "1" * 64,
        "call_count": 12,
        "cost_usd": 0.4213,
        "divergence": _DIVERGENCE,
        "divergence_log_path": "data/divergence.probe.v1.jsonl",
        "divergence_log_sha256": "2" * 64,
        "divergence_pair_count": 8,
        "target_snapshot_path": "data/targets.probe.v1.json",
        "target_snapshot_sha256": "3" * 64,
        "target_snapshot_count": 2,
    }
    values.update(overrides)
    return DatasetEntry(**values)  # type: ignore[arg-type]


def _entry_for(corpus: Path, *, name: str = _CORPUS_NAME, **overrides: object) -> DatasetEntry:
    from arena.datasets.schema import load_corpus

    shape = describe_corpus(load_corpus(corpus))
    return _entry(
        name=name,
        path=str(corpus),
        sha256=sha256_file(corpus),
        session_count=shape["session_count"],
        distinct_target_count=shape["distinct_target_count"],
        scenario_mix=shape["scenario_mix"],
        **overrides,
    )


class NameGateTest(unittest.TestCase):
    def test_accepts_the_three_phase_corpus_names(self) -> None:
        for name in ("probe.v1", "expanded_dev.v1", "expanded_confirm.v1"):
            self.assertEqual(validate_dataset_name(name), name)

    def test_refuses_every_unsafe_or_unversioned_name(self) -> None:
        # Eight refusals against three accepts above: a name becomes a filename
        # (T-02-03), and an unversioned one would let a regenerated corpus land on
        # the bytes an earlier measurement was taken against (D-43).
        for name in (
            "../evil",
            "/abs",
            "C:\\evil.v1",
            "probe",
            "Probe.v1",
            "probe.v1.jsonl",
            "probe.v1:ads",
            "",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_dataset_name(name)

    def test_containment_refuses_an_escaping_path(self) -> None:
        # Called directly, because the regex above already makes an escape
        # unreachable through resolve_corpus_path. The check is defence in depth for
        # the day the allow-list is widened, and a guard nobody can trip is a guard
        # nobody can trust -- so it is tripped here on a crafted root.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inside = registry._ensure_contained(root / "probe.v1.jsonl", root, "probe.v1")
            self.assertEqual(inside, (root / "probe.v1.jsonl").resolve())
            with self.assertRaises(RegistryError):
                registry._ensure_contained(root / ".." / "evil.jsonl", root, "evil")

    def test_resolve_corpus_path_appends_the_jsonl_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                resolve_corpus_path(_CORPUS_NAME, root=root),
                (root / "probe.v1.jsonl").resolve(),
            )
        with self.assertRaises(ValueError):
            resolve_corpus_path("probe")

    def test_target_snapshot_path_is_versioned_with_its_corpus(self) -> None:
        self.assertEqual(
            target_snapshot_path(_CORPUS_NAME).as_posix(),
            "data/targets.probe.v1.json",
        )
        with self.assertRaises(ValueError):
            target_snapshot_path("probe")


class PublishTest(unittest.TestCase):
    def test_publish_writes_canonical_bytes_and_leaves_no_staging(self) -> None:
        rows = synthetic_corpus(20, cross_check_count=5)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = publish_corpus(rows, name=_CORPUS_NAME, root=root)
            expected = root / "expected.jsonl"
            write_corpus(expected, rows)
            self.assertEqual(destination.read_bytes(), expected.read_bytes())
            # A surviving `.probe.v1-xxxx` staging directory would be committed and
            # then mistaken for a record (the T-01-19 shape).
            self.assertEqual(
                [path.name for path in root.iterdir() if path.is_dir()], []
            )

    def test_publish_refuses_an_existing_destination(self) -> None:
        rows = synthetic_corpus(20, cross_check_count=5)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = publish_corpus(rows, name=_CORPUS_NAME, root=root)
            with self.assertRaises(FileExistsError) as caught:
                publish_corpus(rows, name=_CORPUS_NAME, root=root)
            self.assertIn(str(destination), str(caught.exception))

    def test_publish_refuses_a_corpus_carrying_a_foreign_stem(self) -> None:
        # The staged bytes are validated before they become frozen: a mis-namespaced
        # pair id would otherwise be committed and then inner-join against the corpus
        # that really owns the stem (D-45).
        rows = synthetic_corpus(20, cross_check_count=5, corpus_stem="expanded_dev_v1")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                publish_corpus(rows, name=_CORPUS_NAME, root=root)
            self.assertFalse((root / "probe.v1.jsonl").exists())


class FreezeTest(unittest.TestCase):
    def test_resolution_returns_the_corpus_when_the_digest_agrees(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = publish_corpus(
                synthetic_corpus(20, cross_check_count=5),
                name=_CORPUS_NAME,
                root=root,
            )
            registry_path = root / "datasets.json"
            write_registry(registry_path, (_entry_for(corpus),))
            self.assertEqual(
                resolve_dataset(
                    _CORPUS_NAME, registry_path=registry_path, root=root
                ),
                corpus.resolve(),
            )

    def test_resolution_refuses_a_drifted_corpus(self) -> None:
        # The whole point of MEAS-12: a digest nothing re-checks describes the past.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = publish_corpus(
                synthetic_corpus(20, cross_check_count=5),
                name=_CORPUS_NAME,
                root=root,
            )
            entry = _entry_for(corpus)
            registry_path = root / "datasets.json"
            write_registry(registry_path, (entry,))
            with corpus.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            observed = sha256_file(corpus)
            self.assertNotEqual(observed, entry.sha256)
            with self.assertRaises(RegistryError) as caught:
                resolve_dataset(_CORPUS_NAME, registry_path=registry_path, root=root)
            message = str(caught.exception)
            self.assertIn(entry.sha256, message)
            self.assertIn(observed, message)

    def test_resolution_refuses_a_registered_corpus_that_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = publish_corpus(
                synthetic_corpus(20, cross_check_count=5),
                name=_CORPUS_NAME,
                root=root,
            )
            registry_path = root / "datasets.json"
            write_registry(registry_path, (_entry_for(corpus),))
            corpus.unlink()
            with self.assertRaises(RegistryError) as caught:
                resolve_dataset(_CORPUS_NAME, registry_path=registry_path, root=root)
            self.assertIn(_CORPUS_NAME, str(caught.exception))

    def test_a_non_registry_value_falls_back_to_a_filesystem_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = publish_corpus(
                synthetic_corpus(20, cross_check_count=5),
                name=_CORPUS_NAME,
                root=root,
            )
            registry_path = root / "datasets.json"
            write_registry(registry_path, (_entry_for(corpus),))
            self.assertEqual(
                resolve_dataset(
                    str(corpus), registry_path=registry_path, root=root
                ),
                corpus,
            )
            with self.assertRaises(ValueError) as caught:
                resolve_dataset(
                    str(root / "absent.jsonl"),
                    registry_path=registry_path,
                    root=root,
                )
            self.assertIn("dataset does not exist", str(caught.exception))


class RegistryRoundTripTest(unittest.TestCase):
    def test_round_trip_preserves_every_field_and_sorts_by_name(self) -> None:
        entries = (
            _entry(name="probe.v1"),
            _entry(name="expanded_dev.v1", path="data/expanded_dev.v1.jsonl"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "datasets.json"
            write_registry(path, entries)
            loaded = load_registry(path)
            self.assertEqual(
                [entry.name for entry in loaded],
                ["expanded_dev.v1", "probe.v1"],
            )
            self.assertEqual(set(loaded), set(entries))

    def test_a_second_write_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "datasets.json"
            write_registry(path, (_entry(),))
            first = path.read_bytes()
            write_registry(path, (_entry(),))
            self.assertEqual(path.read_bytes(), first)

    def test_a_duplicate_name_is_refused_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "datasets.json"
            write_registry(path, (_entry(),))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["datasets"].append(dict(payload["datasets"][0]))
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RegistryError) as caught:
                load_registry(path)
            self.assertIn(_CORPUS_NAME, str(caught.exception))

    def test_an_unknown_registry_schema_version_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "datasets.json"
            write_registry(path, (_entry(),))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["schema_version"] = 2
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RegistryError):
                load_registry(path)

    def test_an_invalid_entry_is_refused_with_its_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "datasets.json"
            write_registry(path, (_entry(),))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["datasets"][0]["sha256"] = "not-a-digest"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RegistryError):
                load_registry(path)

    def test_upsert_refuses_a_refreeze_unless_it_is_asked_for(self) -> None:
        original = _entry()
        refrozen = _entry(sha256="4" * 64)
        with self.assertRaises(RegistryError) as caught:
            upsert_entry((original,), refrozen)
        self.assertIn("allow_refreeze", str(caught.exception))
        replaced = upsert_entry((original,), refrozen, allow_refreeze=True)
        self.assertEqual(replaced, (refrozen,))

    def test_upsert_appends_a_new_name_in_sorted_order(self) -> None:
        probe = _entry()
        expanded = _entry(name="expanded_dev.v1", path="data/expanded_dev.v1.jsonl")
        self.assertEqual(
            [entry.name for entry in upsert_entry((probe,), expanded)],
            ["expanded_dev.v1", "probe.v1"],
        )

    def test_the_public_entry_is_admitted_without_a_version_suffix(self) -> None:
        # The organizer set predates D-43 and carries no generator, no divergence
        # log and no snapshot; its provenance fields say where it came from.
        public = _entry(
            name="public",
            path="data/public_set.jsonl",
            generator_model_alias="organizer",
            generator_model_resolved="organizer-supplied",
            prompt_pack=(),
            seed=0,
            response_log_path="",
            response_log_sha256="",
            call_count=0,
            cost_usd=0.0,
            divergence=(),
            divergence_log_path="",
            divergence_log_sha256="",
            divergence_pair_count=0,
            target_snapshot_path="",
            target_snapshot_sha256="",
            target_snapshot_count=0,
        )
        public.validate()
        with self.assertRaises(ValueError):
            _entry(name="expanded").validate()


class ScenarioMixTest(unittest.TestCase):
    def test_the_synthetic_corpus_holds_the_official_mix(self) -> None:
        check_scenario_mix(_records(synthetic_corpus(20, cross_check_count=5)))

    def test_a_skewed_corpus_is_refused_with_both_proportions(self) -> None:
        rows = []
        for index in range(8):
            rows.extend(matched_pair(pair_id(index), scenario_type="buying"))
        for index in range(8, 10):
            rows.extend(matched_pair(pair_id(index), scenario_type="browsing"))
        with self.assertRaises(RegistryError) as caught:
            check_scenario_mix(_records(tuple(rows)))
        message = str(caught.exception)
        self.assertIn("buying", message)
        self.assertIn("0.8000", message)
        self.assertIn("0.4000", message)

    def test_an_empty_corpus_is_refused_rather_than_divided_by_zero(self) -> None:
        with self.assertRaises(RegistryError):
            check_scenario_mix(())


class PairingTest(unittest.TestCase):
    def _pair(self, index: int, **kwargs: object) -> tuple[dict, ...]:
        return _records(matched_pair(pair_id(index), **kwargs))

    def test_matched_pairs_pass(self) -> None:
        check_pairing(self._pair(0) + self._pair(1))

    def test_a_probe_row_without_a_control_partner_is_refused(self) -> None:
        orphan = sample_row(pair_id(1), arm="probe_sonnet").as_record()
        with self.assertRaises(RegistryError) as caught:
            check_pairing(self._pair(0) + (orphan,))
        self.assertIn("control", str(caught.exception))

    def test_a_pair_whose_arms_target_different_products_is_refused(self) -> None:
        control = sample_row(
            pair_id(0), arm="control", parent_asin="B000000001"
        ).as_record()
        probe = sample_row(
            pair_id(0), arm="probe_sonnet", parent_asin="B000000002"
        ).as_record()
        with self.assertRaises(RegistryError) as caught:
            check_pairing((control, probe))
        self.assertIn("B000000002", str(caught.exception))

    def test_a_single_arm_pair_is_refused(self) -> None:
        lonely = sample_row(pair_id(1), arm="control").as_record()
        with self.assertRaises(RegistryError):
            check_pairing(self._pair(0) + (lonely,))

    def test_a_repeated_pair_id_and_arm_is_refused(self) -> None:
        control = sample_row(pair_id(0), arm="control").as_record()
        with self.assertRaises(RegistryError):
            check_pairing((control, dict(control)))

    def test_an_arm_outside_the_vocabulary_is_refused(self) -> None:
        rogue = sample_row(pair_id(0), arm="probe_sonnet").as_record()
        rogue["arm"] = "probe_opus"
        with self.assertRaises(RegistryError):
            check_pairing((sample_row(pair_id(0)).as_record(), rogue))


class CrossCheckSubsetTest(unittest.TestCase):
    def test_a_haiku_pair_that_also_carries_sonnet_passes(self) -> None:
        rows = _records(three_arm_pair(pair_id(0))) + _records(
            matched_pair(pair_id(1))
        )
        check_cross_check_subset(rows)

    def test_a_haiku_pair_without_a_sonnet_arm_is_refused(self) -> None:
        rows = (
            sample_row(pair_id(0), arm="control").as_record(),
            sample_row(pair_id(0), arm="probe_haiku").as_record(),
        )
        with self.assertRaises(RegistryError) as caught:
            check_cross_check_subset(rows)
        message = str(caught.exception)
        self.assertIn(pair_id(0), message)
        # Asserted on the subset branch's own words, not merely on the exception
        # type: a two-row pair ALSO trips the three-arm row-count branch below, so a
        # bare assertRaises here stays green even with the subset check removed.
        self.assertIn("subset of probe_sonnet", message)

    def test_a_three_arm_pair_carrying_a_fourth_row_is_refused(self) -> None:
        rows = _records(three_arm_pair(pair_id(0))) + (
            sample_row(pair_id(0), arm="control").as_record(),
        )
        with self.assertRaises(RegistryError):
            check_cross_check_subset(rows)

    def test_a_corpus_with_no_haiku_arm_passes_vacuously(self) -> None:
        # expanded_dev.v1 and expanded_confirm.v1 carry two arms, so the empty
        # subset must be legal rather than an error.
        check_cross_check_subset(_records(matched_pair(pair_id(0))))


class TargetSnapshotTest(unittest.TestCase):
    _TARGETS = (("B000000002", "red leather boot"), ("B000000001", _TARGET_TEXT))

    def _write(self, path: Path, **overrides: object) -> None:
        values: dict[str, object] = {
            "corpus_name": _CORPUS_NAME,
            "catalog_sha256": "a" * 64,
            "targets": self._TARGETS,
        }
        values.update(overrides)
        write_target_snapshot(path, **values)  # type: ignore[arg-type]

    def test_round_trip_returns_sorted_pairs_and_is_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.probe.v1.json"
            self._write(path)
            first = path.read_bytes()
            version, catalog, targets = load_target_snapshot(path)
            self.assertEqual(version, 1)
            self.assertEqual(catalog, "a" * 64)
            self.assertEqual(targets, tuple(sorted(self._TARGETS)))
            self._write(path, targets=tuple(sorted(self._TARGETS)))
            self.assertEqual(path.read_bytes(), first)

    def test_an_empty_or_duplicated_snapshot_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.probe.v1.json"
            with self.assertRaises(RegistryError):
                self._write(path, targets=())
            with self.assertRaises(RegistryError):
                self._write(
                    path,
                    targets=(("B000000001", "one"), ("B000000001", "two")),
                )
            with self.assertRaises(ValueError):
                self._write(path, targets=(("B000000001", ""),))
            self.assertFalse(path.exists())

    def test_an_unknown_snapshot_schema_version_is_refused_by_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.probe.v1.json"
            self._write(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["schema_version"] = 2
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RegistryError) as caught:
                load_target_snapshot(path)
            self.assertIn(str(path), str(caught.exception))

    def test_the_snapshot_substitutes_for_the_product_in_a_divergence_measure(
        self,
    ) -> None:
        # The substitution plan 02-11's sweep depends on: if these two disagree, a
        # catalog-free re-derivation is measuring something other than what the
        # committed log recorded.
        products = (
            product(
                "B000000001",
                title="Soft cotton knit pullover",
                features=("machine washable", "quick drying"),
            ),
            product(
                "B000000002",
                title="Red leather boot",
                features=("rubber sole", "waterproof"),
            ),
        )
        snapshot = {item["parent_asin"]: searchable_text(item) for item in products}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.probe.v1.json"
            self._write(path, targets=tuple(sorted(snapshot.items())))
            _, _, loaded = load_target_snapshot(path)
        recovered = dict(loaded)
        for item in products:
            for phrase in (
                "soft cotton knit throughout",
                "machine washable and quick drying",
                "I do not want to hand wash it",
            ):
                with self.subTest(asin=item["parent_asin"], phrase=phrase):
                    self.assertEqual(
                        divergence.measure_text(
                            phrase, recovered[str(item["parent_asin"])]
                        ),
                        divergence.measure(phrase, item),
                    )

    def test_an_artifact_recorded_without_its_digest_is_refused(self) -> None:
        # T-02-43: a named artifact with no pinned digest can drift from the corpus
        # it describes with nothing anywhere noticing.
        with self.assertRaises(ValueError):
            _entry(target_snapshot_sha256="").validate()
        with self.assertRaises(ValueError):
            _entry(target_snapshot_path="").validate()
        with self.assertRaises(ValueError):
            _entry(target_snapshot_count=0).validate()
        with self.assertRaises(ValueError):
            _entry(divergence_log_sha256="").validate()
        with self.assertRaises(ValueError):
            _entry(divergence_log_path="").validate()


class MarkdownViewTest(unittest.TestCase):
    def test_the_view_is_deterministic_and_names_every_corpus_and_bucket(self) -> None:
        entries = (
            _entry(name="probe.v1"),
            _entry(name="expanded_dev.v1", path="data/expanded_dev.v1.jsonl"),
        )
        rendered = render_markdown(entries)
        self.assertEqual(rendered, render_markdown(entries))
        self.assertEqual(rendered, render_markdown(tuple(reversed(entries))))
        for name in ("probe.v1", "expanded_dev.v1"):
            self.assertIn(f"`{name}`", rendered)
        for bucket, metrics in _DIVERGENCE:
            self.assertIn(f"| `{bucket}` | {dict(metrics)['n']} |", rendered)
        self.assertIn(registry.DIVERGENCE_PROSE, rendered)
        self.assertIn("never as one aggregate", rendered)
        self.assertIn("data/divergence.probe.v1.jsonl", rendered)

    def test_an_empty_divergence_table_renders_the_none_fallback(self) -> None:
        # An empty body would emit a header and separator with nothing under them,
        # which reads as a malformed table rather than as an honest "no rows".
        rendered = render_markdown((_entry(divergence=()),))
        self.assertIn("| _none_ | _none_ | _none_ | _none_ | _none_ | _none_ |", rendered)


if __name__ == "__main__":
    unittest.main()
