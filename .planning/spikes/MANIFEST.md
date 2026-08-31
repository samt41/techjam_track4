# Spike Manifest

## Idea

Test whether compact and larger pretrained cross-encoders can improve product
ordering after the current deterministic shopping retriever, without weakening
hard constraints or committing an ML dependency to the default runtime.

## Requirements

- The experiment must remain off by default and preserve the ordinary agent.
- Hard requirements, exclusions, and symbolic dialogue state remain authoritative.
- Ground truth may be joined only after agent execution for analysis.
- Compare MiniLM-L4, MiniLM-L6, and BGE reranker-base.
- Measure paired recommendation outcomes and actual local latency.
- Establish candidate-pool oracle coverage before interpreting model results.

## Spikes

| # | Name | Type | Validates | Verdict | Tags |
|---|------|------|-----------|---------|------|
| 001 | candidate-pool-oracle | standard | Given deterministic retrieval, when pools grow from 10 to 200, then target coverage reveals the rerankable ceiling | VALIDATED | retrieval, oracle |
| 002a | minilm-l4 | comparison | Given eligible candidates, when L4 reranks them, then paired rank gains exceed regressions within the latency budget | INCONCLUSIVE | reranker, minilm |
| 002b | minilm-l6 | comparison | Given the same candidates, when L6 reranks them, then its extra depth improves the quality/cost tradeoff | VALIDATED | reranker, minilm |
| 002c | bge-base | comparison | Given the same candidates, when the 300M BGE model reranks them, then added capacity produces material lift | INVALIDATED | reranker, bge |
| 003 | end-to-end-safety | standard | Given the best reranker, when all public and held-out sessions run, then score improves without hard-constraint or deterministic fallback regressions | VALIDATED | evaluation, safety |
