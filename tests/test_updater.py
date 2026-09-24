"""End-to-end update pipeline tests with a fake provider + mock HTTP."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from quiver.core import updater
from quiver.core.appimage import sha256_of
from quiver.core.registry import AppEntry
from quiver.core.updater import perform_update, rollback
from quiver.providers.base import Asset, ProviderError, Release, UpdateProvider, register

from tests.conftest import make_appimage


@pytest.fixture
def fake_provider(monkeypatch):
    """Register a throwaway 'fake' provider; cleans up afterwards."""
    from quiver.providers import base

    state: dict = {}

    @register
    class FakeProvider(UpdateProvider):
        type_name = "fake"

        def latest_release(self, app, cfg, client):
            if "release" not in state:
                raise ProviderError("no release configured in test")
            return state["release"]

    yield state
    base._PROVIDER_REGISTRY.pop("fake", None)


def make_app(registry, tmp_path, version="1.0.0", **kwargs):
    path = make_appimage(tmp_path / "storage" / "Test-1.0.0-x86_64.AppImage")
    entry = AppEntry(
        alias="test",
        name="Test",
        path=str(path),
        version=version,
        arch="x86_64",
        source_type="fake",
        source_repo="fake/repo",
        sha256=sha256_of(path),
        size=path.stat().st_size,
        integrated=False,
    )
    entry = AppEntry(**{**entry.to_dict(), **kwargs})
    registry.add(entry)
    registry.add_history(
        "test",
        action="added",
        version=version,
        path=str(path),
        sha256=entry.sha256,
        size=entry.size,
    )
    return registry.require("test")


def serve_new_version(tmp_path, *, arch="x86_64", prefix=b"new-version-"):
    data_file = tmp_path / "new.AppImage"
    make_appimage(data_file, arch=arch, payload=prefix)
    data = data_file.read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def test_check_update_available(cfg, registry, fake_provider, mock_client, tmp_path):
    entry = make_app(registry, tmp_path)
    fake_provider["release"] = Release(
        tag="v1.1.0",
        version="1.1.0",
        assets=[Asset(name="Test-1.1.0-x86_64.AppImage", url="http://x/new.AppImage", size=10)],
    )
    result = updater.check(entry, cfg, mock_client(lambda r: None))
    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.latest_version == "1.1.0"
    assert result.asset.name == "Test-1.1.0-x86_64.AppImage"


def test_check_up_to_date(cfg, registry, fake_provider, mock_client, tmp_path):
    entry = make_app(registry, tmp_path)
    fake_provider["release"] = Release(tag="v1.0.0", version="1.0.0", assets=[])
    result = updater.check(entry, cfg, mock_client(lambda r: None))
    assert result.status == updater.STATUS_UP_TO_DATE


def test_check_unknown_version(cfg, registry, fake_provider, mock_client, tmp_path):
    entry = make_app(registry, tmp_path, version=None)
    fake_provider["release"] = Release(tag="v2.0", version="2.0", assets=[])
    result = updater.check(entry, cfg, mock_client(lambda r: None))
    assert result.status == updater.STATUS_UNKNOWN_VERSION


def test_check_no_source(cfg, registry, mock_client, tmp_path):
    entry = make_app(registry, tmp_path, source_type=None, source_repo=None)
    result = updater.check(entry, cfg, mock_client(lambda r: None))
    assert result.status == updater.STATUS_NO_SOURCE


def test_perform_update_full_pipeline(cfg, registry, fake_provider, mock_client, tmp_path):
    entry = make_app(registry, tmp_path)
    original_path = Path(entry.path)
    original_bytes = original_path.read_bytes()
    data, digest = serve_new_version(tmp_path)

    fake_provider["release"] = Release(
        tag="v1.1.0",
        version="1.1.0",
        assets=[
            Asset(
                name="Test-1.1.0-x86_64.AppImage",
                url="http://x/new.AppImage",
                size=len(data),
                sha256=digest,
            )
        ],
    )
    client = mock_client(lambda request: httpx.Response(200, content=data))
    outcome = perform_update(entry, cfg, registry, client, None, assume_yes=True)

    assert outcome.status == "updated", outcome.error
    assert outcome.new_version == "1.1.0"
    # file replaced with the new build, same path, still executable
    assert original_path.read_bytes() == data
    assert original_path.stat().st_mode & 0o111
    # registry updated
    updated = registry.require("test")
    assert updated.version == "1.1.0"
    assert updated.sha256 == digest
    # backup created and contains the old bytes
    backups = list((cfg.backup_dir / "test").iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == original_bytes
    # history row recorded
    assert registry.history("test")[0].action == "updated"
    # no .part files left behind
    assert not list(original_path.parent.glob(".*.part"))


def test_perform_update_rejects_non_appimage(cfg, registry, fake_provider, mock_client, tmp_path):
    entry = make_app(registry, tmp_path)
    original_bytes = Path(entry.path).read_bytes()
    garbage = b"this is not an appimage at all"

    fake_provider["release"] = Release(
        tag="v1.1.0",
        version="1.1.0",
        assets=[Asset(name="Test-1.1.0-x86_64.AppImage", url="http://x/bad.AppImage")],
    )
    client = mock_client(lambda request: httpx.Response(200, content=garbage))
    outcome = perform_update(entry, cfg, registry, client, None, assume_yes=True)

    assert outcome.status == "failed"
    assert "not an AppImage" in outcome.error
    assert Path(entry.path).read_bytes() == original_bytes  # untouched
    assert not list(Path(entry.path).parent.glob(".*.part"))


def test_perform_update_rejects_bad_sha256(cfg, registry, fake_provider, mock_client, tmp_path):
    entry = make_app(registry, tmp_path)
    data, _digest = serve_new_version(tmp_path)
    fake_provider["release"] = Release(
        tag="v1.1.0",
        version="1.1.0",
        assets=[Asset(name="Test.AppImage", url="http://x/new.AppImage", sha256="0" * 64)],
    )
    client = mock_client(lambda request: httpx.Response(200, content=data))
    outcome = perform_update(entry, cfg, registry, client, None, assume_yes=True)
    assert outcome.status == "failed"
    assert "sha256" in outcome.error


def test_perform_update_rejects_wrong_arch(cfg, registry, fake_provider, mock_client, tmp_path):
    entry = make_app(registry, tmp_path)
    data, digest = serve_new_version(tmp_path, arch="aarch64")
    fake_provider["release"] = Release(
        tag="v1.1.0",
        version="1.1.0",
        assets=[Asset(name="Test-2.0.0.AppImage", url="http://x/arm.AppImage", sha256=digest)],
    )
    client = mock_client(lambda request: httpx.Response(200, content=data))
    outcome = perform_update(entry, cfg, registry, client, None, assume_yes=True)
    assert outcome.status == "failed"
    assert "architecture" in outcome.error


def test_dry_run_changes_nothing(cfg, registry, fake_provider, mock_client, tmp_path):
    entry = make_app(registry, tmp_path)
    before = Path(entry.path).read_bytes()
    data, _ = serve_new_version(tmp_path)
    fake_provider["release"] = Release(
        tag="v1.1.0",
        version="1.1.0",
        assets=[Asset(name="Test.AppImage", url="http://x/new.AppImage", size=len(data))],
    )
    outcome = perform_update(
        entry, cfg, registry, mock_client(lambda r: None), None, assume_yes=True, dry_run=True
    )
    assert outcome.status == "dry_run"
    assert Path(entry.path).read_bytes() == before
    assert not list(cfg.backup_dir.rglob("*test*"))


def test_rollback_restores_previous(cfg, registry, fake_provider, mock_client, tmp_path):
    from pathlib import Path

    entry = make_app(registry, tmp_path)
    old_bytes = Path(entry.path).read_bytes()
    data, digest = serve_new_version(tmp_path, prefix=b"v2-bytes-")
    fake_provider["release"] = Release(
        tag="v2.0.0",
        version="2.0.0",
        assets=[Asset(name="Test-2.0.0.AppImage", url="http://x/new.AppImage", sha256=digest)],
    )
    client = mock_client(lambda request: httpx.Response(200, content=data))
    assert perform_update(entry, cfg, registry, client, None, assume_yes=True).status == "updated"

    outcome = rollback(registry.require("test"), cfg, registry, None, assume_yes=True)
    assert outcome.status == "rolled_back"
    assert Path(entry.path).read_bytes() == old_bytes
    assert registry.require("test").version == "1.0.0"


def test_check_fingerprints_unknown_version(cfg, registry, fake_provider, mock_client, tmp_path):
    """Unknown installed version + asset sha256 match => recognized exactly."""
    entry = make_app(registry, tmp_path, version=None)
    digest = sha256_of(Path(entry.path))
    fake_provider["release"] = Release(
        tag="v2.6.0",
        version="2.6.0",
        assets=[Asset(name="Test-2.6.0-x86_64.AppImage", url="http://x/t.AppImage", sha256=digest)],
    )
    result = updater.check(entry, cfg, mock_client(lambda r: None))
    assert result.status == updater.STATUS_UP_TO_DATE
    assert result.matched_version == "2.6.0"
    updater.record_check(registry, entry, result)
    assert registry.require("test").version == "2.6.0"


def test_check_unknown_version_when_sha_differs(
    cfg, registry, fake_provider, mock_client, tmp_path
):
    entry = make_app(registry, tmp_path, version=None)
    fake_provider["release"] = Release(
        tag="v2.6.0",
        version="2.6.0",
        assets=[
            Asset(name="Test-2.6.0-x86_64.AppImage", url="http://x/t.AppImage", sha256="0" * 64)
        ],
    )
    result = updater.check(entry, cfg, mock_client(lambda r: None))
    assert result.status == updater.STATUS_UNKNOWN_VERSION
    assert result.matched_version is None
