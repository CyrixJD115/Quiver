"""Interactive TUI launcher.

The TUI itself is an OpenTUI (TypeScript) application compiled into a single
standalone binary with `bun build --compile` (see tui/ and scripts/build-tui.sh)
and shipped inside this Python package. The binary speaks JSON-RPC to `quiver
api` over stdio - the Python backend stays the single source of truth.

Linux-only by design: the compiled frontend targets Linux and the whole
interactive surface is explicitly scoped to it. The CLI remains portable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from quiver.errors import UsageError

BINARY_NAME = "quiver-tui"


def tui_binary_path() -> Path | None:
    """Locate the bundled TUI binary, if present."""
    bundled = Path(__file__).parent / "bin" / BINARY_NAME
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return bundled
    found = shutil.which(BINARY_NAME)
    return Path(found) if found else None


def _quiver_executable() -> str:
    """Best-effort path of the running quiver command, for the TUI to spawn
    `quiver api` from."""
    if getattr(sys, "frozen", False):  # pragma: no cover - not a frozen build today
        return sys.executable
    candidate = Path(sys.argv[0]).resolve()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    found = shutil.which("quiver")
    if found:
        return found
    return sys.executable  # last resort: a python -m invocation is not supported


def launch_tui(args: list[str] | None = None) -> int:
    """Spawn the TUI as a child process and forward its exit code."""
    if sys.platform != "linux":
        raise UsageError("the interactive TUI is Linux-only; the CLI commands work everywhere")
    binary = tui_binary_path()
    if binary is None:
        raise UsageError(
            "TUI binary not bundled with this install",
            hint="Build it with `scripts/build-tui.sh` (needs Bun), then reinstall.",
        )
    env = dict(os.environ)
    env.setdefault("QUIVER_API", _quiver_executable())
    env.setdefault("QUIVER_TUI", "1")
    result = subprocess.run([str(binary), *(args or [])], env=env, check=False)
    return result.returncode


def should_autolaunch() -> bool:
    """Bare `quiver` opens the TUI when interactive, on Linux, with a bundled
    binary; scripts and pipes get normal help output instead."""
    return (
        sys.platform == "linux"
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and tui_binary_path() is not None
    )
