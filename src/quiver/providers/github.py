"""GitHub Releases provider."""

from __future__ import annotations

import httpx

from quiver import versions
from quiver.config import Config
from quiver.providers.base import (
    Asset,
    ProviderError,
    Release,
    UpdateProvider,
    normalize_github_repo,
    register,
)
from quiver.registry import AppEntry

API_BASE = "https://api.github.com"


def _headers(cfg: Config) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = cfg.github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _rate_limited(response: httpx.Response) -> bool:
    return (
        response.status_code in (403, 429) and response.headers.get("x-ratelimit-remaining") == "0"
    )


def _parse_asset(asset_json: dict) -> Asset:
    digest = asset_json.get("digest") or ""
    sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
    return Asset(
        name=asset_json.get("name", ""),
        url=asset_json.get("browser_download_url", ""),
        size=asset_json.get("size"),
        sha256=sha256,
    )


def _parse_release(release_json: dict, *, note: str | None = None) -> Release:
    tag = release_json.get("tag_name") or release_json.get("name") or ""
    assets = [_parse_asset(a) for a in release_json.get("assets", []) if a.get("name")]
    return Release(
        tag=tag,
        version=versions.normalize(tag),
        prerelease=bool(release_json.get("prerelease")),
        assets=assets,
        published=release_json.get("published_at"),
        url=release_json.get("html_url"),
        note=note,
    )


@register
class GitHubProvider(UpdateProvider):
    type_name = "github"

    def latest_release(self, app: AppEntry, cfg: Config, client: httpx.Client) -> Release:
        repo = (app.source_repo or "").strip()
        try:
            repo = normalize_github_repo(repo)
        except ProviderError:
            raise ProviderError(
                f"{app.alias}: source_repo {app.source_repo!r} is not a valid GitHub repository"
            ) from None
        allow_prerelease = bool(app.source_opts.get("allow_prerelease")) or bool(
            cfg.data.get("github", {}).get("prerelease", False)
        )

        response = self._get(client, f"{API_BASE}/repos/{repo}/releases/latest", cfg)
        if response.status_code == 404:
            # No stable release yet (or only prereleases) - fall back to the list.
            list_response = self._get(client, f"{API_BASE}/repos/{repo}/releases?per_page=30", cfg)
            if list_response.status_code == 404:
                raise ProviderError(
                    f"GitHub repository not found: {repo}",
                    hint="Check the repository owner/name with `quiver source show`.",
                )
            releases = list_response.json()
            chosen = next((r for r in releases if not r.get("draft")), None)
            if chosen is None:
                raise ProviderError(f"GitHub repository {repo} has no releases")
            note = (
                "latest release is a prerelease"
                if chosen.get("prerelease") and not allow_prerelease
                else None
            )
            return self._installable_or_older(chosen, repo, app, cfg, client, note)
        if response.status_code >= 400:
            raise ProviderError(f"GitHub API error {response.status_code} for {repo}")
        return self._installable_or_older(response.json(), repo, app, cfg, client)

    def _installable_or_older(
        self,
        chosen: dict,
        repo: str,
        app: AppEntry,
        cfg: Config,
        client: httpx.Client,
        note: str | None = None,
    ) -> Release:
        """Return ``chosen`` unless it has no asset for this machine's arch.

        Some projects temporarily publish releases with only, say, arm64
        assets. Walking down to the newest release that actually has a
        matching asset gives a usable "latest" instead of a dead end.
        """
        from dataclasses import replace
        from pathlib import Path

        from quiver.providers import select_asset

        release = _parse_release(chosen, note=note)
        if not app.arch:
            return release
        patterns = app.source_opts.get("asset_patterns")
        if select_asset(
            release.assets, app.arch, current_name=Path(app.path).name, patterns=patterns
        ):
            return release
        list_response = self._get(client, f"{API_BASE}/repos/{repo}/releases?per_page=15", cfg)
        if list_response.status_code != 200:
            return release
        for release_json in list_response.json():
            if release_json.get("draft") or release_json.get("tag_name") == release.tag:
                continue
            candidate = _parse_release(release_json)
            if not candidate.assets:
                continue
            if select_asset(
                candidate.assets, app.arch, current_name=Path(app.path).name, patterns=patterns
            ):
                return replace(
                    candidate,
                    note=f"newer releases have no matching asset; using {candidate.tag}",
                )
        return release

    def _get(self, client: httpx.Client, url: str, cfg: Config) -> httpx.Response:
        try:
            response = client.get(url, headers=_headers(cfg))
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error talking to GitHub: {exc}") from exc
        if _rate_limited(response):
            raise ProviderError(
                "GitHub API rate limit exceeded (60 requests/hour unauthenticated)",
                hint="Set GITHUB_TOKEN or run: quiver config set github.token <token>",
            )
        return response
