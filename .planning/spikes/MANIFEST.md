# Spike Manifest

## Idea

Test whether pretrained and locally fine-tuned cross-encoders can improve
product ordering after the deterministic shopping retriever, without weakening
hard constraints, contaminating evaluation, or committing an ML dependency to
the default runtime.

## Requirements

- The experiment must remain off by default and preserve the ordinary agent.
- Hard requirements, exclusions, and symbolic dialogue state remain authoritative.
- Ground truth may be joined only after agent execution for analysis.
- Compare MiniLM-L4, MiniLM-L6, and BGE reranker-base.
- Measure paired recommendation outcomes and actual local latency.
- Establish candidate-pool oracle coverage before interpreting model results.
- Fine-tuning must exclude every public/gap target from all training and
  validation roles, including hard negatives.
- Training/validation use calibration paraphrases only; test paraphrases remain
  reserved for the semantic-gap evaluation.
- Product IDs are partitioned before negative mining and cannot cross splits.
- Fine-tuned adoption requires public Hit@10 at least 0.940 and semantic-gap
  technical score above 0.591950.

## Spikes

| # | Name | Type | Validates | Verdict | Tags |
|---|------|------|-----------|---------|------|
| 001 | candidate-pool-oracle | standard | Given deterministic retrieval, when pools grow from 10 to 200, then target coverage reveals the rerankable ceiling | VALIDATED | retrieval, oracle |
| 002a | minilm-l4 | comparison | Given eligible candidates, when L4 reranks them, then paired rank gains exceed regressions within the latency budget | INCONCLUSIVE | reranker, minilm |
| 002b | minilm-l6 | comparison | Given the same candidates, when L6 reranks them, then its extra depth improves the quality/cost tradeoff | VALIDATED | reranker, minilm |
| 002c | bge-base | comparison | Given the same candidates, when the 300M BGE model reranks them, then added capacity produces material lift | INVALIDATED | reranker, bge |
| 003 | end-to-end-safety | standard | Given the best reranker, when all public and held-out sessions run, then score improves without hard-constraint or deterministic fallback regressions | VALIDATED | evaluation, safety |
| 004 | leakage-safe-finetune-data | standard | Given untouched public/gap targets, when synthetic relevance pairs are built, then no held-out or cross-split product leaks and queries require semantic matching | VALIDATED | finetuning, data, leakage |
| 005 | minilm-l6-finetune | standard | Given audited synthetic relevance pairs, when MiniLM-L6 is fine-tuned with BCE, then product-disjoint validation ranking improves over zero-shot | PENDING | finetuning, minilm, training |
| 006 | finetuned-heldout-eval | standard | Given a validation-selected MiniLM-L6 checkpoint, when untouched public and semantic-gap sessions run, then it beats zero-shot without safety or latency regression | PENDING | finetuning, evaluation, safety |
