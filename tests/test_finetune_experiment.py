from __future__ import annotations

import unittest

from experiments.reranking.build_finetune_dataset import (
    PairRow,
    audit_pair_rows,
    product_partition,
)


def row(
    *,
    query_id: str,
    product_id: str,
    positive_product_id: str,
    label: float,
    partition: str,
    mapping_id: str = "cal-wool-1",
    document: str | None = None,
) -> PairRow:
    return PairRow(
        query_id=query_id,
        query="shopping request; prefer material: warm animal fleece",
        document=(
            document
            if document is not None
            else (
                "title: wool coat"
                if label == 1.0
                else f"title: synthetic coat {product_id}"
            )
        ),
        label=label,
        product_id=product_id,
        positive_product_id=positive_product_id,
        mapping_id=mapping_id,
        surface_text="wool",
        paraphrase="warm animal fleece",
        partition=partition,
        retrieval_rank=0 if label == 1.0 else 1,
    )


def valid_rows(partition: str, prefix: str) -> list[PairRow]:
    positive = f"{prefix}-positive"
    return [
        row(
            query_id=f"{prefix}-query",
            product_id=positive,
            positive_product_id=positive,
            label=1.0,
            partition=partition,
        ),
        row(
            query_id=f"{prefix}-query",
            product_id=f"{prefix}-negative-1",
            positive_product_id=positive,
            label=0.0,
            partition=partition,
        ),
        row(
            query_id=f"{prefix}-query",
            product_id=f"{prefix}-negative-2",
            positive_product_id=positive,
            label=0.0,
            partition=partition,
        ),
    ]


class FineTuneDatasetAuditTest(unittest.TestCase):
    def audit(self, train, validation, heldout=frozenset()):
        return audit_pair_rows(
            train,
            validation,
            heldout_ids=heldout,
            allowed_mapping_ids=frozenset({"cal-wool-1"}),
            minimum_negatives=2,
        )

    def test_valid_product_disjoint_groups_pass(self) -> None:
        result = self.audit(valid_rows("train", "t"), valid_rows("validation", "v"))

        self.assertEqual(result["group_count"], 2)
        self.assertEqual(result["negative_count"], 4)

    def test_heldout_product_is_rejected_in_any_role(self) -> None:
        train = valid_rows("train", "t")
        train[1] = row(
            query_id="t-query",
            product_id="HELDOUT",
            positive_product_id="t-positive",
            label=0.0,
            partition="train",
        )

        with self.assertRaisesRegex(ValueError, "held-out products"):
            self.audit(train, valid_rows("validation", "v"), frozenset({"HELDOUT"}))

    def test_product_cannot_cross_train_and_validation(self) -> None:
        validation = valid_rows("validation", "v")
        validation[1] = row(
            query_id="v-query",
            product_id="t-negative-1",
            positive_product_id="v-positive",
            label=0.0,
            partition="validation",
        )

        with self.assertRaisesRegex(ValueError, "cross train/validation"):
            self.audit(valid_rows("train", "t"), validation)

    def test_reserved_test_mapping_is_rejected(self) -> None:
        train = valid_rows("train", "t")
        train[0] = row(
            query_id="t-query",
            product_id="t-positive",
            positive_product_id="t-positive",
            label=1.0,
            partition="train",
            mapping_id="test-leather",
        )

        with self.assertRaisesRegex(ValueError, "reserved mapping"):
            self.audit(train, valid_rows("validation", "v"))

    def test_query_paraphrase_cannot_be_copied_into_positive(self) -> None:
        train = valid_rows("train", "t")
        train[0] = row(
            query_id="t-query",
            product_id="t-positive",
            positive_product_id="t-positive",
            label=1.0,
            partition="train",
            document="title: wool coat made from warm animal fleece",
        )

        with self.assertRaisesRegex(ValueError, "copies the paraphrase"):
            self.audit(train, valid_rows("validation", "v"))

    def test_partition_is_stable_and_seeded(self) -> None:
        first = product_partition("P1", seed=7, validation_fraction=0.2)
        second = product_partition("P1", seed=7, validation_fraction=0.2)

        self.assertEqual(first, second)
        self.assertIn(first, {"train", "validation"})


if __name__ == "__main__":
    unittest.main()
