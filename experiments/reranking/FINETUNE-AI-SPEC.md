# AI-SPEC — MiniLM-L6 Shopping Reranker Fine-Tuning

> Experiment-level AI design contract. This repository has spike planning but
> no GSD roadmap phase, so the phase-oriented AI workflow is applied here
> without inventing a project phase.

## 1. System Classification

**System Type:** Hybrid information-retrieval ranking system

**Description:** Fine-tune `cross-encoder/ms-marco-MiniLM-L6-v2` to reorder an
eligible top-100 shopping candidate pool. Good means better held-out product
discovery and reciprocal rank without weakening deterministic constraints or
making the base agent depend on an ML runtime.

**Critical Failure Modes:**

1. Public or semantic-gap targets leak into training as positives or negatives.
2. Synthetic queries copy positive-document text and create a trivial task.
3. Noisy negatives are actually relevant, teaching the model the wrong order.
4. Aggregate gains hide lost hits, hard-eligibility failures, or severe latency.
5. Training is irreproducible or silently selects a worse checkpoint.

## 1b. Domain Context

**Industry Vertical:** E-commerce product search and recommendation

**User Population:** Shoppers expressing category, material, feature, style,
and budget constraints over multiple turns.

**Stakes Level:** Medium

**Output Consequence:** Poor ranking wastes user time and can suppress a suitable
product; violating an explicit exclusion or budget is unacceptable.

### What Domain Experts Evaluate Against

| Dimension | Good | Bad | Stakes | Source |
|-----------|------|-----|--------|--------|
| Constraint fidelity | Every shown item remains eligible | Neural score overrides a hard rule | High | Existing agent contract |
| Discovery | Correct product enters top 10 earlier | Suitable candidate remains buried | Medium | Public/gap evaluator |
| Ordering | Relevant products move upward without losing hits | MRR rises by sacrificing coverage | Medium | Paired session analysis |
| Robustness | Improvement transfers to unseen products and concepts | Memorizes products or calibration phrases | High | Product/concept-disjoint split |

### Known Failure Modes in This Domain

- Product-title memorization masquerading as relevance learning.
- False negatives caused by incomplete catalog relevance labels.
- Popularity/brand bias overwhelming explicit shopper constraints.
- Synthetic language differing from real multi-turn intent state.

### Regulatory / Compliance Context

No domain-specific regulation is required for this offline experiment. Existing
catalog and evaluation data stay local; no user-identifying data is introduced.

### Domain Expert Roles for Evaluation

| Role | Responsibility |
|------|---------------|
| Search/relevance engineer | Leakage audit, hard-negative review, metric interpretation |
| Merchandising/domain reviewer | Sample false-negative and ranking-regression review |

## 2. Framework Decision

**Selected Framework:** SentenceTransformers `CrossEncoderTrainer`

**Version:** `sentence-transformers>=5.1,<6` (tested with 5.7.0)

**Rationale:** It already loads the validated MiniLM-L6 checkpoint, accepts
`datasets.Dataset` pair rows, provides `BinaryCrossEntropyLoss`, and includes a
reranking evaluator. It keeps training aligned with the existing inference code.

**Alternatives Considered:**

| Framework | Ruled Out Because |
|-----------|------------------|
| Raw Hugging Face `Trainer` | More tokenizer/collator/evaluator plumbing without experimental benefit |
| FlagEmbedding trainer | Strong BGE path, but the selected model and current code use SentenceTransformers |
| Legacy `CrossEncoder.fit` | Deprecated by current SentenceTransformers documentation |

**Vendor Lock-In Accepted:** Partial — checkpoint/data remain Hugging Face
compatible, while the training harness uses SentenceTransformers abstractions.

## 3. Framework Quick Reference

### Installation

```bash
uv sync --extra semantic-experiment
```

### Core Imports

```python
from datasets import Dataset
from sentence_transformers.cross_encoder import (
    CrossEncoder,
    CrossEncoderTrainer,
    CrossEncoderTrainingArguments,
)
from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss
```

### Entry Point Pattern

```python
model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2", num_labels=1)
trainer = CrossEncoderTrainer(
    model=model,
    args=CrossEncoderTrainingArguments(output_dir="...", eval_strategy="epoch"),
    train_dataset=Dataset.from_list(train_rows),
    eval_dataset=Dataset.from_list(validation_rows),
    loss=BinaryCrossEntropyLoss(model),
)
trainer.train()
model.save_pretrained("...")
```

### Key Abstractions

| Concept | What It Is | When You Use It |
|---------|------------|-----------------|
| `CrossEncoder` | Joint query-document scorer | Initialization, validation, and export |
| `CrossEncoderTrainer` | Trainer over pair datasets | Fine-tuning and checkpoint selection |
| `BinaryCrossEntropyLoss` | Relevance loss for labels in `[0, 1]` | One positive plus hard negatives |
| `CrossEncoderRerankingEvaluator` | MRR/NDCG/MAP evaluator | Grouped validation queries |

### Common Pitfalls

1. Dataset columns must be two text inputs plus a numeric label.
2. Evaluation targets must be partitioned before negative mining.
3. MPS runs outside the filesystem sandbox on this machine.
4. Trainer checkpoints and raw datasets are generated artifacts, not source.

### Recommended Project Structure

```text
experiments/reranking/
├── build_finetune_dataset.py
├── train_minilm_l6.py
├── audit_finetune_dataset.py
├── FINETUNE-AI-SPEC.md
├── training-data/       # ignored generated rows/manifests
└── checkpoints/         # ignored model/checkpoint output
```

## 4. Implementation Guidance

**Model Configuration:** MiniLM-L6, one output label, max length 256, BCE loss,
fixed seed, epoch evaluation, best-checkpoint reload, JSONL logs, and MPS locally.

**Core Pattern:** Build balanced query groups from calibration-only paraphrases.
Each group has one positive product and same-category hard negatives. Partition
all product IDs first; no product may cross train/validation/held-out boundaries.

**Tool Use:** Existing immutable catalog artifacts supply products and lexical
neighbors. Hidden targets are used only to construct the exclusion set and for
post-training evaluation.

**State Management:** Dataset manifests record catalog hash, source hashes,
seed, mapping IDs, product partitions, row counts, and row-file SHA-256 values.

**Context Window Strategy:** Use the same `ranking_query`/`product_document`
shape as inference and max length 256 so training and serving do not drift.

## 4b. AI Systems Best Practices

### Structured Outputs with Pydantic

```python
from pydantic import BaseModel, Field

class TrainingRow(BaseModel):
    query: str = Field(min_length=1)
    document: str = Field(min_length=1)
    label: float = Field(ge=0.0, le=1.0)
    query_id: str
    product_id: str
    mapping_id: str
```

Runtime code may use frozen dataclasses to avoid adding Pydantic to the default
application; the schema contract and equivalent validations remain mandatory.

### Async-First Design

Not applicable: deterministic dataset construction and local GPU training are
batch jobs. Parallel mutation would make sampling and logs harder to reproduce.

### Prompt Engineering Discipline

Queries are structured ranking inputs, not generative prompts. Templates name
constraint strength and attribute, use only calibration paraphrases, and reject
any query copied into its positive document.

### Context Window Management

Product documents use the existing compact formatter and are truncated by the
model tokenizer at 256 tokens. A later 128-token ablation requires a new row.

### Cost and Latency Budget

Training is an offline MPS/CUDA job. Serving must retain the zero-shot L6 latency
class; checkpoint size and p50/p95 are remeasured end to end before adoption.

## 5. Evaluation Strategy

### Dimensions

| Dimension | Rubric | Measurement | Priority |
|-----------|--------|-------------|----------|
| Leakage | Zero held-out IDs in any training/validation role; zero cross-split IDs | Code audit | Critical |
| Synthetic validity | Query paraphrase absent from positive doc; one positive and ≥2 hard negatives/group | Code audit | Critical |
| Validation ranking | Fine-tuned MRR@10 and NDCG@10 exceed zero-shot on product-disjoint groups | Code metric | High |
| Public safety | Hit@10 ≥ zero-shot L6 0.940 and zero reranker failures | End-to-end evaluator | Critical |
| Gap transfer | Technical score > zero-shot L6 0.591950 | End-to-end evaluator | High |
| Paired regressions | Report added/lost hits and rank improvements/regressions | Paired analysis | High |
| Latency | Report MPS p50/p95; no unexplained order-of-magnitude regression | Code metric | Medium |

### Eval Tooling

**Primary Tool:** Existing deterministic evaluator, paired matrix analyzer, and
structured JSON artifacts. Arize Phoenix is intentionally overridden because
this is an offline local ranker with no LLM/API traces; adding telemetry would
not measure the adoption gates.

**CI/CD Integration:**

```bash
python -m unittest tests.test_finetune_experiment -v
python -m unittest discover -s tests -q
```

### Reference Dataset

**Size:** Up to 3,000 balanced product-disjoint query groups for training and
300 for validation; 200 public and 177 semantic-gap sessions remain held out.

**Composition:** Calibration paraphrases only for training/validation; public
buying/exploring/override/boundary sessions and test-only paraphrases for final
evaluation.

**Labeling:** Exact catalog surface evidence creates positives. Same-category
lexical neighbors lacking the surface and paraphrase create provisional hard
negatives. A sampled negative audit is required because catalog labels are not
exhaustive relevance judgments.

## 6. Guardrails

### Online (Real-Time)

| Guardrail | Trigger | Intervention |
|-----------|---------|--------------|
| Hard eligibility | Candidate fails deterministic constraint | Never enter reranker pool |
| Reranker error | Load/inference/non-finite score failure | Return unchanged baseline top 10 |
| Disabled default | No explicit experimental checkpoint | Do not load ML runtime |

### Offline (Flywheel)

| Metric | Sampling Strategy | Action on Degradation |
|--------|------------------|----------------------|
| Lost hits/rank regressions | Review every regression in 377 held-out sessions | Reject or revise dataset/objective |
| False-negative risk | Deterministic sample across every mapping/split | Remove bad groups and rebuild |
| Latency drift | Every accepted checkpoint | Reject serving configuration |

## 7. Production Monitoring

**Tracing Tool:** Existing structured reranker events and JSON matrix artifacts.

**Key Metrics:** Hit@10, MRR, technical score, paired lost hits, reranker
failures, p50/p95 latency, checkpoint and dataset hashes.

**Alert Thresholds:** Any hard-eligibility failure; any inference failure;
public Hit@10 below 0.940; gap score at or below 0.591950; p95 >2x zero-shot L6.

**Smart Sampling Strategy:** Review all lost-hit sessions and a stable hash
sample of improvements/ties across each scenario and category bucket.

## Checklist

- [x] System type classified
- [x] Critical failure modes identified
- [x] Domain context and expert criteria documented
- [x] Compliance context explicitly assessed
- [x] Expert roles defined
- [x] Framework selected with rationale and alternatives
- [x] Quick reference and entry pattern written
- [x] Structured schema and batch-design practices documented
- [x] Evaluation dimensions have concrete rubrics
- [x] Existing structured tracing chosen with Phoenix override explained
- [x] Reference datasets and leakage boundaries specified
- [x] CI verification commands specified
- [x] Online/offline guardrails and monitoring thresholds defined
