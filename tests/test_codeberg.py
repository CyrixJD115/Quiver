"""Codeberg/Gitea provider parsing."""

from __future__ import annotations

import httpx
import pytest
from quiver.core.registry import AppEntry
from quiver.providers.base import ProviderError
from quiver.providers.codeberg import CodebergProvider, normalize_forge_repo

RELEASES = [
    {
        "tag_name": "v1.5.0",
        "prerelease": False,
        "draft": False,
        "html_url": "https://codeberg.org/acme/tool/releases/v1.5.0",
        "assets": {
            "attachments": [
                {
                    "name": "tool-1.5.0-x86_64.AppImage",
                    "browser_download_url": "https://codeberg.org/acme/tool/releases/download/v1.5.0/tool.AppImage",
                    "size": 1234,
                },
                {
                    "name": "tool-1.5.0-aarch64.AppImage",
                    "browser_download_url": "https://codeberg.org/acme/tool/releases/download/v1.5.0/tool-arm.AppImage",
                    "size": 1200,
                },
            ]
        },
    }
]


def entry(**kwargs):
    params = dict(
        alias="t",
        name="T",
        path="/tmp/t.AppImage",
        arch="x86_64",
        source_type="codeberg",
        source_repo="acme/tool",
    )
    params.update(kwargs)
    return AppEntry(**params)


def test_normalize_forge_repo():
    assert normalize_forge_repo("acme/tool") == "acme/tool"
    assert normalize_forge_repo("https://codeberg.org/acme/tool") == "acme/tool"
    assert normalize_forge_repo("https://codeberg.org/acme/tool.git") == "acme/tool"
    with pytest.raises(ProviderError):
        normalize_forge_repo("not-a-repo")


def test_latest_release(cfg, mock_client):
    client = mock_client(
        lambda request: (
            httpx.Response(200, json=RELEASES)
            if "/releases" in str(request.url)
            else httpx.Response(404)
        )
    )
    release = CodebergProvider().latest_release(entry(), cfg, client)
    assert release.version == "1.5.0"
    names = [a.name for a in release.assets]
    assert "tool-1.5.0-x86_64.AppImage" in names
    assert release.assets[0].url.startswith("https://codeberg.org/")


def test_not_found(cfg, mock_client):
    client = mock_client(lambda request: httpx.Response(404, json={}))
    with pytest.raises(ProviderError, match="not found"):
        CodebergProvider().latest_release(entry(), cfg, client)


def test_no_releases(cfg, mock_client):
    client = mock_client(lambda request: httpx.Response(200, json=[]))
    with pytest.raises(ProviderError, match="no releases"):
        CodebergProvider().latest_release(entry(), cfg, client)


def test_provider_is_registered():
    from quiver.providers import get_provider, known_providers

    assert "codeberg" in known_providers()
    assert get_provider("codeberg").type_name == "codeberg"
