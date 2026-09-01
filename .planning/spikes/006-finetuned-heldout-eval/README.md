---
spike: 006
name: finetuned-heldout-eval
type: standard
validates: "Given a validation-selected MiniLM-L6 checkpoint, when untouched public and semantic-gap sessions run, then it beats zero-shot without safety or latency regression"
verdict: PENDING
related: [002b, 003, 004, 005]
tags: [reranker, finetuning, evaluation, safety]
---

# Spike 006: Fine-Tuned Held-Out Evaluation

## What This Validates

The fine-tuned checkpoint must improve the real end-to-end shopping metrics,
not merely its synthetic validation objective.

## Research

PENDING before implementation.

## How to Run

PENDING.

## What to Expect

PENDING.

## Investigation Trail

- Public Hit@10 gate fixed at zero-shot L6's 0.940.
- Semantic-gap score must exceed zero-shot L6's 0.591950.

## Results

PENDING.
