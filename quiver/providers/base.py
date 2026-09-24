"""Update provider plumbing: data types, registry and asset selection.

Adding a new source means subclassing :class:`UpdateProvider` and registering
it with ``@register`` - nothing else in the codebase needs to change.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fnmatch import fnmatch

import httpx

from quiver.core.registry import AppEntry
from quiver.util.config import Config
from quiver.util.errors import UpdateFailedError

BAD_SUFFIXES = (
    ".zsync",
    ".sha256",
    ".sha512",
    ".sha256sum",
    ".sha256sums",
    ".sig",
    ".asc",
    ".pem",
    ".pub",
    ".json",
    ".txt",
    ".yml",
    ".yaml",
    ".md",
    ".xml",
    ".deb",
    ".rpm",
    ".exe",
    ".dmg",
    ".pkg",
    ".snap",
    ".AppDir",
    ".tar.gz",
    ".tar.xz",
    ".zip",
    ".7z",
    ".br",
    ".bz2",
    ".delta",
    ".appdata",
    ".metainfo",
)

BAD_NAME_TOKENS = (
    "checksum",
    "checksums",
    "digest",
    "sha256",
    "sha512",
    "signature",
    "sources",
    "metainfo",
    "appdata",
)

ARCH_TOKENS: dict[str, tuple[str, ...]] = {
    "x86_64": ("x86_64", "x86-64", "amd64", "x64"),
    "aarch64": ("aarch64", "arm64", "aarch_64"),
    "i386": ("i386", "i686", "x86"),
    "arm": ("armhf", "armv7", "arm"),
    "riscv64": ("riscv64", "riscv"),
}

# Arch tokens must be delimited: "harmony" must NOT read as ARM. Matching on
# non-alphanumeric boundaries keeps glued words from false-positiving.
_ARCH_BOUNDARIES: dict[str, tuple[re.Pattern[str], ...]] = {
    arch: tuple(
        re.compile(rf"(?:^|[^a-z0-9]){re.escape(token)}(?:$|[^a-z0-9])") for token in tokens
    )
    for arch, tokens in ARCH_TOKENS.items()
}


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    prerelease: bool = False
    assets: list[Asset] = field(default_factory=list)
    published: str | None = None
    url: str | None = None
    note: str | None = None  # human note, e.g. "latest including prereleases"


class ProviderError(UpdateFailedError):
    """An update source could not be queried or understood."""


class UpdateProvider(ABC):
    type_name: str = "abstract"

    @abstractmethod
    def latest_release(self, app: AppEntry, cfg: Config, client: httpx.Client) -> Release:
        """Fetch the newest release information for a managed app."""


_PROVIDER_REGISTRY: dict[str, type[UpdateProvider]] = {}


def register(cls: type[UpdateProvider]) -> type[UpdateProvider]:
    _PROVIDER_REGISTRY[cls.type_name] = cls
    return cls


def known_providers() -> list[str]:
    return sorted(_PROVIDER_REGISTRY)


def get_provider(type_name: str) -> UpdateProvider:
    try:
        return _PROVIDER_REGISTRY[type_name]()
    except KeyError:
        raise ProviderError(
            f"unknown update provider type {type_name!r}",
            hint=f"Known providers: {', '.join(known_providers())}",
        ) from None


# ---- asset selection --------------------------------------------------------


def asset_is_candidate(name: str) -> bool:
    low = name.lower()
    if low.endswith(BAD_SUFFIXES):
        return False
    return not any(token in low for token in BAD_NAME_TOKENS)


def _arch_tokens_present(low_name: str) -> set[str]:
    return {
        arch
        for arch, patterns in _ARCH_BOUNDARIES.items()
        if any(pattern.search(low_name) for pattern in patterns)
    }


_JUNK_TOKENS = {"linux", "appimage", "v", "stable", "latest", "release", "portable", "app", "gnu"}


def _name_tokens(name: str) -> set[str]:
    import re

    return {
        t.lower()
        for t in re.split(r"[^A-Za-z0-9]+", name)
        if len(t) > 2 and t.lower() not in _JUNK_TOKENS and not t.isdigit()
    }


def select_asset(
    assets: list[Asset],
    arch: str | None,
    *,
    current_name: str | None = None,
    patterns: list[str] | None = None,
) -> Asset | None:
    """Pick the most plausible AppImage asset for ``arch``.

    Scoring is additive; a wrong-architecture asset is never selected, and
    non-AppImage sidecars (checksums, signatures, packages) are skipped.
    """
    current_tokens = _name_tokens(current_name) if current_name else set()
    ranked: list[tuple[tuple[int, int, str], Asset]] = []

    for asset in assets:
        if not asset_is_candidate(asset.name):
            continue
        low = asset.name.lower()
        score = 0

        archs_present = _arch_tokens_present(low)
        if arch and archs_present:
            if arch not in archs_present:
                continue  # explicitly built for another architecture
            score += 8
        elif archs_present:
            # some architecture is specified but we don't know ours; mild penalty
            score -= 2

        if "appimage" in low:
            score += 4
        if "linux" in low:
            score += 1

        if patterns:
            matched = sum(1 for p in patterns if fnmatch(low, p.lower()))
            if matched:
                score += 10 * matched
            else:
                continue  # an explicit user pattern filters everything else out

        if current_tokens:
            overlap = current_tokens & _name_tokens(asset.name)
            score += min(2 * len(overlap), 6)

        ranked.append(((score, asset.size or 0, asset.name), asset))

    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked[0][1]


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GITHUB_URL_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
GITLAB_URL_RE = re.compile(r"gitlab\.com/([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)")


def normalize_github_repo(value: str) -> str:
    """Accept ``owner/repo`` or any github.com URL; return ``owner/repo``."""
    value = value.strip().rstrip("/")
    match = GITHUB_URL_RE.search(value)
    if match:
        return f"{match.group(1)}/{match.group(2).removesuffix('.git')}"
    if not REPO_RE.match(value):
        raise ProviderError(
            f"invalid GitHub repository: {value!r}",
            hint="Use the form owner/repository or a github.com URL.",
        )
    return value.removesuffix(".git")
