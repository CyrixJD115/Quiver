"""Codeberg (and other Gitea-forge) Releases provider."""

from __future__ import annotations

import re

import httpx

from quiver.core.registry import AppEntry
from quiver.providers.base import Asset, ProviderError, Release, UpdateProvider, register
from quiver.util import versions
from quiver.util.config import Config

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FORGE_URL_RE = re.compile(r"(?:codeberg\.org|forgejo\.org)/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def normalize_forge_repo(value: str) -> str:
    value = value.strip().rstrip("/")
    match = FORGE_URL_RE.search(value)
    if match:
        return f"{match.group(1)}/{match.group(2).removesuffix('.git')}"
    if not REPO_RE.match(value):
        raise ProviderError(
            f"invalid project: {value!r}",
            hint="Use owner/repository or a codeberg.org URL.",
        )
    return value.removesuffix(".git")


@register
class CodebergProvider(UpdateProvider):
    type_name = "codeberg"

    def latest_release(self, app: AppEntry, cfg: Config, client: httpx.Client) -> Release:
        try:
            repo = normalize_forge_repo(app.source_repo or "")
        except ProviderError:
            raise ProviderError(
                f"{app.alias}: source_repo {app.source_repo!r} is not a valid project"
            ) from None
        base = str(app.source_opts.get("base_url", "https://codeberg.org")).rstrip("/")
        url = f"{base}/api/v1/repos/{repo}/releases?limit=10"
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error talking to {base}: {exc}") from exc
        if response.status_code == 404:
            raise ProviderError(
                f"project not found on {base}: {repo}",
                hint="Check the owner/name with `quiver source show`.",
            )
        if response.status_code >= 400:
            raise ProviderError(f"{base} API error {response.status_code} for {repo}")
        releases = response.json()
        if not releases:
            raise ProviderError(f"project {repo} has no releases")
        chosen = next((r for r in releases if not r.get("draft")), releases[0])
        assets = [
            asset
            for asset in chosen.get("assets", {}).get("attachments", [])
            if asset.get("name") and asset.get("browser_download_url")
        ]
        tag = chosen.get("tag_name", "")
        return Release(
            tag=tag,
            version=versions.normalize(tag),
            prerelease=bool(chosen.get("prerelease")),
            assets=[
                Asset(name=a["name"], url=a["browser_download_url"], size=a.get("size"))
                for a in assets
            ],
            published=chosen.get("published_at") or chosen.get("created_at"),
            url=chosen.get("html_url"),
        )
