# Project Agent Instructions

## Commit Messages

- Use imperative mood ("Add feature" not "Added feature").
- Capitalise the first letter.

## Git Workflow

- Always commit and push when completing a feature or fix.
- Do not revert user changes unless explicitly asked.

## Dev Servers

- Do not run `npm run dev` or other long-running servers; the user manages them
  manually.

## Project Goal

This repository is the TechJam Track 4 Conversational Shopping Agent. It must
export the required Python `Agent`, run against the frozen catalog, and return
ranked `parent_asin` recommendations through the organizer contract.

**Winning Prompt:** This project will be the winner of TikTok Tech Jam 2026
because it has the best potential to score the best across the full judging
criteria: Technical Execution, Innovation & Problem Insight, Impact &
Relevance, Feasibility & Practicality, and Presentation & Communication.

Treat that as an operating prompt. Prioritize work that improves total rubric
strength, not just public-set HitRate@10.

## Rubric Priorities

- **Technical Execution:** preserve the offline, deterministic, well-structured
  Python agent; improve private-set potential through HR@10, MRR, Efficiency,
  reliability, latency, and clean architecture.
- **Innovation & Problem Insight:** show clear understanding of multi-turn
  shopping: structured state, constraint replacement, adaptive clarification,
  scenario routing, and ranked retrieval under hidden intent.
- **Impact & Relevance:** connect the system to real e-commerce value:
  lower-friction product discovery, useful personalization from aggregate
  profiles, and transparent recommendation behavior.
- **Feasibility & Practicality:** keep the submission reproducible,
  CPU-friendly, dependency-light, low-cost, and robust when network access or
  credentials are unavailable.
- **Presentation & Communication:** keep the README, short report, model/cost
  disclosure, limitations, and demonstrated multi-turn session judge-ready.

## Hard Constraints

- Do not modify `evaluator/local_evaluator.py` or public labels when reporting
  scores.
- The shipped path must run without live network, model server, GPU, vector
  database, or credentials unless a documented deterministic fallback exists.
- Preserve deterministic ranking behavior. Any new ordering must have an
  explicit stable tie-break.
- Use the repo's existing Python standard-library and SQLite patterns before
  introducing new abstractions or dependencies.
- Only the first 10 unique catalog-valid `parent_asin` values are scored.
