---
spike: 002c
name: bge-base
type: comparison
validates: "Given the same candidates, when the 300M BGE model reranks them, then added capacity produces material lift"
verdict: INVALIDATED
related: [001, 002a, 002b]
tags: [reranker, bge, capacity]
---

# Spike 002c: BGE Reranker Base

## What This Validates

Determine whether roughly thirteen times the parameters of MiniLM-L6 buy enough
shopping-domain ranking quality to justify a 1.11 GB FP32 artifact and greater
latency.

## Research

BGE documents this encoder-only cross-encoder as a top-k reranker and provides
official fine-tuning support using query, positive, and hard-negative passages.

## How to Run

See `experiments/reranking/README.md`.

## What to Expect

A quality upper-bound row. It is not assumed to be deployable merely because it
outperforms a compact model.

## Investigation Trail

- Added at the user's request to test whether greater capacity matters.
- Ran pool 100, max length 256, batch 16, and equal-weight RRF on M1 MPS.

## Results

INVALIDATED. BGE reached the best public score, 0.7860, but the margin over L6
was only 0.0060. Its gap score was 0.5759, below L6's 0.5920, with the same
eight added hits but three lost hits. Public rerank latency was 3.95 seconds
mean, 4.39 seconds p50, and 9.08 seconds p95; the public run took 47.6 minutes,
5.7 times L6. Added capacity did not produce a material, robust lift.
