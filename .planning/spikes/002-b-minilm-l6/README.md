---
spike: 002b
name: minilm-l6
type: comparison
validates: "Given the same candidates, when L6 reranks them, then its extra depth improves the quality/cost tradeoff"
verdict: VALIDATED
related: [001, 002a, 002c]
tags: [reranker, minilm, quality]
---

# Spike 002b: MiniLM-L6

## What This Validates

Test the 22.7M-parameter, 90.9 MB quality reference against L4 on identical
shopping evaluations.

## Research

The official model card reports MRR@10 39.01. L12 reports only 39.02 while being
larger and slower, so L6 is the sensible top of the compact comparison.

## How to Run

See `experiments/reranking/README.md`.

## What to Expect

The same paired metrics as L4, allowing a direct quality/cost decision.

## Investigation Trail

- Selected as the compact quality reference.
- Ran pool 100, max length 256, batch 32, and equal-weight RRF on M1 MPS.

## Results

VALIDATED. Public Hit@10 improved 0.920 to 0.940 and score improved 0.7688 to
0.7800. Gap Hit@10 improved 0.6836 to 0.7232, MRR improved 0.3267 to 0.3807,
and score improved 0.5481 to 0.5920. On the gap set it added eight hits while
losing one and produced 58 rank improvements versus 33 regressions. Public
rerank latency was 340 ms mean, 499 ms p50, and 684 ms p95. This is the
recommended model for tuning.
