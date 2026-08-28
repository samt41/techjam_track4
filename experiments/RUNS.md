# Retained Evaluation Runs

Only the best run for each meaningful implementation class is retained. Generated run directories are local artifacts and are not committed.

| Class | HitRate@10 | MRR | MTTC | TechnicalScore | Runtime | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Organizer BM25 baseline | 0.125 | 0.068034 | 9.81 | 0.10671 | not recorded | Frozen reference |
| Strict multi-route | 0.315 | 0.149054 | 7.98 | 0.262616 | 106.275 s | Superseded by rotation |
| Slate rotation | 0.71 | 0.259663 | 5.71 | 0.538699 | 156.745 s | Superseded by clarification |
| Information-gain clarification | 0.785 | 0.38656 | 4.43 | 0.639868 | 185.261 s | Accuracy reference |
| Unconditional counterfactual | 0.77 | 0.452417 | 4.875 | 0.643225 | 323.590 s | Rejected: small score gain, slower, lower hit rate |
| Gated sparse-pool counterfactual | 0.785 | 0.38656 | 4.43 | 0.639868 | 185.492 s | Retained: sparse-pool safety with no metric regression |

## Constraints and failures

- The catalog contains 112 em-dash prices and five `from N` display prices; these normalize to unknown to avoid false hard-budget decisions.
- Exact catalog phrase matching is precomputed. Per-value regex compilation made the evaluator exceed two minutes before completing.
- Intent-override remains the weakest public scenario at HitRate@10 0.2 and requires further diagnostic analysis.
- Counterfactual routes run only when strict eligibility yields fewer than the requested slate size. Explicit exclusions are never relaxed.
- Two final-schema runs had identical canonical summaries, all 200 session outcomes, and all 843 ordered slates. Runtime differed (185.492 s and 126.485 s).
