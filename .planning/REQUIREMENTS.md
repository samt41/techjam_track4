# Requirements: TechJam Track 4 — Conversational Shopping Agent

**Defined:** 2026-08-29
**Core Value:** Maximize total rubric score, not HitRate@10.

Scoping note: this is a brownfield milestone. A working agent already exists at
HR@10 `0.920` / TechnicalScore `0.7688`. Everything below is *new* work; the
existing engine's capabilities are recorded as Validated in `PROJECT.md` and are
not restated here.

## v1 Requirements

### Measurement Rig

The arena. Nothing downstream can be trusted without it — research established
independently that at n=200 the binomial SE is σ ≈ 0.019 HR@10, and that
selecting the best of k candidates manufactures 0.022-0.030 of apparent gain.

- [ ] **MEAS-01**: Leaderboard reports TechnicalScore with HR@10, MRR, and MTTC
      broken out as separate columns, overall and per scenario
- [ ] **MEAS-02**: HR@1 / @3 / @5 / @10 curve computed and reported for every run
- [ ] **MEAS-03**: Per-scenario MRR and MTTC recovered from existing retained
      trace data without re-running the agent
- [ ] **MEAS-04**: Candidate comparison uses paired tests joined on `sample_id`
      (bootstrap and permutation), never independent-sample tests
- [ ] **MEAS-05**: Holm-Bonferroni correction applied across competing candidates
- [ ] **MEAS-06**: Minimum detectable difference reported beside every
      leaderboard row, so "no significant difference" is visibly distinct from
      "we could not have detected one"
- [ ] **MEAS-07**: A practical-significance floor of ≥0.01 TechnicalScore gates
      any claimed win, independent of the p-value
- [ ] **MEAS-08**: Winner's-curse correction applied to a selected champion's
      reported gain before it is believed or published
- [ ] **MEAS-09**: Per-scenario non-inferiority gates state their bucket-size
      caveat (Boundary n=10, σ ≈ 0.086; Intent Override n=30, σ ≈ 0.050)
- [ ] **MEAS-10**: Expanded evaluation sessions generated from the frozen
      catalog, always taking the evaluator's authored-card branch
- [ ] **MEAS-11**: Paraphrase probe built as matched control/probe pairs — same
      target, two card phrasings — so target difficulty cannot confound the
      vocabulary-generalization signal
- [ ] **MEAS-12**: Probe authoring is anti-circular: the target's literal catalog
      text never appears in the authoring prompt, lexical overlap is measured as
      an acceptance gate, and the probe is frozen before any candidate iterates
      against it
- [ ] **MEAS-13**: Probe cross-checked against a second model family to detect
      self-preference bias
- [ ] **MEAS-14**: Candidates declared through a fingerprinted, hashable spec so
      any run is reproducible and attributable
- [ ] **MEAS-15**: Arena code never imports from, and never modifies,
      `evaluator/` — `evaluate()` is called as an opaque function
- [ ] **MEAS-16**: Statistics engine validated against the retained historical
      rows in `experiments/RUNS.md` before any new candidate exists

### Ranking Precision (MRR)

Where the headroom is: +0.119 available versus +0.040 in recall.

- [ ] **RANK-01**: `DialogueAct.SLATE_FEEDBACK` is consumed as negative evidence
      in the belief posterior, not merely used to rotate the slate
- [ ] **RANK-02**: Negative evidence is bounded, decaying, and scoped to the
      specific `parent_asin` — never propagated to attribute-level weights
- [ ] **RANK-03**: A frozen linear reranker orders the top fused candidates on
      engineered features, with coefficients fit offline and baked in as
      constants
- [ ] **RANK-04**: Fusion uses dev-set-tuned normalized weights rather than
      untuned RRF k=60, or measurement shows RRF is not costing points
- [ ] **RANK-05**: Every ranking change reports HR@10, MRR, and MTTC jointly and
      is checked against the breakeven rule ΔMRR > 0.0667 × ΔMTTC

### Conversational Efficiency (MTTC)

- [ ] **CONV-01**: A confidence-based commitment trigger skips the clarifying
      question when top-1 posterior mass already dominates
- [ ] **CONV-02**: The commitment trigger is gated behind the strict-population
      computation so it cannot fire on a confidently wrong candidate
- [ ] **CONV-03**: Turn-count reduction is measured against recall — HR@10 is 25×
      more sensitive per point than MTTC, so a recall regression cannot be
      bought with speed

### Semantic Asset (Tier 1, offline)

- [ ] **SEM-01**: An offline LLM-generated synonym/concept asset replaces the
      hand-written six-entry `_EXPANSIONS` table
- [ ] **SEM-02**: The asset passes an antonym/negation audit before it is frozen
- [ ] **SEM-03**: The asset is checksummed and version-pinned, and the build step
      that produces it is separate from and not required by agent runtime
- [ ] **SEM-04**: With the asset in place the agent remains stdlib-only,
      network-free, byte-deterministic, and reports zero tokens at inference

### Candidate Spikes (measured, not default)

The user directive is to compare approaches and ship the winner. These are built
to be *measured*, with their true cost disclosed — not adopted by default.

- [ ] **SPIKE-01**: ONNX cross-encoder reranker spiked and measured, with its
      dependency footprint and per-turn CPU latency measured locally
- [ ] **SPIKE-02**: Runtime LLM constraint extraction spiked with a deterministic
      fallback beneath it, measured on both the network-on and network-off paths
- [ ] **SPIKE-03**: Any spike that wins on measured score is evaluated against
      its Feasibility cost before being promoted to the shipping candidate

### Submission Hardening

- [ ] **HARD-01**: `Agent(...)` constructs successfully when the artifact
      directory is absent, building it lazily rather than raising
- [ ] **HARD-02**: Memory is bounded across an 800-session run — session state,
      turn history, and product cache no longer grow monotonically
- [ ] **HARD-03**: A soft per-turn deadline degrades to the best-so-far slate
      rather than risking a timeout scored as a miss
- [ ] **HARD-04**: The network-disabled path is verified by an actual
      blocked-network end-to-end run with explicit short timeouts, against a
      silent-blackhole failure mode rather than a fast DNS failure
- [ ] **HARD-05**: `requirements.txt` is present per the recommended submission
      layout, even though the dependency set is empty
- [ ] **HARD-06**: Artifact build cost is reduced, or explicitly justified in the
      Feasibility narrative with measured numbers

### Deliverables

All five are mandatory. Two were absent from the repository's own gap analysis.

- [ ] **DELIV-01**: The GitHub repository is public
- [ ] **DELIV-02**: Code is meaningfully commented across all components
      (currently ~2.3% density)
- [ ] **DELIV-03**: README covers project overview, setup and installation,
      reproduction steps, a limitations reflection, and team contributions
- [ ] **DELIV-04**: A demo video, ≤3 minutes, is uploaded to YouTube as public
      and linked from Devpost — opening with a live multi-turn transcript before
      any architecture explanation
- [ ] **DELIV-05**: Devpost description covers how the solution addresses the
      problem, development tools, APIs, libraries and frameworks, and datasets
      and assets used
- [ ] **DELIV-06**: Latency, token usage, estimated model cost, network
      requirement, and fallback behavior are disclosed explicitly
- [ ] **DELIV-07**: One demonstrated multi-turn session is packaged as a readable
      artifact from `Agent.turn_history()`

### Rubric Positioning

40% of the score, currently near-unaddressed. Treated as engineering work with
its own budget, not as cleanup.

- [ ] **POS-01**: The Innovation narrative leads with the public-set structural
      blind-spot finding — that the evaluator's fallback branch makes the
      simulated customer quote the target's own catalog text — supported by the
      paraphrase probe as its proof
- [ ] **POS-02**: The Impact case is scoped to cost, compliance, and
      auditability with quantified claims, not generic "better shopping"
- [ ] **POS-03**: Feasibility claims assert only what hardening has actually
      delivered — no "resource usage is proportionate" while a 580 MB artifact
      is a hard construction dependency
- [ ] **POS-04**: A go/no-go checkpoint record exists, stopping score-improvement
      work once winner's-curse-corrected marginal gain falls below ~0.005
      TechnicalScore

## v2 Requirements

Acknowledged, deferred, not in this roadmap.

### Retrieval

- **V2-01**: SPLADE-distilled term-importance weights frozen into the existing
  `lexical_postings` table — mechanism sound, integration nonstandard, MEDIUM
  confidence on magnitude
- **V2-02**: A dense embedding retrieval route via small local ONNX models
- **V2-03**: Deeper profile-conditioned prior — the anonymous profile is
  deliberately thin and headroom is unclear
- **V2-04**: Soft price-proximity scoring — low expected value

### Presentation

- **V2-05**: Live pitch preparation for the final event (Presentation &
  Communication, 10%, final-event only)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Modifying `evaluator/local_evaluator.py` | Byte-identical to the organizer's file; results reported against a modified evaluator are invalid |
| Catalog modification | Explicitly out of scope in the competition specification |
| Full-model training | Explicitly out of scope |
| Multimodal search | Explicitly out of scope |
| Infrastructure-heavy vector databases | Explicitly out of scope |
| A user interface | Not required; the backend track accepts a walkthrough video |
| Real transactions | Out of scope |
| Shipping an LLM-dependent agent with no offline fallback | Network may be disabled at official scoring — no fallback means zero, not degraded |
| HR@10 as the primary optimization target | Nearly saturated; ~4:1 headroom favours MRR and MTTC |
| Slate diversification / MMR reranking | One hidden target per session on exact match — diversity trades away rank-1 concentration for nothing |
| Naive "rejected = negative sample" propagated to attribute weights | CRS literature (EAR, NFCR) reports this backfires |
| Cross-session or bandit personalization | Verified zero user overlap between public and private sets |
| Widening the overfit phrase matchers | The risk they were logged against is largely disproven — the evaluator is unmodified organizer code |

## Traceability

Mapped during roadmap creation (`.planning/ROADMAP.md`). Every v1 requirement
maps to exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| MEAS-01 | Phase 1: Measurement Rig Core | Pending |
| MEAS-02 | Phase 1: Measurement Rig Core | Pending |
| MEAS-03 | Phase 1: Measurement Rig Core | Pending |
| MEAS-04 | Phase 1: Measurement Rig Core | Pending |
| MEAS-05 | Phase 1: Measurement Rig Core | Pending |
| MEAS-06 | Phase 1: Measurement Rig Core | Pending |
| MEAS-07 | Phase 1: Measurement Rig Core | Pending |
| MEAS-08 | Phase 1: Measurement Rig Core | Pending |
| MEAS-09 | Phase 1: Measurement Rig Core | Pending |
| MEAS-14 | Phase 1: Measurement Rig Core | Pending |
| MEAS-15 | Phase 1: Measurement Rig Core | Pending |
| MEAS-16 | Phase 1: Measurement Rig Core | Pending |
| MEAS-10 | Phase 2: Expanded Dataset & Paraphrase Probe | Pending |
| MEAS-11 | Phase 2: Expanded Dataset & Paraphrase Probe | Pending |
| MEAS-12 | Phase 2: Expanded Dataset & Paraphrase Probe | Pending |
| MEAS-13 | Phase 2: Expanded Dataset & Paraphrase Probe | Pending |
| RANK-01 | Phase 3: Ranking Precision & Conversational Efficiency | Pending |
| RANK-02 | Phase 3: Ranking Precision & Conversational Efficiency | Pending |
| RANK-03 | Phase 3: Ranking Precision & Conversational Efficiency | Pending |
| RANK-04 | Phase 3: Ranking Precision & Conversational Efficiency | Pending |
| RANK-05 | Phase 3: Ranking Precision & Conversational Efficiency | Pending |
| CONV-01 | Phase 3: Ranking Precision & Conversational Efficiency | Pending |
| CONV-02 | Phase 3: Ranking Precision & Conversational Efficiency | Pending |
| CONV-03 | Phase 3: Ranking Precision & Conversational Efficiency | Pending |
| SEM-01 | Phase 4: Semantic Asset & Candidate Spikes | Pending |
| SEM-02 | Phase 4: Semantic Asset & Candidate Spikes | Pending |
| SEM-03 | Phase 4: Semantic Asset & Candidate Spikes | Pending |
| SEM-04 | Phase 4: Semantic Asset & Candidate Spikes | Pending |
| SPIKE-01 | Phase 4: Semantic Asset & Candidate Spikes | Pending |
| SPIKE-02 | Phase 4: Semantic Asset & Candidate Spikes | Pending |
| SPIKE-03 | Phase 4: Semantic Asset & Candidate Spikes | Pending |
| POS-04 | Phase 5: Go/No-Go Checkpoint | Pending |
| HARD-01 | Phase 6: Submission Hardening | Pending |
| HARD-02 | Phase 6: Submission Hardening | Pending |
| HARD-03 | Phase 6: Submission Hardening | Pending |
| HARD-04 | Phase 6: Submission Hardening | Pending |
| HARD-05 | Phase 6: Submission Hardening | Pending |
| HARD-06 | Phase 6: Submission Hardening | Pending |
| DELIV-01 | Phase 7: Narrative Draft — Innovation & Impact Positioning | Pending |
| POS-01 | Phase 7: Narrative Draft — Innovation & Impact Positioning | Pending |
| POS-02 | Phase 7: Narrative Draft — Innovation & Impact Positioning | Pending |
| DELIV-02 | Phase 8: Deliverables Finalization & Submission | Pending |
| DELIV-03 | Phase 8: Deliverables Finalization & Submission | Pending |
| DELIV-04 | Phase 8: Deliverables Finalization & Submission | Pending |
| DELIV-05 | Phase 8: Deliverables Finalization & Submission | Pending |
| DELIV-06 | Phase 8: Deliverables Finalization & Submission | Pending |
| DELIV-07 | Phase 8: Deliverables Finalization & Submission | Pending |
| POS-03 | Phase 8: Deliverables Finalization & Submission | Pending |

**Coverage:**
- v1 requirements: 48 total (MEAS 16, RANK 5, CONV 3, SEM 4, SPIKE 3, HARD 6,
  DELIV 7, POS 4)
- Mapped to phases: 48
- Unmapped: 0 ✓

**Per-phase counts:**

| Phase | Requirement count |
|-------|-------------------|
| 1. Measurement Rig Core | 12 |
| 2. Expanded Dataset & Paraphrase Probe | 4 |
| 3. Ranking Precision & Conversational Efficiency | 8 |
| 4. Semantic Asset & Candidate Spikes | 7 |
| 5. Go/No-Go Checkpoint | 1 |
| 6. Submission Hardening | 6 |
| 7. Narrative Draft — Innovation & Impact Positioning | 3 |
| 8. Deliverables Finalization & Submission | 7 |
| **Total** | **48** |

---
*Requirements defined: 2026-08-29*
*Last updated: 2026-08-29 after roadmap creation — traceability populated, 48/48 requirements mapped*
