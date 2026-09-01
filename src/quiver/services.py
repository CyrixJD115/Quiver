"""Headless application services shared by the CLI and the RPC API.

Every function here returns plain data (dicts/lists) and never touches a Rich
console: the CLI renders results, the TUI's JSON-RPC server serializes them.
This module is the single source of truth for orchestration so presentation
layers cannot drift apart. Long-running operations accept an ``emit`` callable
that receives ``(level, message)`` progress lines.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from quiver import appimage, desktop, download, integrations, storage, updater
from quiver.config import Config
from quiver.errors import NotFoundError, UsageError
from quiver.providers import known_providers, normalize_github_repo
from quiver.registry import AppEntry, Registry

Emit = Callable[[str, str], None]


def _noop_emit(level: str, message: str) -> None:
    pass


# ---- apps ------------------------------------------------------------------------


def list_apps(registry: Registry, *, source_only: bool = False) -> list[dict]:
    entries = registry.all()
    if source_only:
        entries = [e for e in entries if e.source_configured]
    return [_app_summary(e) for e in entries]


def _app_summary(entry: AppEntry) -> dict:
    data = entry.to_dict()
    last = entry.last_check_result or {}
    data["update_status"] = last.get("status")
    data["latest_version"] = last.get("latest_version")
    return data


def get_app(cfg: Config, registry: Registry, alias: str, *, history: bool = True) -> dict:
    entry = registry.require(alias)
    data = _app_summary(entry)
    if history:
        data["history"] = [vars(h) for h in registry.history(alias)]
        data["backups"] = [
            {
                "file": str(p),
                "size": p.stat().st_size,
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            }
            for p in storage.list_backups(cfg.backup_dir, alias)
        ]
    return data


def add_app(
    cfg: Config,
    registry: Registry,
    path: Path,
    *,
    alias: str | None = None,
    name: str | None = None,
    version: str | None = None,
    source: str | None = None,
    categories: str | None = None,
    exec_args: str | None = None,
    in_place: bool = False,
    no_integrate: bool = False,
    emit: Emit = _noop_emit,
) -> dict:
    """Register an AppImage (copy into storage unless in_place)."""
    cfg.ensure_dirs()
    path = Path(path)
    if appimage.detect(path) is None:
        raise UsageError(f"{path} does not look like an AppImage (missing AppImage magic bytes)")

    if in_place:
        managed = path
        if not managed.stat().st_mode & 0o111:
            managed.chmod(0o755)
        original = None
    else:
        mode = "move" if cfg.data.get("add_mode") == "move" else "copy"
        managed = (
            storage.move_into_storage(path, cfg.storage_dir)
            if mode == "move"
            else storage.copy_into_storage(path, cfg.storage_dir)
        )
        original = str(path)

    meta = appimage.extract_metadata(managed)
    chosen_alias = alias or appimage.derive_alias(meta.name or name, managed.name)
    if registry.get(chosen_alias) is not None:
        raise UsageError(f"alias {chosen_alias!r} already taken", hint="Pick another alias.")

    entry = AppEntry(
        alias=chosen_alias,
        name=name or meta.name or chosen_alias.replace("-", " ").title(),
        path=str(managed),
        original_path=original,
        app_id=meta.app_id,
        version=version or meta.version,
        arch=meta.arch,
        description=meta.description,
        homepage=meta.homepage,
        categories=[c for c in (categories or "").split(";") if c]
        or meta.categories
        or ["Utility"],
        exec_args=exec_args.split() if exec_args else [],
        source_opts=appimage.hints_from_meta(meta),
        sha256=appimage.sha256_of(managed),
        size=managed.stat().st_size,
    )
    if source:
        apply_source_spec(entry, source)
    registry.add(entry)
    registry.add_history(
        chosen_alias,
        action="added",
        version=entry.version,
        path=str(managed),
        sha256=entry.sha256,
        size=entry.size,
    )
    emit("info", f"added {chosen_alias} ({entry.name} {entry.version or '?'}) at {managed}")

    if not no_integrate:
        result = desktop.integrate(entry, cfg, icon_source=meta.icon_path)
        registry.update(
            chosen_alias,
            integrated=True,
            icon_path=result.icon_path,
            desktop_file=result.entry_path.name,
        )
        emit("info", "desktop entry + icon installed")
    for warning in meta.warnings:
        emit("warn", warning)

    added = registry.get(chosen_alias)
    data = _app_summary(added) if added else {"alias": chosen_alias}
    data["warnings"] = meta.warnings
    return data


def remove_app(
    cfg: Config,
    registry: Registry,
    alias: str,
    *,
    purge: bool = False,
    emit: Emit = _noop_emit,
) -> dict:
    """Unregister an app and its desktop integration (confirmation is the
    caller's job; ``purge`` additionally deletes a file inside storage)."""
    entry = registry.require(alias)
    desktop.deintegrate(entry, cfg)
    purged = False
    if purge:
        target = Path(entry.path)
        if target.exists() and str(cfg.storage_dir) in str(target.resolve()):
            storage.safe_unlink(target)
            purged = True
            emit("warn", f"deleted {target}")
        else:
            emit("warn", f"--purge: not deleting (outside storage dir): {target}")
    registry.remove(alias)
    return {"removed": alias, "purged": purged}


def modify_app(
    cfg: Config,
    registry: Registry,
    alias: str,
    *,
    name: str | None = None,
    exec_args: str | None = None,
    categories: str | None = None,
    auto_check: str | None = None,
    notes: str | None = None,
    integrate: bool | None = None,
) -> dict:
    entry = registry.require(alias)
    changes: dict[str, Any] = {}
    if name is not None:
        changes["name"] = name
    if exec_args is not None:
        changes["exec_args"] = exec_args.split()
    if categories is not None:
        changes["categories"] = [c for c in categories.split(";") if c]
    if auto_check is not None:
        if auto_check not in ("manual", "off"):
            raise UsageError("auto_check must be manual or off")
        changes["autoupdate"] = auto_check
    if notes is not None:
        changes["notes"] = notes
    if integrate is True:
        result = desktop.integrate(entry, cfg)
        changes["integrated"] = True
        changes["icon_path"] = result.icon_path
        changes["desktop_file"] = result.entry_path.name
    elif integrate is False:
        changes["integrated"] = False
    if not changes:
        return entry.to_dict()
    updated = registry.update(alias, **changes)
    if integrate is False:
        desktop.deintegrate(entry, cfg)
    return updated.to_dict()


def launch_app(
    registry: Registry,
    alias: str,
    extra_args: list[str] | None = None,
    *,
    console_output: bool = False,
) -> dict:
    """Launch detached with output isolated to a per-app log."""
    entry = registry.require(alias)
    target = Path(entry.path)
    if not target.exists():
        raise NotFoundError(f"{target} is missing", hint="Try `quiver fix` or re-add the app.")
    if not target.stat().st_mode & 0o111:
        target.chmod(0o755)
    argv = [str(target), *entry.exec_args, *(extra_args or [])]
    try:
        if console_output:
            subprocess.Popen(argv, start_new_session=True)
            return {"alias": alias, "launched": True, "log": None}
        from quiver import paths

        log_dir = paths.app_state_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{alias}.log"
        with log_file.open("ab") as log:
            log.write(
                f"\n==== quiver launch {alias} @ {datetime.now():%Y-%m-%d %H:%M:%S} ====\n".encode()
            )
            log.flush()
            subprocess.Popen(
                argv,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        return {"alias": alias, "launched": True, "log": str(log_file)}
    except OSError as exc:
        raise UsageError(
            f"failed to launch {alias}: {exc}",
            hint="The file may not be a runnable AppImage on this machine.",
        ) from exc


# ---- updates ---------------------------------------------------------------------


def check_app(cfg: Config, registry: Registry, alias: str) -> dict:
    entry = registry.require(alias)
    with download.http_client(cfg) as client:
        result = updater.check(entry, cfg, client)
    updater.record_check(registry, entry, result)
    return result.to_dict()


def check_all_apps(cfg: Config, registry: Registry, *, emit: Emit = _noop_emit) -> list[dict]:
    results = []
    with download.http_client(cfg) as client:
        for entry in registry.all():
            if entry.autoupdate == "off":
                continue
            try:
                result = updater.check(entry, cfg, client)
            except Exception as exc:
                result = updater.CheckResult(
                    alias=entry.alias,
                    name=entry.name,
                    status=updater.STATUS_ERROR,
                    message=str(exc),
                )
            updater.record_check(registry, entry, result)
            results.append(result.to_dict())
            emit(
                "info",
                f"{entry.alias}: {result.status.replace('_', ' ')}"
                + (
                    f" {result.current_version or '?'} -> {result.latest_version}"
                    if result.status == updater.STATUS_UPDATE_AVAILABLE
                    else ""
                ),
            )
    return results


def apply_update(
    cfg: Config,
    registry: Registry,
    alias: str,
    *,
    force: bool = False,
    dry_run: bool = False,
    console=None,
    emit: Emit = _noop_emit,
) -> dict:
    entry = registry.require(alias)
    with download.http_client(cfg) as client:
        outcome = updater.perform_update(
            entry,
            cfg,
            registry,
            client,
            console,
            assume_yes=True,
            dry_run=dry_run,
            force=force,
        )
    for step in outcome.steps:
        emit("info", f"{alias}: {step}")
    return outcome.to_dict()


def apply_update_all(
    cfg: Config,
    registry: Registry,
    *,
    force: bool = False,
    dry_run: bool = False,
    console=None,
    emit: Emit = _noop_emit,
) -> list[dict]:
    outcomes = []
    with download.http_client(cfg) as client:
        for app in registry.all():
            if app.autoupdate == "off":
                continue
            try:
                outcome = updater.perform_update(
                    app,
                    cfg,
                    registry,
                    client,
                    console,
                    assume_yes=True,
                    dry_run=dry_run,
                    force=force,
                )
            except Exception as exc:
                outcome = updater.UpdateOutcome(
                    alias=app.alias, status="failed", error=f"unexpected error: {exc}"
                )
            outcomes.append(outcome.to_dict())
            emit("info", f"{app.alias}: {outcome.status}")
    return outcomes


def rollback_app(
    cfg: Config,
    registry: Registry,
    alias: str,
    *,
    to_version: str | None = None,
    console=None,
    emit: Emit = _noop_emit,
) -> dict:
    entry = registry.require(alias)
    outcome = updater.rollback(
        entry, cfg, registry, console, to_version=to_version, assume_yes=True
    )
    for step in outcome.steps:
        emit("info", f"{alias}: {step}")
    return outcome.to_dict()


# ---- sources ---------------------------------------------------------------------


def apply_source_spec(entry: AppEntry, source: str) -> None:
    """Parse 'github:owner/repo' / 'gitlab:g/p' / 'url:https://' / 'command:...'."""
    kind, _, value = source.partition(":")
    kind = kind.strip().lower()
    value = value.strip()
    if kind in ("github", "gh"):
        entry.source_type = "github"
        entry.source_repo = normalize_github_repo(value)
    elif kind == "gitlab":
        entry.source_type = "gitlab"
        entry.source_repo = value
    elif kind == "url":
        entry.source_type = "url"
        entry.source_repo = value
    elif kind == "command":
        entry.source_type = "command"
        entry.source_repo = "custom command"
        entry.source_opts = {**entry.source_opts, "command": value}
    elif kind in known_providers():
        entry.source_type = kind
        entry.source_repo = value
    else:
        raise UsageError(
            f"unknown source type {kind!r}",
            hint=f"Use one of: {', '.join(known_providers())} (e.g. github:owner/repo)",
        )


def set_source(
    registry: Registry,
    alias: str,
    kind: str,
    value: str,
    *,
    asset_patterns: list[str] | None = None,
    allow_prerelease: bool = False,
) -> dict:
    entry = registry.require(alias)
    probe = AppEntry(alias=entry.alias, name=entry.name, path=entry.path)
    apply_source_spec(probe, f"{kind}:{value}")
    opts = {**entry.source_opts}
    if asset_patterns:
        opts["asset_patterns"] = list(asset_patterns)
    if allow_prerelease:
        opts["allow_prerelease"] = True
    updated = registry.update(
        alias, source_type=probe.source_type, source_repo=probe.source_repo, source_opts=opts
    )
    return {
        "alias": alias,
        "source_type": updated.source_type,
        "source_repo": updated.source_repo,
        "source_opts": updated.source_opts,
    }


def clear_source(registry: Registry, alias: str) -> dict:
    registry.require(alias)
    registry.update(alias, source_type=None, source_repo=None)
    return {"alias": alias, "cleared": True}


def detect_source(
    cfg: Config,
    registry: Registry,
    alias: str | None = None,
    *,
    all_apps: bool = False,
    search: bool = True,
    set_first: bool = False,
    emit: Emit = _noop_emit,
) -> dict:
    """Discover upstream update sources. Returns candidates per app."""
    from quiver.discovery import discover_candidates

    if not alias and not all_apps:
        raise UsageError("give an app alias or use all=true")
    if alias and all_apps:
        raise UsageError("use either an alias or all, not both")
    targets = (
        [registry.require(alias)]
        if alias
        else [e for e in registry.all() if not e.source_configured]
    )
    apps: list[dict] = []
    with download.http_client(cfg) as client:
        for entry in targets:
            candidates = discover_candidates(entry, cfg, client, allow_search=search)
            item: dict[str, Any] = {
                "alias": entry.alias,
                "candidates": [
                    {"repo": c.repo, "version": c.version, "via": c.via} for c in candidates
                ],
            }
            if not candidates:
                item["resolved"] = False
                emit("warn", f"{entry.alias}: no update source found")
            else:
                best = candidates[0]
                if set_first or len(candidates) == 1:
                    registry.update(entry.alias, source_type="github", source_repo=best.repo)
                    item["resolved"] = True
                    item["set"] = f"github:{best.repo}"
                    emit("info", f"{entry.alias}: github:{best.repo} (via {best.via})")
                else:
                    item["resolved"] = None  # needs a choice
                    emit("info", f"{entry.alias}: {len(candidates)} candidates")
            apps.append(item)
    return {"apps": apps, "resolved": sum(1 for a in apps if a.get("resolved")), "total": len(apps)}


# ---- timer -----------------------------------------------------------------------


def timer_install(cfg: Config, *, on_calendar: str = "daily", enable: bool = True) -> dict:
    path = integrations.install_timer(cfg, on_calendar=on_calendar, enable=enable)
    return {"installed": str(path), "on_calendar": on_calendar, "enabled": enable}


def timer_uninstall() -> dict:
    return {"removed": integrations.uninstall_timer()}


def timer_status() -> dict:
    return {"status": integrations.timer_status()}
