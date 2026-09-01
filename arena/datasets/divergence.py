"""The two acceptance gates that make the paraphrase probe interpretable.

D-33 (`preserves_bucket`) refuses a probe constraint whose wording flips the
bucket the harness classifies it into. That bucket decides which asked attribute
unlocks the constraint (`local_evaluator.py:174-185`), so a flipped bucket
changes the *disclosure mechanics* on top of the vocabulary and the measured
control-vs-probe delta then mixes two effects and explains nothing.

D-34 (`measure_text` / `measure`) quantifies what the re-wording actually
achieved: the share of a phrase's content tokens that still appear in the
target's own `searchable_text`, plus any verbatim 2-gram shared with it. It is a
measurement, not an assertion — the control arm is measured too (mean 0.9857 on
the 200 public targets), and that contrast is the reportable result.

Both halves work in the agent's own normalized token space, so a "no overlap"
claim is made in the space retrieval actually sees rather than in raw characters.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from arena.evaluator_bridge import classify_constraint, searchable_text
from starter.shopping_agent.constraint_extractor import STOPWORDS
from starter.shopping_agent.text_normalization import (
    TOKEN_RE,
    normalize_text,
    search_terms,
)


# Transcribed verbatim from classify_constraint (local_evaluator.py:138-151), in
# its first-match clause order.
#
# This table exists ONLY to compute which substring the harness pinned, so the
# D-34 overlap measurement can exclude it: a probe constraint MUST retain a
# classifier trigger to keep its bucket, and counting that forced token as
# lexical reuse would understate every divergence score. The bucket DECISION is
# never taken here -- it always goes through classify_constraint via the seam.
# Re-implementing the decision locally would fork the authority on disclosure
# mechanics (F-05), and this copy would drift silently the moment the harness
# changed. ClassifierAgreementTest pins the two together on eleven phrases.
#
# The colour clause has SEVEN substrings, one of which is the literal word
# "color" (D-51, L-4). The twelve-entry COLOR_RE at local_evaluator.py:24 is a
# different list serving a different function (intent_card), and its five extra
# colour words route to `feature`, not `color`. A gate built on COLOR_RE pins a
# token the classifier never looked at and misreports overlap in both
# directions, so those five words appear nowhere in this module.
#
# Matching is substring containment (`in`), not `\b` -- unlike MATERIAL_RE and
# COLOR_RE, which do use word boundaries. That difference is what makes zero
# overlap attainable at all: "leathery" contains "leather" and so keeps the
# `material` bucket, while the token `leathery` appears in 0 of the 50,000
# products.
_CLASSIFIER_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("budget", ("budget",)),
    (
        "material",
        (
            "cotton",
            "polyester",
            "nylon",
            "leather",
            "wool",
            "spandex",
            "silk",
            "rayon",
            "fabric",
        ),
    ),
    ("color", ("color", "black", "white", "blue", "red", "pink", "green")),
    ("size", ("size", "sizing", "width", "wide", "narrow")),
    ("style", ("department", "style", "fit", "sleeve", "neck")),
    ("use_case", ("hiking", "running", "gym", "winter", "outdoor", "work")),
    ("feature", ()),
)

# The second half of the budget clause. Compiled once, and deliberately the same
# pattern text as local_evaluator.py:139 rather than a tidier equivalent.
_BUDGET_NUMERIC_RE = re.compile(r"(?:\$|<=|under)\s*\d")

# The flat union of clauses 1-6. `feature` is the residual default and 50.5% of
# all control constraints, so most re-authoring starts from a feature-bucket
# phrase -- and an innocuous re-wording that happens to contain "fit", "work",
# "size", "wide", "neck", "style" or any material substring flips its bucket
# without the author noticing (L-5). Plan 02-07 embeds this list in the
# authoring prompt; the gate below is the backstop, not the first line of
# defence.
_FEATURE_TRIGGER_SUBSTRINGS: frozenset[str] = frozenset(
    keyword for _, keywords in _CLASSIFIER_KEYWORDS for keyword in keywords
)

# Transcribed from the ARMS contract in plan 02-03, which builds
# arena/datasets/schema.py in the same wave as this module and is its authority.
# A local copy exists only because the two land in parallel; ArmVocabularyTest
# pins this tuple against schema.ARMS as soon as that module is importable, so
# the transcription cannot outlive the wave undetected.
_ARMS: tuple[str, ...] = ("control", "probe_haiku", "probe_sonnet")

_SLOTS: tuple[str, ...] = ("hard_constraints", "soft_preferences")

DIVERGENCE_LOG_SCHEMA_VERSION = 1

# Committed, not generated-and-discarded (L-13): Roadmap SC3 asks for a measured
# overlap ratio reported for every probe pair, which only a persisted per-pair
# record can answer. `data/` is the right home because .gitignore excludes just
# catalog.jsonl, *.artifacts/ and releases/ from it, whereas anything written
# under experiments/ outside baselines/ is silently ignored and would vanish.
DIVERGENCE_LOG_ROOT = Path("data")


def ordered_tokens(value: str) -> tuple[str, ...]:
    # NOT search_terms: it de-duplicates via dict.fromkeys
    # (text_normalization.py:47), which collapses the adjacency the 2-gram half
    # of D-34 measures. Same token space, order and multiplicity preserved.
    return tuple(TOKEN_RE.findall(normalize_text(value)))


def bigrams(value: str) -> frozenset[tuple[str, str]]:
    tokens = ordered_tokens(value)
    return frozenset(zip(tokens, tokens[1:]))


def carries_content(
    pair: tuple[str, str], *, stopwords: frozenset[str] = STOPWORDS
) -> bool:
    """True when a 2-gram holds at least one word that says something about a product.

    The adjacency half of D-34 asks whether a phrase copied a verbatim span of the
    target's text. `with a`, `it s`, `to be` and `to the` are spans of English, not
    spans of this product: every catalog listing long enough contains them, so a
    probe phrase sharing one has demonstrated nothing about lexical reuse. Charging
    them made the gate reject on grammar. Measured on the 300-pair run: 12 of 202
    overlap rejections named an all-stopword 2-gram and no shared content word at
    all -- `with a` seven times, `it s` and `to be` three each, `to the` twice.

    `rubber sole`, `snap closure` and `moisture wicking` keep rejecting, and that is
    the property this predicate has to preserve rather than merely permit: ONE
    content word is enough, so only a pair made ENTIRELY of function words is
    excused. The pinned classifier keyword is content here even though
    `content_tokens` excludes it, which is deliberate -- `with leather` is copied
    phrasing whether or not D-33 forced the phrase to carry `leather`.

    Same `STOPWORDS` object the content half uses (D-54), never a second list.
    """
    return any(token not in stopwords for token in pair)


def pinned_tokens(phrase: str) -> frozenset[str]:
    """Return the tokens a phrase is only carrying to hold its bucket.

    A probe constraint has to keep whichever substring `classify_constraint`
    routes on, or D-33 rejects it. Charging that forced substring to the phrase
    as lexical reuse would put a floor under every score in six of the seven
    buckets, so D-34 excludes it -- and excludes only it. Exactly one keyword is
    pinned, the first one the harness would have short-circuited on, because
    every additional exclusion is content the phrase gets away with reusing.

    The consequence worth stating: `color` is itself one of the seven colour
    substrings, so for a target whose control colour word is one of the five
    that COLOR_RE matches but the colour clause does not, the pinned token is
    the literal word `color` and the colour word itself stays fully chargeable.

    Returns an empty set for the residual `feature` bucket, which routes on no
    keyword at all and therefore pins nothing.
    """
    lowered = normalize_text(phrase)
    tokens = ordered_tokens(phrase)
    for bucket, keywords in _CLASSIFIER_KEYWORDS:
        matched: str | None = next(
            (keyword for keyword in keywords if keyword in lowered), None
        )
        if matched is None and bucket == "budget":
            # The clause also fires on a bare "$40" or "under 40", where there is
            # no keyword to pin. Pin the tokens inside the matched span instead.
            #
            # findall rather than the obvious .search: SolvabilityAbsenceTest
            # forbids EVERY attribute access named `search` in this module, so
            # that "the probe pipeline never runs retrieval" (D-35, L-3) is
            # checkable without the scanner needing to know which receiver is a
            # regex and which is a backend. A blunt guard with one awkward call
            # site beats a guard with a carve-out that a backend call could hide
            # in. The pattern has no capturing group, so findall yields whole
            # matches.
            numeric = _BUDGET_NUMERIC_RE.findall(lowered)
            if numeric:
                span = frozenset(TOKEN_RE.findall(numeric[0]))
                return frozenset(
                    token
                    for token in tokens
                    if any(part in token for part in span)
                ) | span
        if matched is None:
            continue
        return frozenset(
            token for token in tokens if matched in token
        ) | {matched}
    return frozenset()


def content_tokens(
    phrase: str,
    *,
    pinned: frozenset[str],
    stopwords: frozenset[str] = STOPWORDS,
) -> tuple[str, ...]:
    # Order-preserving and NOT de-duplicated: the denominator of overlap_ratio is
    # a token count, and the measured control baseline of 0.9857 was taken this
    # way. Collapsing repeats here would silently redefine the ratio.
    return tuple(
        token
        for token in ordered_tokens(phrase)
        if token not in stopwords and token not in pinned
    )


def preserves_bucket(control_phrase: str, probe_phrase: str) -> bool:
    """D-33: the probe must classify into its control's bucket.

    `customer_reply` only discloses a constraint when the agent asks about the
    attribute `classify_constraint` assigns it (local_evaluator.py:180), so the
    bucket is disclosure mechanics, not a label. A paraphrase that moves the
    bucket changes which question unlocks the constraint as well as the words,
    and the arm-to-arm delta stops being attributable to vocabulary (F-05).

    The comparison calls the harness's own classifier through the seam in both
    directions; `_CLASSIFIER_KEYWORDS` is never consulted here.
    """
    return classify_constraint(control_phrase) == classify_constraint(probe_phrase)


@dataclass(frozen=True, slots=True)
class DivergenceReport:
    bucket: str
    content_token_count: int
    overlap_ratio: float
    overlapping_tokens: tuple[str, ...]
    shared_bigrams: tuple[str, ...]
    passes: bool

    def validate(self) -> None:
        if not 0.0 <= self.overlap_ratio <= 1.0:
            raise ValueError(
                f"overlap ratio must be within [0.0, 1.0], got {self.overlap_ratio}"
            )
        if self.content_token_count < 0:
            raise ValueError(
                f"content token count must not be negative, got "
                f"{self.content_token_count}"
            )
        # A report that claims it passed while naming an overlapping token or a
        # shared 2-gram is the one shape a committed record must not be able to
        # express: it would read green in the log and be a failed gate in fact.
        clean = not self.overlapping_tokens and not self.shared_bigrams
        if self.passes is not clean:
            raise ValueError(
                f"passes={self.passes} contradicts overlapping_tokens="
                f"{self.overlapping_tokens} and shared_bigrams={self.shared_bigrams}"
            )

    def as_record(self) -> dict[str, object]:
        return {
            "bucket": self.bucket,
            "content_token_count": self.content_token_count,
            "overlap_ratio": self.overlap_ratio,
            "overlapping_tokens": list(self.overlapping_tokens),
            "shared_bigrams": list(self.shared_bigrams),
            "passes": self.passes,
        }


def measure_text(
    phrase: str,
    target_text: str,
    *,
    stopwords: frozenset[str] = STOPWORDS,
) -> DivergenceReport:
    """D-34: measure a phrase's lexical reuse of one target's own text.

    Two independent halves, because a token-set check and an adjacency check
    catch different failures. Overlap uses `search_terms`, whose de-duplication
    is harmless for set membership. Adjacency uses undeduplicated
    `ordered_tokens`, because `search_terms` destroys the token order a 2-gram
    is made of (L-15).

    The 2-gram half runs over the FULL probe token sequence, stopwords and
    pinned keyword included, with one exclusion: a 2-gram made ENTIRELY of
    stopwords is not evidence of anything (see `carries_content`). "rubber sole"
    is copied phrasing however its tokens are individually classified and still
    rejects; "with a" is a span of English and no longer does.
    """
    target_tokens = frozenset(search_terms(target_text))
    target_bigrams = bigrams(target_text)
    probe_sequence = ordered_tokens(phrase)
    content = content_tokens(
        phrase, pinned=pinned_tokens(phrase), stopwords=stopwords
    )
    overlapping = tuple(token for token in content if token in target_tokens)
    shared = tuple(
        pair
        for pair in zip(probe_sequence, probe_sequence[1:])
        if pair in target_bigrams and carries_content(pair, stopwords=stopwords)
    )
    report = DivergenceReport(
        bucket=classify_constraint(phrase),
        content_token_count=len(content),
        overlap_ratio=(len(overlapping) / len(content)) if content else 0.0,
        overlapping_tokens=tuple(sorted(set(overlapping))),
        shared_bigrams=tuple(sorted({" ".join(pair) for pair in shared})),
        passes=not overlapping and not shared,
    )
    report.validate()
    return report


# The split from measure_text is load-bearing, not ergonomic. Plan 02-11's
# corpus-wide sweep has to re-derive every committed ratio without opening the
# 580 MB artifact -- catalog-freedom is a sign-off item -- and it does that by
# feeding measure_text the committed searchable_text snapshot for each target.
# This entry point stays for the callers that already hold the product dict, and
# it must never grow logic of its own: a second implementation here would let
# the two paths diverge and the sweep would stop being evidence. Hence the
# one-line body, which is also what keeps the delegation greppable.
def measure(
    phrase: str, product: dict[str, object], *, stopwords: frozenset[str] = STOPWORDS
) -> DivergenceReport:
    return measure_text(phrase, searchable_text(product), stopwords=stopwords)


def contradicts(
    phrase: str,
    product: dict[str, object],
    admitted_values: frozenset[str],
) -> bool:
    """D-35: True when a phrase asserts admitted vocabulary the target lacks.

    The only automated correctness check on an authored constraint. Solvability
    is guaranteed by construction (D-32) -- the control arm is the harness's own
    `intent_card` over a real catalog product -- so it is deliberately NOT
    re-checked by running retrieval. A retrieval-based recheck would launder the
    vocabulary gap the probe exists to expose out of the corpus before anything
    was measured (L-3), which is why this module never touches a search backend.

    Substring containment, matching the harness's own semantics, so "wool"
    asserted inside "woollen" on a leather boot is caught.
    """
    lowered = normalize_text(phrase)
    target = normalize_text(searchable_text(product))
    return any(
        normalize_text(value) in lowered and normalize_text(value) not in target
        for value in sorted(admitted_values)
    )


def divergence_log_path(
    corpus_name: str, *, root: Path = DIVERGENCE_LOG_ROOT
) -> Path:
    # Versioned with the corpus it describes, exactly as D-43 versions the corpus
    # itself: a ratio measured against one corpus's targets says nothing about
    # the next corpus's, so one shared filename would silently mix two runs.
    return root / f"divergence.{corpus_name}.jsonl"


@dataclass(frozen=True, slots=True)
class DivergenceRecord:
    schema_version: int
    pair_id: str
    arm: str
    position: int
    slot: str
    phrase: str
    bucket: str
    content_token_count: int
    overlap_ratio: float
    overlapping_tokens: tuple[str, ...]
    shared_bigrams: tuple[str, ...]
    passes: bool

    def validate(self) -> None:
        if self.schema_version != DIVERGENCE_LOG_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported divergence log schema version {self.schema_version}"
            )
        if not self.pair_id:
            raise ValueError("divergence record requires a pair id")
        if self.arm not in _ARMS:
            raise ValueError(
                f"arm must be one of {_ARMS}, got {self.arm!r}"
            )
        if self.position < 0:
            raise ValueError(
                f"position must not be negative, got {self.position}"
            )
        if self.slot not in _SLOTS:
            raise ValueError(f"slot must be one of {_SLOTS}, got {self.slot!r}")
        self.report().validate()

    def report(self) -> DivergenceReport:
        return DivergenceReport(
            bucket=self.bucket,
            content_token_count=self.content_token_count,
            overlap_ratio=self.overlap_ratio,
            overlapping_tokens=self.overlapping_tokens,
            shared_bigrams=self.shared_bigrams,
            passes=self.passes,
        )

    def as_record(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "pair_id": self.pair_id,
            "arm": self.arm,
            "position": self.position,
            "slot": self.slot,
            "phrase": self.phrase,
            **self.report().as_record(),
        }


def record_from_report(
    report: DivergenceReport,
    *,
    pair_id: str,
    arm: str,
    position: int,
    slot: str,
    phrase: str,
) -> DivergenceRecord:
    # The CONTROL arm's records are written too, not only the probe's. D-34 asks
    # for the control arm's overlap to be measured and reported so the contrast
    # between arms is quantified rather than asserted, and the measured control
    # mean (~0.9857) is the number a probe ratio is read against.
    return DivergenceRecord(
        schema_version=DIVERGENCE_LOG_SCHEMA_VERSION,
        pair_id=pair_id,
        arm=arm,
        position=position,
        slot=slot,
        phrase=phrase,
        bucket=report.bucket,
        content_token_count=report.content_token_count,
        overlap_ratio=report.overlap_ratio,
        overlapping_tokens=report.overlapping_tokens,
        shared_bigrams=report.shared_bigrams,
        passes=report.passes,
    )


def _record_sort_key(record: DivergenceRecord) -> tuple[str, str, str, int]:
    return (record.pair_id, record.arm, record.slot, record.position)


def write_divergence_log(
    path: Path, records: tuple[DivergenceRecord, ...]
) -> None:
    # Canonical form and a fixed record order are not cosmetic: the log is
    # committed, so a re-derivation that reorders rows would show as a diff and
    # be indistinguishable from a changed measurement.
    for record in records:
        record.validate()
    path.write_text(
        "".join(
            json.dumps(record.as_record(), sort_keys=True) + "\n"
            for record in sorted(records, key=_record_sort_key)
        ),
        encoding="utf-8",
    )


def load_divergence_log(path: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        # json.loads only -- never pickle, eval or yaml.
        try:
            record = json.loads(line)
        except ValueError as error:
            raise ValueError(
                f"invalid divergence record in {path} at line {number}: {error}"
            ) from error
        if not isinstance(record, dict):
            raise ValueError(
                f"invalid divergence record in {path} at line {number}: "
                f"expected an object, got {type(record).__name__}"
            )
        rows.append(record)
    return tuple(rows)


def coverage(
    records: tuple[DivergenceRecord, ...],
) -> tuple[tuple[str, str, str, int], ...]:
    """The sorted `(pair_id, arm, slot, position)` keys the log accounts for.

    Plan 02-11 asserts this equals the committed corpus's constraint count,
    which is how Roadmap SC3's "for every probe pair" becomes machine-checked
    instead of assumed. It refuses a duplicated key because a log that counted
    one constraint twice would satisfy a bare length check while leaving a real
    constraint unmeasured -- inflated coverage is worse than missing coverage,
    because it reads as complete.
    """
    keys = [_record_sort_key(record) for record in records]
    counts: dict[tuple[str, str, str, int], int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    if duplicates:
        detail = ", ".join(f"{key} appears {counts[key]} times" for key in duplicates)
        raise ValueError(f"duplicate divergence record keys: {detail}")
    return tuple(sorted(keys))


def bucket_summary(
    reports: tuple[DivergenceReport, ...],
) -> tuple[dict[str, object], ...]:
    """Per-bucket divergence, because one aggregate number would mislead.

    The buckets do not behave alike and are not the same size. `material` and
    `feature` carry most of the mass; `size` and `use_case` scale to n around 11
    and 4 at probe scale, which is descriptive noise, and presenting six equal
    rows would imply six equally supported findings (D-34). Reporting the n
    alongside each row is what lets a reader discount the thin ones.

    A bucket with no reports is SKIPPED rather than emitted as a zero-n row: the
    statistics below have no defined value on an empty sequence, and
    arena/metrics.py:126-127 refuses that case rather than inventing one (L-18).
    Fabricating a 0.0 mean would read as measured divergence where nothing was
    measured at all -- and 0.0 is the BEST possible score, so the fabricated row
    would flatter the probe precisely where it has no evidence.

    That skip is structural, not a filter: the groups are built from the reports
    themselves, so a bucket nobody reported has no key and cannot reach a
    statistic. Enumerating the seven classifier buckets and looking each one up
    is the shape that reintroduces the bug, which is what BucketSummaryTest
    pins. An empty input returns () by the same construction.
    """
    grouped: dict[str, list[DivergenceReport]] = {}
    for report in reports:
        grouped.setdefault(report.bucket, []).append(report)
    return tuple(
        {
            "bucket": bucket,
            "n": len(members),
            "mean_overlap_ratio": statistics.fmean(
                member.overlap_ratio for member in members
            ),
            "median_overlap_ratio": statistics.median(
                member.overlap_ratio for member in members
            ),
            "min_overlap_ratio": min(member.overlap_ratio for member in members),
            "pass_count": sum(1 for member in members if member.passes),
        }
        for bucket, members in sorted(grouped.items())
    )
