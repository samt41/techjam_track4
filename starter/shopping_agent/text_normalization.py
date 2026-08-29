from __future__ import annotations

import re
import unicodedata


WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-z0-9]+")
COLON_SPACING_RE = re.compile(r"\s*:\s*")


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return WHITESPACE_RE.sub(" ", text).strip()


def match_key(value: str) -> str:
    """Normalize an attribute value for equality and substring matching.

    The catalog records the same colon-prefixed feature two ways, such as
    "material: alloy" and "material:alloy". These are one concept, but a raw
    substring comparison treats them as different values, so a product carrying
    one spelling is scored as mismatching a constraint carrying the other and is
    unfairly penalized. Collapsing the spacing around colons makes the two agree.
    """
    return COLON_SPACING_RE.sub(":", value)


def flatten_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(
            f"{normalize_text(key)} {flatten_text(item)}"
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return " ".join(flatten_text(item) for item in value)
    return normalize_text(value)


def search_terms(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(TOKEN_RE.findall(normalize_text(value))))
