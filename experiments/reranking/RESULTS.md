# Cross-Encoder Recommendation Reranking Matrix

The oracle row records the unchanged deterministic top ten while exposing
larger candidate pools. Model rows RRF-fuse cross-encoder rank with the
existing belief rank after hard eligibility filtering.

## End-to-end recommendation results

| Configuration | Device | Public Hit@10 | Public MRR | Public score | Δ score | Gap Hit@10 | Gap MRR | Gap score | Δ score |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| oracle-200 | none | 0.9200 | 0.5245 | 0.7688 | +0.0000 | 0.6836 | 0.3267 | 0.5481 | +0.0000 |
| minilm-l4-rrf1 | mps:0 | 0.9500 | 0.4845 | 0.7776 | +0.0087 | 0.7062 | 0.3308 | 0.5689 | +0.0208 |
| minilm-l6-rrf1 | mps:0 | 0.9400 | 0.5035 | 0.7800 | +0.0112 | 0.7232 | 0.3807 | 0.5919 | +0.0439 |
| bge-base-rrf1 | mps:0 | 0.9450 | 0.5174 | 0.7860 | +0.0172 | 0.7119 | 0.3420 | 0.5759 | +0.0279 |

## Paired changes and cost

| Configuration | Public hits +/− | Public ranks ↑/↓ | Gap hits +/− | Gap ranks ↑/↓ | Pair count | p50/p95 ms | Public run sec |
|---|---:|---:|---:|---:|---:|---:|---:|
| oracle-200 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0.0/0.0 | 303.9 |
| minilm-l4-rrf1 | 6/0 | 59/74 | 5/1 | 47/44 | 34873 | 337.7/448.6 | 455.7 |
| minilm-l6-rrf1 | 6/2 | 60/62 | 8/1 | 58/33 | 34143 | 498.6/683.7 | 497.6 |
| bge-base-rrf1 | 6/1 | 67/63 | 8/3 | 54/44 | 34403 | 4387.2/9084.6 | 2854.4 |

## Candidate-pool oracle

This is the fraction of public sessions whose target appeared in the
deterministic eligible pool on at least one scoreable turn:

| Cutoff | 10 | 25 | 50 | 100 | 200 |
|---|---:|---:|---:|---:|---:|
| Coverage | 0.9200 | 0.9350 | 0.9600 | 0.9700 | 0.9700 |

The oracle is an upper bound only: a reranker cannot recover a target that
the first-stage candidate pool does not contain.
