# Semantic Hybrid Recommendation Matrix

This is an end-to-end recommendation evaluation. `disabled` is the unchanged
lexical control. Hybrid rows add gated semantic candidates while retaining
the existing hard-filter and ranking path.

## Recommendation results

| Configuration | Public Hit@10 | Public MRR | Public MTTC | Public score | Δ score | Gap Hit@10 | Gap MRR | Gap MTTC | Gap score | Δ score | Contrast traps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| disabled | 0.9200 | 0.5245 | 3.425 | 0.7688 | +0.0000 | 0.6836 | 0.3267 | 5.588 | 0.5481 | +0.0000 | 0/6 accepted |
| hybrid-arctic-s | 0.9200 | 0.5279 | 3.435 | 0.7697 | +0.0008 | 0.6836 | 0.3295 | 5.588 | 0.5489 | +0.0008 | 0/6 accepted |
| hybrid-arctic-xs | 0.9200 | 0.5254 | 3.435 | 0.7689 | +0.0001 | 0.6836 | 0.3267 | 5.588 | 0.5481 | +0.0000 | 0/6 accepted |
| hybrid-bge-small | 0.9200 | 0.5245 | 3.435 | 0.7687 | -0.0002 | 0.6836 | 0.3257 | 5.588 | 0.5478 | -0.0003 | 0/6 accepted |
| hybrid-minilm-l6 | 0.9200 | 0.5245 | 3.425 | 0.7689 | +0.0000 | 0.6836 | 0.3267 | 5.588 | 0.5481 | +0.0000 | 0/6 accepted |

## Paired session changes

| Configuration | Public hits +/− | Public ranks ↑/↓ | Gap hits +/− | Gap ranks ↑/↓ | Public/Gap semantic accepts | Public/Gap p95 ms | Public/Gap run sec |
|---|---:|---:|---:|---:|---:|---:|---:|
| disabled | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0.0/0.0 | 303.3/445.4 |
| hybrid-arctic-s | 0/0 | 5/2 | 0/0 | 1/0 | 106/148 | 39.5/33.5 | 392.8/642.4 |
| hybrid-arctic-xs | 0/0 | 2/0 | 0/0 | 0/0 | 72/78 | 39.7/32.4 | 408.5/623.4 |
| hybrid-bge-small | 0/0 | 1/0 | 0/0 | 0/1 | 48/53 | 36.9/32.6 | 394.1/634.7 |
| hybrid-minilm-l6 | 0/0 | 3/2 | 0/0 | 0/0 | 70/73 | 38.0/32.4 | 405.7/630.3 |

A gained/lost hit means the target product entered/left the top ten versus
the same control session. Rank arrows count reciprocal-rank improvements
and regressions, including hit changes.

## Outcome

No hybrid configuration changed Hit@10 for any paired public or semantic-gap session.
The best semantic-gap composite result was `hybrid-arctic-s` at +0.0008 versus the disabled control.
Every encoder passed the held-out contrast gate.

**Recommendation: do not adopt the current hybrid implementation.** Arctic-S is the only row worth carrying into another iteration, but its rank-only lift is too small to justify the extra retrieval work.

## Limits of this result

The gap set contains only public sessions eligible for the checked-in test
paraphrases; it is not a general open-vocabulary benchmark. The held-out
contrast set is a small safety gate, not proof of broad negation safety.
Thresholds were frozen from the separate calibration split. Model inference
uses the offline Python experiment stack rather than a production ONNX path.
Concurrent runs can distort wall time, but not deterministic recommendation
order or paired outcome counts.
