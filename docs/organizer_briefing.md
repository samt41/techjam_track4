# Organizer briefing notes

Transcribed from eleven slides of the organizer's briefing deck, captured as
screenshots on 28 August 2026. This is a secondary record. Where it disagrees
with `competition_specification.md`, `submission_rules.md`,
`evaluation_config.json`, or `agent_api_contract.json`, those files win, since
they ship in the participant kit and this does not.

Nothing here contradicts those four files. Most of it restates them. The parts
that are genuinely new are listed under "What the deck adds" near the bottom,
along with what they mean for this repository.

## Goal and division of work

Find the hidden target product as early and as highly ranked as possible.

The organizer supplies the frozen catalog, the public sessions, the simulator,
the evaluator, and the starter code. The team supplies one Python Agent that
asks useful questions, keeps active constraints, and returns up to ten ranked
`parent_asin` values. A conversation stops after a valid hit or after turn 10.
No hosted service is required.

## Scope

In scope: keyword, dense, or hybrid retrieval; query rewriting; semantic
reranking; conversation state; clarification strategy; safe use of the
anonymous profile.

Not required: user interface, full-model training, multimodal search, real
transactions, catalog modification, production infrastructure.

The deck is blunt about where the difficulty lies. A beginner can start with
BM25 and rules. Strong teams win through better retrieval and dialogue
decisions.

## How the benchmark was built

The data lineage, with the counts the deck reports at each stage:

```
2,524,981   official Clothing 5-core leave-last-out records
   10,187   eligible records after joining to the frozen catalog
    1,406   distinct candidate targets
      200   public sessions + 800 private sessions
   50,000   frozen catalog products
```

The pipeline starts from the official Clothing 5-core leave-last-out split,
joins targets and visible history to the frozen catalog, requires usable
pre-target catalog history, selects distinct users and target products
deterministically, builds anonymous profiles and organizer-only intent cards,
then splits public from private by user and by target and freezes checksums.

Earlier eligible purchases form the visible history. The final eligible
purchase becomes the hidden target. Customer dialogue is simulated and is not
copied from Amazon reviews.

Source dataset credit is in [DATA_ATTRIBUTION.md](../DATA_ATTRIBUTION.md).

## The privacy boundary

Participants can see the frozen catalog fields, the anonymous aggregate
profile, the public customer messages, and the public target `parent_asin` for
local development.

The organizer keeps the 800 private target labels, the hidden intent cards, the
simulator state, raw user IDs, raw histories, reviews, and timestamps.

Four properties the deck reports as verified before release:

| Property | Value |
| --- | ---: |
| Public/private user overlap | 0 |
| Public/private target overlap | 0 |
| Target records in visible history | 0 |
| `intent_card` fields in released participant data | 0 |

The private set is never placed in the participant repository.

## Visible catalog fields

`parent_asin`, `title`, `features`, `details`, `description`, `categories`,
`store`, `average_rating`, `rating_number`, `price`. Only `parent_asin` is
scored.

## Scenario mix

| Share | Scenario | Behavior |
| ---: | --- | --- |
| 40% | Buying | a hard constraint appears early |
| 40% | Browsing | the request begins vague |
| 15% | Intent Override | a preference changes on turn 3 or 4 |
| 5% | Boundary | the customer may have no preference |

That maps to the 80 / 80 / 30 / 10 split in `data/public_set.jsonl`.

### The override example, and what separates a weak agent from a strong one

The deck works one case through explicitly:

- Turn 1: black running shoes.
- Turn 3: "Actually, make them casual white sneakers."

A weak agent appends the contradictory words to what it already had. A strong
agent replaces black with white and running with casual, then reranks.

This is the behavior `preference_ledger.py` implements as supersede and
retract, and it is why a correction has to be symbolic state rather than
another positive signal added to a pile.

## How customers reveal intent

The deck models disclosure as a rough progression:

```
category -> use case -> material -> style -> budget
```

Its worked dialogue:

```
CUSTOMER   "I need shoes for a trip."
AGENT      "Long walks? Any material or budget preference?"
CUSTOMER   "Water-resistant, comfortable and under $80."

STATE      travel, long walking, water-resistant, comfort, budget <= $80
ACTION     search -> ask -> remember -> re-rank -> Top 10
```

And the line worth pinning to the wall:

> A better question can be more valuable than another retrieval call.

## Agent contract

The local session loop: reset, customer message, Agent response, validate,
exact match, then reply or stop.

```python
reset(session_id, user_profile)
respond(session_id, user_message, turn, top_k)
```

Response fields: `message`, `ask_attribute`, ordered `recommendations`,
optional `usage`.

Validation rules:

- The first ten unique catalog-valid `parent_asin` values are scored.
- Duplicates and invalid IDs are removed. Numeric scores are ignored.
- Exact equality is required. Exceptions, invalid output, or a timeout may
  count as a miss.
- Maximum ten turns. An Intent Override session cannot score before the changed
  intent appears.

The evaluator imports the submission locally. There is no URL and no fixed
port.

## Scoring

Per session:

- `Hit@10` is 1 if the target is in the scored top ten, otherwise 0.
- Reciprocal rank is `1 / target_rank`, and 0 on a miss.
- First-hit turn runs 1 to 10. A miss is assigned 11.

Aggregated **over the 800 private sessions**:

```
HR@10          = successful sessions / N
MRR            = sum(reciprocal rank) / N
MTTC           = sum(first-hit turn) / N
Efficiency     = clip((11 - MTTC) / 10, 0, 1)
TechnicalScore = 0.50*HR@10 + 0.30*MRR + 0.20*Efficiency
```

Reported separately for Buying, Browsing, Intent Override, and Boundary.

Note the scope. `competition_specification.md` line 77 states that
`TechnicalScore` is an objective input to the Technical Execution assessment,
that it is not a separate judging criterion, and that it does not represent the
entire Technical Execution score. The deck does not name the other judging
categories or their weights, so the full rubric is still not in this repository.

## Suggested five-day path

| Day | Work |
| --- | --- |
| 1 | Run the starter kit and build BM25 retrieval. |
| 2 | Implement the Agent contract and conversation state. |
| 3 | Add clarification and evaluate by scenario. |
| 4 | Add hybrid retrieval, embeddings, or reranking. |
| 5 | Improve override handling, latency, token cost, and explanations. |

A valid submission should be possible by Day 3.

Named innovation directions: question-value estimation, intent routing, safe
personalization, strategy switching, context compression, transparent
explanations.

## Downloads

- `catalog.jsonl.gz` and `techjam-participant-kit.zip`
- Repository: https://github.com/TechJam2026/techjam-conversational-search
- Data release:
  https://github.com/TechJam2026/techjam-conversational-search/releases/tag/participant-kit

## What the deck adds

Facts not already present in the four participant-kit files:

- The full data lineage and its counts, from 2,524,981 source records down to
  1,406 candidate targets.
- The four verified disjointness properties, all zero.
- That final aggregation happens over the 800 private sessions. The
  specification implies this; the deck states it.
- The suggested five-day path and the named innovation directions.
- The intent-override worked example.
- The repository and data release URLs.

## What it implies for this repository

Read against the current implementation, the deck lands in three places.

**It confirms the private set is the thing being scored.** Every constant fitted
to the 200 public sessions is a bet on 800 sessions with zero target overlap and
zero user overlap by construction. That is the justification for the
catalog-derived rules in [STATUS.md](STATUS.md) and for the two phrase matchers
recorded there as debt, and it is why keyed-feature recovery was kept despite
measuring no public gain.

**Two named innovation directions are already built.** Question-value estimation
is the expected-posterior-entropy model in `clarification.py`. Override handling
that replaces rather than appends is the supersede and retract logic in
`preference_ledger.py`, which is what moved Intent Override from 0.20 to 0.90.

**Transparent explanations are named and not built.** The `message` string is
templated by `response.py`, and the evaluator never reads it, so it contributes
nothing to TechnicalScore. It is still listed as an innovation direction, and
the specification's Final Deliverables ask for one demonstrated multi-turn
session. Both of those point at the same missing artifact. `Agent.turn_history()`
already returns typed `TurnRecord` values carrying the dialogue act, the
extracted updates, the intent version, the question asked, and the slate, so a
readable transcript is close at hand.

Day 4 on the suggested path is embeddings and reranking. That work is specified
in `superpowers/specs/2026-08-29-offline-semantic-concept-retrieval-design.md`
and deliberately not started, gated on evidence of a vocabulary gap that two
independent miss classifications did not find. See STATUS.md for the reasoning.

## Outstanding deliverable gaps

From the specification's Final Deliverables list:

| Deliverable | State |
| --- | --- |
| Source code with setup and reproduction instructions | Covered by README.md and LOCAL_ENVIRONMENT.md |
| A working Agent on the required interface | Done |
| Short report: architecture, models, cost, limitations, team contributions | Content exists across README.md, STATUS.md, and RUNS.md, but there is no single report and nothing on team contributions |
| One demonstrated multi-turn session | Not built |
