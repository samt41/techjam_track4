# Semantic Encoder Experiment

This package runs the experiment described in
`docs/superpowers/plans/2026-08-30-semantic-retrieval-experiment-implementation.md`.
The ordinary agent remains lexical by default. The hybrid runner explicitly
injects an experimental, low-authority semantic candidate provider so its
recommendations can be compared end to end with the unchanged control.

## Setup

```bash
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv sync --extra semantic-experiment
```

Keep Hugging Face model downloads in an explicit experiment cache when the
default cache is unavailable or should not be shared:

```bash
HF_HOME=experiments/semantic/model-cache \
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run --extra semantic-experiment python -m experiments.semantic.run_probe \
  --concepts experiments/semantic/generated/concepts.jsonl \
  --probe experiments/semantic/probe/v1/test.jsonl \
  --output experiments/semantic/runs/first-test.json
```

Before the curated probe exists, verify the complete model path against the
small checked-in smoke set:

```bash
HF_HOME=experiments/semantic/model-cache \
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run --extra semantic-experiment python -m experiments.semantic.run_probe \
  --concepts experiments/semantic/probe/smoke/concepts.jsonl \
  --probe experiments/semantic/probe/smoke/cases.jsonl \
  --output experiments/semantic/runs/smoke.json
```

The smoke set only catches wiring and glaring model failures. It is not an
adoption benchmark. In particular, raw dense retrieval always returns a
nearest concept for unrelated text; the curated calibration split will set an
abstention threshold before `unrelated_result_at_1` is used as a safety gate.

## Build concepts

Restore `data/catalog.jsonl` and build its ordinary artifacts first. Then run:

```bash
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run python -m experiments.semantic.build_concepts \
  --database data/catalog.artifacts/catalog.sqlite3 \
  --output experiments/semantic/generated/concepts.jsonl
```

The first neural comparison is:

- `Snowflake/snowflake-arctic-embed-s`;
- `BAAI/bge-small-en-v1.5`;
- `Snowflake/snowflake-arctic-embed-xs`; and
- `sentence-transformers/all-MiniLM-L6-v2`.

The existing lexical search plus manual expansions is always included as the
non-neural control.

## Public-session shadow regression

After building the ordinary catalog artifacts and generated concept inventory,
run all 200 public sessions through the unchanged agent while capturing semantic
observations for offline replay:

```bash
HF_HUB_OFFLINE=1 \
HF_HOME=experiments/semantic/model-cache \
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run --no-sync python -m experiments.semantic.run_public_sessions \
  --output experiments/semantic/runs/public-sessions.json
```

To replay an already captured lexical pass without rerunning the agent:

```bash
HF_HUB_OFFLINE=1 \
HF_HOME=experiments/semantic/model-cache \
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run --no-sync python -m experiments.semantic.run_public_sessions \
  --capture experiments/semantic/runs/public-sessions-lexical.json \
  --output experiments/semantic/runs/public-sessions-models.json
```

The wrapper returns each base response object unchanged. Ground-truth products
are joined only after evaluation, and only turns that explicitly contain one of
the target product's catalog concepts receive retrieval labels. This is a
full-catalog regression and latency benchmark. Because the public simulator
mostly copies catalog wording, it is not evidence of open-vocabulary lift.

## Hybrid recommendation matrix

Build the held-out semantic-gap set from the public sessions. This replaces one
catalog-literal constraint with a test-only paraphrase and records source hashes
and replacements in a lineage manifest:

```bash
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run --no-sync python -m experiments.semantic.build_gap_dataset
```

Concept embeddings and calibration thresholds are generated artifacts. The
calibration command only reads the calibration paraphrases and contrast cases;
the matrix evaluates the disjoint test split:

```bash
HF_HUB_OFFLINE=1 \
HF_HOME=experiments/semantic/model-cache \
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run --no-sync python -m experiments.semantic.calibrate_hybrid \
  --output experiments/semantic/generated/hybrid-calibration-v3.json
```

Run one unchanged control and one row for each encoder. For example:

```bash
HF_HUB_OFFLINE=1 \
HF_HOME=experiments/semantic/model-cache \
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run --no-sync python -m experiments.semantic.run_hybrid_matrix \
  --configuration hybrid-bge-small \
  --model bge-small \
  --output experiments/semantic/runs/matrix-bge-small.json
```

Omit `--model` for the `disabled` control. Summarize completed rows with:

```bash
UV_CACHE_DIR=/tmp/tttj-semantic-uv-cache \
  uv run --no-sync python -m experiments.semantic.analyze_hybrid_matrix \
  experiments/semantic/runs/matrix-disabled.json \
  experiments/semantic/runs/matrix-arctic-s.json \
  experiments/semantic/runs/matrix-arctic-xs.json \
  experiments/semantic/runs/matrix-bge-small.json \
  experiments/semantic/runs/matrix-minilm-l6.json
```

The generated matrix reports the evaluator's actual Hit@10, MRR, MTTC, and
recommended technical score on both datasets, plus paired gains/losses, semantic
acceptance, query-resolution latency, and held-out contrast-trap acceptance.
