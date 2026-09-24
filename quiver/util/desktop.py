"""Desktop integration: .desktop entries, icons, menu cache.

Ownership model: every file this tool manages carries the marker key
``X-AppImageManager=managed``. Files without the marker are never modified or
deleted - they are somebody else's. The one exception is *adoption*: an
unmanaged entry whose Exec points exactly at an AppImage being imported gets
rewritten (with the user's confirmation at import time) to point at the
managed copy, and from then on it carries the marker.
"""

from __future__ import annotations

import configparser
import shutil
from dataclasses import dataclass
from pathlib import Path

from quiver.core.registry import AppEntry
from quiver.util import paths, storage

MARKER_KEY = "X-Quiver"
MARKER_VALUE = "managed"
ALIAS_KEY = "X-Quiver-Alias"
# Entries written before the quiver rename carry these; still recognized.
LEGACY_MARKER_KEY = "X-AppImageManager"
LEGACY_ALIAS_KEY = "X-AppImageManager-Alias"
_OWNERSHIP_KEYS = (MARKER_KEY, ALIAS_KEY, LEGACY_MARKER_KEY, LEGACY_ALIAS_KEY)

ENTRY_PREFIX = "quiver-"

# Icon directories that predate this tool; scan reports them, never touches them.
LEGACY_ICON_DIRS = ("AppImage_Icons",)


def desktop_dir() -> Path:
    return paths.desktop_entries_dir()


def entry_path_for(alias: str, filename: str | None = None) -> Path:
    name = filename if filename else f"{ENTRY_PREFIX}{alias}.desktop"
    if not name.endswith(".desktop"):
        name += ".desktop"
    return desktop_dir() / name


def parse_desktop(path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return {}
    if not parser.has_section("Desktop Entry"):
        return {}
    return dict(parser["Desktop Entry"])


def exec_target(exec_value: str) -> str | None:
    """Extract the executable path from an Exec= value (handles quoting)."""
    text = exec_value.strip()
    if not text:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        token = text[1:end] if end > 0 else text[1:]
    else:
        token = text.split()[0]
    return token if token.startswith("/") else None


def is_ours(data: dict[str, str]) -> bool:
    return data.get(MARKER_KEY, data.get(LEGACY_MARKER_KEY, "")).lower() == MARKER_VALUE


def marker_alias(data: dict[str, str]) -> str | None:
    """The alias an owned entry was written for (new or legacy key)."""
    return data.get(ALIAS_KEY) or data.get(LEGACY_ALIAS_KEY)


def render_entry(app: AppEntry, field_codes: str = "") -> str:
    name = app.name or app.alias
    exec_parts = [f'"{app.path}"']
    if app.exec_args:
        exec_parts.extend(app.exec_args)
    codes = field_codes.strip()
    if codes:
        exec_parts.append(codes)
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={name}",
    ]
    if app.description:
        lines.append(f"Comment={app.description}")
    lines.append(f"Exec={' '.join(exec_parts)}")
    lines.append(f"TryExec={app.path}")
    if app.icon_path:
        lines.append(f"Icon={app.icon_path}")
    lines.append("Terminal=false")
    lines.append(f"Categories={';'.join(app.categories) or 'Utility'};")
    if app.app_id:
        lines.append(f"StartupWMClass={app.app_id}")
    lines.append(f"{MARKER_KEY}={MARKER_VALUE}")
    lines.append(f"{ALIAS_KEY}={app.alias}")
    lines.append("")
    return "\n".join(lines)


def write_entry(app: AppEntry, cfg, *, filename: str | None = None) -> tuple[Path, bool]:
    """Write the entry only if content changed; returns (path, changed)."""
    path = entry_path_for(app.alias, filename or app.desktop_file)
    content = render_entry(app, cfg.data.get("desktop_field_codes", ""))
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path, True


def refresh_entry(app: AppEntry, cfg) -> bool:
    _, changed = write_entry(app, cfg)
    if changed:
        refresh_cache()
    return changed


def remove_entry(alias: str, filename: str | None = None) -> bool:
    path = entry_path_for(alias, filename)
    removed = storage.safe_unlink(path)
    if removed:
        refresh_cache()
    return removed


def install_icon(icon_source: Path, cfg, alias: str) -> Path:
    """Copy an extracted icon into managed icon storage; returns new path."""
    storage.ensure_dir(cfg.icon_dir)
    ext = icon_source.suffix or ".png"
    target = cfg.icon_dir / f"{alias}{ext}"
    shutil.copy2(icon_source, target)
    target.chmod(0o644)
    return target


def remove_icon(cfg, alias: str) -> bool:
    removed = False
    for ext in (".png", ".svg", ".svgz", ".xpm"):
        candidate = cfg.icon_dir / f"{alias}{ext}"
        if candidate.exists():
            candidate.unlink(missing_ok=True)
            removed = True
    return removed


def find_entries_executing(path: Path) -> list[Path]:
    """All desktop entries (managed or not) whose Exec points at ``path``."""
    target = str(path)
    found: list[Path] = []
    if not desktop_dir().is_dir():
        return found
    for entry_file in desktop_dir().glob("*.desktop"):
        data = parse_desktop(entry_file)
        exec_value = data.get("Exec", "")
        if exec_target(exec_value) == target:
            found.append(entry_file)
    return found


def adopt_entry_file(entry_file: Path, app: AppEntry, cfg, *, icon_path: str | None = None) -> Path:
    """Rewrite an existing entry in place to point at the managed AppImage."""
    lines = entry_file.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    has_tryexec = any(line.startswith("TryExec=") for line in lines)
    for line in lines:
        if line.startswith("Exec="):
            exec_parts = [f'"{app.path}"']
            if app.exec_args:
                exec_parts.extend(app.exec_args)
            codes = str(cfg.data.get("desktop_field_codes", "")).strip()
            if codes:
                exec_parts.append(codes)
            out.append(f"Exec={' '.join(exec_parts)}")
            if not has_tryexec:
                out.append(f"TryExec={app.path}")
        elif line.startswith("TryExec="):
            out.append(f"TryExec={app.path}")
        elif line.startswith("Icon=") and icon_path:
            out.append(f"Icon={icon_path}")
        elif any(line.startswith(key + "=") for key in _OWNERSHIP_KEYS):
            continue  # old/legacy marker lines are replaced by the fresh pair below
        else:
            out.append(line)
    out.append(f"{MARKER_KEY}={MARKER_VALUE}")
    out.append(f"{ALIAS_KEY}={app.alias}")
    entry_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    refresh_cache()
    return entry_file


def find_legacy_icon(cfg, icon_name: str) -> Path | None:
    """Look for ``icon_name`` in pre-existing icon dirs (read-only lookup)."""
    if not icon_name:
        return None
    for legacy in LEGACY_ICON_DIRS:
        base = paths.data_home() / "icons" / legacy
        for ext in (".png", ".svg", ".svgz", ".xpm"):
            candidate = base / f"{icon_name}{ext}"
            if candidate.is_file():
                return candidate
    return None


@dataclass
class IntegrationResult:
    entry_path: Path
    icon_path: str | None
    changed: bool
    adopted: bool = False


def integrate(
    app: AppEntry,
    cfg,
    *,
    icon_source: Path | None = None,
    adopt_exec_from: Path | None = None,
) -> IntegrationResult:
    """Create/refresh desktop integration for a managed app.

    ``adopt_exec_from``: original path of the AppImage being imported; if an
    existing unmanaged entry points there, it is adopted (repointed in place,
    keeping its original content like localized names) instead of creating a
    duplicate quiver-*.desktop file.
    """
    icon_path = app.icon_path
    if icon_source is not None:
        icon_path = str(install_icon(icon_source, cfg, app.alias))
    elif icon_path and not Path(icon_path).is_file():
        legacy = find_legacy_icon(cfg, app.alias) or find_legacy_icon(cfg, Path(app.path).stem)
        icon_path = str(legacy) if legacy else None

    app = AppEntry(**{**app.to_dict(), "icon_path": icon_path})

    if adopt_exec_from is not None:
        for entry_file in find_entries_executing(adopt_exec_from):
            data = parse_desktop(entry_file)
            if not is_ours(data):
                icon_ref = icon_path
                if not icon_ref:
                    existing_icon = data.get("Icon", "")
                    icon_ref = (
                        existing_icon
                        if existing_icon.startswith("/") and Path(existing_icon).is_file()
                        else None
                    )
                adopt_entry_file(entry_file, app, cfg, icon_path=icon_ref)
                return IntegrationResult(
                    entry_path=entry_file, icon_path=icon_path, changed=True, adopted=True
                )

    path, changed = write_entry(app, cfg, filename=app.desktop_file)
    if changed:
        refresh_cache()
    return IntegrationResult(entry_path=path, icon_path=icon_path, changed=changed, adopted=False)


def deintegrate(app: AppEntry, cfg) -> bool:
    """Remove the desktop entry and managed icon for an app. Returns changed."""
    changed = remove_entry(app.alias, app.desktop_file)
    if app.icon_path and str(cfg.icon_dir) in str(app.icon_path):
        Path(app.icon_path).unlink(missing_ok=True)
        changed = True
    return changed


def refresh_cache() -> bool:
    """Run update-desktop-database when available. Only called after changes."""
    binary = shutil.which("update-desktop-database")
    if binary is None or not desktop_dir().is_dir():
        return False
    import subprocess

    subprocess.run(
        [binary, str(desktop_dir())],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    return True
