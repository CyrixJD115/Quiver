"""Update orchestration: check, update, update-all, rollback.

The golden rule: never destroy the working AppImage. Downloads land in .part
files, get verified (magic, architecture, size, sha256), the current file is
backed up, and only then does an atomic rename swap it in.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from rich.console import Console

from quiver import appimage, desktop, download, storage, versions
from quiver.config import Config
from quiver.errors import AimError, UpdateFailedError
from quiver.output import confirm
from quiver.providers import Asset, ProviderError, get_provider, select_asset
from quiver.registry import AppEntry, Registry

STATUS_UP_TO_DATE = "up_to_date"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_NO_SOURCE = "no_source"
STATUS_UNKNOWN_VERSION = "unknown_version"
STATUS_SOURCE_UNAVAILABLE = "source_unavailable"
STATUS_ERROR = "error"


@dataclass
class CheckResult:
    alias: str
    name: str
    status: str
    current_version: str | None = None
    latest_version: str | None = None
    asset: Asset | None = None
    prerelease: bool = False
    message: str | None = None
    note: str | None = None
    matched_version: str | None = None  # fingerprinted from the asset sha256

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "name": self.name,
            "status": self.status,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "asset": None
            if self.asset is None
            else {"name": self.asset.name, "url": self.asset.url, "size": self.asset.size},
            "prerelease": self.prerelease,
            "message": self.message,
            "matched_version": self.matched_version,
        }


@dataclass
class UpdateOutcome:
    alias: str
    status: (
        str  # updated | up_to_date | skipped_no_source | failed | dry_run | rolled_back | cancelled
    )
    old_version: str | None = None
    new_version: str | None = None
    steps: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "status": self.status,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "steps": self.steps,
            "error": self.error,
        }


def check(app: AppEntry, cfg: Config, client: httpx.Client) -> CheckResult:
    """Determine whether a newer upstream version exists. Pure check - no writes."""
    result = CheckResult(
        alias=app.alias, name=app.name, status=STATUS_ERROR, current_version=app.version
    )
    if not app.source_configured:
        result.status = STATUS_NO_SOURCE
        result.message = "no update source configured"
        return result
    try:
        provider = get_provider(app.source_type or "")
    except ProviderError as exc:
        result.status = STATUS_SOURCE_UNAVAILABLE
        result.message = str(exc)
        return result
    try:
        release = provider.latest_release(app, cfg, client)
    except ProviderError as exc:
        result.status = STATUS_SOURCE_UNAVAILABLE
        result.message = str(exc)
        return result
    except AimError as exc:
        result.status = STATUS_ERROR
        result.message = str(exc)
        return result

    result.latest_version = release.version or None
    result.prerelease = release.prerelease
    result.note = release.note

    asset = select_asset(
        release.assets,
        app.arch,
        current_name=Path(app.path).name,
        patterns=app.source_opts.get("asset_patterns"),
    )
    result.asset = asset

    if app.source_type == "url":
        # No semantic versions; change is detected by content hash.
        if asset is None:
            result.status = STATUS_ERROR
            result.message = "no downloadable asset at the configured URL"
            return result
        changed = (asset.sha256 or "") != (app.sha256 or "")
        result.status = STATUS_UPDATE_AVAILABLE if changed else STATUS_UP_TO_DATE
        result.latest_version = "latest" if changed else (app.version or "latest")
        if changed and asset.sha256 is None:
            result.status = STATUS_ERROR
            result.message = "could not determine whether content changed"
        return result

    if not app.version:
        # The installed version was never recorded - but when the provider
        # publishes asset digests, an exact sha256 match tells us precisely
        # which release the local file is.
        if (
            asset is not None
            and asset.sha256
            and app.sha256
            and asset.sha256.lower() == app.sha256.lower()
        ):
            result.status = STATUS_UP_TO_DATE
            result.current_version = release.version
            result.matched_version = release.version or None
            result.message = f"installed file matches upstream {release.version} exactly (sha256)"
            return result
        result.status = STATUS_UNKNOWN_VERSION
        result.message = (
            f"installed version unknown; upstream latest is {release.version or release.tag or '?'}"
        )
        return result
    if versions.is_newer(release.version, app.version):
        result.status = STATUS_UPDATE_AVAILABLE
        if asset is None:
            result.status = STATUS_ERROR
            result.message = f"release {release.tag} has no matching AppImage asset"
        return result
    result.status = STATUS_UP_TO_DATE
    return result


def record_check(registry: Registry, app: AppEntry, result: CheckResult) -> None:
    from datetime import UTC, datetime

    changes: dict[str, object] = {
        "last_check_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_check_result": result.to_dict(),
    }
    if result.matched_version:
        changes["version"] = result.matched_version
    registry.update(app.alias, **changes)


def perform_update(
    app: AppEntry,
    cfg: Config,
    registry: Registry,
    client: httpx.Client,
    console: Console | None = None,
    *,
    assume_yes: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> UpdateOutcome:
    """Check and install an update for one app following the safe pipeline."""
    outcome = UpdateOutcome(alias=app.alias, status="failed", old_version=app.version)
    target = Path(app.path)

    if not target.exists():
        outcome.error = f"managed AppImage is missing: {target}"
        return outcome

    result = check(app, cfg, client)
    record_check(registry, app, result)

    if result.status == STATUS_NO_SOURCE:
        outcome.status = "skipped_no_source"
        outcome.error = "no update source configured"
        return outcome
    if result.status in (STATUS_SOURCE_UNAVAILABLE, STATUS_ERROR):
        outcome.error = result.message
        return outcome
    if result.status == STATUS_UNKNOWN_VERSION:
        if not force:
            outcome.error = result.message
            outcome.steps.append("use --force to update anyway")
            return outcome
        outcome.steps.append("installed version unknown; forced update")
    elif result.status == STATUS_UP_TO_DATE and not force:
        outcome.status = "up_to_date"
        return outcome
    if result.asset is None:
        outcome.error = "no matching AppImage asset in the latest release"
        return outcome

    asset = result.asset
    outcome.new_version = result.latest_version

    if dry_run:
        outcome.status = "dry_run"
        size = storage.human_size(asset.size)
        outcome.steps = [
            f"would download {asset.name} ({size})",
            f"would verify (appimage magic, arch {app.arch or '?'}, sha256 if provided)",
            f"would back up current file ({app.version or 'unknown version'})",
            f"would replace {target}",
        ]
        return outcome

    if console is not None:
        prompt = (
            f"Update {app.name} {app.version or '?'} -> {result.latest_version} "
            f"({storage.human_size(asset.size)})?"
        )
        if not confirm(console, prompt, assume_yes=assume_yes):
            outcome.status = "cancelled"
            return outcome

    # 1. download to a .part next to the target (same filesystem => atomic rename)
    part = download.download(client, asset.url, target.parent, label=asset.name, console=console)
    try:
        # 2. verify the download really is what upstream says it is
        new_sha = download.verify_downloaded(part, sha256=asset.sha256, size=asset.size)
        appimage.verify_appimage(part, app.arch)
        # 3. back up the current file before replacing it
        backup = storage.backup_file(target, cfg.backup_dir, app.alias, keep=cfg.backups_keep)
        outcome.steps.append(f"backed up to {backup}")
        # 4. atomic swap, preserving the previous mode
        mode = target.stat().st_mode & 0o777
        storage.atomic_replace(part, target, mode=mode)
        outcome.steps.append(f"installed {asset.name}")
        # 5. registry + history
        registry.add_history(
            app.alias,
            action="updated",
            version=result.latest_version,
            path=str(target),
            sha256=new_sha,
            size=target.stat().st_size,
        )
        registry.prune_history(app.alias, keep=10)
        changes: dict[str, object] = {
            "version": result.latest_version,
            "sha256": new_sha,
            "size": target.stat().st_size,
        }
        if app.source_type == "url":
            changes["version"] = f"latest-{new_sha[:12]}"
            head = download.head_info(client, asset.url)
            opts = dict(app.source_opts)
            if head.get("etag"):
                opts["last_etag"] = head["etag"]
            if head.get("last_modified"):
                opts["last_modified"] = head["last_modified"]
            changes["source_opts"] = opts
        registry.update(app.alias, **changes)
        # 6. keep the desktop entry pointing at the (unchanged) path accurate
        if app.integrated:
            entry_changed = desktop.refresh_entry(app, cfg)
            if entry_changed:
                outcome.steps.append("desktop entry refreshed")
        outcome.status = "updated"
    except UpdateFailedError as exc:
        part.unlink(missing_ok=True)
        outcome.error = str(exc)
        outcome.steps.append("download discarded; existing AppImage untouched")
    return outcome


def update_all(
    cfg: Config,
    registry: Registry,
    client: httpx.Client,
    console: Console | None = None,
    *,
    assume_yes: bool = False,
    dry_run: bool = False,
    include_no_source: bool = True,
) -> list[UpdateOutcome]:
    """Update every managed app with a configured source; isolate failures."""
    outcomes: list[UpdateOutcome] = []
    for app in registry.all():
        if app.autoupdate == "off":
            continue
        try:
            outcome = perform_update(
                app,
                cfg,
                registry,
                client,
                console,
                assume_yes=assume_yes,
                dry_run=dry_run,
            )
        except Exception as exc:
            outcome = UpdateOutcome(
                alias=app.alias, status="failed", error=f"unexpected error: {exc}"
            )
        outcomes.append(outcome)
    return outcomes


def rollback(
    app: AppEntry,
    cfg: Config,
    registry: Registry,
    console: Console | None = None,
    *,
    to_version: str | None = None,
    assume_yes: bool = False,
) -> UpdateOutcome:
    """Restore a previous version from the backup area."""
    outcome = UpdateOutcome(alias=app.alias, status="failed", old_version=app.version)
    target = Path(app.path)
    backups = storage.list_backups(cfg.backup_dir, app.alias)
    if not backups:
        outcome.error = "no backups available for this app"
        return outcome

    chosen: Path | None = None
    if to_version:
        for candidate in backups:
            if to_version in candidate.name:
                chosen = candidate
                break
        if chosen is None:
            outcome.error = f"no backup matching version {to_version!r}"
            return outcome
    else:
        chosen = backups[0]

    if console is not None and not confirm(
        console, f"Roll back {app.name} to {chosen.name}?", assume_yes=assume_yes
    ):
        outcome.status = "cancelled"
        return outcome

    current_mode = target.stat().st_mode & 0o777 if target.exists() else 0o755
    if target.exists():
        storage.backup_file(target, cfg.backup_dir, app.alias, keep=cfg.backups_keep)
    restored_sha = appimage.sha256_of(chosen)
    tmp = target.parent / f".{app.alias}.restoring"
    shutil.copy2(chosen, tmp)
    storage.atomic_replace(tmp, target, mode=current_mode)

    # Recover the version from the history row matching this exact file.
    old_version = (
        next(
            (
                h.version
                for h in registry.history(app.alias)
                if h.sha256 == restored_sha and h.version
            ),
            None,
        )
        or app.version
    )
    registry.update(app.alias, version=old_version, sha256=restored_sha, size=target.stat().st_size)
    registry.add_history(
        app.alias,
        action="rolled_back",
        version=old_version,
        path=str(target),
        sha256=restored_sha,
        size=target.stat().st_size,
    )
    if app.integrated:
        desktop.refresh_entry(app, cfg)
    outcome.status = "rolled_back"
    outcome.new_version = old_version
    outcome.steps.append(f"restored from {chosen}")
    return outcome
