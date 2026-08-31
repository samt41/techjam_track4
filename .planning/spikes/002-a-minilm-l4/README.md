---
spike: 002a
name: minilm-l4
type: comparison
validates: "Given eligible candidates, when L4 reranks them, then paired rank gains exceed regressions within the latency budget"
verdict: INCONCLUSIVE
related: [001, 002b, 002c]
tags: [reranker, minilm, cpu]
---

# Spike 002a: MiniLM-L4

## What This Validates

Test the 19.2M-parameter, 76.7 MB efficiency candidate on the real shopping
pipeline rather than relying on MS MARCO metrics.

## Research

The official model card reports MRR@10 37.70 and higher reference throughput
than L6, though its published speed is measured on a V100 rather than this CPU.

## How to Run

See `experiments/reranking/README.md`.

## What to Expect

Paired Hit@10 and reciprocal-rank gains/losses, plus p50/p95 model latency.

## Investigation Trail

- Selected as the likely deployment-efficiency candidate.
- Ran pool 100, max length 256, batch 32, and equal-weight RRF on M1 MPS.

## Results

INCONCLUSIVE as the deployment choice. Public Hit@10 improved 0.920 to 0.950
and score improved 0.7688 to 0.7776, but MRR regressed 0.5245 to 0.4845 with
59 rank improvements versus 74 regressions. The gap score improved 0.5481 to
0.5689. Public rerank latency was 242 ms mean, 338 ms p50, and 449 ms p95.
The model is useful, but L6 produced a better quality/cost result.
