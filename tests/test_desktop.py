from pathlib import Path

from quiver.core.registry import AppEntry
from quiver.util import desktop


def make_entry(**kwargs):
    params = dict(
        alias="foo",
        name="Foo App",
        path="/opt/managed/Foo-1.0.AppImage",
        version="1.0",
        arch="x86_64",
        categories=["Utility"],
        integrated=True,
        description="Does foo things",
    )
    params.update(kwargs)
    return AppEntry(**params)


def test_render_entry_has_marker_and_quoted_exec():
    content = desktop.render_entry(make_entry())
    assert "X-Quiver=managed" in content
    assert "X-Quiver-Alias=foo" in content
    assert 'Exec="/opt/managed/Foo-1.0.AppImage"' in content
    assert "TryExec=/opt/managed/Foo-1.0.AppImage" in content
    assert "Categories=Utility;" in content


def test_write_entry_only_when_changed(cfg):
    entry = make_entry()
    path, changed = desktop.write_entry(entry, cfg)
    assert changed and path.name == "quiver-foo.desktop"
    _, changed_again = desktop.write_entry(entry, cfg)
    assert not changed_again
    data = desktop.parse_desktop(path)
    assert desktop.is_ours(data)
    assert data["X-Quiver-Alias"] == "foo"


def test_exec_target_extraction():
    assert desktop.exec_target('"/opt/a b/Foo.AppImage" %U') == "/opt/a b/Foo.AppImage"
    assert desktop.exec_target("/opt/Foo.AppImage") == "/opt/Foo.AppImage"
    assert desktop.exec_target("foo --local") is None
    assert desktop.exec_target("") is None


def test_exec_args_end_up_in_entry(cfg):
    entry = make_entry(exec_args=["--ozone-platform=wayland"])
    path, _ = desktop.write_entry(entry, cfg)
    data = desktop.parse_desktop(path)
    assert data["Exec"] == '"/opt/managed/Foo-1.0.AppImage" --ozone-platform=wayland'


def test_adopt_entry_rewrites_exec_and_keeps_content(cfg, xdg):
    original = Path("/home/user/Downloads/MyApp-0.9.AppImage")
    entry_file = desktop.desktop_dir() / "myapp.desktop"
    entry_file.parent.mkdir(parents=True, exist_ok=True)
    entry_file.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name[en_US]=My App\n"
        "Name[zh_CN]=我的应用\n"
        f"Exec={original} %U\n"
        "Icon=/home/user/.local/share/icons/AppImage_Icons/myapp.png\n"
        "Categories=Utility;\n",
        encoding="utf-8",
    )
    app = make_entry(alias="myapp", name="My App", path="/state/share/AppImages/MyApp.AppImage")
    desktop.adopt_entry_file(entry_file, app, cfg)

    content = entry_file.read_text(encoding="utf-8")
    assert 'Exec="/state/share/AppImages/MyApp.AppImage"' in content
    assert "Name[zh_CN]=我的应用" in content  # localized names preserved
    assert desktop.parse_desktop(entry_file).get("X-Quiver") == "managed"
    assert "TryExec=/state/share/AppImages/MyApp.AppImage" in content


def test_find_entries_executing(cfg, xdg):
    target = Path("/state/share/AppImages/Find.AppImage")
    entry_file = desktop.desktop_dir() / "find.desktop"
    entry_file.parent.mkdir(parents=True, exist_ok=True)
    entry_file.write_text(f'[Desktop Entry]\nName=Find\nExec="{target}" %U\n')
    assert desktop.find_entries_executing(target) == [entry_file]
    assert desktop.find_entries_executing(Path("/nope.AppImage")) == []


def test_install_and_remove_icon(cfg, tmp_path):
    source = tmp_path / "icon.svg"
    source.write_text("<svg/>")
    installed = desktop.install_icon(source, cfg, "foo")
    assert installed == cfg.icon_dir / "foo.svg"
    assert installed.exists()
    assert desktop.remove_icon(cfg, "foo")
    assert not installed.exists()


def test_legacy_icon_lookup(cfg, xdg):
    legacy_dir = xdg.data / "icons" / "AppImage_Icons"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "winboat.svg").write_text("<svg/>")
    assert desktop.find_legacy_icon(cfg, "winboat") == legacy_dir / "winboat.svg"
    assert desktop.find_legacy_icon(cfg, "missing") is None


def test_integrate_adopts_existing_entry(cfg, xdg):
    original = xdg.home / "Downloads" / "Tool-1.5.AppImage"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"x")
    existing = desktop.desktop_dir() / "tool.desktop"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(f"[Desktop Entry]\nName=Tool\nExec={original} %u\nIcon=tool\n")

    managed = cfg.storage_dir / "Tool-1.5.AppImage"
    managed.parent.mkdir(parents=True, exist_ok=True)
    managed.write_bytes(b"x")
    app = make_entry(alias="tool", name="Tool", path=str(managed))
    result = desktop.integrate(app, cfg, adopt_exec_from=original)

    assert result.adopted
    assert result.entry_path == existing
    assert not (desktop.desktop_dir() / "quiver-tool.desktop").exists()  # no duplicate created
    assert desktop.exec_target(desktop.parse_desktop(existing)["Exec"]) == str(managed)


def test_deintegrate_removes_only_our_files(cfg):
    entry = make_entry()
    path, _ = desktop.write_entry(entry, cfg)
    (cfg.icon_dir / "foo.png").write_bytes(b"png")
    entry = AppEntry(
        **{**entry.to_dict(), "desktop_file": path.name, "icon_path": str(cfg.icon_dir / "foo.png")}
    )
    assert desktop.deintegrate(entry, cfg)
    assert not path.exists()
    assert not (cfg.icon_dir / "foo.png").exists()


def test_unmanaged_files_never_marked(cfg, xdg):
    """Entries without our marker must not parse as ours."""
    foreign = desktop.desktop_dir() / "waydroid.desktop"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("[Desktop Entry]\nName=Waydroid\nExec=/usr/bin/waydroid\n")
    assert not desktop.is_ours(desktop.parse_desktop(foreign))


def test_legacy_marker_still_recognized_as_ours(tmp_path):
    """Entries written before the quiver rename must stay owned."""
    entry_file = desktop.desktop_dir() / "old-timer.desktop"
    entry_file.parent.mkdir(parents=True, exist_ok=True)
    entry_file.write_text(
        "[Desktop Entry]\nName=Old\nExec=/x/y.AppImage\n"
        "X-AppImageManager=managed\nX-AppImageManager-Alias=old-timer\n"
    )
    data = desktop.parse_desktop(entry_file)
    assert desktop.is_ours(data)
    assert desktop.marker_alias(data) == "old-timer"


def test_adopt_entry_is_idempotent_and_keeps_exactly_one_marker_pair(cfg, xdg):
    """Re-adopting an already-adopted file must never drop its markers."""
    from quiver.core.registry import AppEntry as E

    entry_file = desktop.desktop_dir() / "app.desktop"
    entry_file.parent.mkdir(parents=True, exist_ok=True)
    entry_file.write_text("[Desktop Entry]\nName=A\nExec=/old/place.AppImage\n")
    app = E(alias="app", name="A", path="/state/App.AppImage")
    desktop.adopt_entry_file(entry_file, app, cfg)
    first = entry_file.read_text()
    assert first.count("X-Quiver=managed") == 1
    desktop.adopt_entry_file(entry_file, app, cfg)  # second pass
    second = entry_file.read_text()
    assert second.count("X-Quiver=managed") == 1
    assert second.count("X-Quiver-Alias=app") == 1
