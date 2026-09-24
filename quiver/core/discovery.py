"""Upstream source discovery: figure out where an app's updates come from.

Candidate priority (most trustworthy first):
  1. embedded update info read from the AppImage itself (``.upd_info``)
  2. reverse-DNS app ids (``io.github.<owner>.<project>``)
  3. GitHub URLs in the embedded AppStream metadata
  4. GitHub repository search (network, least certain)

Every candidate is *verified*: the repo must have a release carrying an
AppImage asset matching the app's architecture, and candidates are ranked by
how similar that asset's name is to the installed file's name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from quiver.core.appimage import github_repo_from_app_id, parse_update_info
from quiver.core.registry import AppEntry
from quiver.providers import get_provider, select_asset
from quiver.providers.base import ProviderError, _name_tokens
from quiver.providers.github import API_BASE
from quiver.util import versions
from quiver.util.config import Config

_HINT_PRIORITY = (
    "embedded update info",
    "app id",
    "embedded metadata",
    "github search",
)


@dataclass(frozen=True)
class SourceCandidate:
    repo: str
    version: str
    via: str
    asset_name: str

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "version": self.version,
            "via": self.via,
            "asset": self.asset_name,
        }


def _verify(
    repo: str, app: AppEntry, cfg: Config, client: httpx.Client, via: str
) -> SourceCandidate | None:
    probe = AppEntry(
        alias=app.alias,
        name=app.name,
        path=app.path,
        arch=app.arch,
        source_type="github",
        source_repo=repo,
        source_opts={
            key: value
            for key, value in app.source_opts.items()
            if key in ("asset_patterns", "allow_prerelease")
        },
    )
    try:
        release = get_provider("github").latest_release(probe, cfg, client)
        asset = select_asset(
            release.assets,
            app.arch,
            current_name=Path(app.path).name,
            patterns=app.source_opts.get("asset_patterns"),
        )
    except ProviderError:
        return None
    except OSError:
        return None
    if asset is None:
        return None
    return SourceCandidate(
        repo=repo, version=release.version or release.tag, via=via, asset_name=asset.name
    )


def discover_candidates(
    app: AppEntry,
    cfg: Config,
    client: httpx.Client,
    *,
    allow_search: bool = True,
    max_search_verifications: int = 8,
) -> list[SourceCandidate]:
    """Return verified upstream candidates, best first."""
    found: list[SourceCandidate] = []
    tried: set[str] = set()

    hints: list[tuple[str, str]] = []
    for repo in parse_update_info(app.source_opts.get("update_info")):
        hints.append((repo, _HINT_PRIORITY[0]))
    app_id_repo = github_repo_from_app_id(app.app_id)
    if app_id_repo:
        hints.append((app_id_repo, _HINT_PRIORITY[1]))
    for repo in app.source_opts.get("github_hints", []):
        hints.append((repo, _HINT_PRIORITY[2]))

    for repo, via in hints:
        if repo in tried:
            continue
        tried.add(repo)
        candidate = _verify(repo, app, cfg, client, via)
        if candidate:
            found.append(candidate)

    if not found and allow_search:
        for query in (f"{app.name} appimage", app.name):
            repos = _search_repos(query, client)
            if repos:
                break
        search_hits = 0
        for repo in repos[:max_search_verifications]:
            if repo in tried:
                continue
            tried.add(repo)
            candidate = _verify(repo, app, cfg, client, _HINT_PRIORITY[3])
            if candidate and not _version_sane(app, candidate):
                # Installed copy is NEWER than this repo's latest release:
                # that's a strong "wrong repository" signal (a name collision
                # in search), not a downgrade opportunity.
                continue
            if candidate:
                found.append(candidate)
                search_hits += 1
                if search_hits >= 3:
                    break

    current_tokens = _name_tokens(Path(app.path).name)
    found.sort(
        key=lambda c: (
            _HINT_PRIORITY.index(c.via),
            -len(current_tokens & _name_tokens(c.asset_name)),
        )
    )
    return found


def _version_sane(app: AppEntry, candidate: SourceCandidate) -> bool:
    """False when the installed version is clearly newer than the candidate's
    latest release - the repo is probably a name collision, not the upstream."""
    if not app.version or not candidate.version:
        return True
    return not versions.compare(app.version, candidate.version) > 0


def _search_repos(query: str, client: httpx.Client) -> list[str]:
    repos: list[str] = []
    try:
        response = client.get(f"{API_BASE}/search/repositories", params={"q": query, "per_page": 5})
    except httpx.HTTPError:
        return repos
    if response.status_code != 200:
        return repos
    for item in response.json().get("items", [])[:5]:
        full = item.get("full_name")
        if full:
            repos.append(full)
    return repos
