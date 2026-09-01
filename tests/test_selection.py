from quiver.providers.base import Asset, asset_is_candidate, normalize_github_repo, select_asset


def assets(*names):
    return [Asset(name=n, url=f"http://x/{n}", size=1000) for n in names]


def test_prefers_matching_arch_appimage():
    pool = assets(
        "App-1.0-aarch64.AppImage",
        "App-1.0-x86_64.AppImage",
        "App-1.0.deb",
        "App-1.0-x86_64.AppImage.zsync",
        "checksums.txt",
        "App-1.0-x86_64.AppImage.sha256",
    )
    chosen = select_asset(pool, "x86_64")
    assert chosen.name == "App-1.0-x86_64.AppImage"


def test_arch_alias_variants():
    pool = assets("app_amd64.AppImage", "app_arm64.AppImage")
    assert select_asset(pool, "x86_64").name == "app_amd64.AppImage"
    assert select_asset(pool, "aarch64").name == "app_arm64.AppImage"


def test_x64_and_x86_64_tokens():
    pool = assets("MyApp-linux-x64.AppImage", "MyApp-linux-arm64.AppImage")
    assert select_asset(pool, "x86_64").name == "MyApp-linux-x64.AppImage"


def test_never_selects_wrong_arch():
    arm_only = assets("only-arm64.AppImage")
    assert select_asset(arm_only, "x86_64") is None
    assert select_asset(arm_only, "aarch64") is not None
    assert select_asset(assets("only.AppImage"), "x86_64") is not None


def test_skips_sidecars():
    for bad in (
        "app.AppImage.zsync",
        "app.sha256",
        "app.AppImage.sig",
        "app.tar.gz",
        "sources.zip",
    ):
        assert not asset_is_candidate(bad)
    assert asset_is_candidate("app-1.0.AppImage")


def test_user_pattern_overrides():
    pool = assets("App-x86_64.AppImage", "App-portable-x86_64.AppImage")
    chosen = select_asset(pool, "x86_64", patterns=["*portable*"])
    assert chosen.name == "App-portable-x86_64.AppImage"
    assert select_asset(pool, "x86_64", patterns=["*nothing-matches*"]) is None


def test_similarity_to_current_filename():
    pool = assets("winboat-1.0-x86_64.AppImage", "other-thing-1.0-x86_64.AppImage")
    chosen = select_asset(pool, "x86_64", current_name="winboat-0.9.2-x86_64.AppImage")
    assert chosen.name == "winboat-1.0-x86_64.AppImage"


def test_normalize_github_repo():
    assert normalize_github_repo("owner/repo") == "owner/repo"
    assert normalize_github_repo("https://github.com/owner/repo") == "owner/repo"
    assert normalize_github_repo("https://github.com/owner/repo/") == "owner/repo"
    assert normalize_github_repo("https://github.com/owner/repo.git") == "owner/repo"
    import pytest

    from quiver.providers.base import ProviderError

    with pytest.raises(ProviderError):
        normalize_github_repo("just-a-name")


def test_real_impactor_release_naming():
    """Asset soup from a real release: lowercase .appimage, both arches,
    metainfo.xml, dmg and exe sidecars."""
    pool = assets(
        "dev.khcrysalis.PlumeImpactor.metainfo.xml",
        "Impactor-linux-aarch64.appimage",
        "Impactor-linux-x86_64.appimage",
        "Impactor-macos-universal.dmg",
        "Impactor-windows-arm64-portable.exe",
    )
    assert select_asset(pool, "x86_64").name == "Impactor-linux-x86_64.appimage"
    assert select_asset(pool, "aarch64").name == "Impactor-linux-aarch64.appimage"


def test_glued_arm_words_are_not_arch():
    assert select_asset(assets("harmony-player-1.0.AppImage"), "x86_64") is not None
    assert select_asset(assets("alarm-clock-1.0.AppImage"), "x86_64") is not None
    assert select_asset(assets("thermal-monitor.AppImage"), "x86_64") is not None
