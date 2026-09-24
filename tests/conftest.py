"""Shared fixtures. Everything is isolated into tmp_path via XDG/HOME env."""

from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

MACHINES = {"i386": 3, "x86_64": 62, "arm": 40, "aarch64": 183, "riscv64": 243}


@pytest.fixture(autouse=True)
def _no_desktop_cache(monkeypatch):
    """Never shell out to update-desktop-database during tests."""
    import quiver.util.desktop as desktop_mod

    monkeypatch.setattr(desktop_mod.shutil, "which", lambda _: None)


@pytest.fixture(autouse=True)
def xdg(tmp_path, monkeypatch):
    """Isolate every test (HOME + all XDG dirs). autouse: no test may ever
    touch the developer's real config, registry, desktop entries or icons."""
    home = tmp_path / "home"
    data = tmp_path / "data"
    config = tmp_path / "config"
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    for d in (home, data, config, state, cache):
        d.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return SimpleNamespace(home=home, data=data, config=config, state=state, cache=cache)


@pytest.fixture
def cfg(xdg):
    from quiver.util.config import Config

    conf = Config.load()
    conf.ensure_dirs()
    return conf


@pytest.fixture
def registry(xdg):
    from quiver.core.registry import Registry

    return Registry()


def make_appimage(
    path: Path,
    *,
    arch: str = "x86_64",
    payload: bytes = b"payload-data-",
    executable: bool = True,
    appimage_type: int = 2,
    size_pad: int = 0,
) -> Path:
    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4] = 2  # 64-bit
    header[5] = 1  # little endian
    header[6] = 1  # ELF version
    header[8:11] = b"AI" + bytes([appimage_type])
    struct.pack_into("<H", header, 16, 3)  # e_type = ET_DYN
    struct.pack_into("<H", header, 18, MACHINES[arch])
    data = bytes(header) + payload * 3 + b"\0" * size_pad
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o755 if executable else 0o644)
    return path


@pytest.fixture
def fake_appimage(tmp_path):
    return make_appimage


@pytest.fixture
def mock_client():
    """Build an httpx.Client backed by a MockTransport handler."""

    def _build(handler) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    return _build


def make_updinfo_appimage(path: Path, info: str) -> Path:
    """Build a minimal type-2 AppImage whose ELF carries a .upd_info section."""
    import struct

    raw = info.encode() + b"\0"
    shstr = b"\x00.upd_info\x00.shstrtab\x00"
    info_off, info_len = 64, len(raw)
    shstr_off = info_off + info_len
    shoff = shstr_off + len(shstr)

    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4], header[5], header[6] = 2, 1, 1
    header[8:11] = b"AI\x02"
    struct.pack_into("<H", header, 16, 3)
    struct.pack_into("<H", header, 18, 62)
    struct.pack_into("<Q", header, 0x28, shoff)
    struct.pack_into("<H", header, 0x3A, 64)
    struct.pack_into("<H", header, 0x3C, 3)
    struct.pack_into("<H", header, 0x3E, 1)

    def section(name_off: int, sh_type: int, offset: int, size: int) -> bytes:
        return struct.pack("<IIQQQQIIQQ", name_off, sh_type, 0, 0, offset, size, 0, 0, 0, 0)

    sections = (
        section(0, 0, 0, 0)
        + section(shstr.index(b".shstrtab"), 3, shstr_off, len(shstr))
        + section(shstr.index(b".upd_info"), 1, info_off, info_len)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + raw + shstr + sections)
    path.chmod(0o755)
    return path
