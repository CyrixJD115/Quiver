"""quiver command-line interface (Typer + Rich).

Daily verbs live at the top level; rarer knobs live in the `source`, `config`
and `timer` groups. Both this CLI and the interactive TUI (tui/, OpenTUI) are
thin presentation layers over quiver.services - business logic lives once.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from quiver import (
    __version__,
    download,
    integrations,
    maintenance,
    services,
    storage,
    tui,
    updater,
)
from quiver.config import Config, config_file_path, parse_config_value
from quiver.errors import AimError, CancelledError, NotFoundError, UsageError
from quiver.output import GLYPH_ERR, GLYPH_INFO, GLYPH_OK, GLYPH_WARN, UI, confirm
from quiver.providers import known_providers
from quiver.registry import AppEntry, Registry

app = typer.Typer(
    name="quiver",
    help="AppImage manager: install, update, launch and keep AppImages tidy.\n\n"
    "Run `quiver` with no arguments for the interactive TUI (Linux), or a\n"
    "command below for scripting and headless use.",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_show_locals=False,
)
config_app = typer.Typer(help="Show or change configuration.", no_args_is_help=True)
source_app = typer.Typer(help="Configure upstream update sources.", no_args_is_help=True)
timer_app = typer.Typer(help="Manage the systemd update-check timer.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(source_app, name="source")
app.add_typer(timer_app, name="timer")


# ---- shared plumbing -----------------------------------------------------------


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"quiver {__version__}")
        raise typer.Exit()


@app.callback()
def root_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        None, "--version", callback=_version_cb, is_eager=True, help="Print version and exit."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="More detail."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Less chatty output."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable JSON output."),
    config_path: Path | None = typer.Option(None, "--config", help="Use an alternate config file."),
) -> None:
    ctx.obj = UI(
        json_mode=as_json,
        quiet=quiet,
        verbose=verbose,
        cfg_path=str(config_path) if config_path else None,
        console=Console(),
    )
    del version
    if ctx.invoked_subcommand is None:
        if tui.should_autolaunch():
            raise SystemExit(tui.launch_tui())
        console = Console()
        console.print(
            f"[bold]quiver {__version__}[/bold] - AppImage manager."
            " [dim]Run [bold]quiver --help[/bold] for commands,"
            " [bold]quiver run[/bold] for the interactive TUI.[/dim]"
        )


def _ui(ctx: typer.Context) -> UI:
    return ctx.obj


def _cfg(ctx: typer.Context) -> Config:
    cfg_path = _ui(ctx).cfg_path
    return Config.load(Path(cfg_path) if cfg_path else None)


def _reg() -> Registry:
    return Registry()


def _client(cfg: Config):
    return download.http_client(cfg)


def handle_errors(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AimError as exc:
            console = Console(quiet=False)
            console.print(f"{GLYPH_ERR} {exc}")
            if exc.hint:
                console.print(f"      hint: {exc.hint}")
            raise typer.Exit(exc.exit_code) from exc

    return wrapper


def _echo(ui: UI, glyph: str, message: str) -> None:
    if not ui.quiet or glyph == GLYPH_ERR:
        ui.console.print(f"{glyph} {message}")


# ---- core commands -----------------------------------------------------------


def _list_impl(ctx: typer.Context, source_only: bool) -> None:
    ui, registry = _ui(ctx), _reg()
    entries = registry.all()
    if source_only:
        entries = [e for e in entries if e.source_configured]
    if ui.json_mode:
        ui.emit_json([e.to_dict() for e in entries])
        return
    if not entries:
        _echo(
            ui,
            GLYPH_INFO,
            "nothing managed yet - try `quiver add <path.AppImage>` or `quiver import`",
        )
        return
    table = Table(title=f"{len(entries)} managed AppImage(s)", title_style="bold")
    for col in ("alias", "name", "version", "arch", "source", "entry", "updated"):
        table.add_column(col, style="cyan" if col == "alias" else None)
    for entry in entries:
        source = f"{entry.source_type}:{entry.source_repo}" if entry.source_configured else "-"
        table.add_row(
            entry.alias,
            entry.name,
            entry.version or "?",
            entry.arch or "?",
            source,
            "yes" if entry.integrated else "no",
            (entry.updated_at or "")[:10],
        )
    ui.console.print(table)


def _ls(
    ctx: typer.Context,
    source_only: bool = typer.Option(
        False, "--source-only", help="Only apps with an update source."
    ),
) -> None:
    """List managed AppImages."""
    _list_impl(ctx, source_only)


def _list(
    ctx: typer.Context,
    source_only: bool = typer.Option(
        False, "--source-only", help="Only apps with an update source."
    ),
) -> None:
    """List managed AppImages."""
    _list_impl(ctx, source_only)


app.command("ls")(handle_errors(_ls))
app.command("list", hidden=True)(handle_errors(_list))


@app.command()
@handle_errors
def info(ctx: typer.Context, alias: str = typer.Argument(..., help="App alias.")) -> None:
    """Show everything known about a managed app."""
    ui = _ui(ctx)
    entry = _reg().require(alias)
    if ui.json_mode:
        data = entry.to_dict()
        data["history"] = [vars(h) for h in _reg().history(alias)]
        ui.emit_json(data)
        return
    e = entry
    rows = [
        ("alias", e.alias),
        ("name", e.name),
        ("path", e.path),
        ("original", e.original_path or "-"),
        ("version", e.version or "?"),
        ("arch", e.arch or "?"),
        ("app id", e.app_id or "-"),
        ("description", e.description or "-"),
        ("homepage", e.homepage or "-"),
        ("size", storage.human_size(e.size)),
        ("sha256", (e.sha256 or "")[:16] + "..."),
        ("source", f"{e.source_type}:{e.source_repo}" if e.source_configured else "not configured"),
        ("desktop entry", e.desktop_file or "-"),
        ("icon", e.icon_path or "-"),
        ("integrated", "yes" if e.integrated else "no"),
        ("auto-check", e.autoupdate),
        ("added", e.created_at[:10] if e.created_at else "?"),
    ]
    from quiver import paths

    launch_log = paths.app_state_dir() / "logs" / f"{alias}.log"
    if launch_log.exists():
        rows.append(("launch log", str(launch_log)))
    if e.last_check_at:
        rows.append(
            ("last check", f"{e.last_check_at} -> {(e.last_check_result or {}).get('status', '?')}")
        )
    for key, value in rows:
        ui.console.print(f"[bold]{key:<14}[/bold] {value}")
    history = _reg().history(alias)
    if history:
        ui.console.print("\n[bold]history[/bold]")
        for h in history[:8]:
            ui.console.print(f"  {h.created_at}  {h.action:<10} {h.version or '-'}")


@app.command()
@handle_errors
def add(
    ctx: typer.Context,
    path: Path = typer.Argument(..., exists=True, readable=True, help="Path to an AppImage file."),
    alias: str | None = typer.Option(None, "--alias", "-a", help="CLI alias (derived if omitted)."),
    name: str | None = typer.Option(None, "--name", help="Display name override."),
    version: str | None = typer.Option(None, "--version", help="Version override."),
    source: str | None = typer.Option(
        None,
        "--source",
        help="Source: github:owner/repo, gitlab:g/p, url:https://..., or command:'...'.",
    ),
    categories: str | None = typer.Option(None, help="Semicolon-separated menu categories."),
    exec_args: str | None = typer.Option(None, help="Extra launch arguments."),
    in_place: bool = typer.Option(
        False, "--in-place", help="Register the file where it is (no copy)."
    ),
    no_integrate: bool = typer.Option(
        False, "--no-integrate", help="Skip desktop entry/icon creation."
    ),
    yes: bool = typer.Option(False, "--yes", help="Non-interactive; accept defaults."),
) -> None:
    """Add an AppImage to the manager (copies it into managed storage)."""
    ui, cfg, registry = _ui(ctx), _cfg(ctx), _reg()

    def emit(level: str, message: str) -> None:
        if ui.json_mode:
            return
        glyph = {"info": GLYPH_INFO, "warn": GLYPH_WARN}.get(level, GLYPH_INFO)
        _echo(ui, glyph, message)

    data = services.add_app(
        cfg,
        registry,
        path,
        alias=alias,
        name=name,
        version=version,
        source=source,
        categories=categories,
        exec_args=exec_args,
        in_place=in_place,
        no_integrate=no_integrate,
        emit=emit,
    )
    if ui.json_mode:
        ui.emit_json(data)
        return
    _echo(
        ui,
        GLYPH_OK,
        f"added [bold]{data['alias']}[/bold] ({data['name']} {data['version'] or '?'})",
    )
    _echo(ui, GLYPH_INFO, f"stored at {data['path']}")
    for warning in data.get("warnings", []):
        _echo(ui, GLYPH_WARN, warning)
    if not data.get("source_type"):
        _echo(
            ui,
            GLYPH_INFO,
            f"no update source yet: `quiver source detect {data['alias']}`"
            f" or `quiver source set {data['alias']} github owner/repo`",
        )


def _remove_impl(
    ctx: typer.Context,
    alias: str,
    purge: bool,
    yes: bool,
) -> None:
    ui, cfg, registry = _ui(ctx), _cfg(ctx), _reg()
    entry = registry.require(alias)
    if not confirm(
        ui.console, f"Unregister '{alias}' and remove its desktop entry/icon?", assume_yes=yes
    ):
        raise CancelledError("declined")
    if purge and entry.path:
        target = Path(entry.path)
        inside_storage = target.exists() and str(cfg.storage_dir) in str(target.resolve())
        if inside_storage and not confirm(
            ui.console,
            f"Also DELETE the managed file {target} ({storage.human_size(entry.size)})?",
            assume_yes=yes,
        ):
            _echo(ui, GLYPH_WARN, "file kept")
            purge = False
    data = services.remove_app(
        cfg, registry, alias, purge=purge, emit=lambda lvl, msg: _echo(ui, GLYPH_WARN, msg)
    )
    if ui.json_mode:
        ui.emit_json(data)
        return
    _echo(ui, GLYPH_OK, f"removed {alias}")


def _remove(
    ctx: typer.Context,
    alias: str = typer.Argument(..., help="App alias."),
    purge: bool = typer.Option(False, "--purge", help="Also delete the managed AppImage file."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmations."),
) -> None:
    """Remove an app from the manager (asks before touching any file)."""
    _remove_impl(ctx, alias, purge, yes)


def _rm(
    ctx: typer.Context,
    alias: str = typer.Argument(..., help="App alias."),
    purge: bool = typer.Option(False, "--purge", help="Also delete the managed AppImage file."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmations."),
) -> None:
    """Alias for rm."""
    _remove_impl(ctx, alias, purge, yes)


app.command("rm")(handle_errors(_rm))
app.command("remove", hidden=True)(handle_errors(_remove))


def _launch_impl(
    ctx: typer.Context,
    alias: str,
    extra_args: list[str] | None,
    wait: bool,
    console_output: bool,
) -> None:
    ui = _ui(ctx)
    registry = _reg()
    entry = registry.require(alias)
    if wait:
        # Foreground: streams stay on this terminal, exit code is forwarded.
        target = Path(entry.path)
        if not target.exists():
            raise NotFoundError(f"{target} is missing", hint="Try `quiver fix` or re-add the app.")
        if not target.stat().st_mode & 0o111:
            target.chmod(0o755)
        raise SystemExit(
            subprocess.run(
                [str(target), *entry.exec_args, *(extra_args or [])], check=False
            ).returncode
        )
    data = services.launch_app(registry, alias, extra_args, console_output=console_output)
    if ui.json_mode:
        ui.emit_json(data)
        return
    _echo(ui, GLYPH_OK, f"launched {alias}")
    if ui.verbose and data.get("log"):
        _echo(ui, GLYPH_INFO, f"output appends to {data['log']}")


def _launch(
    ctx: typer.Context,
    alias: str = typer.Argument(..., help="App alias."),
    extra_args: list[str] | None = typer.Argument(None, help="Arguments after -- go to the app."),
    wait: bool = typer.Option(False, "--wait", help="Run in this terminal; forward the exit code."),
    console_output: bool = typer.Option(
        False, "--console", help="Keep app output on this terminal (default: detached to a log)."
    ),
) -> None:
    """Launch a managed AppImage detached (output goes to a per-app log)."""
    _launch_impl(ctx, alias, extra_args, wait, console_output)


app.command("launch")(handle_errors(_launch))


def _run() -> None:
    """Launch the interactive TUI (Linux)."""
    code = tui.launch_tui()
    if code:
        raise typer.Exit(code)


app.command("run")(handle_errors(_run))


@app.command("api", hidden=True)
@handle_errors
def _api() -> None:
    """Serve the JSON-RPC API over stdio (used by the TUI; internal)."""
    from quiver.api import serve

    serve()


@app.command("path")
@handle_errors
def path_cmd(
    ctx: typer.Context,
    alias: str = typer.Argument(...),
) -> None:
    """Print the managed AppImage's file path (scripting helper)."""
    ui = _ui(ctx)
    entry = _reg().require(alias)
    if ui.json_mode:
        ui.emit_json({"alias": alias, "path": entry.path})
    else:
        typer.echo(entry.path)


def _check_impl(ctx: typer.Context, alias: str | None, notify: bool) -> None:
    ui, cfg = _ui(ctx), _cfg(ctx)
    registry = _reg()

    def emit(level: str, message: str) -> None:
        if ui.json_mode:
            return
        _echo(ui, {"info": GLYPH_INFO, "warn": GLYPH_WARN}.get(level, GLYPH_INFO), message)

    if alias:
        result = services.check_app(cfg, registry, alias)
        results = [result]
        single = result
    else:
        results = services.check_all_apps(cfg, registry, emit=emit)
        single = None
    if ui.json_mode:
        ui.emit_json(single if single else results)
        return
    for item in results:
        _print_check(ui, _result_view(item))
    if single is None:
        available = sum(1 for r in results if r["status"] == updater.STATUS_UPDATE_AVAILABLE)
        failed = sum(
            1
            for r in results
            if r["status"] in (updater.STATUS_ERROR, updater.STATUS_SOURCE_UNAVAILABLE)
        )
        _echo(ui, GLYPH_INFO, f"{available} update(s) available, {failed} problem(s)")
        if notify and available:
            names = ", ".join(
                f"{r['name']} {r['current_version'] or '?'}->{r['latest_version']}"
                for r in results
                if r["status"] == updater.STATUS_UPDATE_AVAILABLE
            )
            integrations.notify("AppImage updates available", names)
        if failed:
            raise typer.Exit(1)


def _result_view(data: dict) -> updater.CheckResult:
    """Rebuild a CheckResult from its dict form (services return plain data)."""
    return updater.CheckResult(
        alias=data["alias"],
        name=data["name"],
        status=data["status"],
        current_version=data.get("current_version"),
        latest_version=data.get("latest_version"),
        prerelease=bool(data.get("prerelease")),
        message=data.get("message"),
        note=data.get("note"),
        matched_version=data.get("matched_version"),
    )


def _check(
    ctx: typer.Context,
    alias: str | None = typer.Argument(None, help="One app (default: all)."),
    notify: bool = typer.Option(
        False, "--notify", help="Desktop notification summary (check all)."
    ),
) -> None:
    """Check for upstream updates (no installs). Omit ALIAS to check everything."""
    _check_impl(ctx, alias, notify)


def _check_all(
    ctx: typer.Context,
    notify: bool = typer.Option(False, "--notify", help="Send a desktop notification summary."),
) -> None:
    """Check every managed app for updates."""
    _check_impl(ctx, None, notify)


app.command("check")(handle_errors(_check))
app.command("check-all", hidden=True)(handle_errors(_check_all))


def _print_check(ui: UI, result: updater.CheckResult) -> None:
    if result.status == updater.STATUS_UPDATE_AVAILABLE:
        _echo(
            ui,
            GLYPH_OK,
            f"{result.alias:<14} {result.current_version or '?'} → {result.latest_version}"
            + (" (prerelease)" if result.prerelease else ""),
        )
    elif result.status == updater.STATUS_UP_TO_DATE:
        _echo(ui, GLYPH_INFO, f"{result.alias:<14} up to date ({result.current_version})")
    elif result.status == updater.STATUS_NO_SOURCE:
        _echo(ui, GLYPH_WARN, f"{result.alias:<14} no update source configured")
    else:
        detail = result.message or result.status
        _echo(ui, GLYPH_ERR, f"{result.alias:<14} {result.status.replace('_', ' ')}: {detail}")


def _update_impl(
    ctx: typer.Context,
    alias: str | None,
    yes: bool,
    dry_run: bool,
    force: bool,
) -> None:
    ui, cfg = _ui(ctx), _cfg(ctx)
    registry = _reg()

    def emit(level: str, message: str) -> None:
        if ui.json_mode:
            return
        _echo(ui, {"info": GLYPH_INFO, "warn": GLYPH_WARN}.get(level, GLYPH_INFO), message)

    if alias:
        data = services.apply_update(
            cfg, registry, alias, force=force, dry_run=dry_run, console=ui.console, emit=emit
        )
        outcomes = [data]
        single = data
    else:
        outcomes = services.apply_update_all(
            cfg, registry, force=force, dry_run=dry_run, console=ui.console, emit=emit
        )
        single = None
    if ui.json_mode:
        ui.emit_json(single if single else outcomes)
    else:
        for data in outcomes:
            _print_outcome(ui, _outcome_view(data))
    failed = [o for o in outcomes if o["status"] == "failed"]
    updated = [o for o in outcomes if o["status"] == "updated"]
    if single is None and not ui.json_mode:
        _echo(
            ui,
            GLYPH_INFO,
            f"{len(updated)} updated, {len(failed)} failed, "
            f"{len(outcomes) - len(updated) - len(failed)} other",
        )
    if failed:
        raise typer.Exit(4)


def _outcome_view(data: dict) -> updater.UpdateOutcome:
    return updater.UpdateOutcome(
        alias=data["alias"],
        status=data["status"],
        old_version=data.get("old_version"),
        new_version=data.get("new_version"),
        steps=list(data.get("steps") or []),
        error=data.get("error"),
    )


def _update(
    ctx: typer.Context,
    alias: str | None = typer.Argument(None, help="One app (default: all with a source)."),
    yes: bool = typer.Option(False, "--yes", help="Non-interactive (default in scripts)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen."),
    force: bool = typer.Option(
        False, "--force", help="Update even if the version is unknown/same."
    ),
) -> None:
    """Update from the upstream source. Omit ALIAS to update everything."""
    _update_impl(ctx, alias, yes, dry_run, force)


def _update_all(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Update every managed app that has a source; one failure won't stop the rest."""
    _update_impl(ctx, None, yes, dry_run, False)


app.command("update")(handle_errors(_update))
app.command("update-all", hidden=True)(handle_errors(_update_all))


def _print_outcome(ui: UI, outcome: updater.UpdateOutcome) -> None:
    if outcome.status == "updated":
        _echo(
            ui,
            GLYPH_OK,
            f"{outcome.alias:<14} {outcome.old_version or '?'} → {outcome.new_version}",
        )
    elif outcome.status == "rolled_back":
        _echo(ui, GLYPH_OK, f"{outcome.alias:<14} rolled back to {outcome.new_version}")
    elif outcome.status == "up_to_date":
        _echo(ui, GLYPH_INFO, f"{outcome.alias:<14} up to date")
    elif outcome.status == "cancelled":
        _echo(ui, GLYPH_WARN, f"{outcome.alias:<14} skipped (declined)")
    elif outcome.status == "dry_run":
        _echo(ui, GLYPH_INFO, f"{outcome.alias:<14} (dry run) would update → {outcome.new_version}")
        for step in outcome.steps:
            ui.console.print(f"    {step}")
    else:
        _echo(
            ui,
            GLYPH_ERR,
            f"{outcome.alias:<14} {outcome.status.replace('_', ' ')}: {outcome.error}",
        )


@app.command()
@handle_errors
def history(ctx: typer.Context, alias: str = typer.Argument(...)) -> None:
    """Show version history (backups) for an app."""
    ui = _ui(ctx)
    _reg().require(alias)
    rows = _reg().history(alias)
    if ui.json_mode:
        ui.emit_json([vars(r) for r in rows])
        return
    if not rows:
        _echo(ui, GLYPH_INFO, "no history yet")
        return
    for h in rows:
        exists = Path(h.path).exists()
        mark = GLYPH_OK if exists else GLYPH_WARN
        ui.console.print(
            f"{mark} {h.created_at}  {h.action:<10} {h.version or '-':<12} "
            f"{'(backup available)' if exists else ''}"
        )


@app.command()
@handle_errors
def rollback(
    ctx: typer.Context,
    alias: str = typer.Argument(...),
    to_version: str | None = typer.Option(
        None, "--to", help="Version to restore (default: latest backup)."
    ),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Restore a previous version from backup."""
    ui, cfg = _ui(ctx), _cfg(ctx)
    registry = _reg()
    entry = registry.require(alias)
    outcome = updater.rollback(
        entry, cfg, registry, ui.console, to_version=to_version, assume_yes=yes
    )
    if ui.json_mode:
        ui.emit_json(outcome.to_dict())
        return
    _print_outcome(ui, outcome)
    if outcome.status == "failed":
        raise typer.Exit(4)


# ---- maintenance commands ------------------------------------------------------


@app.command()
@handle_errors
def scan(ctx: typer.Context) -> None:
    """Report AppImages, desktop entries and icons on this system. Read-only."""
    ui, cfg = _ui(ctx), _cfg(ctx)
    report = maintenance.scan(cfg, _reg())
    if ui.json_mode:
        ui.emit_json(report.to_dict())
        return
    managed = [a for a in report.appimages if a["managed"]]
    unmanaged = [a for a in report.appimages if not a["managed"]]
    ui.console.print(f"\n[bold]AppImages[/bold] ({len(report.appimages)} found)")
    for a in managed:
        _echo(
            ui,
            GLYPH_OK,
            f"{a['alias']:<14} managed   {Path(a['path']).name} "
            f"({storage.human_size(a['size'])}, {a['arch'] or '?'})",
        )
    for a in unmanaged:
        where = Path(a["path"]).parent
        if a.get("duplicate_of"):
            status = "identical" if a.get("identical_to_managed") else "differs"
            _echo(
                ui,
                GLYPH_INFO,
                f"{'':<14} imported original of {a['duplicate_of']} ({status})"
                f" - {where.name}/{Path(a['path']).name}",
            )
        elif a["valid_appimage"]:
            _echo(ui, GLYPH_INFO, f"{'':<14} unmanaged {Path(a['path']).name}")
        else:
            _echo(ui, GLYPH_WARN, f"{'':<14} invalid AppImage: {Path(a['path']).name}")
    ui.console.print(
        f"\n[bold]Desktop entries[/bold] ({len(report.desktop_entries)} AppImage-related/broken)"
    )
    for d in report.desktop_entries:
        if d["managed"]:
            _echo(ui, GLYPH_OK, f"{d['alias'] or d['file']:<26} managed    {d['file']}")
        elif not d["target_ok"]:
            _echo(ui, GLYPH_ERR, f"{d['file']:<26} broken Exec → {d['target']}")
        else:
            _echo(ui, GLYPH_WARN, f"{d['file']:<26} unmanaged  → {Path(d['target'] or '').name}")
    ui.console.print(f"\n[bold]Icons[/bold] ({len(report.icons)})")
    for icon in report.icons:
        kind = {
            "legacy (referenced)": "legacy (still referenced)",
            "legacy (unreferenced)": "legacy (unreferenced)",
            "managed": "managed",
            "orphan": "orphaned",
        }.get(icon["kind"], icon["kind"])
        _echo(
            ui,
            GLYPH_INFO if icon["kind"] == "managed" else GLYPH_WARN,
            f"{kind:<26} {Path(icon['path']).name}",
        )
    if report.duplicates:
        ui.console.print("\n[bold]Duplicate entries[/bold]")
        for dup in report.duplicates:
            _echo(ui, GLYPH_WARN, f"{', '.join(dup['entries'])} → {dup['exec']}")
    ui.console.print("")


@app.command()
@handle_errors
def doctor(ctx: typer.Context) -> None:
    """Diagnose the tool and every managed app. Read-only."""
    ui, cfg = _ui(ctx), _cfg(ctx)
    diags = maintenance.doctor(cfg, _reg())
    if ui.json_mode:
        ui.emit_json([vars(d) for d in diags])
        return
    counts = {"ok": 0, "info": 0, "warn": 0, "error": 0}
    for d in diags:
        counts[d.level] += 1
        glyph = {"ok": GLYPH_OK, "info": GLYPH_INFO, "warn": GLYPH_WARN, "error": GLYPH_ERR}[
            d.level
        ]
        _echo(
            ui,
            glyph,
            f"[dim]{d.area:<18}[/dim] {d.message}" + (f" [dim]({d.hint})[/dim]" if d.hint else ""),
        )
    _echo(
        ui,
        GLYPH_INFO,
        f"{counts['ok']} ok, {counts['info']} info, {counts['warn']} warnings, "
        f"{counts['error']} errors",
    )
    if counts["error"]:
        raise typer.Exit(1)


@app.command()
@handle_errors
def clean(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be removed."),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Remove leftovers this tool owns: temp downloads, old backups, stale entries/icons."""
    ui, cfg = _ui(ctx), _cfg(ctx)
    report = maintenance.clean(cfg, _reg(), ui.console, dry_run=dry_run, assume_yes=yes)
    if ui.json_mode:
        ui.emit_json({"removed": report.removed, "kept": report.kept, "skipped": report.skipped})
        return
    if not report.removed and not report.skipped:
        _echo(ui, GLYPH_OK, "nothing to clean")
    elif report.removed:
        _echo(ui, GLYPH_OK, f"removed {len(report.removed)} item(s)")


def _fix_impl(ctx: typer.Context, alias: str | None, yes: bool) -> None:
    ui, cfg = _ui(ctx), _cfg(ctx)
    report = maintenance.repair(cfg, _reg(), ui.console, alias=alias, assume_yes=yes)
    if ui.json_mode:
        ui.emit_json({"steps": report.steps})
        return
    if not report.steps:
        _echo(ui, GLYPH_OK, "nothing to repair")
    for step in report.steps:
        _echo(ui, GLYPH_OK if step != "cancelled" else GLYPH_WARN, step)


def _fix(
    ctx: typer.Context,
    alias: str | None = typer.Argument(None, help="Repair one app (default: all)."),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Fix managed files: exec bits, desktop entries, icons, missing markers."""
    _fix_impl(ctx, alias, yes)


def _repair(
    ctx: typer.Context,
    alias: str | None = typer.Argument(None, help="Repair one app (default: all)."),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Alias for fix."""
    _fix_impl(ctx, alias, yes)


app.command("fix")(handle_errors(_fix))
app.command("repair", hidden=True)(handle_errors(_repair))


@app.command()
@handle_errors
def refresh(
    ctx: typer.Context,
    alias: str | None = typer.Argument(None, help="Refresh one app (default: all)."),
) -> None:
    """Re-read AppImages on disk and sync registry metadata.

    For apps that self-update in place (e.g. ZCode): updates the stored
    version, hash, size and icon to match the actual file.
    """
    ui, cfg = _ui(ctx), _cfg(ctx)
    report = maintenance.refresh(cfg, _reg(), alias=alias)
    if ui.json_mode:
        ui.emit_json(report.to_dict())
        return
    for item in report.refreshed:
        alias_name = item["alias"]
        changes = item["changes"]
        version_note = ""
        if "version" in changes:
            old, new = changes["version"]
            version_note = f": {old or '?'} -> {new}"
        fields = ", ".join(sorted(changes)) or "hash"
        _echo(ui, GLYPH_OK, f"{alias_name} refreshed ({fields}){version_note}")
    for name in report.unchanged:
        _echo(ui, GLYPH_INFO, f"{name} unchanged")
    for item in report.failed:
        _echo(ui, GLYPH_WARN, f"{item['alias']}: {item['error']}")
    if not report.refreshed and not report.unchanged and not report.failed:
        _echo(ui, GLYPH_OK, "nothing registered")


def _import_impl(
    ctx: typer.Context,
    adopt_all: bool,
    yes: bool,
    dry_run: bool,
    no_integrate: bool,
    in_place: bool,
    directory: list[Path] | None,
) -> None:
    ui, cfg = _ui(ctx), _cfg(ctx)
    cfg.ensure_dirs()
    report = maintenance.import_existing(
        cfg,
        _reg(),
        ui.console,
        adopt_all=adopt_all,
        assume_yes=yes,
        dry_run=dry_run,
        integrate=not no_integrate,
        in_place=in_place or None,
        extra_dirs=directory,
    )
    if ui.json_mode:
        ui.emit_json(report.to_dict())
        return
    for item in report.adopted:
        if item.get("dry_run"):
            _echo(
                ui,
                GLYPH_INFO,
                f"would adopt {Path(item['path']).name} as [bold]{escape(item['alias'])}[/bold] "
                f"({item['version'] or 'version unknown'})",
            )
        else:
            adopted_entry = " (adopted existing desktop entry)" if item.get("adopted_entry") else ""
            _echo(
                ui,
                GLYPH_OK,
                f"adopted [bold]{escape(item['alias'])}[/bold] {escape(str(item['name']))} "
                f"{item['version'] or '?'}{adopted_entry}",
            )
            for warning in item.get("warnings", []):
                _echo(ui, GLYPH_WARN, f"    {escape(warning)}")
    for item in report.skipped:
        _echo(ui, GLYPH_WARN, f"skipped {item['path']}: {item['reason']}")
    for item in report.failed:
        _echo(ui, GLYPH_ERR, f"failed {item['path']}: {item['error']}")


def _import(
    ctx: typer.Context,
    adopt_all: bool = typer.Option(
        False, "--adopt-all", help="Adopt everything found without asking."
    ),
    yes: bool = typer.Option(False, "--yes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be imported."),
    no_integrate: bool = typer.Option(False, "--no-integrate"),
    in_place: bool = typer.Option(
        False, "--in-place", help="Manage files where they are (no copy)."
    ),
    directory: list[Path] | None = typer.Option(None, "--dir", help="Extra directory to scan."),
) -> None:
    """Find AppImages in your collection dirs and adopt them into the manager."""
    _import_impl(ctx, adopt_all, yes, dry_run, no_integrate, in_place, directory)


def _import_existing(
    ctx: typer.Context,
    adopt_all: bool = typer.Option(
        False, "--adopt-all", help="Adopt everything found without asking."
    ),
    yes: bool = typer.Option(False, "--yes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be imported."),
    no_integrate: bool = typer.Option(False, "--no-integrate"),
    in_place: bool = typer.Option(
        False, "--in-place", help="Manage files where they are (no copy)."
    ),
    directory: list[Path] | None = typer.Option(None, "--dir", help="Extra directory to scan."),
) -> None:
    """Alias for import."""
    _import_impl(ctx, adopt_all, yes, dry_run, no_integrate, in_place, directory)


app.command("import")(handle_errors(_import))
app.command("import-existing", hidden=True)(handle_errors(_import_existing))


# ---- source management ---------------------------------------------------------


def _apply_source(entry: AppEntry, source: str) -> None:
    """Parse 'github:owner/repo' / 'gitlab:g/p' / 'url:https://' / 'command:...'."""
    services.apply_source_spec(entry, source)


@source_app.command("set")
@handle_errors
def source_set(
    ctx: typer.Context,
    alias: str = typer.Argument(...),
    kind: str = typer.Argument(..., help=f"One of: {', '.join(known_providers())}."),
    value: str = typer.Argument(..., help="owner/repo, URL or command."),
    asset_pattern: list[str] | None = typer.Option(
        None, "--asset-pattern", help="Restrict asset matching (glob)."
    ),
    allow_prerelease: bool = typer.Option(False, "--prerelease", help="Allow prerelease versions."),
) -> None:
    """Configure how an app finds updates. Example: quiver source set foo github owner/repo"""
    ui = _ui(ctx)
    data = services.set_source(
        _reg(),
        alias,
        kind,
        value,
        asset_patterns=asset_pattern,
        allow_prerelease=allow_prerelease,
    )
    if ui.json_mode:
        ui.emit_json(data)
        return
    _echo(ui, GLYPH_OK, f"{alias}: {data['source_type']}:{data['source_repo']}")


@source_app.command("show")
@handle_errors
def source_show(ctx: typer.Context, alias: str) -> None:
    """Show the configured update source for an app."""
    ui = _ui(ctx)
    entry = _reg().require(alias)
    if ui.json_mode:
        ui.emit_json(
            {
                "alias": alias,
                "source_type": entry.source_type,
                "source_repo": entry.source_repo,
                "source_opts": entry.source_opts,
            }
        )
        return
    if entry.source_configured:
        ui.console.print(f"{entry.alias}: {entry.source_type}:{entry.source_repo}")
        for key, value in entry.source_opts.items():
            ui.console.print(f"  {key} = {value}")
    else:
        _echo(ui, GLYPH_WARN, f"{alias}: no source configured")


@source_app.command("clear")
@handle_errors
def source_clear(ctx: typer.Context, alias: str) -> None:
    """Remove the update source from an app."""
    ui = _ui(ctx)
    services.clear_source(_reg(), alias)
    _echo(ui, GLYPH_OK, f"{alias}: source cleared")


def _detect_impl(
    ctx: typer.Context,
    alias: str | None,
    all_apps: bool,
    search: bool,
    set_first: bool,
) -> None:
    """Figure out where an app's updates come from.

    Order of evidence: update info embedded in the AppImage itself, then its
    app id (io.github.<owner>.<project>), then URLs from its metadata, and
    finally a GitHub search. Every candidate is verified to actually publish
    an AppImage asset for this machine's architecture.
    """
    ui, cfg = _ui(ctx), _cfg(ctx)
    registry = _reg()
    if not alias and not all_apps:
        raise UsageError("give an app alias or pass --all")
    if alias and all_apps:
        raise UsageError("use either an alias or --all, not both")

    def emit(level: str, message: str) -> None:
        if ui.json_mode:
            return
        _echo(ui, {"info": GLYPH_INFO, "warn": GLYPH_WARN}.get(level, GLYPH_INFO), message)

    report = services.detect_source(
        cfg, registry, alias, all_apps=all_apps, search=search, set_first=set_first, emit=emit
    )
    if ui.json_mode:
        ui.emit_json(report)
        return
    for app in report["apps"]:
        entry_alias = app["alias"]
        candidates = app["candidates"]
        if not candidates:
            _echo(ui, GLYPH_WARN, f"{entry_alias:<14} no update source found")
            _echo(ui, GLYPH_INFO, f"  try: quiver source set {entry_alias} github owner/repo")
            continue
        if app.get("set"):
            best = candidates[0]
            _echo(
                ui,
                GLYPH_OK,
                f"{entry_alias:<14} {app['set']} (latest {best['version']}; via {best['via']})",
            )
            continue
        _echo(ui, GLYPH_INFO, f"{entry_alias:<14} candidates (pick one):")
        for index, cand in enumerate(candidates):
            marker = "→" if index == 0 else " "
            ui.console.print(
                f"  {marker} {cand['repo']:<40} latest {cand['version']:<12}"
                f"[dim]({cand['via']})[/dim]"
            )
        _echo(
            ui,
            GLYPH_INFO,
            f"  choose with: quiver source set {entry_alias} github <owner/repo>"
            f" (or re-run with --set for the top pick)",
        )
    unresolved = sum(1 for a in report["apps"] if not a["candidates"])
    if not report["apps"]:
        _echo(ui, GLYPH_INFO, "every managed app already has a source")
    elif unresolved:
        raise typer.Exit(1)


@source_app.command("detect")
@handle_errors
def source_detect(
    ctx: typer.Context,
    alias: str | None = typer.Argument(None, help="App alias (or use --all)."),
    all_apps: bool = typer.Option(
        False, "--all", help="Detect for every managed app that has no source yet."
    ),
    search: bool = typer.Option(
        True, "--search/--no-search", help="Search GitHub when the file carries no hint."
    ),
    set_first: bool = typer.Option(False, "--set", help="Save the best candidate without asking."),
) -> None:
    _detect_impl(ctx, alias, all_apps, search, set_first)


def _detect_source(
    ctx: typer.Context,
    alias: str | None = typer.Argument(None, help="App alias (or use --all)."),
    all_apps: bool = typer.Option(
        False, "--all", help="Detect for every managed app that has no source yet."
    ),
    search: bool = typer.Option(
        True, "--search/--no-search", help="Search GitHub when the file carries no hint."
    ),
    set_first: bool = typer.Option(False, "--set", help="Save the best candidate without asking."),
) -> None:
    """Alias for `quiver source detect`."""
    _detect_impl(ctx, alias, all_apps, search, set_first)


app.command("detect-source", hidden=True)(handle_errors(_detect_source))


# ---- modification ---------------------------------------------------------------


def _modify_impl(
    ctx: typer.Context,
    alias: str,
    name: str | None,
    exec_args: str | None,
    categories: str | None,
    auto_check: str | None,
    integrate_flag: bool | None,
    notes: str | None,
) -> None:
    ui, cfg = _ui(ctx), _cfg(ctx)
    if auto_check is not None and auto_check not in ("manual", "off"):
        raise UsageError("--auto-check must be manual or off")
    any_change = any(
        v is not None for v in (name, exec_args, categories, auto_check, notes, integrate_flag)
    )
    if not any_change:
        _echo(ui, GLYPH_INFO, "nothing to change")
        return
    updated = services.modify_app(
        cfg,
        _reg(),
        alias,
        name=name,
        exec_args=exec_args,
        categories=categories,
        auto_check=auto_check,
        notes=notes,
        integrate=integrate_flag,
    )
    if ui.json_mode:
        ui.emit_json(updated)
        return
    _echo(ui, GLYPH_OK, f"{alias} updated")


def _modify(
    ctx: typer.Context,
    alias: str = typer.Argument(..., help="App alias."),
    name: str | None = typer.Option(None, "--name"),
    exec_args: str | None = typer.Option(
        None, "--exec-args", help='e.g. "--ozone-platform=wayland"'
    ),
    categories: str | None = typer.Option(None, "--categories"),
    auto_check: str | None = typer.Option(None, "--auto-check", help="manual | off"),
    integrate_flag: bool | None = typer.Option(None, "--integrate/--no-integrate"),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    """Change registered metadata for an app."""
    _modify_impl(ctx, alias, name, exec_args, categories, auto_check, integrate_flag, notes)


def _set_cmd(
    ctx: typer.Context,
    alias: str = typer.Argument(..., help="App alias."),
    name: str | None = typer.Option(None, "--name"),
    exec_args: str | None = typer.Option(
        None, "--exec-args", help='e.g. "--ozone-platform=wayland"'
    ),
    categories: str | None = typer.Option(None, "--categories"),
    auto_check: str | None = typer.Option(None, "--auto-check", help="manual | off"),
    integrate_flag: bool | None = typer.Option(None, "--integrate/--no-integrate"),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    """Alias for modify."""
    _modify_impl(ctx, alias, name, exec_args, categories, auto_check, integrate_flag, notes)


app.command("modify")(handle_errors(_modify))
app.command("set", hidden=True)(handle_errors(_set_cmd))


# ---- config ----------------------------------------------------------------------


@config_app.command("show")
@handle_errors
def config_show(ctx: typer.Context) -> None:
    """Print the effective configuration."""
    ui, cfg = _ui(ctx), _cfg(ctx)
    if ui.json_mode:
        ui.emit_json(cfg.data)
        return
    ui.console.print(f"[dim]# {cfg.path}[/dim]")
    for key, value in cfg.data.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                shown = "***" if sub_key == "token" and sub_value else sub_value
                ui.console.print(f"{key}.{sub_key} = {shown!r}")
        else:
            ui.console.print(f"{key} = {value!r}")


@config_app.command("get")
@handle_errors
def config_get(ctx: typer.Context, key: str) -> None:
    """Read one configuration value."""
    ui = _ui(ctx)
    value = _cfg(ctx).get(key)
    if ui.json_mode:
        ui.emit_json({"key": key, "value": value})
    else:
        ui.console.print(value)


@config_app.command("set")
@handle_errors
def config_set(ctx: typer.Context, key: str, value: str) -> None:
    """Write one configuration value, e.g. quiver config set storage_dir ~/Apps"""
    ui = _ui(ctx)
    cfg = _cfg(ctx)
    parsed = parse_config_value(key, value)
    cfg.set(key, parsed)
    _echo(ui, GLYPH_OK, f"{key} = {value}")


@config_app.command("path")
@handle_errors
def config_path_cmd(ctx: typer.Context) -> None:
    """Print config and state file locations."""
    ui = _ui(ctx)
    from quiver import paths

    data = {
        "config": str(config_file_path()),
        "registry": str(paths.app_state_dir() / "registry.db"),
        "storage_default": "~/.local/share/AppImages",
        "state_dir": str(paths.app_state_dir()),
    }
    if ui.json_mode:
        ui.emit_json(data)
    else:
        for key, value in data.items():
            typer.echo(f"{key:<15} {value}")


# ---- timer ------------------------------------------------------------------------


@timer_app.command("install")
@handle_errors
def timer_install(
    ctx: typer.Context,
    on_calendar: str = typer.Option(
        "daily", "--on-calendar", help="systemd OnCalendar expression."
    ),
    no_enable: bool = typer.Option(False, "--no-enable", help="Write units but don't enable them."),
) -> None:
    """Install a systemd user timer that runs `quiver check-all --notify`."""
    ui, cfg = _ui(ctx), _cfg(ctx)
    path = integrations.install_timer(cfg, on_calendar=on_calendar, enable=not no_enable)
    _echo(ui, GLYPH_OK, f"timer installed: {path} ({on_calendar})")


@timer_app.command("uninstall")
@handle_errors
def timer_uninstall(ctx: typer.Context) -> None:
    """Remove the systemd user timer."""
    ui = _ui(ctx)
    if integrations.uninstall_timer():
        _echo(ui, GLYPH_OK, "timer removed")
    else:
        _echo(ui, GLYPH_INFO, "no timer was installed")


@timer_app.command("status")
@handle_errors
def timer_status_cmd(ctx: typer.Context) -> None:
    """Show timer status."""
    ui = _ui(ctx)
    ui.console.print(integrations.timer_status())


# ---- entry point -------------------------------------------------------------------


def main() -> None:  # console_scripts entry point
    app()


if __name__ == "__main__":
    main()
