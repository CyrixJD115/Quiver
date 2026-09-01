"""Tests for the JSON-RPC API server used by the TUI."""

from __future__ import annotations

import io
import json

from quiver.api import Api
from tests.conftest import make_appimage


def _lines(out: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _last_result(out: io.StringIO):
    messages = _lines(out)
    results = [m for m in messages if "result" in m or "error" in m]
    return results[-1]


def test_core_info(xdg):
    out = io.StringIO()
    api = Api(out=out)
    resp = api.handle({"jsonrpc": "2.0", "id": 1, "method": "core.info", "params": {}})
    assert resp["id"] == 1
    assert resp["result"]["platform"] == "linux"
    assert "storage_dir" in resp["result"]
    assert "version" in resp["result"]


def test_unknown_method(xdg):
    api = Api(out=io.StringIO())
    resp = api.handle({"jsonrpc": "2.0", "id": 2, "method": "nope.nope", "params": {}})
    assert resp["error"]["code"] == -32601


def test_app_lifecycle(cfg, registry, xdg, monkeypatch):
    out = io.StringIO()
    api = Api(out=out)
    appfile = make_appimage(xdg.home / "dl" / "Fake-1.0.0-x86_64.AppImage")

    launched: list[list[str]] = []

    class _FakeProc:
        def __init__(self, argv, **_):
            self.args = argv
            self.returncode = 0
            launched.append(list(argv))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def communicate(self, *a, **_):
            return (None, b"")

        def kill(self):
            pass

        def wait(self, *a, **_):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr("quiver.services.subprocess.Popen", _FakeProc)

    resp = api.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "apps.add", "params": {"path": str(appfile)}}
    )
    assert "error" not in resp, resp
    assert resp["result"]["alias"] == "fake"
    assert resp["result"]["version"] == "1.0.0"

    resp = api.handle({"jsonrpc": "2.0", "id": 2, "method": "apps.list", "params": {}})
    assert [a["alias"] for a in resp["result"]] == ["fake"]
    assert resp["result"][0]["update_status"] is None  # never checked yet

    resp = api.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "apps.get", "params": {"alias": "fake"}}
    )
    assert resp["result"]["history"][0]["action"] == "added"
    assert isinstance(resp["result"]["backups"], list)

    resp = api.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "apps.launch", "params": {"alias": "fake"}}
    )
    assert resp["result"]["launched"] is True
    assert launched and launched[0][0].endswith("Fake-1.0.0-x86_64.AppImage")

    resp = api.handle(
        {"jsonrpc": "2.0", "id": 5, "method": "apps.remove", "params": {"alias": "fake"}}
    )
    assert resp["result"]["removed"] == "fake"
    assert registry.count() == 0


def test_mutation_notifies_state(xdg):
    out = io.StringIO()
    api = Api(out=out)
    appfile = make_appimage(xdg.home / "Fake-1.0.0-x86_64.AppImage")
    api.handle({"jsonrpc": "2.0", "id": 1, "method": "apps.add", "params": {"path": str(appfile)}})
    notifications = [m for m in _lines(out) if m.get("method") == "state"]
    assert notifications and notifications[-1]["params"]["changed"] is True


def test_updates_check_no_source(cfg, xdg):
    api = Api(out=io.StringIO())
    appfile = make_appimage(xdg.home / "Fake-1.0.0-x86_64.AppImage")
    api.handle({"jsonrpc": "2.0", "id": 1, "method": "apps.add", "params": {"path": str(appfile)}})
    resp = api.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "updates.check", "params": {"alias": "fake"}}
    )
    assert resp["result"]["status"] == "no_source"


def test_app_error_becomes_rpc_error(xdg):
    api = Api(out=io.StringIO())
    resp = api.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "apps.get", "params": {"alias": "ghost"}}
    )
    assert resp["error"]["code"] == -32000
    assert "hint" in resp["error"]["data"]


def test_config_roundtrip(xdg):
    api = Api(out=io.StringIO())
    resp = api.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "config.set",
            "params": {"key": "notify", "value": "on"},
        }
    )
    assert resp["result"]["value"] is True
    resp = api.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "config.get", "params": {"key": "notify"}}
    )
    assert resp["result"]["value"] is True


def test_system_doctor_and_scan(cfg, xdg):
    api = Api(out=io.StringIO())
    resp = api.handle({"jsonrpc": "2.0", "id": 1, "method": "system.doctor", "params": {}})
    for key in ("diagnostics", "ok", "info", "warn", "error"):
        assert key in resp["result"]
    resp = api.handle({"jsonrpc": "2.0", "id": 2, "method": "system.scan", "params": {}})
    assert "appimages" in resp["result"]


def test_sources_set_show_clear(cfg, xdg):
    api = Api(out=io.StringIO())
    appfile = make_appimage(xdg.home / "Fake-1.0.0-x86_64.AppImage")
    api.handle({"jsonrpc": "2.0", "id": 1, "method": "apps.add", "params": {"path": str(appfile)}})
    resp = api.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "sources.set",
            "params": {"alias": "fake", "kind": "github", "value": "owner/repo"},
        }
    )
    assert resp["result"]["source_repo"] == "owner/repo"
    resp = api.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "sources.show", "params": {"alias": "fake"}}
    )
    assert resp["result"]["source_type"] == "github"
    resp = api.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "sources.clear", "params": {"alias": "fake"}}
    )
    assert resp["result"]["cleared"] is True


def test_serve_end_to_end(cfg, xdg):
    from quiver.api import serve

    appfile = make_appimage(xdg.home / "Fake-1.0.0-x86_64.AppImage")
    requests = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "core.info", "params": {}})
        + "\n"
        + json.dumps(
            {"jsonrpc": "2.0", "id": 2, "method": "apps.add", "params": {"path": str(appfile)}}
        )
        + "\n"
        + "not json at all\n"
    )
    out = io.StringIO()
    serve(stdin=requests, stdout=out)
    messages = _lines(out)
    results = {m["id"]: m for m in messages if "id" in m and m["id"] is not None}
    assert results[1]["result"]["platform"] == "linux"
    assert results[2]["result"]["alias"] == "fake"
    parse_errors = [m for m in messages if m.get("error", {}).get("code") == -32700]
    assert parse_errors  # garbage line answered, server kept going


def test_line_emitter_streams_log_events():
    from quiver.api import _capture_console

    seen: list[str] = []
    console = _capture_console(lambda lvl, msg: seen.append(msg))
    console.print("downloading [bold]50%[/bold]")
    console.print("done")
    assert any("downloading 50%" in s for s in seen)
    assert any("done" in s for s in seen)
