import pytest

from quiver.config import Config
from quiver.errors import UsageError


def test_defaults(cfg):
    assert cfg.storage_dir.name == "AppImages"
    assert cfg.backups_keep == 3
    assert cfg.data["add_mode"] == "copy"


def test_set_get_roundtrip(cfg):
    cfg.set("storage_dir", "~/Apps")
    assert cfg.get("storage_dir") == "~/Apps"
    reloaded = Config.load(cfg.path)
    assert reloaded.storage_dir.name == "Apps"


def test_set_nested(cfg):
    cfg.set("github.token", "abc123")
    assert cfg.get("github")["token"] == "abc123"


def test_unknown_key_rejected(cfg):
    with pytest.raises(UsageError):
        cfg.set("nonsense_key", "x")
    with pytest.raises(UsageError):
        cfg.get("nonsense_key")


def test_invalid_values_rejected(cfg):
    with pytest.raises(UsageError):
        cfg.set("backups_keep", "many")
    with pytest.raises(UsageError):
        cfg.set("add_mode", "teleport")
    with pytest.raises(UsageError):
        cfg.set("auto_check", "whenever")


def test_bool_parsing(cfg):
    cfg.set("notify", True)
    assert cfg.get("notify") is True
    cfg.set("github.prerelease", False)
    assert cfg.get("github")["prerelease"] is False


def test_expanded_paths_respect_home(cfg, xdg):
    assert str(cfg.storage_dir).startswith(str(xdg.home))
    assert cfg.icon_dir.parent.name == "quiver"


def test_github_token_from_env(cfg, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    assert cfg.github_token() == "env-token"
    cfg.set("github.token", "file-token")
    assert cfg.github_token() == "file-token"


def test_collection_dirs(cfg, xdg):
    dirs = cfg.collection_dirs
    assert len(dirs) == 1
    assert dirs[0] == xdg.home / "Applications"


def test_ensure_dirs_creates(cfg):
    assert cfg.storage_dir.is_dir()
    assert cfg.backup_dir.is_dir()
    assert cfg.download_dir.is_dir()
    assert cfg.icon_dir.is_dir()
