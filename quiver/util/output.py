"""Console output helpers: glyphs, colors, JSON mode, confirmations."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console

from quiver.util.errors import UsageError

GLYPH_OK = "[green]✓[/green]"
GLYPH_INFO = "[cyan]•[/cyan]"
GLYPH_WARN = "[yellow]⚠[/yellow]"
GLYPH_ERR = "[red]✗[/red]"


@dataclass
class UI:
    """Per-invocation UI settings passed through the Typer context."""

    json_mode: bool = False
    quiet: bool = False
    verbose: bool = False
    cfg_path: str | None = None
    console: Console = field(default_factory=Console)

    def emit_json(self, data: Any) -> None:
        # typer.echo, not rich: the console soft-wraps long lines, which would
        # corrupt machine-readable JSON.
        import typer

        typer.echo(json.dumps(data, indent=2, default=str, ensure_ascii=False))


def is_interactive(console: Console) -> bool:
    return console.is_terminal and sys.stdin.isatty()


def confirm(
    console: Console,
    prompt: str,
    *,
    default: bool = False,
    assume_yes: bool = False,
) -> bool:
    """Ask the user to confirm.

    Non-interactive sessions must pass assume_yes (e.g. --yes); otherwise we
    refuse rather than silently guessing.
    """
    if assume_yes:
        return True
    if not is_interactive(console):
        raise UsageError(
            f"Refusing to proceed non-interactively: {prompt}",
            hint="Re-run with --yes to skip this confirmation.",
        )
    from rich.prompt import Confirm

    return Confirm.ask(prompt, console=console, default=default)
