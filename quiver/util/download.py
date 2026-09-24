"""HTTP downloads with streaming, progress and integrity checks."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
from rich.console import Console

from quiver import __version__
from quiver.util.config import Config
from quiver.util.errors import NetworkError, VerificationError

USER_AGENT = f"quiver/{__version__} (+appimage manager)"


def http_client(cfg: Config | None = None, *, timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=timeout,
    )


def download(
    client: httpx.Client,
    url: str,
    dest_dir: Path,
    *,
    label: str | None = None,
    console: Console | None = None,
    quiet: bool = False,
) -> Path:
    """Stream ``url`` into a .part file in ``dest_dir`` and return its path.

    The caller is responsible for verification and atomic replacement; this
    function only moves bytes and checks size/sha when provided.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = label or url.rstrip("/").rsplit("/", 1)[-1] or "download"
    part_file = dest_dir / f".{name}.part"

    progress = _make_progress(console, quiet, name)
    task_id = None
    try:
        with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise NetworkError(f"download failed: HTTP {response.status_code} for {url}")
            total = _parse_content_length(response.headers.get("content-length"))
            digest = hashlib.sha256()
            written = 0
            if progress is not None:
                task_id = progress.add_task(f"downloading {name}", total=total)
                progress.start()
            with progress or _null_context(), part_file.open("wb") as fh:
                for chunk in response.iter_bytes(chunk_size=1024 * 256):
                    fh.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if progress is not None and task_id is not None:
                        progress.advance(task_id, len(chunk))
    except httpx.HTTPError as exc:
        part_file.unlink(missing_ok=True)
        raise NetworkError(f"download failed: {exc}") from exc
    finally:
        if progress is not None:
            progress.stop()

    if total is not None and written != total:
        part_file.unlink(missing_ok=True)
        raise NetworkError(
            f"download incomplete: got {written} of {total} bytes for {name}",
            hint="The connection may have dropped; simply retry.",
        )
    return part_file


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _null_context() -> _NullContext:
    return _NullContext()


def verify_downloaded(
    part_file: Path,
    *,
    sha256: str | None = None,
    size: int | None = None,
) -> str:
    """Verify size and checksum of a finished .part download; returns sha256."""
    if size is not None and part_file.stat().st_size != size:
        raise VerificationError(
            f"size mismatch for {part_file.name}: expected {size}, got {part_file.stat().st_size}"
        )
    digest = _sha256_file(part_file)
    if sha256 and digest != sha256.lower():
        raise VerificationError(
            f"sha256 mismatch for {part_file.name}",
            hint="The download may be corrupted; retry.",
        )
    return digest


def head_info(client: httpx.Client, url: str) -> dict[str, str | None]:
    try:
        response = client.head(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise NetworkError(f"HEAD request failed for {url}: {exc}") from exc
    return {
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
        "content_length": response.headers.get("content-length"),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_content_length(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _make_progress(console: Console | None, quiet: bool, name: str):
    """Return a Progress bar, or None when output is not wanted."""
    if console is None or quiet or not console.is_terminal:
        return None
    from rich.progress import Progress

    return Progress(console=console)
