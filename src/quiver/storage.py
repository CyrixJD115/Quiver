"""Filesystem operations: managed copies, atomic replacement, backups."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from quiver.errors import AimError


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_path(directory: Path, filename: str) -> Path:
    """Return a non-colliding path in ``directory`` for ``filename``."""
    candidate = directory / filename
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def copy_into_storage(source: Path, storage_dir: Path, *, mode: int = 0o755) -> Path:
    """Copy an AppImage into managed storage (original left untouched)."""
    ensure_dir(storage_dir)
    target = unique_path(storage_dir, source.name)
    shutil.copy2(source, target)
    target.chmod(mode)
    return target


def move_into_storage(source: Path, storage_dir: Path, *, mode: int = 0o755) -> Path:
    ensure_dir(storage_dir)
    target = unique_path(storage_dir, source.name)
    shutil.move(str(source), str(target))
    target.chmod(mode)
    return target


def atomic_replace(source: Path, target: Path, *, mode: int | None = None) -> None:
    """Atomically move ``source`` onto ``target`` (same filesystem required)."""
    if mode is not None:
        source.chmod(mode)
    # Flush file data to disk before the rename makes it visible.
    fd = os.open(source, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(source, target)
    _fsync_dir(target.parent)


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass  # directory fsync is best-effort


def backup_file(source: Path, backup_dir: Path, alias: str, *, keep: int = 3) -> Path:
    """Copy the current AppImage into the backup area, prune old ones."""
    app_backup_dir = ensure_dir(backup_dir / alias)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = unique_path(
        app_backup_dir, f"{alias}--{source.stem}--{stamp}{source.suffix or '.AppImage'}"
    )
    shutil.copy2(source, target)
    prune_backups(app_backup_dir, keep)
    return target


def prune_backups(app_backup_dir: Path, keep: int) -> list[Path]:
    """Keep only the ``keep`` newest backups; returns removed paths."""
    if not app_backup_dir.is_dir():
        return []
    backups = sorted(
        (p for p in app_backup_dir.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: list[Path] = []
    for stale in backups[keep:]:
        try:
            stale.unlink()
            removed.append(stale)
        except OSError:
            pass
    return removed


def list_backups(backup_dir: Path, alias: str) -> list[Path]:
    app_dir = backup_dir / alias
    if not app_dir.is_dir():
        return []
    return sorted(
        (p for p in app_dir.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True
    )


def human_size(num: int | float | None) -> str:
    if not num:
        return "?"
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} PiB"


def free_space(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def remove_tree(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def safe_unlink(path: Path) -> bool:
    """Unlink a file if it exists; returns whether something was removed."""
    try:
        path.unlink()
        return True
    except (OSError, FileNotFoundError):
        return False


__all__ = [
    "AimError",
    "atomic_replace",
    "backup_file",
    "copy_into_storage",
    "ensure_dir",
    "free_space",
    "human_size",
    "list_backups",
    "move_into_storage",
    "prune_backups",
    "remove_tree",
    "safe_unlink",
    "unique_path",
]
