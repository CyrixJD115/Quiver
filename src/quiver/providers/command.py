"""User-defined command provider.

The command prints JSON on stdout::

    {"version": "1.2.3", "url": "https://.../App-1.2.3.AppImage", "sha256": "..."}
"""

from __future__ import annotations

import json
import shlex
import subprocess

import httpx

from quiver import versions
from quiver.config import Config
from quiver.providers.base import Asset, ProviderError, Release, UpdateProvider, register
from quiver.registry import AppEntry


@register
class CommandProvider(UpdateProvider):
    type_name = "command"

    def latest_release(self, app: AppEntry, cfg: Config, client: httpx.Client) -> Release:
        command = app.source_opts.get("command")
        if isinstance(command, str):
            command = shlex.split(command)
        if not command or not isinstance(command, list):
            raise ProviderError(
                f"{app.alias}: command source needs a command",
                hint="Set one with: quiver source set <alias> command -- '<cmd>'",
            )
        try:
            proc = subprocess.run(
                [str(part) for part in command],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ProviderError(f"custom update command failed to run: {exc}") from exc
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()[:200]
            raise ProviderError(
                f"custom update command exited {proc.returncode}: {stderr}",
                hint="Run the command manually to see the full error.",
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"custom update command did not print JSON: {exc}",
                hint='Expected e.g. {"version": "1.2.3", "url": "https://..."}',
            ) from exc
        version = versions.normalize(str(data.get("version", "")))
        url = data.get("url")
        if not version or not url:
            raise ProviderError("custom update command JSON must include 'version' and 'url'")
        asset = Asset(
            name=url.rstrip("/").rsplit("/", 1)[-1] or "download",
            url=str(url),
            sha256=data.get("sha256"),
        )
        return Release(
            tag=str(data.get("version", "")),
            version=version,
            prerelease=bool(data.get("prerelease", False)),
            assets=[asset],
        )
