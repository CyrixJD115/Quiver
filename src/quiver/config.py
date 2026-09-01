"""TOML configuration, kept strictly separate from application state.

Config lives at ``$XDG_CONFIG_HOME/quiver/config.toml``. Values may contain ``~``
and environment-style paths; they are expanded lazily when read.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from quiver import paths
from quiver.errors import UsageError

DEFAULTS: dict[str, Any] = {
    "storage_dir": "~/.local/share/AppImages",
    "backup_dir": "~/.local/share/quiver/backups",
    "download_dir": "~/.cache/quiver/downloads",
    "icon_dir": "~/.local/share/quiver/icons",
    "collection_dirs": ["~/Applications"],
    "backups_keep": 3,
    "add_mode": "copy",  # copy | move | in-place
    "auto_check": "manual",  # manual | off
    "notify": False,
    "github": {"token": "", "prerelease": False},
    "desktop_field_codes": "",  # e.g. "%U" appended to Exec
}

_VALID_ADD_MODES = {"copy", "move", "in-place"}
_VALID_AUTO_CHECK = {"manual", "off"}

# key -> validator(approximate type name for messages)
_PATH_KEYS = {"storage_dir", "backup_dir", "download_dir", "icon_dir"}
_SETTABLE = set(DEFAULTS) | {"github.token", "github.prerelease"}


def config_file_path() -> Path:
    return paths.app_config_dir() / "config.toml"


def _validate(key: str, value: Any) -> Any:
    if key not in _SETTABLE:
        raise UsageError(f"Unknown configuration key: {key!r}")
    if key in _PATH_KEYS:
        if not isinstance(value, str) or not value.strip():
            raise UsageError(f"{key} must be a non-empty path string")
        return value
    if key == "collection_dirs":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise UsageError("collection_dirs must be a list of paths")
        return value
    if key == "backups_keep":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise UsageError("backups_keep must be a non-negative integer")
        return value
    if key == "add_mode":
        if value not in _VALID_ADD_MODES:
            raise UsageError(f"add_mode must be one of {sorted(_VALID_ADD_MODES)}")
        return value
    if key == "auto_check":
        if value not in _VALID_AUTO_CHECK:
            raise UsageError(f"auto_check must be one of {sorted(_VALID_AUTO_CHECK)}")
        return value
    if key == "notify":
        if not isinstance(value, bool):
            raise UsageError("notify must be true or false")
        return value
    if key == "desktop_field_codes":
        if not isinstance(value, str):
            raise UsageError("desktop_field_codes must be a string")
        return value
    if key == "github.token":
        if not isinstance(value, str):
            raise UsageError("github.token must be a string")
        return value
    if key == "github.prerelease":
        if not isinstance(value, bool):
            raise UsageError("github.prerelease must be true or false")
        return value
    raise UsageError(f"Key {key!r} is not settable")


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


_TRUTHY = ("1", "true", "yes", "on")


def parse_config_value(key: str, value: str) -> Any:
    """Convert a CLI/RPC string to the typed value a config key expects."""
    if key == "backups_keep":
        return int(value)
    if key.endswith(".prerelease") or key == "notify":
        return value.lower() in _TRUTHY
    if key == "collection_dirs":
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Config:
    """Loaded configuration with typed accessors."""

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or config_file_path()
        data: dict[str, Any] = {
            k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
            for k, v in DEFAULTS.items()
        }
        if path.exists():
            try:
                loaded = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
                raise UsageError(f"Invalid TOML in {path}: {exc}") from exc
            for key, value in loaded.items():
                if key in data and isinstance(data[key], dict) and isinstance(value, dict):
                    data[key].update(value)
                else:
                    data[key] = value
        return cls(data, path)

    def get(self, key: str) -> Any:
        node: Any = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise UsageError(f"Unknown configuration key: {key!r}")
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        if key not in _SETTABLE:
            raise UsageError(
                f"Unknown configuration key: {key!r}",
                hint="Run `quiver config show` to see valid keys.",
            )
        value = _validate(key, value)
        parts = key.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(tomli_w.dumps(self.data), encoding="utf-8")

    # ---- expanded paths -------------------------------------------------
    @property
    def storage_dir(self) -> Path:
        return _expand(self.data["storage_dir"])

    @property
    def backup_dir(self) -> Path:
        return _expand(self.data["backup_dir"])

    @property
    def download_dir(self) -> Path:
        return _expand(self.data["download_dir"])

    @property
    def icon_dir(self) -> Path:
        return _expand(self.data["icon_dir"])

    @property
    def collection_dirs(self) -> list[Path]:
        return [_expand(d) for d in self.data.get("collection_dirs", [])]

    @property
    def backups_keep(self) -> int:
        return int(self.data.get("backups_keep", 3))

    def ensure_dirs(self) -> None:
        for d in (
            self.storage_dir,
            self.backup_dir,
            self.download_dir,
            self.icon_dir,
            paths.app_state_dir(),
            paths.desktop_entries_dir(),
        ):
            d.mkdir(parents=True, exist_ok=True)

    def github_token(self) -> str:
        return str(self.data.get("github", {}).get("token", "")) or os.environ.get(
            "GITHUB_TOKEN", ""
        )
