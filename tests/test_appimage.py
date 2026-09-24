import hashlib

from quiver.core import appimage

from tests.conftest import make_appimage


def test_detect_valid_x86_64(fake_appimage, tmp_path):
    path = fake_appimage(tmp_path / "App-1.0-x86_64.AppImage")
    info = appimage.detect(path)
    assert info is not None
    assert info.appimage_type == 2
    assert info.arch == "x86_64"
    assert info.size == path.stat().st_size


def test_detect_aarch64(fake_appimage, tmp_path):
    path = fake_appimage(tmp_path / "App-aarch64.AppImage", arch="aarch64")
    assert appimage.detect(path).arch == "aarch64"


def test_detect_rejects_plain_elf(tmp_path):
    path = tmp_path / "elf.bin"
    path.write_bytes(b"\x7fELF" + b"\x00" * 60)
    assert appimage.detect(path) is None


def test_detect_rejects_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    assert appimage.detect(path) is None


def test_detect_missing_file(tmp_path):
    assert appimage.detect(tmp_path / "nope.AppImage") is None


def test_parse_filename_patterns():
    cases = {
        "ToolCoin_1.5.0.AppImage": ("ToolCoin", "1.5.0"),
        "winboat-0.9.2-x86_64.AppImage": ("winboat", "0.9.2"),
        "iloader-linux-amd64.AppImage": ("iloader", None),
        "Impactor-linux-x86_64.appimage": ("Impactor", None),
        "MyApp-2.1b-x86_64.AppImage": ("MyApp", "2.1b"),
    }
    for filename, (name, version) in cases.items():
        parsed = appimage.parse_filename(filename)
        assert parsed["name"] == name, filename
        assert parsed["version"] == version, filename
    assert appimage.parse_filename("winboat-0.9.2-x86_64.AppImage")["arch"] == "x86_64"
    assert appimage.parse_filename("iloader-linux-amd64.AppImage")["arch"] == "x86_64"


def test_derive_alias():
    assert appimage.derive_alias("ZCode") == "zcode"
    assert appimage.derive_alias(None, "iloader-linux-amd64.AppImage") == "iloader"
    assert appimage.derive_alias(None, "ToolCoin_1.5.0.AppImage") == "toolcoin"
    assert appimage.derive_alias(None, "Some App") == "some-app"
    assert appimage.derive_alias(None, "linux-x86_64.AppImage") == "app"


def test_sha256_matches_hashlib(fake_appimage, tmp_path):
    path = fake_appimage(tmp_path / "a.AppImage", payload=b"x")
    assert appimage.sha256_of(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_extract_metadata_falls_back_on_non_executable(fake_appimage, tmp_path):
    path = fake_appimage(tmp_path / "Locked-1.0.AppImage", executable=False)
    meta = appimage.extract_metadata(path)
    assert meta.name == "Locked"
    assert meta.version == "1.0"
    assert any("extract" in w for w in meta.warnings)


def test_extract_metadata_type1_skips_runtime(fake_appimage, tmp_path):
    path = fake_appimage(tmp_path / "Old-0.1.AppImage", appimage_type=1)
    meta = appimage.extract_metadata(path)
    assert meta.version == "0.1"
    assert any("type-1" in w for w in meta.warnings)


def test_verify_appimage_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.AppImage"
    bad.write_bytes(b"definitely not an elf")
    import pytest
    from quiver.util.errors import VerificationError

    with pytest.raises(VerificationError):
        appimage.verify_appimage(bad, "x86_64")


def test_verify_appimage_arch_mismatch(fake_appimage, tmp_path):
    import pytest
    from quiver.util.errors import VerificationError

    arm = fake_appimage(tmp_path / "arm.AppImage", arch="aarch64")
    with pytest.raises(VerificationError, match="architecture"):
        appimage.verify_appimage(arm, "x86_64")
    make_appimage(tmp_path / "ok.AppImage")
    info = appimage.verify_appimage(tmp_path / "ok.AppImage", "x86_64")
    assert info.arch == "x86_64"


def test_extract_metadata_stashes_icon_outside_tmp(fake_appimage, xdg, monkeypatch, tmp_path):
    """The icon must survive the temp extraction dir being deleted."""
    from quiver.core import appimage as mod

    def fake_run(appimage, tmp, timeout):
        root = tmp / "squashfs-root"
        root.mkdir()
        (root / "app.desktop").write_text("[Desktop Entry]\nName=Kept\nIcon=kept\n")
        (root / "kept.png").write_bytes(b"\x89PNG kept-icon")
        return True

    monkeypatch.setattr(mod, "_run_extract", fake_run)
    path = fake_appimage(tmp_path / "Kept-1.0.AppImage")
    meta = mod.extract_metadata(path)
    assert meta.name == "Kept"
    assert meta.icon_path is not None
    assert meta.icon_path.exists()  # temp dir is gone, icon must still exist
    assert meta.icon_path.parent == xdg.cache / "quiver" / "icons"
    assert meta.icon_path.read_bytes() == b"\x89PNG kept-icon"


def test_arch_from_stem_uses_boundaries():
    assert appimage.parse_filename("Harmony-1.0.AppImage")["arch"] is None
    assert appimage.parse_filename("alarm-clock-1.0.AppImage")["arch"] is None
    assert appimage.parse_filename("Impactor-linux-aarch64.appimage")["arch"] == "aarch64"
    assert appimage.parse_filename("Impactor-linux-x86_64.appimage")["arch"] == "x86_64"


def test_read_update_info_from_elf_section(tmp_path):
    from tests.conftest import make_updinfo_appimage

    path = make_updinfo_appimage(
        tmp_path / "wb.AppImage",
        "gh-releases-zsync|winboat-org|winboat|latest|winboat-x86_64.AppImage",
    )
    from quiver.core import appimage as mod

    assert mod.read_update_info(path) == (
        "gh-releases-zsync|winboat-org|winboat|latest|winboat-x86_64.AppImage"
    )


def test_parse_update_info_variants():
    from quiver.core.appimage import parse_update_info

    assert parse_update_info("gh-releases-zsync|owner|repo|latest|x.AppImage") == ["owner/repo"]
    assert parse_update_info("gh-releases|owner|repo|v1|x") == ["owner/repo"]
    assert parse_update_info(
        "zsync|https://github.com/a/b/releases/download/latest/b-x86_64.AppImage.zsync"
    ) == ["a/b"]
    assert parse_update_info("nothing useful") == []
    assert parse_update_info(None) == []


def test_github_repo_from_app_id():
    from quiver.core.appimage import github_repo_from_app_id

    assert github_repo_from_app_id("io.github.bluemancz.hyprmod") == "bluemancz/hyprmod"
    assert github_repo_from_app_id("com.github.example.someapp") == "example/someapp"
    assert github_repo_from_app_id("org.kde.okular") is None
    assert github_repo_from_app_id("io.github.only-three") is None
    assert github_repo_from_app_id(None) is None


def test_extract_metadata_uses_updinfo_without_extraction(tmp_path):
    from quiver.core import appimage as mod

    from tests.conftest import make_updinfo_appimage

    path = make_updinfo_appimage(
        tmp_path / "NoExec-1.0.AppImage", "gh-releases-zsync|acme|tool|latest|t.AppImage"
    )
    path.chmod(0o644)  # even without +x the embedded info is readable
    meta = mod.extract_metadata(path)
    assert meta.update_info == "gh-releases-zsync|acme|tool|latest|t.AppImage"
    assert "acme/tool" in meta.github_hints
