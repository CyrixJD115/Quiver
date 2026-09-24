"""GitLab Releases provider (gitlab.com by default, self-hosted via base_url)."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from quiver.core.registry import AppEntry
from quiver.providers.base import (
    GITLAB_URL_RE,
    Asset,
    ProviderError,
    Release,
    UpdateProvider,
    register,
)
from quiver.util import versions
from quiver.util.config import Config


def normalize_gitlab_repo(value: str) -> str:
    value = value.strip().rstrip("/")
    match = GITLAB_URL_RE.search(value)
    if match:
        return "/".join(part for part in match.group(1).split("/") if part).removesuffix(".git")
    if "/" not in value:
        raise ProviderError(
            f"invalid GitLab project: {value!r}",
            hint="Use group/project (possibly nested) or a gitlab.com URL.",
        )
    return value.removesuffix(".git")


@register
class GitLabProvider(UpdateProvider):
    type_name = "gitlab"

    def latest_release(self, app: AppEntry, cfg: Config, client: httpx.Client) -> Release:
        try:
            project = normalize_gitlab_repo(app.source_repo or "")
        except ProviderError:
            raise ProviderError(
                f"{app.alias}: source_repo {app.source_repo!r} is not a valid GitLab project"
            ) from None
        base = str(app.source_opts.get("base_url", "https://gitlab.com")).rstrip("/")
        url = f"{base}/api/v4/projects/{quote(project, safe='')}/releases"
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error talking to GitLab: {exc}") from exc
        if response.status_code == 404:
            raise ProviderError(
                f"GitLab project not found: {project}",
                hint="Check the project path with `quiver source show`.",
            )
        if response.status_code >= 400:
            raise ProviderError(f"GitLab API error {response.status_code} for {project}")
        releases = response.json()
        if not releases:
            raise ProviderError(f"GitLab project {project} has no releases")
        chosen = releases[0]
        assets: list[Asset] = []
        for link in chosen.get("assets", {}).get("links", []):
            url_link = link.get("direct_asset_url") or link.get("url") or ""
            name = link.get("name") or url_link.rsplit("/", 1)[-1]
            if url_link:
                assets.append(Asset(name=name, url=url_link))
        tag = chosen.get("tag_name", "")
        return Release(
            tag=tag,
            version=versions.normalize(tag),
            prerelease=bool(chosen.get("upcoming_release")),
            assets=assets,
            published=chosen.get("released_at"),
            url=chosen.get("_links", {}).get("self"),
        )
