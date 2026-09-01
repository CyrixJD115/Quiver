"""AppImage file inspection: detection, architecture, embedded metadata.

Detection works purely on file bytes (no execution). Metadata extraction runs
the AppImage's own runtime with ``--appimage-extract`` in a temporary
directory, which is the standard mechanism (AppImageLauncher does the same);
it never executes the payload application.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from quiver.errors import VerificationError

ELF_MAGIC = b"\x7fELF"
APPIMAGE_MAGIC = {1: b"AI\x01", 2: b"AI\x02"}

# e_machine values from the ELF header (offset 18, little-endian u16)
ARCH_BY_MACHINE = {
    3: "i386",
    8: "mips",
    40: "arm",
    62: "x86_64",
    183: "aarch64",
    243: "riscv64",
}

ARCH_ALIASES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86-64": "x86_64",
    "arm64": "aarch64",
    "aarch_64": "aarch64",
    "x86": "i386",
    "i686": "i386",
    "riscv": "riscv64",
}

GENERIC_TOKENS = {
    "linux",
    "gnu",
    "gnulinux",
    "appimage",
    "image",
    "stable",
    "latest",
    "release",
    "final",
    "portable",
    "64bit",
    "32bit",
    "64",
    "32",
    "x86",
    "x86_64",
    "x86-64",
    "amd64",
    "x64",
    "aarch64",
    "arm64",
    "arm",
    "i386",
    "i686",
    "riscv",
    "riscv64",
    "bin",
    "binary",
    "intel",
    "macos",
    "win",
    "windows",
    "osx",
    "darwin",
    "unsigned",
    "setup",
    "install",
}


@dataclass(frozen=True)
class AppImageInfo:
    """What the file's own bytes tell us."""

    path: Path
    appimage_type: int
    arch: str | None
    size: int


@dataclass
class AppImageMeta:
    """Everything we could learn about an AppImage."""

    name: str | None = None
    version: str | None = None
    arch: str | None = None
    app_id: str | None = None
    description: str | None = None
    homepage: str | None = None
    icon_path: Path | None = None  # path inside extracted tree
    categories: list[str] = field(default_factory=list)
    exec_name: str | None = None
    desktop_file: str | None = None
    update_info: str | None = None  # raw embedded .upd_info string, if any
    github_hints: list[str] = field(default_factory=list)  # owner/repo candidates
    warnings: list[str] = field(default_factory=list)


def detect(path: Path | str) -> AppImageInfo | None:
    """Return basic byte-level info, or None if the file is not an AppImage."""
    path = Path(path)
    try:
        with path.open("rb") as fh:
            header = fh.read(20)
            size = path.stat().st_size
    except OSError:
        return None
    if len(header) < 20 or header[:4] != ELF_MAGIC:
        return None
    aimage_type = next((t for t, magic in APPIMAGE_MAGIC.items() if header[8:11] == magic), None)
    if aimage_type is None:
        return None
    machine = int.from_bytes(header[18:20], "little")
    return AppImageInfo(
        path=path, appimage_type=aimage_type, arch=ARCH_BY_MACHINE.get(machine), size=size
    )


def sha256_of(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_arch(token: str) -> str:
    return ARCH_ALIASES.get(token.lower(), token.lower())


_ARCH_TOKEN_ORDER = (
    "x86_64",
    "x86-64",
    "amd64",
    "aarch64",
    "aarch_64",
    "arm64",
    "riscv64",
    "i686",
    "i386",
    "armhf",
    "armv7",
    "x86",
    "arm",
)
# Delimited matching: "harmony" must NOT read as ARM. Most specific first so
# "x86_64" wins over the "x86" it contains.
_ARCH_STEM_PATTERNS = tuple(
    (token, re.compile(rf"(?:^|[^a-z0-9]){re.escape(token)}(?:$|[^a-z0-9])"))
    for token in _ARCH_TOKEN_ORDER
)


def _arch_from_stem(stem: str) -> str | None:
    low = stem.lower()
    for token, pattern in _ARCH_STEM_PATTERNS:
        if pattern.search(low):
            return normalize_arch(token)
    return None


_ARCH_WORD = re.compile(r"x86_64|aarch64|riscv64|i386|armhf|armv7|i686|arm|x64|amd64|x86")


def parse_filename(path: Path | str) -> dict[str, str | None]:
    """Best-effort name/version/arch from a filename. Never trusted blindly."""
    stem = Path(path).stem
    arch = _arch_from_stem(stem)
    # Split on separators but keep dots so version tokens like "1.5.0" survive.
    tokens = re.split(r"[-_ ]+", stem)
    name_parts: list[str] = []
    version: str | None = None
    for token in tokens:
        low = token.lower()
        if version is None and re.fullmatch(r"[vV]?\d+(\.\d+)+([A-Za-z]\w*)?", token):
            version = token.lstrip("vV")
            continue
        if low.isdigit() or low in {"linux", "gnu", "gnulinux", "appimage"}:
            continue
        if low in ARCH_ALIASES or _ARCH_WORD.fullmatch(low):
            continue
        if version is None:
            name_parts.append(token)
    name = " ".join(p for p in name_parts if p) or None
    return {"name": name, "version": version, "arch": arch}


def derive_alias(name: str | None, filename: Path | str | None = None) -> str:
    """Derive a CLI alias from a display name or filename, minus junk tokens."""
    source = name or (Path(filename).stem if filename else "")
    tokens = re.split(r"[^A-Za-z0-9]+", source.lower())
    keep = [t for t in tokens if t and t not in GENERIC_TOKENS and not t.isdigit()]
    alias = "-".join(keep)[:48]
    return alias or "app"


def _run_extract(appimage: Path, tmp: Path, timeout: int) -> bool:
    try:
        proc = subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=tmp,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"extraction failed to run: {exc}") from exc
    return proc.returncode == 0 and (tmp / "squashfs-root").is_dir()


def _find_icon(root: Path, icon_name: str | None) -> Path | None:
    candidates: list[Path] = []
    if icon_name:
        for ext in (".png", ".svg", ".svgz", ".xpm"):
            direct = root / f"{icon_name}{ext}"
            if direct.is_file():
                candidates.append(direct)
        for pattern in (
            f"usr/share/icons/**/*/{icon_name}.png",
            f"usr/share/icons/**/*/{icon_name}.svg",
            f"usr/share/pixmaps/{icon_name}.png",
            f"usr/share/pixmaps/{icon_name}.svg",
            f"{icon_name}.png",
            f"{icon_name}.svg",
        ):
            candidates.extend(p for p in root.glob(pattern) if p.is_file())
    diricon = root / ".DirIcon"
    if diricon.is_file():
        candidates.append(diricon)
    for cand in candidates:
        if cand.stat().st_size > 0:
            return cand
    return None


_GITHUB_RE = re.compile(
    r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/[^\s]*)?$"
)
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# --- embedded update information (.upd_info) --------------------------------
#
# Type-2 AppImages built with appimagetool usually carry their own update
# source in the ".upd_info" ELF section, e.g.:
#   gh-releases-zsync|<owner>|<repo>|<latest|tag>|<filename-pattern>
#   gh-releases|<owner>|<repo>|<tag>|<pattern>
#   zsync|https://github.com/<owner>/<repo>/releases/download/...

_UPD_INFO_MAGICS = (b"gh-releases-zsync|", b"gh-releases|", b"zsync|http")


def read_update_info(path: Path | str) -> str | None:
    """Read the embedded .upd_info string from an AppImage's ELF header."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 64 or data[:4] != ELF_MAGIC:
        return None
    try:
        import struct

        e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
        e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]
        e_shnum = struct.unpack_from("<H", data, 0x3C)[0]
        e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
        if not (e_shoff and e_shentsize and e_shnum and e_shstrndx < e_shnum):
            raise struct.error
        headers = []
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            sh_name, sh_type = struct.unpack_from("<II", data, off)
            sh_offset, sh_size = struct.unpack_from("<QQ", data, off + 24)
            headers.append((sh_name, sh_type, sh_offset, sh_size))
        _, _, str_off, str_size = headers[e_shstrndx]
        shstrtab = data[str_off : str_off + str_size]
        for sh_name, _sh_type, sh_offset, sh_size in headers:
            end = shstrtab.find(b"\0", sh_name)
            name = shstrtab[sh_name : end if end != -1 else None]
            if name == b".upd_info" and sh_size:
                raw = data[sh_offset : sh_offset + sh_size]
                return raw.split(b"\0", 1)[0].decode("utf-8", "replace") or None
    except (struct.error, IndexError, OSError):
        pass
    # Fallback: bounded scan for the magic strings some runtimes inline.
    windows = [data[: 1024 * 1024], data[-1024 * 1024 :]] if len(data) > 2 * 1024 * 1024 else [data]
    for window in windows:
        for magic in _UPD_INFO_MAGICS:
            idx = window.find(magic)
            if idx >= 0:
                chunk = window[idx : idx + 4096].split(b"\0", 1)[0]
                return chunk.decode("utf-8", "replace")
    return None


def parse_update_info(raw: str | None) -> list[str]:
    """Extract owner/repo candidates from a raw .upd_info string."""
    if not raw:
        return []
    repos: list[str] = []
    parts = raw.strip().split("|")
    if parts[0] in ("gh-releases-zsync", "gh-releases", "bintray-zsync") and len(parts) >= 3:
        repos.append(f"{parts[1]}/{parts[2]}")
    for match in _GITHUB_RE.finditer(raw):
        repos.append(f"{match.group(1)}/{match.group(2)}")
    seen: list[str] = []
    for repo in repos:
        if _REPO_RE.match(repo) and repo not in seen:
            seen.append(repo)
    return seen


def github_repo_from_app_id(app_id: str | None) -> str | None:
    """Decode a reverse-DNS app id like io.github.<owner>.<project>."""
    if not app_id:
        return None
    labels = app_id.lower().strip().split(".")
    if len(labels) >= 4 and labels[0] in ("io", "com") and labels[1] == "github":
        return f"{labels[2]}/{labels[3]}"
    return None


def hints_from_meta(meta: AppImageMeta) -> dict[str, object]:
    """Persistable discovery hints derived from extracted metadata."""
    opts: dict[str, object] = {}
    if meta.github_hints:
        opts["github_hints"] = meta.github_hints
    if meta.update_info:
        opts["update_info"] = meta.update_info
    return opts


def extract_metadata(path: Path | str, *, timeout: int = 120) -> AppImageMeta:
    """Inspect an AppImage's embedded desktop entry / AppStream metadata."""
    path = Path(path)
    info = detect(path)
    meta = AppImageMeta(arch=info.arch if info else None)
    parsed = parse_filename(path)
    meta.name = parsed["name"]
    meta.version = parsed["version"]

    if info is None:
        meta.warnings.append("file is not a recognizable AppImage (bad magic bytes)")
        return meta
    # Embedded update info needs no extraction and works even without +x.
    meta.update_info = read_update_info(path)
    for repo in parse_update_info(meta.update_info):
        if repo not in meta.github_hints:
            meta.github_hints.append(repo)
    if info.appimage_type != 2:
        meta.warnings.append(
            f"type-{info.appimage_type} AppImage: runtime extraction unsupported;"
            " filename metadata only"
        )
        return meta

    try:
        with tempfile.TemporaryDirectory(prefix="quiver-extract-") as tmp_name:
            tmp = Path(tmp_name)
            if not _run_extract(path, tmp, timeout):
                meta.warnings.append("--appimage-extract failed; using filename metadata only")
                return meta
            root = tmp / "squashfs-root"
            _merge_extracted(root, meta)
            # The temp tree dies with this context manager, so persist the icon.
            meta.icon_path = _stash_icon(meta.icon_path)
    except RuntimeError as exc:
        meta.warnings.append(str(exc))
    return meta


def _stash_icon(icon: Path | None) -> Path | None:
    """Copy an extracted icon out of the doomed temp dir into the cache."""
    if icon is None or not icon.is_file():
        return None
    from quiver import paths

    dest_dir = paths.app_cache_dir() / "icons"
    dest_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256_of(icon)[:16]
    data = icon.read_bytes()
    # .DirIcon has no suffix; sniff the format when needed
    ext = icon.suffix or (".svg" if data.lstrip()[:1] == b"<" else ".png")
    target = dest_dir / f"{digest}{ext}"
    if not target.exists():
        target.write_bytes(data)
    return target


def _merge_extracted(root: Path, meta: AppImageMeta) -> None:
    import configparser

    # Desktop entry
    desktop_files = sorted(root.glob("*.desktop")) or sorted(
        root.glob("usr/share/applications/*.desktop")
    )
    if desktop_files:
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.optionxform = str  # type: ignore[assignment,method-assign]
        try:
            parser.read(desktop_files[0], encoding="utf-8")
            if parser.has_section("Desktop Entry"):
                section = parser["Desktop Entry"]
                meta.name = section.get("Name") or meta.name
                meta.description = section.get("Comment") or meta.description
                meta.exec_name = section.get("Exec", "").split()[0] if section.get("Exec") else None
                meta.categories = [
                    c.strip() for c in (section.get("Categories") or "").split(";") if c.strip()
                ]
                meta.version = section.get("X-AppImage-Version") or meta.version
                icon_name = section.get("Icon")
                if icon_name and "/" not in icon_name:
                    meta.icon_path = _find_icon(root, icon_name)
                elif icon_name:
                    candidate = root / icon_name
                    meta.icon_path = candidate if candidate.is_file() else None
                meta.desktop_file = desktop_files[0].name
        except (configparser.Error, OSError):
            meta.warnings.append("embedded .desktop file could not be parsed")

    # AppStream metainfo
    metainfo_files = [
        *root.glob("usr/share/metainfo/*.xml"),
        *root.glob("usr/share/metainfo/*.metainfo.xml"),
        *root.glob("usr/share/appdata/*.xml"),
        *root.glob("*.metainfo.xml"),
        *root.glob("*.appdata.xml"),
    ]
    for candidate in metainfo_files:
        try:
            _merge_appstream(candidate, meta)
            break
        except ET.ParseError:
            continue

    if meta.icon_path is None:
        meta.icon_path = _find_icon(root, None)


def _merge_appstream(path: Path, meta: AppImageMeta) -> None:
    tree = ET.parse(path)
    component = tree.getroot()
    if component.tag != "component":
        component = component.find("component") or component

    def text(tag: str) -> str | None:
        node = component.find(tag)
        return node.text.strip() if node is not None and node.text and node.text.strip() else None

    meta.app_id = component.get("id") or meta.app_id
    meta.name = text("name") or meta.name
    meta.description = meta.description or text("summary")
    app_id_repo = github_repo_from_app_id(meta.app_id)
    if app_id_repo and app_id_repo not in meta.github_hints:
        meta.github_hints.append(app_id_repo)
    for url_node in component.findall("url"):
        url_type = url_node.get("type", "")
        href = (url_node.text or "").strip()
        if not href:
            continue
        if url_type == "homepage" and not meta.homepage:
            meta.homepage = href
        match = _GITHUB_RE.search(href)
        if match and url_type in {"homepage", "bugtracker", "help", "donation", "contact"}:
            repo = f"{match.group(1)}/{match.group(2)}"
            if repo not in meta.github_hints and match.group(2) not in {"apps", "topics"}:
                meta.github_hints.append(repo)
    releases = component.find("releases")
    if releases is not None:
        release = releases.find("release")
        if release is not None and release.get("version"):
            meta.version = release.get("version") or meta.version


def verify_appimage(path: Path | str, expected_arch: str | None) -> AppImageInfo:
    """Verify a downloaded file is a real AppImage and matches the architecture."""
    path = Path(path)
    info = detect(path)
    if info is None:
        raise VerificationError(f"{path.name} is not an AppImage (missing AppImage magic bytes)")
    if expected_arch and info.arch and info.arch != expected_arch:
        raise VerificationError(
            f"architecture mismatch: expected {expected_arch}, download is {info.arch}",
            hint="The upstream release may not publish a matching asset.",
        )
    return info


def has_extraction_support() -> bool:
    """Type-2 AppImages extract via their own runtime; no external tool needed."""
    return True


__all__ = [
    "AppImageInfo",
    "AppImageMeta",
    "derive_alias",
    "detect",
    "extract_metadata",
    "parse_filename",
    "sha256_of",
    "verify_appimage",
]
