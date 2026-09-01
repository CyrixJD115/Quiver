"""Tolerant version comparison for arbitrary upstream tags.

Upstream tags are wildly inconsistent (``v1.2.3``, ``2024.08.31``,
``0.59.2-rc1``, ``continuous``), so we use a natural (digit-aware) ordering
with semver-like prerelease handling instead of strict semver.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"\d+|[A-Za-z]+")


def normalize(version: str | None) -> str:
    """Strip a leading ``v``/``V`` and surrounding whitespace from a tag."""
    if not version:
        return ""
    version = version.strip()
    if version[:1] in ("v", "V"):
        version = version[1:]
    return version


def _split_prerelease(version: str) -> tuple[str, str]:
    """Split into (core, prerelease); build metadata after ``+`` is dropped."""
    plus = version.find("+")
    if plus != -1:
        version = version[:plus]
    dash = version.find("-")
    if dash != -1:
        return version[:dash], version[dash + 1 :]
    return version, ""


def _tokens(text: str) -> list[str | int]:
    return [int(t) if t.isdigit() else t.lower() for t in _TOKEN.findall(text)]


def _compare_token_groups(a: list[str | int], b: list[str | int]) -> int:
    for x, y in zip(a, b, strict=False):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return (x > y) - (x < y)
        if isinstance(x, int):
            return 1  # numeric segments sort above alpha segments
        if isinstance(y, int):
            return -1
        return (x > y) - (x < y)
    return (len(a) > len(b)) - (len(a) < len(b))


def compare(a: str, b: str) -> int:
    """Compare two version strings naturally. Returns -1/0/1."""
    a, b = normalize(a), normalize(b)
    if a == b:
        return 0
    core_a, pre_a = _split_prerelease(a)
    core_b, pre_b = _split_prerelease(b)
    cmp = _compare_token_groups(_tokens(core_a), _tokens(core_b))
    if cmp != 0:
        return cmp
    # Same core: a version without prerelease is newer than one with it.
    if not pre_a and not pre_b:
        return 0
    if not pre_a:
        return 1
    if not pre_b:
        return -1
    return _compare_token_groups(_tokens(pre_a), _tokens(pre_b))


def is_newer(candidate: str, current: str) -> bool:
    """True when ``candidate`` is strictly newer than ``current``."""
    return compare(candidate, current) > 0
