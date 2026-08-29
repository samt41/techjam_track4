# Roadmap: TechJam Track 4 — Conversational Shopping Agent

## Overview

This milestone does not build a shopping agent — one already exists, deterministic,
scoring HR@10 `0.920` / TechnicalScore `0.7688`. It builds everything needed to win
a hackathon under the actual judging rubric, where that metric feeds only 35% of
the outcome. Phases 1-2 build and validate a measurement rig — the statistics
engine, leaderboard, expanded evaluation corpus, and an anti-circular paraphrase
probe — because no candidate comparison downstream is trustworthy without it, and
both research streams independently prove this at n=200. Phases 3-4 run the actual
bake-off (ranking precision, conversational efficiency, the offline semantic asset,
and two disclosed-cost spikes) entirely through that rig, judged jointly on
HR@10/MRR/MTTC, never one metric at a time. Phase 5 is a hard, explicit go/no-go
checkpoint that stops score-chasing once winner's-curse-corrected marginal gain
runs dry — the exact transition research flags as where solo-developer time
silently misallocates. Phase 6 (submission hardening) is orthogonal to the bake-off
and can run in parallel with any of Phases 1-5. Phases 7-8 carry the Innovation and
Impact narrative and all mandatory deliverables — 40% of the rubric the retrieval
metric never touches — deliberately started early (Phase 7, right after the
paraphrase probe lands) rather than deferred until "the code is done," with
finalization (Phase 8) closing out once the shipping candidate and hardening
numbers are known.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Measurement Rig Core** - Build and validate the statistics engine and leaderboard against retained historical data, before any new candidate exists.
- [ ] **Phase 2: Expanded Dataset & Paraphrase Probe** - Generate an expanded evaluation corpus and a frozen, anti-circular paraphrase probe — the project's first real vocabulary-generalization evidence and the seed of the Innovation narrative.
- [ ] **Phase 3: Ranking Precision & Conversational Efficiency** - Build and jointly measure MRR/MTTC candidates through the arena, gated by the breakeven rule and re-validated against the paraphrase probe.
- [ ] **Phase 4: Semantic Asset & Candidate Spikes** - Ship the audited offline semantic asset and measure the two disclosed-cost spike candidates without adopting either by default.
- [ ] **Phase 5: Go/No-Go Checkpoint** - Record a corrected-gain-based decision to stop or continue score-improvement iteration.
- [ ] **Phase 6: Submission Hardening** - Make the submission robust to a missing artifact, unbounded memory, slow turns, and a blocked network, independent of the bake-off outcome.
- [ ] **Phase 7: Narrative Draft — Innovation & Impact Positioning** - Draft the Innovation and Impact rubric narratives while the paraphrase-probe finding is fresh, not after code work is declared done.
- [ ] **Phase 8: Deliverables Finalization & Submission** - Complete, verify, and disclose every mandatory deliverable against the shipped candidate.

## Phase Details

### Phase 1: Measurement Rig Core
**Goal**: A statistically honest, evaluator-respecting measurement instrument exists and is validated against history — before any new candidate is built, so nothing downstream is judged on noise.
**Depends on**: Nothing (first phase)
**Requirements**: MEAS-01, MEAS-02, MEAS-03, MEAS-04, MEAS-05, MEAS-06, MEAS-07, MEAS-08, MEAS-09, MEAS-14, MEAS-15, MEAS-16
**Success Criteria** (what must be TRUE):
  1. The leaderboard report for the existing 200-session historical run shows TechnicalScore, HR@10, MRR, and MTTC as separate columns, both overall and broken out per scenario (Buying/Browsing/Intent Override/Boundary).
  2. The same report includes an HR@1/@3/@5/@10 curve computed from retained trace data alone, without re-invoking the agent.
  3. Running the paired bootstrap/permutation test, Holm-Bonferroni correction, the ≥0.01 TechnicalScore practical-significance floor, and the winner's-curse order-statistic correction against two retained historical rows in `experiments/RUNS.md` produces a reproducible verdict and a minimum-detectable-difference value, using no new candidates.
  4. Every per-scenario non-inferiority verdict in the report states its bucket size and binomial standard error (e.g., Boundary n=10, σ≈0.086, explicitly flagged as not decision-grade in isolation).
  5. `CandidateSpec` construction from identical inputs produces an identical fingerprint hash twice, and the arena module contains no import of `evaluator.local_evaluator` internals beyond calling `evaluate()` as an opaque function.
**Plans**: TBD

### Phase 2: Expanded Dataset & Paraphrase Probe
**Goal**: An expanded evaluation corpus and a matched, anti-circular paraphrase probe exist and are frozen, giving the project its first real evidence of vocabulary generalization — and the headline finding for the Innovation narrative.
**Depends on**: Phase 1
**Requirements**: MEAS-10, MEAS-11, MEAS-12, MEAS-13
**Success Criteria** (what must be TRUE):
  1. An expanded set of evaluation sessions beyond the original 200 exists, generated so every session takes the evaluator's authored `intent_card` + `behavior` branch — never the catalog-scraping fallback — verified programmatically, not assumed.
  2. Matched control/probe session pairs exist — same hidden target, two phrasings (catalog-quoting vs. customer language) — so any measured score delta isolates vocabulary generalization from target difficulty.
  3. Probe authoring is verified anti-circular: an automated check confirms the target's literal catalog text never appears in the authoring prompt, and a measured lexical-overlap ratio is reported for every probe pair as an acceptance gate.
  4. A second model family has independently authored or reviewed a cross-check subset of the probe, with any generator-affinity gap between families reported explicitly rather than assumed absent.
  5. The probe set is checksummed and frozen (recorded commit/hash) before any Phase 3 or Phase 4 candidate is measured against it.
**Plans**: TBD

### Phase 3: Ranking Precision & Conversational Efficiency
**Goal**: Rank-1 precision and turn-efficiency candidates are built and measured jointly against HR@10, MRR, and MTTC — never in isolation — with every accepted change surviving the breakeven rule and re-validation against the paraphrase probe, not just the original 200 sessions.
**Depends on**: Phase 1, Phase 2
**Requirements**: RANK-01, RANK-02, RANK-03, RANK-04, RANK-05, CONV-01, CONV-02, CONV-03
**Success Criteria** (what must be TRUE):
  1. `DialogueAct.SLATE_FEEDBACK` demonstrably changes belief-posterior ranking in a targeted test (a declined item's rank drops), with the effect bounded, decaying, and scoped to the specific `parent_asin` — never leaking into attribute-level weights.
  2. A frozen linear reranker and a tuned, normalized fusion weighting are both measured through the Phase 1 arena against the untuned RRF k=60 baseline, with HR@10, MRR, and MTTC reported jointly for every candidate.
  3. Every accepted ranking change is justified by a catalog-derived or structurally general property (never "this moves session #47"), and is re-validated against the Phase 2 paraphrase probe, not only the original 200 sessions.
  4. A confidence-based commitment trigger skips the clarifying question only when the strict-population posterior already dominates, and the resulting MTTC change is checked against the ΔMRR > 0.0667×ΔMTTC breakeven rule before acceptance.
  5. No ranking or efficiency candidate is accepted on a single-metric read — every leaderboard entry reports HR@10, MRR, and MTTC together, and any HR@10 regression is treated as disqualifying unless the exchange-rate math clears with margin.
**Plans**: TBD

### Phase 4: Semantic Asset & Candidate Spikes
**Goal**: The offline semantic asset ships safely audited and frozen, and the two disclosed-cost spike candidates are measured with their true feasibility cost on the record — spiked to measure headroom, not adopted by default.
**Depends on**: Phase 1, Phase 2
**Requirements**: SEM-01, SEM-02, SEM-03, SEM-04, SPIKE-01, SPIKE-02, SPIKE-03
**Success Criteria** (what must be TRUE):
  1. The offline LLM-generated concept/synonym asset replaces the six-entry `_EXPANSIONS` table, passes an automated antonym/negation audit with every flagged entry resolved (none silently included), and is checksummed and version-pinned with its generating prompt and model recorded.
  2. With the semantic asset installed, the agent still reports zero runtime dependencies, zero tokens at inference, and reproduces byte-identical output across two independent runs.
  3. The ONNX cross-encoder reranker spike reports its measured local CPU per-turn latency and its installed dependency footprint (MB) alongside its HR@10/MRR/MTTC delta on the Phase 1 arena.
  4. The runtime LLM constraint-extraction spike is measured on both a network-on path and an explicit network-blocked path, with the fallback's degraded-not-zero behavior demonstrated, not assumed.
  5. Every spike's leaderboard entry states whether it clears the ≥0.01 TechnicalScore practical floor and passes an explicit Feasibility-cost judgment before being considered for promotion to the shipping candidate.
**Plans**: TBD

### Phase 5: Go/No-Go Checkpoint
**Goal**: A single explicit decision record exists — continue score-improvement iteration or stop and reallocate to the untouched 65% of the rubric — based on corrected marginal gain, not raw score, closing the exact transition where solo-developer time silently misallocates.
**Depends on**: Phase 3, Phase 4
**Requirements**: POS-04
**Success Criteria** (what must be TRUE):
  1. A written go/no-go record states the winner's-curse-corrected marginal TechnicalScore gain of the current leading candidate(s), computed via the Phase 1 order-statistic correction for however many candidates were actually compared.
  2. The record explicitly compares that corrected gain against the ~0.005 TechnicalScore stopping threshold and states a decision — continue or stop.
  3. If the decision is "stop," the record names the exact candidate that ships and closes further bake-off iteration; if "continue," it names the specific additional candidate(s) and the remaining effort budget before the next checkpoint.
  4. The record is timestamped and linked from `PROJECT.md`'s Key Decisions table, not left as an informal note.
**Plans**: TBD

### Phase 6: Submission Hardening
**Goal**: The submission is robust to organizer-realistic failure conditions — a missing artifact, unbounded memory, slow turns, and a blocked network — independent of which candidate wins the bake-off, and can be built at any point in parallel with Phases 1-5.
**Depends on**: Nothing (orthogonal to the bake-off; may run in parallel with Phases 1-5)
**Requirements**: HARD-01, HARD-02, HARD-03, HARD-04, HARD-05, HARD-06
**Success Criteria** (what must be TRUE):
  1. `Agent(...)` constructs successfully when the artifact directory is absent, building it lazily, with construction no longer raising.
  2. A full 800-session-scale synthetic run shows bounded peak memory — session state, turn history, and product cache no longer grow without limit.
  3. Under an artificially slowed component, a soft per-turn deadline test shows the agent returns a best-so-far slate rather than exceeding the deadline.
  4. An end-to-end run with the network actually blocked at the OS/container level (a blackhole/DROP condition, not merely an absent call), using explicit short connect/read timeouts, completes every session within budget with the documented fallback engaged.
  5. `requirements.txt` is present in the submission layout, and the artifact build cost is either measurably reduced from the 580 MB / 60-90 s baseline or explicitly justified with measured numbers in the Feasibility narrative.
**Plans**: TBD

### Phase 7: Narrative Draft — Innovation & Impact Positioning
**Goal**: The Innovation and Impact rubric narratives exist as committed, evidenced artifacts while the paraphrase-probe finding is fresh — treated as first-class engineering/writing work with its own budget, not cleanup appended at the end.
**Depends on**: Phase 2
**Requirements**: DELIV-01, POS-01, POS-02
**Success Criteria** (what must be TRUE):
  1. The GitHub repository is public, with its history verified clean of organizer-only material.
  2. A committed Innovation narrative document leads with the public-set structural blind-spot finding (the evaluator's fallback branch making the simulated customer quote the target's own catalog text) and cites the Phase 2 paraphrase probe as its supporting evidence, including the probe's sample size and confidence interval.
  3. A committed Impact narrative document is scoped to cost, compliance, and auditability with quantified claims (e.g., zero per-query API cost, zero PII collection, auditable log-odds trace) rather than generic "better shopping" language.
**Plans**: TBD

### Phase 8: Deliverables Finalization & Submission
**Goal**: Every mandatory deliverable is complete, accurate to the shipped candidate, disclosed honestly, and verified on a clean environment — ready for submission.
**Depends on**: Phase 5, Phase 6, Phase 7
**Requirements**: DELIV-02, DELIV-03, DELIV-04, DELIV-05, DELIV-06, DELIV-07, POS-03
**Success Criteria** (what must be TRUE):
  1. Code comment density across all components (agent, arena, build scripts) is measurably increased from the ~2.3% baseline, verified by a line-count check.
  2. The README (overview, setup, reproduction steps, limitations reflection, team contributions) has been executed start-to-finish on a clean, non-development environment and reproduces without manual fixes.
  3. A demo video ≤3 minutes is live on YouTube as public and linked from Devpost, opening with a real multi-turn transcript and a hit before any architecture explanation.
  4. The Devpost description covers problem fit, development tools, APIs/libraries/frameworks, and datasets/assets used, and explicitly discloses latency, token usage, estimated model cost, network requirement, and fallback behavior for the shipped candidate.
  5. One demonstrated multi-turn session is packaged as a readable artifact from `Agent.turn_history()`, and the Feasibility narrative asserts only what Phase 6 hardening actually delivered — no unclaimed "resource usage is proportionate."
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → {3, 4 in parallel} → 5 → 8, with 6 parallelizable against 1-5 and 7 starting immediately after 2.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Measurement Rig Core | 0/TBD | Not started | - |
| 2. Expanded Dataset & Paraphrase Probe | 0/TBD | Not started | - |
| 3. Ranking Precision & Conversational Efficiency | 0/TBD | Not started | - |
| 4. Semantic Asset & Candidate Spikes | 0/TBD | Not started | - |
| 5. Go/No-Go Checkpoint | 0/TBD | Not started | - |
| 6. Submission Hardening | 0/TBD | Not started | - |
| 7. Narrative Draft — Innovation & Impact Positioning | 0/TBD | Not started | - |
| 8. Deliverables Finalization & Submission | 0/TBD | Not started | - |
