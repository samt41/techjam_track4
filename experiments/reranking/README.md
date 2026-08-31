# Cross-Encoder Recommendation Reranking Experiment

This experiment asks whether a second-stage text-ranking model improves the
ordered recommendation slate after the existing deterministic retriever and
hard eligibility gate have done their work. The feature is optional and off by
default; the base agent still imports no ML runtime.

## Compared configurations

- `oracle`: returns the unchanged top ten while recording candidate pools up to
  rank 200. This establishes the maximum recall a reranker could possibly reach.
- `minilm-l4`: `cross-encoder/ms-marco-MiniLM-L4-v2`.
- `minilm-l6`: `cross-encoder/ms-marco-MiniLM-L6-v2`.
- `bge-base`: `BAAI/bge-reranker-base`, included as a larger capacity probe.

Model rows score `(symbolic shopping intent, compact product document)` pairs.
They combine cross-encoder rank with the existing belief rank using reciprocal
rank fusion. Hard filters and exclusions run before the model and cannot be
overridden by it. Already-shown products remain behind unseen products.

## Research basis

Sentence Transformers documents cross-encoders as second-stage rerankers and
warns that domain fine-tuning can be important. Its official training guide
also identifies hard-negative quality as a central factor:

- <https://www.sbert.net/docs/cross_encoder/training_overview.html>
- <https://www.sbert.net/docs/cross_encoder/usage/efficiency.html>

The MiniLM family provides a useful size/quality ladder. L4 is 19.2M parameters
and L6 is 22.7M. The official MS MARCO numbers show a meaningful L4-to-L6 gain
but effectively no L6-to-L12 gain. BGE-base is approximately 300M parameters
and has a 1.11 GB FP32 weight artifact, so it is an upper-bound experiment rather
than the expected deployment choice.

## Run

Install the optional experiment stack:

```bash
uv sync --extra semantic-experiment
```

Run the unchanged oracle first:

```bash
python -m experiments.reranking.run_configuration \
  --configuration oracle-200 \
  --pool-size 200 \
  --output experiments/reranking/runs/oracle-200.json
```

Run a model configuration, for example:

```bash
python -m experiments.reranking.run_configuration \
  --configuration minilm-l6-rrf1 \
  --model minilm-l6 \
  --pool-size 100 \
  --fusion-weight 1.0 \
  --device cpu \
  --output experiments/reranking/runs/minilm-l6-rrf1.json
```

Generate the paired report:

```bash
python -m experiments.reranking.analyze_matrix \
  experiments/reranking/runs/oracle-200.json \
  experiments/reranking/runs/minilm-l4-rrf1.json \
  experiments/reranking/runs/minilm-l6-rrf1.json \
  experiments/reranking/runs/bge-base-rrf1.json
```

Generated JSON results and downloaded models remain ignored. The compact
Markdown report is retained at `experiments/reranking/RESULTS.md`.

## Result

MiniLM-L6 is the best next-step model. At pool 100 with equal-weight RRF it
raised the public technical score from 0.7688 to 0.7800 and the semantic-gap
score from 0.5481 to 0.5920. Its public rerank latency on M1 MPS was 340 ms mean,
499 ms p50, and 684 ms p95.

MiniLM-L4 was faster and improved Hit@10, but regressed public MRR enough to
trail L6 on combined score. BGE-base reached the best public score (0.7860), but
trailed L6 on the gap set (0.5759) and cost 4.0 seconds mean / 9.1 seconds p95
per public rerank on M1 MPS. That is not a material capacity win.

The candidate oracle found public target coverage of 0.920 at rank 10, 0.960 at
rank 50, and 0.970 at ranks 100 and 200. Pool 100 therefore captures all public
headroom observed in this experiment; pool 200 adds no public coverage.

See `RESULTS.md` for the complete aggregate and paired comparison.

## Fine-tuning direction

Do not train an encoder from scratch. Start from MiniLM-L6 (and optionally BGE
on the RTX 5090) and fine-tune a cross-encoder on query, positive product, and
hard-negative product triples. Mine hard negatives from the deterministic
ranker's high-ranked false positives, split by product/session before mining,
and retain this zero-shot matrix as the comparison baseline. Data quality and
leakage control are the likely constraints; a 32 GB RTX 5090 is sufficient for
parameter-efficient or full fine-tuning of these candidates.

## Adoption gate

A model is worth further tuning only if it produces a positive paired MRR or
technical-score change without losing Hit@10, violating hard eligibility, or
making per-turn latency operationally unreasonable. A positive generic
benchmark reputation is not sufficient.
