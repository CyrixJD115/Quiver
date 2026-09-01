"""JSON-RPC 2.0 server over newline-delimited JSON on stdio.

The TUI (an OpenTUI process) spawns `quiver api` and keeps it alive for the
whole session. Requests are answered in order; read-only methods may run
concurrently while mutations serialize behind a lock. Long operations stream
``log`` and ``progress`` notifications so the UI can render live activity.

Protocol (one JSON object per line, both directions):
  -> {"jsonrpc":"2.0","id":1,"method":"apps.list","params":{}}
  <- {"jsonrpc":"2.0","id":1,"result":[...]}
  <- {"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"...","data":{"hint":"..."}}}
  <- {"jsonrpc":"2.0","method":"log","params":{"level":"info","message":"..."}}
"""

from __future__ import annotations

import io
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TextIO

from quiver import __version__, maintenance
from quiver.config import Config, config_file_path, parse_config_value
from quiver.errors import AimError
from quiver.registry import Registry
from quiver.services import (
    add_app,
    apply_update,
    apply_update_all,
    check_all_apps,
    check_app,
    clear_source,
    detect_source,
    get_app,
    launch_app,
    list_apps,
    modify_app,
    remove_app,
    rollback_app,
    set_source,
    timer_install,
    timer_status,
    timer_uninstall,
)

_PARSE_ERROR = -32700
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL = -32603
_APP_ERROR = -32000

MUTATING = {
    "apps.add",
    "apps.remove",
    "apps.modify",
    "apps.launch",
    "updates.apply",
    "updates.applyAll",
    "updates.rollback",
    "sources.set",
    "sources.clear",
    "sources.detect",
    "system.clean",
    "system.repair",
    "system.refresh",
    "system.import",
    "config.set",
    "timer.install",
    "timer.uninstall",
}


class Api:
    """Dispatch context: config + registry per request, notifications out."""

    def __init__(self, out: TextIO = sys.stdout) -> None:
        self.out = out
        self._write_lock = threading.Lock()
        self._mutation_lock = threading.Lock()

    # ---- plumbing -----------------------------------------------------------------

    def send(self, obj: dict) -> None:
        line = json.dumps(obj, separators=(",", ":"), default=str)
        with self._write_lock:
            self.out.write(line + "\n")
            self.out.flush()

    def notify(self, method: str, params: dict) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def emit_for(self, alias: str | None = None):
        def emit(level: str, message: str) -> None:
            self.notify("log", {"level": level, "message": message, "alias": alias})

        return emit

    def handle(self, request: dict) -> dict | None:
        """Handle one request object; returns a response or None (notification)."""
        method = request.get("method")
        msg_id = request.get("id")
        params = request.get("params") or {}
        if not isinstance(method, str):
            return self._error(msg_id, _METHOD_NOT_FOUND, "missing method")
        handler = _METHODS.get(method)
        if handler is None:
            return self._error(msg_id, _METHOD_NOT_FOUND, f"unknown method: {method}")
        try:
            result = handler(self, params)
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except AimError as exc:
            return self._error(msg_id, _APP_ERROR, str(exc), {"hint": exc.hint})
        except Exception as exc:
            return self._error(msg_id, _INTERNAL, f"{type(exc).__name__}: {exc}")
        finally:
            if method in MUTATING:
                self.notify("state", {"changed": True, "method": method})

    def _error(self, msg_id: Any, code: int, message: str, data: dict | None = None) -> dict:
        err: dict[str, Any] = {"code": code, "message": message}
        if data:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": msg_id, "error": err}

    # ---- method implementations ---------------------------------------------------

    def _cfg(self, params: dict) -> Config:
        path = params.get("config_path")
        return Config.load(Path(path) if path else None)

    def core_info(self, params: dict) -> dict:
        from quiver import paths

        cfg = self._cfg(params)
        return {
            "version": __version__,
            "config_path": str(cfg.path),
            "config_file": str(config_file_path()),
            "state_dir": str(paths.app_state_dir()),
            "storage_dir": str(cfg.storage_dir),
            "backup_dir": str(cfg.backup_dir),
            "icon_dir": str(cfg.icon_dir),
            "platform": sys.platform,
        }

    def apps_list(self, params: dict) -> list[dict]:
        return list_apps(Registry(), source_only=bool(params.get("source_only")))

    def apps_get(self, params: dict) -> dict:
        return get_app(self._cfg(params), Registry(), params["alias"])

    def apps_add(self, params: dict) -> dict:
        return add_app(
            self._cfg(params),
            Registry(),
            Path(params["path"]),
            alias=params.get("alias"),
            name=params.get("name"),
            version=params.get("version"),
            source=params.get("source"),
            categories=params.get("categories"),
            exec_args=params.get("exec_args"),
            in_place=bool(params.get("in_place")),
            no_integrate=bool(params.get("no_integrate")),
            emit=self.emit_for(params.get("alias")),
        )

    def apps_remove(self, params: dict) -> dict:
        return remove_app(
            self._cfg(params),
            Registry(),
            params["alias"],
            purge=bool(params.get("purge")),
            emit=self.emit_for(params["alias"]),
        )

    def apps_modify(self, params: dict) -> dict:
        known = ("name", "exec_args", "categories", "auto_check", "notes")
        kwargs = {k: params[k] for k in known if k in params}
        if "integrate" in params:
            kwargs["integrate"] = bool(params["integrate"])
        return modify_app(self._cfg(params), Registry(), params["alias"], **kwargs)

    def apps_launch(self, params: dict) -> dict:
        return launch_app(Registry(), params["alias"], params.get("args", []))

    def apps_path(self, params: dict) -> dict:
        entry = Registry().require(params["alias"])
        return {"alias": entry.alias, "path": entry.path}

    def updates_check(self, params: dict) -> dict | list[dict]:
        if params.get("alias"):
            return check_app(self._cfg(params), Registry(), params["alias"])
        return check_all_apps(self._cfg(params), Registry(), emit=self.emit_for())

    def updates_apply(self, params: dict) -> dict:
        return apply_update(
            self._cfg(params),
            Registry(),
            params["alias"],
            force=bool(params.get("force")),
            dry_run=bool(params.get("dry_run")),
            console=_capture_console(self.emit_for(params["alias"])),
            emit=self.emit_for(params["alias"]),
        )

    def updates_apply_all(self, params: dict) -> list[dict]:
        return apply_update_all(
            self._cfg(params),
            Registry(),
            force=bool(params.get("force")),
            dry_run=bool(params.get("dry_run")),
            console=_capture_console(self.emit_for()),
            emit=self.emit_for(),
        )

    def updates_rollback(self, params: dict) -> dict:
        return rollback_app(
            self._cfg(params),
            Registry(),
            params["alias"],
            to_version=params.get("to_version"),
            console=_capture_console(self.emit_for(params["alias"])),
            emit=self.emit_for(params["alias"]),
        )

    def sources_show(self, params: dict) -> dict:
        entry = Registry().require(params["alias"])
        return {
            "alias": entry.alias,
            "source_type": entry.source_type,
            "source_repo": entry.source_repo,
            "source_opts": entry.source_opts,
        }

    def sources_set(self, params: dict) -> dict:
        return set_source(
            Registry(),
            params["alias"],
            params["kind"],
            params["value"],
            asset_patterns=params.get("asset_patterns"),
            allow_prerelease=bool(params.get("allow_prerelease")),
        )

    def sources_clear(self, params: dict) -> dict:
        return clear_source(Registry(), params["alias"])

    def sources_detect(self, params: dict) -> dict:
        return detect_source(
            self._cfg(params),
            Registry(),
            params.get("alias"),
            all_apps=bool(params.get("all")),
            search=bool(params.get("search", True)),
            set_first=bool(params.get("set")),
            emit=self.emit_for(params.get("alias")),
        )

    def system_scan(self, params: dict) -> dict:
        return maintenance.scan(self._cfg(params), Registry()).to_dict()

    def system_doctor(self, params: dict) -> dict:
        diags = maintenance.doctor(self._cfg(params), Registry())
        return {
            "diagnostics": [
                {"level": d.level, "area": d.area, "message": d.message, "hint": d.hint}
                for d in diags
            ],
            "ok": sum(1 for d in diags if d.level == "ok"),
            "info": sum(1 for d in diags if d.level == "info"),
            "warn": sum(1 for d in diags if d.level == "warn"),
            "error": sum(1 for d in diags if d.level == "error"),
        }

    def system_clean(self, params: dict) -> dict:
        report = maintenance.clean(
            self._cfg(params),
            Registry(),
            None,  # headless: no confirm prompts
            dry_run=bool(params.get("dry_run")),
            assume_yes=True,
        )
        return {
            "removed": report.removed,
            "kept": report.kept,
            "skipped": report.skipped,
        }

    def system_repair(self, params: dict) -> dict:
        report = maintenance.repair(
            self._cfg(params), Registry(), None, alias=params.get("alias"), assume_yes=True
        )
        return {"steps": report.steps}

    def system_refresh(self, params: dict) -> dict:
        report = maintenance.refresh(self._cfg(params), Registry(), alias=params.get("alias"))
        return report.to_dict()

    def system_import(self, params: dict) -> dict:
        report = maintenance.import_existing(
            self._cfg(params),
            Registry(),
            None,
            adopt_all=bool(params.get("adopt_all", True)),
            assume_yes=True,
            dry_run=bool(params.get("dry_run")),
            integrate=not params.get("no_integrate", False),
            in_place=bool(params.get("in_place")) or None,
            extra_dirs=[Path(d) for d in params.get("dirs", [])] or None,
        )
        return report.to_dict()

    def config_list(self, params: dict) -> dict:
        data = dict(self._cfg(params).data)
        token = (
            data.get("github", {}).get("token") if isinstance(data.get("github"), dict) else None
        )
        if token:
            data["github"] = {**data["github"], "token": "***"}
        return data

    def config_get(self, params: dict) -> dict:
        return {"key": params["key"], "value": self._cfg(params).get(params["key"])}

    def config_set(self, params: dict) -> dict:
        cfg = self._cfg(params)
        value = parse_config_value(params["key"], str(params["value"]))
        cfg.set(params["key"], value)
        return {"key": params["key"], "value": value}

    def timer_status(self, params: dict) -> dict:
        return timer_status()

    def timer_install(self, params: dict) -> dict:
        return timer_install(
            self._cfg(params),
            on_calendar=str(params.get("on_calendar", "daily")),
            enable=bool(params.get("enable", True)),
        )

    def timer_uninstall(self, params: dict) -> dict:
        return timer_uninstall()

    def history(self, params: dict) -> list[dict]:
        registry = Registry()
        registry.require(params["alias"])
        return [vars(h) for h in registry.history(params["alias"])]

    def history_recent(self, params: dict) -> list[dict]:
        rows = (
            Registry()
            .conn.execute(
                "SELECT * FROM history ORDER BY id DESC LIMIT ?", (int(params.get("limit", 10)),)
            )
            .fetchall()
        )
        return [dict(r) for r in rows]


_METHODS = {
    "core.info": Api.core_info,
    "core.shutdown": lambda self, params: None,
    "apps.list": Api.apps_list,
    "apps.get": Api.apps_get,
    "apps.add": Api.apps_add,
    "apps.remove": Api.apps_remove,
    "apps.modify": Api.apps_modify,
    "apps.launch": Api.apps_launch,
    "apps.path": Api.apps_path,
    "updates.check": Api.updates_check,
    "updates.apply": Api.updates_apply,
    "updates.applyAll": Api.updates_apply_all,
    "updates.rollback": Api.updates_rollback,
    "sources.show": Api.sources_show,
    "sources.set": Api.sources_set,
    "sources.clear": Api.sources_clear,
    "sources.detect": Api.sources_detect,
    "system.scan": Api.system_scan,
    "system.doctor": Api.system_doctor,
    "system.clean": Api.system_clean,
    "system.repair": Api.system_repair,
    "system.refresh": Api.system_refresh,
    "system.import": Api.system_import,
    "config.list": Api.config_list,
    "config.get": Api.config_get,
    "config.set": Api.config_set,
    "timer.status": Api.timer_status,
    "timer.install": Api.timer_install,
    "timer.uninstall": Api.timer_uninstall,
    "history.get": Api.history,
    "history.recent": Api.history_recent,
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*(?:\x07|\x1b\\)")


class _LineEmitter(io.StringIO):
    """File-like object that forwards written text (ANSI-stripped) as log events."""

    def __init__(self, emit) -> None:
        super().__init__()
        self.emit = emit
        self._pending = ""

    def write(self, s: str) -> int:
        self._pending += s
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            clean = _ANSI_RE.sub("", line).strip()
            if clean:
                self.emit("info", clean)
        return super().write(s)


def _capture_console(emit):
    """A Rich Console whose output is streamed to the UI as log notifications."""
    from rich.console import Console

    return Console(file=_LineEmitter(emit), width=200, force_terminal=False, no_color=True)


def serve(stdin=None, stdout=None) -> None:
    """Read ndjson requests until EOF; answer each on a worker thread."""
    api = Api(out=stdout or sys.stdout)
    stdin = stdin or sys.stdin
    pool = ThreadPoolExecutor(max_workers=4)

    def run(request: dict) -> None:
        method = request.get("method", "")
        lock = api._mutation_lock if method in MUTATING else None
        if lock is not None:
            with lock:
                response = api.handle(request)
        else:
            response = api.handle(request)
        if response is not None:
            api.send(response)
            if method == "core.shutdown":
                pool.shutdown(wait=False, cancel_futures=True)

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            api.send(
                {"jsonrpc": "2.0", "id": None, "error": {"code": _PARSE_ERROR, "message": str(exc)}}
            )
            continue
        pool.submit(run, request)
    pool.shutdown(wait=True)


if __name__ == "__main__":
    serve()
