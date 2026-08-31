---
spike: 003
name: end-to-end-safety
type: standard
validates: "Given the best reranker, when all public and held-out sessions run, then score improves without hard-constraint or deterministic fallback regressions"
verdict: VALIDATED
related: [001, 002a, 002b, 002c]
tags: [evaluation, safety, fallback]
---

# Spike 003: End-to-End Safety

## What This Validates

Verify the optional integration preserves the deterministic agent when disabled
or when reranking fails, and measure the actual recommendation metrics when on.

## Research

Cross-encoder benchmark scores do not establish retail relevance. Adoption is
based on paired public and held-out recommendation outcomes.

## How to Run

Run the full unit suite and matrix commands in `experiments/reranking/README.md`.

## What to Expect

No hard-ineligible product can enter the pool, failures return the unchanged
baseline top ten, and reports expose gains as well as regressions.

## Investigation Trail

- Added integration tests for larger-pool invocation, close behavior, and
  failure fallback.
- Reproduced the exact public baseline while the recording oracle was enabled.
- Completed all three model rows with zero recorded reranker failures.

## Results

VALIDATED. The disabled path remains the original deterministic path, model
dependencies are experiment-only, and reranker exceptions fall back to the
unchanged top ten. Candidates are produced only after hard eligibility and the
implemented models only reorder that pool while preserving exact-match and
unseen-product groups. MiniLM-L6 improved both public and gap technical scores;
all full-dataset model runs reported zero failures.
