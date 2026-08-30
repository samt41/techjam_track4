"""The only module in `arena/` permitted to import from `evaluator/` (D-08).

Every arena module reaches the scoring authority through this seam and calls
`evaluate` as an opaque function, so the rig's entire dependency on the harness
is one reviewable line that never touches harness internals.

`tests/test_arena_boundary.py` enforces both halves of that claim: no other
`arena/*.py` may name the harness package, and this seam re-exports exactly the
three names below.
"""

from __future__ import annotations

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl


__all__ = ("catalog_index", "evaluate", "load_jsonl")
