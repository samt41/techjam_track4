# Semantic Retrieval over 200 Public Sessions

**Run date:** 2026-08-30
**Mode:** Shadow replay; production responses and recommendations unchanged
**Dataset:** All 200 rows of `data/public_set.jsonl`
**Catalog:** All 50,000 products and 31,327 derived concepts

## Method

The ordinary public evaluator ran against the unchanged agent. A transparent
wrapper captured each user message and returned the base response object without
mutation. Ground-truth products were joined only after evaluation completed.

A captured turn received retrieval labels only when the message explicitly
contained the complete surface form or an approved alias of a concept attached
to its target product. This yielded 324 labeled turns across all 200 sessions
from 669 captured turns. The resulting test is a catalog-scale regression and
latency benchmark. It is deliberately not described as open-vocabulary evidence,
because the public simulator mostly copies catalog wording.

The unchanged public evaluation reproduced the retained result exactly:

- HitRate@10: `0.92`
- MRR: `0.524466`
- MTTC: `3.425`
- Recommended technical score: `0.76884`

## Retrieval results

| System | Explicit concept R@1 | R@5 | R@10 | MRR | Target posting R@10 | Session target coverage@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Lexical control | 0.401 | 0.660 | 0.815 | 0.516 | 0.830 | 0.915 |
| Arctic-S | 0.475 | 0.778 | 0.852 | 0.602 | 0.852 | 0.980 |
| BGE-small | **0.534** | **0.815** | **0.904** | **0.658** | **0.907** | **0.985** |
| Arctic-XS | 0.438 | 0.765 | 0.858 | 0.571 | 0.858 | **0.985** |
| MiniLM-L6 | 0.441 | 0.793 | 0.880 | 0.587 | 0.886 | 0.975 |

`Explicit concept` requires retrieving one of the exact target-product concepts
present in the message. `Target posting` is looser: any retrieved concept whose
posting list contains the target product counts.

## Paired comparison with lexical Recall@5

| Encoder | Gained turns | Lost turns | Net turns | Recall delta | 95% paired session-bootstrap CI |
| --- | ---: | ---: | ---: | ---: | ---: |
| Arctic-S | 53 | 15 | +38 | +0.117 | +0.075 to +0.161 |
| BGE-small | 80 | 30 | +50 | **+0.154** | **+0.095 to +0.209** |
| Arctic-XS | 58 | 24 | +34 | +0.105 | +0.054 to +0.158 |
| MiniLM-L6 | 63 | 20 | +43 | +0.133 | +0.082 to +0.184 |

All intervals resample complete sessions rather than treating multiple turns
from one session as independent. Every encoder has positive aggregate lift, but
every encoder also loses turns that lexical retrieval gets right. Dense search
therefore cannot replace lexical matching; it must remain a fallback or
lower-authority fused route.

## CPU timings

The measurements used warm local model files, batch size 128, normalized
384-dimensional embeddings, and exact matrix search.

| Encoder | Encode 62,654 concept views | Query ms/labeled turn | Exact search over all turns |
| --- | ---: | ---: | ---: |
| Arctic-S | 64.91 s | 3.89 ms | 6.01 s |
| BGE-small | 64.08 s | 3.13 ms | 6.34 s |
| Arctic-XS | 34.24 s | 2.10 ms | 6.43 s |
| MiniLM-L6 | 35.01 s | **1.70 ms** | 6.49 s |

Catalog encoding is an offline artifact-build cost. The query measurement is a
batched replay, not single-turn p95 runtime, so it should not be used as the
production latency claim.

## Decision

The public-session benchmark supports continuing the experiment with
`BAAI/bge-small-en-v1.5` as the quality candidate and MiniLM-L6 as the low-cost
comparison. It does not authorize production integration yet:

1. the benchmark contains lexical catalog wording rather than held-out
   paraphrases;
2. semantic output did not affect recommendation order in this shadow run;
3. the smoke probe showed BGE and MiniLM can follow an opposite phrase to the
   forbidden concept; and
4. no calibrated abstention or contrast policy has been applied.

The next decision-bearing experiment is a calibrated hybrid ablation: retain
lexical results, add only accepted dense fallback concepts, and run both the
unchanged public set and a sealed paraphrase/contrast set.
