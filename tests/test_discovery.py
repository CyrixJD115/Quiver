"""Source discovery: hint priority, verification, ranking, search fallback."""

from __future__ import annotations

import httpx

from quiver.discovery import discover_candidates
from quiver.registry import AppEntry
from tests.conftest import make_appimage

LATEST_GOOD = {
    "tag_name": "v2.0.0",
    "prerelease": False,
    "assets": [
        {
            "name": "tool-2.0.0-x86_64.AppImage",
            "browser_download_url": "http://dl/t.AppImage",
            "size": 10,
        }
    ],
}


def make_tool(tmp_path, **kwargs) -> AppEntry:
    path = make_appimage(tmp_path / "tool-1.0.0-x86_64.AppImage")
    params = dict(alias="tool", name="Tool", path=str(path), version="1.0.0", arch="x86_64")
    params.update(kwargs)
    return AppEntry(**params)


def handler_for(routes: dict, default: httpx.Response | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        fallback = default or httpx.Response(404, json={"message": "nope"})
        for pattern, response in routes.items():
            if pattern in url:
                return (
                    response
                    if isinstance(response, httpx.Response)
                    else httpx.Response(200, json=response)
                )
        return fallback

    return handler


def test_upd_info_hint_beats_metadata_hint(cfg, mock_client, tmp_path):
    client = mock_client(handler_for({"repos/winboat-org/winboat/releases/latest": LATEST_GOOD}))
    app = make_tool(
        tmp_path,
        source_opts={
            "update_info": "gh-releases-zsync|winboat-org|winboat|latest|x.AppImage",
            "github_hints": ["other/repo"],
        },
    )
    candidates = discover_candidates(app, cfg, client, allow_search=False)
    assert candidates and candidates[0].repo == "winboat-org/winboat"
    assert candidates[0].via == "embedded update info"


def test_app_id_hint(cfg, mock_client, tmp_path):
    client = mock_client(handler_for({"repos/acme/tool/releases/latest": LATEST_GOOD}))
    app = make_tool(tmp_path, app_id="io.github.acme.tool")
    candidates = discover_candidates(app, cfg, client, allow_search=False)
    assert [c.repo for c in candidates] == ["acme/tool"]
    assert candidates[0].via == "app id"


def test_unverified_hints_fall_through_to_search(cfg, mock_client, tmp_path):
    routes = {
        "search/repositories": {"items": [{"full_name": "found/tool"}]},
        "repos/found/tool/releases/latest": LATEST_GOOD,
    }
    client = mock_client(handler_for(routes))
    app = make_tool(tmp_path, source_opts={"github_hints": ["dead/repo"]})
    candidates = discover_candidates(app, cfg, client, allow_search=True)
    assert [c.repo for c in candidates] == ["found/tool"]
    assert candidates[0].via == "github search"


def test_search_disabled_finds_nothing(cfg, mock_client, tmp_path):
    routes = {"search/repositories": {"items": [{"full_name": "found/tool"}]}}
    client = mock_client(handler_for(routes))
    app = make_tool(tmp_path)
    assert discover_candidates(app, cfg, client, allow_search=False) == []


def test_ranking_by_asset_name_similarity(cfg, mock_client, tmp_path):
    exact = dict(LATEST_GOOD, assets=LATEST_GOOD["assets"])
    other = {
        "tag_name": "v2.0.0",
        "assets": [
            {
                "name": "completely-different-2.0.0-x86_64.AppImage",
                "browser_download_url": "http://dl/z.AppImage",
            }
        ],
    }
    routes = {
        "repos/acme/tool/releases/latest": exact,
        "repos/other/repo/releases/latest": other,
        "repos/zzz/match/releases/latest": exact,
        "search/repositories": {"items": [{"full_name": "other/repo"}, {"full_name": "zzz/match"}]},
    }
    client = mock_client(handler_for(routes))
    app = make_tool(tmp_path)
    candidates = discover_candidates(app, cfg, client)
    assert len(candidates) >= 2
    assert candidates[0].repo in {"other/repo", "zzz/match"}
    assert all(c.via == "github search" for c in candidates)


def test_hint_without_matching_asset_is_rejected(cfg, mock_client, tmp_path):
    arm_only = {
        "tag_name": "v2.0.0",
        "assets": [
            {"name": "tool-2.0.0-aarch64.AppImage", "browser_download_url": "http://dl/a.AppImage"}
        ],
    }
    client = mock_client(handler_for({"repos/acme/tool/releases/latest": arm_only}))
    app = make_tool(tmp_path, app_id="io.github.acme.tool")
    assert discover_candidates(app, cfg, client, allow_search=False) == []


def test_repo_with_no_releases_is_rejected(cfg, mock_client, tmp_path):
    client = mock_client(handler_for({}))
    app = make_tool(tmp_path, source_opts={"github_hints": ["ghost/repo"]})
    assert discover_candidates(app, cfg, client, allow_search=False) == []


def test_search_candidate_with_older_latest_is_rejected(cfg, mock_client, tmp_path):
    """Installed 3.10, repo's latest 1.0.5 => name collision, not upstream."""
    old_release = {
        "tag_name": "v1.0.5",
        "assets": [
            {"name": "tool-1.0.5-x86_64.AppImage", "browser_download_url": "http://dl/o.AppImage"}
        ],
    }
    routes = {
        "search/repositories": {"items": [{"full_name": "wrong/tool"}]},
        "repos/wrong/tool/releases/latest": old_release,
    }
    client = mock_client(handler_for(routes))
    app = make_tool(tmp_path, version="3.10.1.6272")
    assert discover_candidates(app, cfg, client) == []


def test_hint_candidate_survives_version_mismatch(cfg, mock_client, tmp_path):
    """Embedded hints are trusted evidence; a locally-newer nightly is legit."""
    nightly = {
        "tag_name": "v1.0.5",
        "assets": [
            {"name": "tool-1.0.5-x86_64.AppImage", "browser_download_url": "http://dl/o.AppImage"}
        ],
    }
    client = mock_client(handler_for({"repos/acme/tool/releases/latest": nightly}))
    app = make_tool(
        tmp_path,
        version="3.10.1.6272",
        source_opts={"update_info": "gh-releases-zsync|acme|tool|latest|x.AppImage"},
    )
    candidates = discover_candidates(app, cfg, client, allow_search=False)
    assert [c.repo for c in candidates] == ["acme/tool"]
