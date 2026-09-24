"""CLI end-to-end tests via Typer's CliRunner. Fully isolated via XDG env."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from quiver.cli import app
from quiver.core import appimage
from quiver.core.appimage import AppImageMeta
from typer.testing import CliRunner

from tests.conftest import make_appimage

runner = CliRunner()


@pytest.fixture(autouse=True)
def _fake_extraction(monkeypatch, tmp_path):
    """Avoid running real AppImage runtimes; return deterministic metadata."""
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG fake")

    def fake_extract(path, **kwargs):
        return AppImageMeta(
            name="Fake App",
            version="1.0.0",
            arch="x86_64",
            app_id="io.quiver.FakeApp",
            description="A fake app",
            icon_path=icon,
            categories=["Development"],
            github_hints=["some/dev"],
        )

    monkeypatch.setattr(appimage, "extract_metadata", fake_extract)
    return fake_extract


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "quiver" in result.output


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in (
        "add",
        "rm",
        "ls",
        "update",
        "check",
        "doctor",
        "scan",
        "import",
        "rollback",
    ):
        assert cmd in result.output
    # merged away as visible top-level commands (still hidden or as subcommands)
    assert "check-all" not in result.output
    assert "import-existing" not in result.output
    assert "detect-source" not in result.output


def test_hidden_aliases_still_work(tmp_path):
    appfile = make_appimage(tmp_path / "dl" / "Fake-1.0.0-x86_64.AppImage")
    assert runner.invoke(app, ["add", str(appfile), "--yes"]).exit_code == 0
    for args in (
        ["--json", "list"],
        ["--json", "check-all"],
        ["--json", "import-existing", "--adopt-all", "--yes", "--dry-run"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)


def test_update_without_alias_updates_all(tmp_path):
    appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
    assert runner.invoke(app, ["add", str(appfile), "--yes"]).exit_code == 0
    result = runner.invoke(app, ["--json", "update", "--yes"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list) and data[0]["status"] in ("skipped_no_source", "up_to_date")


def test_check_without_alias_checks_all(tmp_path):
    appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
    assert runner.invoke(app, ["add", str(appfile), "--yes"]).exit_code == 0
    result = runner.invoke(app, ["--json", "check"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list) and data[0]["alias"] == "fake-app"


def test_add_list_info_flow(tmp_path):
    appfile = make_appimage(tmp_path / "dl" / "Fake-1.0.0-x86_64.AppImage")
    result = runner.invoke(app, ["add", str(appfile), "--yes"])
    assert result.exit_code == 0, result.output
    assert "added" in result.output

    listing = runner.invoke(app, ["--json", "list"])
    assert listing.exit_code == 0
    entries = json.loads(listing.output)
    assert len(entries) == 1
    assert entries[0]["alias"] == "fake-app"
    assert entries[0]["version"] == "1.0.0"

    info = runner.invoke(app, ["--json", "info", "fake-app"])
    assert info.exit_code == 0
    data = json.loads(info.output)
    assert data["source_opts"]["github_hints"] == ["some/dev"]
    # desktop entry was created and marked as ours
    from quiver.util import paths

    entry_file = paths.desktop_entries_dir() / data["desktop_file"]
    assert entry_file.exists()
    assert "X-Quiver=managed" in entry_file.read_text()


def test_add_rejects_non_appimage(tmp_path):
    bad = tmp_path / "nope.txt"
    bad.write_text("hi")
    result = runner.invoke(app, ["add", str(bad), "--yes"])
    assert result.exit_code == 2
    assert "magic" in result.output


def test_add_duplicate_alias_rejected(tmp_path):
    appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
    assert runner.invoke(app, ["add", str(appfile), "--yes"]).exit_code == 0
    second = make_appimage(tmp_path / "Fake-2.0.0-x86_64.AppImage")
    result = runner.invoke(app, ["add", str(second), "--yes"])
    assert result.exit_code == 2


def test_remove_without_yes_refuses_non_interactive(tmp_path):
    appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
    runner.invoke(app, ["add", str(appfile), "--yes"])
    result = runner.invoke(app, ["remove", "fake-app"])  # no --yes, no tty
    assert result.exit_code == 2
    assert "--yes" in result.output
    # with --yes it works and takes the entry with it
    result = runner.invoke(app, ["remove", "fake-app", "--yes"])
    assert result.exit_code == 0
    assert runner.invoke(app, ["--json", "list"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["--json", "list"]).output) == []


def test_source_set_and_check(tmp_path, monkeypatch):
    from quiver.providers import base
    from quiver.providers.base import Asset, Release, UpdateProvider, register

    @register
    class FakeSource(UpdateProvider):
        type_name = "fakesrc"

        def latest_release(self, app, cfg, client):
            return Release(
                tag="v1.1.0",
                version="1.1.0",
                assets=[Asset(name="Fake-1.1.0-x86_64.AppImage", url="http://x/f.AppImage")],
            )

    try:
        appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
        runner.invoke(app, ["add", str(appfile), "--yes"])
        result = runner.invoke(app, ["source", "set", "fake-app", "fakesrc", "whatever"])
        assert result.exit_code == 0, result.output

        check = runner.invoke(app, ["--json", "check", "fake-app"])
        assert check.exit_code == 0, check.output
        data = json.loads(check.output)
        assert data["status"] == "update_available"
        assert data["latest_version"] == "1.1.0"
    finally:
        base._PROVIDER_REGISTRY.pop("fakesrc", None)


def test_check_unknown_alias():
    result = runner.invoke(app, ["check", "nope"])
    assert result.exit_code == 3


def test_update_end_to_end(tmp_path, monkeypatch):
    from quiver.providers import base
    from quiver.providers.base import Asset, Release, UpdateProvider, register
    from quiver.util import download as download_mod

    new_file = make_appimage(tmp_path / "new.AppImage", payload=b"v2-payload-")
    new_bytes = new_file.read_bytes()
    new_sha = hashlib.sha256(new_bytes).hexdigest()

    @register
    class FakeSource(UpdateProvider):
        type_name = "fakesrc"

        def latest_release(self, app, cfg, client):
            return Release(
                tag="v2.0.0",
                version="2.0.0",
                assets=[
                    Asset(
                        name="Fake-2.0.0-x86_64.AppImage",
                        url="http://x/new.AppImage",
                        size=len(new_bytes),
                        sha256=new_sha,
                    )
                ],
            )

    monkeypatch.setattr(
        download_mod,
        "http_client",
        lambda cfg=None, timeout=30.0: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=new_bytes))
        ),
    )
    try:
        appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
        runner.invoke(app, ["add", str(appfile), "--yes", "--source", "fakesrc:x"])
        result = runner.invoke(app, ["--json", "update", "fake-app", "--yes"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "updated"
        assert data["old_version"] == "1.0.0"
        assert data["new_version"] == "2.0.0"

        listing = json.loads(runner.invoke(app, ["--json", "list"]).output)
        assert listing[0]["version"] == "2.0.0"
        assert listing[0]["sha256"] == new_sha

        history = json.loads(runner.invoke(app, ["--json", "history", "fake-app"]).output)
        assert any(h["action"] == "updated" for h in history)
    finally:
        base._PROVIDER_REGISTRY.pop("fakesrc", None)


def test_check_all_reports_no_source(tmp_path):
    appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
    runner.invoke(app, ["add", str(appfile), "--yes", "--no-integrate"])
    result = runner.invoke(app, ["check-all"])
    assert result.exit_code == 0  # no-source is informational, not a failure
    assert "no update source" in result.output


def test_config_set_get_show():
    assert runner.invoke(app, ["config", "set", "backups_keep", "5"]).exit_code == 0
    result = runner.invoke(app, ["config", "get", "backups_keep"])
    assert "5" in result.output
    show = runner.invoke(app, ["config", "show"])
    assert "storage_dir" in show.output
    bad = runner.invoke(app, ["config", "set", "bogus_key", "x"])
    assert bad.exit_code == 2


def test_config_path_lists_locations():
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    assert "registry.db" in result.output


def test_doctor_clean_exit_when_empty():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "0 errors" in result.output


def test_clean_dry_run_leaves_files(tmp_path):
    from quiver.util.config import Config

    cfg = Config.load()
    cfg.ensure_dirs()
    part = cfg.download_dir / ".stale.part"
    part.write_bytes(b"x")
    result = runner.invoke(app, ["clean", "--dry-run"])
    assert result.exit_code == 0
    assert "dry run" in result.output
    assert part.exists()


def test_import_existing_cli(tmp_path, xdg):
    make_appimage(xdg.home / "Applications" / "Fake-1.0.0-x86_64.AppImage")
    result = runner.invoke(app, ["import-existing", "--adopt-all", "--yes"])
    assert result.exit_code == 0, result.output
    entries = json.loads(runner.invoke(app, ["--json", "list"]).output)
    assert [e["alias"] for e in entries] == ["fake-app"]
    assert (xdg.home / "Applications" / "Fake-1.0.0-x86_64.AppImage").exists()


def test_scan_reads_only(tmp_path, xdg):
    make_appimage(xdg.home / "Applications" / "Fake-1.0.0-x86_64.AppImage")
    result = runner.invoke(app, ["--json", "scan"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["appimages"] and data["appimages"][0]["managed"] is False
    assert (xdg.home / "Applications" / "Fake-1.0.0-x86_64.AppImage").exists()


def test_launch_missing_file_errors(tmp_path):
    appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
    runner.invoke(app, ["add", str(appfile), "--yes", "--no-integrate"])
    Path(json.loads(runner.invoke(app, ["--json", "path", "fake-app"]).output)["path"]).unlink()
    result = runner.invoke(app, ["launch", "fake-app"])
    assert result.exit_code == 3


def test_modify_and_set_alias(tmp_path):
    appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
    runner.invoke(app, ["add", str(appfile), "--yes"])
    result = runner.invoke(app, ["set", "fake-app", "--name", "Renamed", "--auto-check", "off"])
    assert result.exit_code == 0, result.output
    data = json.loads(runner.invoke(app, ["--json", "info", "fake-app"]).output)
    assert data["name"] == "Renamed"
    assert data["autoupdate"] == "off"


def _add_fake_app(tmp_path):
    from tests.conftest import make_appimage

    appfile = make_appimage(tmp_path / "Fake-1.0.0-x86_64.AppImage")
    result = runner.invoke(app, ["add", str(appfile), "--yes", "--no-integrate"])
    assert result.exit_code == 0, result.output


def test_launch_detaches_output_to_log(monkeypatch, tmp_path, xdg):
    import subprocess as subprocess_mod

    _add_fake_app(tmp_path)
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs

    monkeypatch.setattr("quiver.cli.subprocess.Popen", fake_popen)
    result = runner.invoke(app, ["launch", "fake-app"])
    assert result.exit_code == 0, result.output

    kwargs = captured["kwargs"]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] == subprocess_mod.DEVNULL
    assert kwargs["stderr"] == subprocess_mod.STDOUT
    assert kwargs["stdout"] is not None  # a log file handle, not the terminal
    from quiver.util import paths

    log = paths.app_state_dir() / "logs" / "fake-app.log"
    assert log.exists()
    assert "quiver launch fake-app" in log.read_text()


def test_launch_console_keeps_terminal_streams(monkeypatch, tmp_path, xdg):
    _add_fake_app(tmp_path)
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["kwargs"] = kwargs

    monkeypatch.setattr("quiver.cli.subprocess.Popen", fake_popen)
    result = runner.invoke(app, ["launch", "fake-app", "--console"])
    assert result.exit_code == 0, result.output
    assert "stdout" not in captured["kwargs"]  # inherits the terminal
    assert "stdin" not in captured["kwargs"]
    assert captured["kwargs"]["start_new_session"] is True
