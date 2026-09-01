"""Inspection and maintenance: scan, doctor, clean, repair, import-existing.

Scanning and diagnostics never modify anything. Mutating operations only ever
touch files this tool owns (marker key, quiver- prefix, or backup/temp areas).
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from quiver import appimage, desktop, storage
from quiver.appimage import hints_from_meta
from quiver.config import Config
from quiver.output import confirm
from quiver.registry import AppEntry, Registry

# ---- scan --------------------------------------------------------------------


@dataclass
class ScanReport:
    appimages: list[dict] = field(
        default_factory=list
    )  # {path, size, arch, type, executable, managed, alias}
    desktop_entries: list[dict] = field(
        default_factory=list
    )  # {file, name, exec, target, ok, managed, alias}
    icons: list[dict] = field(default_factory=list)  # {path, kind: legacy|managed|orphan}
    duplicates: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "appimages": self.appimages,
            "desktop_entries": self.desktop_entries,
            "icons": self.icons,
            "duplicates": self.duplicates,
        }


def _iter_appimage_files(directory: Path):
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() == ".appimage":
            yield path


def scan(cfg: Config, registry: Registry) -> ScanReport:
    report = ScanReport()
    managed_by_path = {str(Path(e.path).resolve()): e for e in registry.all()}
    originals_by_path = {
        str(Path(e.original_path).resolve()): e for e in registry.all() if e.original_path
    }

    seen: set[Path] = set()
    for directory in [*cfg.collection_dirs, cfg.storage_dir]:
        for path in _iter_appimage_files(directory):
            real = path.resolve()
            if real in seen:
                continue
            seen.add(real)
            info = appimage.detect(path)
            entry = managed_by_path.get(str(real))
            original_of = originals_by_path.get(str(real))
            duplicate_of = None
            identical = None
            if original_of is not None and entry is None:
                duplicate_of = original_of.alias
                identical = (
                    original_of.sha256 is not None
                    and appimage.sha256_of(path) == original_of.sha256
                )
            report.appimages.append(
                {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "arch": info.arch if info else None,
                    "type": info.appimage_type if info else None,
                    "executable": bool(path.stat().st_mode & 0o111),
                    "valid_appimage": info is not None,
                    "managed": entry is not None,
                    "alias": entry.alias if entry else None,
                    "duplicate_of": duplicate_of,
                    "identical_to_managed": identical,
                }
            )

    # desktop entries
    exec_targets: dict[str, list[str]] = {}
    registered_files = {e.desktop_file: e for e in registry.all() if e.desktop_file}
    if desktop.desktop_dir().is_dir():
        for entry_file in sorted(desktop.desktop_dir().glob("*.desktop")):
            data = desktop.parse_desktop(entry_file)
            if not data:
                continue
            exec_value = data.get("Exec", "")
            target = desktop.exec_target(exec_value)
            marked = desktop.is_ours(data)
            alias = desktop.marker_alias(data)
            # Ownership survives desktop tools (e.g. kmenuedit) stripping our
            # X- markers: a file the registry claims whose Exec points at the
            # managed copy is still ours.
            owner = registered_files.get(entry_file.name)
            registered = owner is not None and target == owner.path
            managed = marked or registered
            if owner is not None and registered and not alias:
                alias = owner.alias
            target_ok: bool | str = True
            if target:
                target_ok = Path(target).exists()
                exec_targets.setdefault(target, []).append(entry_file.name)
            record = {
                "file": entry_file.name,
                "name": data.get("Name", ""),
                "exec": exec_value,
                "target": target,
                "target_ok": bool(target_ok),
                "appimage_target": bool(target and target.lower().endswith(".appimage")),
                "managed": managed,
                "alias": alias,
                "registered": registered,
                "missing_markers": managed and not marked,
            }
            # Only surface AppImage-related or broken entries; waydroid/wine noise stays out.
            if managed or record["appimage_target"] or not record["target_ok"]:
                report.desktop_entries.append(record)

    for target, files in exec_targets.items():
        if len(files) > 1:
            report.duplicates.append({"exec": target, "entries": files})

    # icons
    from quiver import paths as quiver_paths

    referenced = referenced_icon_paths()
    icons_root = quiver_paths.data_home() / "icons"
    for legacy_name in desktop.LEGACY_ICON_DIRS:
        legacy_dir = icons_root / legacy_name
        if legacy_dir.is_dir():
            for icon in sorted(legacy_dir.iterdir()):
                if icon.is_file():
                    kind = (
                        "legacy (referenced)"
                        if icon.resolve() in referenced
                        else "legacy (unreferenced)"
                    )
                    report.icons.append({"path": str(icon), "kind": kind})
    if cfg.icon_dir.is_dir():
        used = {Path(e.icon_path).name for e in registry.all() if e.icon_path}
        for icon in sorted(cfg.icon_dir.iterdir()):
            if icon.is_file():
                kind = "managed" if icon.name in used else "orphan"
                report.icons.append({"path": str(icon), "kind": kind})
    return report


# ---- doctor --------------------------------------------------------------------


@dataclass
class Diagnostic:
    level: str  # ok | info | warn | error
    area: str
    message: str
    hint: str | None = None


EXTERNAL_TOOLS = {
    "update-desktop-database": "menu cache refresh after entry changes",
    "desktop-file-validate": "validating generated .desktop entries",
    "gtk-update-icon-cache": "icon cache refresh for themed icon dirs",
    "notify-send": "desktop notifications for update checks",
    "appimageupdate": "zsync-based delta updates (optional; plain downloads are used otherwise)",
}


def doctor(cfg: Config, registry: Registry) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    diags.append(
        Diagnostic(
            "ok" if cfg.path.exists() else "info",
            "config",
            f"config file: {cfg.path}" if cfg.path.exists() else "no config file; defaults in use",
        )
    )
    for label, path in (
        ("storage", cfg.storage_dir),
        ("backups", cfg.backup_dir),
        ("downloads", cfg.download_dir),
        ("icons", cfg.icon_dir),
    ):
        writable = path.exists() and path.is_dir() and _is_writable(path)
        diags.append(
            Diagnostic(
                "ok" if writable else "warn",
                "config",
                f"{label} dir {'writable' if writable else 'missing/not writable'}: {path}",
            )
        )

    free = storage.free_space(cfg.storage_dir if cfg.storage_dir.exists() else Path.home())
    if free is not None:
        level = "ok" if free > 2 * 1024**3 else ("warn" if free > 512 * 1024**2 else "error")
        diags.append(
            Diagnostic(level, "disk", f"{storage.human_size(free)} free under {cfg.storage_dir}")
        )

    for binary, purpose in EXTERNAL_TOOLS.items():
        found = shutil.which(binary) is not None
        diags.append(
            Diagnostic(
                "ok" if found else "info",
                "tools",
                f"{binary}: {'found' if found else 'not installed'} ({purpose})",
            )
        )

    for entry in registry.all():
        area = f"app:{entry.alias}"
        path = Path(entry.path)
        if not path.exists():
            diags.append(
                Diagnostic(
                    "error",
                    area,
                    f"AppImage missing: {path}",
                    hint="Restore it or run `quiver remove --purge` to forget it.",
                )
            )
            continue
        if not path.stat().st_mode & 0o111:
            diags.append(
                Diagnostic(
                    "warn",
                    area,
                    "file is not executable",
                    hint="`quiver repair` will restore the executable bit",
                )
            )
        info = appimage.detect(path)
        if info is None:
            diags.append(Diagnostic("error", area, "file is no longer a valid AppImage"))
        elif entry.arch and info.arch and entry.arch != info.arch:
            diags.append(
                Diagnostic(
                    "warn", area, f"arch changed on disk: {info.arch} (registered {entry.arch})"
                )
            )
        if entry.sha256 and entry.sha256 != appimage.sha256_of(path):
            diags.append(
                Diagnostic(
                    "warn",
                    area,
                    "file changed on disk since registration (app self-updated?)",
                    hint="`quiver refresh` re-reads its embedded version and metadata",
                )
            )
        if entry.integrated:
            entry_file = desktop.entry_path_for(entry.alias, entry.desktop_file)
            data = desktop.parse_desktop(entry_file) if entry_file.exists() else {}
            if not data:
                diags.append(
                    Diagnostic(
                        "warn",
                        area,
                        f"desktop entry missing: {entry_file.name}",
                        hint="`quiver repair` will recreate it",
                    )
                )
            else:
                if not desktop.is_ours(data):
                    diags.append(
                        Diagnostic(
                            "warn",
                            area,
                            "desktop entry lost its ownership markers",
                            hint="a desktop tool rewrote it; `quiver repair` re-stamps it",
                        )
                    )
                if desktop.exec_target(data.get("Exec", "")) != str(path):
                    diags.append(
                        Diagnostic(
                            "warn",
                            area,
                            "desktop entry points somewhere else",
                            hint="`quiver repair` will fix the Exec line",
                        )
                    )
                icon_line = data.get("Icon", "")
                if icon_line.startswith("/") and not Path(icon_line).exists():
                    diags.append(
                        Diagnostic(
                            "warn",
                            area,
                            f"entry Icon points at missing file: {icon_line}",
                            hint="`quiver repair` will restore it",
                        )
                    )
            if entry.icon_path and not Path(entry.icon_path).exists():
                diags.append(Diagnostic("warn", area, f"icon missing: {entry.icon_path}"))
        if not entry.source_configured:
            diags.append(
                Diagnostic(
                    "info",
                    area,
                    "no update source configured",
                    hint="`quiver detect-source` or `quiver source set`",
                )
            )
    return diags


def _is_writable(path: Path) -> bool:
    try:
        probe = path / ".quiver-write-probe"
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


# ---- clean ---------------------------------------------------------------------


@dataclass
class CleanReport:
    removed: list[dict] = field(default_factory=list)
    kept: list[dict] = field(default_factory=list)
    skipped: bool = False


def referenced_icon_paths() -> set[Path]:
    """Absolute Icon= paths referenced by ANY desktop entry (managed or not)."""
    referenced: set[Path] = set()
    if desktop.desktop_dir().is_dir():
        for entry_file in desktop.desktop_dir().glob("*.desktop"):
            icon = desktop.parse_desktop(entry_file).get("Icon", "")
            if icon.startswith("/"):
                try:
                    referenced.add(Path(icon).resolve())
                except OSError:
                    continue
    return referenced


def plan_clean(cfg: Config, registry: Registry) -> tuple[list[dict], str]:
    """Collect removable items. Returns (items, description)."""
    items: list[dict] = []

    for part in sorted(cfg.download_dir.glob(".*.part")) if cfg.download_dir.is_dir() else []:
        items.append({"kind": "partial download", "path": str(part), "size": part.stat().st_size})

    # Imported originals: files we copied into managed storage on import.
    # Deletion is offered because the user's intent was recorded (original_path);
    # hash agreement with the managed copy is reported so nothing is hidden.
    for entry in registry.all():
        original = entry.original_path
        if not original:
            continue
        original_file = Path(original)
        if not original_file.is_file():
            continue
        if str(original_file.resolve()) == str(Path(entry.path).resolve()):
            continue  # in-place import: the managed file IS this file
        identical = entry.sha256 is not None and appimage.sha256_of(original_file) == entry.sha256
        note = "identical to managed copy" if identical else "managed copy has changed since import"
        items.append(
            {
                "kind": f"imported original of {entry.alias} ({note})",
                "path": original,
                "size": original_file.stat().st_size,
            }
        )

    # Legacy icons (pre-tool dirs like AppImage_Icons) nobody references.
    referenced = referenced_icon_paths()
    from quiver import paths as quiver_paths

    icons_root = quiver_paths.data_home() / "icons"
    for legacy_name in desktop.LEGACY_ICON_DIRS:
        legacy_dir = icons_root / legacy_name
        if not legacy_dir.is_dir():
            continue
        for icon in sorted(legacy_dir.iterdir()):
            if icon.is_file() and icon.resolve() not in referenced:
                items.append(
                    {
                        "kind": "unreferenced legacy icon",
                        "path": str(icon),
                        "size": icon.stat().st_size,
                    }
                )

    aliases = registry.aliases()
    if desktop.desktop_dir().is_dir():
        for entry_file in desktop.desktop_dir().glob("quiver-*.desktop"):
            data = desktop.parse_desktop(entry_file)
            alias = desktop.marker_alias(data) or entry_file.stem.removeprefix("quiver-")
            if desktop.is_ours(data) and alias not in aliases:
                items.append(
                    {
                        "kind": "stale managed desktop entry",
                        "path": str(entry_file),
                        "size": entry_file.stat().st_size,
                    }
                )

    if cfg.icon_dir.is_dir():
        used = {Path(e.icon_path).name for e in registry.all() if e.icon_path}
        for icon in cfg.icon_dir.iterdir():
            if icon.is_file() and icon.name not in used:
                items.append(
                    {
                        "kind": "orphaned managed icon",
                        "path": str(icon),
                        "size": icon.stat().st_size,
                    }
                )

    for entry in registry.all():
        for removed in _prune_backup(cfg, entry.alias, dry_run=True):
            items.append(
                {
                    "kind": f"old backup ({entry.alias})",
                    "path": str(removed),
                    "size": removed.stat().st_size,
                }
            )

    # Backup dirs for aliases that are no longer registered.
    if cfg.backup_dir.is_dir():
        registered = registry.aliases()
        for app_dir in cfg.backup_dir.iterdir():
            if app_dir.is_dir() and app_dir.name not in registered:
                for backup in app_dir.iterdir():
                    if backup.is_file():
                        items.append(
                            {
                                "kind": f"orphaned backups (unregistered {app_dir.name})",
                                "path": str(backup),
                                "size": backup.stat().st_size,
                            }
                        )

    total = sum(item["size"] for item in items)
    description = f"{len(items)} item(s), {storage.human_size(total)}"
    return items, description


def clean(
    cfg: Config, registry: Registry, console: Console | None, *, dry_run: bool, assume_yes: bool
) -> CleanReport:
    report = CleanReport()
    items, description = plan_clean(cfg, registry)
    if not items:
        return report

    if console is not None:
        for item in items:
            label = escape(str(item["kind"]))
            console.print(
                f"  - {label}\n    {escape(item['path'])} ({storage.human_size(item['size'])})"
            )
    if dry_run:
        if console is not None:
            console.print(f"[cyan]•[/cyan] dry run: would remove {description} - nothing touched")
        report.skipped = True
        return report
    if console is not None and not confirm(
        console, f"Remove {description}?", assume_yes=assume_yes
    ):
        report.skipped = True
        return report

    for item in items:
        path = Path(item["path"])
        if path.exists() and storage.safe_unlink(path):
            report.removed.append(item)
        else:
            report.kept.append(item)
    for entry in registry.all():
        _prune_backup(cfg, entry.alias, dry_run=False)
    # Sweep now-empty backup directories.
    if cfg.backup_dir.is_dir():
        for app_dir in cfg.backup_dir.iterdir():
            if app_dir.is_dir() and not any(app_dir.iterdir()):
                with contextlib.suppress(OSError):
                    app_dir.rmdir()
    desktop.refresh_cache()
    return report


def _prune_backup(cfg: Config, alias: str, *, dry_run: bool) -> list[Path]:
    app_dir = cfg.backup_dir / alias
    if not app_dir.is_dir():
        return []
    backups = storage.list_backups(cfg.backup_dir, alias)
    stale = backups[cfg.backups_keep :]
    if dry_run:
        return stale
    removed: list[Path] = []
    for path in stale:
        if storage.safe_unlink(path):
            removed.append(path)
    return removed


# ---- repair ---------------------------------------------------------------------


@dataclass
class RepairReport:
    steps: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.steps)


def repair(
    cfg: Config,
    registry: Registry,
    console: Console | None,
    *,
    alias: str | None = None,
    assume_yes: bool = False,
) -> RepairReport:
    report = RepairReport()
    entries = [registry.require(alias)] if alias else registry.all()

    if console is not None and entries and not assume_yes:
        names = ", ".join(e.alias for e in entries)
        if not confirm(console, f"Repair integration for: {names}?", assume_yes=assume_yes):
            report.steps.append("cancelled")
            return report

    for entry in entries:
        path = Path(entry.path)
        area = entry.alias
        if path.exists() and not path.stat().st_mode & 0o111:
            path.chmod(0o755)
            report.steps.append(f"{area}: restored executable bit")
            # Deliberately no hash sync here: a changed file means the app
            # self-updated, and `quiver refresh` owns re-reading its metadata.
        if entry.integrated:
            entry_file = desktop.entry_path_for(entry.alias, entry.desktop_file)
            if not path.exists():
                if desktop.remove_entry(entry.alias, entry.desktop_file):
                    report.steps.append(f"{area}: removed desktop entry (file missing)")
            elif entry_file.exists():
                data = desktop.parse_desktop(entry_file)
                icon_line = data.get("Icon", "")
                icon_dead = icon_line.startswith("/") and not Path(icon_line).exists()
                icon_ref = (
                    entry.icon_path if entry.icon_path and Path(entry.icon_path).exists() else None
                )
                needs_fix = (
                    not desktop.is_ours(data)
                    or desktop.exec_target(data.get("Exec", "")) != str(path)
                    or (icon_dead and icon_ref)
                    or (icon_ref and icon_line != icon_ref)
                )
                if needs_fix:
                    # Rewrite in place: markers, Exec, Icon - preserving the
                    # file's own content (localized names, MimeType, ...).
                    desktop.adopt_entry_file(entry_file, entry, cfg, icon_path=icon_ref)
                    report.steps.append(f"{area}: desktop entry ownership/icons restored")
            else:
                _, changed = desktop.write_entry(entry, cfg)
                if changed:
                    report.steps.append(f"{area}: desktop entry recreated")
        if entry.icon_path and not Path(entry.icon_path).exists():
            registry.update(entry.alias, icon_path=None)
            report.steps.append(f"{area}: dropped missing icon reference")
    desktop.refresh_cache()
    return report


# ---- refresh ---------------------------------------------------------------------


@dataclass
class RefreshReport:
    refreshed: list[dict] = field(default_factory=list)  # {alias, changes: {field: [old, new]}}
    unchanged: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)  # {alias, error}

    def to_dict(self) -> dict:
        return {
            "refreshed": self.refreshed,
            "unchanged": self.unchanged,
            "failed": self.failed,
        }


def refresh(
    cfg: Config,
    registry: Registry,
    *,
    alias: str | None = None,
) -> RefreshReport:
    """Re-read AppImages on disk and sync registry metadata.

    Apps with a built-in updater (e.g. ZCode) replace their own file in place;
    the registry then holds a stale version and hash. Refresh re-extracts
    embedded metadata, re-stashes the icon, and records a history entry.
    """
    report = RefreshReport()
    entries = [registry.require(alias)] if alias else registry.all()

    for entry in entries:
        path = Path(entry.path)
        if not path.exists():
            report.failed.append({"alias": entry.alias, "error": f"missing: {path}"})
            continue
        if not path.stat().st_mode & 0o111:
            path.chmod(0o755)

        current_sha = appimage.sha256_of(path)
        current_size = path.stat().st_size
        if current_sha == entry.sha256 and entry.version:
            report.unchanged.append(entry.alias)
            continue

        try:
            meta = appimage.extract_metadata(path)
        except Exception as exc:  # extraction shells out; never abort the loop
            report.failed.append({"alias": entry.alias, "error": f"extraction failed: {exc}"})
            continue

        changes: dict[str, object] = {"sha256": current_sha, "size": current_size}
        diff: dict[str, list] = {}
        for field_name, new in (
            ("version", meta.version),
            ("name", meta.name),
            ("description", meta.description),
            ("homepage", meta.homepage),
            ("app_id", meta.app_id),
            ("arch", meta.arch),
        ):
            old = getattr(entry, field_name)
            if new and new != old:
                changes[field_name] = new
                diff[field_name] = [old, new]

        # A new file may ship a new icon; re-stash and repoint the entry in place
        # (adopt preserves content like localized names added by desktop tools).
        new_icon = None
        if current_sha != entry.sha256 and meta.icon_path:
            new_icon = desktop.install_icon(meta.icon_path, cfg, entry.alias)
        if new_icon and str(new_icon) != entry.icon_path:
            changes["icon_path"] = str(new_icon)
            diff["icon"] = [entry.icon_path, str(new_icon)]

        if not diff and current_sha == entry.sha256:
            # Looked (version was unknown) but the file has nothing new to
            # teach us: report unchanged instead of an empty "refreshed".
            report.unchanged.append(entry.alias)
            continue

        updated = registry.update(entry.alias, **changes)
        if new_icon and updated.integrated:
            entry_file = desktop.entry_path_for(entry.alias, updated.desktop_file)
            if entry_file.exists():
                if entry_file.name.startswith(desktop.ENTRY_PREFIX):
                    # our own generated entry: regenerate whole file (adds Icon)
                    desktop.write_entry(updated, cfg, filename=updated.desktop_file)
                else:
                    # adopted entry (e.g. renamed by kmenuedit): rewrite in place
                    desktop.adopt_entry_file(entry_file, updated, cfg, icon_path=str(new_icon))

        registry.add_history(
            entry.alias,
            action="refreshed",
            path=str(path),
            version=meta.version or entry.version,
            sha256=current_sha,
            size=current_size,
        )
        report.refreshed.append({"alias": entry.alias, "changes": diff})
    desktop.refresh_cache()
    return report


# ---- import existing ---------------------------------------------------------------


@dataclass
class ImportReport:
    adopted: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"adopted": self.adopted, "skipped": self.skipped, "failed": self.failed}


def _dedupe_alias(base: str, taken: set[str]) -> str:
    alias = base
    counter = 2
    while alias in taken:
        alias = f"{base}-{counter}"
        counter += 1
    return alias


def import_existing(
    cfg: Config,
    registry: Registry,
    console: Console | None,
    *,
    adopt_all: bool = False,
    assume_yes: bool = False,
    dry_run: bool = False,
    integrate: bool = True,
    in_place: bool | None = None,
    extra_dirs: list[Path] | None = None,
) -> ImportReport:
    """Find AppImages in collection dirs and adopt them into the registry."""
    report = ImportReport()
    directories = list(dict.fromkeys([*(extra_dirs or []), *cfg.collection_dirs]))
    already_paths = {str(Path(e.original_path or e.path).resolve()) for e in registry.all()}
    taken_aliases = registry.aliases()

    for directory in directories:
        if not directory.is_dir():
            report.skipped.append({"path": str(directory), "reason": "directory not found"})
            continue
        for path in _iter_appimage_files(directory):
            real = str(path.resolve())
            if real in already_paths:
                report.skipped.append({"path": str(path), "reason": "already managed"})
                continue
            if appimage.detect(path) is None:
                report.failed.append(
                    {"path": str(path), "error": "not a recognizable AppImage (bad magic bytes)"}
                )
                continue

            if dry_run:
                meta = appimage.extract_metadata(path)
                base_alias = appimage.derive_alias(meta.name or meta.app_id, path.name)
                report.adopted.append(
                    {
                        "alias": _dedupe_alias(base_alias, taken_aliases),
                        "path": str(path),
                        "name": meta.name or base_alias,
                        "version": meta.version,
                        "dry_run": True,
                    }
                )
                continue

            if console is not None and not adopt_all and not assume_yes:
                from quiver.output import is_interactive

                if not is_interactive(console):
                    report.skipped.append(
                        {"path": str(path), "reason": "non-interactive; use --adopt-all"}
                    )
                    continue
                from rich.prompt import Confirm

                if not Confirm.ask(f"Adopt {path.name}?", console=console, default=True):
                    report.skipped.append({"path": str(path), "reason": "declined"})
                    continue

            try:
                use_in_place = (
                    in_place if in_place is not None else cfg.data.get("add_mode") == "in-place"
                )
                if use_in_place:
                    managed_path = path
                    if not managed_path.stat().st_mode & 0o111:
                        managed_path.chmod(0o755)
                else:
                    managed_path = storage.copy_into_storage(path, cfg.storage_dir)
            except OSError as exc:
                report.failed.append({"path": str(path), "error": f"copy failed: {exc}"})
                continue

            # Extract from the managed copy: it is guaranteed executable, so the
            # runtime gives us the real embedded desktop entry/metainfo even when
            # the original file had lost its exec bit.
            meta = appimage.extract_metadata(managed_path)
            warnings = list(meta.warnings)
            base_alias = appimage.derive_alias(meta.name or meta.app_id, path.name)
            alias = _dedupe_alias(base_alias, taken_aliases)

            entry = AppEntry(
                alias=alias,
                name=meta.name or alias.replace("-", " ").title(),
                path=str(managed_path),
                original_path=str(path),
                app_id=meta.app_id,
                version=meta.version,
                arch=meta.arch,
                description=meta.description,
                homepage=meta.homepage,
                categories=meta.categories or ["Utility"],
                integrated=False,
                source_opts=hints_from_meta(meta),
                sha256=appimage.sha256_of(managed_path),
                size=managed_path.stat().st_size,
            )
            registry.add(entry)
            registry.add_history(
                alias,
                action="added",
                version=meta.version,
                path=str(managed_path),
                sha256=entry.sha256,
                size=entry.size,
            )
            taken_aliases.add(alias)
            already_paths.add(real)

            if integrate:
                result = desktop.integrate(
                    entry, cfg, icon_source=meta.icon_path, adopt_exec_from=path
                )
                registry.update(
                    alias,
                    integrated=True,
                    icon_path=result.icon_path,
                    desktop_file=result.entry_path.name,
                )
            record = {
                "alias": alias,
                "path": str(managed_path),
                "original": str(path),
                "name": entry.name,
                "version": meta.version,
                "adopted_entry": result.adopted if integrate else False,
                "warnings": warnings,
            }
            report.adopted.append(record)
    return report
