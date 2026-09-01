import httpx
import pytest

from quiver.providers.base import ProviderError
from quiver.providers.github import GitHubProvider
from quiver.registry import AppEntry
from tests.conftest import make_appimage


def github_entry(**kwargs):
    params = dict(
        alias="app",
        name="App",
        path="/tmp/app.AppImage",
        arch="x86_64",
        source_type="github",
        source_repo="owner/repo",
    )
    params.update(kwargs)
    return AppEntry(**params)


LATEST = {
    "tag_name": "v1.2.3",
    "prerelease": False,
    "published_at": "2026-08-01T00:00:00Z",
    "html_url": "https://github.com/owner/repo/releases/v1.2.3",
    "assets": [
        {
            "name": "app-1.2.3-x86_64.AppImage",
            "browser_download_url": "http://dl/x.AppImage",
            "size": 100,
            "digest": "sha256:" + "a" * 64,
        },
        {"name": "app-1.2.3-x86_64.AppImage.zsync", "browser_download_url": "http://dl/x.zsync"},
        {
            "name": "app-1.2.3-aarch64.AppImage",
            "browser_download_url": "http://dl/arm.AppImage",
            "size": 90,
        },
    ],
}


def handler_for(routes: dict, default_status=404):
    def handler(request: httpx.Request) -> httpx.Response:
        for pattern, response in routes.items():
            if pattern in str(request.url):
                return (
                    response
                    if isinstance(response, httpx.Response)
                    else httpx.Response(200, json=response)
                )
        return httpx.Response(default_status)

    return handler


def test_latest_release_parses(cfg, mock_client):
    client = mock_client(handler_for({"releases/latest": LATEST}))
    release = GitHubProvider().latest_release(github_entry(), cfg, client)
    assert release.version == "1.2.3"
    assert release.prerelease is False
    names = [a.name for a in release.assets]
    assert "app-1.2.3-x86_64.AppImage" in names
    asset = next(a for a in release.assets if a.name.endswith("x86_64.AppImage"))
    assert asset.sha256 == "a" * 64
    assert asset.size == 100


def test_falls_back_to_release_list_on_404(cfg, mock_client):
    listed = [
        {"tag_name": "v2.0.0-rc1", "prerelease": True, "assets": []},
        {"tag_name": "v1.9.0", "prerelease": False, "assets": []},
    ]
    client = mock_client(
        handler_for(
            {
                "releases/latest": httpx.Response(404, json={"message": "Not Found"}),
                "releases?per_page=30": listed,
            }
        )
    )
    release = GitHubProvider().latest_release(github_entry(), cfg, client)
    assert release.version == "2.0.0-rc1"
    assert release.prerelease is True
    assert release.note is not None


def test_repo_not_found(cfg, mock_client):
    client = mock_client(lambda request: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(ProviderError, match="not found"):
        GitHubProvider().latest_release(github_entry(), cfg, client)


def test_rate_limit_hint(cfg, mock_client):
    def handler(request):
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "rate limited"},
        )

    client = mock_client(handler)
    with pytest.raises(ProviderError, match="rate limit"):
        GitHubProvider().latest_release(github_entry(), cfg, client)


def test_invalid_repo(cfg, mock_client):
    client = mock_client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(ProviderError, match="not a valid GitHub"):
        GitHubProvider().latest_release(github_entry(source_repo="oops"), cfg, client)


def test_no_releases(cfg, mock_client):
    def handler(request):
        if "releases/latest" in str(request.url):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json=[])

    client = mock_client(handler)
    with pytest.raises(ProviderError, match="no releases"):
        GitHubProvider().latest_release(github_entry(), cfg, client)


def test_asset_selection_integration(cfg, mock_client, tmp_path):
    """End-to-end: provider release -> select_asset picks x86_64 AppImage."""
    from quiver.providers import select_asset

    make_appimage(tmp_path / "app-1.0.0-x86_64.AppImage")
    client = mock_client(handler_for({"releases/latest": LATEST}))
    release = GitHubProvider().latest_release(github_entry(), cfg, client)
    chosen = select_asset(release.assets, "x86_64", current_name="app-1.0.0-x86_64.AppImage")
    assert chosen.name == "app-1.2.3-x86_64.AppImage"


def test_walks_down_when_newest_release_lacks_matching_asset(cfg, mock_client):
    """Newest release only ships arm64; the provider falls back to the newest
    release that actually has an x86_64 asset."""
    newest = {
        "tag_name": "v3.0.0",
        "assets": [
            {"name": "app-3.0.0-aarch64.AppImage", "browser_download_url": "http://dl/arm.AppImage"}
        ],
    }
    listing = [
        newest,
        {"tag_name": "v2.9.0", "assets": []},
        {
            "tag_name": "v2.8.0",
            "assets": [
                {
                    "name": "app-2.8.0-x86_64.AppImage",
                    "browser_download_url": "http://dl/x.AppImage",
                    "size": 5,
                }
            ],
        },
    ]
    routes = {
        "releases/latest": newest,
        "releases?per_page=15": listing,
    }
    client = mock_client(handler_for(routes))
    release = GitHubProvider().latest_release(github_entry(arch="x86_64"), cfg, client)
    assert release.version == "2.8.0"
    assert release.note and "no matching asset" in release.note


def test_no_walk_down_without_arch(cfg, mock_client):
    newest = {
        "tag_name": "v3.0.0",
        "assets": [
            {"name": "app-3.0.0-aarch64.AppImage", "browser_download_url": "http://dl/arm.AppImage"}
        ],
    }
    client = mock_client(handler_for({"releases/latest": newest}))
    release = GitHubProvider().latest_release(github_entry(arch=None), cfg, client)
    assert release.version == "3.0.0"


def test_no_walk_down_when_asset_matches(cfg, mock_client):
    newest = {
        "tag_name": "v3.0.0",
        "assets": [
            {"name": "app-3.0.0-x86_64.AppImage", "browser_download_url": "http://dl/x.AppImage"}
        ],
    }
    client = mock_client(handler_for({"releases/latest": newest}))
    release = GitHubProvider().latest_release(github_entry(arch="x86_64"), cfg, client)
    assert release.version == "3.0.0"
    assert release.note is None
