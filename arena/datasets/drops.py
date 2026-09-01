"""The committed record of what a corpus could not author, and what that cost it.

`AUTHORING_ATTEMPT_CAP` bounds re-authoring; something has to happen when the cap
is spent. Raising ends the run and is what `attempt_until` still does. Dropping
the constraint and continuing is the other option, and it is admissible for
exactly one reason: the drop is recorded completely enough that a reader of the
corpus can see the shortfall and its causes without re-running anything.

That condition is what this module exists to satisfy, and `docs/STATUS.md` states
the failure it is guarding against in the generator's own words -- a silent drop
"would leave the corpus smaller than its recorded session count, and that
shortfall would surface much later as an unexplained row-count mismatch with the
rejection reasons long gone". So the ledger carries, per dropped constraint, the
item id, its pair, its arm, its bucket, the gist pair it was shown, how many
attempts it burned, and the VERBATIM final rejection reason. Not a category, not
a count: the reason string the gate produced, because a category is a summary
somebody has already interpreted.

Two record kinds share one file. A constraint row says a slot was dropped. A pair
row says a whole pair was refused because it lost every constraint in one of its
two lists -- `IntentCard.validate()` requires both to be non-empty, so a card that
lost one is not a smaller card, it is not a card. The two are one artifact rather
than two because they are one causal chain: the pair rows are consequences of the
constraint rows, and splitting them would let a reader hold half of it.

Nothing here runs on the agent's inference path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from arena.datasets.schema import ARMS


DROP_LOG_SCHEMA_VERSION = 1

# Committed, and in `data/` for the same reason the divergence log is (L-13):
# .gitignore excludes only catalog.jsonl, *.artifacts/ and releases/ from data/,
# whereas anything written under experiments/ outside baselines/ is silently
# ignored and would vanish -- which for THIS artifact would recreate the exact
# failure it exists to prevent.
DROP_LOG_ROOT = Path("data")

_SLOTS: tuple[str, ...] = ("hard_constraints", "soft_preferences")

# The `kind` discriminator. Written into every row rather than inferred from which
# keys are present, so a reader filters on a field instead of on a shape.
CONSTRAINT_KIND = "constraint"
PAIR_KIND = "pair"


def drop_log_path(corpus_name: str, *, root: Path = DROP_LOG_ROOT) -> Path:
    # Versioned with the corpus it describes, exactly as the divergence log and
    # the target snapshot are: what one corpus could not author says nothing about
    # the next, and one shared filename would silently mix two runs.
    return root / f"drops.{corpus_name}.jsonl"


@dataclass(frozen=True, slots=True)
class DroppedConstraint:
    """One constraint slot the attempt cap could not fill, and why."""

    schema_version: int
    item_id: str
    pair_id: str
    arm: str
    target: str
    slot: str
    position: int
    bucket: str
    gist_attribute: str
    gist_value: str
    attempts: int
    reason: str

    def validate(self) -> None:
        if self.schema_version != DROP_LOG_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported drop log schema version {self.schema_version}"
            )
        for name, value in (
            ("item id", self.item_id),
            ("pair id", self.pair_id),
            ("target", self.target),
            ("bucket", self.bucket),
        ):
            if not value:
                raise ValueError(f"a dropped constraint requires a {name}")
        if self.arm not in ARMS:
            raise ValueError(f"arm must be one of {ARMS}, got {self.arm!r}")
        if self.slot not in _SLOTS:
            raise ValueError(f"slot must be one of {_SLOTS}, got {self.slot!r}")
        if self.position < 0:
            raise ValueError(f"position must not be negative, got {self.position}")
        if self.attempts < 1:
            raise ValueError(
                f"a dropped constraint must have been attempted at least once,"
                f" got {self.attempts}"
            )
        # The load-bearing field. A drop row with no reason is a silent drop with
        # extra steps: it accounts for the shortfall numerically while discarding
        # the only thing that explains it.
        if not self.reason:
            raise ValueError(
                f"dropped constraint {self.item_id} carries no rejection reason;"
                " a drop with no recorded reason is the silent drop this ledger"
                " exists to prevent"
            )

    def as_record(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "attempts": self.attempts,
            "bucket": self.bucket,
            "gist_attribute": self.gist_attribute,
            "gist_value": self.gist_value,
            "item_id": self.item_id,
            "kind": CONSTRAINT_KIND,
            "pair_id": self.pair_id,
            "position": self.position,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "slot": self.slot,
            "target": self.target,
        }


@dataclass(frozen=True, slots=True)
class RefusedPair:
    """One pair emitted by nobody, because a whole constraint list went with the drops."""

    schema_version: int
    pair_id: str
    target: str
    arms: tuple[str, ...]
    missing_slots: tuple[str, ...]
    dropped_item_ids: tuple[str, ...]

    def validate(self) -> None:
        if self.schema_version != DROP_LOG_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported drop log schema version {self.schema_version}"
            )
        if not self.pair_id:
            raise ValueError("a refused pair requires a pair id")
        if not self.target:
            raise ValueError("a refused pair requires a target")
        unknown = tuple(arm for arm in self.arms if arm not in ARMS)
        if unknown:
            raise ValueError(f"refused pair names unknown arms {list(unknown)}")
        if not self.missing_slots:
            # A pair is refused BECAUSE it lost a list. A row that does not say
            # which list would record the refusal and lose the cause, which is the
            # same defect as a reasonless constraint row.
            raise ValueError(
                f"refused pair {self.pair_id} must name the list it lost"
            )
        unknown_slots = tuple(
            slot for slot in self.missing_slots if slot not in _SLOTS
        )
        if unknown_slots:
            raise ValueError(
                f"refused pair {self.pair_id} names unknown slots"
                f" {list(unknown_slots)}"
            )
        if sorted(self.missing_slots) != list(self.missing_slots):
            raise ValueError(
                f"refused pair {self.pair_id} must list its missing slots in"
                " sorted order"
            )
        if not self.dropped_item_ids:
            raise ValueError(
                f"refused pair {self.pair_id} must name the dropped constraints"
                " that emptied the list"
            )

    def as_record(self) -> dict[str, object]:
        return {
            "arms": list(self.arms),
            "dropped_item_ids": list(self.dropped_item_ids),
            "kind": PAIR_KIND,
            "missing_slots": list(self.missing_slots),
            "pair_id": self.pair_id,
            "schema_version": self.schema_version,
            "target": self.target,
        }


def _constraint_sort_key(record: DroppedConstraint) -> tuple[str, str, str, int]:
    return (record.pair_id, record.arm, record.slot, record.position)


def write_drop_log(
    path: Path,
    constraints: tuple[DroppedConstraint, ...],
    pairs: tuple[RefusedPair, ...],
) -> None:
    """Write the ledger. Always -- an empty ledger is a claim, an absent one is not.

    A run that dropped nothing still writes the file, so "no drops" is a statement
    the artifact makes rather than something a reader has to infer from a missing
    path. The row order is fixed and independent of input order for the same
    reason the divergence log's is: the file is committed, so a re-derivation that
    reordered rows would show as a diff indistinguishable from a changed record.

    Constraint rows come before pair rows because the pair rows are consequences.
    """
    for constraint in constraints:
        constraint.validate()
    for pair in pairs:
        pair.validate()
    rows = [
        record.as_record()
        for record in sorted(constraints, key=_constraint_sort_key)
    ] + [
        record.as_record()
        for record in sorted(pairs, key=lambda record: record.pair_id)
    ]
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_drop_log(path: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        # json.loads only -- never pickle, eval or yaml (T-02-11).
        try:
            record = json.loads(line)
        except ValueError as error:
            raise ValueError(
                f"invalid drop record in {path} at line {number}: {error}"
            ) from error
        if not isinstance(record, dict):
            raise ValueError(
                f"invalid drop record in {path} at line {number}:"
                f" expected an object, got {type(record).__name__}"
            )
        if record.get("kind") not in (CONSTRAINT_KIND, PAIR_KIND):
            raise ValueError(
                f"invalid drop record in {path} at line {number}:"
                f" unknown kind {record.get('kind')!r}"
            )
        rows.append(record)
    return tuple(rows)


def dropped_constraint_ids(rows: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    """The DISTINCT constraint slots a ledger accounts for, sorted.

    Distinct, because one slot is dropped once from the corpus but can be
    exhausted independently in each arm that tried to author it, and each attempt
    has its own verbatim reason worth keeping. Counting rows instead would
    overstate the shortfall by however many arms happened to fail on the same
    slot, and that count is compared against the corpus's own arithmetic.
    """
    return tuple(
        sorted(
            {
                str(row["item_id"])
                for row in rows
                if row.get("kind") == CONSTRAINT_KIND
            }
        )
    )


def refused_pair_ids(rows: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    identifiers = [
        str(row["pair_id"]) for row in rows if row.get("kind") == PAIR_KIND
    ]
    if len(set(identifiers)) != len(identifiers):
        # A pair refused twice would inflate the recorded shortfall while
        # describing one refusal, and the registry count is checked against this.
        raise ValueError(
            "drop ledger refuses the same pair twice:"
            f" {sorted({name for name in identifiers if identifiers.count(name) > 1})}"
        )
    return tuple(sorted(identifiers))


def drop_summary(
    constraints: tuple[DroppedConstraint, ...], pairs: tuple[RefusedPair, ...]
) -> tuple[tuple[str, int], ...]:
    """The stdout-facing counts. Ordered pairs, so the print order is fixed."""

    return (
        ("dropped_constraint_rows", len(constraints)),
        (
            "dropped_constraints",
            len({constraint.item_id for constraint in constraints}),
        ),
        ("refused_pairs", len(pairs)),
    )
