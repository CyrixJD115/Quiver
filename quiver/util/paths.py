"""XDG base-directory resolution.

Everything resolves lazily through functions (never module-level constants)
so tests can monkeypatch the environment and so nothing is hardcoded to a
specific username.
"""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(env_var: str, default: tuple[str, ...]) -> Path:
    value = os.environ.get(env_var)
    if value:
        return Path(value).expanduser()
    return Path.home().joinpath(*default)


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", (".local", "share"))


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", (".config",))


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", (".local", "state"))


def cache_home() -> Path:
    return _xdg("XDG_CACHE_HOME", (".cache",))


def app_data_dir() -> Path:
    """Managed application data (icons, backups)."""
    return data_home() / "quiver"


def app_state_dir() -> Path:
    """Registry database location."""
    return state_home() / "quiver"


def app_config_dir() -> Path:
    return config_home() / "quiver"


def app_cache_dir() -> Path:
    return cache_home() / "quiver"


def desktop_entries_dir() -> Path:
    return data_home() / "applications"
