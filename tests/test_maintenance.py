from __future__ import annotations

from pathlib import Path

from quiver.core import maintenance
from quiver.core.appimage import AppImageMeta
from quiver.core.registry import AppEntry
from quiver.util import desktop

from tests.conftest import make_appimage


def add_managed(registry, cfg, tmp_path, alias="managed", name="Managed"):
    path = make_appimage(cfg.storage_dir / f"{name}-1.0-x86_64.AppImage")
    entry = AppEntry(
        alias=alias, name=name, path=str(path), version="1.0", arch="x86_64", integrated=True
    )
    registry.add(entry)
    return entry


def test_scan_classifies(cfg, registry, tmp_path, xdg):
    make_appimage(cfg.storage_dir / "Managed-1.0-x86_64.AppImage")
    registry.add(
        AppEntry(
            alias="managed",
            name="Managed",
            path=str(cfg.storage_dir / "Managed-1.0-x86_64.AppImage"),
        )
    )
    unmanaged = make_appimage(xdg.home / "Applications" / "Loose-2.0.AppImage")
    notan = xdg.home / "Applications" / "fake.AppImage"
    notan.write_bytes(b"garbage")

    apps_dir = xdg.data / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    broken = apps_dir / "broken.desktop"
    broken.write_text("[Desktop Entry]\nName=Broken\nExec=/gone/ghost.AppImage\n")
    foreign = apps_dir / "foreign.desktop"
    foreign.write_text(
        "[Desktop Entry]\nName=Other\nExec=/usr/bin/env\n"
    )  # valid, non-AppImage: ignored

    legacy = xdg.data / "icons" / "AppImage_Icons"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "old.png").write_bytes(b"png")

    report = maintenance.scan(cfg, registry)

    paths = [a["path"] for a in report.appimages]
    assert str(unmanaged) in paths
    assert str(notan) in paths
    by_path = {a["path"]: a for a in report.appimages}
    assert by_path[str(unmanaged)]["managed"] is False
    assert by_path[str(unmanaged)]["valid_appimage"] is True
    assert by_path[str(notan)]["valid_appimage"] is False
    assert sum(1 for a in report.appimages if a["managed"]) == 1

    files = [d["file"] for d in report.desktop_entries]
    assert "broken.desktop" in files
    assert "foreign.desktop" not in files  # unrelated entries are not our business
    broken_record = next(d for d in report.desktop_entries if d["file"] == "broken.desktop")
    assert broken_record["target_ok"] is False
    assert broken_record["appimage_target"] is True

    assert any(i["kind"].startswith("legacy") for i in report.icons)


def test_scan_detects_duplicates(cfg, registry, xdg):
    target = make_appimage(xdg.home / "Applications" / "Dup.AppImage")
    apps_dir = xdg.data / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    for name in ("dup1.desktop", "dup2.desktop"):
        (apps_dir / name).write_text(f"[Desktop Entry]\nName=Dup\nExec={target}\n")
    report = maintenance.scan(cfg, registry)
    assert len(report.duplicates) == 1
    assert set(report.duplicates[0]["entries"]) == {"dup1.desktop", "dup2.desktop"}


def test_plan_clean_only_touches_owned_files(cfg, registry, xdg):
    apps_dir = xdg.data / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    stale = apps_dir / "quiver-ghost.desktop"
    stale.write_text(
        "[Desktop Entry]\nName=Ghost\nExec=/x/y.AppImage\nX-Quiver=managed\nX-Quiver-Alias=ghost\n"
    )
    foreign = apps_dir / "quiver-lookalike.desktop"
    foreign.write_text(
        "[Desktop Entry]\nName=NotOurs\nExec=/x/y.AppImage\n"
    )  # quiver- name, no marker
    part = cfg.download_dir / ".New-2.0-x86_64.AppImage.part"
    part.write_bytes(b"partial")

    items, _description = maintenance.plan_clean(cfg, registry)
    paths = [Path(i["path"]) for i in items]
    assert stale in paths
    assert part in paths
    assert foreign not in paths  # never managed by us -> never cleaned


def test_clean_removes_and_prunes_backups(cfg, registry, tmp_path):
    entry = AppEntry(
        alias="kept", name="Kept", path=str(make_appimage(cfg.storage_dir / "k.AppImage"))
    )
    registry.add(entry)
    backups = cfg.backup_dir / "kept"
    backups.mkdir(parents=True, exist_ok=True)
    import time

    for i in range(5):
        f = backups / f"kept--1.0.{i}--2020010{i}.AppImage"
        f.write_bytes(b"old")
        stamp = time.time() - (100 - i)
        import os

        os.utime(f, (stamp, stamp))
    stale_entry_dir = cfg.backup_dir / "ghost"
    stale_entry_dir.mkdir(parents=True, exist_ok=True)
    (stale_entry_dir / "x.AppImage").write_bytes(b"x")

    report = maintenance.clean(cfg, registry, None, dry_run=False, assume_yes=True)
    removed_paths = [Path(i["path"]) for i in report.removed]
    remaining = sorted(p.name for p in backups.iterdir())
    assert len(remaining) == cfg.backups_keep  # pruned to keep count
    assert len(removed_paths) >= 3  # 2 old backups + ghost backup


def test_clean_dry_run_removes_nothing(cfg, registry):
    part = cfg.download_dir / ".x.part"
    part.write_bytes(b"x")
    report = maintenance.clean(cfg, registry, None, dry_run=True, assume_yes=True)
    assert report.skipped is True
    assert part.exists()


def test_doctor_reports_missing_file(cfg, registry, tmp_path):
    entry = AppEntry(
        alias="gone",
        name="Gone",
        path=str(tmp_path / "missing.AppImage"),
        integrated=True,
        desktop_file="quiver-gone.desktop",
    )
    registry.add(entry)
    diags = maintenance.doctor(cfg, registry)
    assert any(d.level == "error" and "missing" in d.message for d in diags)


def test_doctor_reports_no_source(cfg, registry, tmp_path):
    path = make_appimage(cfg.storage_dir / "NoSrc.AppImage")
    registry.add(AppEntry(alias="nosrc", name="NoSrc", path=str(path)))
    diags = maintenance.doctor(cfg, registry)
    assert any(d.level == "info" and "no update source" in d.message for d in diags)


def _fake_meta(monkeypatch, name="Imported App", version="3.1.4", icon=None):
    meta = AppImageMeta(
        name=name,
        version=version,
        arch="x86_64",
        description="desc",
        icon_path=icon,
        categories=["Utility"],
    )
    monkeypatch.setattr(maintenance.appimage, "extract_metadata", lambda p, **k: meta)
    return meta


def test_import_existing_copies_and_integrates(cfg, registry, xdg, monkeypatch):
    icon_src = xdg.data / "raw-icon.png"
    icon_src.write_bytes(b"png")
    _fake_meta(monkeypatch, icon=icon_src)
    original = make_appimage(xdg.home / "Applications" / "Imported-3.1.4.AppImage")

    report = maintenance.import_existing(cfg, registry, None, adopt_all=True)

    assert len(report.adopted) == 1
    record = report.adopted[0]
    assert record["alias"] == "imported-app"
    assert Path(record["path"]).parent == cfg.storage_dir
    assert original.exists()  # original untouched
    managed = registry.require("imported-app")
    assert managed.version == "3.1.4"
    assert managed.integrated
    assert managed.icon_path and Path(managed.icon_path).exists()
    entry_file = xdg.data / "applications" / "quiver-imported-app.desktop"
    assert entry_file.exists()


def test_import_existing_adopts_desktop_entry(cfg, registry, xdg, monkeypatch):
    _fake_meta(monkeypatch)
    original = make_appimage(xdg.home / "Applications" / "Imported-3.1.4.AppImage")
    apps_dir = xdg.data / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    existing = apps_dir / "imported.desktop"
    existing.write_text(f"[Desktop Entry]\nName=Imported\nExec={original}\nIcon=imported\n")

    report = maintenance.import_existing(cfg, registry, None, adopt_all=True)

    assert report.adopted[0]["adopted_entry"] is True
    content = existing.read_text()
    assert str(cfg.storage_dir / "Imported-3.1.4.AppImage") in content
    assert "X-Quiver=managed" in content
    assert not (apps_dir / "quiver-imported.desktop").exists()


def test_import_existing_dry_run_touches_nothing(cfg, registry, xdg, monkeypatch):
    _fake_meta(monkeypatch)
    original = make_appimage(xdg.home / "Applications" / "Imported-3.1.4.AppImage")
    report = maintenance.import_existing(cfg, registry, None, adopt_all=True, dry_run=True)
    assert report.adopted and report.adopted[0]["dry_run"]
    assert registry.count() == 0
    assert not list(cfg.storage_dir.iterdir())
    assert original.exists()


def test_import_existing_skips_invalid(cfg, registry, xdg):
    bad = xdg.home / "Applications" / "broken.AppImage"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not an elf")
    report = maintenance.import_existing(cfg, registry, None, adopt_all=True)
    assert report.failed and "magic" in report.failed[0]["error"]
    assert registry.count() == 0


def test_import_existing_dedupes_aliases(cfg, registry, xdg, monkeypatch):
    _fake_meta(monkeypatch)
    make_appimage(xdg.home / "Applications" / "Imported-3.1.4.AppImage")
    make_appimage(xdg.home / "Applications" / "Imported.AppImage")  # same derived alias
    report = maintenance.import_existing(cfg, registry, None, adopt_all=True)
    aliases = sorted(r["alias"] for r in report.adopted)
    assert aliases == ["imported-app", "imported-app-2"]


def test_repair_fixes_exec_bit_and_entry(cfg, registry, tmp_path):
    path = make_appimage(cfg.storage_dir / "Broken-1.0.AppImage", executable=False)
    entry = AppEntry(
        alias="broken",
        name="Broken",
        path=str(path),
        integrated=True,
        version="1.0",
        desktop_file="quiver-broken.desktop",
    )
    registry.add(entry)
    report = maintenance.repair(cfg, registry, None, assume_yes=True)
    assert path.stat().st_mode & 0o111
    assert (Path(desktop.desktop_dir()) / "quiver-broken.desktop").exists()
    assert any("executable" in s for s in report.steps)


def _managed_with_original(registry, cfg, tmp_path, original_dir):
    from quiver.core import appimage
    from quiver.core.registry import AppEntry as E

    from tests.conftest import make_appimage as mk

    original = mk(original_dir / "Orig-1.0-x86_64.AppImage")
    managed = mk(cfg.storage_dir / "Orig-1.0-x86_64-2.AppImage")
    entry = E(
        alias="orig",
        name="Orig",
        path=str(managed),
        original_path=str(original),
        version="1.0",
        sha256=appimage.sha256_of(managed),
    )
    registry.add(entry)
    return original, managed, entry


def test_plan_clean_offers_imported_originals(cfg, registry, tmp_path, xdg):
    original, _managed, _entry = _managed_with_original(
        registry, cfg, tmp_path, xdg.home / "Applications"
    )
    items, _ = maintenance.plan_clean(cfg, registry)
    kinds = [i["kind"] for i in items]
    assert any("imported original of orig" in k and "identical" in k for k in kinds)
    assert str(original) in [i["path"] for i in items]


def test_plan_clean_skips_in_place_imports(cfg, registry, tmp_path, xdg):
    from quiver.core.registry import AppEntry as E

    from tests.conftest import make_appimage as mk

    same = mk(xdg.home / "Applications" / "Same-1.0.AppImage")
    registry.add(E(alias="same", name="Same", path=str(same), original_path=str(same)))
    items, _ = maintenance.plan_clean(cfg, registry)
    assert not any("imported original" in i["kind"] for i in items)


def test_plan_clean_notes_drifted_originals(cfg, registry, tmp_path, xdg):
    original, _managed, _entry = _managed_with_original(
        registry, cfg, tmp_path, xdg.home / "Applications"
    )
    original.write_bytes(original.read_bytes() + b"changed")  # upstream updated since import
    items, _ = maintenance.plan_clean(cfg, registry)
    kinds = [i["kind"] for i in items]
    assert any("imported original of orig" in k and "changed since import" in k for k in kinds)


def test_plan_clean_offers_unreferenced_legacy_icons_only(cfg, registry, xdg):
    legacy_dir = xdg.data / "icons" / "AppImage_Icons"
    legacy_dir.mkdir(parents=True)
    orphaned = legacy_dir / "orphan.png"
    orphaned.write_bytes(b"png")
    referenced = legacy_dir / "in-use.png"
    referenced.write_bytes(b"png")
    apps_dir = xdg.data / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    (apps_dir / "user.desktop").write_text(
        f"[Desktop Entry]\nName=U\nExec=/bin/ls\nIcon={referenced}\n"
    )

    items, _ = maintenance.plan_clean(cfg, registry)
    paths = [i["path"] for i in items]
    assert str(orphaned) in paths
    assert str(referenced) not in paths


def test_clean_removes_imported_original(cfg, registry, tmp_path, xdg):
    original, _managed, _entry = _managed_with_original(
        registry, cfg, tmp_path, xdg.home / "Applications"
    )
    report = maintenance.clean(cfg, registry, None, dry_run=False, assume_yes=True)
    assert any("imported original" in i["kind"] for i in report.removed)
    assert not original.exists()


def test_scan_labels_imported_originals(cfg, registry, tmp_path, xdg):
    original, _managed, _entry = _managed_with_original(
        registry, cfg, tmp_path, xdg.home / "Applications"
    )
    report = maintenance.scan(cfg, registry)
    record = next(a for a in report.appimages if str(original) == a["path"])
    assert record["managed"] is False
    assert record["duplicate_of"] == "orig"
    assert record["identical_to_managed"] is True


def test_scan_recognizes_registered_entry_with_stripped_markers(cfg, registry, xdg, tmp_path):
    """A desktop tool (kmenuedit) rewrote our entry and dropped the X- markers;
    registry ownership (filename + Exec target) must keep it recognized."""
    managed = make_appimage(cfg.storage_dir / "Kept-1.0.AppImage")
    entry = AppEntry(
        alias="kept", name="Kept", path=str(managed), integrated=True, desktop_file="kept.desktop"
    )
    registry.add(entry)
    entry_file = xdg.data / "applications" / "kept.desktop"
    entry_file.parent.mkdir(parents=True, exist_ok=True)
    entry_file.write_text(
        f'[Desktop Entry]\nName=Kept\nExec="{managed}" %U\nIcon=kept\n'
        "MimeType=x-scheme-handler/kept;\n"
    )
    report = maintenance.scan(cfg, registry)
    record = next(d for d in report.desktop_entries if d["file"] == "kept.desktop")
    assert record["managed"] is True
    assert record["registered"] is True
    assert record["missing_markers"] is True
    assert record["alias"] == "kept"


def test_doctor_and_repair_restore_stripped_entry(cfg, registry, xdg, tmp_path):
    managed = make_appimage(cfg.storage_dir / "Kept-1.0.AppImage")
    icon = cfg.icon_dir / "kept.png"
    icon.write_bytes(b"png")
    entry = AppEntry(
        alias="kept",
        name="Kept",
        path=str(managed),
        integrated=True,
        desktop_file="kept.desktop",
        icon_path=str(icon),
    )
    registry.add(entry)
    entry_file = xdg.data / "applications" / "kept.desktop"
    entry_file.parent.mkdir(parents=True, exist_ok=True)
    # markers gone, Icon points at a deleted path, MimeType must survive
    entry_file.write_text(
        f'[Desktop Entry]\nName=Kept\nExec="{managed}"\n'
        f"Icon={cfg.icon_dir / 'dead.png'}\n"
        "MimeType=x-scheme-handler/kept;\n"
    )

    diags = maintenance.doctor(cfg, registry)
    assert any("ownership markers" in d.message for d in diags)
    assert any("Icon points at missing file" in d.message for d in diags)

    report = maintenance.repair(cfg, registry, None, assume_yes=True)
    assert any("ownership/icons restored" in s for s in report.steps)
    content = entry_file.read_text()
    assert "X-Quiver=managed" in content
    assert f"Icon={icon}" in content
    assert "MimeType=x-scheme-handler/kept;" in content  # content preserved


# ---- refresh ---------------------------------------------------------------------


def _registered(registry, cfg, *, alias="app", filename="App-1.0-x86_64.AppImage"):
    from quiver.core import appimage as ai

    path = make_appimage(cfg.storage_dir / filename)
    entry = AppEntry(
        alias=alias,
        name="App",
        path=str(path),
        version="1.0",
        arch="x86_64",
        integrated=True,
        sha256=ai.sha256_of(path),
    )
    registry.add(entry)
    return entry


def test_refresh_syncs_self_updated_file(cfg, registry, tmp_path, monkeypatch):
    entry = _registered(registry, cfg)
    path = Path(entry.path)
    path.write_bytes(path.read_bytes() + b"-self-updated")  # app replaced itself
    _fake_meta(monkeypatch, version="2.0")

    report = maintenance.refresh(cfg, registry)

    assert [r["alias"] for r in report.refreshed] == ["app"]
    updated = registry.get("app")
    assert updated.version == "2.0"
    from quiver.core import appimage as ai

    assert updated.sha256 == ai.sha256_of(path)
    assert updated.size == path.stat().st_size
    assert report.unchanged == []
    history = registry.history("app")
    assert history and history[0].action == "refreshed"


def test_refresh_unchanged_when_file_matches(cfg, registry, tmp_path, monkeypatch):
    _registered(registry, cfg)
    called = []

    def _spy(p, **k):
        called.append(p)
        return AppImageMeta(name="App", version="1.0")

    monkeypatch.setattr(maintenance.appimage, "extract_metadata", _spy)
    report = maintenance.refresh(cfg, registry)
    assert report.unchanged == ["app"]
    assert report.refreshed == []
    assert called == []  # fast path: no extraction when hash and version agree


def test_refresh_fills_unknown_version_without_file_change(cfg, registry, monkeypatch):
    _registered(registry, cfg)
    registry.update("app", version=None)  # iloader case: never knew the version
    _fake_meta(monkeypatch, version="1.2.7")

    report = maintenance.refresh(cfg, registry)

    assert report.refreshed[0]["changes"]["version"] == [None, "1.2.7"]
    assert registry.get("app").version == "1.2.7"


def test_refresh_reports_missing_file(cfg, registry):
    entry = _registered(registry, cfg)
    Path(entry.path).unlink()
    report = maintenance.refresh(cfg, registry)
    assert report.failed and "missing" in report.failed[0]["error"]


def test_refresh_updates_icon_and_entry(cfg, registry, xdg, monkeypatch):
    entry = _registered(registry, cfg)
    desktop.write_entry(entry, cfg)
    path = Path(entry.path)
    path.write_bytes(path.read_bytes() + b"-new")

    icon_src = xdg.data / "new-icon.png"
    icon_src.write_bytes(b"png")
    _fake_meta(monkeypatch, version="2.0", icon=icon_src)

    maintenance.refresh(cfg, registry)

    updated = registry.get("app")
    assert updated.icon_path and Path(updated.icon_path).is_file()
    data = desktop.parse_desktop(desktop.entry_path_for("app"))
    assert data["Icon"] == updated.icon_path


def test_doctor_flags_self_updated_file(cfg, registry):
    entry = _registered(registry, cfg)
    path = Path(entry.path)
    path.write_bytes(path.read_bytes() + b"-changed")
    diags = maintenance.doctor(cfg, registry)
    drift = [d for d in diags if "changed on disk" in d.message]
    assert drift and drift[0].level == "warn"
    assert drift[0].hint and "refresh" in drift[0].hint


def test_doctor_quiet_when_file_matches(cfg, registry):
    _registered(registry, cfg)
    diags = maintenance.doctor(cfg, registry)
    assert not any("changed on disk" in d.message for d in diags)


def test_refresh_unchanged_when_nothing_new_to_learn(cfg, registry, monkeypatch):
    # version unknown AND undiscoverable (iloader case): not an endless "refreshed"
    _registered(registry, cfg)
    registry.update("app", version=None)
    meta = AppImageMeta(name="App", version=None, arch="x86_64")  # matches entry
    monkeypatch.setattr(maintenance.appimage, "extract_metadata", lambda p, **k: meta)

    report = maintenance.refresh(cfg, registry)

    assert report.unchanged == ["app"]
    assert report.refreshed == []
    assert registry.history("app") == []  # no history noise for a no-op
