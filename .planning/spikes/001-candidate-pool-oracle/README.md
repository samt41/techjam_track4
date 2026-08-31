---
spike: 001
name: candidate-pool-oracle
type: standard
validates: "Given deterministic retrieval, when pools grow from 10 to 200, then target coverage reveals the rerankable ceiling"
verdict: VALIDATED
related: [002a, 002b, 002c]
tags: [retrieval, oracle, reranking]
---

# Spike 001: Candidate-Pool Oracle

## What This Validates

A reranker cannot recover a product absent from its input. Record the unchanged
eligible ordering through rank 200 and join targets only after evaluation.

## Research

Sentence Transformers' realistic reranking evaluator exposes the same concern
through `always_rerank_positives=False`: positives must actually be present in
the first-stage result set. This spike implements that realistic boundary.

## How to Run

See `experiments/reranking/README.md`.

## What to Expect

Coverage at cutoffs 10, 25, 50, 100, and 200, with the top-ten responses kept
identical to the deterministic baseline.

## Investigation Trail

- Baseline before integration: all 182 tests passed.
- Added an off-by-default reranker protocol after eligibility and belief ranking.
- Evaluated 200 public and 177 semantic-gap sessions without exposing targets to
  the agent.

## Results

VALIDATED. Public target coverage was 0.920 at rank 10, 0.935 at 25, 0.960
at 50, and 0.970 at both 100 and 200. Gap coverage was 0.684, 0.712, 0.751,
0.774, and 0.797 respectively. Pool 100 captures all observed public headroom;
rank 101--200 only adds four gap sessions.
