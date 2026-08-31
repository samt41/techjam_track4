# Validated Spike Conventions

- Keep cross-encoder dependencies and model loading experiment-only and off by
  default.
- Apply hard filters and exclusions before neural reranking; models may reorder
  only eligible candidates.
- Join hidden targets only after agent execution for oracle and paired analysis.
- Use pool 100 as the current upper bound: it captures all observed public
  candidate coverage available at pool 200.
- Use MiniLM-L6 as the fine-tuning baseline. Treat BGE as an RTX-class research
  option, not the default runtime.
- Record dataset hashes, model identifier, device, pair counts, paired
  wins/losses, and p50/p95 latency for every adopted experiment row.
