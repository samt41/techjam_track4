"""The only module in `arena/` permitted to import from `evaluator/` (D-08).

Every arena module reaches the scoring authority through this seam and calls
`evaluate` as an opaque function, so the rig's entire dependency on the harness
is one reviewable import that never touches harness internals.

`tests/test_arena_boundary.py` enforces both halves of that claim: no module
anywhere under `arena/` may name the harness package, and this seam re-exports
exactly the eight names below. Each name carries its *why* at the import (D-47);
a ninth name is a deliberate widening, never a convenience.

Widening the seam must NOT tempt anyone to replace `arena/metrics.py` with
evaluator imports. That metric chain is transcribed rather than imported on
purpose (D-06): the cross-agreement between two independent code paths is the
MEAS-16 validation evidence, and importing the evaluator's own `metric_summary`
would turn that check into a tautology instead of a check.
"""

from __future__ import annotations

from evaluator.local_evaluator import (
    # The fallback behavior an authored control arm is compared against, so the
    # control reproduces the evaluator's own synthesis rather than a guess (D-55).
    behavior_for,
    catalog_index,
    # The single authority on which asked attribute unlocks which constraint;
    # any local re-derivation would drift from the simulator (D-33/F-05).
    classify_constraint,
    evaluate,
    # Builds the control arm verbatim from the target product, so the control is
    # the evaluator's own card and not a re-implementation of it (D-31).
    intent_card,
    load_jsonl,
    # Proves branch 1 fired: an authored card must come back unchanged rather
    # than being regenerated from the target's catalog text (D-37).
    materialize_hidden_fields,
    # The exact six-field concatenation the D-34 lexical-overlap gate measures
    # authored probe phrasing against.
    searchable_text,
)


__all__ = (
    "behavior_for",
    "catalog_index",
    "classify_constraint",
    "evaluate",
    "intent_card",
    "load_jsonl",
    "materialize_hidden_fields",
    "searchable_text",
)
