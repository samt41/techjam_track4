---
spike: 004
name: leakage-safe-finetune-data
type: standard
validates: "Given untouched public/gap targets, when synthetic relevance pairs are built, then no held-out or cross-split product leaks and queries require semantic matching"
verdict: VALIDATED
related: [002b, 003, 005, 006]
tags: [reranker, finetuning, data, leakage]
---

# Spike 004: Leakage-Safe Fine-Tuning Data

## What This Validates

Build useful query/positive/hard-negative groups without contaminating the 200
public or 177 semantic-gap sessions used to select MiniLM-L6.

## Research

Current SentenceTransformers documentation trains cross-encoders from
`datasets.Dataset` rows and maps text-pair labels in `[0, 1]` to
`BinaryCrossEntropyLoss`. Its reranking evaluator accepts grouped query,
positive, and negative documents and reports MRR/NDCG/MAP.

- <https://www.sbert.net/docs/cross_encoder/training_overview.html>
- <https://www.sbert.net/docs/cross_encoder/loss_overview.html>
- <https://www.sbert.net/docs/package_reference/cross_encoder/trainer.html>

| Approach | Pros | Cons | Status |
|----------|------|------|--------|
| Copy titles/features into queries | Large and easy | Trivial lexical leakage | Rejected |
| Random catalog negatives | Cheap and usually correct | Too easy; unlike top-100 reranking | Rejected |
| Calibration paraphrases + same-category lexical neighbors | Semantic, difficult, deployment-shaped | Some false-negative risk | Chosen |

Training uses only `split=calibration` paraphrases. Test mappings and every
public/gap target product are reserved. All remaining product IDs are assigned
to train or validation before mining, so negatives cannot cross partitions.

## How to Run

```bash
python -m experiments.reranking.build_finetune_dataset \
  --output experiments/reranking/training-data/calibration-v1 \
  --train-groups-per-mapping 100 \
  --validation-groups-per-mapping 25 \
  --negatives-per-group 3
```

## What to Expect

A deterministic JSONL pair dataset, grouped reranking validation data, manifest
hashes, and an audit that fails closed on any held-out or cross-split product.

## Investigation Trail

- Rejected using public/gap rows as labels because the gap set is derived from
  the public benchmark.
- Reused the existing calibration/test paraphrase boundary as a concept split.
- Selected product-disjoint hashing before negative mining.
- The first full build exposed a false raw-text match spanning adjacent feature
  values (`... buckle` + `closure ...`). Anchor validation now uses the exact
  serving document and skips evidence absent from that representation.

## Results

VALIDATED. The audited dataset contains 1,500 balanced query groups: 4,800
training pair rows over 3,707 unique products and 1,200 validation rows over 945
unique products. Each of the 12 calibration mappings contributes exactly 100
train and 25 validation groups. Independent set intersections found zero
train/validation overlap and zero public/gap target IDs in either split.

The manifest records catalog, mapping, public, gap, train, and validation
SHA-256 hashes. Mining skipped 91 candidate attempts that lacked three valid
hard negatives and one boundary-only raw-text surface match; all quotas were
still met. Raw rows remain generated/ignored artifacts.
