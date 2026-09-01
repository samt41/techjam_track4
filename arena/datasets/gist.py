"""The D-32 attribute gist: the only thing an authoring model ever sees about a target.

Two mechanisms, one per attribute class, and they are not interchangeable:

* For the canonical structured attributes (`color`, `material`, `size`, `style`)
  the anti-circularity mechanism is the document-frequency floor. A value carried
  by at least `_GIST_DF_FLOOR` of 50,000 products is shared vocabulary and cannot
  identify one target, so it is admitted verbatim on purpose -- D-32's own worked
  example is `material=leather`.
* For `feature` the DF floor is not the admission rule at all (L-6). Its high-DF
  survivors are verbatim catalog boilerplate, so every admitted feature pair is
  routed through the committed D-52 abstraction table and the catalog string never
  leaves this module.

`prompt_payload_strings` is the single narrow data-flow surface: nothing else may
reach an authoring prompt, which is what lets `tests/test_datasets_gist.py` assert
MEAS-12 as a property of the code rather than as prompt discipline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from arena.store import sha256_file, write_json
from starter.shopping_agent.models import Attribute
from starter.shopping_agent.text_normalization import normalize_text


if TYPE_CHECKING:  # pragma: no cover - annotation-only, never imported at use time
    from starter.shopping_agent.catalog_index import CatalogIndex


GIST_SCHEMA_VERSION = 1

# Resolved from this file's location, never the process working directory, so the
# assets load identically however the module is invoked (tests/arena_fixtures.py:10-14).
_ASSETS_DIRECTORY = Path(__file__).resolve().parent / "assets"
GIST_VOCABULARY_PATH = _ASSETS_DIRECTORY / "gist_vocabulary.json"
FEATURE_ABSTRACTIONS_PATH = _ASSETS_DIRECTORY / "feature_abstractions.json"

# A value carried by at least 10 of the 50,000 catalog products (0.02%) is general
# vocabulary and cannot identify one target; a value carried by a single product is
# that product's idiosyncratic phrasing and is exactly the leak D-32 exists to
# prevent. Measured retention at this floor: material 65 of 434 distinct values,
# color 24 of 1,127, size 11 of 330, style 19 of 844. Below 5 the floor stops
# excluding anything useful (color keeps 32, size 27); above 25 the color and size
# cells collapse to 13 and 5 and most targets lose their real attribute values from
# the gist entirely. 10 is the widest floor that still admits a usable gist.
_GIST_DF_FLOOR = 10

# Governs which feature values earn a row in the D-52 abstraction table, and is
# deliberately a different number from _GIST_DF_FLOOR: for `feature` the DF floor is
# not the admission rule (L-6). 136,232 distinct feature values, 11,522 at DF>=2 and
# 90 at DF>=100, and the high-DF survivors are verbatim catalog boilerplate. So this
# floor bounds how much hand-written table a human must review, while the abstraction
# itself -- not the frequency -- is what keeps the catalog string out of the prompt.
_FEATURE_ABSTRACTION_DF_FLOOR = 100

# Five attributes, and the exclusions matter more than the inclusions.
# `brand` and `category`: `classify_constraint` can never return either (F-06 error 3),
# so a pair in those buckets could not be honoured downstream -- and a brand name is a
# direct identity leak, 19,747 distinct values against 50,000 products.
# `budget`: measured at 0 of 798 control-card constraints (L-7), so it never appears in
# a control card and a gist pair for it would describe nothing the arm can be compared
# against.
# `use_case` and `other` are absent for a different reason: the artifact's `attributes`
# table has zero rows for either (D-52), so there is nothing to exclude. They are not
# a policy choice and must not be re-added by someone reading this tuple as one.
_GIST_ATTRIBUTES = (
    Attribute.COLOR,
    Attribute.FEATURE,
    Attribute.MATERIAL,
    Attribute.SIZE,
    Attribute.STYLE,
)

# The structured attributes read straight off the product's `details`, in the same
# order and by the same key as the artifact builder's `_attribute_values`.
_STRUCTURED_ATTRIBUTES = (
    Attribute.COLOR,
    Attribute.MATERIAL,
    Attribute.SIZE,
    Attribute.STYLE,
)

# Mirrors catalog_artifacts.py's material and keyed-feature recovery, because a target
# frequently states its material or color only inside a free-text feature string and a
# gist built from `details` alone would be thin for exactly those products. The
# builder's own DF floors are NOT reproduced: recovery here is gated on the committed
# gist vocabulary instead, which is a strictly tighter filter (DF>=10 against the
# builder's DF>=2), so nothing idiosyncratic can enter through this path.
_MATERIAL_TOKEN_RE = re.compile(r"[a-z]+")
_MATERIAL_PERCENT_RE = re.compile(r"\d+\s*%|\bpercent\b")
_MATERIAL_BLEND_RE = re.compile(r"\band\b|[/,&+]")
_KEYED_FEATURE_RE = re.compile(r"^([a-z][a-z ]+?)\s*:\s*(.+)$")
_KEYED_VALUE_SPLIT_RE = re.compile(r";|\b[a-z ]+\s*:")
_KEYED_FEATURE_ATTRIBUTES = {
    "color": Attribute.COLOR,
    "colour": Attribute.COLOR,
    "size": Attribute.SIZE,
    "style": Attribute.STYLE,
}


class GistError(RuntimeError):
    """Raised when a gist asset is missing, malformed, or of an unknown schema."""


@dataclass(frozen=True, slots=True)
class GistPair:
    attribute: str
    value: str

    def validate(self) -> None:
        if not self.attribute:
            raise ValueError("gist pair attribute must be non-empty")
        if not self.value:
            raise ValueError("gist pair value must be non-empty")
        # Enforced here rather than in prompt_payload_strings so the structural
        # guarantee "one '=' per payload string" holds at construction, not at
        # serialization -- a caller cannot build a pair that would break the parse.
        if "=" in self.attribute or "=" in self.value:
            raise ValueError("gist pair fields must not contain '='")

    def as_record(self) -> dict[str, str]:
        return {"attribute": self.attribute, "value": self.value}


@dataclass(frozen=True, slots=True)
class GistVocabulary:
    schema_version: int
    df_floor: int
    feature_abstraction_df_floor: int
    catalog_sha256: str
    # attribute name -> admitted values, ordered by descending document frequency
    # with the value string as tie-break. Ordered tuples rather than dicts because
    # this structure is serialized and compared byte for byte (L-17).
    values: tuple[tuple[str, tuple[str, ...]], ...]
    # verbatim catalog feature value -> its abstract (attribute, token) pair.
    abstractions: tuple[tuple[str, tuple[str, str]], ...]

    def validate(self) -> None:
        if self.schema_version != GIST_SCHEMA_VERSION:
            raise ValueError(
                f"gist vocabulary schema_version must be {GIST_SCHEMA_VERSION}"
            )
        if self.df_floor < 1 or self.feature_abstraction_df_floor < 1:
            raise ValueError("gist document-frequency floors must be positive")
        if not self.catalog_sha256:
            raise ValueError("gist vocabulary must record a catalog fingerprint")
        names = [name for name, _ in self.values]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("gist vocabulary attributes must be sorted and unique")

    def abstract_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset(pair for _, pair in self.abstractions)

    def abstract_attributes(self) -> frozenset[str]:
        return frozenset(attribute for _, (attribute, _) in self.abstractions)

    def admits(self, attribute: str, value: str) -> bool:
        if (attribute, value) in self.abstract_pairs():
            return True
        for name, admitted in self.values:
            if name == attribute:
                return value in admitted
        return False

    def as_record(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "df_floor": self.df_floor,
            "feature_abstraction_df_floor": self.feature_abstraction_df_floor,
            "catalog_sha256": self.catalog_sha256,
            "values": {name: list(admitted) for name, admitted in self.values},
            "abstractions": {
                value: [attribute, token]
                for value, (attribute, token) in self.abstractions
            },
        }


def load_feature_abstractions(
    path: Path = FEATURE_ABSTRACTIONS_PATH,
) -> tuple[tuple[str, tuple[str, str]], ...]:
    """Read the committed D-52 table, dropping the rows recorded with a null pair."""
    # json.loads only -- never pickle, eval, or yaml.
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["abstractions"]
        floor = int(payload["df_floor"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GistError(f"malformed feature abstraction table at {path}: {error}") from error
    except OSError as error:
        raise GistError(f"cannot read feature abstraction table at {path}: {error}") from error
    if floor != _FEATURE_ABSTRACTION_DF_FLOOR:
        raise GistError(
            f"feature abstraction table at {path} records df_floor {floor}, "
            f"expected {_FEATURE_ABSTRACTION_DF_FLOOR}"
        )
    admitted: list[tuple[str, tuple[str, str]]] = []
    for row in rows:
        try:
            value = str(row["value"])
            attribute = row["attribute"]
            token = row["token"]
        except (KeyError, TypeError) as error:
            raise GistError(f"malformed abstraction row in {path}: {error}") from error
        # A null pair means the source value carries nothing recoverable. It is
        # recorded in the table so coverage stays auditable, and excluded here.
        if attribute is None or token is None:
            continue
        admitted.append((value, (str(attribute), str(token))))
    return tuple(sorted(admitted, key=lambda row: row[0]))


def load_vocabulary(path: Path = GIST_VOCABULARY_PATH) -> GistVocabulary:
    """Read the committed vocabulary. The only path any non-CLI caller uses.

    Deliberately reads a committed 100 KB asset rather than the 580 MB catalog
    artifact: the artifact is gitignored and an operator-machine dependency, so a
    downstream generator or test that needed it could not run in a clean checkout
    (02-VALIDATION.md lines 115-126).
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        vocabulary = GistVocabulary(
            schema_version=int(payload["schema_version"]),
            df_floor=int(payload["df_floor"]),
            feature_abstraction_df_floor=int(payload["feature_abstraction_df_floor"]),
            catalog_sha256=str(payload["catalog_sha256"]),
            values=tuple(
                (str(name), tuple(str(item) for item in admitted))
                for name, admitted in sorted(payload["values"].items())
            ),
            abstractions=tuple(
                (str(value), (str(pair[0]), str(pair[1])))
                for value, pair in sorted(payload["abstractions"].items())
            ),
        )
        vocabulary.validate()
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GistError(f"malformed gist vocabulary at {path}: {error}") from error
    except OSError as error:
        raise GistError(f"cannot read gist vocabulary at {path}: {error}") from error
    return vocabulary


def build_vocabulary(
    index: CatalogIndex,
    *,
    catalog_sha256: str,
    abstractions: tuple[tuple[str, tuple[str, str]], ...],
) -> GistVocabulary:
    """Derive the closed vocabulary from the catalog. CLI-only; never called at use time."""
    values: list[tuple[str, tuple[str, ...]]] = []
    for attribute in _STRUCTURED_ATTRIBUTES:
        counts = index.value_counts(attribute)
        # value_counts returns an unsorted dict -- values_for sorts, value_counts
        # does not (L-17). An explicit key with the value string as final tie-break
        # is what makes the committed asset byte-reproducible.
        admitted = tuple(
            value
            for value, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )
            if count >= _GIST_DF_FLOOR
        )
        values.append((attribute.value, admitted))

    # FEATURE admits nothing from value_counts. Its entire vocabulary is the set of
    # abstract tokens in the committed table, so no catalog feature string can enter
    # the gist by any route -- the DF floor is not, and cannot be, the gate here (L-6).
    feature_tokens = tuple(
        dict.fromkeys(token for _, (_, token) in sorted(abstractions))
    )
    values.append((Attribute.FEATURE.value, tuple(sorted(feature_tokens))))

    vocabulary = GistVocabulary(
        schema_version=GIST_SCHEMA_VERSION,
        df_floor=_GIST_DF_FLOOR,
        feature_abstraction_df_floor=_FEATURE_ABSTRACTION_DF_FLOOR,
        catalog_sha256=catalog_sha256,
        values=tuple(sorted(values)),
        abstractions=abstractions,
    )
    vocabulary.validate()
    return vocabulary


def _detail_pairs(product: dict[str, object]) -> tuple[tuple[str, str], ...]:
    raw = product.get("details") or {}
    if not isinstance(raw, dict):
        return ()
    return tuple(
        (normalize_text(key), normalize_text(value))
        for key, value in raw.items()
        if value not in (None, "")
    )


def _feature_strings(product: dict[str, object]) -> tuple[str, ...]:
    raw = product.get("features")
    if not isinstance(raw, list):
        return ()
    return tuple(normalize_text(item) for item in raw if item not in (None, ""))


def _keyed_feature_pair(feature: str) -> tuple[str, str] | None:
    match = _KEYED_FEATURE_RE.match(feature)
    if match is None:
        return None
    attribute = _KEYED_FEATURE_ATTRIBUTES.get(match.group(1).strip())
    if attribute is None:
        return None
    value = _KEYED_VALUE_SPLIT_RE.split(match.group(2))[0].strip().strip(".-\"' ")
    if not value:
        return None
    return attribute.value, value


def _recovered_material_tokens(features: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for feature in features:
        stripped = _MATERIAL_PERCENT_RE.sub(" ", feature)
        for part in _MATERIAL_BLEND_RE.split(stripped):
            tokens = _MATERIAL_TOKEN_RE.findall(part)
            if tokens:
                found.append(tokens[-1])
    return tuple(dict.fromkeys(found))


def gist_for_target(
    product: dict[str, object],
    vocabulary: GistVocabulary,
) -> tuple[GistPair, ...]:
    """The complete, closed-vocabulary description of one target.

    Solvability is guaranteed by construction (D-35): every pair is derived from the
    target's own attributes, so every pair is true of the target. That is precisely
    why no retrieval-based solvability check is needed downstream, and why adding one
    would be a category error -- it would measure the agent, not the corpus.
    """
    features = _feature_strings(product)
    candidates: list[tuple[str, str]] = []

    for attribute in _STRUCTURED_ATTRIBUTES:
        candidates.extend(
            (attribute.value, value)
            for key, value in _detail_pairs(product)
            if key == attribute.value
        )
    for feature in features:
        keyed = _keyed_feature_pair(feature)
        if keyed is not None:
            candidates.append(keyed)
    candidates.extend(
        (Attribute.MATERIAL.value, token)
        for token in _recovered_material_tokens(features)
    )
    # The abstraction table is the ONLY route by which a feature reaches the gist.
    # The catalog string is the lookup key and is discarded; the abstract pair is
    # what leaves this function.
    lookup = dict(vocabulary.abstractions)
    candidates.extend(lookup[feature] for feature in features if feature in lookup)

    admitted = {
        pair for pair in candidates if vocabulary.admits(pair[0], pair[1])
    }
    pairs = tuple(
        GistPair(attribute=attribute, value=value)
        for attribute, value in sorted(admitted)
    )
    for pair in pairs:
        pair.validate()
    return pairs


def prompt_payload_strings(pairs: tuple[GistPair, ...]) -> tuple[str, ...]:
    """The exact, complete set of strings an authoring prompt may interpolate.

    This is the data-flow surface MEAS-12 is asserted against. Anything a future
    author wants the model to see about a target has to come through here, which is
    what makes "no catalog text reaches the prompt" checkable rather than aspirational.
    """
    return tuple(f"{pair.attribute}={pair.value}" for pair in pairs)


def main(argv: tuple[str, ...] | None = None) -> int:
    # Imported inside main, not at module scope: this is the only code path that may
    # touch the 580 MB artifact, and a module-level import would put the SQLite
    # backend into the import graph of every downstream generator and test.
    from starter.shopping_agent.catalog_index import CatalogIndex
    from starter.shopping_agent.local_search_backend import LocalProductSearchBackend

    parser = argparse.ArgumentParser(
        description="Build the committed D-32 gist vocabulary from the catalog artifact.",
    )
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.jsonl"))
    parser.add_argument(
        "--artifact-path", type=Path, default=Path("data/catalog.artifacts")
    )
    parser.add_argument("--output", type=Path, default=GIST_VOCABULARY_PATH)
    arguments = parser.parse_args(argv)

    backend = None
    try:
        abstractions = load_feature_abstractions()
        catalog_sha256 = sha256_file(arguments.catalog)
        backend = LocalProductSearchBackend.open(
            arguments.catalog,
            arguments.artifact_path,
        )
        vocabulary = build_vocabulary(
            CatalogIndex(backend),
            catalog_sha256=catalog_sha256,
            abstractions=abstractions,
        )
    except (GistError, OSError, ValueError) as error:
        print(f"gist vocabulary build failed: {error}", file=sys.stderr)
        return 1
    finally:
        # Windows holds the 580 MB database open until the connection is closed, and
        # arena.store.publish documents that a live handle defeats an atomic move.
        if backend is not None:
            backend.close()

    write_json(arguments.output, vocabulary.as_record())
    admitted_total = sum(len(admitted) for _, admitted in vocabulary.values)
    print(f"admitted_total={admitted_total}")
    print(f"df_floor={vocabulary.df_floor}")
    print(f"catalog_sha256={vocabulary.catalog_sha256}")
    print(f"output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
