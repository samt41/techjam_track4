from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from pathlib import Path

from arena.candidate import CandidateSpec
from arena.leaderboard import spec_from_record
from arena.metrics import SessionOutcome
from arena.store import BASELINES_ROOT

# Control-vs-probe is a DIFFERENT statistical object from candidate-vs-candidate, which
# is the entire reason this module exists beside arena/adjudication.py instead of inside
# it (D-44). Nothing here was selected from a pool of k: there is one candidate, measured
# once, partitioned into arms by the `arm` field D-46 puts inside each corpus row. So the
# Holm family and the order-statistic selection debias that adjudicate applies are
# meaningless on these numbers, and this module must not import either of them. That
# absence is asserted by an AST scan in tests/test_arena_paired_contrast.py, whose
# scanner is in turn proven to fire on arena/adjudication.py -- an unfired scanner is
# indistinguishable from a clean module.

PAIRED_CONTRAST_SCHEMA_VERSION = 1

# A distinct pair_seed label, so the probe readout sits on its own RNG stream and cannot
# collide with an adjudication seed for the same two fingerprints (D-24).
BOOTSTRAP_LABEL = "paired-contrast-bootstrap"

# Both destinations sit OUTSIDE what .gitignore excludes, and that placement is
# load-bearing rather than tidy (L-13). `.gitignore` excludes every DIRECTORY under
# experiments/ and then re-includes experiments/baselines/, so the JSON is committed
# because it sits in the one re-included directory and the Markdown is committed because
# it sits at the top level of experiments/ beside LEADERBOARD.md. A generated artifact
# placed anywhere else under experiments/ is SILENTLY gitignored -- it would exist on the
# machine that produced it and nowhere else, making "frozen means committed" quietly
# false for a report the prose cites.
CONTRAST_JSON_PATH = BASELINES_ROOT / "paired_contrast.json"
CONTRAST_MARKDOWN_PATH = Path("experiments/PAIRED_CONTRAST.md")

_STRICT = "strict"
_SHARED_PAIRS = "shared-pairs"
RESTRICTIONS = (_STRICT, _SHARED_PAIRS)


class PairedContrastError(RuntimeError):
    """Raised when two arms cannot honestly be contrasted on `pair_id`."""


@dataclass(frozen=True, slots=True)
class PairedArm:
    """One arm of the contrast: a corpus partition plus the sessions it produced."""

    label: str
    # The `schema.ARMS` value this arm was partitioned on -- "control", "probe_sonnet" or
    # "probe_haiku". Held as a plain string rather than imported from
    # arena.datasets.schema so this module keeps the narrow import surface D-44 gives it;
    # the corpus rows are the authority for which arms exist, and arm_from_run names the
    # ones it actually found when a partition comes back empty.
    arm: str
    spec: CandidateSpec
    corpus_path: Path
    sessions: tuple[SessionOutcome, ...]
    # Ordered pairs, never a dict: a dict field breaks `frozen=True` hashability and
    # admits insertion-order variation, which is exactly the class of non-determinism
    # CandidateSpec.overrides is a tuple to avoid.
    pair_by_sample: tuple[tuple[str, str], ...]

    def validate(self) -> None:
        if not self.label:
            raise ValueError("paired arm label must not be empty")
        if not self.arm:
            raise ValueError("paired arm must name the corpus arm it partitioned on")
        sample_ids = [sample_id for sample_id, _ in self.pair_by_sample]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("paired arm maps one sample_id to two pair ids")
        if sorted(sample_ids) != sample_ids:
            raise ValueError("paired arm pair_by_sample must be in sorted sample order")
        pair_ids = [pair_id for _, pair_id in self.pair_by_sample]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("paired arm maps two sample ids to one pair id")

    def as_record(self) -> dict[str, object]:
        return {
            "label": self.label,
            "arm": self.arm,
            "fingerprint": self.spec.fingerprint,
            "dataset_sha256": self.spec.dataset_sha256,
            # as_posix(), never str(): a backslash-separated Windows path in a committed
            # record would make the JSON differ by platform.
            "corpus_path": self.corpus_path.as_posix(),
            "session_count": len(self.sessions),
        }


@dataclass(frozen=True, slots=True)
class McNemarResult:
    favouring_control: int
    favouring_probe: int
    discordant: int
    discordance_rate: float
    hit_rate_delta: float
    p_value: float

    def as_record(self) -> dict[str, object]:
        return {
            "favouring_control": self.favouring_control,
            "favouring_probe": self.favouring_probe,
            "discordant": self.discordant,
            "discordance_rate": self.discordance_rate,
            "hit_rate_delta": self.hit_rate_delta,
            "p_value": self.p_value,
        }


def spec_for_arm(run_directory: Path) -> CandidateSpec:
    """The one supported way to get an arm's spec, and therefore its two digests.

    L-10: `CandidateEntry` (arena/leaderboard.py) keeps the fingerprint but NOT the
    `catalog_sha256` and `dataset_sha256` it was computed from, so a caller building
    a PairedArm from `entry_from_record` cannot supply the digests
    `require_comparable_arms` needs and cannot reconstruct a matching spec either.
    Routing through `spec_from_record` is what keeps an arm's fingerprint identical to
    the leaderboard row it is reported beside; a hand-rolled reconstruction would
    silently mint a second fingerprint for one record.
    """
    return spec_from_record(run_directory)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: P(|B - n/2| >= |b - n/2|) under B ~ Binom(n, 0.5)."""
    # EXACT binomial rather than a continuity-corrected chi-square, and the choice is
    # driven by the size this rig actually operates at. At n = 300 pairs with the assumed
    # psi ~ 8% discordance, b + c ~ 24 -- BELOW the conventional b + c >= 25 threshold for
    # the normal approximation, which is precisely the regime where Edwards' correction is
    # least trustworthy. The exact test needs no approximation, no continuity fudge and no
    # third-party dependency: math.comb is stdlib, so this stays inside the zero-dependency
    # posture.
    for name, value in (("b", b), ("c", c)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an integer count")
        if value < 0:
            raise ValueError(f"{name} must be a non-negative count")
    total = b + c
    if total == 0:
        # No discordant pairs is no evidence either way, and the branch also stops a
        # division by 2**0 from being read as a meaningful tail. Returning 1.0 is the
        # honest answer: the two arms disagreed on nothing.
        return 1.0
    smaller = min(b, c)
    tail = sum(math.comb(total, index) for index in range(smaller + 1)) / 2**total
    # The clamp is load-bearing, not defensive: at b == c the smaller tail already exceeds
    # one half, so the doubled tail exceeds 1. Without it the function would return 1.246
    # for (5, 5), and any downstream `p <= alpha` gate would still pass while the reported
    # number was not a probability.
    return min(1.0, 2.0 * tail)


def require_comparable_arms(
    control: PairedArm,
    probe: PairedArm,
    *,
    allow_cross_corpus: bool = False,
) -> None:
    """The inverse of adjudicate's digest guard, corrected for D-46's locked design.

    A RECONCILIATION a future reader will otherwise mis-diagnose as a bug.
    `02-RESEARCH.md:754` and `02-VALIDATION.md`'s "D-45 inverse" row both assume control
    and probe live in two separate corpora and therefore carry two DIFFERENT
    `dataset_sha256` values, and both would have this function REFUSE a shared digest.
    D-46 and D-25 lock the opposite design: one `probe.v1` corpus of 700 rows carrying
    `control`, `probe_sonnet` and `probe_haiku` arms inside the sample rows, sized as a
    single 700-session / 300-target file. Both arms therefore come from ONE `run_arena
    run` and ONE digest. Requiring differing digests would make the phase's primary
    contrast impossible to express. Those two notes predate the reconciliation; this
    guard is correct and they are stale.

    The protective intent D-45 encodes is preserved by the two refusals that actually
    stop a corpus being contrasted with itself -- identical `arm` labels, and
    intersecting `sample_id` sets -- plus a refusal on a DIFFERING digest, which is the
    silently-bogus cross-corpus join D-45 exists to prevent and is reachable through plan
    02-10's `--probe-record` / `--probe-corpus` flags.

    Belt and braces, and which is which. The BRACES are structural: plan 02-03 namespaces
    every `pair_id` as `{corpus_stem}_{index:04d}` and its
    `validate_corpus(records, *, corpus_name)` REFUSES at load any row whose stem
    disagrees with its corpus, so no committed corpus can carry a foreign pair id, two
    corpora share no pair id at all, and `align_on_pair_id` raises on every one of them
    regardless of this flag. The enforcement point is the loader rather than the id
    format -- a regex constrains one id's shape and cannot express disjointness. The BELT
    is the refusal below, which makes the intent legible at the guard instead of implicit
    in an id convention.

    Fingerprint equality is deliberately NOT required. The fingerprint hashes `name`, and
    D-46's arms are labelled distinctly, so demanding equal fingerprints would forbid
    naming the arms at all. Every field that could confound a vocabulary delta with a
    configuration delta is checked individually instead. L-10: those fields live on
    `CandidateSpec`, which callers must obtain from `spec_for_arm` above -- a
    `CandidateEntry` carries neither digest.
    """
    for field_name in (
        "catalog_sha256",
        "code_revision",
        "code_revision_dirty",
        "overrides",
    ):
        if getattr(control.spec, field_name) != getattr(probe.spec, field_name):
            raise PairedContrastError(
                f"{probe.label} was measured against a different {field_name}"
                f" than {control.label}"
            )
    if control.arm == probe.arm:
        raise PairedContrastError(
            f"both arms partition on arm {control.arm!r}; a corpus arm cannot be"
            " contrasted with itself"
        )
    shared = {sample_id for sample_id, _ in control.pair_by_sample} & {
        sample_id for sample_id, _ in probe.pair_by_sample
    }
    if shared:
        raise PairedContrastError(
            f"the two arms share {len(shared)} sample_id values; one arm is being"
            " contrasted with itself"
        )
    if control.spec.dataset_sha256 != probe.spec.dataset_sha256 and (
        not allow_cross_corpus
    ):
        raise PairedContrastError(
            "the two arms carry different dataset_sha256 values"
            f" ({control.spec.dataset_sha256} and {probe.spec.dataset_sha256});"
            " joining two corpora on pair_id is the misreading D-45 exists to prevent."
            " Pass allow_cross_corpus=True only if you intend exactly that"
        )


def restrict_to_shared_pairs(
    control: dict[str, SessionOutcome],
    probe: dict[str, SessionOutcome],
) -> tuple[dict[str, SessionOutcome], dict[str, SessionOutcome], tuple[str, ...]]:
    """Narrow two arms to their shared pair ids, and REPORT what was dropped.

    The rule this module holds to, in one sentence: `align_on_pair_id` refuses;
    `restrict_to_shared_pairs` narrows on request and reports the count it dropped;
    nothing here ever discards a pair without recording the number. MEAS-06 requires n to
    be honest, and "100 pairs" and "100 of 300 pairs" are different claims that support
    different conclusions.

    This exists because the MEAS-13 generator-affinity contrast is STRUCTURALLY unequal
    rather than accidentally so: `arm_from_run` yields 300 `probe_sonnet` pairs and 100
    `probe_haiku` pairs from the one `probe.v1` record, because D-40 puts the Haiku arm on
    100 of the 300 targets. `align_on_pair_id` is right to raise on the 200 orphans, so
    the fix is an EXPLICIT, named, counted narrowing -- never a silent inner join, which
    would report 100 while the record still said the corpus held 300.
    """
    shared = sorted(set(control) & set(probe))
    if not shared:
        raise PairedContrastError(
            f"the two arms share no pair ids ({len(control)} and {len(probe)} pairs);"
            " there is no contrast to make"
        )
    dropped = tuple(sorted(set(control) ^ set(probe)))
    return (
        {key: control[key] for key in shared},
        {key: probe[key] for key in shared},
        dropped,
    )


def align_on_pair_id(
    control: dict[str, SessionOutcome],
    probe: dict[str, SessionOutcome],
) -> tuple[tuple[SessionOutcome, ...], tuple[SessionOutcome, ...]]:
    """Re-key both arms onto `pair_id` so the paired guard can join them.

    The L-8 fix, and it lives HERE at the call site rather than in
    arena/statistics.py. `_require_paired` joins on `sample_id`, and control and probe
    rows necessarily carry different `sample_id`s (D-46), so it rejects the arms
    as-handed. That guard is MEAS-04's structural guarantee that an independent-sample
    comparison is impossible to EXPRESS, and it must never be weakened to make these arms
    fit. `dataclasses.replace` onto the shared `pair_id` is what makes them genuinely
    paired, on the same idiom tests/arena_fixtures.py already uses for SessionOutcome.
    """
    missing = sorted(set(control) ^ set(probe))
    if missing:
        # Refuse rather than silently inner-joining: a dropped pair is a silently smaller
        # n, and MEAS-06 requires n to be honest. The opt-in narrowing path is
        # restrict_to_shared_pairs, which counts what it drops.
        raise ValueError(f"unmatched pair ids between arms: {missing[:5]}")
    keys = sorted(control)  # explicit sort; never dict insertion order
    return (
        tuple(dataclasses.replace(control[key], sample_id=key) for key in keys),
        tuple(dataclasses.replace(probe[key], sample_id=key) for key in keys),
    )


def arm_from_run(
    label: str,
    *,
    arm: str,
    spec: CandidateSpec,
    corpus_path: Path,
    corpus_rows: tuple[dict, ...],
    sessions: tuple[SessionOutcome, ...],
) -> PairedArm:
    """Partition ONE run's sessions down to a single corpus arm.

    The D-46 entry point: one 700-session `probe.v1` run becomes three PairedArms, so the
    contrast never needs two runs and therefore never needs two digests. `pair_id` and
    `arm` come from the corpus JSONL rather than from the run record, and this join
    happens only AFTER `evaluate()` has returned -- ground truth never reaches the Agent.
    """
    wanted: dict[str, str] = {}
    present: set[str] = set()
    for row in corpus_rows:
        row_arm = str(row["arm"])
        present.add(row_arm)
        if row_arm != arm:
            continue
        sample_id = str(row["sample_id"])
        pair_id = str(row["pair_id"])
        if sample_id in wanted:
            raise PairedContrastError(
                f"corpus row {sample_id} appears twice in arm {arm!r}"
            )
        wanted[sample_id] = pair_id
    if not wanted:
        raise PairedContrastError(
            f"no corpus rows carry arm {arm!r}; the arms present are"
            f" {sorted(present)}"
        )
    partitioned = tuple(item for item in sessions if item.sample_id in wanted)
    if not partitioned:
        raise PairedContrastError(
            f"arm {arm!r} matched {len(wanted)} corpus rows but no run sessions"
        )
    built = PairedArm(
        label=label,
        arm=arm,
        spec=spec,
        corpus_path=corpus_path,
        sessions=partitioned,
        pair_by_sample=tuple(
            (sample_id, wanted[sample_id]) for sample_id in sorted(wanted)
        ),
    )
    built.validate()
    return built


def sessions_by_pair(arm: PairedArm) -> dict[str, SessionOutcome]:
    """Join an arm's sessions to its pair ids, refusing any gap or collision.

    The run record does not carry `pair_id`: it comes from the corpus JSONL (D-46), and
    this join runs only after the evaluation returned, so the mapping is a post-hoc
    reporting artefact and never an input to the Agent.
    """
    mapping = dict(arm.pair_by_sample)
    joined: dict[str, SessionOutcome] = {}
    for item in arm.sessions:
        pair_id = mapping.get(item.sample_id)
        if pair_id is None:
            raise PairedContrastError(
                f"arm {arm.label} session {item.sample_id} carries no pair_id"
            )
        if pair_id in joined:
            raise PairedContrastError(
                f"arm {arm.label} maps two sessions to pair_id {pair_id}"
            )
        joined[pair_id] = item
    return joined


def mcnemar_from_arms(
    control: tuple[SessionOutcome, ...],
    probe: tuple[SessionOutcome, ...],
) -> McNemarResult:
    """The discordant-pair readout over two ALREADY-ALIGNED arms."""
    if len(control) != len(probe):
        raise PairedContrastError("mcnemar requires two arms of equal length")
    if not control:
        raise PairedContrastError("mcnemar requires at least one pair")
    favouring_control = sum(
        1
        for left, right in zip(control, probe)
        if left.hit and not right.hit
    )
    favouring_probe = sum(
        1
        for left, right in zip(control, probe)
        if right.hit and not left.hit
    )
    count = len(control)
    discordant = favouring_control + favouring_probe
    # The D-28 caveat, and the reason the discordance RATE is emitted rather than only the
    # delta: psi is a ceiling as well as a parameter. With psi = 0.08 the maximum
    # representable delta HR@10 is 0.08, so the 100-pair cross-check's planned MDD of 0.08
    # sits exactly at that ceiling and would need every expected discordant pair to fall
    # one way. Reporting the OBSERVED rate is what lets a reader recompute the MDD post hoc
    # from what actually happened instead of from the a-priori assumption.
    #
    # Sign convention matches paired_bootstrap's delta = candidate - baseline, with the
    # probe in the candidate position: a probe that finds MORE targets reports a POSITIVE
    # delta. `02-RESEARCH.md`'s verified table prints (b - c) / n because it tabulates a
    # control-to-probe DROP as a positive number; the same magnitudes, the other sign.
    return McNemarResult(
        favouring_control=favouring_control,
        favouring_probe=favouring_probe,
        discordant=discordant,
        discordance_rate=discordant / count,
        hit_rate_delta=(favouring_probe - favouring_control) / count,
        p_value=mcnemar_exact(favouring_control, favouring_probe),
    )
