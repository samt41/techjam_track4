from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.semantic.analyze_hybrid_matrix import build_matrix
from experiments.semantic.build_gap_dataset import ParaphraseMapping, _replace_one
from experiments.semantic.concepts import (
    concepts_from_database,
    inventory_sha256,
    stable_concept_id,
)
from experiments.semantic.metrics import retrieval_metrics
from experiments.semantic.hybrid_provider import HybridConfiguration
from experiments.semantic.probe import load_concepts, load_probe, validate_probe
from experiments.semantic.public_sessions import (
    CapturedTurn,
    PublicMessageCaptureAgent,
    PublicObservation,
    derive_public_observations,
    public_retrieval_metrics,
)
from experiments.semantic.schemas import (
    CatalogConcept,
    ConceptHit,
    ExpectedDisposition,
    ProbeCase,
    ProbeKind,
)
from experiments.semantic.search import dense_search, lexical_search
from starter.shopping_agent.models import Attribute
from tests.fixtures import build_test_artifacts, sample_products


def concept(attribute: Attribute, text: str, ordinal: int) -> CatalogConcept:
    source_kind = "structured_value"
    item = CatalogConcept(
        concept_id=stable_concept_id(attribute, None, text, source_kind),
        attribute=attribute,
        category_scope=None,
        surface_text=text,
        contextual_text=f"product {attribute.value}: {text}",
        document_frequency=1,
        source_kind=source_kind,
        product_ordinals=(ordinal,),
    )
    item.validate()
    return item


class SemanticConceptTest(unittest.TestCase):
    def test_inventory_is_stable_and_filters_singleton_features(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        _, artifact_path = build_test_artifacts(
            Path(temporary.name), sample_products()
        )
        database = artifact_path / "catalog.sqlite3"

        first = concepts_from_database(database)
        second = concepts_from_database(database)

        self.assertEqual(first, second)
        self.assertEqual(inventory_sha256(first), inventory_sha256(second))
        self.assertIn("leather", {item.surface_text for item in first})
        self.assertNotIn("warm lining", {item.surface_text for item in first})
        self.assertEqual(
            tuple(sorted(item.concept_id for item in first)),
            tuple(sorted({item.concept_id for item in first})),
        )


class SemanticHybridExperimentTest(unittest.TestCase):
    def test_gap_builder_replaces_only_one_testable_constraint(self) -> None:
        mapping = ParaphraseMapping(
            mapping_id="material-leather",
            split="test",
            attribute="material",
            surface_text="leather",
            paraphrase="made from animal hide",
        )

        replacement = _replace_one(
            {
                "target_category": "boots",
                "hard_constraints": ["leather", "black"],
                "soft_preferences": ["durable"],
            },
            {"leather": mapping},
        )

        self.assertIsNotNone(replacement)
        modified, selected, field, index = replacement
        self.assertEqual(modified["hard_constraints"], [
            "made from animal hide", "black"
        ])
        self.assertEqual(selected, mapping)
        self.assertEqual((field, index), ("hard_constraints", 0))

    def test_hybrid_configuration_rejects_invalid_gates(self) -> None:
        with self.assertRaisesRegex(ValueError, "cosine"):
            HybridConfiguration(minimum_score=1.1, minimum_margin=0.0).validate()
        with self.assertRaisesRegex(ValueError, "margin"):
            HybridConfiguration(minimum_score=0.8, minimum_margin=-0.1).validate()

    def test_matrix_reports_paired_gains_and_losses(self) -> None:
        def record(name: str, mode: str, ranks: tuple[float, float]) -> dict:
            sessions = [
                {
                    "sample_id": f"s{index}",
                    "hit": rank > 0,
                    "reciprocal_rank": rank,
                }
                for index, rank in enumerate(ranks)
            ]
            dataset = {
                "sample_count": 2,
                "hit_rate_at_10": sum(rank > 0 for rank in ranks) / 2,
                "mrr": sum(ranks) / 2,
                "mttc": 1.0,
                "recommended_technical_score": 0.5,
                "semantic": {
                    "accepted_count": 0,
                    "latency_ms_p95": 0.0,
                },
                "elapsed_seconds": 1.0,
                "sessions": sessions,
            }
            return {
                "configuration_name": name,
                "mode": mode,
                "model_name": None if mode == "disabled" else name,
                "hybrid_configuration": None,
                **{
                    field: "same"
                    for field in (
                        "catalog_sha256",
                        "public_dataset_sha256",
                        "gap_dataset_sha256",
                        "contrast_sha256",
                        "concept_sha256",
                        "calibration_sha256",
                    )
                },
                "public": dataset,
                "semantic_gap": dataset,
                "contrast_test": {
                    "accepted_count": 0,
                    "case_count": 1,
                    "passed": True,
                },
            }

        matrix = build_matrix((
            record("disabled", "disabled", (1.0, 0.0)),
            record("hybrid", "hybrid", (0.0, 0.5)),
        ))

        paired = matrix["rows"][1]["public"]["paired"]
        self.assertEqual(paired["gained_hit"], 1)
        self.assertEqual(paired["lost_hit"], 1)


class SemanticProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.warm = concept(Attribute.FEATURE, "insulated", 1)
        self.cool = concept(Attribute.FEATURE, "breathable", 2)
        self.concepts = (self.warm, self.cool)

    def test_probe_rejects_unknown_concept(self) -> None:
        case = ProbeCase(
            case_id="positive-1",
            split="test",
            clause="keeps heat in",
            kind=ProbeKind.POSITIVE,
            expected_disposition=ExpectedDisposition.RESOLVED_SOFT,
            acceptable_concept_ids=("missing",),
            forbidden_concept_ids=(),
            attribute_scope=Attribute.FEATURE,
        )
        with self.assertRaisesRegex(ValueError, "unknown concepts"):
            validate_probe((case,), self.concepts)

    def test_probe_rejects_positive_lexical_target_overlap(self) -> None:
        case = ProbeCase(
            case_id="positive-1",
            split="test",
            clause="insulated for winter",
            kind=ProbeKind.POSITIVE,
            expected_disposition=ExpectedDisposition.RESOLVED_SOFT,
            acceptable_concept_ids=(self.warm.concept_id,),
            forbidden_concept_ids=(),
            attribute_scope=Attribute.FEATURE,
        )
        with self.assertRaisesRegex(ValueError, "lexical target overlap"):
            validate_probe((case,), self.concepts)

    def test_jsonl_probe_loading_validates_schema(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "probe.jsonl"
        case = ProbeCase(
            case_id="positive-1",
            split="smoke",
            clause="keeps heat in",
            kind=ProbeKind.POSITIVE,
            expected_disposition=ExpectedDisposition.RESOLVED_SOFT,
            acceptable_concept_ids=(self.warm.concept_id,),
            forbidden_concept_ids=(),
            attribute_scope=Attribute.FEATURE,
        )
        path.write_text(json.dumps(case.as_record()) + "\n", encoding="utf-8")

        loaded = load_probe(path, self.concepts)

        self.assertEqual(loaded, (case,))

    def test_checked_in_smoke_probe_is_valid_open_vocabulary_data(self) -> None:
        root = Path(__file__).parents[1]
        probe_root = root / "experiments" / "semantic" / "probe" / "smoke"

        concepts = load_concepts(probe_root / "concepts.jsonl")
        cases = load_probe(probe_root / "cases.jsonl", concepts)

        self.assertEqual(len(concepts), 7)
        self.assertEqual(len(cases), 9)
        self.assertEqual(
            sum(case.kind is ProbeKind.POSITIVE for case in cases),
            7,
        )


class SemanticSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.warm = concept(Attribute.FEATURE, "insulated", 1)
        self.cool = concept(Attribute.FEATURE, "breathable", 2)
        self.concepts = (self.warm, self.cool)
        self.case = ProbeCase(
            case_id="positive-1",
            split="test",
            clause="keeps heat in",
            kind=ProbeKind.POSITIVE,
            expected_disposition=ExpectedDisposition.RESOLVED_SOFT,
            acceptable_concept_ids=(self.warm.concept_id,),
            forbidden_concept_ids=(self.cool.concept_id,),
            attribute_scope=Attribute.FEATURE,
        )

    def test_dense_search_uses_best_surface_or_contextual_view(self) -> None:
        hits = dense_search(
            (self.case,),
            self.concepts,
            query_vectors=((1.0, 0.0),),
            surface_vectors=((0.8, 0.2), (0.1, 0.9)),
            contextual_vectors=((1.0, 0.0), (0.0, 1.0)),
            top_k=2,
        )

        self.assertEqual(hits[self.case.case_id][0].concept_id, self.warm.concept_id)
        metrics = retrieval_metrics((self.case,), hits)
        self.assertEqual(metrics.recall_at_1, 1.0)
        self.assertEqual(metrics.recall_at_5, 1.0)

    def test_lexical_control_does_not_bridge_unseen_paraphrase(self) -> None:
        self.assertEqual(lexical_search(self.case, self.concepts), ())


class _CaptureBaseAgent:
    def __init__(self) -> None:
        self.response = {
            "message": "result",
            "ask_attribute": "feature",
            "recommendations": [],
        }

    def reset(self, session_id: str, user_profile: dict) -> None:
        return None

    def respond(
        self, session_id: str, user_message: str, turn: int, top_k: int
    ) -> dict:
        return self.response

    def close(self) -> None:
        return None


class PublicSessionSemanticTest(unittest.TestCase):
    def test_capture_wrapper_returns_the_exact_base_response_object(self) -> None:
        base = _CaptureBaseAgent()
        capture = PublicMessageCaptureAgent(base, ("public-1",))
        capture.reset("session-1", {})

        response = capture.respond("session-1", "warm enough", 1, 10)

        self.assertIs(response, base.response)
        self.assertEqual(capture.turns[0].sample_id, "public-1")
        capture.respond("session-1", "keeps heat in", 2, 10)
        self.assertIs(capture.turns[1].attribute_scope, Attribute.FEATURE)

    def test_public_labels_are_target_concepts_explicit_in_the_message(self) -> None:
        warm = concept(Attribute.FEATURE, "insulated", 0)
        cool = concept(Attribute.FEATURE, "breathable", 1)
        captured = (CapturedTurn(
            sample_id="public-1",
            turn=1,
            user_message="A key requirement is insulated",
            attribute_scope=Attribute.FEATURE,
            response_sha256="0" * 64,
        ),)
        samples = [{
            "sample_id": "public-1",
            "scenario_type": "buying",
            "ground_truth": {"parent_asin": "TARGET"},
        }]

        observations = derive_public_observations(
            captured,
            samples,
            {"TARGET": 0},
            (warm, cool),
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(
            observations[0].case.acceptable_concept_ids,
            (warm.concept_id,),
        )

    def test_public_metrics_distinguish_explicit_and_posting_hits(self) -> None:
        warm = concept(Attribute.FEATURE, "insulated", 0)
        shared = CatalogConcept(
            concept_id="shared",
            attribute=Attribute.FEATURE,
            category_scope=None,
            surface_text="winter ready",
            contextual_text="product feature: winter ready",
            document_frequency=2,
            source_kind="structured_value",
            product_ordinals=(0, 1),
        )
        shared.validate()
        case = ProbeCase(
            case_id="public-1-turn-1",
            split="test",
            clause="insulated please",
            kind=ProbeKind.POSITIVE,
            expected_disposition=ExpectedDisposition.RESOLVED_SOFT,
            acceptable_concept_ids=(warm.concept_id,),
            forbidden_concept_ids=(),
            attribute_scope=Attribute.FEATURE,
        )
        observation = PublicObservation(case, "public-1", "buying", 0)
        self.assertEqual(
            PublicObservation.from_record(observation.as_record()),
            observation,
        )
        hits = {
            case.case_id: (
                ConceptHit("shared", 0.9, 1),
                ConceptHit(warm.concept_id, 0.8, 2),
            )
        }

        metrics = public_retrieval_metrics(
            (observation,), hits, (warm, shared)
        )

        self.assertEqual(metrics["explicit_concept_recall_at_1"], 0.0)
        self.assertEqual(metrics["explicit_concept_recall_at_5"], 1.0)
        self.assertEqual(metrics["target_posting_recall_at_1"], 1.0)


if __name__ == "__main__":
    unittest.main()
