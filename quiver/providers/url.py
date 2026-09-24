"""Direct-URL provider for apps without a release API.

Version is not knowable from a static URL, so change detection compares the
ETag/Last-Modified headers (when served) and falls back to comparing the
sha256 of the content. The computed asset sha256 is compared against the
registered file hash by the updater.
"""

from __future__ import annotations

import hashlib
import re

import httpx

from quiver.core.registry import AppEntry
from quiver.providers.base import Asset, ProviderError, Release, UpdateProvider, register
from quiver.util.config import Config

_CONTENT_DISP = re.compile(r'filename="?([^";]+)"?')


def _filename_from(response: httpx.Response, url: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = _CONTENT_DISP.search(disposition)
    if match:
        return match.group(1)
    return url.rstrip("/").rsplit("/", 1)[-1] or "download"


@register
class URLProvider(UpdateProvider):
    type_name = "url"

    def latest_release(self, app: AppEntry, cfg: Config, client: httpx.Client) -> Release:
        url = (app.source_repo or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ProviderError(
                f"{app.alias}: url source must start with http(s)://, got {app.source_repo!r}"
            )
        try:
            head = client.head(url)
            if head.status_code >= 400:
                # Some servers reject HEAD; a ranged GET is the polite fallback.
                head = client.get(url, headers={"Range": "bytes=0-0"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not reach {url}: {exc}") from exc
        if head.status_code >= 400:
            raise ProviderError(f"HTTP {head.status_code} for {url}")

        etag = head.headers.get("etag")
        last_modified = head.headers.get("last-modified")
        size_header = head.headers.get("content-length") or (
            head.headers.get("content-range", "/").rsplit("/", 1)[-1] or None
        )
        try:
            size = int(size_header) if size_header else None
        except ValueError:
            size = None

        stored_etag = app.source_opts.get("last_etag")
        stored_lm = app.source_opts.get("last_modified")

        content_sha: str | None = None
        note = None
        changed: bool
        if etag and stored_etag:
            changed = etag != stored_etag
        elif last_modified and stored_lm:
            changed = last_modified != stored_lm
        else:
            # No usable validators yet: fetch content and hash it.
            content_sha, size = self._fetch_hash(client, url)
            name = _filename_from(head, url)
            changed = content_sha != app.sha256
            note = "content compared by sha256 (server sends no ETag/Last-Modified)"
            return Release(
                tag="",
                version="",
                assets=[Asset(name=name, url=url, size=size, sha256=content_sha)],
                note=note,
            )

        name = _filename_from(head, url)
        if not changed:
            return Release(
                tag="",
                version="",
                assets=[Asset(name=name, url=url, size=size, sha256=app.sha256)],
                note="unchanged (validators match)",
            )
        content_sha, size = self._fetch_hash(client, url)
        return Release(
            tag="",
            version="",
            assets=[Asset(name=name, url=url, size=size, sha256=content_sha)],
        )

    def _fetch_hash(self, client: httpx.Client, url: str) -> tuple[str, int | None]:
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not download {url} for hashing: {exc}") from exc
        digest = hashlib.sha256(response.content).hexdigest()
        size = len(response.content)
        return digest, size
