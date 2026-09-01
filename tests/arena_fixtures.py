from __future__ import annotations

import dataclasses
from pathlib import Path

from arena.metrics import SessionOutcome
from arena.store import load_sessions


# Derived from this file's location rather than the process working directory, so
# the fixtures resolve identically however unittest is invoked.
ANCHOR_RECORD_DIR = (
    Path(__file__).resolve().parent.parent / "experiments" / "baselines" / "anchor-legacy"
)


def session(
    sample_id: str,
    *,
    scenario_type: str = "buying",
    best_rank: int | None = None,
    first_hit_turn: int | None = None,
    reciprocal_rank: float | None = None,
) -> SessionOutcome:
    return SessionOutcome(
        sample_id=sample_id,
        scenario_type=scenario_type,
        hit=first_hit_turn is not None,
        first_hit_turn=first_hit_turn,
        best_rank=best_rank,
        reciprocal_rank=(
            (0.0 if best_rank is None else 1.0 / best_rank)
            if reciprocal_rank is None
            else reciprocal_rank
        ),
    )


def sessions_from_ranks(
    ranks: tuple[int | None, ...],
    *,
    scenario_type: str = "buying",
    turn: int = 2,
) -> tuple[SessionOutcome, ...]:
    # Zero-padded to three digits so lexicographic and positional order agree.
    return tuple(
        session(
            f"s{index:03d}",
            scenario_type=scenario_type,
            best_rank=rank,
            first_hit_turn=None if rank is None else turn,
        )
        for index, rank in enumerate(ranks)
    )


def load_anchor_sessions() -> tuple[SessionOutcome, ...]:
    return load_sessions(ANCHOR_RECORD_DIR / "sessions.jsonl")


def promote_hits_to_rank_one(
    sessions: tuple[SessionOutcome, ...],
    count: int,
) -> tuple[SessionOutcome, ...]:
    """Promote the first `count` non-rank-1 hits to rank 1, in file order.

    The deterministic synthetic large-effect control. This is a stronger
    true-positive check than any real evaluation run: it costs zero evaluation
    time and its answer is analytically known. Promoting a hit to rank 1 changes
    neither `hit` nor `first_hit_turn`, so HR@10 and MTTC are invariant and
    deltaTechnicalScore is exactly 0.30 * deltaMRR up to the 6 dp rounding of
    TechnicalScore. A rig that fails to detect this effect is broken.

    File order rather than a seeded random draw: it needs no RNG and is therefore
    byte-stable by construction.
    """
    promotable = sum(
        1 for item in sessions if item.best_rank is not None and item.best_rank > 1
    )
    if promotable < count:
        raise ValueError(
            f"cannot promote {count} sessions; only {promotable} are promotable"
        )
    remaining = count
    promoted: list[SessionOutcome] = []
    for item in sessions:
        if remaining > 0 and item.best_rank is not None and item.best_rank > 1:
            promoted.append(
                dataclasses.replace(item, best_rank=1, reciprocal_rank=1.0)
            )
            remaining -= 1
        else:
            promoted.append(item)
    return tuple(promoted)
